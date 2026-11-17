import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMBERS_PATH = ROOT / "config" / "members.json"
DEFAULT_EXTERNAL_PATH = ROOT / "config" / "external_people.json"
DEFAULT_TITLE_RULES_PATH = ROOT / "config" / "title_rules.json"
DEFAULT_PRIVACY_PATH = ROOT / "config" / "privacy.json"
DEFAULT_PEOPLE_LEGACY_PATH = ROOT / "config" / "people.json"

DEFAULT_STRIP_TOKENS = {
    "honorifics": ["선생님", "여사님", "여사", "선생", "귀하", "님", "씨"],
    "modifiers": ["직무대행", "신임", "전", "현"],
    "titles": [
        "경영기획처장", "경영지원실장", "수석부위원장", "부위원장", "위원장",
        "사무국장", "부지부장", "지부장", "분회장", "본부장", "단장",
        "처장", "실장", "팀장", "과장", "반장", "조장",
        "조합원", "의장", "간사", "강사", "노무사", "변호사",
    ],
}

SPACED_HONORIFIC_RE = re.compile(r"(^|[\s(/,\-])([가-힣]{2,4})\s+(?:선생님|여사님|귀하|님|씨)(?=$|[^가-힣])")
EVENT_NIM_RE = re.compile(
    r"(^|[\s(/,\-])([가-힣]{2,4})님(?=\s*(?:모친상|부친상|장인상|장모상|빙모상|빙부상|시모상|시부상|조모상|조부상|결혼|백일|돌|입원|퇴직|\())"
)
NON_PERSON_WORDS = {"부모님", "어머님", "아버님", "할머님", "할아버님", "선생님", "스승님", "하느님", "하나님", "부처님"}


def load_json_if_exists(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def load_directory_bundle(config_dir: Path | None = None) -> dict:
    """Load split local dictionaries (members, external_people, title_rules) plus privacy fallback."""
    cdir = config_dir or (ROOT / "config")
    members_doc = load_json_if_exists(cdir / "members.json")
    external_doc = load_json_if_exists(cdir / "external_people.json")
    rules_doc = load_json_if_exists(cdir / "title_rules.json")
    privacy_doc = load_json_if_exists(cdir / "privacy.json")
    legacy_doc = load_json_if_exists(cdir / "people.json")

    members = list(members_doc.get("members", []))
    events = list(members_doc.get("membership_events", []))
    externals = list(external_doc.get("external_people", []))

    if not members and not externals and legacy_doc.get("people"):
        for p in legacy_doc["people"]:
            members.append({
                "person_id": p.get("id", ""),
                "name": p.get("name", ""),
                "phone": p.get("phone", ""),
                "unit_code": p.get("unit", ""),
                "status": p.get("status", "active"),
            })

    id_to_name = {}
    for m in members:
        if m.get("person_id") and m.get("name"):
            id_to_name[m["person_id"]] = m["name"]
    for e in externals:
        if e.get("person_id") and e.get("name"):
            id_to_name[e["person_id"]] = e["name"]

    return {
        "members": members,
        "membership_events": events,
        "external_people": externals,
        "title_rules": rules_doc,
        "privacy": privacy_doc,
        "id_to_name": id_to_name,
    }


def collect_person_names(bundle: dict | None = None, privacy_cfg: dict | None = None) -> list[str]:
    b = bundle or {}
    # Support legacy people_cfg dict shape gracefully if passed directly
    if "people" in b and "members" not in b:
        names = {str(p.get("name", "")).strip() for p in b.get("people", []) if str(p.get("name", "")).strip()}
    else:
        names = {
            str(p.get("name", "")).strip()
            for p in (b.get("members", []) + b.get("external_people", []))
            if str(p.get("name", "")).strip()
        }

    priv = privacy_cfg if privacy_cfg is not None else b.get("privacy", {})
    for n in (priv or {}).get("forbiddenNames", []):
        s = str(n).strip()
        if s:
            names.add(s)

    # Exclude exact alias tokens that map to another formal name unless needed for privacy scan
    return sorted(names, key=len, reverse=True)


def collect_person_phones(bundle: dict | None = None) -> list[str]:
    b = bundle or {}
    phones = set()
    for p in b.get("members", []) + b.get("external_people", []):
        ph = str(p.get("phone", "")).strip()
        if ph:
            phones.add(ph)
    return sorted(phones)


def _strip_tokens_from_bundle(bundle: dict | None) -> tuple[list[str], list[str], list[str]]:
    tokens = ((bundle or {}).get("title_rules") or {}).get("strip_tokens") or DEFAULT_STRIP_TOKENS
    honorifics = sorted({str(t).strip() for t in tokens.get("honorifics", []) if str(t).strip()}, key=len, reverse=True)
    modifiers = sorted({str(t).strip() for t in tokens.get("modifiers", []) if str(t).strip()}, key=len, reverse=True)
    titles = sorted({str(t).strip() for t in tokens.get("titles", []) if str(t).strip()}, key=len, reverse=True)
    return honorifics, modifiers, titles


def normalize_person_mentions(
    text: str,
    known_names: list[str] | set[str] | None = None,
    bundle: dict | None = None,
) -> str:
    """
    Resolve registered aliases/abbreviations to formal full names and strip all modifiers,
    titles, and honorifics attached before or after person names.
    """
    if not text or not isinstance(text, str):
        return text

    out = text
    b = bundle or {}
    id_to_name = b.get("id_to_name", {})
    rules = b.get("title_rules", {})
    honorifics, modifiers, titles = _strip_tokens_from_bundle(b)
    all_suffix_tokens = sorted(set(honorifics) | set(titles), key=len, reverse=True)
    mod_pat = "(?:" + "|".join(re.escape(m) for m in modifiers) + r")"
    title_pat = "(?:" + "|".join(re.escape(t) for t in titles) + r")"
    hon_pat = "(?:" + "|".join(re.escape(h) for h in honorifics) + r")"

    # 1. Resolve person aliases -> formal name
    aliases = sorted(rules.get("person_aliases", []), key=lambda a: len(str(a.get("alias", ""))), reverse=True)
    suffix_union = "|".join(re.escape(t) for t in all_suffix_tokens)
    for item in aliases:
        alias = str(item.get("alias", "")).strip()
        formal = id_to_name.get(item.get("person_id", ""), "")
        mode = item.get("match_mode", "exact")
        if not alias or not formal or alias == formal:
            continue
        if mode == "exact":
            if alias in out:
                out = re.sub(rf"(?<![가-힣]){re.escape(alias)}(?=$|[^가-힣]|(?:{hon_pat})(?=$|[^가-힣]))", formal, out)
        elif mode == "context_title":
            # Replace given-name abbreviation only when immediately paired with a modifier/title/honorific
            ctx_pat = re.compile(
                rf"(?<![가-힣]){re.escape(alias)}(?=(?:\s*(?:{mod_pat}\s*)?(?:{suffix_union}))(?=$|[^가-힣]))"
            )
            out = ctx_pat.sub(formal, out)

    # Collect formal registered names (do not include pure aliases that were resolved away)
    alias_only = {str(a.get("alias", "")).strip() for a in aliases}
    formal_names = [
        n for n in sorted({str(x).strip() for x in (known_names or collect_person_names(b)) if str(x).strip()}, key=len, reverse=True)
        if n not in alias_only
    ]

    # 2. Strip pre-name titles/modifiers and post-name modifiers/titles/honorifics around formal names
    if formal_names:
        joined = "|".join(re.escape(n) for n in formal_names)
        pre_unit = rf"(?:(?:{mod_pat}\s+)?{title_pat}\s+)"
        post_unit = rf"(?:\s*-\s*(?:{mod_pat}\s*)?{title_pat}|\s*(?:{mod_pat}\s*)?{title_pat}|\s*{hon_pat})"
        person_ctx_pat = re.compile(
            rf"(?<![가-힣])(?:{pre_unit})*({joined})(?:{post_unit})*(?=$|[^가-힣])"
        )
        out = person_ctx_pat.sub(r"\1", out)

    # 3. Fallback: strip generic honorifics after unregistered Hangul names ('홍길동 님' -> '홍길동')
    title_only_pat = re.compile(
        rf"((?:전\s*)?(?:{title_pat})){hon_pat}(?=$|[^가-힣])"
    )
    out = title_only_pat.sub(r"\1", out)
    out = SPACED_HONORIFIC_RE.sub(
        lambda m: m.group(0) if (m.group(2) + "님") in NON_PERSON_WORDS else f"{m.group(1)}{m.group(2)}",
        out,
    )
    out = EVENT_NIM_RE.sub(
        lambda m: m.group(0) if (m.group(2) + "님") in NON_PERSON_WORDS else f"{m.group(1)}{m.group(2)}",
        out,
    )
    return out


# Backwards-compatible alias for existing callers
def strip_person_honorifics(
    text: str,
    known_names: list[str] | set[str] | None = None,
    people_cfg: dict | None = None,
) -> str:
    bundle = people_cfg if (people_cfg and "members" in people_cfg) else load_directory_bundle()
    return normalize_person_mentions(text, known_names=known_names, bundle=bundle)


def sync_privacy_with_directory(
    privacy_path: Path = DEFAULT_PRIVACY_PATH,
    config_dir: Path | None = None,
) -> dict:
    privacy_cfg = load_json_if_exists(privacy_path)
    bundle = load_directory_bundle(config_dir or privacy_path.parent)
    if not privacy_cfg:
        return {}

    formal_names = collect_person_names(bundle, privacy_cfg)
    alias_tokens = {
        str(a.get("alias", "")).strip()
        for a in (bundle.get("title_rules") or {}).get("person_aliases", [])
        if a.get("match_mode") == "exact" and str(a.get("alias", "")).strip()
    }

    ordered = []
    seen = set()
    for n in list(privacy_cfg.get("forbiddenNames", [])) + formal_names + sorted(alias_tokens):
        if n and n not in seen:
            ordered.append(n)
            seen.add(n)
    privacy_cfg["forbiddenNames"] = ordered

    for section in ("targetMask", "exactNoteReplacements"):
        orig_map = dict(privacy_cfg.get(section, {}))
        updated_map = {}
        for k, v in orig_map.items():
            norm_k = normalize_person_mentions(k, formal_names, bundle)
            if norm_k not in updated_map:
                updated_map[norm_k] = v
            if k not in updated_map:
                updated_map[k] = v
        privacy_cfg[section] = updated_map

    privacy_path.write_text(json.dumps(privacy_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return privacy_cfg


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="인명사전·정식성명 정규화 유틸리티")
    parser.add_argument("--sync-privacy", action="store_true", help="members/external_people 기준으로 privacy.json 동기화")
    parser.add_argument("--strip", help="입력 문자열 정규화 테스트 (별칭 -> 정식성명, 수식어·직책·존칭 제거)")
    args = parser.parse_args()

    bundle = load_directory_bundle()
    names = collect_person_names(bundle)
    if args.sync_privacy:
        res = sync_privacy_with_directory()
        print(f"Synced privacy.json: forbiddenNames={len(res.get('forbiddenNames', []))}, targetMask={len(res.get('targetMask', {}))}, exactNoteReplacements={len(res.get('exactNoteReplacements', {}))}")
    if args.strip:
        print(normalize_person_mentions(args.strip, names, bundle))

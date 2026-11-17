import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PEOPLE_PATH = ROOT / "config" / "people.json"
DEFAULT_PRIVACY_PATH = ROOT / "config" / "privacy.json"

TITLE_SUFFIX_RE = re.compile(
    r"((?:전\s*)?(?:수석부위원장|부위원장|위원장|사무국장|지부장|분회장|부지부장|단장|본부장|처장|실장|팀장|조합원|의장|간사|강사|노무사|변호사))님(?=$|[^가-힣])"
)
SPACED_NIM_RE = re.compile(r"(^|[\s(/,\-])([가-힣]{2,4})\s+(?:선생님|여사님|귀하|님|씨)(?=$|[^가-힣])")
EVENT_NIM_RE = re.compile(
    r"(^|[\s(/,\-])([가-힣]{2,4})님(?=\s*(?:모친상|부친상|장인상|장모상|빙모상|빙부상|시모상|시부상|조모상|조부상|결혼|백일|돌|입원|퇴직|\())"
)
NON_PERSON_TITLES = {"부모님", "어머님", "아버님", "할머님", "할아버님", "선생님", "스승님", "하느님", "하나님", "부처님"}


def load_json_if_exists(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def load_people_cfg(people_path: Path = DEFAULT_PEOPLE_PATH) -> dict:
    return load_json_if_exists(people_path)


def collect_person_names(people_cfg: dict | None = None, privacy_cfg: dict | None = None) -> list[str]:
    names = set()
    for p in (people_cfg or {}).get("people", []):
        n = str(p.get("name", "")).strip()
        if n:
            names.add(n)
    for n in (privacy_cfg or {}).get("forbiddenNames", []):
        n = str(n).strip()
        if n:
            names.add(n)
    return sorted(names, key=len, reverse=True)


def strip_person_honorifics(
    text: str,
    known_names: list[str] | set[str] | None = None,
    people_cfg: dict | None = None,
) -> str:
    """Strip honorific suffixes (e.g., '님', '씨', '귀하', '선생님') attached to person names or roles."""
    if not text or not isinstance(text, str):
        return text

    out = text

    # 1. Normalize spaced raw roster names when explicitly registered (e.g. '홍 길 동' -> '홍길동')
    if people_cfg:
        for p in people_cfg.get("people", []):
            raw_name = str(p.get("rawName", "")).strip()
            norm_name = str(p.get("name", "")).strip()
            if raw_name and norm_name and raw_name != norm_name and raw_name in out:
                out = out.replace(raw_name, norm_name)

    # 2. Strip honorifics right after known registered names (optional role word included)
    names = sorted({str(n).strip() for n in (known_names or []) if str(n).strip()}, key=len, reverse=True)
    if names:
        joined = "|".join(re.escape(n) for n in names)
        known_pat = re.compile(
            rf"(?<![가-힣])({joined})((?:\s*(?:전\s*)?(?:수석부위원장|부위원장|위원장|사무국장|지부장|분회장|부지부장|단장|본부장|처장|실장|팀장|조합원|의장|간사|강사))?)\s*(?:선생님|여사님|귀하|님|씨)(?=$|[^가-힣])"
        )
        out = known_pat.sub(lambda m: f"{m.group(1)}{m.group(2)}", out)

    # 3. Strip '님' from personal position/title abbreviations (e.g. '박단장님' -> '박단장', '조합원님' -> '조합원')
    out = TITLE_SUFFIX_RE.sub(r"\1", out)

    # 4. Strip spaced honorifics after generic Korean names ('홍길동 님' -> '홍길동')
    out = SPACED_NIM_RE.sub(lambda m: m.group(0) if (m.group(2) + "님") in NON_PERSON_TITLES else f"{m.group(1)}{m.group(2)}", out)

    # 5. Strip compact '님' before well-known event/parenthetical markers ('홍길동님 모친상' -> '홍길동 모친상')
    out = EVENT_NIM_RE.sub(lambda m: m.group(0) if (m.group(2) + "님") in NON_PERSON_TITLES else f"{m.group(1)}{m.group(2)}", out)

    return out


def sync_privacy_with_people(
    privacy_path: Path = DEFAULT_PRIVACY_PATH,
    people_path: Path = DEFAULT_PEOPLE_PATH,
) -> dict:
    privacy_cfg = load_json_if_exists(privacy_path)
    people_cfg = load_people_cfg(people_path)
    if not privacy_cfg or not people_cfg:
        return privacy_cfg

    known_names = collect_person_names(people_cfg, privacy_cfg)
    existing_forbidden = list(privacy_cfg.get("forbiddenNames", []))
    seen = set(existing_forbidden)
    for p in people_cfg.get("people", []):
        name = str(p.get("name", "")).strip()
        if name and name not in seen:
            existing_forbidden.append(name)
            seen.add(name)
    privacy_cfg["forbiddenNames"] = existing_forbidden

    # Ensure both un-honorific (normalized) and legacy keys map cleanly in targetMask & exactNoteReplacements
    for section in ("targetMask", "exactNoteReplacements"):
        orig_map = dict(privacy_cfg.get(section, {}))
        updated_map = {}
        for k, v in orig_map.items():
            norm_k = strip_person_honorifics(k, known_names, people_cfg)
            if norm_k not in updated_map:
                updated_map[norm_k] = v
            if k not in updated_map:
                updated_map[k] = v
        privacy_cfg[section] = updated_map

    privacy_path.write_text(json.dumps(privacy_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return privacy_cfg


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="인명사전 조회 및 존칭 제거 정규화 유틸리티")
    parser.add_argument("--sync-privacy", action="store_true", help="인명사전 기준으로 privacy.json 동기화")
    parser.add_argument("--strip", help="입력 문자열에서 인명 존칭 제거 테스트")
    parser.add_argument("--lookup", help="이름 또는 소속으로 인명사전 조회")
    args = parser.parse_args()

    p_cfg = load_people_cfg()
    priv_cfg = load_json_if_exists(DEFAULT_PRIVACY_PATH)
    all_names = collect_person_names(p_cfg, priv_cfg)

    if args.sync_privacy:
        res = sync_privacy_with_people()
        print(f"Synced privacy.json: forbiddenNames={len(res.get('forbiddenNames', []))}, targetMask={len(res.get('targetMask', {}))}, exactNoteReplacements={len(res.get('exactNoteReplacements', {}))}")
    if args.strip:
        print(strip_person_honorifics(args.strip, all_names, p_cfg))
    if args.lookup:
        hits = [
            p for p in p_cfg.get("people", [])
            if args.lookup in p.get("name", "") or args.lookup in p.get("unit", "") or args.lookup in p.get("unitFull", "")
        ]
        print(json.dumps(hits, ensure_ascii=False, indent=2))

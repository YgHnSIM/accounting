import argparse
import datetime as dt
import json
import shutil
import sqlite3
from collections import Counter
from pathlib import Path

from people_utils import (
    DEFAULT_EXTERNAL_PATH,
    DEFAULT_MEMBERS_PATH,
    DEFAULT_PRIVACY_PATH,
    DEFAULT_TITLE_RULES_PATH,
    load_directory_bundle,
    load_json_if_exists,
    sync_privacy_with_directory,
)

ROOT = Path(__file__).resolve().parent.parent
UNITS_PATH = ROOT / "config" / "units.json"
COA_PATH = ROOT / "config" / "coa.json"
LEDGER_LATEST_PATH = ROOT / "data" / "latest" / "ledger.json"
DEFAULT_DB_PATH = ROOT / "data" / "local" / "accounting.db"
DEFAULT_DIR_MD = ROOT / "directory"
DEFAULT_APP_DIR = ROOT / "_raw" / "applications"

VALID_DOC_TYPES = ("가입서", "탈퇴서", "기타")
VALID_WITHDRAW_CATEGORIES = ("정년퇴직", "계약만료·퇴직", "기타")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_units_map() -> dict[str, dict]:
    units_doc = load_json_if_exists(UNITS_PATH)
    by_code = {}
    for u in units_doc.get("units", []):
        by_code[u["code"]] = u
        by_code[u["name"]] = u
    return by_code


def _resolve_unit_code(raw_unit: str, units_map: dict[str, dict]) -> str:
    key = raw_unit.strip()
    if key.upper() in units_map:
        return units_map[key.upper()]["code"]
    if key in units_map:
        return units_map[key]["code"]
    valid = sorted({u["code"] for u in units_map.values()})
    raise SystemExit(f"오류: 등록되지 않은 회계단위입니다: {raw_unit} (가능: {', '.join(valid)})")


def _normalize_withdraw_category(raw_cat: str) -> str:
    s = (raw_cat or "기타").strip()
    aliases = {
        "정년": "정년퇴직",
        "정년퇴직": "정년퇴직",
        "계약만료": "계약만료·퇴직",
        "퇴직": "계약만료·퇴직",
        "퇴사": "계약만료·퇴직",
        "계약만료퇴직": "계약만료·퇴직",
        "계약만료·퇴직": "계약만료·퇴직",
        "계약만료 or 퇴직": "계약만료·퇴직",
        "기타": "기타",
    }
    norm = aliases.get(s)
    if not norm:
        raise SystemExit(f"오류: 허용되지 않은 탈퇴 사유 분류입니다: {s} (허용: {', '.join(VALID_WITHDRAW_CATEGORIES)})")
    return norm


def _parse_doc_spec(raw_spec: str, default_type: str) -> tuple[str, str]:
    """Parse optional '유형=경로' without splitting Windows drive letters like C:\\..."""
    spec = raw_spec.strip()
    if "=" in spec:
        prefix, rest = spec.split("=", 1)
        if prefix.strip() in VALID_DOC_TYPES:
            return prefix.strip(), rest.strip()
        raise SystemExit(f"오류: 증빙 유형은 {', '.join(VALID_DOC_TYPES)} 중 하나여야 합니다: {prefix}")
    if default_type not in VALID_DOC_TYPES:
        raise SystemExit(f"오류: 증빙 유형 오류: {default_type}")
    return default_type, spec


def _archive_doc_file(src_spec: str, prefix_tag: str, event_date: str, person_id: str, name: str, seq_idx: int) -> str:
    """Resolve existing path inside repo or copy an external file into _raw/applications/."""
    DEFAULT_APP_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = Path(src_spec)
    abs_path = raw_path if raw_path.is_absolute() else (ROOT / raw_path)
    app_root = DEFAULT_APP_DIR.resolve()
    if abs_path.exists():
        resolved = abs_path.resolve()
        try:
            rel_to_app = resolved.relative_to(app_root)
            return f"_raw/applications/{rel_to_app.as_posix()}"
        except ValueError:
            ymd = event_date.replace("-", "")
            suffix = f"_{seq_idx}" if seq_idx > 1 else ""
            dest = DEFAULT_APP_DIR / f"{prefix_tag}_{ymd}_{person_id}_{name}{suffix}{resolved.suffix.lower()}"
            shutil.copy2(resolved, dest)
            return f"_raw/applications/{dest.name}"
    return src_spec.replace("\\", "/")


def _record_event_documents(
    docs_list: list[dict],
    raw_specs: list[str],
    default_type: str,
    prefix_tag: str,
    event_id: str,
    person_id: str,
    name: str,
    event_date: str,
    doc_note: str = "",
) -> list[dict]:
    added = []
    for idx, spec in enumerate(raw_specs, start=1):
        if not spec.strip():
            continue
        dtype, src = _parse_doc_spec(spec, default_type)
        stored_path = _archive_doc_file(src, prefix_tag, event_date, person_id, name, idx)
        doc_id = _next_seq_id(docs_list, "doc_id", "DOC-")
        row = {
            "doc_id": doc_id,
            "event_id": event_id,
            "person_id": person_id,
            "doc_type": dtype,
            "file_path": stored_path,
            "note": doc_note.strip(),
            "created_at": event_date,
        }
        docs_list.append(row)
        added.append(row)
    if not added and doc_note.strip():
        doc_id = _next_seq_id(docs_list, "doc_id", "DOC-")
        row = {
            "doc_id": doc_id,
            "event_id": event_id,
            "person_id": person_id,
            "doc_type": "기타",
            "file_path": "",
            "note": doc_note.strip(),
            "created_at": event_date,
        }
        docs_list.append(row)
        added.append(row)
    return added


def _next_seq_id(items: list[dict], key: str, prefix: str) -> str:
    nums = []
    for it in items:
        val = str(it.get(key, ""))
        if val.startswith(prefix) and val[len(prefix):].isdigit():
            nums.append(int(val[len(prefix):]))
    nxt = (max(nums) + 1) if nums else 1
    return f"{prefix}{nxt:04d}"


def _find_member(members: list[dict], person_id: str | None, name: str | None) -> dict:
    if person_id:
        for m in members:
            if m["person_id"] == person_id.upper().strip():
                return m
        raise SystemExit(f"오류: person_id '{person_id}'를 찾을 수 없습니다.")
    if name:
        q = name.strip()
        hits = [m for m in members if m["name"] == q]
        if not hits:
            raise SystemExit(f"오류: 조합원 '{q}'을(를) 찾을 수 없습니다.")
        if len(hits) > 1:
            ids = ", ".join(f"{h['person_id']}({h['unit_code']})" for h in hits)
            raise SystemExit(f"오류: 동명이인 '{q}'이(가) 여러 명 있습니다: {ids} — --id 로 지정하세요.")
        return hits[0]
    raise SystemExit("오류: --id 또는 --name 중 하나는 반드시 지정해야 합니다.")


def _find_rejoin_candidate(members: list[dict], name: str, birth_date: str) -> dict | None:
    if not birth_date:
        return None
    hits = [
        m for m in members
        if m.get("name") == name and m.get("birth_date") == birth_date and m.get("status") != "active"
    ]
    return hits[0] if len(hits) == 1 else None


def _apply_rejoin_to_member(
    doc: dict,
    member: dict,
    next_unit: str,
    rejoin_date: str,
    args,
    events: list[dict],
    docs_list: list[dict],
) -> tuple[dict, list[dict]]:
    pid = member["person_id"]
    prev_unit = member.get("unit_code", "")
    ev_id = _next_seq_id(events, "event_id", "EV-")
    ymd = rejoin_date.replace("-", "")
    md_rel = f"_raw/applications/JOIN_{ymd}_{pid}_{member['name']}.md"

    prior_withdraw = next(
        (ev for ev in reversed(events) if ev.get("person_id") == pid and ev.get("event_type") == "withdraw"),
        None,
    )
    default_rejoin_cat = (
        "계약만료 후 재입사"
        if prior_withdraw and prior_withdraw.get("reason_category") == "계약만료·퇴직"
        else "일반 재가입"
    )
    rejoin_cat = (getattr(args, "rejoin_category", "") or default_rejoin_cat).strip()

    if not member.get("first_joined_on"):
        member["first_joined_on"] = member.get("joined_on") or rejoin_date
    member["status"] = "active"
    member["unit_code"] = next_unit
    member["joined_on"] = rejoin_date
    member["left_on"] = ""
    if getattr(args, "birth", ""):
        member["birth_date"] = args.birth.strip()
    if getattr(args, "phone", ""):
        member["phone"] = args.phone.strip()
    if getattr(args, "email", ""):
        member["email"] = args.email.strip()
    if getattr(args, "shift", ""):
        member["shift"] = args.shift.strip()
    if getattr(args, "emp_type", ""):
        member["employment_type"] = args.emp_type.strip()
    if getattr(args, "wish", ""):
        member["member_wish"] = args.wish.strip()
    if getattr(args, "note", ""):
        member["note"] = args.note.strip()

    raw_docs = list(getattr(args, "doc", []) or [])
    added_docs = _record_event_documents(
        docs_list, raw_docs, "가입서", "JOIN", ev_id, pid, member["name"], rejoin_date,
        doc_note=getattr(args, "doc_note", "") or "",
    )
    primary_app = next((d["file_path"] for d in added_docs if d["file_path"]), "")
    if primary_app:
        member["application_doc"] = primary_app

    ev_row = {
        "event_id": ev_id,
        "person_id": pid,
        "event_type": "rejoin",
        "event_date": rejoin_date,
        "from_unit": prev_unit,
        "to_unit": next_unit,
        "reason_category": "",
        "rejoin_category": rejoin_cat,
        "reason": (getattr(args, "reason", "") or getattr(args, "note", "") or rejoin_cat).strip(),
        "doc_md_path": md_rel,
        "refund_tx_id": "",
    }
    events.append(ev_row)
    return ev_row, added_docs


def cmd_list(args):
    doc = load_json_if_exists(DEFAULT_MEMBERS_PATH)
    members = doc.get("members", [])
    units_map = _load_units_map()
    unit_filter = _resolve_unit_code(args.unit, units_map) if args.unit else None

    rows = []
    for m in members:
        if unit_filter and m.get("unit_code") != unit_filter:
            continue
        if args.status != "all" and m.get("status") != args.status:
            continue
        rows.append(m)

    print(f"{'ID':<8} {'성명':<8} {'소속':<6} {'근무':<6} {'고용':<6} {'상태':<10} {'가입/탈퇴일':<22} {'연락처'}")
    print("-" * 86)
    for m in rows:
        period = f"{m.get('joined_on') or '-'} / {m.get('left_on') or '-'}"
        print(
            f"{m['person_id']:<8} {m['name']:<8} {m.get('unit_code',''):<6} "
            f"{(m.get('shift') or '-'):<6} {(m.get('employment_type') or '-'):<6} "
            f"{m.get('status',''):<10} {period:<22} {m.get('phone') or '-'}"
        )
    print(f"\n조합원 {len(rows)}명 표시")

    if args.include_external:
        ext_doc = load_json_if_exists(DEFAULT_EXTERNAL_PATH)
        exts = ext_doc.get("external_people", [])
        print(f"\n{'ID':<8} {'성명':<8} {'소속/기관':<22} {'구분':<10} {'상태'}")
        print("-" * 64)
        for e in exts:
            print(f"{e['person_id']:<8} {e['name']:<8} {e.get('org',''):<22} {e.get('category',''):<10} {e.get('status','')}")


def cmd_summary(_args):
    m_doc = load_json_if_exists(DEFAULT_MEMBERS_PATH)
    e_doc = load_json_if_exists(DEFAULT_EXTERNAL_PATH)
    r_doc = load_json_if_exists(DEFAULT_TITLE_RULES_PATH)
    members = m_doc.get("members", [])
    externals = e_doc.get("external_people", [])
    docs_list = m_doc.get("member_documents", [])

    by_status = Counter(m.get("status", "unknown") for m in members)
    active = [m for m in members if m.get("status") == "active"]
    by_unit = Counter(m.get("unit_code", "") for m in active)
    by_shift = Counter(m.get("shift") or "미지정" for m in active)
    by_emp = Counter(m.get("employment_type") or "미지정" for m in active)

    print("=== 조합원 명부 요약 ===")
    print(f"전체 등록 조합원: {len(members)}명 (active={by_status.get('active',0)}, retired={by_status.get('retired',0)}, withdrawn={by_status.get('withdrawn',0)}, inactive={by_status.get('inactive',0)}, leave={by_status.get('leave',0)})")
    print("현직 소속별:", dict(sorted(by_unit.items())))
    print("현직 근무별:", dict(by_shift))
    print("현직 고용별:", dict(by_emp))
    print(f"외부인 인명사전: {len(externals)}명 | 보관 증빙: {len(docs_list)}건")
    print(f"이력 이벤트: {len(m_doc.get('membership_events', []))}건 | 별칭 규칙: {len(r_doc.get('person_aliases', []))}건 | 직책 규칙: {len(r_doc.get('person_roles', []))}건")


def cmd_join(args):
    doc = load_json_if_exists(DEFAULT_MEMBERS_PATH)
    members = doc.setdefault("members", [])
    events = doc.setdefault("membership_events", [])
    docs_list = doc.setdefault("member_documents", [])
    units_map = _load_units_map()
    ucode = _resolve_unit_code(args.unit, units_map)
    join_date = args.date or dt.date.today().isoformat()
    clean_name = args.name.strip()
    clean_birth = (args.birth or "").strip()

    existing_former = _find_rejoin_candidate(members, clean_name, clean_birth)
    if existing_former:
        ev_row, added_docs = _apply_rejoin_to_member(doc, existing_former, ucode, join_date, args, events, docs_list)
        _save_json(DEFAULT_MEMBERS_PATH, doc)
        sync_privacy_with_directory()
        export_directory_markdown()
        print(
            f"기존 비현역 동일인 감지 -> 재가입 처리: {existing_former['person_id']} {clean_name} "
            f"({ucode}, {join_date}, {ev_row['rejoin_category']}, 증빙 {len(added_docs)}건)"
        )
        return

    pid = _next_seq_id(members, "person_id", "M-")
    ev_id = _next_seq_id(events, "event_id", "EV-")
    ymd = join_date.replace("-", "")
    md_rel = f"_raw/applications/JOIN_{ymd}_{pid}_{clean_name}.md"

    added_docs = _record_event_documents(
        docs_list, list(args.doc or []), "가입서", "JOIN", ev_id, pid, clean_name, join_date,
        doc_note=getattr(args, "doc_note", "") or "",
    )
    primary_doc = next((d["file_path"] for d in added_docs if d["file_path"]), "")

    members.append({
        "person_id": pid,
        "name": clean_name,
        "birth_date": clean_birth,
        "phone": (args.phone or "").strip(),
        "email": (args.email or "").strip(),
        "unit_code": ucode,
        "shift": (args.shift or "").strip(),
        "employment_type": (args.emp_type or "공무직").strip(),
        "status": "active",
        "first_joined_on": join_date,
        "joined_on": join_date,
        "left_on": "",
        "member_wish": (args.wish or "").strip(),
        "application_doc": primary_doc,
        "note": (args.note or "신규 가입").strip(),
    })
    events.append({
        "event_id": ev_id,
        "person_id": pid,
        "event_type": "join",
        "event_date": join_date,
        "from_unit": "",
        "to_unit": ucode,
        "reason_category": "",
        "rejoin_category": "",
        "reason": (args.note or "조합원 가입").strip(),
        "doc_md_path": md_rel,
        "refund_tx_id": "",
    })
    _save_json(DEFAULT_MEMBERS_PATH, doc)
    sync_privacy_with_directory()
    export_directory_markdown()
    print(f"가입 처리 완료: {pid} {clean_name} ({ucode}, {join_date}, 증빙 {len(added_docs)}건) + privacy.json·directory/·_raw/applications/ 동기화됨")


def cmd_withdraw(args):
    doc = load_json_if_exists(DEFAULT_MEMBERS_PATH)
    members = doc.get("members", [])
    events = doc.setdefault("membership_events", [])
    docs_list = doc.setdefault("member_documents", [])
    m = _find_member(members, args.id, args.name)
    w_date = args.date or dt.date.today().isoformat()
    category = _normalize_withdraw_category(args.category)
    ev_id = _next_seq_id(events, "event_id", "EV-")
    ymd = w_date.replace("-", "")
    md_rel = f"_raw/applications/WITHDRAW_{ymd}_{m['person_id']}_{m['name']}.md"

    added_docs = _record_event_documents(
        docs_list, list(args.doc or []), "탈퇴서", "WITHDRAW", ev_id, m["person_id"], m["name"], w_date,
        doc_note=getattr(args, "doc_note", "") or "",
    )

    m["status"] = "withdrawn"
    m["left_on"] = w_date
    events.append({
        "event_id": ev_id,
        "person_id": m["person_id"],
        "event_type": "withdraw",
        "event_date": w_date,
        "from_unit": m.get("unit_code", ""),
        "to_unit": "",
        "reason_category": category,
        "rejoin_category": "",
        "reason": (args.reason or category).strip(),
        "doc_md_path": md_rel,
        "refund_tx_id": (args.refund_tx or "").strip(),
    })
    _save_json(DEFAULT_MEMBERS_PATH, doc)
    export_directory_markdown()
    print(f"탈퇴 처리 완료 (이력 보존): {m['person_id']} {m['name']} ({w_date}, 사유={category}, 증빙 {len(added_docs)}건)")


def cmd_rejoin(args):
    doc = load_json_if_exists(DEFAULT_MEMBERS_PATH)
    members = doc.get("members", [])
    events = doc.setdefault("membership_events", [])
    docs_list = doc.setdefault("member_documents", [])
    units_map = _load_units_map()
    m = _find_member(members, args.id, args.name)
    r_date = args.date or dt.date.today().isoformat()
    next_unit = _resolve_unit_code(args.unit, units_map) if args.unit else m.get("unit_code", "")

    ev_row, added_docs = _apply_rejoin_to_member(doc, m, next_unit, r_date, args, events, docs_list)
    _save_json(DEFAULT_MEMBERS_PATH, doc)
    sync_privacy_with_directory()
    export_directory_markdown()
    print(f"재가입 처리 완료: {m['person_id']} {m['name']} ({next_unit}, {r_date}, {ev_row['rejoin_category']}, 증빙 {len(added_docs)}건)")


def cmd_transfer(args):
    doc = load_json_if_exists(DEFAULT_MEMBERS_PATH)
    members = doc.get("members", [])
    events = doc.setdefault("membership_events", [])
    units_map = _load_units_map()
    m = _find_member(members, args.id, args.name)
    to_unit = _resolve_unit_code(args.to_unit, units_map)
    t_date = args.date or dt.date.today().isoformat()
    from_unit = m.get("unit_code", "")
    ev_id = _next_seq_id(events, "event_id", "EV-")

    m["unit_code"] = to_unit
    events.append({
        "event_id": ev_id,
        "person_id": m["person_id"],
        "event_type": "transfer",
        "event_date": t_date,
        "from_unit": from_unit,
        "to_unit": to_unit,
        "reason_category": "",
        "rejoin_category": "",
        "reason": (args.reason or "지부 이동").strip(),
        "doc_md_path": "",
        "refund_tx_id": "",
    })
    _save_json(DEFAULT_MEMBERS_PATH, doc)
    export_directory_markdown()
    print(f"소속 이동 완료: {m['person_id']} {m['name']} ({from_unit} -> {to_unit}, {t_date})")


def cmd_history(args):
    doc = load_json_if_exists(DEFAULT_MEMBERS_PATH)
    members = {m["person_id"]: m for m in doc.get("members", [])}
    events = doc.get("membership_events", [])
    target_id = None
    if args.id or args.name:
        target = _find_member(list(members.values()), args.id, args.name)
        target_id = target["person_id"]

    filtered = [ev for ev in events if not target_id or ev["person_id"] == target_id]
    for ev in filtered[-args.limit:]:
        m = members.get(ev["person_id"], {})
        move = f"{ev.get('from_unit') or '-'} -> {ev.get('to_unit') or '-'}"
        cat = ev.get("reason_category") or ev.get("rejoin_category") or ""
        cat_lbl = f"[{cat}] " if cat else ""
        print(f"{ev['event_id']} | {ev['event_date']} | {ev['person_id']} {m.get('name','')} | {ev['event_type']} | {move} | {cat_lbl}{ev.get('reason','')}")


def cmd_add_external(args):
    doc = load_json_if_exists(DEFAULT_EXTERNAL_PATH)
    exts = doc.setdefault("external_people", [])
    pid = _next_seq_id(exts, "person_id", "E-")
    exts.append({
        "person_id": pid,
        "name": args.name.strip(),
        "org": (args.org or "").strip(),
        "category": (args.category or "기타").strip(),
        "phone": (args.phone or "").strip(),
        "email": "",
        "status": "active",
        "note": (args.note or "").strip(),
    })
    _save_json(DEFAULT_EXTERNAL_PATH, doc)
    sync_privacy_with_directory()
    export_directory_markdown()
    print(f"외부인 추가 완료: {pid} {args.name.strip()} ({args.org}) + privacy.json·directory/ 동기화됨")


def _md_cell(val) -> str:
    s = str(val or "").strip()
    return s.replace("|", "\\|") if s else "-"


def _render_evidence_markdown(ev_docs: list[dict], md_parent: Path) -> list[str]:
    if not ev_docs:
        return ["*(첨부된 증빙 자료 없음 — 무증빙/구두 처리)*"]
    lines = [
        "| 문서 ID | 유형 | 파일명 | 비고 | 등록일 |",
        "| :--- | :---: | :--- | :--- | :---: |",
    ]
    previews = []
    for d in ev_docs:
        fpath = d.get("file_path", "")
        fname = Path(fpath).name if fpath else "-"
        lines.append(
            f"| `{d['doc_id']}` | `{d['doc_type']}` | {_md_cell(fname)} | {_md_cell(d.get('note'))} | {d.get('created_at','-')} |"
        )
        if fpath and Path(fpath).suffix.lower() in IMAGE_EXTS:
            abs_doc = ROOT / fpath
            if abs_doc.exists():
                rel = abs_doc.name if abs_doc.parent == md_parent else Path(fpath).as_posix()
                previews.extend(["", f"### {d['doc_type']} 원본 (`{d['doc_id']}`)", f"![{d['doc_type']} 원본]({rel})"])
    return lines + previews


def export_application_markdowns() -> list[Path]:
    """Generate per-event JOIN/WITHDRAW Markdown sheets in _raw/applications/ from members.json."""
    DEFAULT_APP_DIR.mkdir(parents=True, exist_ok=True)
    bundle = load_directory_bundle(ROOT / "config")
    units_doc = load_json_if_exists(UNITS_PATH)
    unit_info = {u["code"]: u for u in units_doc.get("units", [])}
    members_map = {m["person_id"]: m for m in bundle.get("members", [])}
    events = bundle.get("membership_events", [])
    docs_by_ev: dict[str, list[dict]] = {}
    for d in bundle.get("member_documents", []):
        docs_by_ev.setdefault(d.get("event_id", ""), []).append(d)

    written: list[Path] = []
    for ev in events:
        etype = ev.get("event_type")
        md_rel = ev.get("doc_md_path", "")
        if etype not in ("join", "rejoin", "withdraw") or not md_rel:
            continue
        m = members_map.get(ev["person_id"], {})
        ev_docs = docs_by_ev.get(ev["event_id"], [])
        out_path = ROOT / md_rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if etype in ("join", "rejoin"):
            uc = ev.get("to_unit") or m.get("unit_code", "")
            u_full = unit_info.get(uc, {}).get("fullName", uc)
            kind_title = "조합 재가입서" if etype == "rejoin" else "조합 가입서"
            wish = str(m.get("member_wish") or "").strip()
            lines = [
                f"# {kind_title} — {m.get('name', '')} (`{ev['person_id']}`)",
                "",
                "| 항목 | 내용 | 항목 | 내용 |",
                "| :--- | :--- | :--- | :--- |",
                f"| **소속 지부** | {u_full} (`{uc}`) | **생년월일** | `{_md_cell(m.get('birth_date'))}` |",
                f"| **고용 / 근무** | {_md_cell(m.get('employment_type'))} / {_md_cell(m.get('shift'))} | **제출일자** | `{ev['event_date']}` |",
                f"| **휴대전화** | {_md_cell(m.get('phone'))} | **이메일** | {_md_cell(m.get('email'))} |",
                f"| **접수 이벤트** | `{ev['event_id']}` (`{etype}`) | **최초 가입일** | `{_md_cell(m.get('first_joined_on') or m.get('joined_on'))}` |",
                "",
                "## 노동조합에 바라는 점 (기재 원문)",
                f"> {wish}" if wish else "*(기재 없음)*",
                "",
                "## 첨부 증빙 목록",
                *_render_evidence_markdown(ev_docs, out_path.parent),
                "",
            ]
        else:
            uc = ev.get("from_unit") or m.get("unit_code", "")
            u_full = unit_info.get(uc, {}).get("fullName", uc)
            refund = ev.get("refund_tx_id", "")
            lines = [
                f"# 조합 탈퇴 기록서 — {m.get('name', '')} (`{ev['person_id']}`)",
                "",
                "| 항목 | 내용 | 항목 | 내용 |",
                "| :--- | :--- | :--- | :--- |",
                f"| **소속 지부** | {u_full} (`{uc}`) | **생년월일** | `{_md_cell(m.get('birth_date'))}` |",
                f"| **고용 / 근무** | {_md_cell(m.get('employment_type'))} / {_md_cell(m.get('shift'))} | **탈퇴일자** | `{ev['event_date']}` |",
                f"| **탈퇴 사유 분류** | **{ev.get('reason_category') or '기타'}** | **이벤트 ID** | `{ev['event_id']}` |",
                f"| **조합비 환급 거래** | `{refund}` | **최초 가입일** | `{_md_cell(m.get('first_joined_on') or m.get('joined_on'))}` |"
                if refund else
                f"| **조합비 환급 거래** | - | **최초 가입일** | `{_md_cell(m.get('first_joined_on') or m.get('joined_on'))}` |",
                "",
                "## 세부 탈퇴 사유",
                f"> {ev.get('reason') or '-'}",
                "",
                "## 첨부 증빙 목록",
                *_render_evidence_markdown(ev_docs, out_path.parent),
                "",
            ]
        out_path.write_text("\n".join(lines), encoding="utf-8")
        written.append(out_path)
    return written


def export_directory_markdown(out_dir: Path = DEFAULT_DIR_MD) -> list[Path]:
    """Render readable Markdown reference files into gitignored directory/ plus application cards."""
    out_dir.mkdir(parents=True, exist_ok=True)
    app_cards = export_application_markdowns()
    bundle = load_directory_bundle(ROOT / "config")
    units_doc = load_json_if_exists(UNITS_PATH)
    unit_info = {u["code"]: u for u in units_doc.get("units", [])}

    members = bundle.get("members", [])
    events = bundle.get("membership_events", [])
    docs_list = bundle.get("member_documents", [])
    externals = bundle.get("external_people", [])
    rules = bundle.get("title_rules", {})
    id_to_name = bundle.get("id_to_name", {})

    active_members = [m for m in members if m.get("status") == "active"]
    former_members = [m for m in members if m.get("status") != "active"]
    withdraw_events = [ev for ev in events if ev.get("event_type") == "withdraw"]
    by_unit_active = Counter(m.get("unit_code", "") for m in active_members)
    by_shift_active = Counter(m.get("shift") or "미지정" for m in active_members)
    by_emp_active = Counter(m.get("employment_type") or "미지정" for m in active_members)
    by_wd_cat = Counter(ev.get("reason_category") or "기타" for ev in withdraw_events)
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    # Map latest join/withdraw doc markdown path per person
    latest_join_md: dict[str, str] = {}
    for ev in events:
        if ev.get("event_type") in ("join", "rejoin") and ev.get("doc_md_path"):
            latest_join_md[ev["person_id"]] = ev["doc_md_path"]

    # 1. directory/README.md
    unit_rows = []
    for code in ("AY", "BP", "HQ", "SS"):
        u = unit_info.get(code, {})
        cnt = by_unit_active.get(code, 0)
        tot = sum(1 for m in members if m.get("unit_code") == code)
        unit_rows.append(
            f"| `{code}` | {u.get('name', code)} | {u.get('fullName', '')} | **{cnt}명** | {tot}명 |"
        )
    shift_summary = " · ".join(f"{k} {v}명" for k, v in by_shift_active.items())
    emp_summary = " · ".join(f"{k} {v}명" for k, v in by_emp_active.items())

    readme_md = "\n".join([
        "# 인명·직책 관리 사전 안내 (로컬 전용 · Git 제외)",
        "",
        f"> 마지막 동기화: `{now_str}` · 원본: `config/members.json`, `config/external_people.json`, `config/title_rules.json`",
        "> 이 폴더(`directory/`)와 `_raw/applications/`는 `.gitignore`에 등록되어 GitHub에 올라가지 않습니다.",
        "",
        "## 문서 목록",
        "",
        "| 문서 | 내용 | 건수 |",
        "| :--- | :--- | :---: |",
        f"| [members.md](members.md) | 지부별 현직 조합원 명부 · 과거/이력 조합원 · 탈퇴 사유 집계 · 변동 로그 | {len(members)}명 |",
        f"| [external_people.md](external_people.md) | 본사·연대노조·상급단체 등 외부인 인명사전 | {len(externals)}명 |",
        f"| [title_rules.md](title_rules.md) | 정식 성명 통일 정책 · 제외 목록 · 별칭 매핑 · 직책 매칭표 | 별칭 {len(rules.get('person_aliases', []))} · 직책 {len(rules.get('person_roles', []))} |",
        f"| `_raw/applications/*.md` | 개별 가입서·탈퇴 기록서 마크다운 카드 & 원본 이미지 링크 | 서류 {len(app_cards)} · 증빙 {len(docs_list)} |",
        "",
        "## 현직 조합원 요약",
        "",
        "| 코드 | 지부 | 정식 명칭 | 현직 인원 | 누적(과거 포함) |",
        "| :--- | :--- | :--- | :---: | :---: |",
        *unit_rows,
        "",
        f"- **근무 구분 (현직 {len(active_members)}명)**: {shift_summary}",
        f"- **고용 구분 (현직 {len(active_members)}명)**: {emp_summary}",
        "",
        "## 갱신 방법",
        "",
        "```powershell",
        "# JSON 수정 또는 가입/탈퇴 명령 후 마크다운·서류 카드 일괄 재생성",
        "python scripts/manage_members.py export-md",
        "```",
        "",
    ])
    p_readme = out_dir / "README.md"
    p_readme.write_text(readme_md, encoding="utf-8")

    # 2. directory/members.md
    mem_lines = [
        "# 조합원 관리 명부",
        "",
        f"> 기준: `{now_str}` · 현직 `{len(active_members)}명` · 과거/비현역 `{len(former_members)}명` · 전체 `{len(members)}명` · 증빙 `{len(docs_list)}건`",
        "",
    ]
    for code, heading in [("AY", "안양물류센터지부 (`AY`)"), ("BP", "부평물류센터지부 (`BP`)"), ("HQ", "본부 (`HQ`)")]:
        sub = [m for m in active_members if m.get("unit_code") == code]
        if not sub:
            continue
        sub_shift = Counter(m.get("shift") or "미지정" for m in sub)
        sub_emp = Counter(m.get("employment_type") or "미지정" for m in sub)
        mem_lines.extend([
            f"## {heading} — {len(sub)}명",
            "",
            f"- **근무**: {' · '.join(f'{k} {v}' for k, v in sub_shift.items())}",
            f"- **고용**: {' · '.join(f'{k} {v}' for k, v in sub_emp.items())}",
            "",
            "| ID | 성명 | 생년월일 | 연락처 | 이메일 | 근무 | 고용 | 가입일 | 가입서 | 비고 |",
            "| :--- | :--- | :---: | :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
        ])
        for m in sub:
            j_md = latest_join_md.get(m["person_id"])
            doc_cell = f"[열람](../{j_md})" if j_md else ("보관" if m.get("application_doc") else "-")
            mem_lines.append(
                f"| `{m['person_id']}` | **{m['name']}** | {_md_cell(m.get('birth_date'))} | {_md_cell(m.get('phone'))} | {_md_cell(m.get('email'))} | {_md_cell(m.get('shift'))} | {_md_cell(m.get('employment_type'))} | {_md_cell(m.get('joined_on'))} | {doc_cell} | {_md_cell(m.get('note'))} |"
            )
        mem_lines.append("")

    wish_members = [m for m in members if str(m.get("member_wish") or "").strip()]
    if wish_members:
        mem_lines.extend([
            f"## 노동조합에 바라는 점 (가입서 기재 원문 · {len(wish_members)}건)",
            "",
            "| ID | 성명 | 소속 | 가입일 | 바라는 점 | 가입서 문서 |",
            "| :--- | :--- | :---: | :---: | :--- | :--- |",
        ])
        for m in wish_members:
            j_md = latest_join_md.get(m["person_id"])
            doc_link = f"[{Path(j_md).name}](../{j_md})" if j_md else f"`{_md_cell(m.get('application_doc'))}`"
            mem_lines.append(
                f"| `{m['person_id']}` | **{m['name']}** | {m.get('unit_code','')} | {_md_cell(m.get('joined_on'))} | {_md_cell(m.get('member_wish'))} | {doc_link} |"
            )
        mem_lines.append("")

    if withdraw_events:
        wd_summary = " · ".join(f"{c} {by_wd_cat.get(c, 0)}건" for c in VALID_WITHDRAW_CATEGORIES)
        mem_lines.extend([
            f"## 탈퇴 현황 및 사유 집계 ({len(withdraw_events)}건)",
            "",
            f"- **사유 분류**: {wd_summary}",
            "",
            "| 이벤트 ID | 탈퇴일 | 대상 | 소속 | 사유 분류 | 세부 사유 | 환급 거래 | 기록서 |",
            "| :--- | :---: | :--- | :---: | :---: | :--- | :---: | :--- |",
        ])
        for ev in reversed(withdraw_events):
            pname = id_to_name.get(ev["person_id"], "")
            w_md = ev.get("doc_md_path", "")
            w_link = f"[열람](../{w_md})" if w_md else "-"
            mem_lines.append(
                f"| `{ev['event_id']}` | {ev['event_date']} | `{ev['person_id']}` {pname} | `{ev.get('from_unit') or '-'}` | `{ev.get('reason_category') or '기타'}` | {_md_cell(ev.get('reason'))} | {_md_cell(ev.get('refund_tx_id'))} | {w_link} |"
            )
        mem_lines.append("")

    if former_members:
        mem_lines.extend([
            f"## 과거·비현역 조합원 ({len(former_members)}명)",
            "",
            "| ID | 성명 | 소속 | 상태 | 최초가입일 | 탈퇴/종료일 | 비고 |",
            "| :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
        ])
        for m in former_members:
            uc = m.get("unit_code") or ""
            uname = unit_info.get(uc, {}).get("name", uc)
            first_j = m.get("first_joined_on") or m.get("joined_on")
            mem_lines.append(
                f"| `{m['person_id']}` | **{m['name']}** | {uname} (`{uc}`) | {m.get('status')} | {_md_cell(first_j)} | {_md_cell(m.get('left_on'))} | {_md_cell(m.get('note'))} |"
            )
        mem_lines.append("")

    mem_lines.extend([
        f"## 변동 이력 로그 (최근 {min(len(events), 50)}건)",
        "",
        "| 이벤트 ID | 일자 | 대상 | 구분 | 이동 | 사유 분류 | 사유/비고 |",
        "| :--- | :---: | :--- | :--- | :---: | :---: | :--- |",
    ])
    for ev in reversed(events[-50:]):
        pname = id_to_name.get(ev["person_id"], "")
        move = f"{ev.get('from_unit') or '-'} → {ev.get('to_unit') or '-'}"
        cat = ev.get("reason_category") or ev.get("rejoin_category") or "-"
        mem_lines.append(
            f"| `{ev['event_id']}` | {ev['event_date']} | `{ev['person_id']}` {pname} | `{ev['event_type']}` | {move} | {cat} | {_md_cell(ev.get('reason'))} |"
        )
    mem_lines.append("")
    p_members = out_dir / "members.md"
    p_members.write_text("\n".join(mem_lines), encoding="utf-8")

    # 3. directory/external_people.md
    ext_lines = [
        "# 외부인 인명사전",
        "",
        f"> 기준: `{now_str}` · 본사·연대노조·상급단체 등 비조합원 `{len(externals)}명` (정식 성명만 원장에 표기)",
        "",
        "| ID | 성명 | 소속/기관 | 구분 | 연락처 | 상태 | 비고 |",
        "| :--- | :--- | :--- | :---: | :--- | :---: | :--- |",
    ]
    for e in externals:
        ext_lines.append(
            f"| `{e['person_id']}` | **{e['name']}** | {_md_cell(e.get('org'))} | {_md_cell(e.get('category'))} | {_md_cell(e.get('phone'))} | {e.get('status')} | {_md_cell(e.get('note'))} |"
        )
    ext_lines.append("")
    p_ext = out_dir / "external_people.md"
    p_ext.write_text("\n".join(ext_lines), encoding="utf-8")

    # 4. directory/title_rules.md
    tokens = rules.get("strip_tokens", {})
    aliases = rules.get("person_aliases", [])
    roles = rules.get("person_roles", [])
    rule_lines = [
        "# 직책 · 별칭 · 제외 목록 관리 사전",
        "",
        f"> 기준: `{now_str}` · 현재 표시 모드: **`{rules.get('display_mode', 'name_only')}`** (원장·보고서는 정식 성명만 유지)",
        "",
        "## 1. 제외 목록 (이름 앞·뒤 결합 시 자동 제거)",
        "",
        f"- **존칭**: {', '.join(f'`{t}`' for t in tokens.get('honorifics', []))}",
        f"- **수식어**: {', '.join(f'`{t}`' for t in tokens.get('modifiers', []))}",
        f"- **직책·호칭**: {', '.join(f'`{t}`' for t in tokens.get('titles', []))}",
        "",
        f"## 2. 별칭 → 정식 성명 매핑 ({len(aliases)}건)",
        "",
        "| 별칭/약칭 표기 | 정식 성명 (`person_id`) | 매칭 방식 | 비고 |",
        "| :--- | :--- | :---: | :--- |",
    ]
    for a in aliases:
        formal = id_to_name.get(a["person_id"], "")
        rule_lines.append(
            f"| `{a['alias']}` | **{formal}** (`{a['person_id']}`) | `{a.get('match_mode', 'exact')}` | {_md_cell(a.get('note'))} |"
        )
    rule_lines.extend([
        "",
        f"## 3. 인물별 직책 매칭표 ({len(roles)}건 — 향후 출력 확장용 보관)",
        "",
        "| 규칙 ID | 성명 (`person_id`) | 소속/기관 | 직책 | 적용 시작 | 종료 | 비고 |",
        "| :--- | :--- | :--- | :--- | :---: | :---: | :---: |",
    ])
    for r in roles:
        formal = id_to_name.get(r["person_id"], "")
        primary_note = "주 직책" if r.get("is_primary", True) else "겸직"
        rule_lines.append(
            f"| `{r['role_id']}` | **{formal}** (`{r['person_id']}`) | {_md_cell(r.get('org'))} | {r['title']} | {_md_cell(r.get('valid_from'))} | {_md_cell(r.get('valid_to'))} | {primary_note} |"
        )
    rule_lines.append("")
    p_rules = out_dir / "title_rules.md"
    p_rules.write_text("\n".join(rule_lines), encoding="utf-8")

    return [p_readme, p_members, p_ext, p_rules] + app_cards


def cmd_export_md(args):
    files = export_directory_markdown(Path(args.dir))
    dir_cnt = sum(1 for p in files if p.parent.resolve() == Path(args.dir).resolve())
    app_cnt = len(files) - dir_cnt
    print(f"마크다운 생성 완료: directory/ {dir_cnt}개 + _raw/applications/ 서류 카드 {app_cnt}개")


def cmd_sync_privacy(_args):
    res = sync_privacy_with_directory(DEFAULT_PRIVACY_PATH, ROOT / "config")
    print(f"privacy.json 동기화 완료: forbiddenNames={len(res.get('forbiddenNames', []))}명")


def cmd_export_sqlite(args):
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    bundle = load_directory_bundle(ROOT / "config")
    units_doc = load_json_if_exists(UNITS_PATH)
    coa_doc = load_json_if_exists(COA_PATH)
    ledger_rows = json.loads(LEDGER_LATEST_PATH.read_text(encoding="utf-8")) if LEDGER_LATEST_PATH.exists() else []
    rules = bundle.get("title_rules", {})

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(
            """
            CREATE TABLE units (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                full_name TEXT NOT NULL,
                status TEXT NOT NULL,
                opened_on TEXT,
                closed_on TEXT,
                ledger_sheet TEXT,
                raw_dir TEXT,
                note TEXT
            );
            CREATE TABLE accounts (
                category TEXT NOT NULL,
                gwan TEXT NOT NULL,
                hang TEXT NOT NULL,
                mok TEXT NOT NULL,
                note TEXT,
                PRIMARY KEY (category, gwan, hang, mok)
            );
            CREATE TABLE members (
                person_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                birth_date TEXT,
                phone TEXT,
                email TEXT,
                unit_code TEXT REFERENCES units(code),
                shift TEXT,
                employment_type TEXT,
                status TEXT NOT NULL,
                first_joined_on TEXT,
                joined_on TEXT,
                left_on TEXT,
                member_wish TEXT,
                application_doc TEXT,
                note TEXT
            );
            CREATE TABLE membership_events (
                event_id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL REFERENCES members(person_id),
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL,
                from_unit TEXT,
                to_unit TEXT,
                reason_category TEXT CHECK(reason_category IN ('정년퇴직', '계약만료·퇴직', '기타', '')),
                rejoin_category TEXT,
                reason TEXT,
                doc_md_path TEXT,
                refund_tx_id TEXT
            );
            CREATE TABLE member_documents (
                doc_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL REFERENCES membership_events(event_id),
                person_id TEXT NOT NULL REFERENCES members(person_id),
                doc_type TEXT NOT NULL CHECK(doc_type IN ('가입서', '탈퇴서', '기타')),
                file_path TEXT,
                note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE external_people (
                person_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                org TEXT,
                category TEXT,
                phone TEXT,
                email TEXT,
                status TEXT NOT NULL,
                note TEXT
            );
            CREATE TABLE person_aliases (
                alias TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                match_mode TEXT NOT NULL,
                note TEXT
            );
            CREATE TABLE person_roles (
                role_id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                org TEXT,
                title TEXT NOT NULL,
                valid_from TEXT,
                valid_to TEXT,
                is_primary INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE ledger_entries (
                tx_id TEXT PRIMARY KEY,
                unit_name TEXT NOT NULL,
                year INTEGER NOT NULL,
                ym TEXT NOT NULL,
                date TEXT NOT NULL,
                gubun TEXT NOT NULL,
                gwan TEXT NOT NULL,
                hang TEXT NOT NULL,
                mok TEXT NOT NULL,
                exp_type TEXT,
                fund TEXT,
                target TEXT,
                attr_ym TEXT,
                inc INTEGER NOT NULL DEFAULT 0,
                exp INTEGER NOT NULL DEFAULT 0,
                unit_bal INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                memo TEXT
            );
            CREATE TABLE ledger_person_links (
                tx_id TEXT NOT NULL REFERENCES ledger_entries(tx_id),
                person_id TEXT NOT NULL,
                person_kind TEXT NOT NULL,
                match_field TEXT NOT NULL,
                PRIMARY KEY (tx_id, person_id)
            );
            """
        )

        conn.executemany(
            "INSERT INTO units VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (u["code"], u["name"], u["fullName"], u["status"], u.get("openedOn"), u.get("closedOn"), u.get("ledgerSheet"), u.get("rawDir"), u.get("note", ""))
                for u in units_doc.get("units", [])
            ],
        )
        conn.executemany(
            "INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
            [
                (a["category"], a["gwan"], a["hang"], a["mok"], a.get("note", ""))
                for a in coa_doc.get("accounts", [])
            ],
        )
        conn.executemany(
            "INSERT INTO members VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (m["person_id"], m["name"], m.get("birth_date", ""), m.get("phone", ""), m.get("email", ""), m.get("unit_code"), m.get("shift", ""), m.get("employment_type", ""), m["status"], m.get("first_joined_on", m.get("joined_on", "")), m.get("joined_on", ""), m.get("left_on", ""), m.get("member_wish", ""), m.get("application_doc", ""), m.get("note", ""))
                for m in bundle.get("members", [])
            ],
        )
        conn.executemany(
            "INSERT INTO membership_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (ev["event_id"], ev["person_id"], ev["event_type"], ev["event_date"], ev.get("from_unit", ""), ev.get("to_unit", ""), ev.get("reason_category", ""), ev.get("rejoin_category", ""), ev.get("reason", ""), ev.get("doc_md_path", ""), ev.get("refund_tx_id", ""))
                for ev in bundle.get("membership_events", [])
            ],
        )
        conn.executemany(
            "INSERT INTO member_documents VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (d["doc_id"], d["event_id"], d["person_id"], d["doc_type"], d.get("file_path", ""), d.get("note", ""), d.get("created_at", ""))
                for d in bundle.get("member_documents", [])
            ],
        )
        conn.executemany(
            "INSERT INTO external_people VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (e["person_id"], e["name"], e.get("org", ""), e.get("category", ""), e.get("phone", ""), e.get("email", ""), e["status"], e.get("note", ""))
                for e in bundle.get("external_people", [])
            ],
        )
        conn.executemany(
            "INSERT INTO person_aliases VALUES (?, ?, ?, ?)",
            [
                (a["alias"], a["person_id"], a.get("match_mode", "exact"), a.get("note", ""))
                for a in rules.get("person_aliases", [])
            ],
        )
        conn.executemany(
            "INSERT INTO person_roles VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (r["role_id"], r["person_id"], r.get("org", ""), r["title"], r.get("valid_from"), r.get("valid_to"), 1 if r.get("is_primary", True) else 0)
                for r in rules.get("person_roles", [])
            ],
        )
        conn.executemany(
            "INSERT INTO ledger_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (r["tx_id"], r["unit"], r["year"], r["ym"], r["date"], r["gubun"], r["gwan"], r["hang"], r["mok"], r.get("exp_type", ""), r.get("fund", ""), r.get("target", ""), r.get("attr_ym", ""), r.get("inc", 0), r.get("exp", 0), r.get("unit_bal", 0), r.get("note", ""), r.get("memo", ""))
                for r in ledger_rows
            ],
        )

        all_people = [("member", m) for m in bundle.get("members", [])] + [("external", e) for e in bundle.get("external_people", [])]
        links = []
        for r in ledger_rows:
            t_txt = r.get("target", "")
            n_txt = r.get("note", "")
            for kind, person in all_people:
                pname = person["name"]
                if pname in t_txt:
                    links.append((r["tx_id"], person["person_id"], kind, "target"))
                elif pname in n_txt:
                    links.append((r["tx_id"], person["person_id"], kind, "note"))
        conn.executemany("INSERT OR IGNORE INTO ledger_person_links VALUES (?, ?, ?, ?)", links)
        conn.commit()

        counts = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("units", "accounts", "members", "membership_events", "member_documents", "external_people", "person_aliases", "person_roles", "ledger_entries", "ledger_person_links")
        }
        print(f"SQLite 내보내기 완료: {db_path}")
        print("테이블별 행 수:", counts)
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser(description="조합원 명부·증빙서류·외부인 사전 관리 및 SQLite 내보내기 도구")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_ls = sub.add_parser("list", help="조합원(및 외부인) 목록 조회")
    p_ls.add_argument("--unit", help="회계단위 필터 (HQ, AY, BP, SS 또는 본부, 안물, 부평물, 서물)")
    p_ls.add_argument("--status", default="active", help="상태 필터 (active, retired, withdrawn, inactive, all)")
    p_ls.add_argument("--include-external", action="store_true", help="외부인 인명사전 함께 표시")

    sub.add_parser("summary", help="조합원/외부인/규칙/증빙 요약 통계")

    p_join = sub.add_parser("join", help="신규 가입(또는 생년월일 일치 시 자동 재가입) 처리")
    p_join.add_argument("--name", required=True)
    p_join.add_argument("--unit", required=True)
    p_join.add_argument("--birth", default="", help="생년월일 앞 6자리 (YYMMDD)")
    p_join.add_argument("--phone", default="")
    p_join.add_argument("--email", default="")
    p_join.add_argument("--shift", default="")
    p_join.add_argument("--emp-type", default="공무직")
    p_join.add_argument("--date", default="")
    p_join.add_argument("--wish", default="", help="노동조합에 바라는 점")
    p_join.add_argument("--doc", action="append", default=[], help="증빙 경로 (반복 가능, '유형=경로' 형식 지원: 가입서/탈퇴서/기타)")
    p_join.add_argument("--doc-note", default="", help="무증빙/기타 증빙 메모")
    p_join.add_argument("--rejoin-category", default="", help="재가입 유형 구분")
    p_join.add_argument("--note", default="")

    p_wd = sub.add_parser("withdraw", help="조합원 탈퇴 처리 (무증빙·다중증빙·3종 사유 지원)")
    p_wd.add_argument("--id")
    p_wd.add_argument("--name")
    p_wd.add_argument("--category", default="기타", help="탈퇴 사유 분류: 정년퇴직 / 계약만료·퇴직 / 기타")
    p_wd.add_argument("--reason", default="", help="세부 탈퇴 사유")
    p_wd.add_argument("--date", default="")
    p_wd.add_argument("--refund-tx", default="", help="조합비 환급 거래번호 (예: HQ-2026-...)")
    p_wd.add_argument("--doc", action="append", default=[], help="증빙 파일 경로 (0건 이상, '탈퇴서=경로' 또는 '기타=경로')")
    p_wd.add_argument("--doc-note", default="", help="증빙 메모 (무증빙/구두 확인 등)")

    p_rj = sub.add_parser("rejoin", help="탈퇴/계약만료/휴직 조합원 재입사·재가입 처리")
    p_rj.add_argument("--id")
    p_rj.add_argument("--name")
    p_rj.add_argument("--unit", default="")
    p_rj.add_argument("--birth", default="")
    p_rj.add_argument("--phone", default="")
    p_rj.add_argument("--email", default="")
    p_rj.add_argument("--shift", default="")
    p_rj.add_argument("--emp-type", default="")
    p_rj.add_argument("--wish", default="")
    p_rj.add_argument("--date", default="")
    p_rj.add_argument("--rejoin-category", default="")
    p_rj.add_argument("--reason", default="")
    p_rj.add_argument("--doc", action="append", default=[], help="증빙 파일 경로 ('가입서=경로' 또는 '기타=경로')")
    p_rj.add_argument("--doc-note", default="")
    p_rj.add_argument("--note", default="")

    p_tr = sub.add_parser("transfer", help="조합원 지부 이동 처리")
    p_tr.add_argument("--id")
    p_tr.add_argument("--name")
    p_tr.add_argument("--to-unit", required=True)
    p_tr.add_argument("--date", default="")
    p_tr.add_argument("--reason", default="")

    p_hs = sub.add_parser("history", help="가입·탈퇴·재가입·이동 이력 조회")
    p_hs.add_argument("--id")
    p_hs.add_argument("--name")
    p_hs.add_argument("--limit", type=int, default=30)

    p_ext = sub.add_parser("add-external", help="외부인 인명사전 항목 추가")
    p_ext.add_argument("--name", required=True)
    p_ext.add_argument("--org", default="")
    p_ext.add_argument("--category", default="연대노조")
    p_ext.add_argument("--phone", default="")
    p_ext.add_argument("--note", default="")

    sub.add_parser("sync-privacy", help="members/external_people 기준으로 privacy.json 동기화")

    p_md = sub.add_parser("export-md", help="directory/*.md 및 _raw/applications/*.md 서류 카드 일괄 생성")
    p_md.add_argument("--dir", default=str(DEFAULT_DIR_MD))

    p_db = sub.add_parser("export-sqlite", help="SQLite 로컬 DB 생성/동기화")
    p_db.add_argument("--db", default=str(DEFAULT_DB_PATH))

    args = p.parse_args()
    handlers = {
        "list": cmd_list,
        "summary": cmd_summary,
        "join": cmd_join,
        "withdraw": cmd_withdraw,
        "rejoin": cmd_rejoin,
        "transfer": cmd_transfer,
        "history": cmd_history,
        "add-external": cmd_add_external,
        "sync-privacy": cmd_sync_privacy,
        "export-md": cmd_export_md,
        "export-sqlite": cmd_export_sqlite,
    }
    handlers[args.cmd](args)


if __name__ == "__main__":
    main()

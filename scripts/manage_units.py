import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNITS_PATH = ROOT / "config" / "units.json"


def load_registry():
    return json.loads(UNITS_PATH.read_text(encoding="utf-8"))


def save_registry(data):
    UNITS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_list(args):
    reg = load_registry()
    print(f"{'코드':<6} {'약칭':<8} {'상태':<8} {'기간':<18} {'원본폴더':<12} {'정식명칭'}")
    print("-" * 80)
    for u in reg["units"]:
        period = f"{u['openedOn']} ~ {u['closedOn'] or '현재'}"
        print(f"{u['code']:<6} {u['name']:<8} {u['status']:<8} {period:<18} {u['rawDir']:<12} {u['fullName']}")


def cmd_add(args):
    code = args.code.upper().strip()
    reg = load_registry()
    if any(u["code"] == code for u in reg["units"]):
        raise SystemExit(f"오류: 이미 존재하는 단위코드입니다: {code}")
    raw_dir = ROOT / "_raw" / code
    raw_dir.mkdir(parents=True, exist_ok=True)
    readme = raw_dir / "README.txt"
    if not readme.exists():
        readme.write_text(
            f"[{code}] {args.full_name} ({args.name}) 원본 PDF 보관 폴더\n파일명 규칙: {code}_YYYYMM.pdf\n",
            encoding="utf-8",
        )
    reg["units"].append({
        "code": code,
        "name": args.name,
        "fullName": args.full_name,
        "status": "active",
        "openedOn": args.opened,
        "closedOn": None,
        "ledgerSheet": f"원장_{args.name}",
        "rawDir": f"_raw/{code}",
        "note": args.note or "",
    })
    save_registry(reg)
    print(f"추가 완료: {code} ({args.name}) -> _raw/{code}/ 폴더 생성됨")
    print(f"안내: Google Sheet에도 '원장_{args.name}' 탭과 '계정과목표' 레지스트리를 추가하고 통합원장 QUERY 범위에 포함하세요.")


def cmd_close(args):
    code = args.code.upper().strip()
    reg = load_registry()
    for u in reg["units"]:
        if u["code"] == code:
            u["status"] = "closed"
            u["closedOn"] = args.closed
            if args.note:
                u["note"] = (u["note"] + "; " if u["note"] else "") + args.note
            save_registry(reg)
            print(f"폐지 처리 완료: {code} ({u['name']}) closedOn={args.closed} (기존 파일/원장은 보존됨)")
            return
    raise SystemExit(f"오류: 존재하지 않는 단위코드입니다: {code}")


def main():
    p = argparse.ArgumentParser(description="회계단위(지부) 신설·폐지 관리 도구")
    sub = p.add_subparsers(dest="cmd", required=True)

    s_list = sub.add_parser("list", help="등록된 회계단위 목록 조회")
    s_list.set_defaults(func=cmd_list)

    s_add = sub.add_parser("add", help="신규 지부/회계단위 등록 및 _raw 폴더 생성")
    s_add.add_argument("--code", required=True, help="영문 2~4자 고정 코드 (예: DS)")
    s_add.add_argument("--name", required=True, help="시트에서 쓰는 약칭 (예: 동서울)")
    s_add.add_argument("--full-name", required=True, help="정식 명칭 (예: 동서울물류센터지부)")
    s_add.add_argument("--opened", required=True, help="개시 연월 YYYY-MM")
    s_add.add_argument("--note", default="", help="비고")
    s_add.set_defaults(func=cmd_add)

    s_close = sub.add_parser("close", help="지부 폐지 처리 (삭제하지 않고 closed로 전환)")
    s_close.add_argument("--code", required=True, help="단위 코드 (예: SS)")
    s_close.add_argument("--closed", required=True, help="폐지 연월 YYYY-MM")
    s_close.add_argument("--note", default="", help="폐지/잔여금 처리 메모")
    s_close.set_defaults(func=cmd_close)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

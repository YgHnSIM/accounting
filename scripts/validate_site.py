import json
import re
from collections import defaultdict
from pathlib import Path

from people_utils import collect_person_names, load_directory_bundle

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_PUBLIC = ROOT / "data" / "public"
SITE_DIR = ROOT / "_site"


def main():
    priv_path = CONFIG_DIR / "privacy.json"
    privacy_cfg = json.loads(priv_path.read_text(encoding="utf-8")) if priv_path.exists() else {}
    bundle = load_directory_bundle(CONFIG_DIR)
    coa_cfg = json.loads((CONFIG_DIR / "coa.json").read_text(encoding="utf-8"))
    forbidden = collect_person_names(bundle, privacy_cfg)
    forbidden_emails = {
        str(p.get("email", "")).strip()
        for p in bundle.get("members", []) + bundle.get("external_people", [])
        if str(p.get("email", "")).strip()
    }
    phone_re = re.compile(r"01[016789]-?\d{3,4}-?\d{4}")
    personal_email_re = re.compile(r"[A-Za-z0-9._%+-]+@(?:naver\.com|gmail\.com|hanmail\.net|daum\.net|kakao\.com|nate\.com)\b", re.I)
    generic_name_re = re.compile(r"[가-힣]{2,4}(?:님|팀장|조합원|위원장|사무국장)\s*(?:모친상|부친상|장인상|빙모상|빙부상|시모상)")

    pub_path = DATA_PUBLIC / "ledger_public.json"
    if not pub_path.exists():
        raise SystemExit(f"FAIL: missing {pub_path}")
    payload = json.loads(pub_path.read_text(encoding="utf-8"))
    records = payload["records"]

    # 1. Verify accounting math & COA
    valid_coa = {
        ("내부이전" if a["category"] == "내부이전" else a["category"], a["gwan"], a["hang"], a["mok"])
        for a in coa_cfg["accounts"]
    }
    bal = defaultdict(int)
    for r in records:
        cat = "내부이전" if r["gubun"].startswith("내부이전") else r["gubun"]
        assert (cat, r["gwan"], r["hang"], r["mok"]) in valid_coa, f"Invalid COA: {r}"
        bal[r["unit"]] += r["inc"] - r["exp"]
        assert bal[r["unit"]] == r["unit_bal"], f"Balance mismatch at {r['tx_id']}"

    # 2. Scan data/public and _site for forbidden names or Excel formula errors
    text_exts = {".html", ".json", ".js", ".css"}
    scanned = 0
    for base in (DATA_PUBLIC, SITE_DIR):
        for fp in base.rglob("*"):
            if fp.is_file() and fp.suffix.lower() in text_exts and "vendor" not in fp.parts:
                txt = fp.read_text(encoding="utf-8")
                scanned += 1
                for name in forbidden:
                    if name in txt:
                        raise SystemExit(f"PRIVACY FAIL: '{name}' found in {fp}")
                m_phone = phone_re.search(txt)
                if m_phone:
                    raise SystemExit(f"PRIVACY FAIL (phone): '{m_phone.group(0)}' found in {fp}")
                for em in forbidden_emails:
                    if em in txt:
                        raise SystemExit(f"PRIVACY FAIL (email): '{em}' found in {fp}")
                m_email = personal_email_re.search(txt)
                if m_email:
                    raise SystemExit(f"PRIVACY FAIL (email pattern): '{m_email.group(0)}' found in {fp}")
                if fp.suffix.lower() in (".json", ".js", ".html"):
                    m_priv = generic_name_re.search(txt)
                    if m_priv:
                        raise SystemExit(f"PRIVACY FAIL (generic pattern): '{m_priv.group(0)}' found in {fp}")
                for err_tok in ("#REF!", "#NAME?", "#VALUE!", "#N/A"):
                    if err_tok in txt:
                        raise SystemExit(f"FORMULA ERROR: '{err_tok}' found in {fp}")

    # 3. Validate all HTML local links, assets, and mobile viewport meta
    link_re = re.compile(r"""(?:href|src)=["']([^"'#?]+)["']""")
    html_files = list(SITE_DIR.rglob("*.html"))
    assert html_files, "No HTML files built in _site"
    for hf in html_files:
        txt = hf.read_text(encoding="utf-8")
        assert '<meta name="viewport"' in txt, f"Missing viewport meta in {hf}"
        for target in link_re.findall(txt):
            if target.startswith(("http://", "https://", "mailto:", "data:")):
                continue
            resolved = (hf.parent / target).resolve()
            assert resolved.exists(), f"BROKEN LINK in {hf}: {target} -> {resolved}"

    print(f"VALIDATION PASSED! records={len(records)}, balances={dict(bal)}, html={len(html_files)}, scanned_files={scanned}, privacy=CLEAN")


if __name__ == "__main__":
    main()

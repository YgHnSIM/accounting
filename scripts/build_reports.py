import argparse
import csv
import datetime as dt
import html
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import openpyxl

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_LATEST = ROOT / "data" / "latest"
REPORTS_MONTHLY = ROOT / "reports" / "monthly"
REPORTS_ANNUAL = ROOT / "reports" / "annual"
REPORTS_CHARTS = ROOT / "reports" / "charts"

# Configure Korean font cleanly for Windows matplotlib
plt.rcParams["font.family"] = ["NanumGothic", "Malgun Gothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

PALETTE = ["#1F4E78", "#2E75B6", "#4472C4", "#548235", "#BF9000", "#C55A11", "#843C0C", "#7030A0"]


def fmt_won(val):
    if val is None or val == "":
        return "-"
    return f"{int(round(val)):,}"


def norm_ym(v):
    if v is None or v == "":
        return ""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m")
    s = str(v).strip()
    if len(s) >= 7 and s[4] == "-":
        return s[:7]
    return s


def norm_date(v):
    if v is None or v == "":
        return ""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    return s[:10] if len(s) >= 10 else s


def norm_int(v):
    if v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return int(round(v))
    s = str(v).replace(",", "").strip()
    return int(float(s)) if s else 0


def load_xlsx_to_records(xlsx_path: Path):
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    sheet_exports = ["통합원장", "원장_본부", "원장_안물", "원장_부평물", "계정과목표"]
    for sname in sheet_exports:
        if sname not in wb.sheetnames:
            continue
        ws = wb[sname]
        csv_path = DATA_LATEST / f"{sname}.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as fp:
            w = csv.writer(fp)
            for row in ws.iter_rows(values_only=True):
                if any(c is not None and str(c).strip() != "" for c in row):
                    cleaned = []
                    for ci, c in enumerate(row):
                        if isinstance(c, (dt.datetime, dt.date)):
                            # Heuristic: col D(3) & M(12) are YYYY-MM, col E(4) is YYYY-MM-DD
                            if sname != "계정과목표" and ci in (3, 12):
                                cleaned.append(c.strftime("%Y-%m"))
                            else:
                                cleaned.append(c.strftime("%Y-%m-%d"))
                        else:
                            cleaned.append("" if c is None else c)
                    w.writerow(cleaned)

    ws = wb["통합원장"]
    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h or "").strip() for h in next(rows_iter)]
    records = []
    for row in rows_iter:
        if not row or not row[0]:
            continue
        tx_id = str(row[0]).strip()
        if tx_id.startswith("#"):
            raise RuntimeError(f"통합원장 수식 오류 감지: {tx_id}")
        rec = {
            "tx_id": tx_id,
            "unit": str(row[1] or "").strip(),
            "year": norm_int(row[2]),
            "ym": norm_ym(row[3]),
            "date": norm_date(row[4]),
            "gubun": str(row[5] or "").strip(),
            "gwan": str(row[6] or "").strip(),
            "hang": str(row[7] or "").strip(),
            "mok": str(row[8] or "").strip(),
            "exp_type": str(row[9] or "").strip(),
            "fund": str(row[10] or "일반회계").strip(),
            "target": str(row[11] or "").strip(),
            "attr_ym": norm_ym(row[12]),
            "inc": norm_int(row[13]),
            "exp": norm_int(row[14]),
            "unit_bal": norm_int(row[15]),
            "note": str(row[16] or "").strip(),
            "memo": str(row[17] or "").strip(),
        }
        records.append(rec)
    return headers, records


def verify_records(records, coa_cfg):
    valid_coa = {
        ("내부이전" if a["category"] == "내부이전" else a["category"], a["gwan"], a["hang"], a["mok"])
        for a in coa_cfg["accounts"]
    }
    valid_exp_types = set(coa_cfg["expenseTypes"])
    errors = []
    unit_running = defaultdict(int)
    for r in records:
        cat_key = "내부이전" if r["gubun"].startswith("내부이전") else r["gubun"]
        if (cat_key, r["gwan"], r["hang"], r["mok"]) not in valid_coa:
            errors.append(f"미등록 계정: {r['tx_id']} -> {(cat_key, r['gwan'], r['hang'], r['mok'])}")
        if r["exp_type"] and r["exp_type"] not in valid_exp_types:
            errors.append(f"미등록 지출형태: {r['tx_id']} -> {r['exp_type']}")
        unit_running[r["unit"]] += r["inc"] - r["exp"]
        if r["unit_bal"] and unit_running[r["unit"]] != r["unit_bal"]:
            errors.append(f"누적잔액 불일치: {r['tx_id']} 계산={unit_running[r['unit']]} vs 시트={r['unit_bal']}")
    return errors, dict(unit_running)


def summarize_period(recs):
    op = sum(r["inc"] for r in recs if r["gubun"] == "기초이월")
    inc = sum(r["inc"] for r in recs if r["gubun"] == "수입")
    exp = sum(r["exp"] for r in recs if r["gubun"] == "지출")
    tr_in = sum(r["inc"] for r in recs if r["gubun"] == "내부이전(전입)")
    tr_out = sum(r["exp"] for r in recs if r["gubun"] == "내부이전(전출)")
    adj = sum(r["inc"] - r["exp"] for r in recs if r["gubun"] == "이월차액")
    return {
        "op": op,
        "inc": inc,
        "exp": exp,
        "tr_in": tr_in,
        "tr_out": tr_out,
        "tr_net": tr_in - tr_out,
        "adj": adj,
        "net": inc - exp + (tr_in - tr_out) + adj,
        "hq_inc": inc + tr_in,
        "hq_exp": exp + tr_out,
    }


BASE_CSS = """
  * { box-sizing: border-box; }
  body { font-family: 'Malgun Gothic', 'NanumGothic', sans-serif; color: #1f2937; margin: 0; padding: clamp(8px, 2vw, 24px); background: #f8fafc; line-height: 1.5; }
  .page { max-width: 1080px; margin: 0 auto; background: #fff; padding: clamp(16px, 3vw, 34px); border-radius: 10px; box-shadow: 0 2px 12px rgba(15,23,42,0.06); container-type: inline-size; }
  header { border-bottom: 3px solid #1F4E78; padding-bottom: 14px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; }
  h1 { font-size: clamp(1.15rem, 0.95rem + 1.1vw, 1.45rem); color: #1F4E78; margin: 0 0 4px 0; line-height: 1.3; }
  .subtitle { font-size: clamp(0.75rem, 0.7rem + 0.25vw, 0.85rem); color: #475569; margin: 0; }
  .meta { text-align: right; font-size: 0.75rem; color: #64748b; flex-shrink: 0; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.7rem; font-weight: 700; background: #dcfce7; color: #166534; margin-bottom: 4px; }
  h2 { font-size: clamp(0.95rem, 0.88rem + 0.4vw, 1.05rem); color: #1F4E78; margin: 24px 0 10px 0; border-left: 4px solid #2E75B6; padding-left: 10px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin-bottom: 18px; }
  .kpi { background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 8px; padding: 11px 13px; min-width: 0; }
  .kpi .label { font-size: 0.75rem; color: #475569; margin-bottom: 3px; }
  .kpi .value { font-size: clamp(1rem, 0.9rem + 0.6vw, 1.15rem); font-weight: 700; color: #0f172a; word-break: keep-all; }
  .kpi .sub { font-size: 0.7rem; color: #64748b; margin-top: 2px; }

  .table-wrapper { overflow: auto; max-inline-size: 100%; max-block-size: min(560px, 75dvh); container-type: inline-size; margin-bottom: 14px; border-radius: 6px; }
  .table-wrapper:focus-visible { outline: 2px solid #2E75B6; outline-offset: 2px; }
  table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.78rem; }
  th, td { border-right: 1px solid #cbd5e1; border-bottom: 1px solid #cbd5e1; padding: 6px 8px; }
  tr > *:first-child { border-left: 1px solid #cbd5e1; }
  thead tr:first-child > th { border-top: 1px solid #1F4E78; }
  thead { position: sticky; inset-block-start: 0; z-index: 2; }
  thead th { background: #1F4E78; color: #fff; font-weight: 600; text-align: center; white-space: nowrap; }
  tbody th { position: sticky; inset-inline-start: 0; z-index: 1; background: #fff; font-weight: 600; text-align: center; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  td.ctr { text-align: center; }
  tr.subtot td, tr.subtot th { background: #eff6ff; font-weight: 700; }
  tr.tot td, tr.tot th { background: #e2e8f0; font-weight: 700; }
  tr.muted td, tr.muted th { color: #64748b; background: #fff7ed; }

  .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 16px; }
  .chart-card { border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; background: #fff; break-inside: avoid; }
  .chart-card.full { grid-column: 1 / -1; }
  .chart-card img { width: 100%; height: auto; display: block; aspect-ratio: auto; }
  .note-box { background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 12px 14px; font-size: 0.8rem; }
  .note-box ul { margin: 4px 0 0 18px; padding: 0; }

  @container (width < 680px) {
    header { flex-direction: column; align-items: flex-start; }
    .meta { text-align: left; }
    .chart-grid { grid-template-columns: 1fr; }
    .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @container (width < 380px) {
    .kpi-grid { grid-template-columns: 1fr; }
  }

  @media screen {
    .table-wrapper {
      /* Enable stacked cards when table container is narrow on mobile */
    }
    @container (width < 620px) {
      .table-wrapper { max-block-size: none; overflow: visible; }
      table, thead, tbody, tr, th, td { display: block; }
      thead { display: none; }
      tr { margin-block-end: 12px; border: 1px solid #cbd5e1; border-radius: 8px; overflow: hidden; background: #fff; box-shadow: 0 1px 3px rgba(15,23,42,0.04); }
      tr > *:first-child { border-left: none; }
      th, td { border-right: none; border-bottom: 1px solid #e2e8f0; padding: 7px 10px; }
      tr > *:last-child { border-bottom: none; }
      tbody th { position: sticky; inset-block-start: 0; z-index: 2; background: #1F4E78; color: #fff; text-align: left; font-size: 0.82rem; }
      tr.subtot th, tr.tot th { background: #334155; color: #fff; }
      td { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; text-align: right; white-space: normal; }
      td::before { content: attr(data-label); font-weight: 600; color: #475569; text-align: left; flex-shrink: 0; }
      td.empty-cell { display: none; }
    }
  }

  @media print {
    body { background: #fff; padding: 0; }
    .page { box-shadow: none; padding: 0; max-width: none; container-type: normal; }
    .table-wrapper { max-block-size: none; overflow: visible; container-type: normal; }
    table { display: table; }
    thead { display: table-header-group; }
    tbody { display: table-row-group; }
    tr { display: table-row; }
    th, td, td.empty-cell { display: table-cell; }
    table, .chart-card, .kpi-grid { break-inside: avoid; }
    @page { size: A4; margin: 12mm; }
  }
"""


def build_monthly_report(records, target_ym: str, units_cfg):
    all_yms = sorted({r["ym"] for r in records if r["ym"]})
    if target_ym not in all_yms:
        raise SystemExit(f"오류: 원장에 {target_ym} 데이터가 없습니다. (가능 범위: {all_yms[0]} ~ {all_yms[-1]})")

    # Opening balance before target_ym across all records
    prior = [r for r in records if r["ym"] < target_ym]
    prior_bal = sum(r["inc"] - r["exp"] for r in prior)
    curr = [r for r in records if r["ym"] == target_ym]
    curr_sum = summarize_period(curr)
    end_bal = prior_bal + curr_sum["op"] + curr_sum["net"]

    idx_ym = all_yms.index(target_ym)
    recent_yms = all_yms[max(0, idx_ym - 5):idx_ym + 1]

    # Prev month comparison
    prev_ym = all_yms[idx_ym - 1] if idx_ym > 0 else None
    prev_sum = summarize_period([r for r in records if r["ym"] == prev_ym]) if prev_ym else None

    # Group curr by (gubun, gwan, hang, mok)
    act_agg = defaultdict(lambda: [0, 0, 0])
    for r in curr:
        if r["gubun"] in ("기초이월",):
            continue
        k = (r["gubun"], r["gwan"], r["hang"], r["mok"])
        act_agg[k][0] += 1
        act_agg[k][1] += r["inc"]
        act_agg[k][2] += r["exp"]

    # Build recent 6 months table
    recent_rows_html = []
    run_b = sum(r["inc"] - r["exp"] for r in records if r["ym"] < recent_yms[0])
    for ym in recent_yms:
        m_recs = [r for r in records if r["ym"] == ym]
        ms = summarize_period(m_recs)
        op_m = run_b + ms["op"]
        end_m = op_m + ms["net"]
        run_b = end_m
        cls = ' class="subtot"' if ym == target_ym else ""
        recent_rows_html.append(
            f"<tr{cls}><th scope='row'>{ym}</th>"
            f"<td class='num' data-label='기초잔액'>{fmt_won(op_m)}</td>"
            f"<td class='num' data-label='외부 순수입'>{fmt_won(ms['inc'])}</td>"
            f"<td class='num' data-label='외부 순지출'>{fmt_won(ms['exp'])}</td>"
            f"<td class='num' data-label='내부이전(순)'>{fmt_won(ms['tr_net'])}</td>"
            f"<td class='num' data-label='이월차액'>{fmt_won(ms['adj'])}</td>"
            f"<td class='num' data-label='기말잔액'>{fmt_won(end_m)}</td></tr>"
        )

    # Act summary rows
    act_rows_html = []
    for (gb, gw, ha, mo), (cnt, iv, ev) in sorted(act_agg.items()):
        cls_iv = "num" if iv else "num empty-cell"
        cls_ev = "num" if ev else "num empty-cell"
        act_rows_html.append(
            f"<tr><th scope='row'>{html.escape(mo)}</th>"
            f"<td class='ctr' data-label='구분'>{html.escape(gb)}</td>"
            f"<td data-label='관(대분류)'>{html.escape(gw)}</td>"
            f"<td data-label='항(중분류)'>{html.escape(ha)}</td>"
            f"<td class='ctr' data-label='건수'>{cnt}</td>"
            f"<td class='{cls_iv}' data-label='수입금액'>{fmt_won(iv) if iv else ''}</td>"
            f"<td class='{cls_ev}' data-label='지출금액'>{fmt_won(ev) if ev else ''}</td></tr>"
        )

    # Transaction detail rows
    tx_rows_html = []
    for r in curr:
        cls = ' class="muted"' if r["gubun"] == "이월차액" else ""
        attr_txt = f"{r['target']}{(' ('+r['attr_ym']+')') if r['attr_ym'] else ''}"
        et_cls = "ctr" if r["exp_type"] else "ctr empty-cell"
        iv_cls = "num" if r["inc"] else "num empty-cell"
        ev_cls = "num" if r["exp"] else "num empty-cell"
        note_cls = "" if r["note"] else "empty-cell"
        tx_rows_html.append(
            f"<tr{cls}><th scope='row'>{html.escape(r['date'])} · {html.escape(r['mok'])}</th>"
            f"<td class='ctr' data-label='회계단위'>{html.escape(r['unit'])}</td>"
            f"<td class='ctr' data-label='구분'>{html.escape(r['gubun'])}</td>"
            f"<td data-label='계정(관·항·목)'>{html.escape(r['gwan'])} &gt; {html.escape(r['hang'])} &gt; <b>{html.escape(r['mok'])}</b></td>"
            f"<td class='{et_cls}' data-label='지출형태'>{html.escape(r['exp_type'])}</td>"
            f"<td class='ctr' data-label='대상·귀속'>{html.escape(attr_txt)}</td>"
            f"<td class='{iv_cls}' data-label='수입'>{fmt_won(r['inc']) if r['inc'] else ''}</td>"
            f"<td class='{ev_cls}' data-label='지출'>{fmt_won(r['exp']) if r['exp'] else ''}</td>"
            f"<td class='num' data-label='단위잔액'>{fmt_won(r['unit_bal'])}</td>"
            f"<td class='{note_cls}' data-label='적요(비고)'>{html.escape(r['note'])}</td></tr>"
        )

    # Special notes / alerts for target_ym
    alerts = [r for r in curr if r["gubun"] == "이월차액" or ("오기" in r["memo"]) or ("누락" in r["memo"]) or ("확인" in r["memo"])]
    dues_gong = sum(r["inc"] for r in curr if r["mok"] == "공무직 조합비")
    dues_gigan = sum(r["inc"] for r in curr if r["mok"] == "기간제 조합비")
    grant_out = sum(r["exp"] for r in curr if r["mok"] == "지부 교부금")

    alert_items = [
        f"<li>당월 조합비 입금: 공무직 <b>{fmt_won(dues_gong)}원</b>, 기간제 <b>{fmt_won(dues_gigan)}원</b> / 지부 교부금 전출: <b>{fmt_won(grant_out)}원</b></li>"
    ]
    for a in alerts:
        alert_items.append(f"<li>[{html.escape(a['date'])}] {html.escape(a['mok'])} — {html.escape(a['memo'])}</li>")

    prev_txt = f"전월({prev_ym}) 대비 순수입 {curr_sum['inc'] - prev_sum['inc']:+,}원 / 순지출 {curr_sum['exp'] - prev_sum['exp']:+,}원" if prev_sum else "최초 기준월"
    y_num, m_num = target_ym.split("-")
    title = f"{y_num}년 {int(m_num)}월 정기 운영위원회 재정보고"

    doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{BASE_CSS}</style>
</head>
<body>
<div class="page">
  <header>
    <div>
      <h1>{title}</h1>
      <p class="subtitle">우체국물류지원단 물류노동조합 · 내부 회의용(원본 적요 포함) · 단위: 원</p>
    </div>
    <div class="meta">
      <span class="badge">원장 검증 완료</span><br>
      보고 기준월: {target_ym}<br>
      생성일시: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
  </header>

  <div class="kpi-grid">
    <div class="kpi"><div class="label">기초(이월) 잔액</div><div class="value">{fmt_won(prior_bal + curr_sum['op'])}원</div><div class="sub">전월 마감 승계</div></div>
    <div class="kpi"><div class="label">당월 외부 순수입</div><div class="value">{fmt_won(curr_sum['inc'])}원</div><div class="sub">조합비·기부·기타수입</div></div>
    <div class="kpi"><div class="label">당월 외부 순지출</div><div class="value">{fmt_won(curr_sum['exp'])}원</div><div class="sub">교부금 제외 실제 지출</div></div>
    <div class="kpi"><div class="label">내부이전 (전입-전출)</div><div class="value">{curr_sum['tr_net']:+,}원</div><div class="sub">전출 {fmt_won(curr_sum['tr_out'])}원</div></div>
    <div class="kpi"><div class="label">당월 기말잔액</div><div class="value">{fmt_won(end_bal)}원</div><div class="sub">{prev_txt}</div></div>
  </div>

  <h2 id="sec-trend">1. 최근 6개월 수지 추이 요약</h2>
  <div tabindex="0" role="region" aria-labelledby="sec-trend" class="table-wrapper">
    <table>
      <thead><tr><th>보고월</th><th>기초잔액</th><th>외부 순수입</th><th>외부 순지출</th><th>내부이전(순)</th><th>이월차액</th><th>기말잔액</th></tr></thead>
      <tbody>{''.join(recent_rows_html)}</tbody>
    </table>
  </div>

  <h2 id="sec-act">2. 당월 활동별(관·항·목) 집계</h2>
  <div tabindex="0" role="region" aria-labelledby="sec-act" class="table-wrapper">
    <table>
      <thead><tr><th>목(활동)</th><th>구분</th><th>관(대분류)</th><th>항(중분류)</th><th>건수</th><th>수입금액</th><th>지출금액</th></tr></thead>
      <tbody>
        {''.join(act_rows_html)}
        <tr class="tot"><th scope="row">당월 합계</th><td class="ctr empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="ctr" data-label="총 건수">{len(curr)}</td><td class="num" data-label="총 수입금액">{fmt_won(sum(r['inc'] for r in curr))}</td><td class="num" data-label="총 지출금액">{fmt_won(sum(r['exp'] for r in curr))}</td></tr>
      </tbody>
    </table>
  </div>

  <h2 id="sec-tx">3. 당월 세부 거래 내역 ({len(curr)}건)</h2>
  <div tabindex="0" role="region" aria-labelledby="sec-tx" class="table-wrapper">
    <table>
      <thead><tr><th>일자 · 활동</th><th>단위</th><th>구분</th><th>계정과목 (관 &gt; 항 &gt; 목)</th><th>지출형태</th><th>대상·귀속</th><th>수입</th><th>지출</th><th>단위잔액</th><th>적요(비고)</th></tr></thead>
      <tbody>{''.join(tx_rows_html)}</tbody>
    </table>
  </div>

  <h2>4. 조합비·교부금 및 회계 특이사항</h2>
  <div class="note-box"><ul>{''.join(alert_items)}</ul></div>
</div>
</body>
</html>"""
    out = REPORTS_MONTHLY / f"{target_ym}_운영위보고.html"
    out.write_text(doc, encoding="utf-8")
    return out


def generate_annual_charts(records, target_year: int):
    y_recs = [r for r in records if r["year"] == target_year]
    months = sorted({r["ym"] for r in y_recs})
    chart_paths = {}

    # 1. Monthly Income vs Expense & Ending Balance
    m_inc, m_exp, m_end = [], [], []
    run_b = sum(r["inc"] - r["exp"] for r in records if r["year"] < target_year)
    for ym in months:
        mr = [r for r in y_recs if r["ym"] == ym]
        s = summarize_period(mr)
        run_b += s["op"] + s["net"]
        m_inc.append(s["inc"] / 10000.0)
        m_exp.append(s["exp"] / 10000.0)
        m_end.append(run_b / 10000.0)

    fig, ax1 = plt.subplots(figsize=(10, 4.4), dpi=200)
    x = list(range(len(months)))
    w = 0.36
    ax1.bar([i - w / 2 for i in x], m_inc, width=w, label="외부 순수입", color="#2E75B6")
    ax1.bar([i + w / 2 for i in x], m_exp, width=w, label="외부 순지출", color="#C55A11")
    ax1.set_ylabel("월간 수지 (만원)")
    ax1.set_ylim(0, max(m_inc + m_exp + [10]) * 1.15)
    ax1.set_xticks(x)
    ax1.set_xticklabels([m[5:] + "월" for m in months])
    ax1.grid(axis="y", linestyle="--", alpha=0.4)
    ax2 = ax1.twinx()
    ax2.plot(x, m_end, color="#1F4E78", marker="o", linewidth=2.2, label="기말 통장잔액")
    ax2.set_ylabel("기말 잔액 (만원)")
    ax2.set_ylim(0, max(m_end + [10]) * 1.18)
    for i, v in enumerate(m_end):
        ax2.annotate(f"{v:,.0f}", (i, v), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=8, color="#1F4E78")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3, frameon=True)
    ax1.set_title(f"{target_year}년 월별 외부 수지 및 기말 잔액 추이 (단위: 만원)", fontsize=12, fontweight="bold", pad=30)
    fig.tight_layout()
    p1 = REPORTS_CHARTS / f"{target_year}_01_월별수지_잔액추이.png"
    fig.savefig(p1)
    plt.close(fig)
    chart_paths["monthly"] = p1

    # 2. Gwan (대분류) spending share
    gwan_agg = defaultdict(int)
    for r in y_recs:
        if r["gubun"] == "지출":
            gwan_agg[r["gwan"]] += r["exp"]
    g_items = sorted(gwan_agg.items(), key=lambda kv: kv[1], reverse=True)
    tot_exp = sum(v for _, v in g_items) or 1

    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
    labels = [k for k, _ in reversed(g_items)]
    vals = [v / 10000.0 for _, v in reversed(g_items)]
    bars = ax.barh(labels, vals, color=PALETTE[:len(labels)][::-1])
    for bar, v in zip(bars, vals):
        pct = (v * 10000.0) / tot_exp * 100
        ax.text(v + max(vals) * 0.02, bar.get_y() + bar.get_height() / 2, f"{v:,.1f}만원 ({pct:.1f}%)", va="center", fontsize=9)
    ax.set_xlim(0, max(vals) * 1.33 if vals else 10)
    ax.set_xlabel("지출액 (만원)")
    ax.set_title(f"{target_year}년 관(대분류)별 외부 순지출 비중", fontsize=11.5, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    fig.tight_layout()
    p2 = REPORTS_CHARTS / f"{target_year}_02_관별지출비중.png"
    fig.savefig(p2)
    plt.close(fig)
    chart_paths["gwan"] = p2

    # 3. Top 10 Activities (목)
    mok_agg = defaultdict(int)
    for r in y_recs:
        if r["gubun"] == "지출":
            mok_agg[f"{r['mok']} ({r['gwan']})"] += r["exp"]
    top_m = sorted(mok_agg.items(), key=lambda kv: kv[1], reverse=True)[:10]

    fig, ax = plt.subplots(figsize=(6.8, 4.5), dpi=200)
    labels = [k for k, _ in reversed(top_m)]
    vals = [v / 10000.0 for _, v in reversed(top_m)]
    bars = ax.barh(labels, vals, color="#2E75B6")
    for bar, v in zip(bars, vals):
        ax.text(v + max(vals) * 0.02, bar.get_y() + bar.get_height() / 2, f"{v:,.1f}만원", va="center", fontsize=8.5)
    ax.set_xlim(0, max(vals) * 1.24 if vals else 10)
    ax.set_xlabel("지출액 (만원)")
    ax.set_title(f"{target_year}년 주요 활동(목)별 지출 TOP 10", fontsize=11.5, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    fig.tight_layout()
    p3 = REPORTS_CHARTS / f"{target_year}_03_활동별TOP10.png"
    fig.savefig(p3)
    plt.close(fig)
    chart_paths["mok"] = p3

    # 4. Expense Type (지출형태)
    et_agg = defaultdict(int)
    for r in y_recs:
        if r["gubun"] == "지출" and r["exp_type"]:
            et_agg[r["exp_type"]] += r["exp"]
    et_items = sorted(et_agg.items(), key=lambda kv: kv[1], reverse=True)

    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
    labels = [k for k, _ in reversed(et_items)]
    vals = [v / 10000.0 for _, v in reversed(et_items)]
    bars = ax.barh(labels, vals, color="#548235")
    for bar, v in zip(bars, vals):
        pct = (v * 10000.0) / tot_exp * 100
        ax.text(v + max(vals) * 0.02, bar.get_y() + bar.get_height() / 2, f"{v:,.1f}만원 ({pct:.1f}%)", va="center", fontsize=8.5)
    ax.set_xlim(0, max(vals) * 1.32 if vals else 10)
    ax.set_xlabel("지출액 (만원)")
    ax.set_title(f"{target_year}년 지출형태별 집행 현황", fontsize=11.5, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    fig.tight_layout()
    p4 = REPORTS_CHARTS / f"{target_year}_04_지출형태비중.png"
    fig.savefig(p4)
    plt.close(fig)
    chart_paths["exp_type"] = p4

    # 5. Multi-year Dues vs Grants vs External Expense trend
    all_years = sorted({r["year"] for r in records if r["year"] <= target_year})
    if len(all_years) == 1:
        all_years = sorted({r["year"] for r in records})
    dues_g, dues_p, grants_y, ext_exp_y = [], [], [], []
    for y in all_years:
        yr_r = [r for r in records if r["year"] == y]
        dues_g.append(sum(r["inc"] for r in yr_r if r["mok"] == "공무직 조합비") / 10000.0)
        dues_p.append(sum(r["inc"] for r in yr_r if r["mok"] == "기간제 조합비") / 10000.0)
        grants_y.append(sum(r["exp"] for r in yr_r if r["mok"] == "지부 교부금") / 10000.0)
        ext_exp_y.append(sum(r["exp"] for r in yr_r if r["gubun"] == "지출") / 10000.0)

    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=200)
    x = list(range(len(all_years)))
    w = 0.25
    ax.bar([i - w for i in x], [g + p for g, p in zip(dues_g, dues_p)], width=w, label="정기조합비 합계", color="#1F4E78")
    ax.bar(x, ext_exp_y, width=w, label="외부 순지출", color="#C55A11")
    ax.bar([i + w for i in x], grants_y, width=w, label="지부 교부금(내부이전)", color="#BF9000")
    for i in x:
        ax.text(i - w, dues_g[i] + dues_p[i] + 25, f"{dues_g[i]+dues_p[i]:,.0f}", ha="center", fontsize=8.5)
        ax.text(i, ext_exp_y[i] + 25, f"{ext_exp_y[i]:,.0f}", ha="center", fontsize=8.5)
        ax.text(i + w, grants_y[i] + 25, f"{grants_y[i]:,.0f}", ha="center", fontsize=8.5)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{y}년" + ("(1~9월)" if y == 2026 else "") for y in all_years])
    ax.set_ylabel("금액 (만원)")
    ax.set_ylim(0, max([g + p for g, p in zip(dues_g, dues_p)] + ext_exp_y + [100]) * 1.15)
    ax.legend(loc="upper right", ncol=3)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_title("연도별 정기조합비 · 외부 순지출 · 지부 교부금 비교 (단위: 만원)", fontsize=11.5, fontweight="bold")
    fig.tight_layout()
    p5 = REPORTS_CHARTS / f"{target_year}_05_연도별_조합비_교부금추이.png"
    fig.savefig(p5)
    plt.close(fig)
    chart_paths["multiyear"] = p5

    return chart_paths


def build_annual_report(records, target_year: int, coa_cfg):
    y_recs = [r for r in records if r["year"] == target_year]
    if not y_recs:
        raise SystemExit(f"오류: {target_year}년도 원장 데이터가 없습니다.")

    prior_bal = sum(r["inc"] - r["exp"] for r in records if r["year"] < target_year)
    curr_sum = summarize_period(y_recs)
    op_bal = prior_bal + curr_sum["op"]
    end_bal = op_bal + curr_sum["net"]

    prev_year = target_year - 1
    prev_recs = [r for r in records if r["year"] == prev_year]
    prev_sum = summarize_period(prev_recs) if prev_recs else None

    chart_paths = generate_annual_charts(records, target_year)

    # 3-level COA table (curr vs prev year)
    coa_rows_html = []
    tot_inc = curr_sum["inc"] or 1
    tot_exp = curr_sum["exp"] or 1
    for acc in coa_cfg["accounts"]:
        cat, gw, ha, mo = acc["category"], acc["gwan"], acc["hang"], acc["mok"]
        if cat in ("기초이월", "이월차액"):
            continue
        if cat == "내부이전":
            cur_v = sum((r["exp"] if "전출" in r["gubun"] else r["inc"]) for r in y_recs if r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            prv_v = sum((r["exp"] if "전출" in r["gubun"] else r["inc"]) for r in prev_recs if r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            cnt = sum(1 for r in y_recs if r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            pct_s = "-"
            cat_disp = "내부이전"
        else:
            field = "inc" if cat == "수입" else "exp"
            cur_v = sum(r[field] for r in y_recs if r["gubun"] == cat and r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            prv_v = sum(r[field] for r in prev_recs if r["gubun"] == cat and r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            cnt = sum(1 for r in y_recs if r["gubun"] == cat and r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            denom = tot_inc if cat == "수입" else tot_exp
            pct_s = f"{cur_v / denom * 100:.1f}%"
            cat_disp = cat
        if cur_v == 0 and prv_v == 0:
            continue
        diff_v = cur_v - prv_v
        coa_rows_html.append(
            f"<tr><th scope='row'>{html.escape(mo)}</th>"
            f"<td class='ctr' data-label='구분'>{cat_disp}</td>"
            f"<td data-label='관(대분류)'>{html.escape(gw)}</td>"
            f"<td data-label='항(중분류)'>{html.escape(ha)}</td>"
            f"<td class='ctr' data-label='건수'>{cnt}</td>"
            f"<td class='num' data-label='{prev_year}년'>{fmt_won(prv_v) if prev_recs else '-'}</td>"
            f"<td class='num' data-label='{target_year}년'><b>{fmt_won(cur_v)}</b></td>"
            f"<td class='num' data-label='전년 대비 증감'>{f'{diff_v:+,}' if prev_recs else '-'}</td>"
            f"<td class='num' data-label='비중'>{pct_s}</td></tr>"
        )

    # Fund breakdown
    fund_rows = []
    for f_name in coa_cfg["fundTypes"]:
        fr = [r for r in y_recs if r["fund"] == f_name]
        fs = summarize_period(fr)
        fund_rows.append(
            f"<tr><th scope='row'>{html.escape(f_name)}</th>"
            f"<td class='num' data-label='외부 순수입'>{fmt_won(fs['inc'])}</td>"
            f"<td class='num' data-label='외부 순지출'>{fmt_won(fs['exp'])}</td>"
            f"<td class='num' data-label='내부이전(순)'>{fmt_won(fs['tr_net'])}</td>"
            f"<td class='num' data-label='재원 수지차'>{fs['inc'] - fs['exp']:+,}</td></tr>"
        )

    # Audit notes
    adj_rows = [r for r in y_recs if r["gubun"] == "이월차액" or ("결산표" in r["memo"]) or ("오기" in r["memo"])]
    audit_items = [
        f"<li><b>[{html.escape(r['date'])}] {html.escape(r['mok'])}</b>: {html.escape(r['note'])} ({html.escape(r['memo'])})</li>"
        for r in adj_rows
    ]
    if not audit_items:
        audit_items.append("<li>해당 연도 원장 검수 특이사항 없음 (월별 잔액 100% 일치)</li>")

    months_covered = sorted({r["ym"] for r in y_recs})
    period_label = f"{months_covered[0]} ~ {months_covered[-1]}"
    title = f"{target_year}년 정기 대의원대회 결산 보고서"

    doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{BASE_CSS}</style>
</head>
<body>
<div class="page">
  <header>
    <div>
      <h1>{title}</h1>
      <p class="subtitle">우체국물류지원단 물류노동조합 · 3단계 활동 결산 및 시각화 보고 · 단위: 원</p>
    </div>
    <div class="meta">
      <span class="badge">결산 검증 완료</span><br>
      대상 기간: {period_label}<br>
      생성일시: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
  </header>

  <div class="kpi-grid">
    <div class="kpi"><div class="label">기초 잔액</div><div class="value">{fmt_won(op_bal)}원</div><div class="sub">{target_year}년 개시</div></div>
    <div class="kpi"><div class="label">외부 순수입</div><div class="value">{fmt_won(curr_sum['inc'])}원</div><div class="sub">전년 대비 {curr_sum['inc'] - (prev_sum['inc'] if prev_sum else 0):+,}원</div></div>
    <div class="kpi"><div class="label">외부 순지출</div><div class="value">{fmt_won(curr_sum['exp'])}원</div><div class="sub">교부금 제외 순사업비</div></div>
    <div class="kpi"><div class="label">지부 교부·지원(내부이전)</div><div class="value">{fmt_won(curr_sum['tr_out'])}원</div><div class="sub">환입 {fmt_won(curr_sum['tr_in'])}원</div></div>
    <div class="kpi"><div class="label">기말 통장잔액</div><div class="value">{fmt_won(end_bal)}원</div><div class="sub">이월차액 {curr_sum['adj']:+,}원 포함</div></div>
  </div>

  <h2>1. 재정 흐름 및 활동 비중 시각화</h2>
  <div class="chart-grid">
    <div class="chart-card full"><img src="../charts/{chart_paths['monthly'].name}" alt="월별 수지 및 잔액 추이"></div>
    <div class="chart-card"><img src="../charts/{chart_paths['gwan'].name}" alt="관별 지출 비중"></div>
    <div class="chart-card"><img src="../charts/{chart_paths['mok'].name}" alt="활동별 지출 TOP 10"></div>
    <div class="chart-card"><img src="../charts/{chart_paths['exp_type'].name}" alt="지출형태별 현황"></div>
    <div class="chart-card"><img src="../charts/{chart_paths['multiyear'].name}" alt="연도별 조합비·교부금 비교"></div>
  </div>

  <h2 id="sec-coa">2. 3단계 계정과목(관 · 항 · 목) 연간 결산표</h2>
  <div tabindex="0" role="region" aria-labelledby="sec-coa" class="table-wrapper">
    <table>
      <thead><tr><th>목(활동)</th><th>구분</th><th>관(대분류)</th><th>항(중분류)</th><th>건수</th><th>{prev_year}년</th><th>{target_year}년</th><th>증감</th><th>비중</th></tr></thead>
      <tbody>
        {''.join(coa_rows_html)}
        <tr class="subtot"><th scope="row">외부 순수입 합계</th><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="num" data-label="{prev_year}년">{fmt_won(prev_sum['inc']) if prev_sum else '-'}</td><td class="num" data-label="{target_year}년">{fmt_won(curr_sum['inc'])}</td><td class="num" data-label="증감">{f"{curr_sum['inc']-(prev_sum['inc'] if prev_sum else 0):+,}" if prev_sum else '-'}</td><td class="num" data-label="비중">100.0%</td></tr>
        <tr class="subtot"><th scope="row">외부 순지출 합계</th><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="num" data-label="{prev_year}년">{fmt_won(prev_sum['exp']) if prev_sum else '-'}</td><td class="num" data-label="{target_year}년">{fmt_won(curr_sum['exp'])}</td><td class="num" data-label="증감">{f"{curr_sum['exp']-(prev_sum['exp'] if prev_sum else 0):+,}" if prev_sum else '-'}</td><td class="num" data-label="비중">100.0%</td></tr>
        <tr class="tot"><th scope="row">본부 기준 총지출</th><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="num" data-label="{prev_year}년">{fmt_won(prev_sum['hq_exp']) if prev_sum else '-'}</td><td class="num" data-label="{target_year}년">{fmt_won(curr_sum['hq_exp'])}</td><td class="num" data-label="증감">{f"{curr_sum['hq_exp']-(prev_sum['hq_exp'] if prev_sum else 0):+,}" if prev_sum else '-'}</td><td class="num empty-cell"></td></tr>
      </tbody>
    </table>
  </div>

  <h2 id="sec-fund">3. 재원별(일반회계 vs 특별모금·찬조) 결산 요약</h2>
  <div tabindex="0" role="region" aria-labelledby="sec-fund" class="table-wrapper">
    <table>
      <thead><tr><th>재원구분</th><th>외부 순수입</th><th>외부 순지출</th><th>내부이전(순)</th><th>재원 수지차(수입-지출)</th></tr></thead>
      <tbody>{''.join(fund_rows)}</tbody>
    </table>
  </div>

  <h2>4. 회계 검수 및 특이사항 보고</h2>
  <div class="note-box"><ul>{''.join(audit_items)}</ul></div>
</div>
</body>
</html>"""
    out = REPORTS_ANNUAL / f"{target_year}_대의원대회결산.html"
    out.write_text(doc, encoding="utf-8")
    return out, list(chart_paths.values())


def main():
    p = argparse.ArgumentParser(description="동기화 스냅샷 검증 및 운영위·대의원대회 보고서 생성기")
    p.add_argument("--xlsx", default=str(DATA_LATEST / "ledger.xlsx"), help="입력 XLSX 경로")
    p.add_argument("--month", default="latest", help="운영위 월간 보고서 대상월 (YYYY-MM 또는 latest)")
    p.add_argument("--year", default="2025", help="대의원대회 결산 보고서 대상연도 (YYYY)")
    args = p.parse_args()

    REPORTS_MONTHLY.mkdir(parents=True, exist_ok=True)
    REPORTS_ANNUAL.mkdir(parents=True, exist_ok=True)
    REPORTS_CHARTS.mkdir(parents=True, exist_ok=True)
    DATA_LATEST.mkdir(parents=True, exist_ok=True)

    units_cfg = json.loads((CONFIG_DIR / "units.json").read_text(encoding="utf-8"))
    coa_cfg = json.loads((CONFIG_DIR / "coa.json").read_text(encoding="utf-8"))

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        raise SystemExit(f"오류: XLSX 파일이 없습니다: {xlsx_path}\nGoogle Sheet에서 다운로드하거나 동기화를 먼저 실행하세요.")

    headers, records = load_xlsx_to_records(xlsx_path)
    errors, unit_balances = verify_records(records, coa_cfg)
    if errors:
        print("검증 오류 발견:")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)

    # Save JSON snapshot & sync metadata
    (DATA_LATEST / "ledger.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = {
        "syncedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "sourceXlsx": str(xlsx_path),
        "totalRecords": len(records),
        "unitBalances": unit_balances,
        "monthsRange": [min(r["ym"] for r in records), max(r["ym"] for r in records)],
    }
    (DATA_LATEST / "sync_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    target_ym = max(r["ym"] for r in records) if args.month == "latest" else args.month
    target_year = int(args.year)

    m_out = build_monthly_report(records, target_ym, units_cfg)
    a_out, charts = build_annual_report(records, target_year, coa_cfg)

    print(f"검증 통과! 총 {len(records)}건, 단위별 잔액={unit_balances}")
    print(f"운영위 월간 보고서 생성: {m_out}")
    print(f"대의원대회 결산 보고서 생성: {a_out} (차트 {len(charts)}종)")


if __name__ == "__main__":
    main()

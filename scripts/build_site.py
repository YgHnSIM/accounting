import argparse
import datetime as dt
import html
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_LATEST = ROOT / "data" / "latest"
DATA_PUBLIC = ROOT / "data" / "public"
WEB_ASSETS = ROOT / "web" / "assets"
SITE_DIR = ROOT / "_site"

plt.rcParams["font.family"] = ["NanumGothic", "Malgun Gothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
PALETTE = ["#1F4E78", "#2E75B6", "#4472C4", "#548235", "#BF9000", "#C55A11", "#843C0C", "#7030A0"]


def fmt_won(v):
    if v is None or v == "":
        return "-"
    return f"{int(round(v)):,}"


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
        "hq_exp": exp + tr_out,
    }


def sanitize_records(records, privacy_cfg):
    target_mask = privacy_cfg.get("targetMask", {})
    note_map = privacy_cfg.get("exactNoteReplacements", {})
    forbidden = privacy_cfg.get("forbiddenNames", [])
    clean = []
    for r in records:
        nr = dict(r)
        if nr["target"] in target_mask:
            nr["target"] = target_mask[nr["target"]]
        note = nr.get("note", "")
        if note in note_map:
            note = note_map[note]
        else:
            for name in forbidden:
                if name in note:
                    note = re.sub(rf"{re.escape(name)}(?:님|팀장|조합원|위원장|사무국장|단장)?", "관계자", note)
        nr["note"] = note
        # Strip raw source/memo internal detail filenames if any name appears
        memo = nr.get("memo", "")
        for name in forbidden:
            if name in memo:
                memo = memo.replace(name, "관계자")
        nr["memo"] = memo
        clean.append(nr)
    return clean


def render_shell(title: str, active_nav: str, rel_root: str, body_html: str, extra_scripts: str = "", page_desc: str = ""):
    prefix = f"{rel_root}/" if rel_root else ""
    nav_items = [
        ("dashboard", "index.html", "대시보드"),
        ("ledger", "ledger.html", "거래 탐색기"),
        ("reports", "reports/index.html", "보고서 아카이브"),
        ("coa", "coa.html", "계정과목·단위"),
    ]
    links_html = []
    for key, href, label in nav_items:
        cur = ' aria-current="page"' if key == active_nav else ""
        links_html.append(f'<li><a href="{prefix}{href}"{cur}>{label}</a></li>')

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="description" content="{html.escape(page_desc or title)}">
<title>{html.escape(title)} · 물류노동조합 회계</title>
<link rel="stylesheet" href="{prefix}assets/app.css">
</head>
<body>
<a class="skip-link" href="#main-content">본문으로 건너뛰기</a>
<header class="site-header">
  <div class="header-inner">
    <a class="site-logo" href="{prefix}index.html">
      <span>물류노동조합 회계</span>
      <span class="sub-tag">공개 대시보드</span>
    </a>
    <nav class="site-nav" aria-label="주요 메뉴">
      <button class="menu-button" type="button" popovertarget="site-menu" popovertargetaction="toggle" aria-controls="site-menu">
        <span aria-hidden="true">☰</span>
        <span>메뉴</span>
      </button>
      <ul id="site-menu" class="site-menu" popover="auto">
        {''.join(links_html)}
      </ul>
    </nav>
  </div>
</header>
<main id="main-content" class="main-wrap">
  {body_html}
</main>
<footer class="site-footer">
  우체국물류지원단 물류노동조합 공개 재정 자료실 · 공개 웹 버전은 개인 실명 비식별 처리됨
</footer>
<script src="{prefix}assets/nav.js"></script>
{extra_scripts}
</body>
</html>"""


def build_index_page(meta):
    body = f"""
  <div class="page-card">
    <div class="page-head">
      <div>
        <h1>노동조합 회계 대시보드</h1>
        <p class="sub">3단계 활동 체계(관·항·목) 및 본부·지부 통합 기준의 실시간 재정 현황</p>
      </div>
      <span id="sync-badge" class="status-pill">데이터 기준: {meta['monthsRange'][0]} ~ {meta['monthsRange'][1]} ({meta['totalRecords']}건)</span>
    </div>

    <div class="toolbar" role="region" aria-label="대시보드 필터">
      <div class="filter-field">
        <label for="f-year">회계연도</label>
        <select id="f-year"><option value="전체">전체 (2023~2026)</option></select>
      </div>
      <div class="filter-field">
        <label for="f-unit">회계단위</label>
        <select id="f-unit"><option value="전체">전체 (연결 기준)</option></select>
      </div>
      <div class="filter-field">
        <label for="f-fund">재원구분</label>
        <select id="f-fund"><option value="전체">전체 재원</option></select>
      </div>
      <button id="btn-reset" type="button" class="btn secondary">초기화</button>
    </div>

    <div class="kpi-grid">
      <div class="kpi"><div class="label">기초 잔액</div><div id="kpi-open" class="value">-</div><div class="sub">기간 개시 통장잔액</div></div>
      <div class="kpi"><div class="label">외부 순수입</div><div id="kpi-inc" class="value">-</div><div class="sub">조합비·찬조·기타</div></div>
      <div class="kpi"><div class="label">외부 순지출</div><div id="kpi-exp" class="value">-</div><div class="sub">교부금 제외 순사업비</div></div>
      <div class="kpi"><div class="label">내부이전 (전입-전출)</div><div id="kpi-tr" class="value">-</div><div id="kpi-tr-sub" class="sub">-</div></div>
      <div class="kpi"><div class="label">기말 잔액</div><div id="kpi-end" class="value">-</div><div id="kpi-end-sub" class="sub">-</div></div>
    </div>

    <div class="chart-grid">
      <section class="chart-card full">
        <div class="chart-head">
          <h3>월별 외부 수지 및 통장 잔액 추이</h3>
          <span class="chart-hint">수입·지출 막대 및 잔액 꺾은선</span>
        </div>
        <div class="chart-canvas-wrap"><canvas id="chart-monthly"></canvas></div>
      </section>

      <section class="chart-card">
        <div class="chart-head">
          <h3>3단계 활동 드릴다운 (관 → 항 → 목)</h3>
          <span id="drill-hint" class="chart-hint">막대를 클릭/터치해 하위 항목 탐색</span>
        </div>
        <div id="drill-breadcrumbs" class="breadcrumb-bar"></div>
        <div class="chart-canvas-wrap"><canvas id="chart-drill"></canvas></div>
      </section>

      <section class="chart-card">
        <div class="chart-head">
          <h3>주요 활동(목) 지출 TOP 10</h3>
          <span class="chart-hint">조합 주요 사업별 집행 규모</span>
        </div>
        <div class="chart-canvas-wrap"><canvas id="chart-top-mok"></canvas></div>
      </section>

      <section class="chart-card">
        <div class="chart-head">
          <h3>지출형태별 구성비</h3>
          <span class="chart-hint">식대·선물·인쇄 등 물리적 지출 수단</span>
        </div>
        <div class="chart-canvas-wrap"><canvas id="chart-exp-type"></canvas></div>
      </section>

      <section class="chart-card">
        <div class="chart-head">
          <h3>정기조합비 vs 지부 교부금 추이</h3>
          <span class="chart-hint">조합비 수납과 지부 배분 비교</span>
        </div>
        <div class="chart-canvas-wrap"><canvas id="chart-dues-grant"></canvas></div>
      </section>
    </div>

    <h2 id="sec-act-tbl" class="section-title">선택 조건별 활동(목) 세부 지출 집계</h2>
    <div tabindex="0" role="region" aria-labelledby="sec-act-tbl" class="table-wrapper">
      <table>
        <thead><tr><th>목(활동)</th><th>관(대분류)</th><th>항(중분류)</th><th>건수</th><th>지출액</th><th>비중</th></tr></thead>
        <tbody id="summary-tbody"></tbody>
      </table>
    </div>
  </div>"""
    scripts = (
        '<script src="assets/vendor/chart.umd.min.js"></script>\n'
        '<script src="data/public_ledger.js"></script>\n'
        '<script src="assets/dashboard.js"></script>'
    )
    return render_shell("대시보드", "dashboard", "", body, scripts, "우체국물류지원단 물류노동조합 회계 대시보드")


def build_ledger_page():
    body = """
  <div class="page-card">
    <div class="page-head">
      <div>
        <h1>공개 거래 탐색기</h1>
        <p class="sub">연도·구분·관·키워드 검색으로 원장 내역을 조회하고 CSV로 내려받을 수 있습니다. (개인 실명 비식별 처리)</p>
      </div>
      <button id="btn-csv" type="button" class="btn secondary small">필터 결과 CSV 저장</button>
    </div>

    <div class="toolbar" role="region" aria-label="원장 검색 필터">
      <div class="filter-field">
        <label for="l-year">연도</label>
        <select id="l-year"><option value="전체">전체 연도</option></select>
      </div>
      <div class="filter-field">
        <label for="l-gubun">구분</label>
        <select id="l-gubun"><option value="전체">전체 구분</option></select>
      </div>
      <div class="filter-field">
        <label for="l-gwan">관(대분류)</label>
        <select id="l-gwan"><option value="전체">전체 관</option></select>
      </div>
      <div class="filter-field">
        <label for="l-query">검색어 (적요·활동·지출형태)</label>
        <input id="l-query" type="search" placeholder="예: 운영위, 초복, 추석, 교부금">
      </div>
    </div>

    <p id="ledger-stats" class="sub" style="margin: 0 0 0.6rem 0; font-weight: 700;"></p>

    <div tabindex="0" role="region" aria-label="거래 내역 목록" class="table-wrapper">
      <table>
        <thead><tr><th>일자 · 활동</th><th>거래ID</th><th>단위</th><th>구분</th><th>계정(관·항·목)</th><th>지출형태</th><th>대상·귀속</th><th>수입금액</th><th>지출금액</th><th>적요(비고)</th></tr></thead>
        <tbody id="ledger-tbody"></tbody>
      </table>
    </div>

    <div class="toolbar" style="justify-content: space-between; margin-bottom: 0;">
      <button id="btn-prev" type="button" class="btn secondary small">이전</button>
      <span id="page-info" style="font-size: 0.85rem; font-weight: 700;">1 / 1</span>
      <button id="btn-next" type="button" class="btn secondary small">다음</button>
    </div>
  </div>"""
    scripts = '<script src="data/public_ledger.js"></script>\n<script src="assets/ledger.js"></script>'
    return render_shell("거래 탐색기", "ledger", "", body, scripts, "노동조합 공개 원장 거래 탐색기")


def build_coa_page(coa_cfg, units_cfg):
    unit_rows = []
    for u in units_cfg["units"]:
        st = "운영중" if u["status"] == "active" else "폐지"
        per = f"{u['openedOn']} ~ {u['closedOn'] or '현재'}"
        unit_rows.append(
            f"<tr><th scope='row'>{html.escape(u['code'])}</th>"
            f"<td class='ctr' data-label='약칭'>{html.escape(u['name'])}</td>"
            f"<td data-label='정식명칭'>{html.escape(u['fullName'])}</td>"
            f"<td class='ctr' data-label='상태'>{st}</td>"
            f"<td class='ctr' data-label='운영기간'>{per}</td>"
            f"<td data-label='비고'>{html.escape(u['note'])}</td></tr>"
        )
    coa_rows = []
    for a in coa_cfg["accounts"]:
        coa_rows.append(
            f"<tr><th scope='row'>{html.escape(a['mok'])}</th>"
            f"<td class='ctr' data-label='구분'>{html.escape(a['category'])}</td>"
            f"<td data-label='관(대분류)'>{html.escape(a['gwan'])}</td>"
            f"<td data-label='항(중분류)'>{html.escape(a['hang'])}</td>"
            f"<td data-label='설명'>{html.escape(a['description'])}</td></tr>"
        )

    body = f"""
  <div class="page-card">
    <div class="page-head">
      <div>
        <h1>3단계 계정과목표 및 회계단위 기준</h1>
        <p class="sub">소규모 노동조합의 활동이 명확히 드러나도록 설계한 관·항·목 체계와 단위 레지스트리입니다.</p>
      </div>
    </div>

    <h2 id="sec-units" class="section-title">1. 회계단위 레지스트리</h2>
    <div tabindex="0" role="region" aria-labelledby="sec-units" class="table-wrapper">
      <table>
        <thead><tr><th>코드</th><th>약칭</th><th>정식명칭</th><th>상태</th><th>운영기간</th><th>비고</th></tr></thead>
        <tbody>{''.join(unit_rows)}</tbody>
      </table>
    </div>

    <h2 id="sec-coa-list" class="section-title">2. 3단계 계정과목표 (관 · 항 · 목 · {len(coa_cfg['accounts'])}개)</h2>
    <div tabindex="0" role="region" aria-labelledby="sec-coa-list" class="table-wrapper">
      <table>
        <thead><tr><th>목(활동)</th><th>구분</th><th>관(대분류)</th><th>항(중분류)</th><th>계정 설명</th></tr></thead>
        <tbody>{''.join(coa_rows)}</tbody>
      </table>
    </div>
  </div>"""
    return render_shell("계정과목·단위", "coa", "", body, "", "노동조합 3단계 계정과목표 및 회계단위 안내")


def generate_public_charts(records, target_year: int, out_dir: Path):
    y_recs = [r for r in records if r["year"] == target_year]
    months = sorted({r["ym"] for r in y_recs})
    paths = {}

    # 1. Monthly chart
    m_inc, m_exp, m_end = [], [], []
    run_b = sum(r["inc"] - r["exp"] for r in records if r["year"] < target_year)
    for ym in months:
        s = summarize_period([r for r in y_recs if r["ym"] == ym])
        run_b += s["op"] + s["net"]
        m_inc.append(s["inc"] / 10000.0)
        m_exp.append(s["exp"] / 10000.0)
        m_end.append(run_b / 10000.0)

    fig, ax1 = plt.subplots(figsize=(10, 4.4), dpi=180)
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
    l1, lb1 = ax1.get_legend_handles_labels()
    l2, lb2 = ax2.get_legend_handles_labels()
    ax1.legend(l1 + l2, lb1 + lb2, loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3, frameon=True)
    ax1.set_title(f"{target_year}년 월별 외부 수지 및 기말 잔액 추이 (단위: 만원)", fontsize=12, fontweight="bold", pad=30)
    fig.tight_layout()
    p1 = out_dir / f"{target_year}_01_월별수지_잔액추이.png"
    fig.savefig(p1)
    plt.close(fig)
    paths["monthly"] = p1.name

    # 2. Gwan share
    g_agg = defaultdict(int)
    for r in y_recs:
        if r["gubun"] == "지출":
            g_agg[r["gwan"]] += r["exp"]
    g_items = sorted(g_agg.items(), key=lambda kv: kv[1], reverse=True)
    tot_exp = sum(v for _, v in g_items) or 1
    fig, ax = plt.subplots(figsize=(6.4, 4.1), dpi=180)
    labels = [k for k, _ in reversed(g_items)]
    vals = [v / 10000.0 for _, v in reversed(g_items)]
    bars = ax.barh(labels, vals, color=PALETTE[:len(labels)][::-1])
    for bar, v in zip(bars, vals):
        ax.text(v + max(vals) * 0.02, bar.get_y() + bar.get_height() / 2, f"{v:,.1f}만원 ({v*10000/tot_exp*100:.1f}%)", va="center", fontsize=9)
    ax.set_xlim(0, max(vals) * 1.35 if vals else 10)
    ax.set_xlabel("지출액 (만원)")
    ax.set_title(f"{target_year}년 관(대분류)별 외부 순지출 비중", fontsize=11.5, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    fig.tight_layout()
    p2 = out_dir / f"{target_year}_02_관별지출비중.png"
    fig.savefig(p2)
    plt.close(fig)
    paths["gwan"] = p2.name

    # 3. Top 10 Mok
    m_agg = defaultdict(int)
    for r in y_recs:
        if r["gubun"] == "지출":
            m_agg[f"{r['mok']} ({r['gwan']})"] += r["exp"]
    top_m = sorted(m_agg.items(), key=lambda kv: kv[1], reverse=True)[:10]
    fig, ax = plt.subplots(figsize=(6.8, 4.4), dpi=180)
    labels = [k for k, _ in reversed(top_m)]
    vals = [v / 10000.0 for _, v in reversed(top_m)]
    bars = ax.barh(labels, vals, color="#2E75B6")
    for bar, v in zip(bars, vals):
        ax.text(v + max(vals) * 0.02, bar.get_y() + bar.get_height() / 2, f"{v:,.1f}만원", va="center", fontsize=8.5)
    ax.set_xlim(0, max(vals) * 1.25 if vals else 10)
    ax.set_xlabel("지출액 (만원)")
    ax.set_title(f"{target_year}년 주요 활동(목)별 지출 TOP 10", fontsize=11.5, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    fig.tight_layout()
    p3 = out_dir / f"{target_year}_03_활동별TOP10.png"
    fig.savefig(p3)
    plt.close(fig)
    paths["mok"] = p3.name

    # 4. Exp type
    et_agg = defaultdict(int)
    for r in y_recs:
        if r["gubun"] == "지출" and r["exp_type"]:
            et_agg[r["exp_type"]] += r["exp"]
    et_items = sorted(et_agg.items(), key=lambda kv: kv[1], reverse=True)
    fig, ax = plt.subplots(figsize=(6.4, 4.1), dpi=180)
    labels = [k for k, _ in reversed(et_items)]
    vals = [v / 10000.0 for _, v in reversed(et_items)]
    bars = ax.barh(labels, vals, color="#548235")
    for bar, v in zip(bars, vals):
        ax.text(v + max(vals) * 0.02, bar.get_y() + bar.get_height() / 2, f"{v:,.1f}만원 ({v*10000/tot_exp*100:.1f}%)", va="center", fontsize=8.5)
    ax.set_xlim(0, max(vals) * 1.35 if vals else 10)
    ax.set_xlabel("지출액 (만원)")
    ax.set_title(f"{target_year}년 지출형태별 집행 현황", fontsize=11.5, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    fig.tight_layout()
    p4 = out_dir / f"{target_year}_04_지출형태비중.png"
    fig.savefig(p4)
    plt.close(fig)
    paths["exp_type"] = p4.name

    return paths


def build_public_monthly_html(records, target_ym: str):
    all_yms = sorted({r["ym"] for r in records if r["ym"]})
    prior_bal = sum(r["inc"] - r["exp"] for r in records if r["ym"] < target_ym)
    curr = [r for r in records if r["ym"] == target_ym]
    cs = summarize_period(curr)
    end_bal = prior_bal + cs["op"] + cs["net"]
    idx_ym = all_yms.index(target_ym)
    recent_yms = all_yms[max(0, idx_ym - 5):idx_ym + 1]

    recent_rows = []
    run_b = sum(r["inc"] - r["exp"] for r in records if r["ym"] < recent_yms[0])
    for ym in recent_yms:
        ms = summarize_period([r for r in records if r["ym"] == ym])
        op_m = run_b + ms["op"]
        end_m = op_m + ms["net"]
        run_b = end_m
        cls = ' class="subtot"' if ym == target_ym else ""
        recent_rows.append(
            f"<tr{cls}><th scope='row'>{ym}</th>"
            f"<td class='num' data-label='기초잔액'>{fmt_won(op_m)}</td>"
            f"<td class='num' data-label='외부 순수입'>{fmt_won(ms['inc'])}</td>"
            f"<td class='num' data-label='외부 순지출'>{fmt_won(ms['exp'])}</td>"
            f"<td class='num' data-label='내부이전(순)'>{fmt_won(ms['tr_net'])}</td>"
            f"<td class='num' data-label='이월차액'>{fmt_won(ms['adj'])}</td>"
            f"<td class='num' data-label='기말잔액'>{fmt_won(end_m)}</td></tr>"
        )

    tx_rows = []
    for r in curr:
        cls = ' class="muted"' if r["gubun"] == "이월차액" else ""
        et_cls = "ctr" if r["exp_type"] else "ctr empty-cell"
        iv_cls = "num" if r["inc"] else "num empty-cell"
        ev_cls = "num" if r["exp"] else "num empty-cell"
        note_cls = "" if r["note"] else "empty-cell"
        tx_rows.append(
            f"<tr{cls}><th scope='row'>{html.escape(r['date'])} · {html.escape(r['mok'])}</th>"
            f"<td class='ctr' data-label='단위'>{html.escape(r['unit'])}</td>"
            f"<td class='ctr' data-label='구분'>{html.escape(r['gubun'])}</td>"
            f"<td data-label='계정(관·항·목)'>{html.escape(r['gwan'])} &gt; {html.escape(r['hang'])} &gt; <b>{html.escape(r['mok'])}</b></td>"
            f"<td class='{et_cls}' data-label='지출형태'>{html.escape(r['exp_type'])}</td>"
            f"<td class='{iv_cls}' data-label='수입'>{fmt_won(r['inc']) if r['inc'] else ''}</td>"
            f"<td class='{ev_cls}' data-label='지출'>{fmt_won(r['exp']) if r['exp'] else ''}</td>"
            f"<td class='num' data-label='단위잔액'>{fmt_won(r['unit_bal'])}</td>"
            f"<td class='{note_cls}' data-label='적요'>{html.escape(r['note'])}</td></tr>"
        )

    y_n, m_n = target_ym.split("-")
    title = f"{y_n}년 {int(m_n)}월 운영위원회 재정보고"
    body = f"""
  <div class="page-card">
    <div class="page-head">
      <div>
        <h1>{title}</h1>
        <p class="sub">공개 웹 보고서(개인 실명 비식별 처리) · <a href="../index.html">전체 보고서 목록</a></p>
      </div>
      <span class="status-pill">기준월: {target_ym}</span>
    </div>
    <div class="kpi-grid">
      <div class="kpi"><div class="label">기초 잔액</div><div class="value">{fmt_won(prior_bal + cs['op'])}원</div></div>
      <div class="kpi"><div class="label">외부 순수입</div><div class="value">{fmt_won(cs['inc'])}원</div></div>
      <div class="kpi"><div class="label">외부 순지출</div><div class="value">{fmt_won(cs['exp'])}원</div></div>
      <div class="kpi"><div class="label">내부이전(순)</div><div class="value">{cs['tr_net']:+,}원</div></div>
      <div class="kpi"><div class="label">기말 잔액</div><div class="value">{fmt_won(end_bal)}원</div></div>
    </div>
    <h2 id="sec-r" class="section-title">1. 최근 6개월 수지 추이</h2>
    <div tabindex="0" role="region" aria-labelledby="sec-r" class="table-wrapper">
      <table>
        <thead><tr><th>보고월</th><th>기초잔액</th><th>외부 순수입</th><th>외부 순지출</th><th>내부이전(순)</th><th>이월차액</th><th>기말잔액</th></tr></thead>
        <tbody>{''.join(recent_rows)}</tbody>
      </table>
    </div>
    <h2 id="sec-d" class="section-title">2. 당월 세부 거래 내역 ({len(curr)}건)</h2>
    <div tabindex="0" role="region" aria-labelledby="sec-d" class="table-wrapper">
      <table>
        <thead><tr><th>일자 · 활동</th><th>단위</th><th>구분</th><th>계정(관·항·목)</th><th>지출형태</th><th>수입</th><th>지출</th><th>단위잔액</th><th>적요</th></tr></thead>
        <tbody>{''.join(tx_rows)}</tbody>
      </table>
    </div>
  </div>"""
    return render_shell(title, "reports", "../..", body, "", f"{title} 공개 재정 요약")


def build_public_annual_html(records, target_year: int, coa_cfg, charts_dir: Path):
    y_recs = [r for r in records if r["year"] == target_year]
    prior_bal = sum(r["inc"] - r["exp"] for r in records if r["year"] < target_year)
    cs = summarize_period(y_recs)
    op_bal = prior_bal + cs["op"]
    end_bal = op_bal + cs["net"]
    prev_year = target_year - 1
    prev_recs = [r for r in records if r["year"] == prev_year]
    ps = summarize_period(prev_recs) if prev_recs else None

    chart_names = generate_public_charts(records, target_year, charts_dir)

    tot_inc = cs["inc"] or 1
    tot_exp = cs["exp"] or 1
    coa_rows = []
    for acc in coa_cfg["accounts"]:
        cat, gw, ha, mo = acc["category"], acc["gwan"], acc["hang"], acc["mok"]
        if cat in ("기초이월", "이월차액"):
            continue
        if cat == "내부이전":
            cur_v = sum((r["exp"] if "전출" in r["gubun"] else r["inc"]) for r in y_recs if r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            prv_v = sum((r["exp"] if "전출" in r["gubun"] else r["inc"]) for r in prev_recs if r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            cnt = sum(1 for r in y_recs if r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            pct_s = "-"
        else:
            fld = "inc" if cat == "수입" else "exp"
            cur_v = sum(r[fld] for r in y_recs if r["gubun"] == cat and r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            prv_v = sum(r[fld] for r in prev_recs if r["gubun"] == cat and r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            cnt = sum(1 for r in y_recs if r["gubun"] == cat and r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            pct_s = f"{cur_v / (tot_inc if cat == '수입' else tot_exp) * 100:.1f}%"
        if cur_v == 0 and prv_v == 0:
            continue
        coa_rows.append(
            f"<tr><th scope='row'>{html.escape(mo)}</th>"
            f"<td class='ctr' data-label='구분'>{cat}</td>"
            f"<td data-label='관'>{html.escape(gw)}</td>"
            f"<td data-label='항'>{html.escape(ha)}</td>"
            f"<td class='ctr' data-label='건수'>{cnt}</td>"
            f"<td class='num' data-label='{prev_year}년'>{fmt_won(prv_v) if ps else '-'}</td>"
            f"<td class='num' data-label='{target_year}년'><b>{fmt_won(cur_v)}</b></td>"
            f"<td class='num' data-label='증감'>{f'{cur_v - prv_v:+,}' if ps else '-'}</td>"
            f"<td class='num' data-label='비중'>{pct_s}</td></tr>"
        )

    title = f"{target_year}년 대의원대회 결산 보고서"
    body = f"""
  <div class="page-card">
    <div class="page-head">
      <div>
        <h1>{title}</h1>
        <p class="sub">3단계 활동별 연간 결산 및 시각화 · <a href="../index.html">전체 보고서 목록</a></p>
      </div>
      <span class="status-pill">{target_year}년 결산</span>
    </div>
    <div class="kpi-grid">
      <div class="kpi"><div class="label">기초 잔액</div><div class="value">{fmt_won(op_bal)}원</div></div>
      <div class="kpi"><div class="label">외부 순수입</div><div class="value">{fmt_won(cs['inc'])}원</div></div>
      <div class="kpi"><div class="label">외부 순지출</div><div class="value">{fmt_won(cs['exp'])}원</div></div>
      <div class="kpi"><div class="label">내부이전 전출</div><div class="value">{fmt_won(cs['tr_out'])}원</div></div>
      <div class="kpi"><div class="label">기말 잔액</div><div class="value">{fmt_won(end_bal)}원</div></div>
    </div>
    <h2 class="section-title">1. 연간 재정 시각화</h2>
    <div class="chart-grid">
      <div class="chart-card full"><img src="../../assets/charts/{chart_names['monthly']}" alt="{target_year}년 월별 수지 및 잔액 추이"></div>
      <div class="chart-card"><img src="../../assets/charts/{chart_names['gwan']}" alt="{target_year}년 관별 지출 비중"></div>
      <div class="chart-card"><img src="../../assets/charts/{chart_names['mok']}" alt="{target_year}년 활동별 TOP 10"></div>
      <div class="chart-card full"><img src="../../assets/charts/{chart_names['exp_type']}" alt="{target_year}년 지출형태별 현황"></div>
    </div>
    <h2 id="sec-ac" class="section-title">2. 3단계 계정과목(관·항·목) 결산표</h2>
    <div tabindex="0" role="region" aria-labelledby="sec-ac" class="table-wrapper">
      <table>
        <thead><tr><th>목(활동)</th><th>구분</th><th>관</th><th>항</th><th>건수</th><th>{prev_year}년</th><th>{target_year}년</th><th>증감</th><th>비중</th></tr></thead>
        <tbody>
          {''.join(coa_rows)}
          <tr class="subtot"><th scope="row">외부 순수입 합계</th><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="num" data-label="{prev_year}년">{fmt_won(ps['inc']) if ps else '-'}</td><td class="num" data-label="{target_year}년">{fmt_won(cs['inc'])}</td><td class="num" data-label="증감">{f"{cs['inc']-ps['inc']:+,}" if ps else '-'}</td><td class="num" data-label="비중">100.0%</td></tr>
          <tr class="subtot"><th scope="row">외부 순지출 합계</th><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="num" data-label="{prev_year}년">{fmt_won(ps['exp']) if ps else '-'}</td><td class="num" data-label="{target_year}년">{fmt_won(cs['exp'])}</td><td class="num" data-label="증감">{f"{cs['exp']-ps['exp']:+,}" if ps else '-'}</td><td class="num" data-label="비중">100.0%</td></tr>
        </tbody>
      </table>
    </div>
  </div>"""
    return render_shell(title, "reports", "../..", body, "", f"{title} 공개 결산")


def build_reports_archive_page(years, months, records):
    ann_cards = []
    for y in sorted(years, reverse=True):
        yr_r = [r for r in records if r["year"] == y]
        s = summarize_period(yr_r)
        lbl = f"{y}년 대의원대회 결산" + (" (1~9월)" if y == 2026 else "")
        ann_cards.append(
            f"<article class='report-card'><div><h3>{lbl}</h3>"
            f"<p>순수입 {fmt_won(s['inc'])}원 · 순지출 {fmt_won(s['exp'])}원 · 교부금 {fmt_won(s['tr_out'])}원</p></div>"
            f"<a class='btn small' href='annual/{y}.html'>결산 보고서 열기</a></article>"
        )

    mon_cards = []
    for ym in sorted(months, reverse=True):
        mr = [r for r in records if r["ym"] == ym]
        ms = summarize_period(mr)
        mon_cards.append(
            f"<article class='report-card'><div><h3>{ym} 운영위 재정보고</h3>"
            f"<p>{len(mr)}건 · 수입 {fmt_won(ms['inc'])}원 · 지출 {fmt_won(ms['exp'])}원</p></div>"
            f"<a class='btn secondary small' href='monthly/{ym}.html'>월간 보고서 열기</a></article>"
        )

    body = f"""
  <div class="page-card">
    <div class="page-head">
      <div>
        <h1>보고서 아카이브</h1>
        <p class="sub">연도별 대의원대회 결산 보고서와 월별 운영위원회 재정보고 모음입니다.</p>
      </div>
    </div>
    <h2 class="section-title">연간 대의원대회 결산 보고서</h2>
    <div class="card-grid">{''.join(ann_cards)}</div>
    <h2 class="section-title">월간 운영위원회 재정보고 ({len(months)}개월)</h2>
    <div class="card-grid">{''.join(mon_cards)}</div>
  </div>"""
    return render_shell("보고서 아카이브", "reports", "..", body, "", "노동조합 월간·연간 재정보고 아카이브")


def main():
    p = argparse.ArgumentParser(description="공개용 정적 웹(_site) 생성기")
    p.add_argument("--ci", action="store_true", help="CI 모드: data/public/ledger_public.json만 사용해 빌드")
    args = p.parse_args()

    coa_cfg = json.loads((CONFIG_DIR / "coa.json").read_text(encoding="utf-8"))
    units_cfg = json.loads((CONFIG_DIR / "units.json").read_text(encoding="utf-8"))
    priv_path = CONFIG_DIR / "privacy.json"
    privacy_cfg = json.loads(priv_path.read_text(encoding="utf-8")) if priv_path.exists() else {}

    DATA_PUBLIC.mkdir(parents=True, exist_ok=True)
    pub_json_path = DATA_PUBLIC / "ledger_public.json"

    raw_json_path = DATA_LATEST / "ledger.json"
    if not args.ci and raw_json_path.exists():
        raw_records = json.loads(raw_json_path.read_text(encoding="utf-8"))
        pub_records = sanitize_records(raw_records, privacy_cfg)
        meta = json.loads((DATA_LATEST / "sync_meta.json").read_text(encoding="utf-8")) if (DATA_LATEST / "sync_meta.json").exists() else {}
        pub_payload = {
            "meta": {
                "syncedAt": meta.get("syncedAt", dt.datetime.now().isoformat(timespec="seconds")),
                "totalRecords": len(pub_records),
                "monthsRange": [min(r["ym"] for r in pub_records), max(r["ym"] for r in pub_records)],
                "sanitized": True,
            },
            "records": pub_records,
        }
        pub_json_path.write_text(json.dumps(pub_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Refreshed data/public/ledger_public.json ({len(pub_records)} sanitized records)")
    else:
        if not pub_json_path.exists():
            raise SystemExit(f"오류: {pub_json_path}가 없습니다.")
        pub_payload = json.loads(pub_json_path.read_text(encoding="utf-8"))

    records = pub_payload["records"]
    meta = pub_payload["meta"]

    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    (SITE_DIR / "assets" / "charts").mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "data").mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "reports" / "monthly").mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "reports" / "annual").mkdir(parents=True, exist_ok=True)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")

    # Copy web assets
    shutil.copytree(WEB_ASSETS, SITE_DIR / "assets", dirs_exist_ok=True)

    # Write public data json & js wrapper (works under both HTTPS & file://)
    (SITE_DIR / "data" / "public_ledger.json").write_text(json.dumps(pub_payload, ensure_ascii=False), encoding="utf-8")
    (SITE_DIR / "data" / "public_ledger.js").write_text(
        "window.__PUBLIC_LEDGER__ = " + json.dumps(pub_payload, ensure_ascii=False) + ";\n", encoding="utf-8"
    )

    # Core pages
    (SITE_DIR / "index.html").write_text(build_index_page(meta), encoding="utf-8")
    (SITE_DIR / "ledger.html").write_text(build_ledger_page(), encoding="utf-8")
    (SITE_DIR / "coa.html").write_text(build_coa_page(coa_cfg, units_cfg), encoding="utf-8")

    years = sorted({r["year"] for r in records if r["year"]})
    months = sorted({r["ym"] for r in records if r["ym"]})

    for ym in months:
        (SITE_DIR / "reports" / "monthly" / f"{ym}.html").write_text(build_public_monthly_html(records, ym), encoding="utf-8")
    for y in years:
        (SITE_DIR / "reports" / "annual" / f"{y}.html").write_text(
            build_public_annual_html(records, y, coa_cfg, SITE_DIR / "assets" / "charts"), encoding="utf-8"
        )
    (SITE_DIR / "reports" / "index.html").write_text(build_reports_archive_page(years, months, records), encoding="utf-8")

    print(f"Built _site/ successfully! ({len(years)} annual reports, {len(months)} monthly reports)")


if __name__ == "__main__":
    main()

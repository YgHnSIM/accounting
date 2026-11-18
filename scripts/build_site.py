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

from people_utils import (
    collect_person_names,
    load_directory_bundle,
    normalize_person_mentions,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_LATEST = ROOT / "data" / "latest"
DATA_PUBLIC = ROOT / "data" / "public"
WEB_ASSETS = ROOT / "web" / "assets"
SITE_DIR = ROOT / "_site"

plt.rcParams["font.family"] = ["NanumGothic", "Malgun Gothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["axes.facecolor"] = "#ffffff"
plt.rcParams["figure.facecolor"] = "#ffffff"
plt.rcParams["axes.edgecolor"] = "#d1d5e0"
plt.rcParams["axes.labelcolor"] = "#1d2130"
plt.rcParams["xtick.color"] = "#4d5160"
plt.rcParams["ytick.color"] = "#4d5160"
plt.rcParams["text.color"] = "#0b051a"
PALETTE = ["#3b82f6", "#002fa7", "#10b981", "#f43f5e", "#f59e0b", "#06b6d4", "#8b5cf6", "#64748b"]


def year_tone(year: int) -> str:
    return "accent" if int(year) % 2 == 0 else "neutral"


def fmt_won(v):
    if v is None or v == "":
        return "-"
    return f"{int(round(v)):,}"


def fmt_man(v):
    man = v / 10000.0
    if abs(man) >= 100 or abs(man - round(man)) < 0.05:
        return f"{man:,.0f}만"
    return f"{man:,.1f}만"


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


def sanitize_records(records, privacy_cfg, bundle=None):
    target_mask = privacy_cfg.get("targetMask", {})
    note_map = privacy_cfg.get("exactNoteReplacements", {})
    forbidden = collect_person_names(bundle, privacy_cfg)
    clean = []
    for r in records:
        nr = dict(r)
        raw_target = normalize_person_mentions(nr.get("target", ""), forbidden, bundle)
        nr["target"] = target_mask.get(raw_target, target_mask.get(nr.get("target", ""), raw_target))
        for name in forbidden:
            if name in nr["target"]:
                nr["target"] = "개인"

        raw_note = normalize_person_mentions(nr.get("note", ""), forbidden, bundle)
        if raw_note in note_map:
            note = note_map[raw_note]
        elif nr.get("note", "") in note_map:
            note = note_map[nr.get("note", "")]
        else:
            note = raw_note
            for name in forbidden:
                if name in note:
                    note = re.sub(rf"{re.escape(name)}(?:\s*(?:님|팀장|조합원|위원장|사무국장|단장|지부장|처장|실장|반장))?", "관계자", note)
        nr["note"] = note

        # Strip raw source/memo internal detail filenames if any name appears
        memo = normalize_person_mentions(nr.get("memo", ""), forbidden, bundle)
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
        ("coa", "coa.html", "회계기준·단위"),
    ]
    links_html = []
    for key, href, label in nav_items:
        cur = ' aria-current="page"' if key == active_nav else ""
        links_html.append(f'<li><a href="{prefix}{href}"{cur}>{label}</a></li>')

    favicon_svg = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
        "%3Cpath fill='%23516DB2' d='M48.2 4L10 26v48l38.2 22V76.5L26.5 64V36l21.7-12.5z'/%3E"
        "%3Cpath fill='%230B051A' d='M51.8 4L90 26v48L51.8 96V76.5L73.5 64V36L51.8 23.5z'/%3E"
        "%3Cpath fill='%230B051A' d='M48.2 28.5L32 37.8l16.2 8.4z'/%3E"
        "%3Cpath fill='%23516DB2' d='M51.8 28.5L68 37.8l-16.2 8.4z'/%3E%3C/svg%3E"
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="color-scheme" content="light">
<script>try{{const s=localStorage.getItem("color-scheme");if(s==="dark"||s==="light"){{document.querySelector('meta[name="color-scheme"]').content=s;document.documentElement.dataset.theme=s;}}}}catch(e){{}}</script>
<meta name="description" content="{html.escape(page_desc or title)}">
<title>{html.escape(title)} | 물류노동조합 회계</title>
<link rel="icon" type="image/svg+xml" href="{favicon_svg}">
<link rel="stylesheet" href="{prefix}assets/app.css">
</head>
<body>
<a class="skip-link" href="#main-content">본문으로 건너뛰기</a>
<header class="site-header">
  <div class="header-inner">
    <a class="site-logo" href="{prefix}index.html">
      <svg class="site-mark" aria-hidden="true" viewBox="0 0 100 100">
        <path fill="var(--color-logo, #516DB2)" d="M48.2 4L10 26v48l38.2 22V76.5L26.5 64V36l21.7-12.5z"/>
        <path fill="var(--color-ink, #0B051A)" d="M51.8 4L90 26v48L51.8 96V76.5L73.5 64V36L51.8 23.5z"/>
        <path fill="var(--color-ink, #0B051A)" d="M48.2 28.5L32 37.8l16.2 8.4z"/>
        <path fill="var(--color-logo, #516DB2)" d="M51.8 28.5L68 37.8l-16.2 8.4z"/>
      </svg>
      <span>물류노동조합 회계</span>
    </a>
    <div class="header-controls">
      <nav class="site-nav" aria-label="주요 메뉴">
        <button class="menu-button" type="button" popovertarget="site-menu" popovertargetaction="toggle" aria-controls="site-menu">
          <svg class="menu-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="4" y1="7" x2="20" y2="7"/>
            <line x1="4" y1="12" x2="20" y2="12"/>
            <line x1="4" y1="17" x2="20" y2="17"/>
          </svg>
          <span>메뉴</span>
        </button>
        <ul id="site-menu" class="site-menu" popover="auto">
          {''.join(links_html)}
        </ul>
      </nav>
      <button id="theme-toggle" class="theme-toggle" type="button" aria-label="다크 모드로 전환" aria-pressed="false">
        <span class="theme-opt-dark">
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
          <span>다크</span>
        </span>
        <span class="theme-opt-light">
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="4"/>
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
          </svg>
          <span>라이트</span>
        </span>
      </button>
    </div>
  </div>
</header>
<main id="main-content" class="main-wrap">
  {body_html}
</main>
<footer class="site-footer">
  <span>우체국물류지원단 물류노동조합 공개 재정 자료실</span>
  <span>공개 웹 버전 개인 실명 비식별 처리 적용</span>
</footer>
<script src="{prefix}assets/nav.js"></script>
{extra_scripts}
</body>
</html>"""


def build_index_page(meta):
    min_y = meta["monthsRange"][0][:4]
    max_y = meta["monthsRange"][1][:4]
    body = f"""
  <header class="page-masthead">
    <div>
      <h1>노동조합 회계 대시보드</h1>
      <p class="lead">대분류·중분류·세부활동 기준으로 한눈에 보는 조합 살림살이 현황</p>
    </div>
    <div class="masthead-meta">
      <span id="sync-badge" class="data-stamp">기준: {meta['monthsRange'][0]} ~ {meta['monthsRange'][1]} ({meta['totalRecords']}건)</span>
    </div>
  </header>

  <div class="toolbar" role="region" aria-label="대시보드 필터">
    <div class="filter-field">
      <label for="f-year">회계연도</label>
      <select id="f-year">
        <option value="{max_y}" selected>{max_y}년</option>
        <option value="전체">전체 기간 ({min_y}~{max_y})</option>
      </select>
    </div>
    <div class="filter-field">
      <label for="f-unit">회계단위</label>
      <select id="f-unit"><option value="전체">전체 (통합 기준)</option></select>
    </div>
    <div class="filter-field">
      <label for="f-fund">자금 구분</label>
      <select id="f-fund"><option value="전체">전체 자금</option></select>
    </div>
    <button id="btn-reset" type="button" class="btn secondary">초기화</button>
  </div>

  <div class="kpi-strip" role="region" aria-label="주요 재정 요약">
    <div class="kpi"><div class="label">기초 잔액</div><div id="kpi-open" class="value">-</div><div class="sub">기간 개시 통장잔액</div></div>
    <div class="kpi" data-tone="income"><div class="label">조합 수입</div><div id="kpi-inc" class="value">-</div><div class="sub">조합비·찬조·기타수입</div></div>
    <div class="kpi" data-tone="expense"><div class="label">사업 지출</div><div id="kpi-exp" class="value">-</div><div class="sub">지부 교부금 제외 순사업비</div></div>
    <div class="kpi" data-tone="grant"><div class="label">지부 교부·지원</div><div id="kpi-tr" class="value">-</div><div id="kpi-tr-sub" class="sub">-</div></div>
    <div class="kpi" data-tone="balance"><div class="label">기말 잔액</div><div id="kpi-end" class="value">-</div><div id="kpi-end-sub" class="sub">-</div></div>
  </div>

  <section class="section-band" aria-labelledby="sec-charts">
    <div class="section-head">
      <h2 id="sec-charts">월별 추이 및 활동별 시각화</h2>
      <span class="section-sub">항목 선택 시 하위 분류와 통계를 즉시 재계산합니다</span>
    </div>

    <div class="chart-grid">
      <section class="chart-card full">
        <div class="chart-head">
          <h3>월별 수입·지출 및 통장 잔액 추이</h3>
          <div id="monthly-mode-switch" class="view-mode-switch" role="group" aria-label="추이 차트 보기 방식">
            <button type="button" id="btn-mode-fit" class="mode-btn" aria-pressed="true">한눈에 보기</button>
            <button type="button" id="btn-mode-pan" class="mode-btn" aria-pressed="false">확대 탐색</button>
          </div>
        </div>
        <div id="readout-monthly" class="chart-readout" aria-live="polite">월을 누르거나 짚으면 수치가 여기에 표시됩니다</div>
        <div id="monthly-scroll" class="chart-scroll-x" tabindex="0" role="region" aria-label="월별 수입·지출 및 통장 잔액 차트">
          <div id="monthly-stage" class="chart-stage-wide"><canvas id="chart-monthly"></canvas></div>
        </div>
        <div id="monthly-minimap-wrap" class="minimap-wrap" hidden>
          <div class="minimap-head">
            <span class="minimap-title">전체 기간 잔액 흐름 (눌러서 시기 이동)</span>
            <span id="minimap-range" class="minimap-range">-</span>
          </div>
          <div id="minimap-viewport" class="minimap-viewport" role="slider" tabindex="0" aria-label="전체 추세 미니맵 이동" aria-valuemin="0" aria-valuemax="100" aria-valuenow="100">
            <canvas id="chart-monthly-minimap"></canvas>
            <div id="minimap-lens" class="minimap-lens" aria-hidden="true"></div>
          </div>
        </div>
      </section>
    </div>

    <div class="chart-deck" aria-roledescription="carousel" aria-label="활동별 분석 차트 모음">
      <nav id="chart-deck-tabs" class="chart-deck-tabs" aria-label="분석 차트 선택">
        <button type="button" class="chart-deck-tab" aria-current="true">1. 활동별 지출 탐색</button>
        <button type="button" class="chart-deck-tab">2. 세부활동 TOP 10</button>
        <button type="button" class="chart-deck-tab">3. 지출방식별 구성비</button>
        <button type="button" class="chart-deck-tab">4. 조합비 vs 교부금</button>
      </nav>

      <div id="chart-deck-track" class="chart-deck-track" tabindex="0" role="group" aria-label="분석 차트 슬라이드">
        <section class="chart-card" role="group" aria-roledescription="slide" aria-label="4개 중 1번째: 활동별 지출 탐색">
          <div class="chart-head">
            <h3>활동별 지출 탐색</h3>
            <span id="drill-hint" class="chart-hint" aria-live="polite">1단계 대분류 · 항목 선택 시 중분류 이동</span>
          </div>
          <div class="drill-bar-wrap">
            <div id="drill-breadcrumbs" class="breadcrumb-bar"></div>
            <a id="drill-ledger-link" class="drill-ledger-link" href="ledger.html">전체 지출 내역 보기 →</a>
          </div>
          <div id="readout-drill" class="chart-readout" aria-live="polite"></div>
          <div id="waffle-drill" class="waffle-wrap"></div>
        </section>

        <section class="chart-card" role="group" aria-roledescription="slide" aria-label="4개 중 2번째: 주요 세부활동 지출 TOP 10">
          <div class="chart-head">
            <h3>주요 세부활동 지출 TOP 10</h3>
            <span class="chart-hint">대분류 색상 연동 · 막대 선택 시 거래내역 이동</span>
          </div>
          <div id="readout-top-mok" class="chart-readout" aria-live="polite"></div>
          <div id="top-mok-legend" class="top-mok-legend" aria-label="대분류 색상 범례"></div>
          <div class="chart-canvas-wrap"><canvas id="chart-top-mok"></canvas></div>
        </section>

        <section class="chart-card" role="group" aria-roledescription="slide" aria-label="4개 중 3번째: 지출방식별 구성비">
          <div class="chart-head">
            <h3>지출방식별 구성비</h3>
            <span class="chart-hint">항목 선택 시 해당 지출 내역 이동</span>
          </div>
          <div id="readout-exp-type" class="chart-readout" aria-live="polite"></div>
          <div id="exp-type-viz" class="exp-rank-wrap"></div>
        </section>

        <section class="chart-card" role="group" aria-roledescription="slide" aria-label="4개 중 4번째: 정기조합비 vs 지부 교부금 추이">
          <div class="chart-head">
            <h3>정기조합비 vs 지부 교부금 추이</h3>
            <span class="chart-hint">조합비 수납과 지부 배분 비교</span>
          </div>
          <div id="readout-dues-grant" class="chart-readout" aria-live="polite"></div>
          <div class="chart-canvas-wrap"><canvas id="chart-dues-grant"></canvas></div>
        </section>
      </div>
      <p id="chart-deck-status" class="visually-hidden" role="status" aria-live="polite"></p>
    </div>
  </section>

  <section class="section-band" aria-labelledby="sec-act-tbl">
    <div class="section-head">
      <h2 id="sec-act-tbl">선택 조건별 세부활동 지출 집계</h2>
      <span class="section-sub">세부활동명을 누르면 거래 탐색기로 이동해 상세 내역을 보여줍니다</span>
    </div>
    <div tabindex="0" role="region" aria-labelledby="sec-act-tbl" class="table-wrapper">
      <table>
        <caption class="visually-hidden">선택 조건별 세부활동 지출 집계표</caption>
        <thead><tr><th scope="col">세부활동</th><th scope="col">대분류</th><th scope="col">중분류</th><th scope="col">건수</th><th scope="col">지출액</th><th scope="col">비중</th></tr></thead>
        <tbody id="summary-tbody"></tbody>
      </table>
    </div>
  </section>"""
    scripts = (
        '<script src="assets/vendor/chart.umd.min.js"></script>\n'
        '<script src="data/public_ledger.js"></script>\n'
        '<script src="assets/dashboard.js"></script>'
    )
    return render_shell("대시보드", "dashboard", "", body, scripts, "우체국물류지원단 물류노동조합 회계 대시보드")


def build_ledger_page():
    body = """
  <header class="page-masthead">
    <div>
      <h1>공개 거래 탐색기</h1>
      <p class="lead">연도, 구분, 대분류, 키워드로 원장 내역을 조회하고 CSV로 내려받을 수 있습니다. (개인 실명 비식별 처리)</p>
    </div>
    <div class="masthead-meta">
      <button id="btn-csv" type="button" class="btn secondary small">필터 결과 CSV 저장</button>
    </div>
  </header>

  <div class="toolbar" role="region" aria-label="원장 검색 필터">
    <div class="filter-field">
      <label for="l-year">연도</label>
      <select id="l-year"><option value="전체">전체 기간</option></select>
    </div>
    <div class="filter-field">
      <label for="l-gubun">구분</label>
      <select id="l-gubun"><option value="전체">전체 구분</option></select>
    </div>
    <div class="filter-field">
      <label for="l-gwan">대분류</label>
      <select id="l-gwan"><option value="전체">전체 대분류</option></select>
    </div>
    <div class="filter-field">
      <label for="l-query">검색어 (내용·세부활동·지출방식)</label>
      <input id="l-query" type="search" placeholder="예: 운영위, 초복, 추석, 교부금">
    </div>
    <button id="btn-ledger-reset" type="button" class="btn secondary">초기화</button>
  </div>

  <p id="ledger-stats" class="stats-line" aria-live="polite"></p>

  <div tabindex="0" role="region" aria-label="거래 내역 목록" class="table-wrapper">
    <table>
      <caption class="visually-hidden">공개 원장 거래 내역 목록</caption>
      <thead><tr><th scope="col">일자 · 세부활동</th><th scope="col">거래번호</th><th scope="col">단위</th><th scope="col">구분</th><th scope="col">분류(대·중·세부)</th><th scope="col">지출방식</th><th scope="col">대상·귀속</th><th scope="col">수입금액</th><th scope="col">지출금액</th><th scope="col">내용(적요)</th></tr></thead>
      <tbody id="ledger-tbody"></tbody>
    </table>
  </div>

  <div class="pager-bar">
    <button id="btn-prev" type="button" class="btn secondary small">이전</button>
    <span id="page-info" class="pager-info">1 / 1</span>
    <button id="btn-next" type="button" class="btn secondary small">다음</button>
  </div>"""
    scripts = '<script src="data/public_ledger.js"></script>\n<script src="assets/ledger.js"></script>'
    return render_shell("거래 탐색기", "ledger", "", body, scripts, "노동조합 공개 원장 거래 탐색기")


COA_MAP_GROUPS = [
    ("income", "수입", ("수입",)),
    ("expense", "지출", ("지출",)),
    ("transfer", "교부·이월", ("내부이전", "기초이월", "이월차액")),
]


def build_coa_map_data(coa_cfg, units_cfg):
    """Tree for the coa.html diagram: 구분 group -> 대분류 -> 중분류 -> 세부활동 (order kept from coa.json)."""
    groups = []
    for key, label, cats in COA_MAP_GROUPS:
        gwans = []
        index = {}
        for a in coa_cfg["accounts"]:
            if a["category"] not in cats:
                continue
            gid = (a["category"], a["gwan"])
            if gid not in index:
                index[gid] = {"name": a["gwan"], "category": a["category"], "hangs": []}
                gwans.append(index[gid])
            g = index[gid]
            hang = next((h for h in g["hangs"] if h["name"] == a["hang"]), None)
            if hang is None:
                hang = {"name": a["hang"], "moks": []}
                g["hangs"].append(hang)
            hang["moks"].append({"name": a["mok"], "desc": a["description"]})
        if gwans:
            groups.append({"key": key, "label": label, "gwans": gwans})
    units = [
        {"code": u["code"], "name": u["name"], "fullName": u["fullName"],
         "active": u["status"] == "active", "note": u["note"],
         "period": f"{u['openedOn']} ~ {u['closedOn'] or '현재'}"}
        for u in units_cfg["units"]
    ]
    return {"groups": groups, "units": units}


def render_coa_map_fallback(data):
    """Static nested lists: the full tree, readable without JS (and in print)."""
    e = html.escape
    hq = [u for u in data["units"] if u["code"] == "HQ"]
    branches = [u for u in data["units"] if u["code"] != "HQ"]
    unit_li = "".join(
        f"<li>{e(u['name'])} <span class='coa-tree-note'>{e(u['fullName'])}{'' if u['active'] else ' · 폐지'}</span></li>"
        for u in branches
    )
    units_html = (
        f"<li><strong>회계단위</strong><ul>"
        + "".join(f"<li>{e(u['name'])} <span class='coa-tree-note'>{e(u['note'])}</span><ul>{unit_li}</ul></li>" for u in hq)
        + "</ul></li>"
    )
    group_html = []
    for g in data["groups"]:
        gw = []
        for gwan in g["gwans"]:
            hs = "".join(
                f"<li>{e(h['name'])}<ul>"
                + "".join(f"<li><b>{e(m['name'])}</b> <span class='coa-tree-note'>{e(m['desc'])}</span></li>" for m in h["moks"])
                + "</ul></li>"
                for h in gwan["hangs"]
            )
            gw.append(f"<li><strong>{e(gwan['name'])}</strong><ul>{hs}</ul></li>")
        group_html.append(f"<li><strong>{e(g['label'])}</strong><ul>{''.join(gw)}</ul></li>")
    return (
        "<ul class='coa-tree'>"
        f"<li><strong>물류노동조합 회계</strong><ul>{units_html}"
        f"<li><strong>수입·지출 분류</strong><ul>{''.join(group_html)}</ul></li></ul></li></ul>"
    )


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
        cat_disp = "지부 교부·정산" if a["category"] == "내부이전" else ("이월 잔액 조정" if a["category"] == "이월차액" else a["category"])
        coa_rows.append(
            f"<tr><th scope='row'>{html.escape(a['mok'])}</th>"
            f"<td class='ctr' data-label='구분'>{html.escape(cat_disp)}</td>"
            f"<td data-label='대분류'>{html.escape(a['gwan'])}</td>"
            f"<td data-label='중분류'>{html.escape(a['hang'])}</td>"
            f"<td data-label='설명'>{html.escape(a['description'])}</td></tr>"
        )

    map_data = build_coa_map_data(coa_cfg, units_cfg)
    map_fallback = render_coa_map_fallback(map_data)
    map_json = json.dumps(map_data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    body = f"""
  <header class="page-masthead">
    <div>
      <h1>수입·지출 분류 기준 및 회계단위 안내</h1>
      <p class="lead">조합의 활동이 한눈에 드러나도록 대분류·중분류·세부활동 3단계로 정리한 기준표입니다.</p>
    </div>
    <div class="masthead-meta">
      <span class="data-stamp">{len(coa_cfg['accounts'])}개 세부활동 · {len(units_cfg['units'])}개 단위</span>
    </div>
  </header>

  <div class="coa-tabs-mount" id="coa-tabs-mount"></div>

  <div class="coa-panel" id="panel-diagram" data-tab="diagram" data-tab-label="다이어그램">
  <section class="section-band" aria-labelledby="sec-coa-map">
    <div class="section-head">
      <h2 id="sec-coa-map">한눈에 보는 회계 구조</h2>
      <span class="section-sub">대분류를 누르면 중분류, 중분류를 누르면 세부활동이 펼쳐집니다</span>
    </div>
    <div class="coa-map" id="coa-map">
      <div class="coa-map-fallback" id="coa-map-fallback">{map_fallback}</div>
    </div>
    <script type="application/json" id="coa-map-data">{map_json}</script>
  </section>
  </div>

  <div class="coa-panel" id="panel-table" data-tab="table" data-tab-label="표">
  <section class="section-band" aria-labelledby="sec-units">
    <div class="section-head">
      <h2 id="sec-units">1. 회계단위 안내 (본부 · 지부)</h2>
      <span class="section-sub">본부 및 지부 운영 상태와 기록 보관 기준</span>
    </div>
    <div tabindex="0" role="region" aria-labelledby="sec-units" class="table-wrapper">
      <table>
        <caption class="visually-hidden">회계단위 목록</caption>
        <thead><tr><th scope="col">코드</th><th scope="col">약칭</th><th scope="col">정식명칭</th><th scope="col">상태</th><th scope="col">운영기간</th><th scope="col">비고</th></tr></thead>
        <tbody>{''.join(unit_rows)}</tbody>
      </table>
    </div>
  </section>

  <section class="section-band" aria-labelledby="sec-coa-list">
    <div class="section-head">
      <h2 id="sec-coa-list">2. 수입·지출 분류 기준표 (대분류 · 중분류 · 세부활동 · {len(coa_cfg['accounts'])}개)</h2>
      <span class="section-sub">조합 활동 중심의 3단계 계층 분류</span>
    </div>
    <div tabindex="0" role="region" aria-labelledby="sec-coa-list" class="table-wrapper">
      <table>
        <caption class="visually-hidden">수입·지출 분류 기준표</caption>
        <thead><tr><th scope="col">세부활동</th><th scope="col">구분</th><th scope="col">대분류</th><th scope="col">중분류</th><th scope="col">항목 설명</th></tr></thead>
        <tbody>{''.join(coa_rows)}</tbody>
      </table>
    </div>
  </section>
  </div>"""
    return render_shell("회계기준·단위", "coa", "", body, '<script src="assets/coa-tabs.js"></script>\n<script src="assets/coa-map.js"></script>', "노동조합 수입·지출 분류 기준 및 회계단위 안내")


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
    ax1.bar([i - w / 2 for i in x], m_inc, width=w, label="조합 수입", color="#10b981")
    ax1.bar([i + w / 2 for i in x], m_exp, width=w, label="사업 지출", color="#f43f5e")
    ax1.set_ylabel("월간 수지 (만원)")
    ax1.set_ylim(0, max(m_inc + m_exp + [10]) * 1.15)
    ax1.set_xticks(x)
    ax1.set_xticklabels([m[5:] + "월" for m in months])
    ax1.grid(axis="y", linestyle="--", color="#d1d5e0", alpha=0.8)
    ax1.spines["top"].set_visible(False)
    ax2 = ax1.twinx()
    ax2.plot(x, m_end, color="#3b82f6", marker="o", linewidth=2.2, label="기말 통장잔액")
    ax2.set_ylabel("기말 잔액 (만원)")
    ax2.set_ylim(0, max(m_end + [10]) * 1.18)
    ax2.spines["top"].set_visible(False)
    for i, v in enumerate(m_end):
        ax2.annotate(f"{v:,.0f}", (i, v), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=8, color="#002fa7")
    l1, lb1 = ax1.get_legend_handles_labels()
    l2, lb2 = ax2.get_legend_handles_labels()
    ax1.legend(l1 + l2, lb1 + lb2, loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3, frameon=False)
    ax1.set_title(f"{target_year}년 월별 조합 수입·사업 지출 및 잔액 추이 (단위: 만원)", fontsize=12, fontweight="bold", pad=30)
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
    ax.set_title(f"{target_year}년 대분류별 사업 지출 비중", fontsize=11.5, fontweight="bold")
    ax.grid(axis="x", linestyle="--", color="#d1d5e0", alpha=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
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
    bars = ax.barh(labels, vals, color="#3b82f6")
    for bar, v in zip(bars, vals):
        ax.text(v + max(vals) * 0.02, bar.get_y() + bar.get_height() / 2, f"{v:,.1f}만원", va="center", fontsize=8.5)
    ax.set_xlim(0, max(vals) * 1.25 if vals else 10)
    ax.set_xlabel("지출액 (만원)")
    ax.set_title(f"{target_year}년 주요 세부활동별 지출 TOP 10", fontsize=11.5, fontweight="bold")
    ax.grid(axis="x", linestyle="--", color="#d1d5e0", alpha=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
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
    bars = ax.barh(labels, vals, color="#002fa7")
    for bar, v in zip(bars, vals):
        ax.text(v + max(vals) * 0.02, bar.get_y() + bar.get_height() / 2, f"{v:,.1f}만원 ({v*10000/tot_exp*100:.1f}%)", va="center", fontsize=8.5)
    ax.set_xlim(0, max(vals) * 1.35 if vals else 10)
    ax.set_xlabel("지출액 (만원)")
    ax.set_title(f"{target_year}년 지출방식별 집행 현황", fontsize=11.5, fontweight="bold")
    ax.grid(axis="x", linestyle="--", color="#d1d5e0", alpha=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
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
    recent_yms = all_yms[max(0, idx_ym - 2):idx_ym + 1]

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
            f"<td class='num' data-label='조합 수입'>{fmt_won(ms['inc'])}</td>"
            f"<td class='num' data-label='사업 지출'>{fmt_won(ms['exp'])}</td>"
            f"<td class='num' data-label='지부 교부·정산'>{fmt_won(ms['tr_net'])}</td>"
            f"<td class='num' data-label='이월 조정'>{fmt_won(ms['adj'])}</td>"
            f"<td class='num' data-label='기말잔액'>{fmt_won(end_m)}</td></tr>"
        )

    gubun_disp = {
        "내부이전(전출)": "지부 교부·지원(전출)",
        "내부이전(전입)": "지부 회수·환수(전입)",
        "이월차액": "이월 잔액 조정",
    }
    tx_rows = []
    for r in curr:
        cls = ' class="muted"' if r["gubun"] == "이월차액" else ""
        et_cls = "ctr" if r["exp_type"] else "ctr empty-cell"
        iv_cls = "num num-inc" if r["inc"] else "num empty-cell"
        ev_cls = "num num-exp" if r["exp"] else "num empty-cell"
        note_cls = "" if r["note"] else "empty-cell"
        tx_rows.append(
            f"<tr{cls}><th scope='row'>{html.escape(r['date'])} · {html.escape(r['mok'])}</th>"
            f"<td class='ctr' data-label='단위'>{html.escape(r['unit'])}</td>"
            f"<td class='ctr' data-label='구분'>{html.escape(gubun_disp.get(r['gubun'], r['gubun']))}</td>"
            f"<td class='coa-cell' data-label='분류(대·중·세부)'><span class='coa-path'><span class='coa-gwan'>{html.escape(r['gwan'])} <span class='coa-sep'>&gt;</span></span> <span class='coa-hang'>{html.escape(r['hang'])} <span class='coa-sep'>&gt;</span></span> <b class='coa-mok'>{html.escape(r['mok'])}</b></span></td>"
            f"<td class='{et_cls}' data-label='지출방식'>{html.escape(r['exp_type'])}</td>"
            f"<td class='{iv_cls}' data-label='수입'>{('+' + fmt_won(r['inc'])) if r['inc'] else ''}</td>"
            f"<td class='{ev_cls}' data-label='지출'>{('-' + fmt_won(r['exp'])) if r['exp'] else ''}</td>"
            f"<td class='num' data-label='단위잔액'>{fmt_won(r['unit_bal'])}</td>"
            f"<td class='{note_cls}' data-label='내용'>{html.escape(r['note'])}</td></tr>"
        )

    prev_ym = all_yms[idx_ym - 1] if idx_ym > 0 else None
    next_ym = all_yms[idx_ym + 1] if idx_ym + 1 < len(all_yms) else None
    prev_btn = f'<a class="btn secondary small" href="{prev_ym}.html">← {prev_ym} 보고서</a>' if prev_ym else '<button type="button" class="btn secondary small" disabled>← 이전 없음</button>'
    next_btn = f'<a class="btn secondary small" href="{next_ym}.html">{next_ym} 보고서 →</a>' if next_ym else '<button type="button" class="btn secondary small" disabled>다음 없음 →</button>'
    nav_bar = f"""
  <nav class="report-nav-bar" aria-label="월간 보고서 이동">
    {prev_btn}
    <a class="btn secondary small" href="../index.html">전체 보고서 목록</a>
    {next_btn}
  </nav>"""

    y_n, m_n = target_ym.split("-")
    ytone = year_tone(int(y_n))
    title = f"{y_n}년 {int(m_n)}월 운영위원회 재정보고"
    body = f"""
  <header class="page-masthead" data-year-tone="{ytone}">
    <div>
      <h1>{title}</h1>
      <p class="lead">공개 웹 보고서(개인 실명 비식별 처리)</p>
    </div>
    <div class="masthead-meta">
      <span class="data-stamp">{y_n}년 · {target_ym}</span>
    </div>
  </header>

  {nav_bar}

  <div class="kpi-strip" role="region" aria-label="당월 재정 요약">
    <div class="kpi"><div class="label">기초 잔액</div><div class="value">{fmt_won(prior_bal + cs['op'])}원</div></div>
    <div class="kpi" data-tone="income"><div class="label">조합 수입</div><div class="value">{fmt_won(cs['inc'])}원</div></div>
    <div class="kpi" data-tone="expense"><div class="label">사업 지출</div><div class="value">{fmt_won(cs['exp'])}원</div></div>
    <div class="kpi" data-tone="grant"><div class="label">지부 교부·지원</div><div class="value">{fmt_won(cs['tr_out'])}원</div></div>
    <div class="kpi" data-tone="balance"><div class="label">기말 잔액</div><div class="value">{fmt_won(end_bal)}원</div></div>
  </div>

  <section class="section-band" aria-labelledby="sec-r">
    <div class="section-head">
      <h2 id="sec-r">1. 최근 3개월 수지 추이</h2>
      <span class="section-sub">당월 포함 최근 3개월 월간 잔액 흐름</span>
    </div>
    <div tabindex="0" role="region" aria-labelledby="sec-r" class="table-wrapper">
      <table>
        <caption class="visually-hidden">최근 3개월 수지 추이표</caption>
        <thead><tr><th scope="col">보고월</th><th scope="col">기초잔액</th><th scope="col">조합 수입</th><th scope="col">사업 지출</th><th scope="col">지부 교부·정산</th><th scope="col">이월 조정</th><th scope="col">기말잔액</th></tr></thead>
        <tbody>{''.join(recent_rows)}</tbody>
      </table>
    </div>
  </section>

  <section class="section-band" aria-labelledby="sec-d">
    <div class="section-head">
      <h2 id="sec-d">2. 당월 세부 거래 내역 ({len(curr)}건)</h2>
      <span class="section-sub">일자 및 세부활동 기준 상세 원장</span>
    </div>
    <div tabindex="0" role="region" aria-labelledby="sec-d" class="table-wrapper">
      <table>
        <caption class="visually-hidden">당월 세부 거래 내역표</caption>
        <thead><tr><th scope="col">일자 · 세부활동</th><th scope="col">단위</th><th scope="col">구분</th><th scope="col">분류(대·중·세부)</th><th scope="col">지출방식</th><th scope="col">수입</th><th scope="col">지출</th><th scope="col">단위잔액</th><th scope="col">내용</th></tr></thead>
        <tbody>{''.join(tx_rows)}</tbody>
      </table>
    </div>
  </section>

  <nav class="report-nav-bar bottom" aria-label="하단 월간 보고서 이동">
    {prev_btn}
    <a class="btn secondary small" href="../index.html">전체 보고서 목록</a>
    {next_btn}
  </nav>"""
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
            cat_disp = "지부 교부·정산"
        else:
            fld = "inc" if cat == "수입" else "exp"
            cur_v = sum(r[fld] for r in y_recs if r["gubun"] == cat and r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            prv_v = sum(r[fld] for r in prev_recs if r["gubun"] == cat and r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            cnt = sum(1 for r in y_recs if r["gubun"] == cat and r["gwan"] == gw and r["hang"] == ha and r["mok"] == mo)
            pct_s = f"{cur_v / (tot_inc if cat == '수입' else tot_exp) * 100:.1f}%"
            cat_disp = cat
        if cur_v == 0 and prv_v == 0:
            continue
        coa_rows.append(
            f"<tr><th scope='row'>{html.escape(mo)}</th>"
            f"<td class='ctr' data-label='구분'>{cat_disp}</td>"
            f"<td data-label='대분류'>{html.escape(gw)}</td>"
            f"<td data-label='중분류'>{html.escape(ha)}</td>"
            f"<td class='ctr' data-label='건수'>{cnt}</td>"
            f"<td class='num' data-label='{prev_year}년'>{fmt_won(prv_v) if ps else '-'}</td>"
            f"<td class='num' data-label='{target_year}년'><b>{fmt_won(cur_v)}</b></td>"
            f"<td class='num' data-label='증감'>{f'{cur_v - prv_v:+,}' if ps else '-'}</td>"
            f"<td class='num' data-label='비중'>{pct_s}</td></tr>"
        )

    all_years = sorted({r["year"] for r in records if r["year"]})
    idx_yr = all_years.index(target_year)
    prev_y = all_years[idx_yr - 1] if idx_yr > 0 else None
    next_y = all_years[idx_yr + 1] if idx_yr + 1 < len(all_years) else None
    prev_btn = f'<a class="btn secondary small" href="{prev_y}.html">← {prev_y}년 결산</a>' if prev_y else '<button type="button" class="btn secondary small" disabled>← 이전 연도 없음</button>'
    next_btn = f'<a class="btn secondary small" href="{next_y}.html">{next_y}년 결산 →</a>' if next_y else '<button type="button" class="btn secondary small" disabled>다음 연도 없음 →</button>'
    nav_bar = f"""
  <nav class="report-nav-bar" aria-label="연간 결산 보고서 이동">
    {prev_btn}
    <a class="btn secondary small" href="../index.html">전체 보고서 목록</a>
    {next_btn}
  </nav>"""

    ytone = year_tone(target_year)
    title = f"{target_year}년 대의원대회 결산 보고서"
    body = f"""
  <header class="page-masthead" data-year-tone="{ytone}">
    <div>
      <h1>{title}</h1>
      <p class="lead">활동별 연간 결산 및 시각화</p>
    </div>
    <div class="masthead-meta">
      <span class="data-stamp">{target_year}년 결산</span>
    </div>
  </header>

  {nav_bar}

  <div class="kpi-strip" role="region" aria-label="{target_year}년 재정 요약">
    <div class="kpi"><div class="label">기초 잔액</div><div class="value">{fmt_won(op_bal)}원</div></div>
    <div class="kpi" data-tone="income"><div class="label">조합 수입</div><div class="value">{fmt_won(cs['inc'])}원</div></div>
    <div class="kpi" data-tone="expense"><div class="label">사업 지출</div><div class="value">{fmt_won(cs['exp'])}원</div></div>
    <div class="kpi" data-tone="grant"><div class="label">지부 교부·지원</div><div class="value">{fmt_won(cs['tr_out'])}원</div></div>
    <div class="kpi" data-tone="balance"><div class="label">기말 잔액</div><div class="value">{fmt_won(end_bal)}원</div></div>
  </div>

  <section class="section-band" aria-labelledby="sec-annual-charts">
    <div class="section-head">
      <h2 id="sec-annual-charts">1. 연간 재정 시각화</h2>
      <span class="section-sub">차트를 누르면 고해상도 확대 창에서 좌우 슬라이드로 크게 볼 수 있습니다</span>
    </div>
    <div class="chart-grid">
      <figure class="chart-card full">
        <button type="button" class="chart-zoom-trigger" data-zoom-src="../../assets/charts/{chart_names['monthly']}" data-zoom-title="{target_year}년 월별 수입·지출 및 잔액 추이">
          <img src="../../assets/charts/{chart_names['monthly']}" alt="{target_year}년 월별 수입·지출 및 잔액 추이">
          <span class="chart-zoom-caption"><span>월별 조합 수입·사업 지출 및 기말 잔액 추이</span><span>눌러서 크게 보기 ⊕</span></span>
        </button>
      </figure>
      <figure class="chart-card">
        <button type="button" class="chart-zoom-trigger" data-zoom-src="../../assets/charts/{chart_names['gwan']}" data-zoom-title="{target_year}년 대분류별 지출 비중">
          <img src="../../assets/charts/{chart_names['gwan']}" alt="{target_year}년 대분류별 지출 비중">
          <span class="chart-zoom-caption"><span>대분류별 사업 지출 비중</span><span>눌러서 크게 보기 ⊕</span></span>
        </button>
      </figure>
      <figure class="chart-card">
        <button type="button" class="chart-zoom-trigger" data-zoom-src="../../assets/charts/{chart_names['mok']}" data-zoom-title="{target_year}년 세부활동 TOP 10">
          <img src="../../assets/charts/{chart_names['mok']}" alt="{target_year}년 세부활동 TOP 10">
          <span class="chart-zoom-caption"><span>주요 세부활동별 지출 TOP 10</span><span>눌러서 크게 보기 ⊕</span></span>
        </button>
      </figure>
      <figure class="chart-card full">
        <button type="button" class="chart-zoom-trigger" data-zoom-src="../../assets/charts/{chart_names['exp_type']}" data-zoom-title="{target_year}년 지출방식별 현황">
          <img src="../../assets/charts/{chart_names['exp_type']}" alt="{target_year}년 지출방식별 현황">
          <span class="chart-zoom-caption"><span>지출방식별 집행 현황</span><span>눌러서 크게 보기 ⊕</span></span>
        </button>
      </figure>
    </div>
  </section>

  <dialog id="chart-lightbox" class="chart-lightbox" aria-labelledby="lightbox-title">
    <div class="lightbox-head">
      <strong id="lightbox-title">차트 확대 보기</strong>
      <button type="button" id="lightbox-close" class="btn secondary small">닫기</button>
    </div>
    <div class="lightbox-scroll">
      <img id="lightbox-img" src="../../assets/charts/{chart_names['monthly']}" alt="확대 차트 이미지">
    </div>
  </dialog>

  <section class="section-band" aria-labelledby="sec-ac">
    <div class="section-head">
      <h2 id="sec-ac">2. 활동별 연간 결산표 (대분류 · 중분류 · 세부활동)</h2>
      <span class="section-sub">전년 대비 증감 및 구성비</span>
    </div>
    <div tabindex="0" role="region" aria-labelledby="sec-ac" class="table-wrapper">
      <table>
        <caption class="visually-hidden">{target_year}년 활동별 연간 결산표</caption>
        <thead><tr><th scope="col">세부활동</th><th scope="col">구분</th><th scope="col">대분류</th><th scope="col">중분류</th><th scope="col">건수</th><th scope="col">{prev_year}년</th><th scope="col">{target_year}년</th><th scope="col">증감</th><th scope="col">비중</th></tr></thead>
        <tbody>
          {''.join(coa_rows)}
          <tr class="subtot"><th scope="row">조합 수입 합계</th><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="num" data-label="{prev_year}년">{fmt_won(ps['inc']) if ps else '-'}</td><td class="num" data-label="{target_year}년">{fmt_won(cs['inc'])}</td><td class="num" data-label="증감">{f"{cs['inc']-ps['inc']:+,}" if ps else '-'}</td><td class="num" data-label="비중">100.0%</td></tr>
          <tr class="subtot"><th scope="row">사업 지출 합계</th><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="empty-cell"></td><td class="num" data-label="{prev_year}년">{fmt_won(ps['exp']) if ps else '-'}</td><td class="num" data-label="{target_year}년">{fmt_won(cs['exp'])}</td><td class="num" data-label="증감">{f"{cs['exp']-ps['exp']:+,}" if ps else '-'}</td><td class="num" data-label="비중">100.0%</td></tr>
        </tbody>
      </table>
    </div>
  </section>

  <nav class="report-nav-bar bottom" aria-label="하단 연간 결산 보고서 이동">
    {prev_btn}
    <a class="btn secondary small" href="../index.html">전체 보고서 목록</a>
    {next_btn}
  </nav>"""
    lightbox_script = """<script>
(function(){
  const dlg = document.getElementById("chart-lightbox");
  const img = document.getElementById("lightbox-img");
  const ttl = document.getElementById("lightbox-title");
  const cls = document.getElementById("lightbox-close");
  if (!dlg || typeof dlg.showModal !== "function") return;
  document.querySelectorAll(".chart-zoom-trigger").forEach((btn) => {
    btn.addEventListener("click", () => {
      img.src = btn.dataset.zoomSrc;
      img.alt = btn.dataset.zoomTitle || "확대 차트";
      ttl.textContent = btn.dataset.zoomTitle || "차트 확대 보기";
      dlg.showModal();
    });
  });
  cls.addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
})();
</script>"""
    return render_shell(title, "reports", "../..", body, lightbox_script, f"{title} 공개 결산")


def build_reports_archive_page(years, months, records):
    ann_cards = []
    for y in sorted(years, reverse=True):
        yr_r = [r for r in records if r["year"] == y]
        s = summarize_period(yr_r)
        ytone = year_tone(y)
        lbl = f"{y}년 대의원대회 결산" + (" (1~9월)" if y == 2026 else "")
        ann_cards.append(
            f"<article class='report-entry' data-year-tone='{ytone}'><div><h3>{lbl}</h3>"
            f"<p class='meta-figures'>조합 수입 {fmt_won(s['inc'])}원 / 사업 지출 {fmt_won(s['exp'])}원 / 교부금 {fmt_won(s['tr_out'])}원</p></div>"
            f"<a class='btn small entry-link' href='annual/{y}.html'>{y}년 결산 열기</a></article>"
        )

    # Precompute chronological monthly balances and top expense activity
    month_info = {}
    running_bal = 0
    for ym in sorted(months):
        mr = [r for r in records if r["ym"] == ym]
        ms = summarize_period(mr)
        running_bal += ms["op"] + ms["net"]
        exp_by_mok = defaultdict(int)
        for r in mr:
            if r["gubun"] == "지출":
                exp_by_mok[r["mok"]] += r["exp"]
        top_mok = max(exp_by_mok.items(), key=lambda kv: kv[1]) if exp_by_mok else None
        month_info[ym] = {
            "sum": ms,
            "count": len(mr),
            "end_bal": running_bal,
            "top_mok": top_mok,
        }

    sorted_years = sorted(years, reverse=True)
    default_year = sorted_years[0] if sorted_years else None
    year_chips = []
    year_sections = []
    for y in sorted_years:
        ytone = year_tone(y)
        y_months = sorted([ym for ym in months if ym.startswith(f"{y}-")], reverse=True)
        yr_r = [r for r in records if r["year"] == y]
        ys = summarize_period(yr_r)
        yr_end = month_info[y_months[0]]["end_bal"] if y_months else 0
        max_flow = max(
            [max(month_info[ym]["sum"]["inc"], month_info[ym]["sum"]["exp"]) for ym in y_months] or [1]
        ) or 1

        is_default = (y == default_year)
        year_chips.append(
            f"<button type='button' class='year-chip' data-filter-year='{y}' data-year-tone='{ytone}' aria-pressed='{str(is_default).lower()}'>"
            f"<span class='year-chip-swatch' aria-hidden='true'></span><span>{y}년 ({len(y_months)})</span></button>"
        )

        month_cards = []
        for ym in y_months:
            info = month_info[ym]
            ms = info["sum"]
            m_num = ym.split("-")[1]
            inc_pct = round(ms["inc"] / max_flow * 100) if ms["inc"] else 0
            exp_pct = round(ms["exp"] / max_flow * 100) if ms["exp"] else 0

            if info["top_mok"]:
                m_name, m_amt = info["top_mok"]
                hi_html = f"최대 지출: <strong>{html.escape(m_name)}</strong> ({fmt_man(m_amt)})"
            elif ms["tr_out"]:
                hi_html = f"지부 교부금 집행 ({fmt_man(ms['tr_out'])})"
            else:
                hi_html = "조합비 수납 중심 (사업 지출 없음)"

            month_cards.append(
                f"<article class='month-card'>"
                f"<div class='month-card-top'>"
                f"<span class='month-num'>{m_num}월</span>"
                f"<span class='month-tx-cnt'>{info['count']}건</span>"
                f"</div>"
                f"<div class='month-bars'>"
                f"<div class='month-bar-row'><span class='month-bar-label'>수입</span><div class='month-bar-track'><div class='month-bar-fill inc' style='--bar-pct: {inc_pct}%'></div></div><span class='month-bar-amt'>{fmt_man(ms['inc'])}</span></div>"
                f"<div class='month-bar-row'><span class='month-bar-label'>지출</span><div class='month-bar-track'><div class='month-bar-fill exp' style='--bar-pct: {exp_pct}%'></div></div><span class='month-bar-amt'>{fmt_man(ms['exp'])}</span></div>"
                f"</div>"
                f"<div class='month-highlight'>{hi_html}</div>"
                f"<div class='month-card-foot'>"
                f"<span class='month-bal'>잔액 <b>{fmt_won(info['end_bal'])}원</b></span>"
                f"<a class='month-open-link' href='monthly/{ym}.html' aria-label='{y}년 {int(m_num)}월 운영위원회 재정보고 열기'>보고서 보기 →</a>"
                f"</div>"
                f"</article>"
            )

        hidden_attr = "" if is_default else " hidden"
        year_sections.append(
            f"<section class='year-group' data-year='{y}' data-year-tone='{ytone}' aria-labelledby='yg-{y}'{hidden_attr}>"
            f"<div class='year-group-head'>"
            f"<div class='year-group-title'><h3 id='yg-{y}'>{y}년</h3><span class='year-group-count'>{len(y_months)}개월</span></div>"
            f"<div class='year-group-summary'>"
            f"<span>수입 {fmt_won(ys['inc'])}원 · 지출 {fmt_won(ys['exp'])}원 · 연말잔액 <b>{fmt_won(yr_end)}원</b></span>"
            f"<a class='year-annual-link' href='annual/{y}.html'>{y}년 결산 보기 →</a>"
            f"</div>"
            f"</div>"
            f"<div class='month-grid'>{''.join(month_cards)}</div>"
            f"</section>"
        )

    year_chips.append(
        f"<button type='button' class='year-chip' data-filter-year='all' aria-pressed='{str(default_year is None).lower()}'>전체 기간 ({len(months)}개월)</button>"
    )
    default_cnt = len([m for m in months if m.startswith(f"{default_year}-")]) if default_year else len(months)
    init_status = f"{default_year}년 {default_cnt}개월만 모아보는 중" if default_year else f"전체 기간 {len(months)}개월 표시 중"

    body = f"""
  <header class="page-masthead">
    <div>
      <h1>보고서 아카이브</h1>
      <p class="lead">연도별 격년 구분과 월별 핵심 지출 내역으로 재정 흐름을 차분하게 살펴볼 수 있습니다.</p>
    </div>
    <div class="masthead-meta">
      <span class="data-stamp">연간 {len(years)}건 · 월간 {len(months)}건</span>
    </div>
  </header>

  <section class="section-band" aria-labelledby="sec-annual-arch">
    <div class="section-head">
      <h2 id="sec-annual-arch">연간 대의원대회 결산 보고서</h2>
      <span class="section-sub">연도별 수지 결산 및 시각화 자료</span>
    </div>
    <div class="archive-grid">{''.join(ann_cards)}</div>
  </section>

  <section class="section-band" aria-labelledby="sec-monthly-arch">
    <div class="section-head">
      <h2 id="sec-monthly-arch">월간 운영위원회 재정보고 ({len(months)}개월)</h2>
      <span id="archive-filter-status" class="section-sub" aria-live="polite">{init_status}</span>
    </div>
    <div class="year-filter-bar" role="group" aria-label="연도별 보고서 필터">
      {''.join(year_chips)}
    </div>
    {''.join(year_sections)}
  </section>"""
    archive_script = """<script>
(function(){
  const chips = [...document.querySelectorAll(".year-chip")];
  const groups = [...document.querySelectorAll(".year-group")];
  const statusEl = document.getElementById("archive-filter-status");
  if (!chips.length || !groups.length) return;

  function applyArchiveFilter(target) {
    let activeChip = chips.find((c) => c.dataset.filterYear === target);
    if (!activeChip) {
      activeChip = chips.find((c) => c.dataset.filterYear !== "all") || chips[0];
    }
    if (!activeChip) return;
    const resolved = activeChip.dataset.filterYear;
    chips.forEach((c) => c.setAttribute("aria-pressed", String(c === activeChip)));
    let visibleCount = 0;
    groups.forEach((g) => {
      const match = resolved === "all" || g.dataset.year === resolved;
      g.hidden = !match;
      if (match) visibleCount += g.querySelectorAll(".month-card").length;
    });
    if (statusEl) {
      statusEl.textContent = resolved === "all"
        ? `전체 기간 ${visibleCount}개월 표시 중`
        : `${resolved}년 ${visibleCount}개월만 모아보는 중`;
    }
  }

  chips.forEach((chip) => {
    chip.addEventListener("click", () => applyArchiveFilter(chip.dataset.filterYear));
  });

  const currentYear = String(new Date().getFullYear());
  applyArchiveFilter(currentYear);
})();
</script>"""
    return render_shell("보고서 아카이브", "reports", "..", body, archive_script, "노동조합 월간·연간 재정보고 아카이브")


def main():
    p = argparse.ArgumentParser(description="공개용 정적 웹(_site) 생성기")
    p.add_argument("--ci", action="store_true", help="CI 모드: data/public/ledger_public.json만 사용해 빌드")
    args = p.parse_args()

    coa_cfg = json.loads((CONFIG_DIR / "coa.json").read_text(encoding="utf-8"))
    units_cfg = json.loads((CONFIG_DIR / "units.json").read_text(encoding="utf-8"))
    priv_path = CONFIG_DIR / "privacy.json"
    privacy_cfg = json.loads(priv_path.read_text(encoding="utf-8")) if priv_path.exists() else {}
    bundle = load_directory_bundle(CONFIG_DIR)

    DATA_PUBLIC.mkdir(parents=True, exist_ok=True)
    pub_json_path = DATA_PUBLIC / "ledger_public.json"

    raw_json_path = DATA_LATEST / "ledger.json"
    if not args.ci and raw_json_path.exists():
        raw_records = json.loads(raw_json_path.read_text(encoding="utf-8"))
        pub_records = sanitize_records(raw_records, privacy_cfg, bundle)
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

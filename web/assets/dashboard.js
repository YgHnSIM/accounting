(function () {
  const fmt = (n) => Number(n || 0).toLocaleString("ko-KR");

  let ALL_RECORDS = [];
  let META = {};
  const charts = {};
  let drillState = { gwan: null, hang: null };

  function readChartTheme() {
    const cs = getComputedStyle(document.documentElement);
    const tok = (name, fallback) => cs.getPropertyValue(name).trim() || fallback;
    return {
      palette: [
        tok("--chart-cobalt", "#1b4079"),
        tok("--chart-blue", "#2d63a8"),
        tok("--chart-income", "#1c6b4e"),
        tok("--chart-expense", "#b3461d"),
        tok("--chart-grant", "#9e6b08"),
        tok("--chart-teal", "#177278"),
        tok("--chart-plum", "#6b468c"),
        tok("--chart-slate", "#5c6473"),
      ],
      cobalt: tok("--chart-cobalt", "#1b4079"),
      blue: tok("--chart-blue", "#2d63a8"),
      income: tok("--chart-income", "#1c6b4e"),
      expense: tok("--chart-expense", "#b3461d"),
      grant: tok("--chart-grant", "#9e6b08"),
      grid: tok("--chart-grid", "rgba(118, 116, 108, 0.22)"),
      tick: tok("--chart-tick", "#4a505e"),
      tooltipBg: tok("--chart-tooltip-bg", "#16181d"),
      tooltipInk: tok("--chart-tooltip-ink", "#fcfcfa"),
      sheet: tok("--color-sheet", "#fcfcfa"),
      font: tok("--font-sans", "system-ui, sans-serif"),
    };
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function buildLedgerHref(params) {
    const sp = new URLSearchParams();
    if (params.year && params.year !== "전체") sp.set("year", params.year);
    if (params.gubun && params.gubun !== "전체") sp.set("gubun", params.gubun);
    if (params.gwan && params.gwan !== "전체") sp.set("gwan", params.gwan);
    if (params.q) sp.set("q", params.q);
    const qs = sp.toString();
    return qs ? `ledger.html?${qs}` : "ledger.html";
  }

  function summarize(recs) {
    let op = 0, inc = 0, exp = 0, trIn = 0, trOut = 0, adj = 0;
    for (const r of recs) {
      if (r.gubun === "기초이월") op += r.inc;
      else if (r.gubun === "수입") inc += r.inc;
      else if (r.gubun === "지출") exp += r.exp;
      else if (r.gubun === "내부이전(전입)") trIn += r.inc;
      else if (r.gubun === "내부이전(전출)") trOut += r.exp;
      else if (r.gubun === "이월차액") adj += r.inc - r.exp;
    }
    return { op, inc, exp, trIn, trOut, trNet: trIn - trOut, adj, net: inc - exp + (trIn - trOut) + adj };
  }

  function destroyChart(key) {
    if (charts[key]) {
      charts[key].destroy();
      delete charts[key];
    }
  }

  function getFilters() {
    return {
      year: document.getElementById("f-year").value,
      unit: document.getElementById("f-unit").value,
      fund: document.getElementById("f-fund").value,
    };
  }

  function baseScaleOpts(t) {
    return {
      grid: { color: t.grid },
      ticks: { color: t.tick, font: { family: t.font, size: 11 } },
      border: { color: t.grid },
    };
  }

  function basePluginOpts(t) {
    return {
      legend: { labels: { color: t.tick, font: { family: t.font, size: 11 }, boxWidth: 12 } },
      tooltip: { backgroundColor: t.tooltipBg, titleColor: t.tooltipInk, bodyColor: t.tooltipInk, padding: 10, cornerRadius: 4 },
    };
  }

  function applyFilters() {
    const f = getFilters();
    const matchUnitFund = (r) => (f.unit === "전체" || r.unit === f.unit) && (f.fund === "전체" || r.fund === f.fund);
    const scoped = ALL_RECORDS.filter(matchUnitFund);
    const filtered = f.year === "전체" ? scoped : scoped.filter((r) => String(r.year) === f.year);

    let priorBal = 0;
    if (f.year !== "전체") {
      const yNum = Number(f.year);
      for (const r of scoped) {
        if (r.year < yNum) priorBal += r.inc - r.exp;
      }
    }
    const sum = summarize(filtered);
    const opBal = priorBal + sum.op;
    const endBal = opBal + sum.net;

    document.getElementById("kpi-open").textContent = fmt(opBal) + "원";
    document.getElementById("kpi-inc").textContent = fmt(sum.inc) + "원";
    document.getElementById("kpi-exp").textContent = fmt(sum.exp) + "원";
    document.getElementById("kpi-tr").textContent = fmt(sum.trOut) + "원";
    document.getElementById("kpi-tr-sub").textContent = `환수·회수 ${fmt(sum.trIn)}원`;
    document.getElementById("kpi-end").textContent = fmt(endBal) + "원";
    document.getElementById("kpi-end-sub").textContent = `이월 조정 ${sum.adj >= 0 ? "+" : ""}${fmt(sum.adj)} · ${filtered.length}건`;

    const theme = readChartTheme();
    renderMonthlyChart(filtered, opBal, theme);
    renderDrillChart(filtered, theme);
    renderTopMokChart(filtered, theme);
    renderExpTypeChart(filtered, theme);
    renderDuesGrantChart(filtered, theme);
    renderSummaryTable(filtered, sum.exp || 1);
  }

  function renderMonthlyChart(filtered, opBal, t) {
    destroyChart("monthly");
    const yms = [...new Set(filtered.map((r) => r.ym).filter(Boolean))].sort();
    let run = opBal;
    const incs = [], exps = [], bals = [];
    for (const ym of yms) {
      const mr = filtered.filter((r) => r.ym === ym);
      const ms = summarize(mr);
      run += ms.net;
      incs.push(ms.inc);
      exps.push(ms.exp);
      bals.push(run);
    }

    const scroller = document.getElementById("monthly-scroll");
    const stage = document.getElementById("monthly-stage");
    const panHint = document.getElementById("monthly-pan-hint");
    const isWideSeries = yms.length > 14;
    if (stage) {
      stage.style.setProperty("--stage-min-width", isWideSeries ? `${Math.max(540, yms.length * 26)}px` : "100%");
    }
    if (panHint) {
      panHint.textContent = isWideSeries ? "← 좌우로 밀어 이전 월 탐색 (최신월 기준)" : "수입·지출 막대 및 잔액 꺾은선";
    }

    const ctx = document.getElementById("chart-monthly");
    charts.monthly = new Chart(ctx, {
      data: {
        labels: yms,
        datasets: [
          { type: "bar", label: "조합 수입", data: incs, backgroundColor: t.income, borderRadius: 2, yAxisID: "y" },
          { type: "bar", label: "사업 지출", data: exps, backgroundColor: t.expense, borderRadius: 2, yAxisID: "y" },
          { type: "line", label: "기말 잔액", data: bals, borderColor: t.cobalt, backgroundColor: t.cobalt, tension: 0.18, pointRadius: 2.5, borderWidth: 2, yAxisID: "y1" },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { ...baseScaleOpts(t), grid: { display: false } },
          y: { ...baseScaleOpts(t), beginAtZero: true, ticks: { ...baseScaleOpts(t).ticks, callback: (v) => fmt(v / 10000) + "만" } },
          y1: { ...baseScaleOpts(t), position: "right", grid: { drawOnChartArea: false }, ticks: { ...baseScaleOpts(t).ticks, callback: (v) => fmt(v / 10000) + "만" } },
        },
        plugins: {
          ...basePluginOpts(t),
          tooltip: { ...basePluginOpts(t).tooltip, callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y)}원` } },
        },
      },
    });

    if (scroller && isWideSeries) {
      requestAnimationFrame(() => {
        if (scroller.scrollWidth > scroller.clientWidth) {
          scroller.scrollLeft = scroller.scrollWidth;
        }
      });
    }
  }

  function updateDrillBreadcrumbs() {
    const bar = document.getElementById("drill-breadcrumbs");
    const parts = [`<button type="button" class="btn small ${!drillState.gwan ? "" : "secondary"}" data-level="root">전체 대분류</button>`];
    if (drillState.gwan) {
      parts.push(`<span aria-hidden="true">&rsaquo;</span><button type="button" class="btn small ${!drillState.hang ? "" : "secondary"}" data-level="gwan">${escapeHtml(drillState.gwan)}</button>`);
    }
    if (drillState.hang) {
      parts.push(`<span aria-hidden="true">&rsaquo;</span><span class="crumb-active">${escapeHtml(drillState.hang)}</span>`);
    }
    bar.innerHTML = parts.join("");
    bar.querySelectorAll("button").forEach((b) => {
      b.addEventListener("click", () => {
        if (b.dataset.level === "root") drillState = { gwan: null, hang: null };
        else if (b.dataset.level === "gwan") drillState = { gwan: drillState.gwan, hang: null };
        applyFilters();
      });
    });

    const dlLink = document.getElementById("drill-ledger-link");
    if (dlLink) {
      const f = getFilters();
      dlLink.href = buildLedgerHref({
        year: f.year,
        gubun: "지출",
        gwan: drillState.gwan || "전체",
        q: drillState.hang || "",
      });
      dlLink.textContent = drillState.hang
        ? `'${drillState.hang}' 거래 내역 보기 →`
        : drillState.gwan
          ? `'${drillState.gwan}' 거래 내역 보기 →`
          : "전체 지출 내역 보기 →";
    }
  }

  function renderDrillChart(filtered, t) {
    destroyChart("drill");
    updateDrillBreadcrumbs();
    const expRows = filtered.filter((r) => r.gubun === "지출");
    let field = "gwan";
    let scoped = expRows;
    if (drillState.gwan) {
      scoped = scoped.filter((r) => r.gwan === drillState.gwan);
      field = "hang";
    }
    if (drillState.hang) {
      scoped = scoped.filter((r) => r.hang === drillState.hang);
      field = "mok";
    }
    const agg = new Map();
    for (const r of scoped) {
      agg.set(r[field], (agg.get(r[field]) || 0) + r.exp);
    }
    const items = [...agg.entries()].sort((a, b) => b[1] - a[1]);
    const hint = document.getElementById("drill-hint");
    hint.textContent = field === "gwan" ? "막대를 누르면 중분류로 내려갑니다" : field === "hang" ? "막대를 누르면 세부활동으로 내려갑니다" : "막대를 누르면 해당 거래 내역으로 이동합니다";

    const ctx = document.getElementById("chart-drill");
    charts.drill = new Chart(ctx, {
      type: "bar",
      data: {
        labels: items.map((x) => x[0]),
        datasets: [{ label: "지출액", data: items.map((x) => x[1]), backgroundColor: items.map((_, i) => t.palette[i % t.palette.length]), borderRadius: 2 }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        onClick: (_, elements) => {
          if (!elements.length) return;
          const label = items[elements[0].index][0];
          if (field === "gwan") {
            drillState = { gwan: label, hang: null };
            renderDrillChart(filtered, readChartTheme());
          } else if (field === "hang") {
            drillState = { gwan: drillState.gwan, hang: label };
            renderDrillChart(filtered, readChartTheme());
          } else if (field === "mok") {
            window.location.href = buildLedgerHref({
              year: getFilters().year,
              gubun: "지출",
              gwan: drillState.gwan || "전체",
              q: label,
            });
          }
        },
        scales: {
          x: { ...baseScaleOpts(t), beginAtZero: true, ticks: { ...baseScaleOpts(t).ticks, callback: (v) => fmt(v / 10000) + "만" } },
          y: { ...baseScaleOpts(t), grid: { display: false } },
        },
        plugins: {
          ...basePluginOpts(t),
          legend: { display: false },
          tooltip: { ...basePluginOpts(t).tooltip, callbacks: { label: (c) => `${fmt(c.parsed.x)}원` } },
        },
      },
    });
  }

  function renderTopMokChart(filtered, t) {
    destroyChart("topMok");
    const agg = new Map();
    for (const r of filtered) {
      if (r.gubun === "지출") agg.set(r.mok, (agg.get(r.mok) || 0) + r.exp);
    }
    const items = [...agg.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10);
    charts.topMok = new Chart(document.getElementById("chart-top-mok"), {
      type: "bar",
      data: {
        labels: items.map((x) => x[0]),
        datasets: [{ label: "지출액", data: items.map((x) => x[1]), backgroundColor: t.blue, borderRadius: 2 }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { ...baseScaleOpts(t), beginAtZero: true, ticks: { ...baseScaleOpts(t).ticks, callback: (v) => fmt(v / 10000) + "만" } },
          y: { ...baseScaleOpts(t), grid: { display: false } },
        },
        plugins: {
          ...basePluginOpts(t),
          legend: { display: false },
          tooltip: { ...basePluginOpts(t).tooltip, callbacks: { label: (c) => `${fmt(c.parsed.x)}원` } },
        },
      },
    });
  }

  function renderExpTypeChart(filtered, t) {
    destroyChart("expType");
    const agg = new Map();
    for (const r of filtered) {
      if (r.gubun === "지출" && r.exp_type) agg.set(r.exp_type, (agg.get(r.exp_type) || 0) + r.exp);
    }
    const items = [...agg.entries()].sort((a, b) => b[1] - a[1]);
    charts.expType = new Chart(document.getElementById("chart-exp-type"), {
      type: "doughnut",
      data: {
        labels: items.map((x) => x[0]),
        datasets: [{
          data: items.map((x) => x[1]),
          backgroundColor: items.map((_, i) => t.palette[i % t.palette.length]),
          borderColor: t.sheet,
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { color: t.tick, boxWidth: 12, font: { family: t.font, size: 11 } } },
          tooltip: { ...basePluginOpts(t).tooltip, callbacks: { label: (c) => `${c.label}: ${fmt(c.parsed)}원` } },
        },
      },
    });
  }

  function renderDuesGrantChart(filtered, t) {
    destroyChart("duesGrant");
    const f = getFilters();
    const useYears = f.year === "전체";
    const keys = [...new Set(filtered.map((r) => (useYears ? String(r.year) : r.ym)).filter(Boolean))].sort();
    const dues = [], grants = [];
    for (const k of keys) {
      const sub = filtered.filter((r) => (useYears ? String(r.year) === k : r.ym === k));
      dues.push(sub.filter((r) => r.gwan === "조합비수입").reduce((a, b) => a + b.inc, 0));
      grants.push(sub.filter((r) => r.mok === "지부 교부금").reduce((a, b) => a + b.exp, 0));
    }
    charts.duesGrant = new Chart(document.getElementById("chart-dues-grant"), {
      type: "bar",
      data: {
        labels: keys,
        datasets: [
          { label: "정기조합비 수입", data: dues, backgroundColor: t.cobalt, borderRadius: 2 },
          { label: "지부 교부금", data: grants, backgroundColor: t.grant, borderRadius: 2 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { ...baseScaleOpts(t), grid: { display: false } },
          y: { ...baseScaleOpts(t), beginAtZero: true, ticks: { ...baseScaleOpts(t).ticks, callback: (v) => fmt(v / 10000) + "만" } },
        },
        plugins: {
          ...basePluginOpts(t),
          tooltip: { ...basePluginOpts(t).tooltip, callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y)}원` } },
        },
      },
    });
  }

  function renderSummaryTable(filtered, totExp) {
    const tbody = document.getElementById("summary-tbody");
    const agg = new Map();
    for (const r of filtered) {
      if (r.gubun !== "지출") continue;
      const key = `${r.gwan}|${r.hang}|${r.mok}`;
      const cur = agg.get(key) || { gwan: r.gwan, hang: r.hang, mok: r.mok, cnt: 0, amt: 0 };
      cur.cnt += 1;
      cur.amt += r.exp;
      agg.set(key, cur);
    }
    const items = [...agg.values()].sort((a, b) => b.amt - a.amt);
    const curYear = getFilters().year;
    tbody.innerHTML = items.map((it) => {
      const href = buildLedgerHref({ year: curYear, gubun: "지출", gwan: it.gwan, q: it.mok });
      return `
      <tr>
        <th scope="row"><a class="row-link" href="${escapeHtml(href)}">${escapeHtml(it.mok)}</a></th>
        <td data-label="대분류">${escapeHtml(it.gwan)}</td>
        <td data-label="중분류">${escapeHtml(it.hang)}</td>
        <td class="ctr" data-label="건수">${it.cnt}</td>
        <td class="num num-exp" data-label="지출액">${fmt(it.amt)}원</td>
        <td class="num" data-label="비중">${(it.amt / totExp * 100).toFixed(1)}%</td>
      </tr>`;
    }).join("");
  }

  function initScrollFadeFallback() {
    if (window.CSS && CSS.supports && CSS.supports("animation-timeline", "scroll()")) return;
    for (const scroller of document.querySelectorAll(".chart-scroll-x")) {
      const start = document.createElement("div");
      const end = document.createElement("div");
      for (const s of [start, end]) {
        s.setAttribute("aria-hidden", "true");
        s.style.cssText = "min-inline-size: 1px; min-block-size: 1px;";
      }
      scroller.prepend(start);
      scroller.append(end);
      const obs = new IntersectionObserver((entries) => {
        for (const e of entries) {
          scroller.classList.toggle(e.target === start ? "more-start" : "more-end", !e.isIntersecting);
        }
      }, { root: scroller, rootMargin: "1px" });
      obs.observe(start);
      obs.observe(end);
    }
  }

  function initChartDeck() {
    const track = document.getElementById("chart-deck-track");
    const tabsWrap = document.getElementById("chart-deck-tabs");
    const statusEl = document.getElementById("chart-deck-status");
    if (!track || !tabsWrap) return;

    const slides = [...track.querySelectorAll(".chart-card")];
    const tabs = [...tabsWrap.querySelectorAll(".chart-deck-tab")];
    let pendingIndex = null;
    let settledIndex = 0;
    let rafId = 0;

    function setActiveTab(idx) {
      tabs.forEach((btn, i) => {
        if (i === idx) btn.setAttribute("aria-current", "true");
        else btn.removeAttribute("aria-current");
      });
    }

    function nearestIndex() {
      const center = track.scrollLeft + track.clientWidth / 2;
      let best = 0;
      let bestDist = Infinity;
      slides.forEach((sl, i) => {
        const slCenter = sl.offsetLeft - track.offsetLeft + sl.offsetWidth / 2;
        const d = Math.abs(slCenter - center);
        if (d < bestDist) {
          bestDist = d;
          best = i;
        }
      });
      return best;
    }

    function onSettle() {
      pendingIndex = null;
      const idx = nearestIndex();
      setActiveTab(idx);
      if (idx !== settledIndex) {
        settledIndex = idx;
        if (statusEl && tabs[idx]) {
          statusEl.textContent = `${slides.length}개 차트 중 ${idx + 1}번째: ${tabs[idx].textContent}`;
        }
      }
    }

    tabs.forEach((btn, i) => {
      btn.addEventListener("click", () => {
        const slide = slides[i];
        if (!slide) return;
        pendingIndex = i;
        setActiveTab(i);
        const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        track.scrollTo({
          left: slide.offsetLeft - track.offsetLeft,
          behavior: reduce ? "auto" : "smooth",
        });
        btn.scrollIntoView({ block: "nearest", inline: "nearest" });
      });
    });

    track.addEventListener("scroll", () => {
      if (pendingIndex !== null || rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = 0;
        setActiveTab(nearestIndex());
      });
    }, { passive: true });

    if ("onscrollend" in window) {
      track.addEventListener("scrollend", onSettle);
    } else {
      let timer = 0;
      track.addEventListener("scroll", () => {
        clearTimeout(timer);
        timer = setTimeout(onSettle, 140);
      }, { passive: true });
    }
  }

  async function init() {
    let payload = window.__PUBLIC_LEDGER__;
    if (!payload) {
      const res = await fetch("data/public_ledger.json");
      payload = await res.json();
    }
    ALL_RECORDS = payload.records || [];
    META = payload.meta || {};
    if (META.syncedAt) {
      document.getElementById("sync-badge").textContent = `기준: ${META.monthsRange[0]} ~ ${META.monthsRange[1]} (${META.totalRecords}건)`;
    }

    const years = [...new Set(ALL_RECORDS.map((r) => r.year).filter(Boolean))].sort();
    const units = [...new Set(ALL_RECORDS.map((r) => r.unit).filter(Boolean))];
    const funds = [...new Set(ALL_RECORDS.map((r) => r.fund).filter(Boolean))];

    const fYear = document.getElementById("f-year");
    years.forEach((y) => fYear.add(new Option(`${y}년`, String(y))));
    const fUnit = document.getElementById("f-unit");
    units.forEach((u) => fUnit.add(new Option(u, u)));
    const fFund = document.getElementById("f-fund");
    funds.forEach((fd) => fFund.add(new Option(fd, fd)));

    [fYear, fUnit, fFund].forEach((el) => el.addEventListener("change", () => {
      drillState = { gwan: null, hang: null };
      applyFilters();
    }));
    document.getElementById("btn-reset").addEventListener("click", () => {
      fYear.value = "전체";
      fUnit.value = "전체";
      fFund.value = "전체";
      drillState = { gwan: null, hang: null };
      applyFilters();
    });

    if (window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyFilters);
    }

    initScrollFadeFallback();
    initChartDeck();
    applyFilters();
  }

  document.addEventListener("DOMContentLoaded", init);
})();

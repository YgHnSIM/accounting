(function () {
  const PALETTE = ["#1F4E78", "#2E75B6", "#4472C4", "#548235", "#BF9000", "#C55A11", "#843C0C", "#7030A0", "#0D9488", "#64748B"];
  const fmt = (n) => Number(n || 0).toLocaleString("ko-KR");
  const fmtMan = (n) => (Number(n || 0) / 10000).toLocaleString("ko-KR", { maximumFractionDigits: 1 }) + "만원";

  let ALL_RECORDS = [];
  let META = {};
  const charts = {};
  let drillState = { gwan: null, hang: null };

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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

  function applyFilters() {
    const f = getFilters();
    const matchUnitFund = (r) => (f.unit === "전체" || r.unit === f.unit) && (f.fund === "전체" || r.fund === f.fund);
    const scoped = ALL_RECORDS.filter(matchUnitFund);
    const filtered = f.year === "전체" ? scoped : scoped.filter((r) => String(r.year) === f.year);

    // Opening balance prior to selected year (only meaningful when fund=전체)
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

    renderMonthlyChart(filtered, opBal);
    renderDrillChart(filtered);
    renderTopMokChart(filtered);
    renderExpTypeChart(filtered);
    renderDuesGrantChart(filtered);
    renderSummaryTable(filtered, sum.exp || 1);
  }

  function renderMonthlyChart(filtered, opBal) {
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
    const ctx = document.getElementById("chart-monthly");
    charts.monthly = new Chart(ctx, {
      data: {
        labels: yms,
        datasets: [
          { type: "bar", label: "조합 수입", data: incs, backgroundColor: "rgba(46, 117, 182, 0.85)", yAxisID: "y" },
          { type: "bar", label: "사업 지출", data: exps, backgroundColor: "rgba(197, 90, 17, 0.85)", yAxisID: "y" },
          { type: "line", label: "기말 잔액", data: bals, borderColor: "#1F4E78", backgroundColor: "#1F4E78", tension: 0.2, pointRadius: 3, yAxisID: "y1" },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { beginAtZero: true, ticks: { callback: (v) => fmt(v / 10000) + "만" } },
          y1: { position: "right", grid: { drawOnChartArea: false }, ticks: { callback: (v) => fmt(v / 10000) + "만" } },
        },
        plugins: {
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y)}원` } },
        },
      },
    });
  }

  function updateDrillBreadcrumbs() {
    const bar = document.getElementById("drill-breadcrumbs");
    const parts = [`<button type="button" class="btn small ${!drillState.gwan ? "" : "secondary"}" data-level="root">전체 대분류</button>`];
    if (drillState.gwan) {
      parts.push(`<span>&rsaquo;</span><button type="button" class="btn small ${!drillState.hang ? "" : "secondary"}" data-level="gwan">${escapeHtml(drillState.gwan)}</button>`);
    }
    if (drillState.hang) {
      parts.push(`<span>&rsaquo;</span><span class="status-pill">${escapeHtml(drillState.hang)}</span>`);
    }
    bar.innerHTML = parts.join("");
    bar.querySelectorAll("button").forEach((b) => {
      b.addEventListener("click", () => {
        if (b.dataset.level === "root") drillState = { gwan: null, hang: null };
        else if (b.dataset.level === "gwan") drillState = { gwan: drillState.gwan, hang: null };
        applyFilters();
      });
    });
  }

  function renderDrillChart(filtered) {
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
    hint.textContent = field === "gwan" ? "막대를 누르면 중분류로 내려갑니다" : field === "hang" ? "막대를 누르면 세부활동으로 내려갑니다" : "세부활동별 상세 지출입니다";

    const ctx = document.getElementById("chart-drill");
    charts.drill = new Chart(ctx, {
      type: "bar",
      data: {
        labels: items.map((x) => x[0]),
        datasets: [{ label: "지출액", data: items.map((x) => x[1]), backgroundColor: PALETTE.slice(0, items.length) }],
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
            renderDrillChart(filtered);
          } else if (field === "hang") {
            drillState = { gwan: drillState.gwan, hang: label };
            renderDrillChart(filtered);
          }
        },
        scales: { x: { beginAtZero: true, ticks: { callback: (v) => fmt(v / 10000) + "만" } } },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => `${fmt(c.parsed.x)}원` } },
        },
      },
    });
  }

  function renderTopMokChart(filtered) {
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
        datasets: [{ label: "지출액", data: items.map((x) => x[1]), backgroundColor: "#2E75B6" }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: { x: { beginAtZero: true, ticks: { callback: (v) => fmt(v / 10000) + "만" } } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${fmt(c.parsed.x)}원` } } },
      },
    });
  }

  function renderExpTypeChart(filtered) {
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
        datasets: [{ data: items.map((x) => x[1]), backgroundColor: PALETTE.slice(0, items.length) }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { label: (c) => `${c.label}: ${fmt(c.parsed)}원` } },
        },
      },
    });
  }

  function renderDuesGrantChart(filtered) {
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
          { label: "정기조합비 수입", data: dues, backgroundColor: "#1F4E78" },
          { label: "지부 교부금", data: grants, backgroundColor: "#BF9000" },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true, ticks: { callback: (v) => fmt(v / 10000) + "만" } } },
        plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y)}원` } } },
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
    tbody.innerHTML = items.map((it) => `
      <tr>
        <th scope="row">${escapeHtml(it.mok)}</th>
        <td data-label="대분류">${escapeHtml(it.gwan)}</td>
        <td data-label="중분류">${escapeHtml(it.hang)}</td>
        <td class="ctr" data-label="건수">${it.cnt}</td>
        <td class="num" data-label="지출액">${fmt(it.amt)}원</td>
        <td class="num" data-label="비중">${(it.amt / totExp * 100).toFixed(1)}%</td>
      </tr>
    `).join("");
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
      document.getElementById("sync-badge").textContent = `데이터 기준: ${META.monthsRange[0]} ~ ${META.monthsRange[1]} (${META.totalRecords}건)`;
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

    applyFilters();
  }

  document.addEventListener("DOMContentLoaded", init);
})();

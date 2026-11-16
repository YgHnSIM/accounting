(function () {
  const fmt = (n) => (n ? Number(n).toLocaleString("ko-KR") : "");
  const PAGE_SIZE = 30;
  let ALL_RECORDS = [];
  let FILTERED = [];
  let curPage = 1;

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function applyFilters() {
    const yr = document.getElementById("l-year").value;
    const gb = document.getElementById("l-gubun").value;
    const gw = document.getElementById("l-gwan").value;
    const q = document.getElementById("l-query").value.trim().toLowerCase();

    FILTERED = ALL_RECORDS.filter((r) => {
      if (yr !== "전체" && String(r.year) !== yr) return false;
      if (gb !== "전체" && r.gubun !== gb) return false;
      if (gw !== "전체" && r.gwan !== gw) return false;
      if (q) {
        const hay = `${r.tx_id} ${r.date} ${r.gwan} ${r.hang} ${r.mok} ${r.exp_type} ${r.target} ${r.note}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    curPage = 1;
    renderPage();
  }

  function renderPage() {
    const total = FILTERED.length;
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (curPage > totalPages) curPage = totalPages;

    const sumIn = FILTERED.reduce((a, r) => a + r.inc, 0);
    const sumOut = FILTERED.reduce((a, r) => a + r.exp, 0);
    document.getElementById("ledger-stats").textContent = `검색 결과 ${total}건 · 입금합계 ${fmt(sumIn) || 0}원 · 출금합계 ${fmt(sumOut) || 0}원`;

    const slice = FILTERED.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE);
    const tbody = document.getElementById("ledger-tbody");
    tbody.innerHTML = slice.map((r) => {
      const rowCls = r.gubun === "이월차액" ? ' class="muted"' : "";
      const etCls = r.exp_type ? "ctr" : "ctr empty-cell";
      const inCls = r.inc ? "num" : "num empty-cell";
      const outCls = r.exp ? "num" : "num empty-cell";
      const noteCls = r.note ? "" : "empty-cell";
      return `<tr${rowCls}>
        <th scope="row">${escapeHtml(r.date)} · ${escapeHtml(r.mok)}</th>
        <td class="ctr" data-label="거래ID">${escapeHtml(r.tx_id)}</td>
        <td class="ctr" data-label="단위">${escapeHtml(r.unit)}</td>
        <td class="ctr" data-label="구분">${escapeHtml(r.gubun)}</td>
        <td data-label="계정(관·항·목)">${escapeHtml(r.gwan)} &gt; ${escapeHtml(r.hang)} &gt; <b>${escapeHtml(r.mok)}</b></td>
        <td class="${etCls}" data-label="지출형태">${escapeHtml(r.exp_type)}</td>
        <td class="ctr" data-label="대상·귀속">${escapeHtml(r.target)}${r.attr_ym ? " (" + escapeHtml(r.attr_ym) + ")" : ""}</td>
        <td class="${inCls}" data-label="수입금액">${fmt(r.inc)}</td>
        <td class="${outCls}" data-label="지출금액">${fmt(r.exp)}</td>
        <td class="${noteCls}" data-label="적요(비고)">${escapeHtml(r.note)}</td>
      </tr>`;
    }).join("");

    document.getElementById("page-info").textContent = `${curPage} / ${totalPages} 페이지`;
    document.getElementById("btn-prev").disabled = curPage <= 1;
    document.getElementById("btn-next").disabled = curPage >= totalPages;
  }

  function downloadCsv() {
    const header = ["거래ID", "회계단위", "연도", "보고월", "거래일자", "구분", "관", "항", "목", "지출형태", "재원구분", "대상", "귀속월", "수입금액", "지출금액", "적요"];
    const lines = [header.join(",")];
    for (const r of FILTERED) {
      const vals = [r.tx_id, r.unit, r.year, r.ym, r.date, r.gubun, r.gwan, r.hang, r.mok, r.exp_type, r.fund, r.target, r.attr_ym, r.inc || "", r.exp || "", r.note]
        .map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`);
      lines.push(vals.join(","));
    }
    const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "union_ledger_filtered.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function init() {
    let payload = window.__PUBLIC_LEDGER__;
    if (!payload) {
      const res = await fetch("data/public_ledger.json");
      payload = await res.json();
    }
    ALL_RECORDS = [...(payload.records || [])].reverse();

    const years = [...new Set(ALL_RECORDS.map((r) => r.year).filter(Boolean))].sort((a, b) => b - a);
    const gubuns = [...new Set(ALL_RECORDS.map((r) => r.gubun).filter(Boolean))];
    const gwans = [...new Set(ALL_RECORDS.map((r) => r.gwan).filter(Boolean))];

    const lYear = document.getElementById("l-year");
    years.forEach((y) => lYear.add(new Option(`${y}년`, String(y))));
    const lGubun = document.getElementById("l-gubun");
    gubuns.forEach((g) => lGubun.add(new Option(g, g)));
    const lGwan = document.getElementById("l-gwan");
    gwans.forEach((g) => lGwan.add(new Option(g, g)));

    [lYear, lGubun, lGwan].forEach((el) => el.addEventListener("change", applyFilters));
    document.getElementById("l-query").addEventListener("input", applyFilters);
    document.getElementById("btn-prev").addEventListener("click", () => { if (curPage > 1) { curPage--; renderPage(); } });
    document.getElementById("btn-next").addEventListener("click", () => { curPage++; renderPage(); });
    document.getElementById("btn-csv").addEventListener("click", downloadCsv);

    applyFilters();
  }

  document.addEventListener("DOMContentLoaded", init);
})();

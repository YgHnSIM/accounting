(function () {
  // Conditional Popover polyfill only when native support is missing
  if (!Object.hasOwn(HTMLElement.prototype, "popover")) {
    const s = document.createElement("script");
    s.src = "https://unpkg.com/@oddbird/popover-polyfill@latest/dist/popover.min.js";
    s.defer = true;
    document.head.appendChild(s);
  }

  // Theme Toggle (Light default, persistent light/dark override)
  const metaScheme = document.querySelector('meta[name="color-scheme"]');
  const themeBtn = document.getElementById("theme-toggle");

  function applyScheme(scheme) {
    const next = scheme === "dark" ? "dark" : "light";
    if (metaScheme) metaScheme.content = next;
    document.documentElement.dataset.theme = next;
    if (themeBtn) {
      themeBtn.setAttribute("aria-pressed", String(next === "dark"));
      themeBtn.setAttribute("aria-label", next === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환");
    }
    window.dispatchEvent(new CustomEvent("themechange", { detail: { theme: next } }));
  }

  if (themeBtn && metaScheme) {
    const curInitial = metaScheme.content === "dark" ? "dark" : "light";
    themeBtn.setAttribute("aria-pressed", String(curInitial === "dark"));
    themeBtn.setAttribute("aria-label", curInitial === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환");

    themeBtn.addEventListener("click", () => {
      const next = metaScheme.content === "dark" ? "light" : "dark";
      try {
        if (next === "light") localStorage.removeItem("color-scheme");
        else localStorage.setItem("color-scheme", next);
      } catch (_) {}
      applyScheme(next);
    });

    window.addEventListener("storage", (e) => {
      if (e.key === "color-scheme") {
        applyScheme(e.newValue === "dark" ? "dark" : "light");
      }
    });
  }

  // Responsive Navigation Bar
  const header = document.querySelector(".site-header");
  const inner = header ? header.querySelector(".header-inner") : null;
  const menu = document.getElementById("site-menu");
  if (!header || !inner || !menu) return;

  let lastWidth = inner.clientWidth;

  function updateLayout(forceCheck) {
    const isCurrentlyWide = header.classList.contains("is-wide");
    const curW = inner.clientWidth;
    if (!forceCheck && !isCurrentlyWide && curW <= lastWidth) {
      lastWidth = curW;
      return;
    }
    lastWidth = curW;

    const wasOpen = !isCurrentlyWide && menu.matches(":popover-open");
    header.classList.add("is-measuring", "is-wide");
    menu.removeAttribute("popover");

    const fits = inner.scrollWidth <= inner.clientWidth + 1;
    if (!fits) {
      header.classList.remove("is-wide");
      menu.setAttribute("popover", "auto");
      if (wasOpen && typeof menu.showPopover === "function") {
        try { menu.showPopover(); } catch (_) {}
      }
    }

    requestAnimationFrame(() => {
      header.classList.remove("is-measuring");
    });
  }

  const ro = new ResizeObserver(() => updateLayout(false));
  ro.observe(inner);
  ro.observe(menu);
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => updateLayout(true));
  }
  updateLayout(true);
})();

"use strict";

(() => {
  const PAGE_ASSETS = {
    "/ui/legacy/index.html": [
      "/ui/app.js?v=20260521-cleanup2",
      "/ui/market_clock.js?v=20260513-session-api1",
      "/ui/style.css?v=20260508-two-statuses1",
    ],
    "/ui/legacy/trading.html": [
      "/ui/market_clock.js?v=20260513-session-api1",
      "/ui/trading.js?v=20260629-final",
      "/ui/style.css",
    ],
    "/ui/legacy/performance.html": [
      "/ui/performance.js?v=20260519-performance-center2",
      "/ui/market_clock.js?v=20260513-session-api1",
      "/ui/style.css?v=20260519-performance-center1",
    ],
    "/ui/legacy/strategies.html": [
      "/ui/strategies.js?v=20260521-cleanup2",
      "/ui/market_clock.js?v=20260513-session-api1",
      "/ui/style.css?v=20260508-two-statuses1",
    ],
    "/ui/legacy/docs.html": [
      "/ui/docs.js?v=20260627-governance1",
      "/ui/style.css?v=20260627-governance1",
    ],
  };

  const prefetched = new Set();

  function prefetch(href, as) {
    if (!href || prefetched.has(href)) return;
    prefetched.add(href);
    const link = document.createElement("link");
    link.rel = "prefetch";
    link.href = href;
    if (as) link.as = as;
    document.head.appendChild(link);
  }

  function prefetchPage(pathname) {
    if (!pathname || pathname === window.location.pathname) return;
    prefetch(pathname, "document");
    for (const asset of PAGE_ASSETS[pathname] || []) {
      prefetch(asset, asset.includes(".css") ? "style" : "script");
    }
  }

  function navTargets() {
    return Array.from(document.querySelectorAll('.top-nav a[href^="/ui/"]'))
      .map((link) => link.getAttribute("href") || "")
      .filter(Boolean);
  }

  function scheduleWarmup() {
    const warm = () => {
      for (const href of navTargets()) prefetchPage(href);
    };
    if (typeof window.requestIdleCallback === "function") {
      window.requestIdleCallback(warm, { timeout: 1200 });
      return;
    }
    window.setTimeout(warm, 250);
  }

  document.addEventListener("DOMContentLoaded", () => {
    for (const link of document.querySelectorAll('.top-nav a[href^="/ui/"]')) {
      const href = link.getAttribute("href") || "";
      const prime = () => prefetchPage(href);
      link.addEventListener("mouseenter", prime, { passive: true, once: true });
      link.addEventListener("focus", prime, { passive: true, once: true });
      link.addEventListener("touchstart", prime, { passive: true, once: true });
    }
    scheduleWarmup();
  });
})();

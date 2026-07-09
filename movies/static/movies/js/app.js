/* OentBox — front-end interactions.
 * Hero carousel, scroll-to-top, bottom-nav active state, HTMX events,
 * infinite scroll trigger, PWA install prompt, native-app polish.
 */
(function () {
  "use strict";

  // -------- HTMX: configure CSRF token for all POST requests --------
  function setupCsrf() {
    if (typeof window.htmx === "undefined") {
      return setTimeout(setupCsrf, 100);
    }
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    if (csrfMeta) {
      var csrfToken = csrfMeta.getAttribute("content");
      document.body.addEventListener("htmx:configRequest", function (evt) {
        evt.detail.headers["X-CSRFToken"] = csrfToken;
      });
    }
  }
  setupCsrf();

  // -------- Helper: debounce --------
  function debounce(fn, ms) {
    var t;
    return function () {
      var ctx = this, args = arguments;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(ctx, args); }, ms || 250);
    };
  }

  // -------- Hero carousel --------
  function initHero() {
    var slides = document.querySelectorAll(".hero__slide");
    var dots = document.querySelectorAll(".hero__dot");
    var prev = document.getElementById("hero-prev");
    var next = document.getElementById("hero-next");
    if (slides.length < 2) return;

    var idx = 0;
    var timer = null;

    function show(n) {
      idx = (n + slides.length) % slides.length;
      slides.forEach(function (s, i) { s.classList.toggle("is-active", i === idx); });
      dots.forEach(function (d, i) { d.classList.toggle("is-active", i === idx); });
    }

    function nextSlide() { show(idx + 1); }
    function prevSlide() { show(idx - 1); }

    function startAuto() { stopAuto(); timer = setInterval(nextSlide, 6000); }
    function stopAuto() { if (timer) { clearInterval(timer); timer = null; } }

    if (next) next.addEventListener("click", function () { nextSlide(); startAuto(); });
    if (prev) prev.addEventListener("click", function () { prevSlide(); startAuto(); });
    dots.forEach(function (d, i) {
      d.addEventListener("click", function () { show(i); startAuto(); });
    });

    // Swipe support
    var hero = document.getElementById("hero");
    if (hero) {
      var startX = 0, startY = 0;
      hero.addEventListener("touchstart", function (e) {
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
        stopAuto();
      }, { passive: true });
      hero.addEventListener("touchend", function (e) {
        var dx = e.changedTouches[0].clientX - startX;
        var dy = e.changedTouches[0].clientY - startY;
        if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) {
          if (dx < 0) nextSlide(); else prevSlide();
        }
        startAuto();
      });
    }

    // Pause on hover (desktop)
    if (hero) {
      hero.addEventListener("mouseenter", stopAuto);
      hero.addEventListener("mouseleave", startAuto);
    }

    startAuto();
  }

  // -------- Scroll-to-top --------
  function initScrollTop() {
    var btn = document.getElementById("scrolltop");
    var main = document.getElementById("main");
    if (!btn || !main) return;
    function onScroll() {
      var show = window.scrollY > 400;
      btn.hidden = false;
      btn.classList.toggle("is-visible", show);
    }
    window.addEventListener("scroll", debounce(onScroll, 100), { passive: true });
    btn.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  // -------- Bottom nav active state --------
  function initBottomNav() {
    var path = window.location.pathname;
    document.querySelectorAll(".bottomnav__item").forEach(function (a) {
      var href = a.getAttribute("href");
      var active = false;
      if (href === "/" && path === "/") active = true;
      else if (href !== "/" && path.indexOf(href) === 0) active = true;
      a.classList.toggle("active", active);
      a.setAttribute("data-active", active ? "true" : "false");
    });
  }

  // -------- Topbar shadow on scroll --------
  function initTopbarShadow() {
    var topbar = document.getElementById("topbar");
    if (!topbar) return;
    function onScroll() {
      topbar.classList.toggle("is-scrolled", window.scrollY > 8);
    }
    window.addEventListener("scroll", debounce(onScroll, 50), { passive: true });
  }

  // -------- Row scroll: arrows on hover (desktop) --------
  function initRowScroll() {
    document.querySelectorAll(".row__scroller").forEach(function (scroller) {
      // already scrollable via touch; just enable wheel horizontal scroll
      scroller.addEventListener("wheel", function (e) {
        if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
          // vertical wheel -> horizontal scroll
          scroller.scrollLeft += e.deltaY;
          if (scroller.scrollLeft > 0 && scroller.scrollLeft < scroller.scrollWidth - scroller.clientWidth) {
            e.preventDefault();
          }
        }
      }, { passive: false });
    });
  }

  // -------- Suggestions dropdown: show/hide on focus --------
  function initSearchDropdown() {
    var form = document.querySelector(".topbar__search");
    var dropdown = document.getElementById("suggestions-dropdown");
    if (!form || !dropdown) return;

    form.addEventListener("htmx:after-request", function () {
      if (dropdown.innerHTML.trim()) {
        dropdown.hidden = false;
        dropdown.style.display = "block";
      }
    });

    document.addEventListener("click", function (e) {
      if (!form.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.hidden = true;
        dropdown.style.display = "none";
      }
    });

    form.querySelector("input").addEventListener("focus", function () {
      if (dropdown.innerHTML.trim()) {
        dropdown.hidden = false;
        dropdown.style.display = "block";
      }
    });

    form.querySelector("input").addEventListener("input", function () {
      if (!this.value.trim()) {
        dropdown.hidden = true;
        dropdown.style.display = "none";
      }
    });
  }

  // -------- PWA: register service worker --------
  function registerSW() {
    if ("serviceWorker" in navigator) {
      window.addEventListener("load", function () {
        navigator.serviceWorker.register("/sw.js").then(function (reg) {
          console.log("[MovieHub] SW registered:", reg.scope);
        }).catch(function (err) {
          console.warn("[MovieHub] SW registration failed:", err);
        });
      });
    }
  }

  // -------- PWA: install prompt --------
  var deferredPrompt = null;
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferredPrompt = e;
    showInstallBanner();
  });

  function showInstallBanner() {
    if (sessionStorage.getItem("install-dismissed")) return;
    var banner = document.createElement("div");
    banner.className = "install-banner";
    banner.innerHTML =
      '<div class="install-banner__body">' +
      '<div class="install-banner__icon">📱</div>' +
      '<div><div class="install-banner__title">Install MovieHub</div>' +
      '<div class="install-banner__sub">Add to home screen for a native-app experience</div></div>' +
      '</div>' +
      '<button class="btn btn--primary btn--sm" id="install-btn">Install</button>' +
      '<button class="install-banner__close" id="install-close" aria-label="Dismiss">×</button>';
    document.body.appendChild(banner);
    // Delay banner appearance so it doesn't disrupt first impression
    setTimeout(function () { banner.classList.add("is-visible"); }, 8000);
    // Auto-hide after 25s if user doesn't interact
    setTimeout(function () {
      if (banner.parentNode) {
        banner.classList.remove("is-visible");
        setTimeout(function () { if (banner.parentNode) banner.remove(); }, 500);
      }
    }, 33000);

    document.getElementById("install-btn").addEventListener("click", function () {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(function (c) {
          if (c.outcome === "accepted") console.log("[MovieHub] PWA installed");
          deferredPrompt = null;
          banner.remove();
        });
      }
    });
    document.getElementById("install-close").addEventListener("click", function () {
      sessionStorage.setItem("install-dismissed", "1");
      banner.remove();
    });
  }

  // -------- HTMX: handle after-swap animations --------
  document.body.addEventListener("htmx:afterSwap", function (e) {
    // Re-init row scrolling for newly swapped rows
    if (e.detail && e.detail.target && e.detail.target.classList.contains("row__track")) {
      // already handled
    }
  });

  // -------- Native feel: prevent double-tap zoom on iOS --------
  var lastTouch = 0;
  document.addEventListener("touchend", function (e) {
    var now = Date.now();
    if (now - lastTouch < 300) e.preventDefault();
    lastTouch = now;
  }, { passive: false });

  // -------- Trailer click-to-load (saves bandwidth + faster page load) --------
  function initTrailer() {
    var poster = document.getElementById("trailer-poster");
    var iframe = document.getElementById("trailer-iframe");
    if (!poster || !iframe) return;
    poster.addEventListener("click", function () {
      iframe.src = iframe.getAttribute("data-src");
      iframe.style.display = "block";
      poster.style.display = "none";
    });
  }

  // -------- Init on DOM ready --------
  function init() {
    initHero();
    initScrollTop();
    initBottomNav();
    initTopbarShadow();
    initRowScroll();
    initSearchDropdown();
    initTrailer();
    registerSW();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

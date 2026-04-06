/**
 * Open Canon Site – Mobile navigation sidebar toggle
 *
 * Wires up the hamburger button (#nav-toggle) to show/hide the
 * sidebar (.sidebar-nav) as a slide-in drawer on narrow viewports.
 * Also handles the backdrop overlay, ESC key, and closing when a
 * nav link is followed.
 */
(function () {
  "use strict";

  var toggle  = document.getElementById("nav-toggle");
  var sidebar = document.querySelector(".sidebar-nav");
  var overlay = document.getElementById("nav-overlay");

  if (!toggle || !sidebar) return;

  function openNav() {
    sidebar.classList.add("is-open");
    if (overlay) {
      overlay.classList.add("is-open");
      overlay.setAttribute("aria-hidden", "false");
    }
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Close navigation");
    document.body.classList.add("nav-open");
  }

  function closeNav() {
    sidebar.classList.remove("is-open");
    if (overlay) {
      overlay.classList.remove("is-open");
      overlay.setAttribute("aria-hidden", "true");
    }
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open navigation");
    document.body.classList.remove("nav-open");
  }

  toggle.addEventListener("click", function () {
    if (sidebar.classList.contains("is-open")) {
      closeNav();
    } else {
      openNav();
    }
  });

  if (overlay) {
    overlay.addEventListener("click", closeNav);
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && sidebar.classList.contains("is-open")) closeNav();
  });

  // Close the drawer when the user follows a nav link (navigating away).
  sidebar.querySelectorAll("a").forEach(function (link) {
    link.addEventListener("click", closeNav);
  });
})();

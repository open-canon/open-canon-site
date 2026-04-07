/**
 * Open Canon Site – Mobile navigation sidebar toggle + note popup
 *
 * Wires up the hamburger button (#nav-toggle) to show/hide the
 * sidebar (.sidebar-nav) as a slide-in drawer on narrow viewports.
 * Also handles the backdrop overlay, ESC key, and closing when a
 * nav link is followed.
 *
 * Additionally, intercepts clicks on note markers (.note-marker a) when the
 * notes tray is hidden (mobile/tablet) and displays the note content in a
 * bottom-sheet popup (#note-popup) instead of attempting to scroll to the
 * hidden tray.
 */
(function () {
  "use strict";

  /* ── Sidebar drawer ── */

  var toggle  = document.getElementById("nav-toggle");
  var sidebar = document.querySelector(".sidebar-nav");
  var overlay = document.getElementById("nav-overlay");

  if (toggle && sidebar) {
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
  }

  /* ── Note popup (shown when the notes tray is hidden) ── */

  var notePopup     = document.getElementById("note-popup");
  var notePopupRef  = document.getElementById("note-popup-ref");
  var notePopupText = document.getElementById("note-popup-text");
  var notePopupClose = document.getElementById("note-popup-close");

  if (notePopup && notePopupText) {
    function isNotesTrayHidden() {
      var tray = document.querySelector(".notes-tray");
      return !tray || getComputedStyle(tray).display === "none";
    }

    function openNotePopup(noteEl) {
      var refEl = noteEl.querySelector(".note-verse-ref");
      var textEl = noteEl.querySelector(".note-text");
      notePopupRef.textContent  = refEl  ? refEl.textContent  : "";
      notePopupText.innerHTML   = textEl ? textEl.innerHTML   : "";
      notePopup.classList.add("is-open");
      notePopup.setAttribute("aria-hidden", "false");
    }

    function closeNotePopup() {
      notePopup.classList.remove("is-open");
      notePopup.setAttribute("aria-hidden", "true");
    }

    if (notePopupClose) {
      notePopupClose.addEventListener("click", closeNotePopup);
    }

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && notePopup.classList.contains("is-open")) closeNotePopup();
    });

    // Intercept note marker link clicks when the tray is not visible.
    document.querySelectorAll(".note-marker a").forEach(function (link) {
      link.addEventListener("click", function (e) {
        if (!isNotesTrayHidden()) return;  // tray is visible; let the browser scroll normally
        var targetId = (link.getAttribute("href") || "").replace(/^#/, "");
        var noteEl = targetId ? document.getElementById(targetId) : null;
        if (noteEl) {
          e.preventDefault();
          openNotePopup(noteEl);
        }
      });
    });
  }
})();

/**
 * Open Canon Site – Theme (dark/light mode) script
 *
 * Apply saved preference before first paint to avoid a flash of the wrong
 * theme. Run this script as early as possible (ideally in <head>).
 *
 * Storage key: "oc-theme"  Values: "dark" | "light"
 * If absent, the system preference (prefers-color-scheme) drives the UI.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "oc-theme";
  var DARK = "dark";
  var LIGHT = "light";

  /** Apply or remove the data-theme attribute on <html>. */
  function applyTheme(theme) {
    if (theme === DARK || theme === LIGHT) {
      document.documentElement.setAttribute("data-theme", theme);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }

  /** Return the current effective theme ("dark" or "light"). */
  function effectiveTheme() {
    var stored = localStorage.getItem(STORAGE_KEY);
    if (stored === DARK || stored === LIGHT) return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? DARK : LIGHT;
  }

  // Apply theme immediately to avoid FOUC.
  var saved = localStorage.getItem(STORAGE_KEY);
  if (saved) applyTheme(saved);

  // Wire up toggle button(s) once the DOM is ready.
  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;

    function updateButton() {
      var isDark = effectiveTheme() === DARK;
      btn.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
      btn.textContent = isDark ? "☀" : "🌙";
    }

    btn.addEventListener("click", function () {
      var next = effectiveTheme() === DARK ? LIGHT : DARK;
      localStorage.setItem(STORAGE_KEY, next);
      applyTheme(next);
      updateButton();
    });

    updateButton();
  });
})();

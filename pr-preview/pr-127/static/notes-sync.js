/**
 * Open Canon Site – Notes tray alignment script
 *
 * Watches which verse is closest to the top of the visible content area and
 * scrolls the notes tray so that the corresponding note (if any) is visible
 * near the top of the tray.
 */
(function () {
  "use strict";

  /** @type {HTMLElement|null} */
  const trayInner = document.querySelector(".notes-tray-inner");
  if (!trayInner) return;

  /** Map of verse-id → note element in the tray */
  const noteMap = /** @type {Map<string, HTMLElement>} */ (new Map());
  trayInner.querySelectorAll(".note-item[data-verse]").forEach((el) => {
    const vid = /** @type {HTMLElement} */ (el).dataset.verse;
    if (vid) noteMap.set(vid, /** @type {HTMLElement} */ (el));
  });

  if (noteMap.size === 0) return;

  /** All verse elements in reading order */
  const verseEls = /** @type {HTMLElement[]} */ (
    Array.from(document.querySelectorAll(".verse[data-verse]"))
  );

  let ticking = false;

  /**
   * Find the verse element that is closest to (but not above) the top of the
   * viewport (with a small offset for the fixed header).
   * @returns {string|null} osisId of the nearest verse
   */
  function getNearestVerseId() {
    const headerH = parseInt(
      getComputedStyle(document.documentElement).getPropertyValue("--header-h") || "52",
      10
    );
    const threshold = headerH + 8;

    let best = null;
    let bestDist = Infinity;

    for (const el of verseEls) {
      const rect = el.getBoundingClientRect();
      // Distance below the threshold line (negative if above)
      const dist = rect.top - threshold;
      if (dist >= 0 && dist < bestDist) {
        bestDist = dist;
        best = el.dataset.verse;
      }
    }

    // If nothing below threshold, take the last one that scrolled past
    if (best === null) {
      let latestTop = -Infinity;
      for (const el of verseEls) {
        const rect = el.getBoundingClientRect();
        if (rect.top <= threshold && rect.top > latestTop) {
          latestTop = rect.top;
          best = el.dataset.verse;
        }
      }
    }

    return best;
  }

  /** @type {string|null} */
  let lastVid = null;

  function syncTray() {
    ticking = false;
    const vid = getNearestVerseId();
    if (!vid || vid === lastVid) return;
    lastVid = vid;

    // Remove active highlight from all notes
    trayInner.querySelectorAll(".note-item.active").forEach((el) => {
      el.classList.remove("active");
    });

    // Highlight the matching note
    const noteEl = noteMap.get(vid);
    if (noteEl) {
      noteEl.classList.add("active");
      // Scroll the tray so the note is near the top
      trayInner.scrollTo({
        top: noteEl.offsetTop - 12,
        behavior: "smooth",
      });
    }

    // Also highlight the verse in the main text
    document.querySelectorAll(".verse.note-highlighted").forEach((el) => {
      el.classList.remove("note-highlighted");
    });
    const verseEl = document.querySelector(`.verse[data-verse="${CSS.escape(vid)}"]`);
    if (verseEl && noteMap.has(vid)) {
      verseEl.classList.add("note-highlighted");
    }
  }

  window.addEventListener("scroll", () => {
    if (!ticking) {
      requestAnimationFrame(syncTray);
      ticking = true;
    }
  }, { passive: true });

  // Initial sync on load
  syncTray();
})();

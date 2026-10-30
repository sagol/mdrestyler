(function () {
  "use strict";

  // 1. Theme: a saved choice first, then the system preference, dark by default.
  var root = document.documentElement;
  var themeToggle = document.getElementById("theme-toggle");
  var savedTheme = null;

  try {
    savedTheme = localStorage.getItem("mdrestyler-theme");
  } catch (e) {
    savedTheme = null;
  }

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    if (themeToggle) {
      themeToggle.textContent = theme === "light" ? "Dark theme" : "Light theme";
      themeToggle.setAttribute(
        "aria-label",
        theme === "light" ? "Switch to dark theme" : "Switch to light theme"
      );
    }
  }

  if (savedTheme === "light" || savedTheme === "dark") {
    applyTheme(savedTheme);
  } else if (
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: light)").matches
  ) {
    applyTheme("light");
  } else {
    applyTheme("dark");
  }

  // Colours change without a transition until the first theme is applied, so a light-preference visitor sees no fade.
  window.requestAnimationFrame(function () {
    window.requestAnimationFrame(function () {
      root.setAttribute("data-theme-ready", "");
    });
  });

  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      applyTheme(next);
      try {
        localStorage.setItem("mdrestyler-theme", next);
      } catch (e) {
        // Storage can be unavailable in private windows; the theme still applies.
      }
    });
  }

  // 2. Install tabs (WAI-ARIA tabs pattern). Without JavaScript every panel stays visible.
  var tabButtons = Array.prototype.slice.call(
    document.querySelectorAll('[role="tab"]')
  );
  var tabPanels = Array.prototype.slice.call(
    document.querySelectorAll('[role="tabpanel"]')
  );
  var panelTitles = Array.prototype.slice.call(
    document.querySelectorAll(".tab-panel-title")
  );

  if (tabButtons.length > 0) {
    panelTitles.forEach(function (el) {
      el.setAttribute("hidden", "hidden");
    });
  }

  function activateTab(selectedBtn, focusTab) {
    var targetId = selectedBtn.getAttribute("aria-controls");
    tabButtons.forEach(function (btn) {
      var isSelected = btn === selectedBtn;
      btn.setAttribute("aria-selected", isSelected ? "true" : "false");
      btn.setAttribute("tabindex", isSelected ? "0" : "-1");
      if (isSelected && focusTab) {
        btn.focus();
      }
    });
    tabPanels.forEach(function (panel) {
      if (panel.id === targetId) {
        panel.removeAttribute("hidden");
      } else {
        panel.setAttribute("hidden", "hidden");
      }
    });
  }

  if (tabButtons.length > 0) {
    var initialTab = tabButtons[0];
    tabButtons.forEach(function (b) {
      if (b.getAttribute("aria-selected") === "true") {
        initialTab = b;
      }
    });
    activateTab(initialTab, false);
  }

  tabButtons.forEach(function (btn, index) {
    btn.addEventListener("click", function () {
      activateTab(btn, false);
    });
    btn.addEventListener("keydown", function (e) {
      var nextIndex = null;
      if (e.key === "ArrowRight") {
        nextIndex = (index + 1) % tabButtons.length;
      } else if (e.key === "ArrowLeft") {
        nextIndex = (index - 1 + tabButtons.length) % tabButtons.length;
      } else if (e.key === "Home") {
        nextIndex = 0;
      } else if (e.key === "End") {
        nextIndex = tabButtons.length - 1;
      }
      if (nextIndex !== null) {
        e.preventDefault();
        activateTab(tabButtons[nextIndex], true);
      }
    });
  });

  // 3. Copy buttons, with a selection fallback and a live-region announcement.
  var copyButtons = Array.prototype.slice.call(
    document.querySelectorAll(".copy-btn")
  );
  var copyLive = document.getElementById("copy-status-live");
  var copyTimers = new WeakMap();

  function selectCodeElement(codeEl) {
    try {
      var selection = window.getSelection ? window.getSelection() : null;
      if (selection && document.createRange) {
        var range = document.createRange();
        range.selectNodeContents(codeEl);
        selection.removeAllRanges();
        selection.addRange(range);
        return true;
      }
    } catch (e) {
      // Selection is a fallback only.
    }
    return false;
  }

  function setCopyFeedback(btn, label, liveMsg) {
    var defaultLabel = btn.getAttribute("data-default-label") || "Copy";
    var prevTimer = copyTimers.get(btn);
    if (prevTimer) {
      clearTimeout(prevTimer);
    }
    btn.textContent = label;
    if (copyLive) {
      copyLive.textContent = liveMsg;
    }
    copyTimers.set(
      btn,
      setTimeout(function () {
        btn.textContent = defaultLabel;
        copyTimers.delete(btn);
      }, 2000)
    );
  }

  function copyFallback(btn, codeEl) {
    var selected = selectCodeElement(codeEl);
    setCopyFeedback(
      btn,
      selected ? "Text selected" : "Copy failed",
      selected
        ? "Copy is unavailable. The text is selected; press Ctrl+C or Command+C."
        : "Could not copy. Select the text and copy it by hand."
    );
  }

  copyButtons.forEach(function (btn) {
    btn.setAttribute("data-default-label", btn.textContent || "Copy");
    btn.addEventListener("click", function () {
      var targetId = btn.getAttribute("data-copy-target");
      var codeEl = targetId ? document.getElementById(targetId) : null;
      if (!codeEl) {
        return;
      }
      var text = codeEl.textContent || "";
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(
          function () {
            setCopyFeedback(btn, "Copied", "Copied to the clipboard.");
          },
          function () {
            copyFallback(btn, codeEl);
          }
        );
      } else {
        copyFallback(btn, codeEl);
      }
    });
  });

  // 4. Filter the commands table by any word in a row.
  var searchInput = document.getElementById("command-search");
  var rows = Array.prototype.slice.call(
    document.querySelectorAll("#command-rows tr")
  );
  var countStatus = document.getElementById("command-count");

  function filterRows() {
    var query = searchInput ? searchInput.value.trim().toLowerCase() : "";
    var visible = 0;
    rows.forEach(function (row) {
      var match = !query || (row.textContent || "").toLowerCase().indexOf(query) !== -1;
      if (match) {
        row.removeAttribute("hidden");
        visible += 1;
      } else {
        row.setAttribute("hidden", "hidden");
      }
    });
    if (countStatus) {
      countStatus.textContent =
        "Showing " + visible + " of " + rows.length + " commands";
    }
  }

  var filterBox = document.getElementById("command-filter");
  if (searchInput && rows.length > 0) {
    if (filterBox) {
      filterBox.removeAttribute("hidden");
    }
    filterRows();
    searchInput.addEventListener("input", filterRows);
  }
})();

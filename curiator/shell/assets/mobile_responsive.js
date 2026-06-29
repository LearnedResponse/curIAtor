/* mobile_responsive.js — auto-loaded by every app in this dir (Dash default assets/).
 *
 * The apps are desktop multi-column flex layouts; on a phone (esp. portrait) they should
 * collapse to ONE scrollable column. This does it globally, with no per-app edits:
 *   (1) inject a width=device-width viewport meta (Dash apps usually lack it, so phones
 *       render at ~980px and zoom out -> the "cramped grid" look);
 *   (2) on narrow screens, turn page-level flex-ROW containers into a column and make
 *       their children full-width / auto-height; restore the originals on desktop.
 * Conservative: only acts on width <= BP, only on TALL row containers with >=2 children
 * (the main columns), never on small flex rows (button groups). Idempotent + reversible.
 */
(function () {
  var BP = 820;

  // (1) viewport meta (for apps opened directly; in the shell the parent provides it)
  try {
    if (!document.querySelector('meta[name="viewport"]')) {
      var m = document.createElement("meta");
      m.name = "viewport";
      m.content = "width=device-width, initial-scale=1";
      (document.head || document.documentElement).appendChild(m);
    }
  } catch (e) {}

  function isRowFlex(el, cs) {
    if (cs.display !== "flex") return false;
    var d = cs.flexDirection || "row";
    return d.indexOf("row") === 0;
  }

  function collapse() {
    try {
      var mobile = window.innerWidth <= BP;
      var vh = window.innerHeight || 800;
      var root = document.getElementById("react-entry-point") || document.body;
      if (!root) return;
      var divs = root.getElementsByTagName("div");
      for (var i = 0; i < divs.length; i++) {
        var el = divs[i];
        var cs = window.getComputedStyle(el);
        var tall = el.getBoundingClientRect().height >= 0.55 * vh;
        var target = isRowFlex(el, cs) && tall && el.children.length >= 2;
        if (mobile && target && !el.__mobCollapsed) {
          el.__mobCollapsed = true;
          el.__origStyle = el.getAttribute("style") || "";
          el.style.flexDirection = "column";
          el.style.height = "auto";
          el.style.minHeight = "100vh";
          for (var c = 0; c < el.children.length; c++) {
            var ch = el.children[c];
            ch.__origStyle = ch.getAttribute("style") || "";
            ch.style.width = "100%";
            ch.style.maxWidth = "100%";
            ch.style.flex = "0 0 auto";
            var sty = ch.__origStyle;
            if (/height\s*:\s*[0-9.]+vh/i.test(sty) || /height\s*:\s*100%/i.test(sty) ||
                /height\s*:\s*calc/i.test(sty)) {
              ch.style.height = "auto";
              ch.style.minHeight = "320px";
            }
          }
        } else if (!mobile && el.__mobCollapsed) {
          el.__mobCollapsed = false;
          el.setAttribute("style", el.__origStyle || "");
          for (var k = 0; k < el.children.length; k++) {
            var kid = el.children[k];
            if (kid.__origStyle !== undefined) kid.setAttribute("style", kid.__origStyle);
          }
        }
      }
    } catch (e) {}
  }

  var timer = null;
  function schedule() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(collapse, 150);
  }

  window.addEventListener("resize", schedule);
  // Dash renders the layout asynchronously and re-renders on callbacks: re-run on DOM growth.
  function watch() {
    var root = document.getElementById("react-entry-point");
    if (!root) { setTimeout(watch, 200); return; }
    try { new MutationObserver(schedule).observe(root, { childList: true, subtree: true }); } catch (e) {}
    collapse();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
  setTimeout(collapse, 500);
  setTimeout(collapse, 1500);
})();

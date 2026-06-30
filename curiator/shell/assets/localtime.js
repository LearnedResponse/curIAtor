// Render feedback timestamps in the VIEWER's local timezone.
// Stored timestamps are UTC (tz-aware), so `new Date(iso)` converts unambiguously. Each timestamp is
// emitted as <span class="ts" data-ts="<iso>">…</span>; we replace the text with a compact local string
// and put the full local datetime in the tooltip. A MutationObserver keeps re-rendered feedback lists
// (the Dash sidebar) localized; the same script, loaded in the /general iframe, handles that view too.
(function () {
  function fmt(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    if (isNaN(d.getTime())) return null;                       // unparseable → leave the raw text
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }
  function one(el) {
    if (el.getAttribute("data-localized")) return;
    var iso = el.getAttribute("data-ts");
    var s = fmt(iso);
    if (s) {
      el.textContent = s;
      try { el.title = new Date(iso).toLocaleString(); } catch (e) {}
      el.setAttribute("data-localized", "1");
    }
  }
  function scan(root) {
    if (root && root.nodeType === 1 && root.classList && root.classList.contains("ts")) one(root);
    var els = root && root.querySelectorAll ? root.querySelectorAll(".ts[data-ts]") : [];
    for (var i = 0; i < els.length; i++) one(els[i]);
  }
  function run() { scan(document); }
  if (document.readyState !== "loading") run();
  else document.addEventListener("DOMContentLoaded", run);

  try {
    var mo = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var added = muts[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          if (added[j].nodeType === 1) scan(added[j]);
        }
      }
    });
    mo.observe(document.body || document.documentElement, { childList: true, subtree: true });
  } catch (e) {}
})();

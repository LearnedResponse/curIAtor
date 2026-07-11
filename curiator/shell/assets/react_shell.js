(function () {
  const h = React.createElement;
  const {useEffect, useMemo, useRef, useState} = React;
  const STATUS = {
    new: "#cc7a00",
    working: "#8e44ad",
    done: "#1f9d55",
    awaiting_approval: "#2980b9",
    held: "#6f42c1",
    rejected: "#555"
  };
  const DICTATION_HINT = "OS dictation can type feedback here.";
  const NEW_APP_TYPES = [
    ["dash", "Dash"],
    ["react_node", "React + Node"],
    ["rust", "Rust server"],
    ["react_rust", "React + Rust"],
    ["github_repo", "GitHub repo"],
    ["pyodide_wasm", "Pyodide / WASM"],
    ["static", "Static HTML"],
    ["other", "Other (will try to accommodate)"]
  ];

  function api(path, opts) {
    return fetch(path, Object.assign({headers: {"content-type": "application/json"}}, opts || {}))
      .then((r) => r.ok ? r.json() : r.json().catch(() => ({})).then((j) => Promise.reject(j)));
  }

  function wordmark(size) {
    return h("span", {style: {fontWeight: 800, fontSize: size || 16}},
      h("span", {className: "ia"}, "◆ "), "cur", h("span", {className: "ia"}, "IA"), "tor");
  }

  function ts(iso) {
    if (!iso) return null;
    return h("span", {className: "ts", "data-ts": iso, title: iso}, iso);
  }

  function appSrc(key, generalKey, revision, extraQuery) {
    if (!key) return "";
    if (key === generalKey) return "/general";
    const base = "/app/" + encodeURIComponent(key) + "/";
    // Forward any deep-link query args (e.g. ?node=crit) to the mounted app, plus the reload cache-buster.
    const params = new URLSearchParams(extraQuery || "");
    const rev = Number(revision) || 0;
    if (rev) params.set("v", String(rev));
    const qs = params.toString();
    return qs ? base + "?" + qs : base;
  }

  function tree(items) {
    const byId = new Map(items.map((e, i) => [e.id, Object.assign({__i: i}, e)]));
    const children = {};
    const roots = [];
    items.forEach((e, i) => {
      const ids = (e.reply_to || []).filter((id) => byId.has(id));
      const parent = ids.length ? ids[ids.length - 1] : null;
      const item = byId.get(e.id) || Object.assign({__i: i}, e);
      if (parent) (children[parent] = children[parent] || []).push(item);
      else roots.push(item);
    });
    function activity(e) {
      return Math.max(e.__i, ...((children[e.id] || []).map(activity)));
    }
    roots.sort((a, b) => activity(b) - activity(a));
    return {roots, children};
  }

  function actor(e) {
    if (e.kind === "system" || e.author === "claude") return e.agent || "Claude";
    return (e.user && e.user.name) || "user";
  }

  function excerpt(e) {
    const text = (e.comment || "").replace(/\s+/g, " ").trim() || (e.stars ? "★".repeat(e.stars) : "");
    return text.length > 110 ? text.slice(0, 110) + "…" : text;
  }

  function drawAnnotation(ctx, mark, width, height) {
    const x1 = mark.x1 * width;
    const y1 = mark.y1 * height;
    const x2 = (mark.x2 == null ? mark.x1 : mark.x2) * width;
    const y2 = (mark.y2 == null ? mark.y1 : mark.y2) * height;
    ctx.save();
    ctx.lineWidth = Math.max(3, Math.round(width / 240));
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    if (mark.tool === "redact") {
      ctx.fillStyle = "#111";
      ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
    } else if (mark.tool === "box") {
      ctx.strokeStyle = "#8e44ad";
      ctx.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
    } else if (mark.tool === "arrow") {
      const angle = Math.atan2(y2 - y1, x2 - x1);
      const head = Math.max(14, Math.round(width / 35));
      ctx.strokeStyle = "#2980b9";
      ctx.fillStyle = "#2980b9";
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(x2 - head * Math.cos(angle - Math.PI / 6), y2 - head * Math.sin(angle - Math.PI / 6));
      ctx.lineTo(x2 - head * Math.cos(angle + Math.PI / 6), y2 - head * Math.sin(angle + Math.PI / 6));
      ctx.closePath();
      ctx.fill();
    } else if (mark.tool === "pin") {
      const radius = Math.max(12, Math.round(width / 36));
      ctx.fillStyle = "#cc7a00";
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = Math.max(2, Math.round(width / 360));
      ctx.beginPath();
      ctx.arc(x1, y1, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.font = "700 " + Math.max(13, Math.round(radius * .9)) + "px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(mark.n || 1), x1, y1);
    }
    ctx.restore();
  }

  function annotationLabel(mark, idx) {
    if (mark.tool === "pin") return String(mark.n || idx + 1);
    if (mark.tool === "box") return "□" + (idx + 1);
    if (mark.tool === "arrow") return "↗" + (idx + 1);
    if (mark.tool === "redact") return "█" + (idx + 1);
    return String(idx + 1);
  }

  function AnnotationRows({marks, selectedIndex, onSelect}) {
    return marks.map((mark, idx) => {
      const selected = selectedIndex === idx;
      const selectable = typeof onSelect === "function";
      const props = {
        className: "rshell-annotation-summary-row" + (selected ? " selected" : ""),
        key: idx
      };
      if (selectable) {
        props.role = "button";
        props.tabIndex = 0;
        props.onClick = () => onSelect(idx);
        props.onKeyDown = (evt) => {
          if (evt.key === "Enter" || evt.key === " ") {
            evt.preventDefault();
            onSelect(idx);
          }
        };
      }
      return h("div", props,
        h("span", {className: "rshell-annotation-chip"}, annotationLabel(mark, idx)),
        h("span", {className: "rshell-annotation-copy"},
          mark.tool || "mark",
          mark.note ? " — " + mark.note : ""));
    });
  }

  function AnnotationDrawer({marks, selectedIndex, onSelect, open, onToggle}) {
    const count = (marks || []).length;
    return h("div", {className: "rshell-annotation-replay-list rshell-annotation-drawer" + (open ? " open" : " collapsed")},
      h("button", {className: "rshell-annotation-drawer-tab", type: "button",
        title: open ? "Hide annotation list" : "Show annotation list", onClick: onToggle},
        h("span", {className: "rshell-annotation-drawer-icon"}, open ? "›" : "‹"),
        h("span", {className: "rshell-annotation-drawer-count"}, count)),
      open ? h("div", {className: "rshell-annotation-drawer-panel"},
        count
          ? h(AnnotationRows, {marks, selectedIndex, onSelect})
          : h("div", {className: "rshell-annotation-empty"}, "No annotations yet.")) : null);
  }

  function clamp01(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.min(1, n));
  }

  function replayBounds(mark) {
    const x1 = clamp01(mark.x1);
    const y1 = clamp01(mark.y1);
    const x2 = clamp01(mark.x2 == null ? mark.x1 : mark.x2);
    const y2 = clamp01(mark.y2 == null ? mark.y1 : mark.y2);
    return {x1, y1, x2, y2, x: Math.min(x1, x2), y: Math.min(y1, y2),
      w: Math.abs(x2 - x1), h: Math.abs(y2 - y1)};
  }

  function pct(value) {
    return (clamp01(value) * 100) + "%";
  }

  function copyAnnotations(marks) {
    return (marks || []).map((mark) => {
      const copy = Object.assign({}, mark);
      if (mark.target) copy.target = Object.assign({}, mark.target);
      if (Array.isArray(mark.target && mark.target.classes)) copy.target.classes = mark.target.classes.slice();
      return copy;
    });
  }

  function AnnotationReplayOverlay({marks, activeIndex}) {
    const shapes = [];
    const pins = [];
    marks.forEach((mark, idx) => {
      const b = replayBounds(mark);
      const key = idx + "-" + (mark.tool || "mark");
      const state = activeIndex ? (activeIndex === idx + 1 ? " active" : " inactive") : "";
      if (mark.tool === "box") {
        shapes.push(h("rect", {key, className: "rshell-annotation-replay-box" + state,
          x: b.x, y: b.y, width: b.w, height: b.h}));
      } else if (mark.tool === "arrow") {
        shapes.push(h("line", {key, className: "rshell-annotation-replay-arrow" + state,
          x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2}));
      } else if (mark.tool === "redact") {
        shapes.push(h("rect", {key, className: "rshell-annotation-replay-redact" + state,
          x: b.x, y: b.y, width: b.w, height: b.h}));
      } else if (mark.tool === "pin") {
        pins.push(h("span", {key, className: "rshell-annotation-replay-pin" + state,
          style: {left: pct(b.x1), top: pct(b.y1)}}, annotationLabel(mark, idx)));
      }
    });
    if (!shapes.length && !pins.length) return null;
    return h("div", {className: "rshell-annotation-replay-overlay", "aria-hidden": "true"},
      h("svg", {className: "rshell-annotation-replay-svg", viewBox: "0 0 1 1", preserveAspectRatio: "none"},
        shapes),
      pins);
  }

  function AnnotationSummary({entry, onPreview}) {
    const marks = (entry && entry.annotations) || [];
    if (!marks.length) return null;
    const canPreview = entry && entry.shot_url && onPreview;
    const label = marks.length + " annotation" + (marks.length === 1 ? "" : "s");
    return h("div", {className: "rshell-annotation-summary"},
      h("div", {className: "rshell-annotation-summary-title"},
        "Annotations",
        canPreview ? h("button", {className: "rshell-annotation-preview-btn",
          title: "Open annotation preview", onClick: () => onPreview(entry)}, "view") : null),
      h("div", {className: "rshell-annotation-summary-count"}, label));
  }

  function designRefTitle(ref, idx) {
    if (ref && ref.label) return ref.label;
    if (ref && ref.node_id) return "Figma node " + ref.node_id;
    return "Figma reference " + (idx + 1);
  }

  function DesignReferenceSummary({entry}) {
    const refs = (entry && entry.design_refs) || [];
    if (!Array.isArray(refs) || !refs.length) return null;
    return h("div", {className: "rshell-design-summary"},
      h("div", {className: "rshell-annotation-summary-title"},
        "Design reference" + (refs.length === 1 ? "" : "s"),
        h("span", {className: "rshell-design-count"}, refs.length)),
      refs.slice(0, 5).map((ref, idx) => h("a", {key: ref.url || idx,
        className: "rshell-design-link", href: ref.url, target: "_blank", rel: "noopener noreferrer",
        title: "Open Figma node"},
        h("span", {className: "rshell-design-provider"}, "Figma"),
        h("span", null, designRefTitle(ref, idx)),
        ref.node_id ? h("span", {className: "rshell-design-node"}, ref.node_id) : null)));
  }

  function numberValue(value) {
    if (typeof value === "boolean") return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function intervalOf(item) {
    const start = numberValue(item && item.start_ms);
    const end = numberValue(item && item.end_ms);
    if (start === null && end === null) return null;
    const s = start === null ? end : start;
    const e = end === null ? s : end;
    return [s, Math.max(s, e)];
  }

  function intervalsOverlap(a, b) {
    return b[0] <= a[1] && a[0] <= b[1];
  }

  function msLabel(value) {
    const n = numberValue(value);
    if (n === null) return "";
    if (n < 1000) return Math.round(n) + "ms";
    const seconds = n / 1000;
    if (seconds < 60) return (seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)) + "s";
    const minutes = Math.floor(seconds / 60);
    const rest = String(Math.round(seconds % 60)).padStart(2, "0");
    return minutes + ":" + rest;
  }

  function timeRange(start, end) {
    const a = msLabel(start);
    const b = msLabel(end);
    if (!a && !b) return "";
    if (!b || a === b) return a;
    if (!a) return b;
    return a + "-" + b;
  }

  function transcriptRows(entry) {
    const segments = (entry && entry.transcript_segments) || [];
    if (!Array.isArray(segments)) return [];
    return segments.slice(0, 200).map((segment, idx) => {
      if (!segment || typeof segment !== "object") return null;
      const interval = intervalOf(segment);
      const text = String(segment.text || "").replace(/\s+/g, " ").trim();
      if (!text) return null;
      return {index: idx + 1, interval, text};
    }).filter(Boolean);
  }

  function narrativeTargetText(target) {
    if (!target || typeof target !== "object") return "";
    if (target.selector) return target.selector;
    if (target.data_testid) return "[data-testid=\"" + target.data_testid + "\"]";
    if (target.role) return "[role=\"" + target.role + "\"]";
    if (target.tag) return target.tag;
    return "";
  }

  function buildNarrative(entry) {
    const persisted = (entry && entry.narrative) || [];
    if (Array.isArray(persisted) && persisted.length) {
      return persisted.slice(0, 50).map((row, idx) => {
        if (!row || typeof row !== "object") return null;
        const start = numberValue(row.start_ms);
        const end = numberValue(row.end_ms);
        if (!Number.isFinite(start) && !Number.isFinite(end)) return null;
        const markIndex = Number(row.mark_index || row.index || idx + 1) || idx + 1;
        return {
          index: markIndex,
          label: String(row.label || "mark " + markIndex),
          tool: String(row.tool || "mark"),
          note: String(row.note || "").replace(/\s+/g, " ").trim(),
          target: row.tool === "redact" ? "" : narrativeTargetText(row.target),
          start_ms: Number.isFinite(start) ? start : end,
          end_ms: Number.isFinite(end) ? Math.max(Number.isFinite(start) ? start : end, end) : start,
          text: String(row.text || "").replace(/\s+/g, " ").trim()
        };
      }).filter(Boolean).sort((a, b) => (a.start_ms - b.start_ms) || (a.index - b.index));
    }
    const marks = (entry && entry.annotations) || [];
    if (!Array.isArray(marks)) return [];
    const segments = transcriptRows(entry).filter((segment) => segment.interval);
    return marks.slice(0, 50).map((mark, idx) => {
      if (!mark || typeof mark !== "object") return null;
      const interval = intervalOf(mark);
      if (!interval) return null;
      const matches = segments.filter((segment) => intervalsOverlap(interval, segment.interval));
      const target = mark.tool === "redact" ? "" : narrativeTargetText(mark.target);
      return {
        index: idx + 1,
        label: mark.tool === "pin" && mark.n ? "pin " + mark.n : "mark " + (idx + 1),
        tool: mark.tool || "mark",
        note: String(mark.note || "").replace(/\s+/g, " ").trim(),
        target,
        start_ms: interval[0],
        end_ms: interval[1],
        text: matches.map((segment) => segment.text).join(" ")
      };
    }).filter(Boolean).sort((a, b) => (a.start_ms - b.start_ms) || (a.index - b.index));
  }

  function narrativeHasDisplayContent(row) {
    if (!row || typeof row !== "object") return false;
    return Boolean(String(row.text || "").trim() || String(row.note || "").trim());
  }

  function displayNarrativeRows(rows) {
    return (rows || []).filter(narrativeHasDisplayContent);
  }

  function VoiceSummary({entry}) {
    const narrative = displayNarrativeRows(buildNarrative(entry));
    const segments = transcriptRows(entry);
    const hasAudio = Boolean(entry && entry.audio_url);
    if (!narrative.length && !segments.length && !hasAudio) return null;
    const rows = narrative.length ? narrative : segments;
    const title = narrative.length ? "Narrated feedback" : (segments.length ? "Voice transcript" : "Retained audio");
    return h("div", {className: "rshell-voice-summary"},
      h("div", {className: "rshell-annotation-summary-title"}, title),
      hasAudio ? h("audio", {className: "rshell-narrative-audio", controls: true, src: entry.audio_url}) : null,
      rows.slice(0, 8).map((row) => {
        const isNarrative = Boolean(row.tool);
        const body = isNarrative
          ? h("span", {className: "rshell-voice-copy"},
              h("b", null, row.label + " · " + row.tool),
              row.note ? h("span", {className: "rshell-voice-note"}, row.note) : null,
              row.text ? h("span", {className: "rshell-voice-text"}, row.text) : null)
          : h("span", {className: "rshell-voice-copy"},
              h("span", {className: "rshell-voice-text"}, row.text));
        return h("div", {className: "rshell-voice-row", key: isNarrative ? "mark-" + row.index : "seg-" + row.index},
          h("span", {className: "rshell-voice-time"}, row.interval
            ? timeRange(row.interval[0], row.interval[1])
            : timeRange(row.start_ms, row.end_ms)),
          body);
      }),
      rows.length > 8 ? h("div", {className: "rshell-voice-more"}, "+" + (rows.length - 8) + " more") : null);
  }

  function narrativeStepDuration(row) {
    const delta = numberValue(row && row.end_ms) - numberValue(row && row.start_ms);
    if (!Number.isFinite(delta) || delta <= 0) return 1400;
    return Math.max(900, Math.min(3000, delta));
  }

  function NarrativeReplay({rows, activeIndex, setActiveIndex, playing, setPlaying}) {
    if (!rows.length) return null;
    return h("div", {className: "rshell-narrative-replay"},
      h("div", {className: "rshell-narrative-replay-head"},
        h("b", null, "Narrative replay"),
        h("div", {className: "rshell-narrative-replay-actions"},
          h("button", {className: "rshell-annotation-preview-btn",
            title: "Play transcript-timed narrative",
            onClick: () => {
              if (!activeIndex) setActiveIndex(rows[0].index);
              setPlaying(!playing);
            }}, playing ? "pause" : "play"),
          activeIndex ? h("button", {className: "rshell-annotation-preview-btn",
            title: "Clear active mark", onClick: () => { setPlaying(false); setActiveIndex(null); }}, "clear") : null)),
      rows.map((row) => h("button", {key: row.index, className: "rshell-narrative-step" +
          (activeIndex === row.index ? " active" : ""), onClick: () => {
            setPlaying(false);
            setActiveIndex(row.index);
          }},
        h("span", {className: "rshell-voice-time"}, timeRange(row.start_ms, row.end_ms)),
        h("span", {className: "rshell-voice-copy"},
          h("b", null, row.label + " · " + row.tool),
          row.note ? h("span", {className: "rshell-voice-note"}, row.note) : null,
          row.text ? h("span", {className: "rshell-voice-text"}, row.text) : null))));
  }

  function AnnotationPreview({entry, onClose, onUseDraft}) {
    const marks = (entry && entry.annotations) || [];
    const narrative = useMemo(() => displayNarrativeRows(buildNarrative(entry)), [entry]);
    const [editing, setEditing] = useState(false);
    const [draftMarks, setDraftMarks] = useState(copyAnnotations(marks));
    const [draftSelected, setDraftSelected] = useState(null);
    const [draftDrawerOpen, setDraftDrawerOpen] = useState(false);
    const [activeIndex, setActiveIndex] = useState(null);
    const [playing, setPlaying] = useState(false);
    const audioRef = useRef(null);
    useEffect(() => {
      setEditing(false);
      setDraftMarks(copyAnnotations(marks));
      setDraftSelected(null);
      setDraftDrawerOpen(false);
      setActiveIndex(null);
      setPlaying(false);
    }, [entry]);
    useEffect(() => {
      if (!draftMarks.length && draftSelected !== null) setDraftSelected(null);
      else if (draftSelected !== null && draftSelected >= draftMarks.length) {
        setDraftSelected(draftMarks.length - 1);
      }
    }, [draftMarks.length, draftSelected]);
    useEffect(() => {
      if (!playing || !narrative.length) return undefined;
      let pos = narrative.findIndex((row) => row.index === activeIndex);
      if (pos < 0) {
        setActiveIndex(narrative[0].index);
        return undefined;
      }
      const timer = window.setTimeout(() => {
        if (pos >= narrative.length - 1) {
          setPlaying(false);
        } else {
          setActiveIndex(narrative[pos + 1].index);
        }
      }, narrativeStepDuration(narrative[pos]));
      return () => window.clearTimeout(timer);
    }, [playing, activeIndex, narrative]);
    useEffect(() => {
      const audio = audioRef.current;
      if (!audio) return;
      const row = narrative.find((item) => item.index === activeIndex);
      if (playing && row) {
        audio.currentTime = Math.max(0, (numberValue(row.start_ms) || 0) / 1000);
        audio.play().catch(() => {});
      } else if (!playing) {
        audio.pause();
      }
    }, [playing, activeIndex, narrative]);
    if (!entry || !marks.length) return null;
    const preview = h("div", {className: "rshell-annotation-replay-frame"},
      h("img", {src: entry.shot_url, alt: "annotated screenshot"}),
      h(AnnotationReplayOverlay, {marks, activeIndex: editing ? null : activeIndex}));
    const editor = entry.shot_url ? h(AnnotationEditor, {
      image: entry.shot_url,
      annotations: draftMarks,
      setAnnotations: setDraftMarks,
      selectedIndex: draftSelected,
      setSelectedIndex: setDraftSelected
    }) : null;
    return h("div", {className: "rshell-modal-backdrop", onClick: onClose},
      h("div", {className: "rshell-annotation-modal", role: "dialog", "aria-modal": "true",
          onClick: (e) => e.stopPropagation()},
        h("div", {className: "rshell-modal-head"},
          h("b", null, editing ? "Edit annotation copy" : "Annotations"),
          h("div", {className: "rshell-modal-actions"},
            h("button", {className: "rshell-button secondary", onClick: () => setEditing(!editing)},
              editing ? "Preview" : "Edit copy"),
            editing && onUseDraft ? h("button", {className: "rshell-button secondary",
              disabled: !draftMarks.length, onClick: () => onUseDraft(entry, draftMarks)}, "Use as reply draft") : null),
          h("button", {className: "rshell-modal-close", title: "Close", onClick: onClose}, "×")),
        h("div", {className: "rshell-annotation-modal-body" + (editing && !draftDrawerOpen ? " drawer-collapsed" : "")},
          entry.shot_url ? h("div", {className: "rshell-annotation-replay-shot"},
            editing ? editor : preview) : null,
          editing ? h(AnnotationDrawer, {marks: draftMarks, selectedIndex: draftSelected,
            onSelect: setDraftSelected, open: draftDrawerOpen, onToggle: () => setDraftDrawerOpen(!draftDrawerOpen)})
            : h("div", {className: "rshell-annotation-replay-list"},
              entry.audio_url ? h("audio", {className: "rshell-narrative-audio",
                controls: true, ref: audioRef, src: entry.audio_url}) : null,
              h(NarrativeReplay, {rows: narrative, activeIndex, setActiveIndex, playing, setPlaying}),
              h(AnnotationRows, {marks})))));
  }

  function ShotThumbnail({image, annotations, onOpen}) {
    const marks = annotations || [];
    return h("button", {className: "rshell-shot-thumb", type: "button",
        title: "Open expanded annotation view", "aria-label": "Open expanded annotation view",
        onClick: onOpen},
      h("span", {className: "rshell-shot-thumb-frame"},
        h("img", {src: image, alt: "captured screenshot"})),
      h("span", {className: "rshell-shot-thumb-footer"},
        h("span", null, "Screenshot"),
        h("span", {className: "rshell-shot-thumb-action"}, marks.length ? "Annotate (" + marks.length + ")" : "Annotate")));
  }

  function DraftAnnotationModal({image, annotations, setAnnotations, annotate, clockStart, onClose}) {
    const [selectedAnnotation, setSelectedAnnotation] = useState(null);
    const [drawerOpen, setDrawerOpen] = useState(false);
    useEffect(() => {
      if (!annotations.length && selectedAnnotation !== null) setSelectedAnnotation(null);
      else if (selectedAnnotation !== null && selectedAnnotation >= annotations.length) {
        setSelectedAnnotation(annotations.length - 1);
      }
    }, [annotations.length, selectedAnnotation]);
    if (!image) return null;
    return h("div", {className: "rshell-modal-backdrop", onClick: onClose},
      h("div", {className: "rshell-annotation-modal rshell-draft-annotation-modal",
          role: "dialog", "aria-modal": "true", onClick: (e) => e.stopPropagation()},
        h("div", {className: "rshell-modal-head"},
          h("b", null, "Screenshot annotations"),
          h("div", {className: "rshell-modal-actions"},
            annotations.length ? h("button", {className: "rshell-button secondary",
              onClick: () => { setAnnotations([]); setSelectedAnnotation(null); }}, "Clear") : null),
          h("button", {className: "rshell-modal-close", title: "Close", onClick: onClose}, "×")),
        h("div", {className: "rshell-annotation-modal-body" + (drawerOpen ? "" : " drawer-collapsed")},
          h("div", {className: "rshell-annotation-replay-shot"},
            h(AnnotationEditor, {image, annotations, setAnnotations, annotate, clockStart,
              selectedIndex: selectedAnnotation, setSelectedIndex: setSelectedAnnotation})),
          h(AnnotationDrawer, {marks: annotations, selectedIndex: selectedAnnotation,
            onSelect: setSelectedAnnotation, open: drawerOpen, onToggle: () => setDrawerOpen(!drawerOpen)}))));
  }

  function composeShot(dataUrl, annotations) {
    if (!dataUrl || (!annotations.length && String(dataUrl).startsWith("data:image"))) return Promise.resolve(dataUrl);
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement("canvas");
        const width = img.naturalWidth || img.width;
        const height = img.naturalHeight || img.height;
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          resolve(dataUrl);
          return;
        }
        ctx.drawImage(img, 0, 0, width, height);
        annotations.forEach((mark) => drawAnnotation(ctx, mark, width, height));
        try {
          resolve(canvas.toDataURL("image/png"));
        } catch (e) {
          resolve(dataUrl);
        }
      };
      img.onerror = () => resolve(dataUrl);
      img.src = dataUrl;
    });
  }

  function cssEscape(value) {
    if (window.CSS && window.CSS.escape) return window.CSS.escape(String(value));
    return String(value).replace(/[^a-zA-Z0-9_-]/g, (ch) => "\\" + ch);
  }

  function attrValue(value) {
    return String(value).replace(/\\/g, "\\\\").replace(/"/g, "\\\"");
  }

  function selectorFor(el) {
    if (!el || !el.tagName) return null;
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && cur.tagName && cur.tagName.toLowerCase() !== "html" && parts.length < 5) {
      const tag = cur.tagName.toLowerCase();
      const testid = cur.getAttribute("data-testid") || cur.getAttribute("data-test") || cur.getAttribute("data-cy");
      let part = tag;
      if (cur.id) {
        part += "#" + cssEscape(cur.id);
        parts.unshift(part);
        break;
      }
      if (testid) part += '[data-testid="' + attrValue(testid) + '"]';
      else Array.from(cur.classList || []).slice(0, 2).forEach((cls) => { part += "." + cssEscape(cls); });
      const parent = cur.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children || []).filter((node) => node.tagName === cur.tagName);
        if (siblings.length > 1) part += ":nth-of-type(" + (siblings.indexOf(cur) + 1) + ")";
      }
      parts.unshift(part);
      cur = parent;
    }
    return parts.join(" > ");
  }

  function targetForElement(el) {
    if (!el || !el.tagName) return null;
    const testid = el.getAttribute("data-testid") || el.getAttribute("data-test") || el.getAttribute("data-cy");
    const target = {
      selector: selectorFor(el),
      tag: el.tagName.toLowerCase()
    };
    if (el.id) target.id = el.id;
    if (testid) target.data_testid = testid;
    const role = el.getAttribute("role");
    if (role) target.role = role;
    const classes = Array.from(el.classList || []).slice(0, 5);
    if (classes.length) target.classes = classes;
    return target;
  }

  function withDomTarget(mark, doc) {
    if (!mark || mark.tool === "redact" || !doc || !doc.elementFromPoint) return mark;
    const docEl = doc.documentElement || {};
    const body = doc.body || {};
    const pageW = Math.max(body.scrollWidth || 0, docEl.scrollWidth || 0, body.offsetWidth || 0, docEl.clientWidth || 0, 1);
    const pageH = Math.max(body.scrollHeight || 0, docEl.scrollHeight || 0, body.offsetHeight || 0, docEl.clientHeight || 0, 1);
    const win = doc.defaultView || {};
    const x = ((mark.x1 || 0) + (mark.x2 == null ? mark.x1 || 0 : mark.x2)) / 2;
    const y = ((mark.y1 || 0) + (mark.y2 == null ? mark.y1 || 0 : mark.y2)) / 2;
    const clientX = x * pageW - (win.pageXOffset || docEl.scrollLeft || body.scrollLeft || 0);
    const clientY = y * pageH - (win.pageYOffset || docEl.scrollTop || body.scrollTop || 0);
    if (clientX < 0 || clientY < 0 || clientX > (docEl.clientWidth || pageW) || clientY > (docEl.clientHeight || pageH)) {
      return mark;
    }
    const target = targetForElement(doc.elementFromPoint(clientX, clientY));
    return target ? Object.assign({}, mark, {target}) : mark;
  }

  function AnnotationEditor({image, annotations, setAnnotations, annotate, clockStart, selectedIndex, setSelectedIndex}) {
    const canvasRef = useRef(null);
    const imageRef = useRef(null);
    const clockRef = useRef(clockStart || performance.now());
    const [tool, setTool] = useState("box");
    const [draft, setDraft] = useState(null);

    useEffect(() => {
      clockRef.current = clockStart || performance.now();
    }, [image, clockStart]);

    function elapsedMs() {
      return Math.max(0, Math.round((performance.now() - clockRef.current) * 10) / 10);
    }

    function redraw() {
      const canvas = canvasRef.current;
      const img = imageRef.current;
      if (!canvas || !img || !img.complete) return;
      const width = img.naturalWidth || img.width;
      const height = img.naturalHeight || img.height;
      if (!width || !height) return;
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(img, 0, 0, width, height);
      annotations.concat(draft ? [draft] : []).forEach((mark) => drawAnnotation(ctx, mark, width, height));
    }

    useEffect(redraw, [image, annotations, draft]);

    function selectAnnotation(idx) {
      if (typeof setSelectedIndex === "function") setSelectedIndex(idx);
    }

    function replaceAnnotations(next, nextSelected) {
      setAnnotations(next);
      if (typeof setSelectedIndex === "function") {
        setSelectedIndex(next.length ? nextSelected : null);
      }
    }

    function segmentDistance(p, ax, ay, bx, by) {
      const vx = bx - ax;
      const vy = by - ay;
      const wx = p.x - ax;
      const wy = p.y - ay;
      const denom = vx * vx + vy * vy;
      const t = denom ? Math.max(0, Math.min(1, (wx * vx + wy * vy) / denom)) : 0;
      const x = ax + t * vx;
      const y = ay + t * vy;
      return Math.hypot(p.x - x, p.y - y);
    }

    function markDistance(mark, p) {
      const x1 = numberValue(mark.x1);
      const y1 = numberValue(mark.y1);
      const x2 = mark.x2 == null ? x1 : numberValue(mark.x2);
      const y2 = mark.y2 == null ? y1 : numberValue(mark.y2);
      if (mark.tool === "pin" || mark.x2 == null || mark.y2 == null) return Math.hypot(p.x - x1, p.y - y1);
      if (mark.tool === "arrow") return segmentDistance(p, x1, y1, x2, y2);
      const left = Math.min(x1, x2);
      const right = Math.max(x1, x2);
      const top = Math.min(y1, y2);
      const bottom = Math.max(y1, y2);
      if (p.x >= left && p.x <= right && p.y >= top && p.y <= bottom) {
        return Math.min(p.x - left, right - p.x, p.y - top, bottom - p.y);
      }
      const dx = p.x < left ? left - p.x : p.x > right ? p.x - right : 0;
      const dy = p.y < top ? top - p.y : p.y > bottom ? p.y - bottom : 0;
      return Math.hypot(dx, dy);
    }

    function selectNearestAnnotation(p) {
      let best = null;
      let bestDist = Infinity;
      annotations.forEach((mark, idx) => {
        const dist = markDistance(mark, p);
        if (dist < bestDist) {
          bestDist = dist;
          best = idx;
        }
      });
      selectAnnotation(bestDist <= 0.04 ? best : null);
    }

    function toolSelectsOnClick(value) {
      return value === "arrow" || value === "box" || value === "redact";
    }

    function point(evt) {
      const rect = canvasRef.current.getBoundingClientRect();
      const width = Math.max(rect.width, 1);
      const height = Math.max(rect.height, 1);
      return {
        x: Math.max(0, Math.min(1, (evt.clientX - rect.left) / width)),
        y: Math.max(0, Math.min(1, (evt.clientY - rect.top) / height))
      };
    }

    function down(evt) {
      evt.preventDefault();
      const p = point(evt);
      if (tool === "pin") {
        const n = annotations.filter((m) => m.tool === "pin").length + 1;
        const t = elapsedMs();
        const mark = {tool, x1: p.x, y1: p.y, n, start_ms: t, end_ms: t};
        const next = annotations.concat([annotate ? annotate(mark) : mark]);
        replaceAnnotations(next, next.length - 1);
        return;
      }
      evt.currentTarget.setPointerCapture(evt.pointerId);
      setDraft({tool, x1: p.x, y1: p.y, x2: p.x, y2: p.y, start_ms: elapsedMs()});
    }

    function move(evt) {
      if (!draft) return;
      const p = point(evt);
      setDraft(Object.assign({}, draft, {x2: p.x, y2: p.y}));
    }

    function up(evt) {
      if (!draft) return;
      const p = point(evt);
      const mark = Object.assign({}, draft, {x2: p.x, y2: p.y, end_ms: elapsedMs()});
      setDraft(null);
      if (Math.abs(mark.x2 - mark.x1) + Math.abs(mark.y2 - mark.y1) < .015) {
        if (toolSelectsOnClick(tool)) selectNearestAnnotation(p);
        return;
      }
      const next = annotations.concat([annotate ? annotate(mark) : mark]);
      replaceAnnotations(next, next.length - 1);
    }

    function note(idx, value) {
      setAnnotations(annotations.map((mark, i) => i === idx ? Object.assign({}, mark, {note: value}) : mark));
    }

    function moveAnnotation(delta) {
      if (selectedIndex === null || selectedIndex === undefined) return;
      const from = selectedIndex;
      const to = Math.max(0, Math.min(annotations.length - 1, from + delta));
      if (from === to) return;
      const next = annotations.slice();
      const [mark] = next.splice(from, 1);
      next.splice(to, 0, mark);
      replaceAnnotations(next, to);
    }

    const selectedMark = selectedIndex === null || selectedIndex === undefined ? null : annotations[selectedIndex];

    const tools = [["box", "□"], ["arrow", "↗"], ["pin", "①"], ["redact", "█"]];
    return h("div", {className: "rshell-annotator"},
      h("div", {className: "rshell-annotation-toolbar"},
        tools.map(([value, label]) => h("button", {key: value,
          className: "rshell-tool" + (tool === value ? " active" : ""),
          title: value, onClick: () => setTool(value)}, label)),
        h("button", {className: "rshell-tool", title: "Undo annotation",
          disabled: !annotations.length, onClick: () => {
            const next = annotations.slice(0, -1);
            replaceAnnotations(next, next.length ? Math.min(selectedIndex ?? next.length - 1, next.length - 1) : null);
          }}, "↶"),
        h("button", {className: "rshell-tool", title: "Clear annotations",
          disabled: !annotations.length, onClick: () => replaceAnnotations([], null)}, "×")),
      h("div", {className: "rshell-annotation-stage"},
        h("img", {ref: imageRef, src: image, onLoad: redraw, style: {display: "none"}, alt: ""}),
        h("canvas", {ref: canvasRef, className: "rshell-annotation-canvas",
          onPointerDown: down, onPointerMove: move, onPointerUp: up, onPointerCancel: () => setDraft(null)})),
      selectedMark ? h("div", {className: "rshell-annotation-properties"},
        h("div", {className: "rshell-annotation-property-head"},
          h("span", {className: "rshell-annotation-chip"}, annotationLabel(selectedMark, selectedIndex)),
          h("div", {className: "rshell-annotation-order"},
            h("button", {className: "rshell-tool", title: "Move annotation earlier",
              disabled: selectedIndex <= 0, onClick: () => moveAnnotation(-1)}, "↑"),
            h("button", {className: "rshell-tool", title: "Move annotation later",
              disabled: selectedIndex >= annotations.length - 1, onClick: () => moveAnnotation(1)}, "↓"),
            h("button", {className: "rshell-tool", title: "Deselect annotation",
              onClick: () => selectAnnotation(null)}, "×"))),
        h("label", {className: "rshell-annotation-note"},
          h("span", null, "note"),
          h("input", {value: selectedMark.note || "", maxLength: 500, placeholder: "note…",
            "aria-label": "annotation note " + annotationLabel(selectedMark, selectedIndex),
            onChange: (e) => note(selectedIndex, e.target.value)}))) : null);
  }

  function NewAppWizard({open, onClose, onCreated}) {
    const [appType, setAppType] = useState("dash");
    const [title, setTitle] = useState("");
    const [appKey, setAppKey] = useState("");
    const [repoUrl, setRepoUrl] = useState("");
    const [prompt, setPrompt] = useState("");
    const [notes, setNotes] = useState("");
    const [dockerize, setDockerize] = useState(false);
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState("");
    useEffect(() => {
      if (!open) return;
      setMsg("");
      setBusy(false);
    }, [open]);
    if (!open) return null;
    const isRepo = appType === "github_repo";
    const ready = isRepo ? repoUrl.trim() : prompt.trim();
    function submit(evt) {
      evt.preventDefault();
      if (!ready || busy) {
        setMsg(isRepo ? "Add a GitHub repo URL." : "Describe the app to create.");
        return;
      }
      setBusy(true);
      setMsg("Creating app request…");
      api("/api/new-app", {method: "POST", body: JSON.stringify({
        app_type: appType,
        title,
        app_key: appKey,
        repo_url: repoUrl,
        dockerize,
        prompt,
        notes
      })}).then((data) => {
        setBusy(false);
        setTitle("");
        setAppKey("");
        setRepoUrl("");
        setPrompt("");
        setNotes("");
        setDockerize(false);
        if (onCreated) onCreated(data);
      }).catch((e) => {
        setBusy(false);
        setMsg(e.error || "Could not create app request.");
      });
    }
    return h("div", {className: "rshell-modal-backdrop"},
      h("form", {className: "rshell-new-app-modal", onSubmit: submit},
        h("div", {className: "rshell-modal-head"},
          h("h3", null, "Make a new app"),
          h("button", {className: "rshell-modal-close", type: "button", title: "Close", onClick: onClose}, "×")),
        h("div", {className: "rshell-new-app-body"},
          h("label", {className: "rshell-field"},
            h("span", null, "type"),
            h("select", {className: "rshell-select", value: appType, onChange: (e) => setAppType(e.target.value)},
              NEW_APP_TYPES.map(([value, label]) => h("option", {key: value, value}, label)))),
          h("label", {className: "rshell-field"},
            h("span", null, "title"),
            h("input", {className: "rshell-input", value: title, maxLength: 120,
              placeholder: isRepo ? "repo title or gallery label" : "working app title",
              onChange: (e) => setTitle(e.target.value), autoFocus: true})),
          h("label", {className: "rshell-field"},
            h("span", null, "app key"),
            h("input", {className: "rshell-input", value: appKey, maxLength: 80,
              placeholder: "optional_slug", onChange: (e) => setAppKey(e.target.value)})),
          isRepo ? h("label", {className: "rshell-field"},
            h("span", null, "repo URL"),
            h("input", {className: "rshell-input", value: repoUrl, maxLength: 500,
              placeholder: "https://github.com/org/project.git", onChange: (e) => setRepoUrl(e.target.value)})) : null,
          h("label", {className: "rshell-checkbox-field"},
            h("input", {type: "checkbox", checked: dockerize, onChange: (e) => setDockerize(e.target.checked)}),
            h("span", null, "Dockerize"),
            h("small", null, "package/run with Docker when useful")),
          h("label", {className: "rshell-field"},
            h("span", null, isRepo ? "brief" : "prompt"),
            h("textarea", {className: "rshell-textarea rshell-new-app-prompt",
              value: prompt, maxLength: 5000,
              placeholder: isRepo ? "what to adapt, expose, or test after import…" : "what should the app do?",
              onChange: (e) => setPrompt(e.target.value)})),
          h("label", {className: "rshell-field"},
            h("span", null, "notes"),
            h("textarea", {className: "rshell-textarea rshell-new-app-notes",
              value: notes, maxLength: 2000,
              placeholder: "data sources, constraints, tags, dependencies…",
              onChange: (e) => setNotes(e.target.value)}))),
        h("div", {className: "rshell-modal-actions"},
          h("button", {className: "rshell-button secondary", type: "button", onClick: onClose}, "Cancel"),
          h("button", {className: "rshell-button primary", type: "submit", disabled: busy || !ready},
            busy ? "Creating…" : "Create request")),
        msg ? h("div", {className: "rshell-new-app-msg"}, msg) : null));
  }

  function WorkspaceWizard({app, open, onClose, onCreated}) {
    const [name, setName] = useState("");
    const [ref, setRef] = useState("HEAD");
    const [mode, setMode] = useState("branch");
    const [credentials, setCredentials] = useState("none");
    const [agentNetwork, setAgentNetwork] = useState(true);
    const [agentSandbox, setAgentSandbox] = useState("container");
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState("");
    useEffect(() => {
      if (!open) return;
      setName(app ? app.key + "-fork" : "");
      setRef("HEAD");
      setMode("branch");
      setCredentials("none");
      setAgentNetwork(true);
      setAgentSandbox("container");
      setBusy(false);
      setMsg("");
    }, [open, app && app.key]);
    if (!open || !app) return null;
    function submit(evt) {
      evt.preventDefault();
      setBusy(true);
      setMsg("Creating…");
      api("/api/workspaces", {method: "POST", body: JSON.stringify({
        app: app.key, name, ref, preview: mode === "preview", credentials,
        agent_network: agentNetwork, agent_sandbox: agentSandbox
      })}).then((data) => {
        setBusy(false);
        if (onCreated) onCreated(data.workspace);
      }).catch((err) => {
        setBusy(false);
        setMsg(err.error || "Workspace creation failed.");
      });
    }
    return h("div", {className: "rshell-modal-backdrop"},
      h("form", {className: "rshell-workspace-modal", onSubmit: submit},
        h("div", {className: "rshell-modal-head"},
          h("h3", null, "Fork " + app.title),
          h("button", {className: "rshell-modal-close", type: "button", title: "Close", onClick: onClose}, "×")),
        h("div", {className: "rshell-workspace-body"},
          h("label", {className: "rshell-field"}, h("span", null, "name"),
            h("input", {className: "rshell-input", value: name, autoFocus: true,
              onChange: (e) => setName(e.target.value)})),
          h("label", {className: "rshell-field"}, h("span", null, "Git ref"),
            h("input", {className: "rshell-input", value: ref, onChange: (e) => setRef(e.target.value)})),
          h("div", {className: "rshell-field"}, h("span", null, "mode"),
            h("div", {className: "rshell-segments"},
              [["branch", "Editable"], ["preview", "Preview"]].map(([value, label]) =>
                h("button", {key: value, type: "button", className: mode === value ? "active" : "",
                  onClick: () => setMode(value)}, label)))),
          h("label", {className: "rshell-field"}, h("span", null, "agent credentials"),
            h("select", {className: "rshell-select", value: credentials,
              onChange: (e) => setCredentials(e.target.value)},
              h("option", {value: "none"}, "None"),
              h("option", {value: "codex"}, "Codex"),
              h("option", {value: "claude"}, "Claude"))),
          credentials !== "none" ? h("label", {className: "rshell-check-row"},
            h("input", {type: "checkbox", checked: agentNetwork,
              onChange: (e) => setAgentNetwork(e.target.checked)}),
            h("span", null, "Allow agent network access")) : null,
          credentials === "codex" ? h("label", {className: "rshell-field"},
            h("span", null, "agent isolation"),
            h("select", {className: "rshell-select", value: agentSandbox,
              onChange: (e) => setAgentSandbox(e.target.value)},
              h("option", {value: "container"}, "Container boundary"),
              h("option", {value: "workspace-write"}, "Nested sandbox"))) : null),
        h("div", {className: "rshell-modal-actions"},
          h("button", {className: "rshell-button secondary", type: "button", onClick: onClose}, "Cancel"),
          h("button", {className: "rshell-button primary", type: "submit", disabled: busy || !name.trim() || !ref.trim()},
            busy ? "Creating…" : mode === "preview" ? "Create preview" : "Create fork")),
        msg ? h("div", {className: "rshell-new-app-msg"}, msg) : null));
  }

  function WorkspacePanel({open, workspaces, onClose, onRefresh}) {
    const [detail, setDetail] = useState(null);
    const [msg, setMsg] = useState("");
    if (!open) return null;
    function action(ws, name, body) {
      setMsg(name + "…");
      return api("/api/workspaces/" + ws.id + "/" + name,
        {method: "POST", body: JSON.stringify(body || {})}).then(() => {
          setMsg("");
          setDetail(null);
          return onRefresh();
        }).catch((err) => setMsg(err.error || (name + " failed")));
    }
    function compare(ws) {
      setMsg("Comparing…");
      api("/api/workspaces/" + ws.id + "?diff=1").then((data) => {
        setDetail(data.diff || {});
        setMsg("");
      }).catch((err) => setMsg(err.error || "Compare failed"));
    }
    function discard(ws) {
      setMsg("Checking source…");
      api("/api/workspaces/" + ws.id + "/delete", {method: "POST", body: "{}"}).then(() => {
        setMsg("");
        setDetail(null);
        onRefresh();
      }).catch((err) => {
        if (!window.confirm((err.error || "Workspace has unpreserved work.") + "\n\nDiscard it permanently?")) {
          setMsg(err.error || "Discard cancelled.");
          return;
        }
        action(ws, "delete", {force: true});
      });
    }
    function applyAccepted(ws) {
      if (!window.confirm("Apply this kept branch to the current canonical checkout?")) return;
      action(ws, "apply");
    }
    return h("div", {className: "rshell-modal-backdrop"},
      h("div", {className: "rshell-workspace-panel"},
        h("div", {className: "rshell-modal-head"}, h("h3", null, "Workspaces"),
          h("button", {className: "rshell-modal-close", title: "Close", onClick: onClose}, "×")),
        h("div", {className: "rshell-workspace-list"},
          workspaces.length ? workspaces.map((ws) => h("div", {className: "rshell-workspace-item", key: ws.id},
            h("div", {className: "rshell-workspace-item-head"},
              h("b", null, ws.name), h("span", {className: "state " + ws.status}, ws.status)),
            h("div", {className: "rshell-workspace-meta"}, ws.app_key, " · ", ws.mode, " · ",
              (ws.branch || ws.owning_repo_base_sha.slice(0, 10))),
            h("div", {className: "rshell-workspace-actions"},
              ws.status === "running" && ws.url ? h("a", {href: ws.url, target: "_blank"}, "Open") : null,
              ws.status === "running" ? h("button", {onClick: () => action(ws, "stop")}, "Stop") : null,
              ws.status === "stopped" ? h("button", {onClick: () => action(ws, "start")}, "Start") : null,
              ws.mode === "preview" ? h("button", {onClick: () => action(ws, "edit")}, "Start editing") : null,
              h("button", {onClick: () => compare(ws)}, "Compare"),
              ws.mode === "branch" && !ws.preserved_ref
                ? h("button", {onClick: () => action(ws, "keep")}, "Keep branch") : null,
              ws.preserved_ref && ws.status !== "applied"
                ? h("button", {onClick: () => applyAccepted(ws)}, "Apply to canonical") : null,
              h("button", {className: "danger", onClick: () => discard(ws)}, "Discard")))
          ) : h("div", {className: "rshell-empty"}, "No workspaces.")),
        detail ? h("pre", {className: "rshell-workspace-diff"},
          (detail.status || "clean") + "\n" + (detail.commits || []).join("\n") + "\n\n" + (detail.patch || "")) : null,
        msg ? h("div", {className: "rshell-new-app-msg"}, msg) : null));
  }

  function ReplayModal({feedbackId, initialGroupId, onClose}) {
    const [audit, setAudit] = useState(null);
    const [selectedProfiles, setSelectedProfiles] = useState(["baseline"]);
    const [confirmResources, setConfirmResources] = useState(false);
    const [groupId, setGroupId] = useState(null);
    const [group, setGroup] = useState(null);
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState("");

    useEffect(() => {
      if (!feedbackId) return;
      setAudit(null);
      setSelectedProfiles(["baseline"]);
      setConfirmResources(false);
      setGroupId(initialGroupId || null);
      setGroup(null);
      setBusy(false);
      setMsg("Checking replay completeness…");
      api("/api/replays/inspect/" + encodeURIComponent(feedbackId)).then((data) => {
        setAudit(data.replay);
        setMsg("");
      }).catch((err) => setMsg(err.error || "Replay audit failed."));
    }, [feedbackId, initialGroupId]);

    useEffect(() => {
      if (!groupId) return undefined;
      let active = true;
      let timer = null;
      function poll() {
        api("/api/replays/" + encodeURIComponent(groupId)).then((data) => {
          if (!active) return;
          const next = data.replay;
          setGroup(next);
          setMsg("");
          if (next.status !== "complete" && next.status !== "deleted") {
            timer = setTimeout(poll, 2000);
          }
        }).catch((err) => {
          if (!active) return;
          setMsg(err.error && !err.error.includes("not found") ? err.error : "Starting replay workspace…");
          timer = setTimeout(poll, 1500);
        });
      }
      poll();
      return () => {
        active = false;
        if (timer) clearTimeout(timer);
      };
    }, [groupId]);

    if (!feedbackId) return null;
    const profiles = (audit && audit.profiles) || [];
    const runnable = audit && audit.workspace_ready && ["exact", "source-exact"].includes(audit.exactness);
    function toggleProfile(name) {
      if (selectedProfiles.includes(name)) {
        if (selectedProfiles.length > 1) setSelectedProfiles(selectedProfiles.filter((item) => item !== name));
      } else if (selectedProfiles.length < 3) {
        setSelectedProfiles([...selectedProfiles, name]);
      }
    }
    function launch() {
      setBusy(true);
      setMsg("Starting replay workspace…");
      api("/api/replays", {method: "POST", body: JSON.stringify({
        feedback_id: feedbackId,
        profiles: selectedProfiles,
        confirm_resources: confirmResources
      })}).then((data) => {
        setGroupId(data.group_id);
        setBusy(false);
      }).catch((err) => {
        setBusy(false);
        setMsg(err.error || "Replay launch failed.");
      });
    }
    function groupAction(action, body) {
      setBusy(true);
      setMsg(action === "keep" ? "Preserving branch…" : "Discarding replay resources…");
      api("/api/replays/" + encodeURIComponent(group.id) + "/" + action,
        {method: "POST", body: JSON.stringify(body || {})}).then((data) => {
          setGroup(data.replay);
          setBusy(false);
          setMsg("");
        }).catch((err) => {
          setBusy(false);
          setMsg(err.error || (action + " failed"));
        });
    }
    function discard() {
      if (!window.confirm("Delete these replay containers and volumes? Preserved Git branches remain available.")) return;
      groupAction("delete", {force: true});
    }
    const consistency = group && group.evidence_consistency;
    return h("div", {className: "rshell-modal-backdrop"},
      h("div", {className: "rshell-replay-modal"},
        h("div", {className: "rshell-modal-head"},
          h("div", null, h("h3", null, "Replay feedback"),
            h("span", {className: "rshell-replay-id"}, feedbackId)),
          h("button", {className: "rshell-modal-close", title: "Close", onClick: onClose}, "×")),
        h("div", {className: "rshell-replay-body"},
          audit ? h("div", {className: "rshell-replay-audit"},
            h("b", null, audit.exactness),
            h("span", null, audit.workspace_ready ? "source snapshot ready" : "workspace unavailable"),
            (audit.reasons || []).map((reason) => h("div", {key: reason}, reason))) : null,
          !groupId && audit ? h("div", {className: "rshell-replay-launch"},
            h("div", {className: "rshell-field"}, h("span", null, "profiles"),
              h("div", {className: "rshell-replay-profiles"}, profiles.map((name) =>
                h("label", {key: name},
                  h("input", {type: "checkbox", checked: selectedProfiles.includes(name),
                    onChange: () => toggleProfile(name)}), h("span", null, name))))),
            selectedProfiles.length > 1 ? h("label", {className: "rshell-check-row"},
              h("input", {type: "checkbox", checked: confirmResources,
                onChange: (e) => setConfirmResources(e.target.checked)}),
              h("span", null, "Confirm provider cost and one Docker workspace per variant")) : null,
            h("button", {className: "rshell-button primary", onClick: launch,
              disabled: busy || !runnable || (selectedProfiles.length > 1 && !confirmResources)},
              busy ? "Starting…" : selectedProfiles.length > 1 ? "Run variants" : "Run replay")) : null,
          group ? h(React.Fragment, null,
            h("div", {className: "rshell-replay-common"},
              h("span", null, group.status),
              h("span", null, group.exactness),
              consistency ? h("span", {className: consistency.byte_identical_across_variants ? "ok" : "bad"},
                consistency.byte_identical_across_variants ? "identical task evidence" : "task evidence mismatch") : null),
            h("div", {className: "rshell-replay-grid"}, (group.variants || []).map((variant) => {
              const result = variant.result || {};
              const browser = result.browser || {};
              const diff = result.diff || {};
              const metricResult = (browser.results || []).find((item) => item.metric_artifact);
              const metricArtifact = metricResult && metricResult.metric_artifact;
              const effective = result.effective_profile || {};
              const profile = [effective.adapter, effective.model, effective.autonomy].some(Boolean)
                ? effective : (variant.profile || {});
              const accepted = group.review && group.review.variant_id === variant.id;
              const screenshot = browser.ok && group.status !== "deleted"
                ? "/api/replays/" + group.id + "/" + variant.id + "/screenshot?v=" + encodeURIComponent(group.updated_at || "")
                : null;
              return h("section", {className: "rshell-replay-variant", key: variant.id},
                h("div", {className: "rshell-replay-variant-head"},
                  h("b", null, (variant.profile && variant.profile.name) || variant.id),
                  h("span", {className: "state " + variant.status}, variant.status || "unknown")),
                h("div", {className: "rshell-replay-meta"},
                  [profile.adapter, profile.model, profile.autonomy].filter(Boolean).join(" · ") || "profile pending",
                  variant.duration_seconds != null ? " · " + variant.duration_seconds + "s" : ""),
                screenshot ? h("img", {className: "rshell-replay-shot", src: screenshot,
                  alt: "Rendered replay result for " + ((variant.profile && variant.profile.name) || variant.id)}) : null,
                h("div", {className: "rshell-replay-checks"},
                  h("span", {className: browser.ok ? "ok" : "bad"}, browser.ok ? "browser passed" : "browser pending/failed"),
                  h("span", null, result.feedback_status || result.workspace_status || "pending"),
                  h("span", null, (diff.commits || []).length + " commit" + ((diff.commits || []).length === 1 ? "" : "s"))),
                h("div", {className: "rshell-workspace-actions"},
                  result.url && group.status !== "deleted" ? h("a", {href: result.url, target: "_blank"}, "Open live") : null,
                  (diff.commits || []).length && !(group.review && group.review.decision === "accepted")
                    ? h("button", {onClick: () => groupAction("keep", {variant_id: variant.id}), disabled: busy}, "Keep branch") : null,
                  accepted ? h("b", {className: "rshell-replay-kept"}, "Kept") : null),
                metricArtifact ? h("details", {className: "rshell-replay-diff"},
                  h("summary", null, "Metric artifact"),
                  h("pre", null, JSON.stringify(metricArtifact, null, 2))) : null,
                diff.patch ? h("details", {className: "rshell-replay-diff"},
                  h("summary", null, "Source diff"), h("pre", null, diff.patch)) : null);
            })),
            group.status !== "deleted" ? h("div", {className: "rshell-replay-footer"},
              h("button", {className: "rshell-button secondary danger", onClick: discard, disabled: busy},
                "Discard replay resources")) : null) : null,
          msg ? h("div", {className: "rshell-new-app-msg"}, msg) : null)));
  }

  function WorkspaceBanner({workspace}) {
    if (!workspace) return null;
    const target = workspace.control_url
      ? workspace.control_url + "/?workspaces=1&workspace=" + encodeURIComponent(workspace.id) : null;
    return h("div", {className: "rshell-workspace-banner"},
      h("b", null, "Fork: " + workspace.name),
      h("span", null, workspace.mode, " · ", (workspace.branch || workspace.base_sha || "").slice(0, 24)),
      target ? h("a", {href: target, target: "_blank"}, "Manage") : null);
  }

  function Catalog({apps, selected, setSelected, search, setSearch, sort, setSort, reverse, setReverse,
      open, collapsed, onCollapse, onNewApp, workspaces, onFork, onWorkspaces}) {
    const rows = useMemo(() => {
      const q = (search || "").toLowerCase();
      const filtered = apps
        .filter((a) => a.kind !== "general")
        .filter((a) => !q || [a.key, a.title, ...(a.tags || [])].join(" ").toLowerCase().includes(q));
      const byKey = (a, b) => String(a.key).localeCompare(String(b.key));
      filtered.sort((a, b) => {
        if (sort === "open") return (a.metrics.open || 0) - (b.metrics.open || 0) || byKey(a, b);
        if (sort === "rating") return (a.metrics.avg_stars || 0) - (b.metrics.avg_stars || 0) || byKey(a, b);
        if (sort === "updated") return (a.updated || 0) - (b.updated || 0) || byKey(a, b);
        if (sort === "title") return String(a.title).localeCompare(String(b.title));
        // "id"/number → sort by the number shown on each row (a.port), numerically; apps without a
        // number sort last, then ties break by key. (Was sorting by a.key string, unrelated to a.port.)
        // Guard with `a.port ?` so a falsy port (0/null/undefined) is "no number", matching the row.
        const na = a.port ? numberValue(a.port) : null;
        const nb = b.port ? numberValue(b.port) : null;
        if (na === null && nb === null) return byKey(a, b);
        if (na === null) return 1;
        if (nb === null) return -1;
        return na - nb || byKey(a, b);
      });
      if (reverse) filtered.reverse();
      return filtered;
    }, [apps, search, sort, reverse]);
    const general = apps.find((a) => a.kind === "general");
    return h("aside", {className: "rshell-catalog" + (open ? " open" : "") + (collapsed ? " collapsed" : "")},
      h("div", {className: "rshell-brand"},
        h("span", null, wordmark(16), h("span", {style: {fontWeight: 400, color: "#777"}}, " gallery")),
        h("button", {className: "rshell-collapse-btn", title: "Collapse library", onClick: onCollapse}, "‹")),
      h("div", {className: "rshell-controls"},
        h("input", {className: "rshell-input", placeholder: "search…", value: search,
          onChange: (e) => setSearch(e.target.value), style: {marginBottom: 5}}),
        h("div", {style: {display: "flex", gap: 5}},
          h("select", {className: "rshell-select", value: sort, onChange: (e) => setSort(e.target.value)},
            [["id", "number"], ["updated", "date updated"], ["open", "open feedback"], ["rating", "rating"], ["title", "title"]]
              .map(([v, label]) => h("option", {key: v, value: v}, "sort: " + label))),
          h("label", {style: {fontSize: 12, color: "#555", whiteSpace: "nowrap"}},
            h("input", {type: "checkbox", checked: reverse, onChange: (e) => setReverse(e.target.checked)}), " ⇅"))),
      h("div", {style: {overflowY: "auto", flex: 1}},
        general ? h("div", {className: "rshell-row rshell-general-row" + (general.key === selected ? " active" : ""),
          onClick: () => setSelected(general.key)},
          h("div", {className: "rshell-general-title-row"},
            h("div", {className: "rshell-row-title"}, "◆ General"),
            h("button", {className: "rshell-button secondary rshell-new-app-inline",
              onClick: (evt) => {
                evt.stopPropagation();
                onNewApp();
              }}, "+ New app")),
          h("div", {className: "rshell-row-meta"}, "gallery & runner feedback",
            general.metrics && general.metrics.open ? " · ●" + general.metrics.open + " open" : "")) : null,
        h("div", {className: "rshell-app-count"},
          h("span", null, rows.length + " apps"),
          workspaces.length ? h("button", {onClick: onWorkspaces}, workspaces.length + " workspace" +
            (workspaces.length === 1 ? "" : "s")) : null),
        rows.map((a) => h(React.Fragment, {key: a.key},
          h("div", {className: "rshell-row" + (a.key === selected ? " active" : ""),
            onClick: () => setSelected(a.key)},
            h("div", {className: "rshell-row-title-line"},
              h("div", {className: "rshell-row-title"}, a.port ? a.port + " · " : "", a.title),
              h("button", {className: "rshell-fork-btn", title: "Fork app in workspace", onClick: (evt) => {
                evt.stopPropagation(); onFork(a);
              }}, "⑂")),
            h("div", {className: "rshell-row-meta"},
              a.metrics.avg_stars ? "★" + a.metrics.avg_stars + " " : "",
              a.metrics.open ? "●" + a.metrics.open + " open" : a.kind),
            h("div", null, (a.tags || []).map((t) => h("span", {key: t, className: "rshell-tag",
              style: {background: a.color || "#888"}}, t)))),
          workspaces.filter((ws) => ws.app_key === a.key).map((ws) => h("button", {key: ws.id,
            className: "rshell-workspace-child", title: ws.branch || ws.owning_repo_base_sha,
            onClick: () => ws.url ? window.open(ws.url, "_blank") : onWorkspaces()},
            h("span", {className: "dot " + ws.status}), "⑂ ", ws.name,
            h("span", null, ws.status)))))));
  }

  function Entry({entry, depth, children, actions, onReply, onAction, onPreview, canReplay, onReplay}) {
    const isSystem = entry.kind === "system" || entry.author === "claude";
    const marginLeft = Math.min(depth * 14, 56);
    const st = entry.status || "new";
    const status = isSystem ? null : (entry.trace_url
      ? h("a", {href: entry.trace_url, target: "_blank", className: "rshell-status",
          style: {background: STATUS[st] || "#777"}}, st)
      : h("span", {className: "rshell-status", style: {background: STATUS[st] || "#777"}}, st));
    const actionBlock = isSystem && actions && actions.target === entry.id
      ? h("div", {style: {marginTop: 6}},
          actions.items.map(([label, value]) => h("button", {key: label, className: "rshell-button",
            style: {fontSize: 11, padding: "3px 11px", marginRight: 5, background: "#2980b9", color: "#fff"},
            onClick: () => onAction(value, entry.id)}, label)),
          h("span", {style: {fontSize: 10, color: "#999"}}, "optional — or type a reply"))
      : null;
    const body = h("div", {className: "rshell-entry " + (isSystem ? "system" : "user"),
        style: {marginLeft, borderLeft: isSystem ? undefined : "2px solid " + (STATUS[st] || "#777"),
          opacity: st === "done" ? .65 : 1}},
      h("div", {className: "rshell-entry-head"},
        isSystem ? h("b", {style: {color: "#2980b9"}}, "⚙ " + actor(entry)) : null,
        !isSystem && entry.stars ? h("span", {style: {color: "#cc7a00", fontSize: 13, marginRight: 6}}, "★".repeat(entry.stars)) : null,
        status, " ", ts(entry.ts), entry.user && entry.user.name ? " · " + entry.user.name : "",
        canReplay && entry.replay_eligible ? h("button", {className: "rshell-replay-entry",
          title: "Replay this completed task in an isolated workspace", onClick: () => onReplay(entry.id)}, "Replay") : null,
        h("button", {className: "rshell-reply", onClick: () => onReply(entry)}, "reply")),
      h("div", {className: "rshell-entry-body"}, entry.comment || ""),
      entry.shot_url ? h("img", {className: "rshell-shot", src: entry.shot_url}) : null,
      h(DesignReferenceSummary, {entry}),
      h(AnnotationSummary, {entry, onPreview}),
      h(VoiceSummary, {entry}),
      actionBlock);
    return h("div", {className: "rshell-thread"}, body,
      (children[entry.id] || []).map((c) => h(Entry, {key: c.id, entry: c, depth: depth + 1, children,
        actions, onReply, onAction, onPreview, canReplay, onReplay})));
  }

  function AccountMenu({boot}) {
    const [open, setOpen] = useState(false);
    const auth = (boot && boot.auth) || {};
    const user = (boot && boot.user) || {};
    const mode = auth.mode || "none";
    const verified = Boolean(user && user.name && mode !== "none");
    const name = user.name || "anonymous";
    const items = [];
    if (auth.is_admin) {
      const workspaceHref = boot.workspace && boot.workspace.control_url
        ? boot.workspace.control_url + "/?workspaces=1" : "/?workspaces=1";
      items.push(["Workspaces", workspaceHref, "_top"], ["Queue", "/queue", "app-frame"],
        ["Settings", "/settings", "app-frame"]);
    }
    if (verified) {
      items.push(["Profile", "/profile", "app-frame"], ["Sign out", "/logout", "_top"]);
    } else {
      items.push(["Log in", "/login", mode === "oidc" || mode === "local" ? "_top" : "app-frame"]);
    }
    return h("div", {className: "rshell-auth"},
      open ? h("button", {className: "rshell-auth-scrim", "aria-label": "close account menu",
        onClick: () => setOpen(false)}) : null,
      h("button", {className: "rshell-auth-trigger", onClick: () => setOpen(!open)},
        h("span", {className: verified ? "rshell-auth-dot on" : "rshell-auth-dot"}, verified ? "●" : "○"),
        h("span", null, name),
        h("span", {className: "rshell-auth-caret"}, "▾")),
      open ? h("div", {className: "rshell-auth-menu"},
        items.map(([label, href, target]) => h("a", {key: label, className: "auth-menu-item",
          href, target, onClick: () => setOpen(false)}, label))) : null);
  }

  function Feedback({boot, selected, selectedApp, feedback, setFeedback, reloadApps,
      open, collapsed, onCollapse, onReplay}) {
    const [stars, setStars] = useState("");
    const [comment, setComment] = useState("");
    const [shot, setShot] = useState(null);
    const [shotApp, setShotApp] = useState(null);
    const [shotSource, setShotSource] = useState(null);
    const [annotations, setAnnotations] = useState([]);
    const [shotEditorOpen, setShotEditorOpen] = useState(false);
    const [transcriptSegments, setTranscriptSegments] = useState([]);
    const [retainedAudioRef, setRetainedAudioRef] = useState(null);
    const [narrativeClockStart, setNarrativeClockStart] = useState(null);
    const [replyTo, setReplyTo] = useState(null);
    const [designRefs, setDesignRefs] = useState([]);
    const [designAttachOpen, setDesignAttachOpen] = useState(false);
    const [designUrl, setDesignUrl] = useState("");
    const [designLabel, setDesignLabel] = useState("");
    const [previewEntry, setPreviewEntry] = useState(null);
    const [msg, setMsg] = useState("");
    const [recording, setRecording] = useState(false);
    const [dictating, setDictating] = useState(false);
    const recorderRef = useRef(null);
    const speechRef = useRef(null);
    const audioChunksRef = useRef([]);
    const narrativeClockRef = useRef(null);
    const recordingOffsetRef = useRef(0);
    const selectedRef = useRef(selected);
    selectedRef.current = selected;

    function clearShotDraft() {
      setShot(null);
      setShotApp(null);
      setShotSource(null);
      setAnnotations([]);
      setShotEditorOpen(false);
    }

    useEffect(() => {
      window.curiatorShell = window.curiatorShell || {};
      window.curiatorShell.replyTo = function (key, id) {
        window.curiatorShell.selectApp(key);
        setReplyTo({key, id});
      };
    }, []);
    useEffect(() => () => {
      const active = recorderRef.current;
      if (active && active.stream) stopCaptureStream(active.stream);
      const speech = speechRef.current;
      if (speech) {
        speech.onend = null;
        speech.abort();
      }
    }, []);
    useEffect(() => {
      if (replyTo && replyTo.key !== selected) setReplyTo(null);
      if (previewEntry) setPreviewEntry(null);
      if (transcriptSegments.length) setTranscriptSegments([]);
      if (retainedAudioRef) setRetainedAudioRef(null);
      narrativeClockRef.current = null;
      if (narrativeClockStart !== null) setNarrativeClockStart(null);
      if (shot || shotApp || shotSource || annotations.length || shotEditorOpen) clearShotDraft();
      if (designRefs.length) setDesignRefs([]);
      if (designAttachOpen) setDesignAttachOpen(false);
      if (designUrl) setDesignUrl("");
      if (designLabel) setDesignLabel("");
    }, [selected]);

    const items = feedback.items || [];
    const byId = new Map(items.map((e) => [e.id, e]));
    const target = replyTo && byId.get(replyTo.id);
    const t = tree(items);
    const auth = (boot && boot.auth) || {};
    const user = (boot && boot.user) || {};
    const voice = (boot && boot.voice) || {};
    const figma = (((boot && boot.agent_capabilities) || {}).figma) || {};
    const anonymousHeld = Boolean(auth.allow_anonymous && auth.mode !== "none" && !(user && user.name));

    function refresh() {
      return api("/api/feedback/" + encodeURIComponent(selected)).then(setFeedback).then(reloadApps);
    }

    function save() {
      const draftShot = shot && (!shotApp || shotApp === selected) ? shot : null;
      const draftAnnotations = draftShot ? annotations : [];
      if (!stars && !comment.trim() && !draftShot && !retainedAudioRef && !designRefs.length) {
        setMsg("Add a rating, comment, screenshot, or design reference.");
        return;
      }
      setMsg(draftShot && draftAnnotations.length ? "Compositing annotation…" : "");
      composeShot(draftShot, draftAnnotations).then((screenshot) => {
        const payload = {stars: stars ? Number(stars) : null, comment, screenshot,
          screenshot_source: screenshot ? shotSource : null,
          annotations: screenshot ? draftAnnotations : [],
          transcript_segments: transcriptSegments,
          audio_ref: retainedAudioRef,
          design_refs: designRefs,
          reply_to: target ? [target.id] : []};
        return api("/api/feedback/" + encodeURIComponent(selected), {method: "POST", body: JSON.stringify(payload)});
      })
        .then((data) => {
          setFeedback(data);
          setStars("");
          setComment("");
          clearShotDraft();
          setTranscriptSegments([]);
          setRetainedAudioRef(null);
          setDesignRefs([]);
          setDesignAttachOpen(false);
          setDesignUrl("");
          setDesignLabel("");
          narrativeClockRef.current = null;
          setNarrativeClockStart(null);
          setReplyTo(null);
          const audio = data.entry.audio ? " +audio" : "";
          setMsg(data.entry.status === "held"
            ? "✓ queued for review (" + data.entry.id + ")" + (data.entry.screenshot ? " +screenshot" : "") + audio
            : "✓ saved (" + data.entry.id + ")" + (data.entry.screenshot ? " +screenshot" : "") + audio);
          reloadApps();
        }).catch((e) => setMsg(e.error || "Save failed."));
    }

    function capture() {
      const captureApp = selected;
      const iframe = document.getElementById("app-frame");
      const doc = iframe && (iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document));
      if (!doc || typeof html2canvas === "undefined") {
        setMsg("Capture failed: app is not readable.");
        return;
      }
      html2canvas(doc.body, {logging: false, backgroundColor: "#ffffff"})
        .then((canvas) => {
          if (captureApp !== selectedRef.current) return;
          setShot(canvas.toDataURL("image/png"));
          setShotApp(captureApp);
          setShotSource("capture");
          setAnnotations([]);
          setShotEditorOpen(false);
        })
        .catch((e) => setMsg("Capture failed: " + e));
    }

    function stopCaptureStream(stream) {
      (stream && stream.getTracks ? stream.getTracks() : []).forEach((track) => track.stop());
    }

    function nativeCapture() {
      const captureApp = selected;
      const media = navigator.mediaDevices || {};
      if (!media.getDisplayMedia) {
        setMsg("Native capture unavailable in this browser.");
        return;
      }
      setMsg("Choose a tab or window to capture.");
      media.getDisplayMedia({video: true, audio: false}).then((stream) => {
        const video = document.createElement("video");
        video.muted = true;
        video.playsInline = true;
        return new Promise((resolve, reject) => {
          video.onloadedmetadata = () => {
            video.play().then(() => {
              const nextFrame = window.requestAnimationFrame || ((fn) => window.setTimeout(fn, 0));
              nextFrame(() => {
                try {
                  const width = video.videoWidth || 1;
                  const height = video.videoHeight || 1;
                  const canvas = document.createElement("canvas");
                  canvas.width = width;
                  canvas.height = height;
                  const ctx = canvas.getContext("2d");
                  if (!ctx) throw new Error("canvas unavailable");
                  ctx.drawImage(video, 0, 0, width, height);
                  resolve(canvas.toDataURL("image/png"));
                } catch (e) {
                  reject(e);
                }
              });
            }).catch(reject);
          };
          video.onerror = () => reject(new Error("video stream failed"));
          video.srcObject = stream;
        }).finally(() => stopCaptureStream(stream));
      }).then((dataUrl) => {
        if (captureApp !== selectedRef.current) return;
        setShot(dataUrl);
        setShotApp(captureApp);
        setShotSource("native");
        setAnnotations([]);
        setShotEditorOpen(false);
        setMsg("Native capture ready.");
      }).catch((e) => setMsg("Native capture failed: " + (e && e.message ? e.message : e)));
    }

    function appendTranscript(text) {
      const clean = (text || "").trim();
      if (!clean) return;
      setComment((current) => current.trim() ? current.replace(/\s*$/, "\n\n") + clean : clean);
    }

    function ensureNarrativeClock() {
      if (narrativeClockRef.current == null) {
        narrativeClockRef.current = performance.now();
        setNarrativeClockStart(narrativeClockRef.current);
      }
      return narrativeClockRef.current;
    }

    function offsetTranscriptSegments(segments, offsetMs) {
      return (segments || []).map((seg) => {
        const out = Object.assign({}, seg);
        if (Number.isFinite(Number(out.start_ms))) out.start_ms = Number(out.start_ms) + offsetMs;
        if (Number.isFinite(Number(out.end_ms))) out.end_ms = Number(out.end_ms) + offsetMs;
        return out;
      });
    }

    function transcribeBlob(blob, offsetMs) {
      const form = new FormData();
      form.append("audio", blob, "feedback.webm");
      setMsg("Transcribing feedback…");
      return fetch("/api/transcribe", {method: "POST", body: form})
        .then((r) => r.ok ? r.json() : r.json().catch(() => ({})).then((j) => Promise.reject(j)))
        .then((data) => {
          appendTranscript(data.text || "");
          const segments = offsetTranscriptSegments(data.segments || [], offsetMs || 0);
          setTranscriptSegments((current) => current.concat(segments));
          setRetainedAudioRef(data.audio_ref || null);
          const count = segments.length;
          const audio = data.audio_ref ? " +retained audio" : "";
          setMsg(data.text
            ? "Transcript added" + (count ? " (" + count + " segments)" : "") + audio + "."
            : (data.audio_ref ? "No speech detected; retained audio ready." : "No speech detected."));
        })
        .catch((e) => setMsg(e.error || "Transcription failed."));
    }

    function browserSpeechCtor() {
      return window.SpeechRecognition || window.webkitSpeechRecognition || null;
    }

    function startBrowserSpeech() {
      if (!voice.web_speech) {
        setMsg("Browser dictation is not enabled for this collection.");
        return;
      }
      const Speech = browserSpeechCtor();
      if (!Speech) {
        setMsg("Browser dictation is unavailable in this browser.");
        return;
      }
      try {
        const recognition = new Speech();
        recognition.continuous = true;
        recognition.interimResults = true;
        if (voice.web_speech_lang) recognition.lang = voice.web_speech_lang;
        recognition.onresult = (event) => {
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const result = event.results[i];
            if (result && result.isFinal && result[0] && result[0].transcript) {
              appendTranscript(result[0].transcript);
            }
          }
        };
        recognition.onerror = (event) => {
          speechRef.current = null;
          setDictating(false);
          setMsg("Browser dictation failed: " + ((event && event.error) || "unknown error"));
        };
        recognition.onend = () => {
          speechRef.current = null;
          setDictating(false);
          setMsg("Browser dictation stopped.");
        };
        speechRef.current = recognition;
        recognition.start();
        setDictating(true);
        setMsg("Browser dictation active…");
      } catch (e) {
        speechRef.current = null;
        setDictating(false);
        setMsg("Browser dictation failed: " + (e && e.message ? e.message : e));
      }
    }

    function stopBrowserSpeech() {
      const active = speechRef.current;
      if (!active) return;
      setMsg("Stopping browser dictation…");
      active.stop();
    }

    function startVoice() {
      const media = navigator.mediaDevices || {};
      if (!voice.local_transcribe) {
        setMsg("Local transcription is not configured.");
        return;
      }
      if (!media.getUserMedia || typeof MediaRecorder === "undefined") {
        setMsg("Voice recording is unavailable in this browser.");
        return;
      }
      media.getUserMedia({audio: true}).then((stream) => {
        const recorder = new MediaRecorder(stream);
        audioChunksRef.current = [];
        recorderRef.current = {recorder, stream};
        const clockStart = ensureNarrativeClock();
        recordingOffsetRef.current = Math.max(0, performance.now() - clockStart);
        recorder.ondataavailable = (e) => {
          if (e.data && e.data.size) audioChunksRef.current.push(e.data);
        };
        recorder.onstop = () => {
          const active = recorderRef.current;
          recorderRef.current = null;
          setRecording(false);
          stopCaptureStream(active && active.stream);
          const blob = new Blob(audioChunksRef.current, {type: recorder.mimeType || "audio/webm"});
          audioChunksRef.current = [];
          if (!blob.size) {
            setMsg("No audio recorded.");
            return;
          }
          transcribeBlob(blob, recordingOffsetRef.current);
        };
        recorder.start();
        setRecording(true);
        setMsg("Recording feedback…");
      }).catch((e) => setMsg("Voice recording failed: " + (e && e.message ? e.message : e)));
    }

    function stopVoice() {
      const active = recorderRef.current;
      if (!active || !active.recorder) return;
      setMsg("Preparing transcript…");
      active.recorder.stop();
    }

    function upload(file) {
      if (!file) return;
      const captureApp = selected;
      const r = new FileReader();
      r.onload = () => {
        if (captureApp !== selectedRef.current) return;
        setShot(r.result);
        setShotApp(captureApp);
        setShotSource("upload");
        setAnnotations([]);
        setShotEditorOpen(false);
      };
      r.readAsDataURL(file);
    }

    function addDesignRef() {
      const raw = designUrl.trim();
      if (!raw) {
        setMsg("Paste a node-specific Figma URL.");
        return;
      }
      try {
        const parsed = new URL(raw);
        const host = parsed.hostname.toLowerCase();
        const make = parsed.pathname.startsWith("/make/");
        if (parsed.protocol !== "https:" || !["figma.com", "www.figma.com"].includes(host)) {
          throw new Error("Use an https://figma.com URL.");
        }
        if (!make && !parsed.searchParams.get("node-id")) {
          throw new Error("Copy a Figma URL for a specific frame or component with node-id.");
        }
      } catch (e) {
        setMsg((e && e.message) || "Invalid Figma URL.");
        return;
      }
      if (designRefs.some((ref) => ref.url === raw)) {
        setMsg("That design reference is already attached.");
        return;
      }
      if (designRefs.length >= 5) {
        setMsg("A feedback item can carry at most five design references.");
        return;
      }
      setDesignRefs(designRefs.concat([{provider: "figma", url: raw, label: designLabel.trim(), access: "read"}]));
      setDesignUrl("");
      setDesignLabel("");
      setDesignAttachOpen(false);
      setMsg(figma.read_context === "available"
        ? "Figma node attached."
        : "Figma node attached; it will wait for connector authorization before dispatch.");
    }

    function annotationDoc() {
      try {
        const iframe = document.getElementById("app-frame");
        return iframe && (iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document));
      } catch (e) {
        return null;
      }
    }

    function annotate(mark) {
      if (shotSource !== "capture") return mark;
      return withDomTarget(mark, annotationDoc());
    }

    function useAnnotationDraft(entry, marks) {
      if (!entry || !entry.shot_url) return;
      setShot(entry.shot_url);
      setShotApp(selected);
      setShotSource("replay");
      setAnnotations(copyAnnotations(marks));
      setShotEditorOpen(true);
      setReplyTo({key: selected, id: entry.id});
      setPreviewEntry(null);
      setMsg("Loaded annotated screenshot as a reply draft.");
    }

    function action(value, replyToId) {
      api("/api/action", {method: "POST", body: JSON.stringify({key: selected, value, reply_to: replyToId})})
        .then((data) => {
          setFeedback(data);
          if (data.proposal_result) {
            setMsg(data.proposal_result.action === "approved"
              ? "Proposal approved and merged into the accepted branch."
              : "Proposal rejected; its branch was retained.");
          } else {
            setMsg(data.entry && data.entry.status === "held"
              ? "✓ recorded “" + value + "” — queued for review"
              : "✓ recorded “" + value + "” — processing shortly");
          }
          reloadApps();
        }).catch((e) => setMsg(e.error || "Action failed."));
    }

    return h("aside", {className: "rshell-feedback" + (open ? " open" : "") + (collapsed ? " collapsed" : "")},
      h(AnnotationPreview, {entry: previewEntry, onClose: () => setPreviewEntry(null), onUseDraft: useAnnotationDraft}),
      shotEditorOpen ? h(DraftAnnotationModal, {image: shot, annotations, setAnnotations, annotate,
        clockStart: narrativeClockStart, onClose: () => setShotEditorOpen(false)}) : null,
      h(AccountMenu, {boot}),
      h("div", {className: "rshell-feedback-head"},
        h("h4", null, "Feedback"),
        h("button", {className: "rshell-collapse-btn", title: "Collapse feedback", onClick: onCollapse}, "›")),
      h("div", {style: {fontSize: 11, color: "#777", marginBottom: 6}}, selectedApp ? selectedApp.title : "Select an app"),
      selectedApp && selectedApp.proposal ? h("div", {className: "rshell-proposal-banner"},
        h("b", null, "Proposal preview"),
        h("code", null, selectedApp.proposal.branch),
        h("span", null, "@" + String(selectedApp.proposal.sha || "").slice(0, 8))) : null,
      h("div", {style: {fontSize: 15, color: "#cc7a00", marginBottom: 6}},
        [1, 2, 3, 4, 5].map((n) => h("label", {key: n, style: {marginRight: 4}},
          h("input", {type: "radio", name: "stars", checked: Number(stars) === n, onChange: () => setStars(n),
            style: {display: "none"}}), h("span", {style: {cursor: "pointer", opacity: stars && Number(stars) < n ? .25 : 1}}, "★")))),
      target ? h("div", {className: "rshell-reply-context"},
        h("div", {style: {fontSize: 11}}, "replying to ", h("b", null, actor(target)),
          h("button", {className: "rshell-reply", style: {float: "right", color: "#777"}, onClick: () => setReplyTo(null)}, "×")),
        h("div", {style: {fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"}}, excerpt(target))) : null,
      h("textarea", {className: "rshell-textarea", placeholder: "What's good / what to change…",
        title: DICTATION_HINT, "aria-label": "Feedback comment. " + DICTATION_HINT,
        value: comment, onChange: (e) => setComment(e.target.value)}),
      h("div", {style: {display: "flex", flexWrap: "wrap", gap: 8, margin: "6px 0"}},
        h("button", {className: "rshell-button secondary", onClick: capture}, "📷 Capture view"),
        voice.local_transcribe ? h("button", {className: "rshell-button secondary" + (recording ? " active" : ""),
          title: "Local voice transcription", onClick: recording ? stopVoice : startVoice},
          recording ? "■ Stop" : "🎤 Record") : null,
        voice.web_speech ? h("button", {className: "rshell-button secondary" + (dictating ? " active" : ""),
          title: "Browser Web Speech dictation; may use browser speech services",
          onClick: dictating ? stopBrowserSpeech : startBrowserSpeech},
          dictating ? "■ Dictation" : "🎙 Dictate") : null,
        anonymousHeld ? null : h("button", {className: "rshell-button secondary",
          title: "Browser screen capture", onClick: nativeCapture}, "▣ Native"),
        anonymousHeld ? null : h("label", {className: "rshell-button secondary"}, "⬆ upload",
          h("input", {type: "file", accept: "image/*", style: {display: "none"}, onChange: (e) => upload(e.target.files[0])})),
        figma.enabled ? h("button", {className: "rshell-button secondary", title: "Attach Figma node",
          onClick: () => setDesignAttachOpen(!designAttachOpen)}, "◇ Design") : null),
      designAttachOpen ? h("div", {className: "rshell-design-attach"},
        h("div", {className: "rshell-design-attach-head"},
          h("b", null, "Attach Figma node"),
          h("span", {className: "rshell-design-state " + (figma.read_context || "unavailable")},
            figma.read_context || "unavailable")),
        h("input", {className: "rshell-input", type: "url", placeholder: "https://figma.com/design/…?node-id=…",
          value: designUrl, onChange: (e) => setDesignUrl(e.target.value)}),
        h("input", {className: "rshell-input", placeholder: "label (optional)", value: designLabel,
          onChange: (e) => setDesignLabel(e.target.value), onKeyDown: (e) => {
            if (e.key === "Enter") addDesignRef();
          }}),
        anonymousHeld ? h("div", {className: "rshell-design-note"},
          "This submission will be held for moderation before any provider fetch.") : null,
        h("div", {className: "rshell-design-actions"},
          h("button", {className: "rshell-button secondary", onClick: () => setDesignAttachOpen(false)}, "Cancel"),
          h("button", {className: "rshell-button primary", onClick: addDesignRef}, "Attach"))) : null,
      designRefs.length ? h("div", {className: "rshell-design-drafts"}, designRefs.map((ref, idx) =>
        h("div", {className: "rshell-design-draft", key: ref.url},
          h("a", {href: ref.url, target: "_blank", rel: "noopener noreferrer"}, designRefTitle(ref, idx)),
          h("button", {title: "Remove design reference", onClick: () => {
            setDesignRefs(designRefs.filter((_item, itemIdx) => itemIdx !== idx));
          }}, "×")))) : null,
      shot ? h(ShotThumbnail, {image: shot, annotations, onOpen: () => setShotEditorOpen(true)}) : null,
      h("button", {className: "rshell-button primary", onClick: save}, "Save feedback"),
      h("div", {className: "rshell-msg"}, msg),
      h("hr", {style: {border: "none", borderTop: "1px solid #eee"}}),
      h("div", {style: {fontSize: 11, color: "#666", fontWeight: 700, marginBottom: 4}}, "prior feedback"),
      items.length ? t.roots.map((root) => h(Entry, {key: root.id, entry: root, depth: 0, children: t.children,
        actions: feedback.actions, onReply: (e) => setReplyTo({key: selected, id: e.id}), onAction: action,
        onPreview: (e) => setPreviewEntry(e), canReplay: boot.auth && boot.auth.is_admin && !boot.workspace,
        onReplay}))
        : h("div", {style: {fontSize: 12, color: "#777"}}, "No feedback yet."));
  }

  function App() {
    const [boot, setBoot] = useState(null);
    const [apps, setApps] = useState([]);
    const [general, setGeneral] = useState(null);
    const [selected, setSelectedState] = useState(null);
    const [feedback, setFeedback] = useState({items: []});
    const [search, setSearch] = useState("");
    const [sort, setSort] = useState("id");
    const [reverse, setReverse] = useState(true);
    const [catOpen, setCatOpen] = useState(false);
    const [fbOpen, setFbOpen] = useState(false);
    const [catCollapsed, setCatCollapsed] = useState(false);
    const [fbCollapsed, setFbCollapsed] = useState(false);
    const [newAppOpen, setNewAppOpen] = useState(false);
    const [workspaceApp, setWorkspaceApp] = useState(null);
    const [workspacePanelOpen, setWorkspacePanelOpen] = useState(false);
    const [workspaces, setWorkspaces] = useState([]);
    const [replayFeedbackId, setReplayFeedbackId] = useState(null);
    const [replayGroupId, setReplayGroupId] = useState(null);
    // Deep-link query args (everything except our own `app`) captured at load, forwarded to the mounted
    // app's iframe so `/?app=X&node=crit` behaves like `/app/X/?node=crit`. Cleared when the user
    // manually switches apps, since those args are specific to the deep-linked app.
    const [frameQuery, setFrameQuery] = useState(() => {
      const p = new URLSearchParams(location.search);
      p.delete("app");
      p.delete("replay");
      p.delete("replay_group");
      p.delete("workspaces");
      p.delete("workspace");
      return p.toString();
    });

    function setSelected(key) {
      setSelectedState(key);
      setFrameQuery("");
      setCatOpen(false);
      setFbOpen(false);
      const g = boot && boot.general_key;
      const url = key && key !== g ? "?app=" + encodeURIComponent(key) : location.pathname;
      history.replaceState(null, "", url);
    }

    function loadApps() {
      return api("/api/apps").then((data) => {
        setApps(data.apps || []);
        if (data.general) setGeneral(data.general);
      });
    }

    function newAppCreated(data) {
      const key = boot && boot.general_key;
      setNewAppOpen(false);
      if (key) setSelected(key);
      setFeedback(data || {items: []});
      setFbOpen(true);
      return loadApps();
    }

    function loadWorkspaces() {
      if (!boot || !boot.auth || !boot.auth.is_admin || boot.workspace) return Promise.resolve();
      return api("/api/workspaces").then((data) => setWorkspaces(data.workspaces || [])).catch(() => {});
    }

    function workspaceCreated() {
      setWorkspaceApp(null);
      setWorkspacePanelOpen(true);
      return loadWorkspaces();
    }

    useEffect(() => {
      api("/api/bootstrap").then((b) => {
        const params = new URLSearchParams(location.search);
        const fromUrl = params.get("app");
        setBoot(b);
        setApps(b.apps || []);
        setGeneral(b.general || null);
        setSelectedState(fromUrl || b.general_key);
        if (params.get("replay")) setReplayFeedbackId(params.get("replay"));
        if (params.get("replay_group")) setReplayGroupId(params.get("replay_group"));
        if (b.auth && b.auth.is_admin && !b.workspace) {
          api("/api/workspaces").then((data) => setWorkspaces(data.workspaces || [])).catch(() => {});
          if (params.get("workspaces") === "1") setWorkspacePanelOpen(true);
        }
      });
    }, []);

    useEffect(() => {
      if (!selected) return;
      api("/api/feedback/" + encodeURIComponent(selected)).then(setFeedback);
    }, [selected]);

    useEffect(() => {
      if (!boot || !selected || !boot.poll_ms) return undefined;
      const id = setInterval(() => {
        loadApps();
        api("/api/feedback/" + encodeURIComponent(selected)).then(setFeedback);
        loadWorkspaces();
      }, boot.poll_ms);
      return () => clearInterval(id);
    }, [boot, selected]);

    useEffect(() => {
      window.curiatorShell = Object.assign({}, window.curiatorShell || {}, {
        selectApp: (key) => setSelected(key),
        openNewAppWizard: () => setNewAppOpen(true),
        openWorkspaces: () => setWorkspacePanelOpen(true),
        openReplay: (feedbackId) => setReplayFeedbackId(feedbackId)
      });
    }, [boot]);

    if (!boot) return h("div", {style: {padding: 20, color: "#777"}}, "Loading curIAtor…");
    const generalApp = general || {key: boot.general_key, title: "General — gallery & runner", tags: [],
      color: "#8e44ad", kind: "general", metrics: {open: 0, total: 0}};
    const allApps = [generalApp, ...apps];
    const selectedApp = allApps.find((a) => a.key === selected);
    const src = appSrc(selected, boot.general_key, selectedApp && selectedApp.revision, frameQuery);

    return h("div", {className: "rshell"},
      h(NewAppWizard, {open: newAppOpen, onClose: () => setNewAppOpen(false), onCreated: newAppCreated}),
      h(WorkspaceWizard, {app: workspaceApp, open: Boolean(workspaceApp), onClose: () => setWorkspaceApp(null),
        onCreated: workspaceCreated}),
      h(WorkspacePanel, {open: workspacePanelOpen, workspaces,
        onClose: () => setWorkspacePanelOpen(false), onRefresh: loadWorkspaces}),
      h(ReplayModal, {feedbackId: replayFeedbackId, initialGroupId: replayGroupId, onClose: () => {
        setReplayFeedbackId(null);
        setReplayGroupId(null);
      }}),
      h("div", {className: "rshell-mobilebar"},
        h("button", {className: "shell-mbtn", onClick: () => { setCatOpen(!catOpen); setFbOpen(false); }}, "☰ Library"),
        h("div", {style: {flex: 1, textAlign: "center"}}, wordmark(14)),
        h("button", {className: "shell-mbtn", onClick: () => { setFbOpen(!fbOpen); setCatOpen(false); }}, "💬 Feedback")),
      h(WorkspaceBanner, {workspace: boot.workspace}),
      h("div", {className: "rshell-main"},
        h("div", {className: "rshell-scrim" + (catOpen || fbOpen ? " open" : ""), onClick: () => { setCatOpen(false); setFbOpen(false); }}),
        h(Catalog, {apps: allApps, selected, setSelected, search, setSearch, sort, setSort, reverse, setReverse,
          open: catOpen, collapsed: catCollapsed, onCollapse: () => setCatCollapsed(true),
          onNewApp: () => setNewAppOpen(true), workspaces,
          onFork: (app) => setWorkspaceApp(app), onWorkspaces: () => setWorkspacePanelOpen(true)}),
        catCollapsed ? h("button", {className: "rshell-edge-tab left", title: "Expand library",
          onClick: () => setCatCollapsed(false)}, "Library") : null,
        h("iframe", {id: "app-frame", name: "app-frame", className: "rshell-frame", src}),
        fbCollapsed ? h("button", {className: "rshell-edge-tab right", title: "Expand feedback",
          onClick: () => setFbCollapsed(false)}, "Feedback") : null,
        h(Feedback, {boot, selected, selectedApp, feedback, setFeedback, reloadApps: loadApps,
          open: fbOpen, collapsed: fbCollapsed, onCollapse: () => setFbCollapsed(true),
          onReplay: (feedbackId) => setReplayFeedbackId(feedbackId)})));
  }

  ReactDOM.createRoot(document.getElementById("react-entry-point")).render(h(App));
})();

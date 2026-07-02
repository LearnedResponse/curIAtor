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

  function appSrc(key, generalKey, revision) {
    if (!key) return "";
    if (key === generalKey) return "/general";
    const base = "/app/" + encodeURIComponent(key) + "/";
    const rev = Number(revision) || 0;
    return rev ? base + "?v=" + encodeURIComponent(String(rev)) : base;
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

  function composeShot(dataUrl, annotations) {
    if (!dataUrl || !annotations.length) return Promise.resolve(dataUrl);
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
        resolve(canvas.toDataURL("image/png"));
      };
      img.onerror = () => resolve(dataUrl);
      img.src = dataUrl;
    });
  }

  function AnnotationEditor({image, annotations, setAnnotations}) {
    const canvasRef = useRef(null);
    const imageRef = useRef(null);
    const [tool, setTool] = useState("box");
    const [draft, setDraft] = useState(null);

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
        setAnnotations(annotations.concat([{tool, x1: p.x, y1: p.y, n}]));
        return;
      }
      evt.currentTarget.setPointerCapture(evt.pointerId);
      setDraft({tool, x1: p.x, y1: p.y, x2: p.x, y2: p.y});
    }

    function move(evt) {
      if (!draft) return;
      const p = point(evt);
      setDraft(Object.assign({}, draft, {x2: p.x, y2: p.y}));
    }

    function up(evt) {
      if (!draft) return;
      const p = point(evt);
      const mark = Object.assign({}, draft, {x2: p.x, y2: p.y});
      setDraft(null);
      if (Math.abs(mark.x2 - mark.x1) + Math.abs(mark.y2 - mark.y1) < .015) return;
      setAnnotations(annotations.concat([mark]));
    }

    const tools = [["box", "□"], ["arrow", "↗"], ["pin", "①"], ["redact", "█"]];
    return h("div", {className: "rshell-annotator"},
      h("div", {className: "rshell-annotation-toolbar"},
        tools.map(([value, label]) => h("button", {key: value,
          className: "rshell-tool" + (tool === value ? " active" : ""),
          title: value, onClick: () => setTool(value)}, label)),
        h("button", {className: "rshell-tool", title: "Undo annotation",
          disabled: !annotations.length, onClick: () => setAnnotations(annotations.slice(0, -1))}, "↶"),
        h("button", {className: "rshell-tool", title: "Clear annotations",
          disabled: !annotations.length, onClick: () => setAnnotations([])}, "×")),
      h("div", {className: "rshell-annotation-stage"},
        h("img", {ref: imageRef, src: image, onLoad: redraw, style: {display: "none"}, alt: ""}),
        h("canvas", {ref: canvasRef, className: "rshell-annotation-canvas",
          onPointerDown: down, onPointerMove: move, onPointerUp: up, onPointerCancel: () => setDraft(null)})));
  }

  function Catalog({apps, selected, setSelected, search, setSearch, sort, setSort, reverse, setReverse,
      open, collapsed, onCollapse}) {
    const rows = useMemo(() => {
      const q = (search || "").toLowerCase();
      const filtered = apps
        .filter((a) => a.kind !== "general")
        .filter((a) => !q || [a.key, a.title, ...(a.tags || [])].join(" ").toLowerCase().includes(q));
      filtered.sort((a, b) => {
        if (sort === "open") return (a.metrics.open || 0) - (b.metrics.open || 0);
        if (sort === "rating") return (a.metrics.avg_stars || 0) - (b.metrics.avg_stars || 0);
        if (sort === "title") return String(a.title).localeCompare(String(b.title));
        return String(a.key).localeCompare(String(b.key));
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
            [["id", "number"], ["open", "open feedback"], ["rating", "rating"], ["title", "title"]]
              .map(([v, label]) => h("option", {key: v, value: v}, "sort: " + label))),
          h("label", {style: {fontSize: 12, color: "#555", whiteSpace: "nowrap"}},
            h("input", {type: "checkbox", checked: reverse, onChange: (e) => setReverse(e.target.checked)}), " ⇅"))),
      h("div", {style: {overflowY: "auto", flex: 1}},
        general ? h("div", {className: "rshell-row rshell-general-row" + (general.key === selected ? " active" : ""),
          onClick: () => setSelected(general.key)},
          h("div", {className: "rshell-row-title"}, "◆ General"),
          h("div", {className: "rshell-row-meta"}, "gallery & runner feedback",
            general.metrics && general.metrics.open ? " · ●" + general.metrics.open + " open" : ""),
          h("div", null, h("span", {className: "rshell-tag", style: {background: general.color || "#8e44ad"}}, "meta"))) : null,
        h("div", {className: "rshell-app-count"}, rows.length + " apps"),
        rows.map((a) => h("div", {key: a.key, className: "rshell-row" + (a.key === selected ? " active" : ""),
          onClick: () => setSelected(a.key)},
          h("div", {className: "rshell-row-title"}, a.port ? a.port + " · " : "", a.title),
          h("div", {className: "rshell-row-meta"},
            a.metrics.avg_stars ? "★" + a.metrics.avg_stars + " " : "",
            a.metrics.open ? "●" + a.metrics.open + " open" : a.kind),
          h("div", null, (a.tags || []).map((t) => h("span", {key: t, className: "rshell-tag",
            style: {background: a.color || "#888"}}, t)))))));
  }

  function Entry({entry, depth, children, actions, onReply, onAction}) {
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
        h("button", {className: "rshell-reply", onClick: () => onReply(entry)}, "reply")),
      h("div", {className: "rshell-entry-body"}, entry.comment || ""),
      entry.shot_url ? h("img", {className: "rshell-shot", src: entry.shot_url}) : null,
      actionBlock);
    return h("div", {className: "rshell-thread"}, body,
      (children[entry.id] || []).map((c) => h(Entry, {key: c.id, entry: c, depth: depth + 1, children, actions, onReply, onAction})));
  }

  function AccountMenu({boot}) {
    const [open, setOpen] = useState(false);
    const auth = (boot && boot.auth) || {};
    const user = (boot && boot.user) || {};
    const mode = auth.mode || "none";
    const verified = Boolean(user && user.name && mode !== "none");
    const name = user.name || "anonymous";
    const items = [];
    if (auth.is_admin) items.push(["Queue", "/queue", "app-frame"], ["Settings", "/settings", "app-frame"]);
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
      open, collapsed, onCollapse}) {
    const [stars, setStars] = useState("");
    const [comment, setComment] = useState("");
    const [shot, setShot] = useState(null);
    const [shotSource, setShotSource] = useState(null);
    const [annotations, setAnnotations] = useState([]);
    const [replyTo, setReplyTo] = useState(null);
    const [msg, setMsg] = useState("");

    useEffect(() => {
      window.curiatorShell = window.curiatorShell || {};
      window.curiatorShell.replyTo = function (key, id) {
        window.curiatorShell.selectApp(key);
        setReplyTo({key, id});
      };
    }, []);
    useEffect(() => {
      if (replyTo && replyTo.key !== selected) setReplyTo(null);
    }, [selected]);

    const items = feedback.items || [];
    const byId = new Map(items.map((e) => [e.id, e]));
    const target = replyTo && byId.get(replyTo.id);
    const t = tree(items);
    const auth = (boot && boot.auth) || {};
    const user = (boot && boot.user) || {};
    const anonymousHeld = Boolean(auth.allow_anonymous && auth.mode !== "none" && !(user && user.name));

    function refresh() {
      return api("/api/feedback/" + encodeURIComponent(selected)).then(setFeedback).then(reloadApps);
    }

    function save() {
      if (!stars && !comment.trim() && !shot) {
        setMsg("Add a rating, comment, or screenshot.");
        return;
      }
      setMsg(shot && annotations.length ? "Compositing annotation…" : "");
      composeShot(shot, annotations).then((screenshot) => {
        const payload = {stars: stars ? Number(stars) : null, comment, screenshot,
          screenshot_source: screenshot ? shotSource : null,
          reply_to: target ? [target.id] : []};
        return api("/api/feedback/" + encodeURIComponent(selected), {method: "POST", body: JSON.stringify(payload)});
      })
        .then((data) => {
          setFeedback(data);
          setStars("");
          setComment("");
          setShot(null);
          setShotSource(null);
          setAnnotations([]);
          setReplyTo(null);
          setMsg(data.entry.status === "held"
            ? "✓ queued for review (" + data.entry.id + ")" + (data.entry.screenshot ? " +screenshot" : "")
            : "✓ saved (" + data.entry.id + ")" + (data.entry.screenshot ? " +screenshot" : ""));
          reloadApps();
        }).catch((e) => setMsg(e.error || "Save failed."));
    }

    function capture() {
      const iframe = document.getElementById("app-frame");
      const doc = iframe && (iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document));
      if (!doc || typeof html2canvas === "undefined") {
        setMsg("Capture failed: app is not readable.");
        return;
      }
      html2canvas(doc.body, {logging: false, backgroundColor: "#ffffff"})
        .then((canvas) => {
          setShot(canvas.toDataURL("image/png"));
          setShotSource("capture");
          setAnnotations([]);
        })
        .catch((e) => setMsg("Capture failed: " + e));
    }

    function upload(file) {
      if (!file) return;
      const r = new FileReader();
      r.onload = () => {
        setShot(r.result);
        setShotSource("upload");
        setAnnotations([]);
      };
      r.readAsDataURL(file);
    }

    function action(value, replyToId) {
      api("/api/action", {method: "POST", body: JSON.stringify({key: selected, value, reply_to: replyToId})})
        .then((data) => {
          setFeedback(data);
          setMsg(data.entry && data.entry.status === "held"
            ? "✓ recorded “" + value + "” — queued for review"
            : "✓ recorded “" + value + "” — processing shortly");
          reloadApps();
        });
    }

    return h("aside", {className: "rshell-feedback" + (open ? " open" : "") + (collapsed ? " collapsed" : "")},
      h(AccountMenu, {boot}),
      h("div", {className: "rshell-feedback-head"},
        h("h4", null, "Feedback"),
        h("button", {className: "rshell-collapse-btn", title: "Collapse feedback", onClick: onCollapse}, "›")),
      h("div", {style: {fontSize: 11, color: "#777", marginBottom: 6}}, selectedApp ? selectedApp.title : "Select an app"),
      h("div", {style: {fontSize: 15, color: "#cc7a00", marginBottom: 6}},
        [1, 2, 3, 4, 5].map((n) => h("label", {key: n, style: {marginRight: 4}},
          h("input", {type: "radio", name: "stars", checked: Number(stars) === n, onChange: () => setStars(n),
            style: {display: "none"}}), h("span", {style: {cursor: "pointer", opacity: stars && Number(stars) < n ? .25 : 1}}, "★")))),
      target ? h("div", {className: "rshell-reply-context"},
        h("div", {style: {fontSize: 11}}, "replying to ", h("b", null, actor(target)),
          h("button", {className: "rshell-reply", style: {float: "right", color: "#777"}, onClick: () => setReplyTo(null)}, "×")),
        h("div", {style: {fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"}}, excerpt(target))) : null,
      h("textarea", {className: "rshell-textarea", placeholder: "What's good / what to change…",
        value: comment, onChange: (e) => setComment(e.target.value)}),
      h("div", {style: {display: "flex", gap: 8, margin: "6px 0"}},
        h("button", {className: "rshell-button secondary", onClick: capture}, "📷 Capture view"),
        anonymousHeld ? null : h("label", {className: "rshell-button secondary"}, "⬆ upload",
          h("input", {type: "file", accept: "image/*", style: {display: "none"}, onChange: (e) => upload(e.target.files[0])}))),
      shot ? h(AnnotationEditor, {image: shot, annotations, setAnnotations}) : null,
      h("button", {className: "rshell-button primary", onClick: save}, "Save feedback"),
      h("div", {className: "rshell-msg"}, msg),
      h("hr", {style: {border: "none", borderTop: "1px solid #eee"}}),
      h("div", {style: {fontSize: 11, color: "#666", fontWeight: 700, marginBottom: 4}}, "prior feedback"),
      items.length ? t.roots.map((root) => h(Entry, {key: root.id, entry: root, depth: 0, children: t.children,
        actions: feedback.actions, onReply: (e) => setReplyTo({key: selected, id: e.id}), onAction: action}))
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

    function setSelected(key) {
      setSelectedState(key);
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

    useEffect(() => {
      api("/api/bootstrap").then((b) => {
        const params = new URLSearchParams(location.search);
        const fromUrl = params.get("app");
        setBoot(b);
        setApps(b.apps || []);
        setGeneral(b.general || null);
        setSelectedState(fromUrl || b.general_key);
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
      }, boot.poll_ms);
      return () => clearInterval(id);
    }, [boot, selected]);

    useEffect(() => {
      window.curiatorShell = Object.assign({}, window.curiatorShell || {}, {
        selectApp: (key) => setSelected(key)
      });
    }, [boot]);

    if (!boot) return h("div", {style: {padding: 20, color: "#777"}}, "Loading curIAtor…");
    const generalApp = general || {key: boot.general_key, title: "General — gallery & runner", tags: ["meta"],
      color: "#8e44ad", kind: "general", metrics: {open: 0, total: 0}};
    const allApps = [generalApp, ...apps];
    const selectedApp = allApps.find((a) => a.key === selected);
    const src = appSrc(selected, boot.general_key, selectedApp && selectedApp.revision);

    return h("div", {className: "rshell"},
      h("div", {className: "rshell-mobilebar"},
        h("button", {className: "shell-mbtn", onClick: () => { setCatOpen(!catOpen); setFbOpen(false); }}, "☰ Library"),
        h("div", {style: {flex: 1, textAlign: "center"}}, wordmark(14)),
        h("button", {className: "shell-mbtn", onClick: () => { setFbOpen(!fbOpen); setCatOpen(false); }}, "💬 Feedback")),
      h("div", {className: "rshell-main"},
        h("div", {className: "rshell-scrim" + (catOpen || fbOpen ? " open" : ""), onClick: () => { setCatOpen(false); setFbOpen(false); }}),
        h(Catalog, {apps: allApps, selected, setSelected, search, setSearch, sort, setSort, reverse, setReverse,
          open: catOpen, collapsed: catCollapsed, onCollapse: () => setCatCollapsed(true)}),
        catCollapsed ? h("button", {className: "rshell-edge-tab left", title: "Expand library",
          onClick: () => setCatCollapsed(false)}, "Library") : null,
        h("iframe", {id: "app-frame", name: "app-frame", className: "rshell-frame", src}),
        fbCollapsed ? h("button", {className: "rshell-edge-tab right", title: "Expand feedback",
          onClick: () => setFbCollapsed(false)}, "Feedback") : null,
        h(Feedback, {boot, selected, selectedApp, feedback, setFeedback, reloadApps: loadApps,
          open: fbOpen, collapsed: fbCollapsed, onCollapse: () => setFbCollapsed(true)})));
  }

  ReactDOM.createRoot(document.getElementById("react-entry-point")).render(h(App));
})();

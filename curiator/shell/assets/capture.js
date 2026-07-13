(function () {
  "use strict";

  const captureJobs = new WeakMap();
  const captureLibraryJobs = new WeakMap();
  const captureLibraryScript = Array.from(document.scripts || []).find(function (script) {
    return /\/html2canvas(?:\.min)?\.js(?:[?#]|$)/.test(script.src || "");
  });
  const captureLibraryUrl = captureLibraryScript && captureLibraryScript.src
    ? captureLibraryScript.src
    : new URL("assets/html2canvas.min.js", window.location.href).href;

  function html2canvasFor(doc) {
    const view = doc && doc.defaultView;
    if (!view) return Promise.reject(new Error("app window is not readable"));
    if (typeof view.html2canvas === "function") return Promise.resolve(view.html2canvas);

    const active = captureLibraryJobs.get(doc);
    if (active) return active;

    const job = new Promise(function (resolve, reject) {
      const script = doc.createElement("script");
      script.async = true;
      script.src = captureLibraryUrl;
      script.setAttribute("data-curiator-capture-library", "html2canvas");
      script.addEventListener("load", function () {
        if (typeof view.html2canvas === "function") {
          resolve(view.html2canvas);
        } else {
          reject(new Error("html2canvas loaded without registering in the app window"));
        }
      }, {once: true});
      script.addEventListener("error", function () {
        reject(new Error("app blocked the screenshot capture library"));
      }, {once: true});
      (doc.head || doc.documentElement).appendChild(script);
    }).finally(function () {
      captureLibraryJobs.delete(doc);
    });
    captureLibraryJobs.set(doc, job);
    return job;
  }

  function captureBaseCleanup(doc) {
    if (!doc.head || doc.querySelector("base[href]")) return null;
    const base = doc.createElement("base");
    base.href = doc.baseURI;
    base.setAttribute("data-curiator-capture-base", "");
    doc.head.prepend(base);
    return function cleanup() { base.remove(); };
  }

  function visibleRect(element, view) {
    const rect = element.getBoundingClientRect();
    const style = view && view.getComputedStyle ? view.getComputedStyle(element) : null;
    if (rect.width < 2 || rect.height < 2) return null;
    if (style && (style.display === "none" || style.visibility === "hidden")) return null;
    return rect;
  }

  function imageReady(image) {
    if (typeof image.decode === "function") {
      return image.decode().catch(function () {});
    }
    if (image.complete) return Promise.resolve();
    return new Promise(function (resolve) {
      image.addEventListener("load", resolve, {once: true});
      image.addEventListener("error", resolve, {once: true});
    });
  }

  function plotlySurrogate(doc, plot) {
    const view = doc.defaultView || window;
    const Plotly = view.Plotly;
    const rect = visibleRect(plot, view);
    if (!rect || !Plotly || typeof Plotly.toImage !== "function") return Promise.resolve(null);

    return Promise.resolve(Plotly.toImage(plot, {
      format: "png",
      width: Math.ceil(rect.width),
      height: Math.ceil(rect.height),
      scale: 1
    })).then(function (dataUrl) {
      if (typeof dataUrl !== "string" || !dataUrl.startsWith("data:image/")) return null;
      const image = doc.createElement("img");
      const priorPosition = plot.style.position;
      const computed = view.getComputedStyle ? view.getComputedStyle(plot) : null;
      const changedPosition = !computed || computed.position === "static";
      if (changedPosition) plot.style.position = "relative";
      image.alt = "";
      image.setAttribute("aria-hidden", "true");
      image.setAttribute("data-curiator-capture-surrogate", "plotly");
      Object.assign(image.style, {
        position: "absolute",
        inset: "0",
        width: "100%",
        height: "100%",
        display: "block",
        objectFit: "fill",
        pointerEvents: "none",
        zIndex: "2147483646"
      });
      image.src = dataUrl;
      plot.appendChild(image);
      return imageReady(image).then(function () {
        return function cleanup() {
          image.remove();
          if (changedPosition) plot.style.position = priorPosition;
        };
      });
    }).catch(function () {
      // A failed chart export should not block all feedback capture. html2canvas still gets its normal
      // best-effort pass, and Native capture remains available for unsupported GPU surfaces.
      return null;
    });
  }

  function preparePlotlySurrogates(doc) {
    const plots = Array.from(doc.querySelectorAll(".js-plotly-plot"));
    return Promise.all(plots.map(function (plot) {
      return plotlySurrogate(doc, plot);
    })).then(function (cleanups) {
      return cleanups.filter(Boolean);
    });
  }

  function captureDocument(doc, options) {
    if (!doc || !doc.body) return Promise.reject(new Error("app is not readable"));
    const active = captureJobs.get(doc);
    if (active) return active;

    let cleanups = [];
    let render = null;
    const job = html2canvasFor(doc)
      .then(function (html2canvas) {
        render = html2canvas;
        const cleanupBase = captureBaseCleanup(doc);
        if (cleanupBase) cleanups.push(cleanupBase);
        return preparePlotlySurrogates(doc);
      })
      .then(function (prepared) {
        cleanups = cleanups.concat(prepared);
        return render(doc.body, Object.assign({
          logging: false,
          backgroundColor: "#ffffff"
        }, options || {}));
      })
      .finally(function () {
        cleanups.slice().reverse().forEach(function (cleanup) {
          try { cleanup(); } catch (_error) {}
        });
        captureJobs.delete(doc);
      });
    captureJobs.set(doc, job);
    return job;
  }

  window.curiatorCaptureDocument = captureDocument;
  window.dash_clientside = Object.assign({}, window.dash_clientside, {
    shell: {
      capture: function (nClicks) {
        if (!nClicks) return window.dash_clientside.no_update;
        const iframe = document.getElementById("app-frame");
        if (!iframe) return "ERR:no-iframe";
        const doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
        if (!doc) return "ERR:cross-origin";
        return captureDocument(doc)
          .then(function (canvas) { return canvas.toDataURL("image/png"); })
          .catch(function (error) { return "ERR:" + error; });
      }
    }
  });
})();

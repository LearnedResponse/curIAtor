(function () {
  "use strict";

  const captureJobs = new WeakMap();

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
    if (typeof window.html2canvas !== "function") return Promise.reject(new Error("html2canvas unavailable"));
    const active = captureJobs.get(doc);
    if (active) return active;

    let cleanups = [];
    const job = preparePlotlySurrogates(doc)
      .then(function (prepared) {
        cleanups = prepared;
        return window.html2canvas(doc.body, Object.assign({
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

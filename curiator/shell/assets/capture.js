window.dash_clientside = Object.assign({}, window.dash_clientside, {
  shell: {
    capture: function(n_clicks) {
      if (!n_clicks) { return window.dash_clientside.no_update; }
      var iframe = document.getElementById('app-frame');
      if (!iframe) { return 'ERR:no-iframe'; }
      var doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
      if (!doc) { return 'ERR:cross-origin'; }
      if (typeof html2canvas === 'undefined') { return 'ERR:no-html2canvas'; }
      return html2canvas(doc.body, {logging: false, backgroundColor: '#ffffff'})
        .then(function(canvas){ return canvas.toDataURL('image/png'); })
        .catch(function(e){ return 'ERR:' + e; });
    }
  }
});

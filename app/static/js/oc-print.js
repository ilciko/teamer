// Export PDF del grafico linee di riporto: il grafico (.oc dentro .oc-wrap[data-print]) sta in
// una pagina A4 orientata come lui, ridotto con zoom finché ci sta. Usato da /org/chart e dalle
// simulazioni (dove dopo il grafico seguono altre pagine con la lista dei cambi).
// L'orientamento si fissa già al caricamento (alcuni browser ignorano gli stili cambiati in
// beforeprint); lo zoom tiene un margine di sicurezza perché ogni browser misura la pagina a modo suo.
(function () {
  const wrap = document.querySelector('.oc-wrap[data-print]');
  const oc = wrap && wrap.querySelector('.oc');
  if (!oc) return;
  const page = document.createElement('style');
  document.head.appendChild(page);
  const mm = 96 / 25.4, margin = 10, safe = 0.94;

  function natural() {
    oc.style.zoom = '';
    oc.style.minWidth = '0';
    const w = oc.scrollWidth, h = oc.scrollHeight;
    return { w: w, h: h, land: w >= h * 0.9 };
  }
  function orient(land) {
    page.textContent = '@page { size: A4 ' + (land ? 'landscape' : 'portrait') + '; margin: ' + margin + 'mm; }';
  }
  // altezza di ciò che in stampa sta sopra il grafico (si salta quello marcato no-print)
  function head() {
    let h = 0;
    for (let el = wrap.previousElementSibling; el; el = el.previousElementSibling) {
      if (el.classList.contains('no-print') || el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
      h += el.getBoundingClientRect().height + 14;
    }
    return h;
  }

  const first = natural();
  oc.style.minWidth = '';
  orient(first.land);

  window.addEventListener('beforeprint', function () {
    const n = natural();
    orient(n.land);
    const pw = ((n.land ? 297 : 210) - 2 * margin) * mm * safe;
    const ph = (((n.land ? 210 : 297) - 2 * margin) * mm - head() - 24) * safe;
    oc.style.zoom = Math.min(1, pw / n.w, ph / n.h);
  });
  window.addEventListener('afterprint', function () { oc.style.zoom = ''; oc.style.minWidth = ''; });
})();

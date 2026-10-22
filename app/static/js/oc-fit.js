// Grafico linee di riporto adattato alla larghezza: ogni .oc dentro un .oc-wrap[data-fit] si
// riduce con zoom finché entra nel suo riquadro (mai ingrandito oltre il 100%), anche al resize.
// Il pulsante [data-fit-toggle] passa a 100% con scroll orizzontale e ritorna; la scelta resta
// per il browser (localStorage, facoltativo). Dopo la stampa si riadatta (oc-print azzera lo zoom).
(function () {
  const charts = Array.from(document.querySelectorAll('.oc-wrap[data-fit] .oc'));
  if (!charts.length) return;
  const KEY = 'teamer.oc.full';
  let full = false;
  try { full = localStorage.getItem(KEY) === '1'; } catch (e) { /* storage non disponibile */ }

  function fit() {
    charts.forEach(function (oc) {
      oc.style.zoom = '';
      oc.style.minWidth = '';
      if (full) return;
      oc.style.minWidth = '0';
      const wrap = oc.closest('.oc-wrap');
      const cs = getComputedStyle(wrap);
      const room = wrap.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      oc.style.zoom = Math.min(1, room / oc.scrollWidth);
    });
    document.querySelectorAll('[data-fit-toggle]').forEach(function (b) {
      b.textContent = full ? 'Adatta alla pagina' : 'Zoom 100%';
    });
  }

  document.querySelectorAll('[data-fit-toggle]').forEach(function (b) {
    b.addEventListener('click', function () {
      full = !full;
      try { localStorage.setItem(KEY, full ? '1' : '0'); } catch (e) { /* ignora */ }
      fit();
    });
  });
  fit();
  let t;
  window.addEventListener('resize', function () { clearTimeout(t); t = setTimeout(fit, 150); });
  window.addEventListener('afterprint', function () { setTimeout(fit, 0); });
})();

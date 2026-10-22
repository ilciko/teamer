/* Teamer — battito di sessione.
 *
 * Finché questa pagina è aperta il database resta sbloccato: nessun timeout di
 * inattività può più portarti al login mentre scrivi una nota. Quando l'ultima
 * pagina si chiude, il server chiude davvero la connessione cifrata.
 *
 * Se il DB si blocca lo stesso (updater che riavvia il servizio, portatile
 * sospeso, rete caduta) NON si naviga via: compare un overlay che chiede la
 * password, e quello che hai scritto resta dov'è.
 */
(function () {
  var INTERVAL = (parseInt(document.body.dataset.heartbeat, 10) || 20) * 1000;
  var tab = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : String(Date.now()) + Math.random();
  var bloccato = false;
  var formInSospeso = null;

  var overlay = document.getElementById('lock-overlay');
  var campo = document.getElementById('lock-password');
  var errore = document.getElementById('lock-error');

  function corpo() {
    var f = new FormData();
    f.append('tab', tab);
    return f;
  }

  function ping() {
    fetch('/heartbeat', { method: 'POST', body: corpo(), credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) { d.stato === 'bloccato' ? mostraLock() : nascondiLock(); })
      .catch(function () { /* rete assente: si riprova al giro dopo, senza allarmi */ });
  }

  function mostraLock() {
    if (bloccato) return;
    bloccato = true;
    overlay.hidden = false;
    document.body.classList.add('locked');
    campo.focus();
  }

  function nascondiLock() {
    if (!bloccato) return;
    bloccato = false;
    overlay.hidden = true;
    document.body.classList.remove('locked');
    if (formInSospeso) {           // il submit trattenuto riparte da solo
      var f = formInSospeso;
      formInSospeso = null;
      f.submit();
    }
  }

  function sblocca() {
    var body = new FormData();
    body.append('password', campo.value);
    fetch('/unlock', { method: 'POST', body: body, credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) {
          campo.value = '';
          errore.hidden = true;
          nascondiLock();
          ping();
        } else {
          errore.textContent = d.errore;
          errore.hidden = false;
          campo.select();
        }
      })
      .catch(function () {
        errore.textContent = 'Server non raggiungibile.';
        errore.hidden = false;
      });
  }

  document.getElementById('lock-submit').addEventListener('click', sblocca);
  campo.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); sblocca(); }
  });

  /* Testo non salvato in un ALTRO riquadro della stessa pagina: salvare questo
     form fa un redirect che se lo porterebbe via (succede nella pagina del
     ciclo, che ha quattro form indipendenti). I form htmx non navigano, quindi
     non sono un pericolo per nessuno. */
  function sporco(el) {
    return el.value !== el.defaultValue;
  }

  function altriFormConTestoNonSalvato(form) {
    var campi = document.querySelectorAll('textarea, input[type="text"]');
    for (var i = 0; i < campi.length; i++) {
      if (campi[i].form && campi[i].form !== form && sporco(campi[i])) return true;
    }
    return false;
  }

  /* Rete di sicurezza: a DB bloccato un submit finirebbe nel redirect verso
     /login, portandosi via il testo. Lo tratteniamo, chiediamo la password e
     poi lo rimandiamo. */
  document.addEventListener('submit', function (e) {
    if (e.target.hasAttribute('data-no-lock-guard')) return;
    if (bloccato) {
      e.preventDefault();
      formInSospeso = e.target;
      mostraLock();
      return;
    }
    if (e.target.hasAttribute('hx-post')) return;   // non ricarica: nessun rischio
    if (altriFormConTestoNonSalvato(e.target) &&
        !confirm('In un altro riquadro di questa pagina ci sono modifiche non salvate: ' +
                 'salvando qui la pagina si ricarica e andrebbero perse. Continuare?')) {
      e.preventDefault();
    }
  }, true);
  document.body.addEventListener('htmx:beforeRequest', function (e) {
    if (bloccato) { e.preventDefault(); mostraLock(); }
  });

  ping();                                   // registra subito questa scheda
  setInterval(ping, INTERVAL);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') ping();   // rientro dal background
  });
  window.addEventListener('pageshow', function (e) { if (e.persisted) ping(); });
  window.addEventListener('pagehide', function (e) {
    if (e.persisted) return;                // bfcache: la pagina può tornare
    navigator.sendBeacon('/heartbeat/chiusa', corpo());
  });
})();

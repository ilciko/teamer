-- Team archiviati: un team rimasto vuoto ma con storico (assegnazioni passate,
-- posizioni chiuse) non si può eliminare senza perdere la storia delle persone.
-- Archiviato sparisce da organigramma, grafico, simulazioni e menu, ma resta
-- per lo storico; si ripristina da /org. NULL = attivo.
ALTER TABLE team ADD COLUMN archived_at DATETIME;

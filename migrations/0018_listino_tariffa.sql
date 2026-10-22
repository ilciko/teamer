-- Tariffa a listino corrente per codice (€/giorno di vendita).
-- Serve a confrontare il costo giornaliero calcolato con quello che il listino
-- commerciale chiede davvero: lo scostamento dice se il prezzo copre il costo.
-- NULL = tariffa non ancora definita: nessun confronto.
ALTER TABLE listino_profile ADD COLUMN day_rate REAL;

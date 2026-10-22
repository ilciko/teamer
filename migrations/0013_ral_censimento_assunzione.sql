-- L'import Excel datava il ral_event di censimento con la data di riferimento
-- dell'import, anche per chi era stato assunto dopo: nell'analisi salary un
-- neoassunto mostrava la data del censimento invece della sua assunzione.
-- Assignment ed employment usavano già `hire or ref_date`; qui si allinea lo
-- storico. Chi è stato assunto PRIMA resta com'è: la RAL censita è quella
-- vigente alla data di riferimento, non all'assunzione.
UPDATE ral_event
   SET effective_date = (SELECT p.hire_date FROM person p WHERE p.id = ral_event.person_id)
 WHERE change_type = 'censimento'
   AND EXISTS (SELECT 1 FROM person p WHERE p.id = ral_event.person_id
                 AND p.hire_date IS NOT NULL
                 AND p.hire_date > ral_event.effective_date);

-- Soglie di anzianità dell'ultima variazione di RAL (Configurazione → Generale):
-- oltre la prima l'analisi salary evidenzia in arancio, oltre la seconda in rosso.
INSERT INTO app_meta (key, value) VALUES
    ('ral_stale_amber_years', '2'),
    ('ral_stale_red_years', '4')
ON CONFLICT(key) DO NOTHING;

-- Listino: costo giornaliero di vendita dei profili tecnici.
--
-- 1. listino_profile è il catalogo dei codici commerciali (es. GE040 /
--    Consultant PM): una categoria d'offerta più larga del ruolo, che non
--    coincide mai con livello o role_type. Si rinomina la descrizione, il
--    codice resta stabile; si disattiva, mai si cancella (le assegnazioni
--    storiche lo citano).
-- 2. Il codice vive sulla person_assignment, accanto a team e role_type:
--    cambia con una nuova assegnazione (storicizzato) e si corregge in place.
--    Platea del listino = assegnazioni correnti con codice non nullo; chi non
--    ce l'ha (COO, HR, staff) è fuori senza bisogno di un flag a parte.
-- 3. I parametri del calcolo stanno in app_meta (Listino → «Salva come
--    predefiniti»). listino_festivita_gg = '' significa «dal calendario
--    dell'anno»: le festività nazionali che cadono in giorno feriale.
CREATE TABLE listino_profile (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE person_assignment ADD COLUMN listino_profile_id INTEGER REFERENCES listino_profile(id);

INSERT INTO app_meta (key, value) VALUES
    ('listino_oneri_mult', '1.41'),
    ('listino_premi_pct', '0'),
    ('listino_altri_costi', '2000'),
    ('listino_festivita_gg', ''),
    ('listino_festivita_extra_gg', '1'),
    ('listino_ferie_gg', '33'),
    ('listino_malattia_gg', '5'),
    ('listino_formazione_pct', '5'),
    ('listino_interne_pct', '5'),
    ('listino_saturazione_pct', '100')
ON CONFLICT(key) DO NOTHING;

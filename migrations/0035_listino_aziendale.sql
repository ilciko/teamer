-- Tappa 5 del profilo HR: il listino diventa aziendale. I codici (listino_profile) e i parametri
-- (listino_* in user_meta) tornano unici per l'istanza, gestiti da HR in Azienda → Listino: tutti i
-- director leggono gli stessi numeri. Le copie per director si fondono per codice (vince la più
-- vecchia con un proprietario, come nella 0030) e le assegnazioni vengono ripuntate. I parametri
-- prendono i valori di un director (il più vecchio); le festività diventano un numero fisso
-- (10 giorni, niente più calendario dell'anno) e i weekend sono 104 fissi.
PRAGMA foreign_keys=OFF;
BEGIN;

CREATE TABLE listino_profile_map (old INTEGER PRIMARY KEY, new INTEGER NOT NULL);
INSERT INTO listino_profile_map
    SELECT l.id, (SELECT l2.id FROM listino_profile l2 WHERE l2.code = l.code
                   ORDER BY l2.owner_user_id IS NULL, l2.id LIMIT 1) FROM listino_profile l;
UPDATE person_assignment SET listino_profile_id = (SELECT new FROM listino_profile_map WHERE old = listino_profile_id)
    WHERE listino_profile_id IS NOT NULL;

CREATE TABLE listino_profile_new (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    day_rate REAL
);
INSERT INTO listino_profile_new (id, code, description, active, sort_order, day_rate)
    SELECT id, code, description, active, sort_order, day_rate FROM listino_profile
     WHERE id IN (SELECT new FROM listino_profile_map);
DROP TABLE listino_profile;
ALTER TABLE listino_profile_new RENAME TO listino_profile;
DROP TABLE listino_profile_map;

-- parametri: da user_meta (per director) ad app_meta (aziendali); festività vuote = 10 giorni fissi
INSERT OR REPLACE INTO app_meta (key, value)
    SELECT u.key, u.value FROM user_meta u
     WHERE u.key LIKE 'listino\_%' ESCAPE '\'
       AND u.id = (SELECT u2.id FROM user_meta u2 WHERE u2.key = u.key ORDER BY u2.owner_user_id IS NULL, u2.id LIMIT 1);
DELETE FROM user_meta WHERE key LIKE 'listino\_%' ESCAPE '\';
UPDATE app_meta SET value = '10' WHERE key = 'listino_festivita_gg' AND TRIM(value) = '';

COMMIT;
PRAGMA foreign_keys=ON;

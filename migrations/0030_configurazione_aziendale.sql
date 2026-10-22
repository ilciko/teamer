-- Configurazione aziendale (gestita dall'admin, poi da HR): liste valori, catalogo benefit
-- e CCNL predefinito tornano unici per l'istanza (dalla 0028 erano per director).
-- Le copie per director si fondono: per ogni voce vince quella di un director (la più
-- vecchia: di norma l'originale assegnato con i dati), poi quella senza proprietario.
-- I benefit si uniscono per nome e le assegnazioni vengono ripuntate.
-- Inoltre ogni valutazione 9-box salva d'ora in poi il questionario usato (model_snapshot).
PRAGMA foreign_keys=OFF;
BEGIN;

CREATE TABLE lookup_new (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (category, code)
);
INSERT INTO lookup_new (id, category, code, label, sort_order, active)
    SELECT l.id, l.category, l.code, l.label, l.sort_order, l.active FROM lookup l
     WHERE l.id = (SELECT l2.id FROM lookup l2 WHERE l2.category = l.category AND l2.code = l.code
                    ORDER BY l2.owner_user_id IS NULL, l2.id LIMIT 1);
DROP TABLE lookup;
ALTER TABLE lookup_new RENAME TO lookup;

CREATE TABLE benefit_type_map (old INTEGER PRIMARY KEY, new INTEGER NOT NULL);
INSERT INTO benefit_type_map
    SELECT b.id, (SELECT b2.id FROM benefit_type b2 WHERE b2.name = b.name
                   ORDER BY b2.owner_user_id IS NULL, b2.id LIMIT 1) FROM benefit_type b;
UPDATE benefit_assignment SET benefit_type_id = (SELECT new FROM benefit_type_map WHERE old = benefit_type_id);
CREATE TABLE benefit_type_new (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    value_kind TEXT NOT NULL DEFAULT 'boolean',
    enum_options TEXT,
    is_cost INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1
);
INSERT INTO benefit_type_new (id, name, value_kind, enum_options, is_cost, active)
    SELECT id, name, value_kind, enum_options, is_cost, active FROM benefit_type
     WHERE id IN (SELECT new FROM benefit_type_map);
DROP TABLE benefit_type;
ALTER TABLE benefit_type_new RENAME TO benefit_type;
DROP TABLE benefit_type_map;

INSERT INTO app_meta (key, value)
    SELECT 'default_ccnl', value FROM user_meta WHERE key = 'default_ccnl'
     ORDER BY owner_user_id IS NULL, id LIMIT 1;
DELETE FROM user_meta WHERE key = 'default_ccnl';

ALTER TABLE ninebox_assessment ADD COLUMN model_snapshot TEXT;

COMMIT;
PRAGMA foreign_keys=ON;

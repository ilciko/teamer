-- Montepremi per ruolo di HR (0.43): un pool con il solo fattore ruolo, moltiplicatori aziendali
-- per ruolo (bonus_role_factor, Azienda → Premi), platea per team con esclusioni (team, ruoli,
-- chi non era in organico a una data), ruolo di riferimento = quello prevalente nell'anno di
-- competenza (il premio pagato in primavera guarda all'anno prima), modificabile per allocazione.
CREATE TABLE bonus_role_factor (
    role_type TEXT PRIMARY KEY,
    factor REAL NOT NULL DEFAULT 1.0
);
INSERT INTO bonus_role_factor (role_type, factor) VALUES ('ic', 1.0), ('tl', 2.0), ('mgr', 3.0), ('sr', 4.0);

ALTER TABLE bonus_pool ADD COLUMN kind TEXT NOT NULL DEFAULT 'composito';   -- composito (director) | ruolo (HR)
ALTER TABLE bonus_pool ADD COLUMN competence_year INTEGER;
ALTER TABLE bonus_pool ADD COLUMN ref_date DATE;                            -- in organico a questa data
ALTER TABLE bonus_pool ADD COLUMN teams TEXT;                               -- JSON: id dei team della platea (vuoto = tutti)
ALTER TABLE bonus_pool ADD COLUMN excluded_roles TEXT;                      -- JSON: ruoli esclusi
ALTER TABLE bonus_allocation ADD COLUMN role_proposed TEXT;                 -- ruolo prevalente nell'anno di competenza
ALTER TABLE bonus_allocation ADD COLUMN role_type TEXT;                     -- ruolo usato per il premio (modificabile)

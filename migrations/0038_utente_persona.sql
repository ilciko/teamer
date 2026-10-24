-- Utente director ↔ persona (0.47.3): IT, creando (o gestendo) un utente director, lo collega alla
-- persona che lo rappresenta nell'organigramma (ruolo «Senior Manager / Director+», sr). Una persona,
-- un utente. HR non sposta una persona collegata a un utente: prima IT la scollega.
ALTER TABLE app_user ADD COLUMN person_id INTEGER REFERENCES person(id);
CREATE UNIQUE INDEX idx_app_user_person ON app_user(person_id) WHERE person_id IS NOT NULL;

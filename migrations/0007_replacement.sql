-- Sostituzioni: una posizione può nascere per rimpiazzare un cessato
ALTER TABLE hiring_position ADD COLUMN replaces_person_id INTEGER REFERENCES person(id);

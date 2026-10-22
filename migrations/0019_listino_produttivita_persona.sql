-- Produttività per persona nel listino.
-- Formazione, attività interne e saturazione non sono uguali per tutti: un
-- junior si forma di più, un referente ha più attività interne. I valori
-- globali (app_meta listino_*) restano il predefinito; qui stanno solo le
-- eccezioni, NULL = usa il predefinito. È un overlay di parametri di calcolo,
-- non uno stato da storicizzare: si corregge in place dalla pagina Listino.
CREATE TABLE listino_person_param (
    person_id INTEGER PRIMARY KEY REFERENCES person(id),
    formazione_pct REAL,
    interne_pct REAL,
    saturazione_pct REAL
);

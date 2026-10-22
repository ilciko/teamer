-- Le note 1:1 sono documenti, non eventi: si correggono in place.
-- Il "cambiamento reale" è una nota nuova (nuovo meeting, nuovo record); la
-- "correzione di un errore" è la modifica di questa. Nessuna query di stato
-- legge meeting_note, quindi non c'è storico da preservare.
-- updated_at NULL = mai modificata (ADD COLUMN non ammette default non costanti).
ALTER TABLE meeting_note ADD COLUMN updated_at DATETIME;

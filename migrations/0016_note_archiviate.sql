-- Archiviazione delle note 1:1.
--
-- Con gli anni la lista si riempie di appunti che non servono più ogni giorno
-- ma non vanno persi. Archiviare toglie la nota di mezzo (lista, ricerca,
-- dashboard, scheda persona) senza cancellarla: un toggle la fa ricomparire e
-- da lì si ripristina. È uno stato reversibile del documento, non una
-- correzione: non tocca updated_at.
-- archived_at NULL = nota attiva.
ALTER TABLE meeting_note ADD COLUMN archived_at DATETIME;

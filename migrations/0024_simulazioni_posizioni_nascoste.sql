-- Simulazioni: una posizione aperta del budget si può nascondere in una simulazione
-- (la riorganizzazione vista senza quell'assunzione). Vale solo lì: applicando la
-- simulazione la posizione resta nel budget com'è; per annullarla si passa da Assunzioni.
ALTER TABLE reorg_position_move ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0;

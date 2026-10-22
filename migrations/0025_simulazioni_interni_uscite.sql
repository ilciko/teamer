-- Simulazioni:
-- * posizione ipotetica "interna": una figura di un altro team invece di un'assunzione
--   (il titolo è il nome della persona; nel grafico ha lo stile di una persona);
-- * persona che esce (reorg_move.hidden): nella simulazione non c'è più. Vale solo lì:
--   applicando la simulazione non si tocca (la cessazione si fa dalla scheda persona).
ALTER TABLE reorg_position ADD COLUMN internal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reorg_move ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0;

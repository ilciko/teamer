-- Tappa 4 del profilo HR: HR sposta una persona a un altro director. La persona arriva nel team
-- tecnico «Da collocare» del destinatario (uno per director, creato al volo: `holding = 1`),
-- da cui il director la assegna a un suo team. Il team «Da collocare» non compare nel grafico
-- finché è vuoto e il director ne vede l'avviso in dashboard finché non si svuota.
ALTER TABLE team ADD COLUMN holding INTEGER NOT NULL DEFAULT 0;

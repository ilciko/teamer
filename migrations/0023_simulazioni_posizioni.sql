-- Simulazioni: anche le posizioni aperte del budget assunzioni si spostano di
-- team e ruolo, come le persone. Una riga solo per chi cambia rispetto alla
-- realtà; applicando la simulazione la posizione si aggiorna in place (è
-- pianificazione, non storia). team_ref come in 0021: > 0 reale, < 0 team nuovo.
-- Se la posizione sparisce (budget eliminato) lo spostamento cade con lei.
CREATE TABLE reorg_position_move (
    scenario_id INTEGER NOT NULL REFERENCES reorg_scenario(id) ON DELETE CASCADE,
    position_id INTEGER NOT NULL REFERENCES hiring_position(id) ON DELETE CASCADE,
    team_ref INTEGER NOT NULL,
    role_type TEXT NOT NULL,
    PRIMARY KEY (scenario_id, position_id)
);

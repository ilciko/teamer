-- Budget aumenti chiudibili (i chiusi restano storico senza evidenza)
ALTER TABLE ral_budget ADD COLUMN status TEXT NOT NULL DEFAULT 'aperto';

-- Snapshot del calcolo del peso composito per ogni allocazione premio (trasparenza)
ALTER TABLE bonus_allocation ADD COLUMN weight_detail TEXT;

-- Moltiplicatori del peso premio: ruolo e rating review (configurabili da UI).
-- Il fattore obiettivi è la formula fissa score/3 (3 = neutro).
CREATE TABLE bonus_factor (
    kind TEXT NOT NULL,
    code TEXT NOT NULL,
    factor REAL NOT NULL,
    PRIMARY KEY (kind, code)
);

INSERT INTO bonus_factor (kind, code, factor) VALUES
    ('role','ic',1.0), ('role','tl',1.2), ('role','mgr',1.3), ('role','sr',1.5),
    ('rating','1',0.5), ('rating','2',0.8), ('rating','3',1.0), ('rating','4',1.2), ('rating','5',1.4);

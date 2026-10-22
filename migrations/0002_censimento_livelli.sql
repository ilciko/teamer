-- Censimento: tipo evento RAL per il primo inserimento (stato attuale, non un aumento)
INSERT INTO lookup (category, code, label, sort_order) VALUES
    ('change_type','censimento','Censimento iniziale',0);

-- Livelli d'inquadramento numerici (1–8); i descrittivi restano ma disattivati
UPDATE lookup SET active = 0 WHERE category='livello' AND code IN ('operaio','impiegato','quadro','dirigente');
INSERT INTO lookup (category, code, label, sort_order) VALUES
    ('livello','1','1',1), ('livello','2','2',2), ('livello','3','3',3), ('livello','4','4',4),
    ('livello','5','5',5), ('livello','6','6',6), ('livello','7','7',7), ('livello','8','8',8);

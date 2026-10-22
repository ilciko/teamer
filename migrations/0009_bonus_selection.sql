-- Montepremi: platea selezionabile e fattori di valutazione attivabili per pool
ALTER TABLE bonus_allocation ADD COLUMN included INTEGER NOT NULL DEFAULT 1;
ALTER TABLE bonus_pool ADD COLUMN use_box INTEGER NOT NULL DEFAULT 1;
ALTER TABLE bonus_pool ADD COLUMN use_role INTEGER NOT NULL DEFAULT 1;
ALTER TABLE bonus_pool ADD COLUMN use_rating INTEGER NOT NULL DEFAULT 1;
ALTER TABLE bonus_pool ADD COLUMN use_goal INTEGER NOT NULL DEFAULT 1;

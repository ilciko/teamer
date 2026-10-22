-- Ordine dei team tra fratelli (stesso parent_team_id): sostituisce l'ordine
-- alfabetico in organigramma, linee di riporto e filtri. Si cambia con
-- "sposta su/giù", che scambia due fratelli e non cambia mai il padre.
ALTER TABLE team ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;

-- partenza = l'ordine alfabetico di oggi, così niente si muove all'aggiornamento
UPDATE team SET sort_order = (
    SELECT COUNT(*) FROM team t2
    WHERE COALESCE(t2.parent_team_id, 0) = COALESCE(team.parent_team_id, 0)
      AND (t2.name < team.name OR (t2.name = team.name AND t2.id < team.id))
);

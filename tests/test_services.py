"""Test dei servizi di calcolo puri."""
from datetime import date

import pytest

from app.services import budget, cost, goal_score, listino, ninebox_calc
from app.services.ninebox_defaults import DEFAULT_NINEBOX_CONFIG

BOXES = DEFAULT_NINEBOX_CONFIG["boxes"]


class TestNinebox:
    def test_consistent_star(self):
        # tutti 3, nessun aggiustamento → box 9 (come nell'artefatto)
        r = ninebox_calc.compute([3, 3, 3, 3, 3, 3], 0, 0, BOXES)
        assert r["box_number"] == 9
        assert r["perf_level"] == "high" and r["pot_level"] == "high"

    def test_low_performer(self):
        r = ninebox_calc.compute([1, 1, 1, 1, 1, 1], 0, 0, BOXES)
        assert r["box_number"] == 1

    def test_new_ic_penalty(self):
        # ic nuovo nel ruolo (artefatto: perf -0.40, pot +0.10):
        # perf 2.0-0.40=1.60 → low; pot 2.0+0.10=2.10 → med → box 3
        r = ninebox_calc.compute([2, 2, 2, 2, 2, 2], -0.40, 0.10, BOXES)
        assert r["adj_perf"] == pytest.approx(1.60)
        assert r["perf_level"] == "low"
        assert r["box_number"] == 3

    def test_senior_adjustment(self):
        # consolidato: -0.10/-0.10; 2.34 è la soglia high
        r = ninebox_calc.compute([3, 2, 2, 3, 3, 3], -0.10, -0.10, BOXES)
        assert r["adj_perf"] == pytest.approx(2.2333, abs=1e-3)
        assert r["perf_level"] == "med"
        assert r["pot_level"] == "high"
        assert r["box_number"] == 8

    def test_clamp(self):
        r = ninebox_calc.compute([3, 3, 3, 3, 3, 3], 0.5, 0.5, BOXES)
        assert r["adj_perf"] == 3.0 and r["adj_pot"] == 3.0

    def test_invalid_answers(self):
        with pytest.raises(ValueError):
            ninebox_calc.compute([1, 2, 3], 0, 0, BOXES)
        with pytest.raises(ValueError):
            ninebox_calc.compute([0, 2, 3, 1, 2, 3], 0, 0, BOXES)


class TestGoalScore:
    def test_weighted(self):
        items = [
            {"weight_pct": 80, "tl_score": 4},
            {"weight_pct": 20, "tl_score": 5},
        ]
        assert goal_score.weighted_score(items) == 4.2

    def test_partial_scores(self):
        items = [
            {"weight_pct": 80, "tl_score": 4},
            {"weight_pct": 20, "tl_score": None},
        ]
        assert goal_score.weighted_score(items) == 4.0

    def test_no_scores(self):
        assert goal_score.weighted_score([{"weight_pct": 100, "tl_score": None}]) is None

    def test_weights_complete(self):
        assert goal_score.weights_complete([{"weight_pct": 80}, {"weight_pct": 20}])
        assert not goal_score.weights_complete([{"weight_pct": 80}])


class TestBudget:
    def test_residual(self):
        assert budget.budget_residual(15000, [2000, 3000]) == 10000

    def test_overrun(self):
        assert budget.budget_residual(1000, [2000]) == -1000

    def test_bonus_proposals_proportional(self):
        out = budget.bonus_proposals(10000, {1: 3.0, 2: 1.0, 3: 0.0})
        assert out[1] == 7500 and out[2] == 2500 and out[3] == 0

    def test_bonus_all_zero_weights(self):
        out = budget.bonus_proposals(10000, {1: 0.0, 2: 0.0})
        assert out == {1: 0.0, 2: 0.0}

    def test_pool_residual(self):
        assert budget.pool_residual(10000, [7500, 2500]) == 0


class TestBudgetPct:
    def test_cap_from_pct(self):
        assert budget.cap_from_pct(2.5, [30000, 20000, 50000]) == 2500

    def test_cap_from_pct_empty(self):
        assert budget.cap_from_pct(3.0, []) == 0


class TestBudgetSummary:
    def test_residuo_al_netto_dell_impegnato(self):
        s = budget.budget_summary(15000, [4200], [6500])
        assert s == {"applicato": 4200, "impegnato": 6500, "residuo": 4300}

    def test_sforamento(self):
        assert budget.budget_summary(1000, [600], [800])["residuo"] == -400

    def test_nulla_allocato(self):
        assert budget.budget_summary(5000, [], []) == {
            "applicato": 0, "impegnato": 0, "residuo": 5000}


class TestGoalCategorie:
    def test_pesi_per_categoria_100_piu_100(self):
        items = [
            {"category": "professionale", "weight_pct": 80},
            {"category": "professionale", "weight_pct": 20},
            {"category": "personale", "weight_pct": 100},
        ]
        assert goal_score.weights_by_category(items) == {
            "professionale": 100, "personale": 100}
        assert goal_score.weights_complete(items)

    def test_categoria_incompleta_segnalata(self):
        items = [
            {"category": "professionale", "weight_pct": 100},
            {"category": "personale", "weight_pct": 40},
        ]
        assert not goal_score.weights_complete(items)

    def test_solo_una_categoria_basta_il_suo_100(self):
        assert goal_score.weights_complete(
            [{"category": "professionale", "weight_pct": 100}])


class TestPesoComposito:
    def test_goal_factor(self):
        assert budget.goal_factor(None) == 1.0
        assert budget.goal_factor(3) == 1.0
        assert budget.goal_factor(4.5) == 1.5

    def test_composite_weight(self):
        assert budget.composite_weight(3.0, 1.2, 1.2, 1.5) == 6.48
        assert budget.composite_weight(3.0) == 3.0
        assert budget.composite_weight(0, 1.5, 1.4, 1.5) == 0


class TestRalDeltas:
    """La variazione mostrata si ricava dalla timeline, non dal delta salvato."""

    EVENTI = [  # ordinati per decorrenza DESC come li carica la scheda persona
        {"effective_date": "2022-07-01", "amount": 48100},
        {"effective_date": "2022-01-01", "amount": 47500},
        {"effective_date": "2021-01-01", "amount": 44000},
        {"effective_date": "2005-02-23", "amount": 39500},
    ]

    def test_delta_dalla_timeline(self):
        rows = cost.derive_deltas(self.EVENTI)
        assert [r["delta_calc"] for r in rows] == [600, 3500, 4500, 0]

    def test_non_altera_gli_eventi_originali(self):
        cost.derive_deltas(self.EVENTI)
        assert "delta_calc" not in self.EVENTI[0]


class TestRalAgeFlag:
    """Anzianità dell'ultima variazione: oltre = più vecchia di, non "compiuti"."""

    OGGI = date(2026, 9, 10)

    def flag(self, eff):
        return cost.ral_age_flag(eff, 2, 4, on_date=self.OGGI)

    def test_recente(self):
        assert self.flag("2026-01-15") == ""

    def test_esattamente_due_anni_non_e_oltre(self):
        assert self.flag("2024-09-10") == ""

    def test_due_anni_e_un_giorno(self):
        assert self.flag("2024-09-09") == "amber"

    def test_esattamente_quattro_anni_resta_arancio(self):
        assert self.flag("2022-09-10") == "amber"

    def test_oltre_quattro_anni(self):
        assert self.flag("2022-09-09") == "red"

    def test_29_febbraio(self):
        # +2 anni da un bisestile cade su un anno che non ha il 29: 1° marzo
        assert cost.ral_age_flag("2024-02-29", 2, 4, on_date=date(2026, 2, 28)) == ""
        assert cost.ral_age_flag("2024-02-29", 2, 4, on_date=date(2026, 3, 2)) == "amber"

    def test_data_assente(self):
        assert cost.ral_age_flag(None, 2, 4, on_date=self.OGGI) == ""

    def test_cutoffs_coerenti_col_flag(self):
        """Le date mostrate in Configurazione sono le stesse che colorano la lista."""
        amber_from, red_from = cost.ral_stale_cutoffs(1, 2, on_date=self.OGGI)
        assert (amber_from.isoformat(), red_from.isoformat()) == ("2025-09-10", "2024-09-10")
        assert cost.ral_age_flag("2025-06-01", 1, 2, on_date=self.OGGI) == "amber"
        assert cost.ral_age_flag(amber_from.isoformat(), 1, 2, on_date=self.OGGI) == ""


class TestListino:
    def test_pasqua(self):
        assert listino.pasqua(2024) == date(2024, 3, 31)
        assert listino.pasqua(2025) == date(2025, 4, 20)
        assert listino.pasqua(2026) == date(2026, 4, 5)
        assert listino.pasqua(2027) == date(2027, 3, 28)

    def test_calendario_conta_davvero(self):
        c = listino.calendario(2026)
        assert (c["giorni"], c["weekend"], c["festivita_feriali"]) == (365, 104, 7)
        assert c["festivita_weekend"] == 4  # 25/4, 15/8, 1/11, 26/12
        c = listino.calendario(2025)
        assert (c["giorni"], c["weekend"], c["festivita_feriali"]) == (365, 104, 10)
        c = listino.calendario(2028)  # bisestile che parte di sabato: mai fissare 104
        assert (c["giorni"], c["weekend"], c["festivita_feriali"]) == (366, 106, 10)

    def test_giorni_default_2026(self):
        g = listino.giorni(2026, dict(listino.DEFAULTS))
        assert g["festivita_auto"] and g["festivita_tot"] == 8
        assert g["lavorabili"] == 253 and g["presenza"] == 215
        assert g["fatturabili_fte"] == pytest.approx(193.5)

    def test_costo_esempio(self):
        p = dict(listino.DEFAULTS)
        c = listino.costo_persona(50000, 0, 100, p, listino.giorni(2026, p))
        assert c["costo_annuo"] == pytest.approx(72500)
        assert c["costo_gg"] == pytest.approx(374.68, abs=0.01)
        c = listino.costo_persona(50000, 0, 100, p, listino.giorni(2025, p))
        assert c["fatturabili"] == pytest.approx(190.8)
        assert c["costo_gg"] == pytest.approx(379.98, abs=0.01)

    def test_part_time_dimezza_i_giorni_non_il_costo(self):
        p = dict(listino.DEFAULTS)
        g = listino.giorni(2026, p)
        full = listino.costo_persona(50000, 0, None, p, g)
        half = listino.costo_persona(50000, 0, 50, p, g)
        assert half["fatturabili"] == pytest.approx(96.75)
        assert half["costo_annuo"] == full["costo_annuo"]
        assert half["costo_gg"] == pytest.approx(full["costo_gg"] * 2)

    def test_premi_con_oneri_benefit_e_altri_senza(self):
        p = {**listino.DEFAULTS, "premi_pct": 10.0, "altri_costi": 2000.0}
        c = listino.costo_persona(50000, 1200, 100, p, listino.giorni(2026, p))
        assert c["costo_annuo"] == pytest.approx(50000 * 1.41 * 1.1 + 1200 + 2000)

    def test_festivita_override_e_extra(self):
        p = {**listino.DEFAULTS, "festivita_gg": 10.0, "festivita_extra_gg": 1.0}
        g = listino.giorni(2026, p)
        assert not g["festivita_auto"] and g["festivita_tot"] == 11 and g["lavorabili"] == 250
        p["festivita_gg"] = None
        assert listino.giorni(2026, p)["lavorabili"] == 253

    def test_fatturabili_non_positivi(self):
        p = {**listino.DEFAULTS, "saturazione_pct": 0.0}
        c = listino.costo_persona(50000, 0, 100, p, listino.giorni(2026, p))
        assert c["costo_gg"] is None and c["motivo"] == "giorni"
        p = {**listino.DEFAULTS, "formazione_pct": 60.0, "interne_pct": 50.0}
        assert listino.costo_persona(50000, 0, 100, p, listino.giorni(2026, p))["motivo"] == "giorni"
        p = dict(listino.DEFAULTS)
        assert listino.costo_persona(50000, 0, 0, p, listino.giorni(2026, p))["motivo"] == "giorni"
        assert listino.costo_persona(None, 0, 100, p, listino.giorni(2026, p))["motivo"] == "ral"

    def test_parse_params_fallback(self):
        saved = {"ferie_gg": "30", "oneri_mult": "", "festivita_gg": ""}
        p = listino.parse_params({"ferie_gg": "", "oneri_mult": "abc", "malattia_gg": "7,5"}, saved)
        assert p["ferie_gg"] == 30 and p["oneri_mult"] == 1.41 and p["malattia_gg"] == 7.5
        assert p["festivita_gg"] is None
        assert listino.parse_params({"festivita_gg": ""}, {"festivita_gg": "9"})["festivita_gg"] is None
        assert listino.parse_params({}, {"festivita_gg": "9"})["festivita_gg"] == 9

    def test_validate_params(self):
        ok = {k: "" if v is None else str(v) for k, v in listino.DEFAULTS.items()}
        p, err = listino.validate_params(ok)
        assert not err and p["festivita_gg"] is None and p["ferie_gg"] == 33
        assert listino.params_to_meta(p)["listino_festivita_gg"] == ""
        assert listino.params_to_meta(p)["listino_altri_costi"] == "2000"
        _, err = listino.validate_params({**ok, "oneri_mult": "abc"})
        assert err
        _, err = listino.validate_params({**ok, "saturazione_pct": "250"})
        assert err
        _, err = listino.validate_params({**ok, "saturazione_pct": "105"})
        assert not err
        _, err = listino.validate_params({**ok, "formazione_pct": "105"})
        assert err
        _, err = listino.validate_params({**ok, "ferie_gg": "-1"})
        assert err

    def test_aggregate(self):
        rows = [
            {"g": "A", "costo_annuo": 72500.0, "fatturabili": 193.5, "costo_gg": 72500 / 193.5},
            {"g": "A", "costo_annuo": 100000.0, "fatturabili": 96.75, "costo_gg": 100000 / 96.75},
            {"g": "A", "costo_annuo": None, "fatturabili": 193.5, "costo_gg": None},
            {"g": "B", "costo_annuo": 50000.0, "fatturabili": 100.0, "costo_gg": 500.0},
        ]
        out = listino.aggregate(rows, "g")
        a, b = out
        assert a["key"] == "A" and a["n"] == 2 and a["n_escluse"] == 1
        assert a["min"] == pytest.approx(374.68, abs=0.01)
        assert a["max"] == pytest.approx(1033.59, abs=0.01)
        assert a["media"] == pytest.approx((374.677 + 1033.592) / 2, abs=0.01)
        assert a["blended"] == pytest.approx(172500 / 290.25, abs=0.01)
        assert a["media"] != a["blended"]
        assert b["n"] == 1 and b["min"] == b["max"] == b["media"] == b["blended"] == 500.0
        assert listino.aggregate([], "g") == []

    def test_scostamento(self):
        s = listino.scostamento(450.0, 374.68)
        assert s["delta"] == pytest.approx(75.32) and s["pct"] == pytest.approx(16.74, abs=0.01)
        s = listino.scostamento(300.0, 374.68)
        assert s["delta"] < 0 and s["pct"] < 0
        assert listino.scostamento(None, 374.68) is None
        assert listino.scostamento(450.0, None) is None
        assert listino.scostamento(0.0, 10.0)["pct"] is None

    def test_aggregate_carry(self):
        rows = [{"g": "A", "rate": 450.0, "costo_annuo": 72500.0, "fatturabili": 193.5, "costo_gg": 72500 / 193.5},
                {"g": "A", "rate": 450.0, "costo_annuo": 58050.0, "fatturabili": 193.5, "costo_gg": 58050 / 193.5}]
        out = listino.aggregate(rows, "g", carry=("rate",))
        assert out[0]["rate"] == 450.0
        # stessi giorni per tutti: blended = media per costruzione
        assert out[0]["blended"] == pytest.approx(out[0]["media"])

    def test_override_produttivita(self):
        p = dict(listino.DEFAULTS)
        g = listino.giorni(2026, p)
        base = listino.costo_persona(50000, 0, 100, p, g)
        ov = listino.costo_persona(50000, 0, 100, p, g, {"saturazione_pct": 50, "formazione_pct": None})
        assert ov["fatturabili"] == pytest.approx(96.75) and ov["prod_custom"]
        assert ov["costo_gg"] == pytest.approx(base["costo_gg"] * 2)
        assert not base["prod_custom"]
        assert listino.prod_persona(p, None)["saturazione_pct"] == 100
        vals, err = listino.parse_prod({"pp_formazione_pct": "", "pp_interne_pct": "abc", "pp_saturazione_pct": "80"})
        assert vals == {"formazione_pct": None, "saturazione_pct": 80.0} and err == ["interne_pct"]

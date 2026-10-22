"""Test delle serie storiche (addetti, monte RAL, per team)."""
from datetime import date

from app.services import trends


PEOPLE = [
    {"id": 1, "hire_date": "2024-03-15", "end_date": None},
    {"id": 2, "hire_date": "2024-06-01", "end_date": "2025-02-28"},  # cessato
    {"id": 3, "hire_date": "2025-01-10", "end_date": None},
]
MONTHS = trends.month_range(date(2024, 3, 1), date(2025, 3, 1))


def test_month_range():
    assert MONTHS[0] == date(2024, 3, 1)
    assert MONTHS[-1] == date(2025, 3, 1)
    assert len(MONTHS) == 13


def test_headcount_con_assunzioni_e_cessazioni():
    hc = trends.headcount_series(PEOPLE, MONTHS)
    # mar 2024: nessuno (1 assunto il 15/3, al 1/3 non ancora); apr: 1; giu: 2
    assert hc[0] == 0 and hc[1] == 1 and hc[3] == 2
    # 1 gen 2025: l'assunto del 10/1 non è ancora attivo → 2; feb: tutti e 3;
    # mar 2025: il cessato (28/2) esce → 2
    assert hc[10] == 2 and hc[11] == 3 and hc[12] == 2


def test_ral_series_con_eventi_multipli():
    events = {
        1: [{"effective_date": "2024-03-15", "amount": 30000},
            {"effective_date": "2025-01-01", "amount": 32000}],
        2: [{"effective_date": "2024-06-01", "amount": 20000}],
        3: [{"effective_date": "2025-01-10", "amount": 25000}],
    }
    ral = trends.ral_series(PEOPLE, events, MONTHS)
    assert ral[1] == 30000            # apr 2024: solo persona 1
    assert ral[4] == 50000            # lug 2024: 30k + 20k
    assert ral[11] == 77000           # feb 2025: 32k (aumentato) + 20k + 25k
    assert ral[12] == 57000           # mar 2025: senza il cessato


def test_team_of_con_cambio_team():
    assignments = [
        {"team_id": 10, "start_date": "2024-03-15", "end_date": "2024-08-31"},
        {"team_id": 20, "start_date": "2024-09-01", "end_date": None},
    ]
    assert trends.team_of(assignments, date(2024, 5, 1)) == 10
    assert trends.team_of(assignments, date(2024, 9, 1)) == 20
    assert trends.team_of(assignments, date(2024, 1, 1)) is None


def test_headcount_by_team_split():
    assignments = {
        1: [{"team_id": 10, "start_date": "2024-03-15", "end_date": None}],
        2: [{"team_id": 10, "start_date": "2024-06-01", "end_date": "2024-12-31"},
            {"team_id": 20, "start_date": "2025-01-01", "end_date": None}],
        3: [],  # senza team
    }
    by_team = trends.headcount_by_team(PEOPLE, assignments, MONTHS)
    m_lug24 = MONTHS.index(date(2024, 7, 1))
    m_feb25 = MONTHS.index(date(2025, 2, 1))
    assert by_team[10][m_lug24] == 2          # entrambi in team 10
    assert by_team[10][m_feb25] == 1          # persona 2 passata al 20
    assert by_team[20][m_feb25] == 1
    assert by_team[None][m_feb25] == 1        # persona 3 senza team


def test_monte_ral_vuoto_finche_manca_la_ral_di_qualcuno():
    """Prima del censimento il monte RAL non esiste: buco, non zero.

    Chi c'era già entra in Teamer con un evento di censimento datato al giorno
    dell'import: fino a lì la sua RAL è ignota, e sommarla come zero farebbe
    sembrare un balzo l'inizio della rilevazione.
    """
    events = {
        1: [{"effective_date": "2024-11-01", "amount": 30000}],  # censito a novembre
        2: [{"effective_date": "2024-06-01", "amount": 20000}],
        3: [{"effective_date": "2025-01-10", "amount": 25000}],
    }
    ral = trends.ral_series(PEOPLE, events, MONTHS)
    assert ral[1] is None             # apr 2024: la persona 1 è attiva ma senza RAL nota
    assert ral[4] is None             # lug 2024: idem, anche se la 2 ce l'ha
    assert ral[8] == 50000            # nov 2024: entrambe note → il dato riparte
    assert ral[11] == 75000           # feb 2025: 30k + 20k + 25k


def test_monte_ral_per_team_segue_la_stessa_regola():
    assignments = {
        1: [{"team_id": 10, "start_date": "2024-03-15", "end_date": None}],
        2: [{"team_id": 20, "start_date": "2024-06-01", "end_date": None}],
        3: [{"team_id": 20, "start_date": "2025-01-10", "end_date": None}],
    }
    events = {
        1: [{"effective_date": "2024-11-01", "amount": 30000}],
        2: [{"effective_date": "2024-06-01", "amount": 20000}],
        3: [{"effective_date": "2025-01-10", "amount": 25000}],
    }
    by_team = trends.ral_by_team(PEOPLE, assignments, events, MONTHS)
    m_lug24 = MONTHS.index(date(2024, 7, 1))
    m_dic24 = MONTHS.index(date(2024, 12, 1))
    # il team 10 aspetta la RAL della persona 1; il team 20 ha già la sua
    assert by_team[10][m_lug24] is None and by_team[20][m_lug24] == 20000
    assert by_team[10][m_dic24] == 30000


def test_ral_zero_non_e_dato_mancante():
    """Una RAL registrata a 0 è un dato, non un buco."""
    people = [{"id": 1, "hire_date": "2024-03-15", "end_date": None}]
    events = {1: [{"effective_date": "2024-03-15", "amount": 0}]}
    assert trends.ral_series(people, events, MONTHS)[1] == 0


def test_data_start_dopo_l_ultimo_buco():
    assert trends.data_start([None, None, 10, 20]) == 2
    assert trends.data_start([10, None, 20]) == 2       # conta l'ultimo buco, non il primo
    assert trends.data_start([10, 20]) == 0
    assert trends.data_start([None, None]) == 2         # nessun dato leggibile


def test_missing_ral_nomina_chi_tiene_indietro():
    events = {
        1: [{"effective_date": "2024-11-01", "amount": 30000}],
        2: [{"effective_date": "2024-06-01", "amount": 20000}],
        3: [],
    }
    mancanti = trends.missing_ral(PEOPLE, events, date(2024, 7, 1))
    assert [p["id"] for p in mancanti] == [1]           # la 3 non è ancora assunta

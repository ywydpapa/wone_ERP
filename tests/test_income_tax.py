from migrate import run_migrations
from tests.conftest import _connect

from core.payroll import calc_income_tax, calc_deductions


def test_under_lower_bound_is_zero():
    assert calc_income_tax(769_999) == 0
    assert calc_income_tax(0) == 0


def test_table_lookup_matches_csv():
    assert calc_income_tax(3_000_000, dependents=1) == 74_350
    assert calc_income_tax(3_000_000, dependents=3) == 31_940
    assert calc_income_tax(2_000_000, dependents=1) == 19_520


def test_boundary_lo_inclusive_hi_exclusive():
    assert calc_income_tax(1_999_999, dependents=1) == 19_200
    assert calc_income_tax(2_000_000, dependents=1) == 19_520
    assert calc_income_tax(2_009_999, dependents=1) == 19_520
    assert calc_income_tax(2_010_000, dependents=1) == 19_850


def test_exactly_10m_uses_f_base():
    assert calc_income_tax(10_000_000, dependents=1) == 1_507_400
    assert calc_income_tax(10_000_000, dependents=11) == 960_840


def test_over_10m_uses_formula():
    # 1,507,400 + 2,000,000 x 98% x 35% + 25,000
    assert calc_income_tax(12_000_000, dependents=1) == 1_507_400 + 686_000 + 25_000
    # 1,507,400 + 13,394,600 + 5,000,000 x 42%
    assert calc_income_tax(50_000_000, dependents=1) == 1_507_400 + 13_394_600 + 2_100_000


def test_over_11_family_members():
    # 5,000,000원 행 10명 106,600, 11명 87,850
    assert calc_income_tax(5_000_000, dependents=13) == 87_850 - (106_600 - 87_850) * 2


def test_child_adjustment():
    base = 74_350
    assert calc_income_tax(3_000_000, dependents=1, children=1) == base - 20_830
    assert calc_income_tax(3_000_000, dependents=1, children=2) == base - 45_830
    assert calc_income_tax(3_000_000, dependents=1, children=3) == 0


def test_withholding_rate_truncation():
    # 19,520 기준, 10원 미만 절사
    assert calc_income_tax(2_000_000, dependents=1, rate=80) == 15_610
    assert calc_income_tax(2_000_000, dependents=1, rate=120) == 23_420


def test_resident_tax_truncation_not_rounding():
    # 7,435 절사
    deductions = calc_deductions(3_000_000, {}, dependents=1)
    assert deductions["income_tax"] == 74_350
    assert deductions["resident_tax"] == 7_430


def test_migration_075_applies_on_fresh_db(tmp_path):
    path = str(tmp_path / "t075.db")
    run_migrations(path, upto=74)
    conn = _connect(path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(employees)")}
    assert "tax_child_count" not in cols
    assert "tax_rate" not in cols

    run_migrations(path)
    conn = _connect(path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(employees)")}
    assert "tax_child_count" in cols
    assert "tax_rate" in cols

    eid = conn.execute(
        "INSERT INTO employees (name, company_id, status) VALUES ('테스트', NULL, 'active')"
    ).lastrowid
    row = conn.execute(
        "SELECT tax_child_count, tax_rate FROM employees WHERE id=?", (eid,)
    ).fetchone()
    assert row["tax_child_count"] == 0
    assert row["tax_rate"] == 100
    conn.close()

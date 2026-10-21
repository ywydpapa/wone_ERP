import csv
import io

from core.pay_items import ensure_default_items, get_items
from routers.hr_book_tax import (
    _build_acq_rows, _build_loss_rows, _match_ei_loss_code,
)


def _mk_emp(db, company_id, **kwargs):
    kwargs.setdefault("status", "active")
    cols = ", ".join(kwargs.keys())
    qs = ", ".join("?" * len(kwargs))
    return db.execute(
        f"INSERT INTO employees (company_id, {cols}) VALUES (?, {qs})",
        (company_id, *kwargs.values()),
    ).lastrowid


def _mk_payslip(db, eid, year, month, items, amounts, status="confirmed"):
    gross = sum(amounts.values())
    ps_id = db.execute(
        """INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay, total_deduction, net_pay, status)
           VALUES (?,?,?,?,0,?,?)""",
        (eid, year, month, gross, gross, status),
    ).lastrowid
    for code, amount in amounts.items():
        db.execute(
            "INSERT INTO payslip_items (payslip_id, item_id, amount) VALUES (?,?,?)",
            (ps_id, items[code], amount),
        )
    db.commit()
    return ps_id


def test_hire_in_and_out_of_period(db, seed):
    a = seed["a"]["company"]
    _mk_emp(db, a, name="재직자", hire_date="2026-03-10")
    _mk_emp(db, a, name="밖사람", hire_date="2026-04-01")
    db.commit()

    rows = _build_acq_rows(db, a, "2026-03-01", "2026-03-31")
    names = [r["name"] for r in rows]
    assert "재직자" in names
    assert "밖사람" not in names


def test_resign_in_and_out_of_period(db, seed):
    a = seed["a"]["company"]
    _mk_emp(db, a, name="퇴사자", hire_date="2020-01-01", resign_date="2026-03-20", status="retired")
    _mk_emp(db, a, name="계속근무", hire_date="2020-01-01", resign_date="2026-04-05", status="retired")
    db.commit()

    rows = _build_loss_rows(db, a, "2026-03-01", "2026-03-31")
    names = [r["name"] for r in rows]
    assert "퇴사자" in names
    assert "계속근무" not in names


def test_loss_date_next_day_across_month_end(db, seed):
    a = seed["a"]["company"]
    _mk_emp(db, a, name="월말퇴사", hire_date="2020-01-01", resign_date="2026-01-31", status="retired")
    db.commit()

    rows = _build_loss_rows(db, a, "2026-01-01", "2026-01-31")
    assert rows[0]["loss_date"] == "2026-02-01"
    # 신고기한은 상실일(2월1일) 다음달 15일
    assert rows[0]["deadline"] == "2026-03-15"


def test_ei_loss_code_mapping():
    assert _match_ei_loss_code("개인사정으로 자진퇴사") == ("11", False)
    assert _match_ei_loss_code("경영상 어려움으로 권고사직") == ("23", False)
    assert _match_ei_loss_code("징계해고") == ("26", False)
    assert _match_ei_loss_code("정년퇴직") == ("31", False)
    assert _match_ei_loss_code("계약기간 만료") == ("32", False)
    code, need_confirm = _match_ei_loss_code("기타 사유")
    assert code == "11"
    assert need_confirm is True


def test_monthly_income_from_payslip_vs_base_salary(db, seed):
    a = seed["a"]["company"]
    ensure_default_items(db, a)
    items = {it["code"]: it["id"] for it in get_items(db, a)}

    eid_with_slip = _mk_emp(db, a, name="명세서있음", hire_date="2026-03-05", base_salary=2_000_000)
    _mk_payslip(db, eid_with_slip, 2026, 3, items, {"BASE": 3_000_000})

    eid_no_slip = _mk_emp(db, a, name="명세서없음", hire_date="2026-03-05", base_salary=2_500_000)
    db.commit()

    rows = _build_acq_rows(db, a, "2026-03-01", "2026-03-31")
    by_name = {r["name"]: r for r in rows}
    assert by_name["명세서있음"]["monthly_income"] == 3_000_000
    assert by_name["명세서없음"]["monthly_income"] == 2_500_000


def test_monthly_income_excludes_tax_free_portion(db, seed):
    a = seed["a"]["company"]
    ensure_default_items(db, a)
    items = {it["code"]: it["id"] for it in get_items(db, a)}

    eid = _mk_emp(db, a, name="식대있음", hire_date="2026-03-05", base_salary=1_000_000)
    # MEAL 비과세한도 20만원짜리 30만원 지급 -> 과세분 10만원만 보수월액에 포함
    _mk_payslip(db, eid, 2026, 3, items, {"BASE": 3_000_000, "MEAL": 300_000})
    db.commit()

    rows = _build_acq_rows(db, a, "2026-03-01", "2026-03-31")
    assert rows[0]["monthly_income"] == 3_100_000


def test_client_sees_only_own_company(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    _mk_emp(db, a, name="가사람", hire_date="2026-03-10")
    _mk_emp(db, b, name="나사람", hire_date="2026-03-10")
    db.commit()

    c = login("a_mgr")
    html = c.get("/insurance-reports?from=2026-03-01&to=2026-03-31&kind=acq").text
    assert "가사람" in html
    assert "나사람" not in html


def test_staff_internal_book_shows_empty_not_crash(db, seed, login):
    c = login("t_staff")
    resp = c.get("/insurance-reports")
    assert resp.status_code == 200
    assert "4대보험" in resp.text


def test_csv_headers_and_content(db, seed, login):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (a,))
    db.commit()
    _mk_emp(db, a, name="씨에스브이", hire_date="2026-03-10", base_salary=2_100_000, monthly_work_hours=209)
    db.commit()

    c = login("t_staff")
    c.post("/hr-book", data={"book": a, "next": "/insurance-reports"})
    resp = c.get("/insurance-reports/export?from=2026-03-01&to=2026-03-31&kind=acq&reason=테스트조회")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]

    text = resp.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    assert header == [
        "성명", "주민등록번호", "자격취득일", "월소득액(보수월액)",
        "주소정근로시간", "고용보험가입여부", "장애인여부", "신고기한", "기한초과",
    ]
    body = list(reader)
    assert body[0][0] == "씨에스브이"
    assert body[0][3] == "2100000"
    assert body[0][4] == "40"


def test_csv_loss_headers(db, seed, login):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (a,))
    db.commit()
    _mk_emp(db, a, name="상실씨", hire_date="2020-01-01", resign_date="2026-03-15",
            resign_reason="개인사정으로 자진퇴사", status="retired")
    db.commit()

    c = login("t_staff")
    c.post("/hr-book", data={"book": a, "next": "/insurance-reports"})
    resp = c.get("/insurance-reports/export?from=2026-03-01&to=2026-03-31&kind=loss&reason=테스트조회")
    assert resp.status_code == 200

    text = resp.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    assert header == [
        "성명", "주민등록번호", "퇴사일", "자격상실일",
        "고용보험상실사유코드", "고용보험상실사유", "확인필요",
        "건강보험상실부호", "국민연금상실부호",
        "당해연도보수총액", "전년도보수총액", "신고기한", "기한초과",
    ]
    row = next(reader)
    assert row[0] == "상실씨"
    assert row[3] == "2026-03-16"
    assert row[4] == "11"

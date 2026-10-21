import io

from openpyxl import load_workbook

from core.books import INTERNAL
from routers.hr_book import calc_disability_report, calc_subsidy


def _emp(db, book, name, **kw):
    cols = {
        "company_id": book, "status": "active", "hire_date": "2020-01-01",
        "monthly_work_hours": 174, "disability_type": "", "disability_grade": "",
        "resident_no": "", "base_salary": 2000000,
    }
    cols.update(kw)
    cols["name"] = name
    keys = ",".join(cols.keys())
    qs = ",".join("?" * len(cols))
    return db.execute(f"INSERT INTO employees ({keys}) VALUES ({qs})", list(cols.values())).lastrowid


# 연간 기초일수 충족용. 판정보류 케이스는 미호출
def _seed_attendance(db, emp_id, days):
    for d in days:
        db.execute(
            "INSERT INTO attendance (employee_id, work_date, status, clock_in, clock_out, work_minutes) "
            "VALUES (?, ?, 'normal', '09:00:00', '18:00:00', 480)",
            (emp_id, f"2026-03-{d:02d}"),
        )


def _seed_year(db, emp_id, days_per_month=20):
    for m in range(1, 13):
        for d in range(1, days_per_month + 1):
            db.execute(
                "INSERT INTO attendance (employee_id, work_date, status, clock_in, clock_out, work_minutes) "
                "VALUES (?, ?, 'normal', '09:00:00', '18:00:00', 480)",
                (emp_id, f"2026-{m:02d}-{d:02d}"),
            )


def _hong_gildong_id(db):
    return db.execute("SELECT id FROM employees WHERE name='홍길동'").fetchone()["id"]


def test_monthly_breakdown_and_averages(db):
    for i in range(98):
        eid = _emp(db, None, f"직원{i}")
        _seed_year(db, eid)
    eid = _emp(db, None, "중증1", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-1234567", base_salary=2000000)
    _seed_year(db, eid)
    eid = _emp(db, None, "경증1", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-2234567", base_salary=2000000)
    _seed_year(db, eid)
    _seed_year(db, _hong_gildong_id(db))
    db.commit()

    result = calc_disability_report(db, INTERNAL, 2026)
    assert len(result["months"]) == 12
    first = result["months"][0]
    # 시드 데이터의 홍길동(3급 중증)도 중증 예외로 상시근로자 및 장애인근로자에 포함
    assert first["regular_cnt"] == 101
    assert first["disabled_cnt"] == 4
    assert result["avg_regular"] == 101
    assert result["avg_disabled"] == 4
    assert result["sector"] == "민간"
    assert result["quota_pct"] == 3.1


def test_gap_reflects_shortfall(db):
    for i in range(99):
        eid = _emp(db, None, f"직원{i}")
        _seed_year(db, eid)
    _seed_year(db, _hong_gildong_id(db))
    db.commit()

    result = calc_disability_report(db, INTERNAL, 2026)
    m = result["months"][0]
    assert m["quota_cnt"] == 3
    assert m["disabled_cnt"] == 1  # 시드 홍길동(중증 예외)
    assert m["gap"] == -2


def test_public_sector_uses_higher_quota(db, seed):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET sector='공공' WHERE id=?", (a,))
    for i in range(100):
        _emp(db, a, f"직원{i}")
    db.commit()

    result = calc_disability_report(db, a, 2026)
    assert result["sector"] == "공공"
    assert result["quota_pct"] == 3.8


def test_report_page_renders(db, login):
    c = login("t_staff")
    r = c.get("/hr/disability-report?year=2026")
    assert r.status_code == 200
    assert "장애인 고용현황" in r.text


def test_report_excel_download(login):
    c = login("t_staff")
    r = c.get("/hr/disability-report/excel?year=2026&reason=테스트조회")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/")


# 상시근로자 판정 - 임금지급 기초일수(16일) 및 중증장애인 소정시간 예외

def test_base_days_under_16_excludes_worker(db):
    emp_id = _emp(db, None, "출근일수부족", monthly_work_hours=174)
    _seed_attendance(db, emp_id, range(2, 12))  # 10일만 근무
    _seed_attendance(db, _hong_gildong_id(db), range(1, 21))  # 시드 홍길동은 기초일수 충족
    db.commit()

    r = calc_subsidy(db, INTERNAL, 2026, 3)
    assert r["regular_cnt"] == 1  # 시드 홍길동만 상시근로자
    assert "출근일수부족" not in r["pending_workers"]  # 기록은 있으나 16일 미달이므로 적용제외


def test_base_days_16_or_more_includes_worker(db):
    emp_id = _emp(db, None, "출근일수충분", monthly_work_hours=174)
    _seed_attendance(db, emp_id, range(2, 19))  # 17일 근무
    _seed_attendance(db, _hong_gildong_id(db), range(1, 21))
    db.commit()

    r = calc_subsidy(db, INTERNAL, 2026, 3)
    assert r["regular_cnt"] == 2  # 시드 홍길동 + 신규 직원


def test_severe_worker_exempt_from_hours_requirement(db):
    emp_id = _emp(db, None, "중증저시간", disability_type="지체장애", disability_grade="심한장애",
                  resident_no="900101-1234567", monthly_work_hours=30)
    _seed_attendance(db, emp_id, range(2, 19))
    _seed_attendance(db, _hong_gildong_id(db), range(1, 21))
    db.commit()

    r = calc_subsidy(db, INTERNAL, 2026, 3)
    assert r["regular_cnt"] == 2  # 시드 홍길동 + 중증저시간(소정시간 예외)
    assert r["severe_lt60_cnt"] == 2  # 시드 홍길동도 60시간 미만 중증


def test_mild_worker_low_hours_excluded_even_with_base_days(db):
    emp_id = _emp(db, None, "경증저시간", disability_type="지체장애", disability_grade="심하지않은장애",
                  resident_no="900101-2234567", monthly_work_hours=30)
    _seed_attendance(db, emp_id, range(2, 19))
    _seed_attendance(db, _hong_gildong_id(db), range(1, 21))
    db.commit()

    r = calc_subsidy(db, INTERNAL, 2026, 3)
    assert r["regular_cnt"] == 1  # 경증은 소정시간 60시간 미만이면 기초일수 충족해도 제외


def test_no_attendance_at_all_is_pending_excluded_from_regular(db):
    emp_id = _emp(db, None, "근태전무", monthly_work_hours=174)  # 근태 기록 자체가 없음
    db.commit()

    r = calc_subsidy(db, INTERNAL, 2026, 3)
    assert "근태전무" in r["pending_workers"]
    assert "홍길동" in r["pending_workers"]  # 시드 홍길동도 근태 미기록이면 함께 판정보류
    assert emp_id  # 생성 확인


# 첨부 장애인 근로자 명부

def test_roster_sheet_lists_disabled_employee(db, login):
    emp_id = _emp(db, None, "명부테스트", disability_type="지체장애", disability_grade="심한장애",
                  resident_no="900101-1234567", monthly_work_hours=100)
    db.execute(
        "UPDATE employees SET disability_class=?, veteran_grade=?, disability_date=? WHERE id=?",
        ("1", "", "20200101", emp_id),
    )
    db.commit()

    c = login("t_staff")
    r = c.get("/hr/disability-report/excel?year=2026&reason=테스트조회")
    wb = load_workbook(io.BytesIO(r.content))
    assert "장애인근로자명부" in wb.sheetnames
    ws = wb["장애인근로자명부"]
    names = [row[3].value for row in ws.iter_rows(min_row=2)]
    assert "명부테스트" in names


def test_roster_scoped_to_company(db, seed, login):
    a = seed["a"]["company"]
    b = seed["b"]["company"]
    _emp(db, a, "A사장애인", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-1234567")
    _emp(db, b, "B사장애인", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-2234567")
    db.commit()

    c = login("a_mgr")
    r = c.get("/hr/disability-report/excel?year=2026&reason=테스트조회")
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["장애인근로자명부"]
    names = [row[3].value for row in ws.iter_rows(min_row=2)]
    assert "A사장애인" in names
    assert "B사장애인" not in names

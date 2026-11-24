from core.books import INTERNAL
from routers.hr_book import calc_subsidy
from tests.conftest import make_emp


def _emp(db, book, name, **kw):
    kw.setdefault("monthly_work_hours", 174)
    kw.setdefault("disability_type", "")
    kw.setdefault("disability_grade", "")
    kw.setdefault("resident_no", "")
    kw.setdefault("base_salary", 2000000)
    return make_emp(db, book, name, **kw)


# 기초일수 16일 요건 충족용 근태 기록. 판정보류(근태 미기록) 테스트는 호출 제외
def _seed_attendance(db, emp_id, year=2026, month=3, days=20):
    for d in range(1, days + 1):
        db.execute(
            "INSERT INTO attendance (employee_id, work_date, status, clock_in, clock_out, work_minutes) "
            "VALUES (?, ?, 'normal', '09:00:00', '18:00:00', 480)",
            (emp_id, f"{year}-{month:02d}-{d:02d}"),
        )


def _hong_gildong_id(db):
    return db.execute("SELECT id FROM employees WHERE name='홍길동'").fetchone()["id"]


def _company_form_data(name="장려금테스트"):
    return {
        "name": name, "business_no": "", "representative": "", "biz_type": "", "biz_item": "",
        "address": "", "contact_name": "", "contact_phone": "", "contact_email": "",
        "contract_start": "", "contract_end": "", "contract_amount": "", "contract_content": "",
        "status": "active", "start_time": "09:00", "end_time": "18:00", "break_min": "60",
        "rest_day": "6", "off_day": "5", "employee_count": "0",
    }



def test_quota_floor_private(db):
    for i in range(99):
        eid = _emp(db, None, f"직원{i}")
        _seed_attendance(db, eid)
    _seed_attendance(db, _hong_gildong_id(db))  # 시드 홍길동(3급 중증)도 기초일수 충족시켜 포함
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert result["regular_cnt"] == 100
    assert result["quota_cnt"] == 3


def test_public_sector_quota(db, seed):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET sector='공공' WHERE id=?", (a,))
    for i in range(99):
        eid = _emp(db, a, f"직원{i}")
        _seed_attendance(db, eid)
    db.commit()

    result = calc_subsidy(db, a, 2026, 3)
    assert result["sector"] == "공공"
    assert result["quota_cnt"] == 3  # 99 * 38 // 1000



def test_fill_order_cheap_price_first(db):
    for i in range(29):
        eid = _emp(db, None, f"일반{i}")
        _seed_attendance(db, eid)
    eid = _emp(db, None, "경증남", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-1234567", base_salary=2000000)
    _seed_attendance(db, eid)
    eid = _emp(db, None, "경증여", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-2234567", base_salary=2000000)
    _seed_attendance(db, eid)
    _seed_attendance(db, _hong_gildong_id(db))
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert result["regular_cnt"] == 32  # +시드 홍길동(중증 예외)
    assert result["reward_base_cnt"] == 1
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["경증남"]["category"] == "의무고용 충당"
    assert rows["경증여"]["category"] == "장려금 대상"


def test_fill_order_lower_wage_tiebreak(db):
    for i in range(30):
        eid = _emp(db, None, f"일반{i}")
        _seed_attendance(db, eid)
    eid = _emp(db, None, "저임금", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-1234567", base_salary=1500000, monthly_work_hours=140)
    _seed_attendance(db, eid)
    eid = _emp(db, None, "고임금", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-1345678", base_salary=3000000, monthly_work_hours=140)
    _seed_attendance(db, eid)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert result["reward_base_cnt"] == 1
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["저임금"]["category"] == "의무고용 충당"
    assert rows["고임금"]["category"] == "장려금 대상"



def test_severe_not_doubled(db):
    for i in range(60):
        eid = _emp(db, None, f"일반{i}")
        _seed_attendance(db, eid)
    eid = _emp(db, None, "경증남", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-1234567", base_salary=2000000)
    _seed_attendance(db, eid)
    eid = _emp(db, None, "중증1", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-1234567", base_salary=1000000, monthly_work_hours=80)
    _seed_attendance(db, eid)
    eid = _emp(db, None, "중증2", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-1234567", base_salary=2000000)
    _seed_attendance(db, eid)
    _seed_attendance(db, _hong_gildong_id(db))
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert result["regular_cnt"] == 64  # +시드 홍길동(중증 예외)
    assert result["reward_base_cnt"] == 2
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["경증남"]["category"] == "의무고용 충당"
    assert rows["중증1"]["category"] == "의무고용 충당"
    assert rows["중증2"]["category"] == "장려금 대상"
    assert result["excess_cnt"] == 1



def test_60_percent_cap_applies(db):
    eid = _emp(db, None, "충당용", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-1234567", base_salary=2000000)
    _seed_attendance(db, eid)
    eid = _emp(db, None, "저임금중증", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-1234567", base_salary=1000000, monthly_work_hours=80)
    _seed_attendance(db, eid)
    eid = _emp(db, None, "고임금중증", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-3234567", base_salary=5000000)
    _seed_attendance(db, eid)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["저임금중증"]["unit_price"] == 700000
    assert rows["저임금중증"]["capped_amount"] == 600000  # 1,000,000 * 60% < 단가
    assert rows["고임금중증"]["capped_amount"] == 700000  # 단가가 60%보다 낮아 단가로 적용



def test_base_ceil_kead_example(db):
    # 공단 예시 기준. 상시 10명이면 기준인원 1명, 장애인 2명 중 1명 지급
    for i in range(8):
        eid = _emp(db, None, f"일반{i}")
        _seed_attendance(db, eid)
    for name in ("장애1", "장애2"):
        eid = _emp(db, None, name, disability_type="지체장애", disability_grade="심하지않은장애",
             resident_no="900101-1234567", base_salary=2000000)
        _seed_attendance(db, eid)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert result["regular_cnt"] == 10
    assert result["reward_base_cnt"] == 1
    assert result["excess_cnt"] == 1
    assert result["pay_cnt"] == 1
    assert result["subsidy_total"] == 350000


def test_no_ins_min_wage_excluded(db):
    eid = _emp(db, None, "고보미가입", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-1234567", base_salary=2000000, employment_insurance=0)
    _seed_attendance(db, eid)
    eid = _emp(db, None, "최저미만", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-2234567", base_salary=1500000)  # 174시간 기준 1,795,680원 미만
    _seed_attendance(db, eid)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["고보미가입"]["category"] == "제외(고용보험 미가입)"
    assert rows["최저미만"]["category"] == "제외(최저임금 미만)"
    assert result["exempt_cnt"] == 2
    assert result["subsidy_total"] == 0


def test_resident_no_missing_excluded(db):
    eid = _emp(db, None, "주민번호없음", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="", base_salary=2000000)
    _seed_attendance(db, eid)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    row = result["rows"][0]
    assert row["gender"] is None
    assert row["category"] == "제외(주민번호 없음)"
    assert result["subsidy_total"] == 0
    assert result["excess_cnt"] == 0



def test_resign_boundary(db):
    _emp(db, None, "월초이전퇴사", resign_date="2026-02-28")
    eid = _emp(db, None, "월중퇴사", resign_date="2026-03-15")
    _seed_attendance(db, eid)
    _seed_attendance(db, _hong_gildong_id(db))
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert result["regular_cnt"] == 2  # 월중퇴사 1명 + 시드 홍길동(중증 예외)



def test_grade_3_is_severe(db):
    eid = _emp(db, None, "3급", disability_type="지체장애", disability_grade="3급",
         resident_no="900101-1234567", base_salary=2000000)
    _seed_attendance(db, eid)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    rows = {r["name"]: r for r in result["rows"]}
    row = rows["3급"]
    assert row["severe"] is True
    assert row["unit_price"] == 700000



def test_no_attendance_worker_pending(db):
    _emp(db, None, "무기록", monthly_work_hours=174)  # 근태 기록 전혀 없음
    db.commit()

    # 시드 홍길동도 근태 미기록이므로 함께 판정보류
    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert "무기록" in result["pending_workers"]
    assert "홍길동" in result["pending_workers"]
    assert result["regular_cnt"] == 0


def test_subsidy_page_200(db, seed, login):
    a = seed["a"]["company"]
    _emp(db, a, "직원1", disability_type="지체장애", disability_grade="심한장애", resident_no="900101-1234567")
    db.commit()

    c = login("a_mgr")
    r = c.get("/hr/subsidy?year=2026&month=3")
    assert r.status_code == 200
    assert "고용장려금" in r.text


def test_subsidy_excel_200(db, seed, login):
    a = seed["a"]["company"]
    _emp(db, a, "직원1")
    db.commit()

    c = login("a_mgr")
    r = c.get("/hr/subsidy/excel?year=2026&month=3&reason=테스트조회")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")



def test_platform_company_sector_saved(db, seed, login):
    a = seed["a"]["company"]
    c = login("t_staff")

    data = _company_form_data()
    data["sector"] = "공공"
    c.post(f"/platform/companies/{a}", data=data, follow_redirects=False)
    assert db.execute("SELECT sector FROM client_companies WHERE id=?", (a,)).fetchone()["sector"] == "공공"

    data2 = _company_form_data()
    data2["sector"] = "잘못된값"
    c.post(f"/platform/companies/{a}", data=data2, follow_redirects=False)
    assert db.execute("SELECT sector FROM client_companies WHERE id=?", (a,)).fetchone()["sector"] == "민간"


def test_offset_paid_as_difference(db):
    eid = _emp(db, None, "충당용", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-1234567", base_salary=2000000)
    _seed_attendance(db, eid)
    eid = _emp(db, None, "중복수급", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-2234567", base_salary=2000000)
    _seed_attendance(db, eid)
    db.execute("INSERT INTO subsidy_offsets (employee_id, pay_year, pay_month, amount) VALUES (?,2026,3,300000)", (eid,))
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    row = {r["name"]: r for r in result["rows"]}["중복수급"]
    assert row["limit_amount"] == 900000
    assert row["capped_amount"] == 600000


def test_rate_effective_date(db):
    for key, amt in (("경증남", 400000), ("경증여", 550000), ("중증남", 750000), ("중증여", 950000)):
        db.execute("INSERT INTO subsidy_rates (rate_key, amount, effective_date) VALUES (?,?,'2026-04-01')", (key, amt))
    db.commit()

    assert calc_subsidy(db, INTERNAL, 2026, 3)["rates"]["경증남"] == 350000
    result = calc_subsidy(db, INTERNAL, 2026, 4)
    assert result["rates"]["경증남"] == 400000
    assert result["rate_from"] == "2026-04-01"


def test_offsets_save_with_history(db, seed, login):
    a = seed["a"]["company"]
    ea = _emp(db, a, "가직원", disability_type="지체장애", disability_grade="심한장애", resident_no="900101-1234567")
    db.commit()

    c = login("a_mgr")
    c.post("/hr/subsidy/offsets", data={"year": 2026, "month": 3, f"offset_{ea}": "200,000", "reason": "고용창출장려금"},
           follow_redirects=False)
    assert db.execute("SELECT amount FROM subsidy_offsets WHERE employee_id=?", (ea,)).fetchone()["amount"] == 200000

    # 금액 동일 시 이력 미기록
    c.post("/hr/subsidy/offsets", data={"year": 2026, "month": 3, f"offset_{ea}": "200000"}, follow_redirects=False)
    logs = db.execute("SELECT summary, company_id FROM audit_logs WHERE action='subsidy_offset'").fetchall()
    assert len(logs) == 1
    assert logs[0]["summary"] == "2026년 3월 가직원 0원 -> 200,000원 (고용창출장려금)"
    assert logs[0]["company_id"] == a


def test_offsets_other_book_404(db, seed, login):
    b = seed["b"]["company"]
    eb = _emp(db, b, "나직원", disability_type="지체장애", disability_grade="심한장애", resident_no="900101-1234567")
    db.commit()

    r = login("a_mgr").post("/hr/subsidy/offsets", data={"year": 2026, "month": 3, f"offset_{eb}": "100000"},
                            follow_redirects=False)
    assert r.status_code == 404
    assert db.execute("SELECT 1 FROM subsidy_offsets WHERE employee_id=?", (eb,)).fetchone() is None


def test_rates_staff_only_reason_required(db, seed, login):
    data = {"year": 2026, "month": 3, "effective_date": "2027-01-01",
            "경증남": "400,000", "경증여": "550000", "중증남": "750000", "중증여": "950000"}

    login("a_mgr").post("/hr/subsidy/rates", data={**data, "reason": "고시"}, follow_redirects=False)
    assert db.execute("SELECT 1 FROM subsidy_rates WHERE effective_date='2027-01-01'").fetchone() is None

    c = login("t_staff")
    c.post("/hr/subsidy/rates", data=data, follow_redirects=False)
    assert db.execute("SELECT 1 FROM subsidy_rates WHERE effective_date='2027-01-01'").fetchone() is None

    c.post("/hr/subsidy/rates", data={**data, "reason": "2027년 고시"}, follow_redirects=False)
    rows = db.execute("SELECT rate_key, amount, reason, created_by FROM subsidy_rates "
                      "WHERE effective_date='2027-01-01'").fetchall()
    assert {r["rate_key"]: r["amount"] for r in rows}["경증남"] == 400000
    assert rows[0]["reason"] == "2027년 고시"
    assert rows[0]["created_by"] == seed["staff"]


def test_subsidy_page_rows_rate_form(db, seed, login):
    eid = _emp(db, None, "장애1", disability_type="지체장애", disability_grade="심한장애", resident_no="900101-1234567")
    _seed_attendance(db, eid)
    db.commit()

    c = login("t_staff")
    r = c.get("/hr/subsidy?year=2026&month=3")
    assert r.status_code == 200
    assert f'name="offset_{eid}"' in r.text
    assert "단가 등록" in r.text
    assert "공단 고시" in r.text

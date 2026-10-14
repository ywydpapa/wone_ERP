from core.books import INTERNAL
from routers.hr_book import calc_subsidy


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
        _emp(db, None, f"직원{i}")
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert result["regular_cnt"] == 99
    assert result["quota_cnt"] == 3


def test_public_sector_quota(db, seed):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET sector='공공' WHERE id=?", (a,))
    for i in range(99):
        _emp(db, a, f"직원{i}")
    db.commit()

    result = calc_subsidy(db, a, 2026, 3)
    assert result["sector"] == "공공"
    assert result["quota_cnt"] == 3  # 99 * 38 // 1000



def test_fill_order_cheap_price_class_first(db):
    for i in range(33):
        _emp(db, None, f"일반{i}")
    _emp(db, None, "경증남", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-1234567", base_salary=2000000)
    _emp(db, None, "경증여", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-2234567", base_salary=2000000)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert result["regular_cnt"] == 35
    assert result["quota_cnt"] == 1
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["경증남"]["category"] == "의무고용 충당"
    assert rows["경증여"]["category"] == "장려금 대상"


def test_fill_order_lower_wage_first_in_same_price(db):
    for i in range(33):
        _emp(db, None, f"일반{i}")
    _emp(db, None, "저임금", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-1234567", base_salary=1500000)
    _emp(db, None, "고임금", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-1345678", base_salary=3000000)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert result["quota_cnt"] == 1
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["저임금"]["category"] == "의무고용 충당"
    assert rows["고임금"]["category"] == "장려금 대상"



def test_severe_doubles_and_remainder_discarded(db):
    for i in range(67):
        _emp(db, None, f"일반{i}")
    _emp(db, None, "경증남", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="900101-1234567", base_salary=2000000)
    _emp(db, None, "중증1", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-1234567", base_salary=1000000)
    _emp(db, None, "중증2", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-1234567", base_salary=2000000)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert result["regular_cnt"] == 70
    assert result["quota_cnt"] == 2
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["경증남"]["category"] == "의무고용 충당"
    assert rows["중증1"]["category"] == "의무고용 충당"  # 잔여 1명분인데도 통째로 충당 처리
    assert rows["중증2"]["category"] == "장려금 대상"
    assert result["excess_cnt"] == 2



def test_60_percent_cap_applies(db):
    _emp(db, None, "저임금중증", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-1234567", base_salary=1000000)
    _emp(db, None, "고임금중증", disability_type="지체장애", disability_grade="심한장애",
         resident_no="900101-3234567", base_salary=5000000)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    rows = {r["name"]: r for r in result["rows"]}
    assert rows["저임금중증"]["unit_price"] == 700000
    assert rows["저임금중증"]["capped_amount"] == 600000  # 1,000,000 * 60% < 단가
    assert rows["고임금중증"]["capped_amount"] == 700000  # 단가가 60%보다 낮아 단가로 적용



def test_resident_no_missing_excluded(db):
    _emp(db, None, "주민번호없음", disability_type="지체장애", disability_grade="심하지않은장애",
         resident_no="", base_salary=2000000)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    row = result["rows"][0]
    assert row["gender"] is None
    assert row["category"] == "제외(주민번호 없음)"
    assert result["subsidy_total"] == 0
    assert result["excess_cnt"] == 0



def test_resign_boundary(db):
    _emp(db, None, "월초이전퇴사", resign_date="2026-02-28")
    _emp(db, None, "월중퇴사", resign_date="2026-03-15")
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    assert result["regular_cnt"] == 1



def test_grade_3_is_severe(db):
    _emp(db, None, "3급", disability_type="지체장애", disability_grade="3급",
         resident_no="900101-1234567", base_salary=2000000)
    db.commit()

    result = calc_subsidy(db, INTERNAL, 2026, 3)
    row = result["rows"][0]
    assert row["severe"] is True
    assert row["unit_price"] == 700000



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
    r = c.get("/hr/subsidy/excel?year=2026&month=3")
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

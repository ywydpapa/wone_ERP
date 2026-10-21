from routers.hr_training import training_stats


def _company(db, name="교육테스트"):
    return db.execute("INSERT INTO client_companies (name) VALUES (?)", (name,)).lastrowid


def _emp(db, book, name, **kw):
    cols = {"company_id": book, "status": "active", "hire_date": "2020-01-01"}
    cols.update(kw)
    cols["name"] = name
    keys = ",".join(cols.keys())
    qs = ",".join("?" * len(cols))
    return db.execute(f"INSERT INTO employees ({keys}) VALUES ({qs})", list(cols.values())).lastrowid


def test_stats_no_session_means_all_missed(db):
    book = _company(db)
    e1 = _emp(db, book, "미이수1")
    e2 = _emp(db, book, "미이수2")
    db.commit()

    stats = training_stats(db, book, 2026)
    assert stats["total"] == 2
    assert stats["completed_cnt"] == 0
    assert stats["rate"] == 0.0
    assert {m["id"] for m in stats["missed"]} == {e1, e2}


def test_stats_completion_rate_after_training(db):
    book = _company(db)
    e1 = _emp(db, book, "이수자")
    _emp(db, book, "미이수자")
    training_id = db.execute(
        "INSERT INTO disability_awareness_trainings (company_id, held_date, method) VALUES (?,?,?)",
        (book, "2026-05-10", "집체교육"),
    ).lastrowid
    db.execute(
        "INSERT INTO disability_awareness_attendees (training_id, employee_id, completed) VALUES (?,?,1)",
        (training_id, e1),
    )
    db.commit()

    stats = training_stats(db, book, 2026)
    assert stats["total"] == 2
    assert stats["completed_cnt"] == 1
    assert stats["rate"] == 50.0
    assert [m["name"] for m in stats["missed"]] == ["미이수자"]


def test_training_out_of_year_not_counted(db):
    book = _company(db)
    e1 = _emp(db, book, "작년이수자")
    training_id = db.execute(
        "INSERT INTO disability_awareness_trainings (company_id, held_date, method) VALUES (?,?,?)",
        (book, "2025-05-10", "집체교육"),
    ).lastrowid
    db.execute(
        "INSERT INTO disability_awareness_attendees (training_id, employee_id, completed) VALUES (?,?,1)",
        (training_id, e1),
    )
    db.commit()

    stats = training_stats(db, book, 2026)
    assert stats["completed_cnt"] == 0


def test_retired_before_year_excluded_from_target(db):
    book = _company(db)
    _emp(db, book, "퇴사자", status="retired", resign_date="2025-06-30")
    db.commit()

    stats = training_stats(db, book, 2026)
    assert stats["total"] == 0

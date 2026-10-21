from core.tz import today_kst

KINDS = {"dept": "부서이동", "position": "승진", "base_salary": "급여변경"}


def log_changes(conn, company_id, emp_id, changed, uid):
    for f, (old, new) in changed.items():
        if f not in KINDS:
            continue
        conn.execute(
            """INSERT INTO hr_appointments
               (company_id, employee_id, kind, from_val, to_val, effective_date, created_by)
               VALUES (?,?,?,?,?,?,?)""",
            (company_id, emp_id, KINDS[f], "" if old is None else str(old), "" if new is None else str(new), today_kst().isoformat(), uid),
        )

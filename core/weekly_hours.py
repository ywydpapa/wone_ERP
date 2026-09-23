import datetime


def _week_bounds(date_str):
    d = datetime.date.fromisoformat(date_str)
    start = d - datetime.timedelta(days=d.weekday())
    end = start + datetime.timedelta(days=6)
    return start.isoformat(), end.isoformat()


def get_weekly_hours(conn, emp_id, date_str):
    ws, we = _week_bounds(date_str)
    row = conn.execute(
        "SELECT COALESCE(SUM(work_minutes + COALESCE(overtime_minutes,0)), 0) AS total "
        "FROM attendance WHERE employee_id=? AND work_date>=? AND work_date<=?",
        (emp_id, ws, we),
    ).fetchone()
    return round((row["total"] or 0) / 60, 2)


def check_52hr(conn, emp_id, year_month):
    year, month = int(year_month[:4]), int(year_month[5:7])
    rows = conn.execute(
        "SELECT work_date, COALESCE(work_minutes,0) + COALESCE(overtime_minutes,0) AS mins "
        "FROM attendance WHERE employee_id=? AND work_date LIKE ?",
        (emp_id, f"{year_month}%"),
    ).fetchall()

    weeks = {}
    for r in rows:
        ws, we = _week_bounds(r["work_date"])
        key = ws
        if key not in weeks:
            weeks[key] = {"week_start": ws, "week_end": we, "total_minutes": 0}
        weeks[key]["total_minutes"] += r["mins"]

    violations = []
    for w in sorted(weeks.values(), key=lambda x: x["week_start"]):
        if w["total_minutes"] > 52 * 60:
            w["over"] = w["total_minutes"] - 52 * 60
            violations.append(w)
    return violations

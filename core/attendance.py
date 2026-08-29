import calendar
from datetime import datetime, date

from core.tz import now_kst, today_kst


STATUS_LABELS = {
    "normal": "정상",
    "late": "지각",
    "early_leave": "조퇴",
    "absent": "결근",
    "holiday": "휴일",
}


def get_company_workers(conn, company_id):
    rows = conn.execute(
        "SELECT id, name, employee_no, dept, position FROM employees WHERE company_id = ? AND status = 'active'",
        (company_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_attendance_records(conn, employee_ids, year_month):
    if not employee_ids:
        return []
    placeholders = ",".join("?" * len(employee_ids))
    rows = conn.execute(
        f"""SELECT a.*, e.name AS employee_name, e.employee_no, e.dept
            FROM attendance a
            JOIN employees e ON e.id = a.employee_id
            WHERE a.employee_id IN ({placeholders})
              AND a.work_date LIKE ?
            ORDER BY a.work_date DESC, e.name""",
        [*employee_ids, f"{year_month}%"],
    ).fetchall()
    records = [dict(r) for r in rows]
    for r in records:
        r["status_label"] = STATUS_LABELS.get(r.get("status", ""), r.get("status", ""))
        mins = r.get("work_minutes") or 0
        r["work_hours"] = f"{mins // 60}h {mins % 60}m" if mins else "-"
    return records


def get_attendance_summary(records, worker_count):
    total = len(records)
    late = sum(1 for r in records if r.get("status") == "late")
    absent = sum(1 for r in records if r.get("status") == "absent")
    normal = sum(1 for r in records if r.get("status") == "normal")
    on_time_rate = round(normal / total * 100) if total > 0 else 0
    return {
        "worker_count": worker_count,
        "total_records": total,
        "normal": normal,
        "late": late,
        "absent": absent,
        "on_time_rate": on_time_rate,
    }


def get_company_id_for_client(conn, user_id):
    row = conn.execute(
        "SELECT company_id FROM client_users WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row["company_id"] if row else None


def get_worker_detail(conn, employee_id):
    row = conn.execute(
        """SELECT e.*, cc.name AS company_name
           FROM employees e
           LEFT JOIN client_companies cc ON cc.id = e.company_id
           WHERE e.id = ?""",
        (employee_id,),
    ).fetchone()
    return dict(row) if row else None


def get_worker_month_records(conn, employee_id, year_month):
    rows = conn.execute(
        """SELECT * FROM attendance
           WHERE employee_id = ? AND work_date LIKE ?
           ORDER BY work_date""",
        (employee_id, f"{year_month}%"),
    ).fetchall()
    records = [dict(r) for r in rows]
    for r in records:
        r["status_label"] = STATUS_LABELS.get(r.get("status", ""), r.get("status", ""))
        mins = r.get("work_minutes") or 0
        r["work_hours"] = f"{mins // 60}h {mins % 60}m" if mins else "-"
    return records


def build_calendar_data(records, year_month):
    y, m = map(int, year_month.split("-"))
    by_date = {r["work_date"]: r for r in records}
    _, days_in_month = calendar.monthrange(y, m)
    first_weekday = date(y, m, 1).weekday()
    today = today_kst().isoformat()

    days = []
    for d in range(1, days_in_month + 1):
        iso = f"{y}-{m:02d}-{d:02d}"
        rec = by_date.get(iso)
        days.append({
            "day": d,
            "date": iso,
            "record": rec,
            "is_today": iso == today,
            "is_weekend": date(y, m, d).weekday() >= 5,
        })
    return {"days": days, "first_weekday": first_weekday, "year": y, "month": m}


def worker_month_summary(records):
    total = len([r for r in records if r.get("status") != "holiday"])
    late = sum(1 for r in records if r.get("status") == "late")
    absent = sum(1 for r in records if r.get("status") == "absent")
    early = sum(1 for r in records if r.get("status") == "early_leave")
    normal = sum(1 for r in records if r.get("status") == "normal")
    on_time_rate = round(normal / total * 100) if total > 0 else 0
    total_mins = sum(r.get("work_minutes") or 0 for r in records)

    consec_absent = 0
    max_consec = 0
    for r in records:
        if r.get("status") == "absent":
            consec_absent += 1
            max_consec = max(max_consec, consec_absent)
        else:
            consec_absent = 0

    return {
        "work_days": total,
        "normal": normal,
        "late": late,
        "absent": absent,
        "early_leave": early,
        "on_time_rate": on_time_rate,
        "total_hours": round(total_mins / 60, 1),
        "consec_absent": max_consec,
    }


def prev_next_month(year_month):
    y, m = map(int, year_month.split("-"))
    prev_m = m - 1 if m > 1 else 12
    prev_y = y if m > 1 else y - 1
    next_m = m + 1 if m < 12 else 1
    next_y = y if m < 12 else y + 1
    return f"{prev_y}-{prev_m:02d}", f"{next_y}-{next_m:02d}"


def available_months():
    now = now_kst()
    months = []
    for i in range(6):
        m = now.month - i
        y = now.year
        if m <= 0:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")
    return months

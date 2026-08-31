from datetime import date, timedelta


LEAVE_TYPES = {
    "annual": {"label": "연차", "badge_bg": "#e3f0ff", "badge_color": "#2563eb", "uses_balance": True},
    "half_day": {"label": "반차", "badge_bg": "#fef9c3", "badge_color": "#ca8a04", "uses_balance": True},
    "sick": {"label": "병가", "badge_bg": "#fee2e2", "badge_color": "#dc2626", "uses_balance": False},
    "family_event": {"label": "경조사", "badge_bg": "#fce7f3", "badge_color": "#be185d", "uses_balance": False},
    "official": {"label": "공가", "badge_bg": "#dbeafe", "badge_color": "#1d4ed8", "uses_balance": False},
    "other": {"label": "기타", "badge_bg": "#f3f4f6", "badge_color": "#374151", "uses_balance": False},
    "special": {"label": "특별휴가", "badge_bg": "#f3e8ff", "badge_color": "#7c3aed", "uses_balance": False},
    "maternity": {"label": "출산휴가", "badge_bg": "#dcfce7", "badge_color": "#16a34a", "uses_balance": False},
    "paternity": {"label": "배우자출산휴가", "badge_bg": "#dcfce7", "badge_color": "#16a34a", "uses_balance": False},
    "compensation": {"label": "보상휴가", "badge_bg": "#e0e7ff", "badge_color": "#4338ca", "uses_balance": False},
}


def get_leave_balance(conn, emp_id):
    row = conn.execute(
        "SELECT annual_leave_total, annual_leave_used FROM employees WHERE id = ?",
        (emp_id,),
    ).fetchone()
    if not row:
        return {"total": 15, "used": 0, "remaining": 15}
    total = row["annual_leave_total"] or 15
    used = row["annual_leave_used"] or 0
    return {"total": total, "used": used, "remaining": round(total - used, 1)}


def validate_leave_request(conn, emp_id, leave_type, start_date_str, end_date_str, days):
    errors = []
    today = date.today()

    try:
        sd = date.fromisoformat(start_date_str)
        ed = date.fromisoformat(end_date_str)
    except ValueError:
        return ["날짜 형식이 올바르지 않습니다."]

    if sd < today:
        errors.append("과거 날짜는 신청할 수 없습니다.")

    if ed < sd:
        errors.append("종료일이 시작일보다 빠릅니다.")

    lt = LEAVE_TYPES.get(leave_type, {})
    if lt.get("uses_balance"):
        balance = get_leave_balance(conn, emp_id)
        if days > balance["remaining"]:
            errors.append(f"잔여 연차({balance['remaining']}일)를 초과합니다.")

    overlap = conn.execute(
        """SELECT id FROM leave_requests
           WHERE employee_id = ? AND status = 'approved'
           AND start_date <= ? AND end_date >= ?""",
        (emp_id, end_date_str, start_date_str),
    ).fetchone()
    if overlap:
        errors.append("해당 기간에 이미 승인된 휴가가 있습니다.")

    return errors


def approve_leave(conn, leave_id, approver_id):
    lr = conn.execute("SELECT * FROM leave_requests WHERE id = ?", (leave_id,)).fetchone()
    if not lr or lr["status"] != "pending":
        return False

    conn.execute(
        "UPDATE leave_requests SET status='approved', approved_by=?, approved_at=datetime('now','localtime') WHERE id=?",
        (approver_id, leave_id),
    )

    lt = LEAVE_TYPES.get(lr["leave_type"], {})
    if lt.get("uses_balance"):
        conn.execute(
            "UPDATE employees SET annual_leave_used = annual_leave_used + ? WHERE id = ?",
            (lr["days"], lr["employee_id"]),
        )

    conn.commit()
    return True


def reject_leave(conn, leave_id, approver_id, reason):
    lr = conn.execute("SELECT * FROM leave_requests WHERE id = ?", (leave_id,)).fetchone()
    if not lr or lr["status"] != "pending":
        return False

    conn.execute(
        "UPDATE leave_requests SET status='rejected', approved_by=?, approved_at=datetime('now','localtime'), reject_reason=? WHERE id=?",
        (approver_id, leave_id, reason),
    )
    conn.commit()
    return True


def get_pending_leaves(conn, company_id):
    return conn.execute(
        """SELECT lr.*, e.name as emp_name, e.dept, e.employee_no
           FROM leave_requests lr
           JOIN employees e ON lr.employee_id = e.id
           WHERE e.company_id = ? AND lr.status = 'pending'
           ORDER BY lr.created_at ASC""",
        (company_id,),
    ).fetchall()


def get_all_leaves(conn, company_id, status_filter=None):
    sql = """SELECT lr.*, e.name as emp_name, e.dept, e.employee_no
             FROM leave_requests lr
             JOIN employees e ON lr.employee_id = e.id
             WHERE e.company_id = ?"""
    params = [company_id]
    if status_filter:
        sql += " AND lr.status = ?"
        params.append(status_filter)
    sql += " ORDER BY lr.created_at DESC"
    return conn.execute(sql, params).fetchall()


def get_month_leaves(conn, company_id, year, month):
    month_start = f"{year}-{month:02d}-01"
    if month == 12:
        month_end = f"{year + 1}-01-01"
    else:
        month_end = f"{year}-{month + 1:02d}-01"

    return conn.execute(
        """SELECT lr.*, e.name as emp_name, e.dept
           FROM leave_requests lr
           JOIN employees e ON lr.employee_id = e.id
           WHERE e.company_id = ? AND lr.status = 'approved'
           AND lr.start_date < ? AND lr.end_date >= ?
           ORDER BY lr.start_date""",
        (company_id, month_end, month_start),
    ).fetchall()


def build_leave_calendar(leaves, year, month):
    import calendar
    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdayscalendar(year, month)

    leave_map = {}
    for lv in leaves:
        sd = date.fromisoformat(lv["start_date"])
        ed = date.fromisoformat(lv["end_date"])
        d = sd
        while d <= ed:
            if d.year == year and d.month == month:
                day = d.day
                if day not in leave_map:
                    leave_map[day] = []
                lt = LEAVE_TYPES.get(lv["leave_type"], {})
                leave_map[day].append({
                    "name": lv["emp_name"],
                    "type": lt.get("label", lv["leave_type"]),
                    "badge_bg": lt.get("badge_bg", "#f3f4f6"),
                    "badge_color": lt.get("badge_color", "#374151"),
                })
            d += timedelta(days=1)

    return weeks, leave_map

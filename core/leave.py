import calendar
from datetime import date, timedelta
from core import audit
from core.tz import today_kst
from core.leave_accrual import ensure_accrual, get_leave_balance as _accrual_balance


LEAVE_TYPES = {
    "annual": {"label": "연차", "uses_balance": True},
    "half_day": {"label": "반차", "uses_balance": True},
    "sick": {"label": "병가", "uses_balance": False},
    "family_event": {"label": "경조사", "uses_balance": False},
    "official": {"label": "공가", "uses_balance": False},
    "other": {"label": "기타", "uses_balance": False},
    "special": {"label": "특별휴가", "uses_balance": False},
    "maternity": {"label": "출산휴가", "uses_balance": False},
    "paternity": {"label": "배우자출산휴가", "uses_balance": False},
    "compensation": {"label": "보상휴가", "uses_balance": False},
}


def get_leave_balance(conn, emp_id, year=None):
    if year is None:
        year = date.today().year
    granted, used, remain = _accrual_balance(conn, emp_id, year)
    return {"total": granted, "used": used, "remaining": remain}


def validate_leave_request(conn, emp_id, leave_type, start_date_str, end_date_str, days):
    errors = []
    today = today_kst()

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
        yr = sd.year
        balance = get_leave_balance(conn, emp_id, yr)
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


def create_leave(conn, emp_id, leave_type, start_date, end_date, days, reason,
                 attachment=None, half_day_period=None, doc_id=None):
    cur = conn.execute(
        """INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days, reason, attachment,
               half_day_period, status, doc_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (emp_id, leave_type, start_date, end_date, days, reason, attachment, half_day_period, doc_id),
    )
    return cur.lastrowid


def _doc_leave(conn, doc_id):
    return conn.execute(
        """SELECT lr.*, e.company_id, e.name AS emp_name FROM leave_requests lr
           JOIN employees e ON e.id = lr.employee_id WHERE lr.doc_id=?""",
        (doc_id,),
    ).fetchone()


def approve_leave(conn, doc, u, now):
    lr = _doc_leave(conn, doc["id"])
    # 통합 전 그룹웨어 휴가 양식 문서는 연결된 신청 없음
    if not lr:
        return
    conn.execute(
        "UPDATE leave_requests SET status='approved', approved_by=?, approved_at=? WHERE id=?",
        (u["id"], now, lr["id"]),
    )
    if LEAVE_TYPES.get(lr["leave_type"], {}).get("uses_balance"):
        emp_id = lr["employee_id"]
        # 신청일 기준 연도로 차감
        yr = date.fromisoformat(lr["start_date"]).year
        ensure_accrual(conn, emp_id, yr)
        conn.execute(
            """UPDATE leave_accruals SET used = used + ?
               WHERE employee_id=? AND accrual_year=?""",
            (lr["days"], emp_id, yr),
        )
    audit.log(conn, u["id"], "leave_approve", "leave", lr["id"],
              f"{lr['emp_name']} {lr['start_date']}~{lr['end_date']}", company_id=lr["company_id"])


def reject_leave(conn, doc, u, now, comment):
    lr = _doc_leave(conn, doc["id"])
    if not lr:
        return
    conn.execute(
        "UPDATE leave_requests SET status='rejected', approved_by=?, approved_at=?, reject_reason=? WHERE id=?",
        (u["id"], now, comment, lr["id"]),
    )
    audit.log(conn, u["id"], "leave_reject", "leave", lr["id"],
              f"{lr['emp_name']} {lr['start_date']}~{lr['end_date']}", company_id=lr["company_id"])


def cancel_block(conn, lr):
    s, e = date.fromisoformat(lr["start_date"]), date.fromisoformat(lr["end_date"])
    for y, m in {(s.year, s.month), (e.year, e.month)}:
        if conn.execute(
            "SELECT 1 FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=? AND status='confirmed'",
            (lr["employee_id"], y, m),
        ).fetchone():
            return "급여가 확정된 달의 휴가는 취소할 수 없습니다."
    return None


def cancel_leave(conn, leave_id, reason):
    # 승인된 휴가 취소. 승인 전 신청은 결재 회수로 처리
    lr = conn.execute("SELECT * FROM leave_requests WHERE id=?", (leave_id,)).fetchone()
    if not lr or lr["status"] != "approved":
        return False

    conn.execute("UPDATE leave_requests SET status='cancelled', cancel_reason=? WHERE id=?", (reason, leave_id))
    if LEAVE_TYPES.get(lr["leave_type"], {}).get("uses_balance"):
        yr = date.fromisoformat(lr["start_date"]).year
        conn.execute(
            """UPDATE leave_accruals SET used = MAX(0, used - ?)
               WHERE employee_id=? AND accrual_year=?""",
            (lr["days"], lr["employee_id"], yr),
        )
    return True


def done_cancel(conn, doc, u, now):
    lr = conn.execute(
        """SELECT lr.*, e.company_id, e.name AS emp_name FROM leave_requests lr
           JOIN employees e ON e.id = lr.employee_id WHERE lr.cancel_doc_id=?""",
        (doc["id"],),
    ).fetchone()
    if lr and cancel_leave(conn, lr["id"], lr["cancel_reason"]):
        audit.log(conn, u["id"], "leave_cancel", "leave", lr["id"],
                  f"{lr['emp_name']} {lr['start_date']}~{lr['end_date']}", company_id=lr["company_id"])


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
                })
            d += timedelta(days=1)

    return weeks, leave_map

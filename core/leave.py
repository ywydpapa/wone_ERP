import calendar
from datetime import date, timedelta
from core.approval import approve, reject, create_approval
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
                 attachment=None, half_day_period=None):
    cur = conn.execute(
        """INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days, reason, attachment, half_day_period, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (emp_id, leave_type, start_date, end_date, days, reason, attachment, half_day_period),
    )
    leave_id = cur.lastrowid
    create_approval(conn, 'leave', leave_id)
    return leave_id


def approve_leave(conn, leave_id, approver_id):
    lr = conn.execute("SELECT * FROM leave_requests WHERE id = ?", (leave_id,)).fetchone()
    if not lr or lr["status"] != "pending":
        return False

    conn.execute("UPDATE leave_requests SET status='approved' WHERE id=?", (leave_id,))
    approve(conn, 'leave', leave_id, approver_id)

    lt = LEAVE_TYPES.get(lr["leave_type"], {})
    if lt.get("uses_balance"):
        emp_id = lr["employee_id"]
        # 신청일 기준 연도로 차감
        yr = date.fromisoformat(lr["start_date"]).year
        ensure_accrual(conn, emp_id, yr)
        conn.execute(
            """UPDATE leave_accruals SET used = used + ?
               WHERE employee_id=? AND accrual_year=?""",
            (lr["days"], emp_id, yr),
        )
        conn.execute(
            "UPDATE employees SET annual_leave_used = annual_leave_used + ? WHERE id = ?",
            (lr["days"], emp_id),
        )

    conn.commit()
    return True


def reject_leave(conn, leave_id, approver_id, reason):
    lr = conn.execute("SELECT * FROM leave_requests WHERE id = ?", (leave_id,)).fetchone()
    if not lr or lr["status"] != "pending":
        return False

    conn.execute("UPDATE leave_requests SET status='rejected' WHERE id=?", (leave_id,))
    reject(conn, 'leave', leave_id, approver_id, reason)
    conn.commit()
    return True


def cancel_leave(conn, leave_id, emp_id=None):
    # emp_id 있으면 본인 pending 취소, 없으면 HR의 approved 취소
    sql = "SELECT * FROM leave_requests WHERE id=?"
    params = [leave_id]
    if emp_id is not None:
        sql += " AND employee_id=?"
        params.append(emp_id)
    lr = conn.execute(sql, params).fetchone()
    if not lr:
        return False

    if emp_id is not None and lr["status"] != "pending":
        return False
    if emp_id is None and lr["status"] != "approved":
        return False

    conn.execute("UPDATE leave_requests SET status='cancelled' WHERE id=?", (leave_id,))

    # 승인된 연차 취소 시 잔여 복원
    if lr["status"] == "approved":
        lt = LEAVE_TYPES.get(lr["leave_type"], {})
        if lt.get("uses_balance"):
            emp = lr["employee_id"]
            yr = date.fromisoformat(lr["start_date"]).year
            conn.execute(
                """UPDATE leave_accruals SET used = MAX(0, used - ?)
                   WHERE employee_id=? AND accrual_year=?""",
                (lr["days"], emp, yr),
            )
            conn.execute(
                "UPDATE employees SET annual_leave_used = MAX(0, annual_leave_used - ?) WHERE id=?",
                (lr["days"], emp),
            )

    conn.commit()
    return True


def get_pending_leaves(conn, company_id):
    return conn.execute(
        """SELECT lr.*, e.name as emp_name, e.dept, e.employee_no,
                  a.comment as reject_reason
           FROM leave_requests lr
           JOIN employees e ON lr.employee_id = e.id
           LEFT JOIN approvals a ON a.doc_type='leave' AND a.doc_id=lr.id AND a.step=1
           WHERE e.company_id = ? AND lr.status = 'pending'
           ORDER BY lr.created_at ASC""",
        (company_id,),
    ).fetchall()


def get_all_leaves(conn, company_id, status_filter=None):
    sql = """SELECT lr.*, e.name as emp_name, e.dept, e.employee_no,
                    a.comment as reject_reason
             FROM leave_requests lr
             JOIN employees e ON lr.employee_id = e.id
             LEFT JOIN approvals a ON a.doc_type='leave' AND a.doc_id=lr.id AND a.step=1
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

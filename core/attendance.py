import calendar
from datetime import date, timedelta

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from openpyxl.utils import get_column_letter

from core.leave import LEAVE_TYPES
from core.holiday import get_holidays
from core.tz import now_kst, today_kst
from core.work_schedule import get_schedule
from core.export import esc_cell, HEADER_FONT, HEADER_FILL, CELL_FONT, THIN_BORDER


STATUS_LABELS = {
    "normal": "정상",
    "late": "지각",
    "early_leave": "조퇴",
    "late_early": "지각+조퇴",
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
        f"""SELECT a.*, e.name AS employee_name, e.employee_no, e.dept,
                   cc.name AS company_name
            FROM attendance a
            JOIN employees e ON e.id = a.employee_id
            LEFT JOIN client_companies cc ON cc.id = e.company_id
            WHERE a.employee_id IN ({placeholders})
              AND a.work_date LIKE ?
            ORDER BY a.work_date DESC, e.name""",
        [*employee_ids, f"{year_month}%"],
    ).fetchall()
    records = [dict(r) for r in rows]
    for r in records:
        r["status_label"] = STATUS_LABELS.get(r.get("status", ""), r.get("status", ""))
        mins = r.get("work_minutes") or 0
        h, m = mins // 60, mins % 60
        r["work_hours"] = (f"{h}시간 {m}분" if m else f"{h}시간") if mins else "-"
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
        h, m = mins // 60, mins % 60
        r["work_hours"] = (f"{h}시간 {m}분" if m else f"{h}시간") if mins else "-"
    return records


WORK_STATUSES = ("normal", "late", "early_leave", "late_early")


def apply_overtime(conn, employee_id, work_date, minutes):
    row = conn.execute(
        "SELECT id FROM attendance WHERE employee_id=? AND work_date=?", (employee_id, work_date)
    ).fetchone()
    if row:
        conn.execute("UPDATE attendance SET overtime_minutes = overtime_minutes + ? WHERE id=?",
                     (minutes, row["id"]))
    else:
        conn.execute(
            "INSERT INTO attendance (employee_id, work_date, status, overtime_minutes) VALUES (?,?,'normal',?)",
            (employee_id, work_date, minutes)
        )


def calc_night_minutes(clock_in, clock_out):
    if not clock_in or not clock_out:
        return 0
    cin = int(clock_in[:2]) * 60 + int(clock_in[3:5])
    cout = int(clock_out[:2]) * 60 + int(clock_out[3:5])
    if cout <= cin:
        cout += 24 * 60  # 익일 퇴근
    night = max(0, min(cout, 24 * 60) - max(cin, 22 * 60))
    night += max(0, min(cout, 24 * 60 + 6 * 60) - max(cin, 24 * 60))
    return night


def get_month_work_stats(conn, employee_id, year_month):
    records = get_worker_month_records(conn, employee_id, year_month)
    y = int(year_month.split("-")[0])
    holiday_dates = {h["date"] for h in get_holidays(conn, y)}

    emp = conn.execute("SELECT company_id FROM employees WHERE id=?", (employee_id,)).fetchone()
    rest_day = get_schedule(conn, emp["company_id"] if emp else None)["rest_day"]

    work_days = total_mins = ot_mins = night_mins = holiday_mins = 0
    holiday_day_mins = []
    for r in records:
        if r.get("status") not in WORK_STATUSES:
            continue
        mins = r.get("work_minutes") or 0
        work_days += 1
        total_mins += mins
        ot_mins += r.get("overtime_minutes") or 0
        night_mins += calc_night_minutes(r.get("clock_in"), r.get("clock_out"))
        wd = date.fromisoformat(r["work_date"]).weekday()
        if wd == rest_day or r["work_date"] in holiday_dates:
            holiday_mins += mins
            holiday_day_mins.append(mins)

    return {
        "work_days": work_days,
        "total_mins": total_mins,
        "ot_mins": ot_mins,
        "night_mins": night_mins,
        "holiday_mins": holiday_mins,
        "holiday_day_mins": holiday_day_mins,
    }


def get_worker_month_leaves(conn, employee_id, year_month):
    y, m = map(int, year_month.split("-"))
    month_start = f"{y}-{m:02d}-01"
    if m == 12:
        month_end = f"{y + 1}-01-01"
    else:
        month_end = f"{y}-{m + 1:02d}-01"

    rows = conn.execute(
        """SELECT id, leave_type, start_date, end_date, days, half_day_period
           FROM leave_requests
           WHERE employee_id = ? AND status = 'approved'
             AND start_date < ? AND end_date >= ?
           ORDER BY start_date""",
        (employee_id, month_end, month_start),
    ).fetchall()

    by_date = {}
    for row in rows:
        sd = date.fromisoformat(row["start_date"])
        ed = date.fromisoformat(row["end_date"])
        lt = LEAVE_TYPES.get(row["leave_type"], {})
        label = lt.get("label", row["leave_type"])
        d = sd
        while d <= ed:
            if d.year == y and d.month == m:
                by_date[d.isoformat()] = {
                    "type": row["leave_type"],
                    "label": label,
                    "half_day_period": row["half_day_period"],
                }
            d += timedelta(days=1)
    return by_date


def build_calendar_data(records, year_month, leaves=None, schedule=None):
    y, m = map(int, year_month.split("-"))
    by_date = {r["work_date"]: r for r in records}
    leaves = leaves or {}
    rest_day = schedule["rest_day"] if schedule else 6
    off_day = schedule["off_day"] if schedule else 5
    _, days_in_month = calendar.monthrange(y, m)
    first_weekday = date(y, m, 1).weekday()
    today = today_kst().isoformat()

    days = []
    for d in range(1, days_in_month + 1):
        iso = f"{y}-{m:02d}-{d:02d}"
        rec = by_date.get(iso)
        wd = date(y, m, d).weekday()
        days.append({
            "day": d,
            "date": iso,
            "record": rec,
            "leave": leaves.get(iso),
            "is_today": iso == today,
            "is_weekend": wd in (rest_day, off_day),
        })
    return {"days": days, "first_weekday": first_weekday, "year": y, "month": m}


def worker_month_summary(records, leaves=None):
    total = len([r for r in records if r.get("status") != "holiday"])
    late = sum(1 for r in records if r.get("status") in ("late", "late_early"))
    absent = sum(1 for r in records if r.get("status") == "absent")
    early = sum(1 for r in records if r.get("status") in ("early_leave", "late_early"))
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

    leave_days = len(leaves) if leaves else 0

    return {
        "work_days": total,
        "normal": normal,
        "late": late,
        "absent": absent,
        "early_leave": early,
        "on_time_rate": on_time_rate,
        "total_hours": total_mins // 60,
        "total_mins_remainder": total_mins % 60,
        "consec_absent": max_consec,
        "leave_days": leave_days,
    }


def merge_records_leaves(records, leaves):
    by_date = {r["work_date"]: r for r in records}
    for dt, lv in leaves.items():
        if dt not in by_date:
            by_date[dt] = {
                "work_date": dt,
                "clock_in": None,
                "clock_out": None,
                "work_minutes": 0,
                "work_hours": "-",
                "status": "leave",
                "status_label": lv["label"],
                "notes": "",
                "id": None,
            }
        by_date[dt]["leave"] = lv
    return sorted(by_date.values(), key=lambda x: x["work_date"])


def is_month_closed(conn, year, month, company_id):
    row = conn.execute(
        "SELECT status FROM attendance_closings WHERE year=? AND month=? AND company_id=?",
        (year, month, company_id),
    ).fetchone()
    return row and row["status"] == "closed"


def get_closing_info(conn, year, month, company_id):
    row = conn.execute(
        "SELECT ac.*, u.name AS closed_by_name FROM attendance_closings ac "
        "LEFT JOIN users u ON ac.closed_by=u.id "
        "WHERE ac.year=? AND ac.month=? AND ac.company_id=?",
        (year, month, company_id),
    ).fetchone()
    return dict(row) if row else None


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


def build_sheet_data(conn, year, month, company_id):
    _, days_in_month = calendar.monthrange(year, month)
    ym = f"{year}-{month:02d}"

    emp_sql = "SELECT id, name, employee_no, monthly_work_hours, hire_date FROM employees WHERE status='active'"
    emp_params = []
    if company_id:
        emp_sql += " AND company_id=?"
        emp_params.append(company_id)
    emp_sql += " ORDER BY employee_no, name"
    employees = conn.execute(emp_sql, emp_params).fetchall()
    emp_ids = [e["id"] for e in employees]

    if not emp_ids:
        return [], days_in_month

    ph = ",".join("?" * len(emp_ids))
    att_rows = conn.execute(
        f"""SELECT employee_id, work_date, status, clock_in, clock_out,
                   work_minutes, overtime_minutes, break_minutes, notes
            FROM attendance
            WHERE employee_id IN ({ph}) AND work_date LIKE ?
            ORDER BY work_date""",
        [*emp_ids, f"{ym}%"],
    ).fetchall()

    att_map = {}
    for r in att_rows:
        att_map.setdefault(r["employee_id"], {})[r["work_date"]] = dict(r)

    rows = []
    for emp in employees:
        eid = emp["id"]
        days = att_map.get(eid, {})
        cells = []
        work_days = 0
        late_cnt = 0
        early_cnt = 0
        absent_cnt = 0
        holiday_cnt = 0
        total_mins = 0
        ot_mins = 0
        for d in range(1, days_in_month + 1):
            dt = f"{ym}-{d:02d}"
            rec = days.get(dt)
            if rec:
                cells.append(rec)
                if rec["status"] in ("normal", "late", "early_leave", "late_early"):
                    work_days += 1
                    total_mins += rec.get("work_minutes") or 0
                    ot_mins += rec.get("overtime_minutes") or 0
                if rec["status"] in ("late", "late_early"):
                    late_cnt += 1
                if rec["status"] in ("early_leave", "late_early"):
                    early_cnt += 1
                if rec["status"] == "absent":
                    absent_cnt += 1
                elif rec["status"] == "holiday":
                    holiday_cnt += 1
            else:
                cells.append(None)
        rows.append({
            "employee": dict(emp),
            "cells": cells,
            "work_days": work_days,
            "late": late_cnt,
            "early_leave": early_cnt,
            "absent": absent_cnt,
            "holiday_days": holiday_cnt,
            "monthly_work_hours": emp["monthly_work_hours"] or 0,
            "total_mins": total_mins,
            "total_hours": total_mins // 60,
            "total_mins_r": total_mins % 60,
            "ot_hours": ot_mins // 60,
            "ot_mins_r": ot_mins % 60,
        })
    return rows, days_in_month


def build_sheet_workbook(rows, days_in_month, ym_str, company_name):
    wb = Workbook()
    ws = wb.active
    ws.title = "출근부"

    title_text = f"출근부 - {ym_str}"
    if company_name:
        title_text += f" ({company_name})"
    sum_cols = ["출근", "지각", "조퇴", "결근", "휴일", "연장", "총근무"]
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=days_in_month + 2 + len(sum_cols))
    title_cell = ws.cell(row=1, column=1, value=title_text)
    title_cell.font = Font(name="맑은 고딕", bold=True, size=14)
    title_cell.alignment = Alignment(horizontal="center")

    header_row = 3
    headers = ["사번", "이름"] + [str(d) for d in range(1, days_in_month + 1)] + sum_cols
    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=ci, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER

    status_short = {"normal": "O", "late": "△", "early_leave": "▽", "late_early": "△▽", "absent": "X", "holiday": "-"}
    for ri, r in enumerate(rows, header_row + 1):
        emp = r["employee"]
        ws.cell(row=ri, column=1, value=esc_cell(emp.get("employee_no", ""))).font = CELL_FONT
        ws.cell(row=ri, column=1).border = THIN_BORDER
        ws.cell(row=ri, column=2, value=esc_cell(emp["name"])).font = CELL_FONT
        ws.cell(row=ri, column=2).border = THIN_BORDER
        for di, cell_data in enumerate(r["cells"], 3):
            cell = ws.cell(row=ri, column=di)
            cell.border = THIN_BORDER
            cell.alignment = Alignment(horizontal="center")
            cell.font = CELL_FONT
            if cell_data:
                cell.value = status_short.get(cell_data["status"], "")
            else:
                cell.value = ""
        base_col = days_in_month + 3
        vals = [
            r["work_days"], r["late"], r["early_leave"], r["absent"],
            r["holiday_days"],
            f"{r['ot_hours']}:{r['ot_mins_r']:02d}",
            f"{r['total_hours']}:{r['total_mins_r']:02d}",
        ]
        for offset, val in enumerate(vals):
            cell = ws.cell(row=ri, column=base_col + offset, value=val)
            cell.font = CELL_FONT
            cell.border = THIN_BORDER
            cell.alignment = Alignment(horizontal="center")

    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 10
    for ci in range(3, days_in_month + 3):
        col_letter = get_column_letter(ci)
        ws.column_dimensions[col_letter].width = 4
    for ci in range(days_in_month + 3, days_in_month + 3 + len(sum_cols)):
        col_letter = get_column_letter(ci)
        ws.column_dimensions[col_letter].width = 9

    return wb

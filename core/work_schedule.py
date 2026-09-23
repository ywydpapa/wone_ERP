_DEFAULT = {"start_time": "09:00", "end_time": "18:00", "break_min": 60}
LATE_GRACE = 10  # 분


def get_schedule(conn, company_id):
    if not company_id:
        return dict(_DEFAULT)
    row = conn.execute(
        "SELECT start_time, end_time, break_min FROM work_schedules WHERE company_id=?",
        (company_id,),
    ).fetchone()
    if row:
        return dict(row)
    return dict(_DEFAULT)


def _parse_hm(t):
    return int(t[:2]), int(t[3:5])


def calc_work_minutes(clock_in, clock_out, schedule):
    if not clock_in or not clock_out:
        return 0, 0
    cin_h, cin_m = int(clock_in[:2]), int(clock_in[3:5])
    out_h, out_m = int(clock_out[:2]), int(clock_out[3:5])
    total = (out_h * 60 + out_m) - (cin_h * 60 + cin_m)
    work_m = max(0, total - schedule["break_min"])

    end_h, end_m = _parse_hm(schedule["end_time"])
    end_total = end_h * 60 + end_m
    ot_m = max(0, (out_h * 60 + out_m) - end_total)

    return work_m, ot_m


def is_late(clock_in_time, schedule):
    cin_h, cin_m = int(clock_in_time[:2]), int(clock_in_time[3:5])
    st_h, st_m = _parse_hm(schedule["start_time"])
    threshold = st_h * 60 + st_m + LATE_GRACE
    return (cin_h * 60 + cin_m) > threshold

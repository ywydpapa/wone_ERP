HOLIDAYS_2027 = [
    (2027, "2027-01-01", "신정"),
    (2027, "2027-02-06", "설날연휴"),
    (2027, "2027-02-07", "설날"),
    (2027, "2027-02-08", "설날연휴"),
    (2027, "2027-02-09", "대체공휴일(설날)"),
    (2027, "2027-03-01", "삼일절"),
    (2027, "2027-05-05", "어린이날"),
    (2027, "2027-05-13", "부처님오신날"),
    (2027, "2027-06-06", "현충일"),
    (2027, "2027-08-15", "광복절"),
    (2027, "2027-08-16", "대체공휴일(광복절)"),
    (2027, "2027-09-14", "추석연휴"),
    (2027, "2027-09-15", "추석"),
    (2027, "2027-09-16", "추석연휴"),
    (2027, "2027-10-03", "개천절"),
    (2027, "2027-10-04", "대체공휴일(개천절)"),
    (2027, "2027-10-09", "한글날"),
    (2027, "2027-10-11", "대체공휴일(한글날)"),
    (2027, "2027-12-25", "크리스마스"),
    (2027, "2027-12-27", "대체공휴일(크리스마스)"),
]


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(work_schedules)")}
    if "rest_day" not in cols:
        conn.execute("ALTER TABLE work_schedules ADD COLUMN rest_day INTEGER NOT NULL DEFAULT 6")
    if "off_day" not in cols:
        conn.execute("ALTER TABLE work_schedules ADD COLUMN off_day INTEGER NOT NULL DEFAULT 5")

    conn.executemany(
        "INSERT OR IGNORE INTO holidays (year, date, name) VALUES (?,?,?)",
        HOLIDAYS_2027,
    )
    conn.commit()

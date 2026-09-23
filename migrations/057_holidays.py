import sqlite3

HOLIDAYS_2026 = [
    (2026, "2026-01-01", "신정"),
    (2026, "2026-02-16", "설날연휴"),
    (2026, "2026-02-17", "설날"),
    (2026, "2026-02-18", "설날연휴"),
    (2026, "2026-03-01", "삼일절"),
    (2026, "2026-03-02", "대체공휴일(삼일절)"),
    (2026, "2026-05-05", "어린이날"),
    (2026, "2026-05-24", "부처님오신날"),
    (2026, "2026-05-25", "대체공휴일(부처님오신날)"),
    (2026, "2026-06-06", "현충일"),
    (2026, "2026-08-15", "광복절"),
    (2026, "2026-08-17", "대체공휴일(광복절)"),
    (2026, "2026-09-25", "추석연휴"),
    (2026, "2026-09-26", "추석"),
    (2026, "2026-09-27", "추석연휴"),
    (2026, "2026-10-03", "개천절"),
    (2026, "2026-10-05", "대체공휴일(개천절)"),
    (2026, "2026-10-09", "한글날"),
    (2026, "2026-12-25", "크리스마스"),
]


def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS holidays (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            date TEXT    NOT NULL,
            name TEXT    NOT NULL,
            type TEXT    NOT NULL DEFAULT 'public',
            UNIQUE(date)
        )
    """)
    conn.executemany(
        "INSERT OR IGNORE INTO holidays (year, date, name) VALUES (?,?,?)",
        HOLIDAYS_2026,
    )
    conn.commit()

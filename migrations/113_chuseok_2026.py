# 2026 추석 날짜 보정. 057 하루 밀림, 110 대체공휴일은 토요일 겹침이므로 미발생


def up(conn):
    conn.execute("DELETE FROM holidays WHERE date IN ('2026-09-27', '2026-09-28')")
    for d, name in (("2026-09-24", "추석연휴"), ("2026-09-25", "추석"), ("2026-09-26", "추석연휴")):
        conn.execute(
            "INSERT INTO holidays (year, date, name) VALUES (2026, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET name=excluded.name",
            (d, name),
        )
    conn.commit()

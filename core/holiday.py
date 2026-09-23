def is_holiday(conn, date_str):
    row = conn.execute(
        "SELECT 1 FROM holidays WHERE date=?", (date_str,)
    ).fetchone()
    return row is not None


def get_holidays(conn, year):
    return [
        dict(r) for r in conn.execute(
            "SELECT * FROM holidays WHERE year=? ORDER BY date", (year,)
        ).fetchall()
    ]

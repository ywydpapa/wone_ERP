def is_holiday(conn, date_str):
    # 근로자의 날(5/1)은 2026 개정 전까지 관공서 공휴일과 별개 법률. 과거 연도 호환 위해 하드코딩 유지
    if date_str[5:] == "05-01":
        return True
    row = conn.execute(
        "SELECT 1 FROM holidays WHERE date=?", (date_str,)
    ).fetchone()
    return row is not None


def get_holidays(conn, year):
    rows = [
        dict(r) for r in conn.execute(
            "SELECT * FROM holidays WHERE year=? ORDER BY date", (year,)
        ).fetchall()
    ]
    may1 = f"{year}-05-01"
    if not any(h["date"] == may1 for h in rows):
        rows.append({"id": None, "year": year, "date": may1, "name": "근로자의날", "type": "public"})
        rows.sort(key=lambda h: h["date"])
    return rows

# 공휴일 2026 누락분(제헌절, 노동절) 및 2027 노동절/제헌절 보강
# 제헌절: 2026 관공서 공휴일 재지정
# 노동절: 2026 개정으로 근로자의날에서 관공서 공휴일 제6호로 편입, 대체공휴일 대상 포함
HOLIDAY_BACKFILL = [
    (2026, "2026-05-01", "노동절"),
    (2026, "2026-07-17", "제헌절"),
    (2027, "2027-05-01", "노동절"),
    (2027, "2027-05-03", "대체공휴일(노동절)"),
    (2027, "2027-07-17", "제헌절"),
    (2027, "2027-07-19", "대체공휴일(제헌절)"),
]


def up(conn):
    conn.executemany(
        "INSERT OR IGNORE INTO holidays (year, date, name) VALUES (?,?,?)",
        HOLIDAY_BACKFILL,
    )

    cert_cols = {r[1] for r in conn.execute("PRAGMA table_info(certificate_requests)")}
    if "issued_by" not in cert_cols:
        conn.execute("ALTER TABLE certificate_requests ADD COLUMN issued_by INTEGER REFERENCES users(id)")

    att_cols = {r[1] for r in conn.execute("PRAGMA table_info(attendance)")}
    if "appeal_desired_clock_in" not in att_cols:
        conn.execute("ALTER TABLE attendance ADD COLUMN appeal_desired_clock_in TEXT")
    if "appeal_desired_clock_out" not in att_cols:
        conn.execute("ALTER TABLE attendance ADD COLUMN appeal_desired_clock_out TEXT")

    conn.commit()

# 고용장려금 단가 이력 관리. 기존 상수 단가는 2023년 발생분 공단 고시 기준
# 타 지원금(고용보험, 산재, 사회적기업) 중복수급 시 차액 지급이므로 근로자별 월 수급액 별도 보관


def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subsidy_rates (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            rate_key       TEXT NOT NULL,
            amount         INTEGER NOT NULL,
            effective_date TEXT NOT NULL,
            reason         TEXT,
            created_by     INTEGER REFERENCES users(id),
            created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subsidy_rates_key_date "
        "ON subsidy_rates(rate_key, effective_date)"
    )
    for key, amt in (("경증남", 350000), ("경증여", 500000), ("중증남", 700000), ("중증여", 900000)):
        conn.execute(
            "INSERT INTO subsidy_rates (rate_key, amount, effective_date, reason) VALUES (?,?,'2023-01-01','공단 고시')",
            (key, amt),
        )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS subsidy_offsets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id),
            pay_year    INTEGER NOT NULL,
            pay_month   INTEGER NOT NULL,
            amount      INTEGER NOT NULL DEFAULT 0,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE (employee_id, pay_year, pay_month)
        )
    """)
    conn.commit()

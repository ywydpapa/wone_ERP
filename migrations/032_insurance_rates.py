def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS insurance_rates (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            rate_key       TEXT NOT NULL,
            rate_value     REAL NOT NULL,
            effective_date TEXT NOT NULL,
            created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_insurance_rates_key_date "
        "ON insurance_rates(rate_key, effective_date)"
    )

    # 2026년 기준 요율 시드
    seeds = [
        ("national_pension", 0.0475, "2026-01-01"),
        ("health_insurance", 0.03595, "2026-01-01"),
        ("long_care", 0.1314, "2026-01-01"),
        ("employment_insurance", 0.009, "2026-01-01"),
        ("pension_upper", 5900000, "2026-01-01"),
        ("pension_lower", 370000, "2026-01-01"),
    ]
    for key, val, eff in seeds:
        conn.execute(
            "INSERT INTO insurance_rates (rate_key, rate_value, effective_date) VALUES (?,?,?)",
            (key, val, eff),
        )
    conn.commit()

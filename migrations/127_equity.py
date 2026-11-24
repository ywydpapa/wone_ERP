# 이익준비금(351), 임의적립금(356), 미지급배당금(265) 계정 추가, re_appropriations 테이블 생성


def up(conn):
    new_accounts = [
        ("351", "이익준비금", "자본", 0),
        ("356", "임의적립금", "자본", 0),
        ("265", "미지급배당금", "부채", 0),
    ]
    conn.executemany(
        "INSERT INTO accounts (company_id, code, name, category, is_debit) VALUES (0,?,?,?,?)",
        new_accounts,
    )

    companies = [r["id"] for r in conn.execute("SELECT id FROM client_companies")]
    for cid in companies:
        conn.executemany(
            "INSERT OR IGNORE INTO accounts (company_id, code, name, category, is_debit) VALUES (?,?,?,?,?)",
            [(cid, code, name, cat, is_debit) for code, name, cat, is_debit in new_accounts],
        )

    conn.execute("""
        CREATE TABLE re_appropriations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            approve_date TEXT NOT NULL,
            legal_reserve INTEGER NOT NULL DEFAULT 0,
            cash_div INTEGER NOT NULL DEFAULT 0,
            other_reserve INTEGER NOT NULL DEFAULT 0,
            doc_id INTEGER REFERENCES erp_docs(id),
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE(company_id, year)
        )
    """)
    conn.execute("CREATE INDEX idx_re_approp_book ON re_appropriations(company_id, year)")

    conn.commit()

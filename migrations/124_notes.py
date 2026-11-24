# 어음 관리. 부도어음과수표(246), 매출채권처분손실(956) 계정 추가, notes 테이블 생성


def up(conn):
    new_accounts = [
        ("246", "부도어음과수표", "자산", 1),
        ("956", "매출채권처분손실", "비용", 1),
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
        CREATE TABLE notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('recv','pay')),
            note_no TEXT NOT NULL,
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            amount INTEGER NOT NULL,
            issue_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            bank TEXT DEFAULT '',
            is_electronic INTEGER DEFAULT 0,
            status TEXT NOT NULL,
            issue_doc_id INTEGER REFERENCES erp_docs(id),
            close_doc_id INTEGER REFERENCES erp_docs(id),
            close_date TEXT,
            endorsee_id INTEGER REFERENCES partners(id),
            memo TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("CREATE INDEX idx_notes_book ON notes(company_id)")

    conn.commit()

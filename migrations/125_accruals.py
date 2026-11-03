# 선급비용/미지급비용 기간 배분, 반복전표


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accruals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('prepaid','accrued')),
            expense_code TEXT NOT NULL,
            amount INTEGER NOT NULL,
            start_ym TEXT NOT NULL,
            end_ym TEXT NOT NULL,
            partner_id INTEGER REFERENCES partners(id),
            dept TEXT NOT NULL DEFAULT '',
            memo TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','stopped')),
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_accruals_company ON accruals(company_id, status);

        CREATE TABLE IF NOT EXISTS accrual_posts (
            accrual_id INTEGER NOT NULL REFERENCES accruals(id),
            ym TEXT NOT NULL,
            doc_id INTEGER NOT NULL REFERENCES erp_docs(id),
            UNIQUE(accrual_id, ym)
        );

        CREATE TABLE IF NOT EXISTS recurring_slips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            day INTEGER NOT NULL DEFAULT 0,
            lines_json TEXT NOT NULL,
            start_ym TEXT NOT NULL,
            end_ym TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','stopped')),
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recurring_company ON recurring_slips(company_id, status);

        CREATE TABLE IF NOT EXISTS recurring_posts (
            recurring_id INTEGER NOT NULL REFERENCES recurring_slips(id),
            ym TEXT NOT NULL,
            doc_id INTEGER NOT NULL REFERENCES erp_docs(id),
            UNIQUE(recurring_id, ym)
        );
    """)
    conn.commit()

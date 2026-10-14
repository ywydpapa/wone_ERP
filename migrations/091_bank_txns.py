# 은행 거래내역 업로드, 계정 자동 매칭 규칙, 홈택스 승인번호 중복 방지
# 기존 수기 세금계산서는 승인번호가 빈 문자열이므로 인덱스 대상 제외


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bank_txns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            bank_account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
            txn_at TEXT NOT NULL,
            memo TEXT NOT NULL DEFAULT '',
            counterparty TEXT NOT NULL DEFAULT '',
            amt_in INTEGER NOT NULL DEFAULT 0,
            amt_out INTEGER NOT NULL DEFAULT 0,
            balance INTEGER,
            hash TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT '미처리' CHECK(status IN ('미처리','처리','제외')),
            doc_id INTEGER REFERENCES erp_docs(id),
            settlement_id INTEGER REFERENCES settlements(id),
            uploaded_by INTEGER REFERENCES users(id),
            uploaded_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bank_txns_account ON bank_txns(company_id, bank_account_id, txn_at);

        CREATE TABLE IF NOT EXISTS txn_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            keyword TEXT NOT NULL,
            account_code TEXT NOT NULL,
            partner_id INTEGER REFERENCES partners(id),
            hit_cnt INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER REFERENCES users(id),
            UNIQUE(company_id, keyword)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_tax_invoices_approval
            ON tax_invoices(company_id, approval_no) WHERE approval_no IS NOT NULL AND approval_no != '';
    """)
    conn.execute("ALTER TABLE bank_accounts ADD COLUMN import_preset TEXT")
    conn.execute("ALTER TABLE bank_accounts ADD COLUMN column_map TEXT")

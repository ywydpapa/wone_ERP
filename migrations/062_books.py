def up(conn):
    for ddl in (
        "ALTER TABLE erp_docs ADD COLUMN company_id INTEGER DEFAULT 0",
        "ALTER TABLE erp_docs ADD COLUMN slip_no TEXT",
        "ALTER TABLE erp_docs ADD COLUMN source_type TEXT DEFAULT 'manual'",
        "ALTER TABLE erp_docs ADD COLUMN source_id INTEGER",
        "ALTER TABLE erp_docs ADD COLUMN reversal_of INTEGER",
        "ALTER TABLE erp_docs ADD COLUMN posted_at TEXT",
    ):
        try:
            conn.execute(ddl)
        except Exception:
            pass

    for ddl in (
        "ALTER TABLE slip_lines ADD COLUMN partner_id INTEGER",
        "ALTER TABLE slip_lines ADD COLUMN dept TEXT DEFAULT ''",
        "ALTER TABLE slip_lines ADD COLUMN project_code TEXT DEFAULT ''",
    ):
        try:
            conn.execute(ddl)
        except Exception:
            pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS slip_seqs (
            company_id INTEGER NOT NULL,
            slip_date  TEXT NOT NULL,
            last_no    INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (company_id, slip_date)
        )
    """)

    conn.executescript("""
        CREATE TABLE accounts_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            is_debit INTEGER DEFAULT 1,
            parent_code TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            req_partner INTEGER DEFAULT 0,
            req_dept INTEGER DEFAULT 0,
            UNIQUE(company_id, code)
        );
        INSERT INTO accounts_new (id, company_id, code, name, category, is_debit, parent_code, is_active)
            SELECT id, 0, code, name, category, is_debit, parent_code, is_active FROM accounts;
        DROP TABLE accounts;
        ALTER TABLE accounts_new RENAME TO accounts;

        CREATE TABLE partners_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            biz_no TEXT DEFAULT '',
            representative TEXT DEFAULT '',
            biz_type TEXT DEFAULT '',
            biz_item TEXT DEFAULT '',
            address TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            partner_type TEXT CHECK(partner_type IN ('supplier','customer','both')) DEFAULT 'supplier',
            contact_name TEXT DEFAULT '',
            contact_phone TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            email TEXT DEFAULT '',
            fax TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            task_id INTEGER REFERENCES tasks(id),
            UNIQUE(company_id, code)
        );
        INSERT INTO partners_new (id, company_id, code, name, biz_no, representative, biz_type, biz_item, address, phone, is_active, partner_type, contact_name, contact_phone, contact_email, email, fax, notes, created_by, task_id)
            SELECT id, 0, code, name, biz_no, representative, biz_type, biz_item, address, phone, is_active, partner_type, contact_name, contact_phone, contact_email, email, fax, notes, created_by, task_id FROM partners;
        DROP TABLE partners;
        ALTER TABLE partners_new RENAME TO partners;

        CREATE TABLE fi_closings_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            closed_by INTEGER REFERENCES users(id),
            closed_at TEXT,
            reopened_by INTEGER REFERENCES users(id),
            reopened_at TEXT,
            reopen_reason TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(company_id, year, month)
        );
        INSERT INTO fi_closings_new (id, company_id, year, month, status, closed_by, closed_at, reopened_by, reopened_at, reopen_reason, created_at)
            SELECT id, 0, year, month, status, closed_by, closed_at, reopened_by, reopened_at, reopen_reason, created_at FROM fi_closings;
        DROP TABLE fi_closings;
        ALTER TABLE fi_closings_new RENAME TO fi_closings;

        CREATE TABLE budgets_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            account_code TEXT NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(company_id, account_code, year, month)
        );
        INSERT INTO budgets_new (id, company_id, account_code, year, month, amount, created_by, created_at)
            SELECT id, 0, account_code, year, month, amount, created_by, created_at FROM budgets;
        DROP TABLE budgets;
        ALTER TABLE budgets_new RENAME TO budgets;
    """)

    # 결산용 계정 추가 (공통 계정, company_id=0)
    conn.executemany(
        "INSERT INTO accounts (company_id, code, name, category, is_debit) VALUES (0,?,?,?,?)",
        [
            ("375", "이월이익잉여금", "자본", 0),
            ("377", "미처분이익잉여금", "자본", 0),
            ("400", "손익", "자본", 0),
            ("914", "유형자산처분이익", "수익", 0),
            ("970", "유형자산처분손실", "비용", 1),
        ],
    )
    conn.execute(
        "UPDATE accounts SET req_partner=1 WHERE company_id=0 AND code IN ('110','111','251','252','257','115')"
    )

    # 회사 배정 백필
    conn.execute("""
        UPDATE erp_docs SET company_id = (
            SELECT wr.company_id FROM tasks t JOIN work_requests wr ON wr.id = t.work_request_id
            WHERE t.id = erp_docs.task_id)
        WHERE task_id IS NOT NULL AND company_id = 0""")
    conn.execute("""
        UPDATE erp_docs SET company_id = (
            SELECT e.company_id FROM payslips p JOIN employees e ON e.id = p.employee_id
            WHERE p.id = erp_docs.payslip_id)
        WHERE payslip_id IS NOT NULL AND company_id = 0""")
    conn.execute("""
        UPDATE erp_docs SET company_id = COALESCE(
            (SELECT company_id FROM client_users WHERE user_id = erp_docs.user_id),
            (SELECT company_id FROM employees WHERE user_id = erp_docs.user_id), 0)
        WHERE company_id = 0 OR company_id IS NULL""")

    conn.execute("""
        UPDATE partners SET company_id = COALESCE((
            SELECT wr.company_id FROM tasks t JOIN work_requests wr ON wr.id = t.work_request_id
            WHERE t.id = partners.task_id), 0)
        WHERE task_id IS NOT NULL AND company_id = 0""")
    conn.execute("""
        UPDATE partners SET company_id = COALESCE(
            (SELECT company_id FROM client_users WHERE user_id = partners.created_by),
            (SELECT company_id FROM employees WHERE user_id = partners.created_by), 0)
        WHERE company_id = 0 OR company_id IS NULL""")

    # 회사별 계정 복사
    companies = [r["id"] for r in conn.execute("SELECT id FROM client_companies")]
    base_accounts = conn.execute(
        "SELECT code, name, category, is_debit, parent_code, is_active, req_partner, req_dept FROM accounts WHERE company_id=0"
    ).fetchall()
    for cid in companies:
        for acc in base_accounts:
            conn.execute(
                "INSERT OR IGNORE INTO accounts (company_id, code, name, category, is_debit, parent_code, is_active, req_partner, req_dept) VALUES (?,?,?,?,?,?,?,?,?)",
                (cid, acc["code"], acc["name"], acc["category"], acc["is_debit"], acc["parent_code"], acc["is_active"], acc["req_partner"], acc["req_dept"]),
            )

    conn.execute("""
        UPDATE slip_lines SET partner_id = (
            SELECT p.id FROM partners p JOIN erp_docs d ON d.id = slip_lines.doc_id
            WHERE p.name = slip_lines.partner AND p.company_id = d.company_id)
        WHERE partner != ''""")

    # 전표번호 채번 (회사+일자별 YYYYMMDD-NNNNN)
    rows = conn.execute(
        "SELECT id, company_id, slip_date FROM erp_docs WHERE slip_date IS NOT NULL AND slip_date != '' ORDER BY company_id, slip_date, id"
    ).fetchall()
    seqs = {}
    for r in rows:
        key = (r["company_id"], r["slip_date"])
        seqs[key] = seqs.get(key, 0) + 1
        no = seqs[key]
        date_part = r["slip_date"].replace("-", "")
        conn.execute(
            "UPDATE erp_docs SET slip_no=? WHERE id=?",
            (f"{date_part}-{no:05d}", r["id"]),
        )
    for (cid, sdate), last_no in seqs.items():
        conn.execute(
            "INSERT INTO slip_seqs (company_id, slip_date, last_no) VALUES (?,?,?)",
            (cid, sdate, last_no),
        )

    conn.execute("UPDATE erp_docs SET posted_at = COALESCE(approved_at, created_at) WHERE status='done'")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_book ON erp_docs(company_id, slip_date)")

    conn.commit()

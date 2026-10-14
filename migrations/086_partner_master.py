# 거래처구분, 등록구분, 사업자/거래 상태, 결제조건, 배송지, 계좌 다건, 첨부, 변경이력, 담당자 역할/퇴사, 문서별 담당자
# 기존 bank_*, is_invoice 컬럼은 화면 전환 후 087에서 재동기화 후 삭제


def fmt_phone(v):
    d = "".join(c for c in v or "" if c.isdigit())
    if d.startswith("02") and len(d) in (9, 10):
        return f"02-{d[2:-4]}-{d[-4:]}"
    if d.startswith("0") and len(d) in (10, 11):
        return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"
    if len(d) == 8 and d[0] == "1":
        return f"{d[:4]}-{d[4:]}"
    return (v or "").strip()


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS partner_addrs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            name TEXT DEFAULT '',
            postcode TEXT DEFAULT '',
            address TEXT NOT NULL,
            receiver TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            is_default INTEGER DEFAULT 0,
            sort INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_partner_addrs ON partner_addrs(partner_id, sort);

        CREATE TABLE IF NOT EXISTS partner_banks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            bank TEXT NOT NULL,
            account_no TEXT NOT NULL,
            holder TEXT DEFAULT '',
            is_default INTEGER DEFAULT 0,
            sort INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_partner_banks ON partner_banks(partner_id, sort);

        CREATE TABLE IF NOT EXISTS partner_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            kind TEXT NOT NULL CHECK(kind IN ('bizreg','bankbook','contract','etc')),
            file TEXT NOT NULL,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_partner_files ON partner_files(partner_id);

        CREATE TABLE IF NOT EXISTS partner_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            field TEXT NOT NULL,
            old TEXT DEFAULT '',
            new TEXT DEFAULT '',
            user_id INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_partner_history ON partner_history(partner_id, id);
    """)

    def add(table, cols):
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    add("partners", (
        ("kind", "TEXT DEFAULT 'general'"),
        ("reg_kind", "TEXT DEFAULT 'biz'"),
        ("biz_status", "TEXT DEFAULT 'normal'"),
        ("biz_checked_at", "TEXT DEFAULT ''"),
        ("trade_status", "TEXT DEFAULT 'active'"),
        ("postcode", "TEXT DEFAULT ''"),
        ("pay_terms", "TEXT DEFAULT ''"),
        ("pay_days", "INTEGER DEFAULT 0"),
        ("sub_rep_id", "INTEGER REFERENCES users(id)"),
        ("merged_into", "INTEGER REFERENCES partners(id)"),
    ))
    add("partner_contacts", (
        ("roles", "TEXT DEFAULT ''"),
        ("fax", "TEXT DEFAULT ''"),
        ("birthday", "TEXT DEFAULT ''"),
        ("memo", "TEXT DEFAULT ''"),
        ("is_primary", "INTEGER DEFAULT 0"),
        ("is_active", "INTEGER DEFAULT 1"),
    ))
    for table in ("crm_activities", "quotations", "sales_orders", "purchase_orders", "shipments", "tax_invoices"):
        add(table, (("contact_id", "INTEGER REFERENCES partner_contacts(id)"),))
    for table in ("quotations", "sales_orders", "shipments"):
        add(table, (("ship_to", "TEXT DEFAULT ''"),))
    add("client_companies", (("partner_alerts", "TEXT DEFAULT ''"),))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_crm_acts_contact ON crm_activities(contact_id)")

    conn.execute("UPDATE partner_contacts SET roles='tax' WHERE is_invoice=1 AND roles=''")
    conn.execute("""
        UPDATE partner_contacts SET is_primary=1
        WHERE id IN (SELECT MIN(id) FROM partner_contacts GROUP BY partner_id)
          AND partner_id NOT IN (SELECT partner_id FROM partner_contacts WHERE is_primary=1)
    """)
    conn.execute("""
        INSERT INTO partner_banks (company_id, partner_id, bank, account_no, holder, is_default)
        SELECT company_id, id, COALESCE(bank_name, ''), bank_account, COALESCE(bank_holder, ''), 1
        FROM partners
        WHERE COALESCE(bank_account, '') != '' AND id NOT IN (SELECT partner_id FROM partner_banks)
    """)
    # 13자리 등록번호는 주민번호로 분류. 마스킹 대상
    conn.execute("""
        UPDATE partners SET reg_kind='rrn'
        WHERE reg_kind='biz' AND LENGTH(REPLACE(REPLACE(biz_no, '-', ''), ' ', ''))=13
    """)

    for table, cols in (("partners", ("phone", "fax")), ("partner_contacts", ("phone", "mobile"))):
        for r in conn.execute(f"SELECT id, {', '.join(cols)} FROM {table}").fetchall():
            vals = [fmt_phone(r[c]) for c in cols]
            if vals != [r[c] for c in cols]:
                conn.execute(f"UPDATE {table} SET {', '.join(c + '=?' for c in cols)} WHERE id=?", (*vals, r["id"]))

# 거래처 담당자 다건, 담당사원, 계좌, 거래처별 단가, 고객등급과 영업관리(잠재고객, 영업기회, 영업활동)


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS partner_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            name TEXT NOT NULL,
            dept TEXT DEFAULT '',
            position TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            mobile TEXT DEFAULT '',
            email TEXT DEFAULT '',
            is_invoice INTEGER DEFAULT 0,
            sort INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_partner_contacts ON partner_contacts(partner_id, sort);

        CREATE TABLE IF NOT EXISTS partner_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            item_id INTEGER NOT NULL REFERENCES items(id),
            kind TEXT NOT NULL CHECK(kind IN ('sale','buy')),
            price INTEGER NOT NULL,
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(partner_id, item_id, kind)
        );

        CREATE TABLE IF NOT EXISTS partner_grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            min_sales INTEGER NOT NULL DEFAULT 0,
            UNIQUE(company_id, name)
        );

        CREATE TABLE IF NOT EXISTS crm_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            contact_name TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            biz_no TEXT DEFAULT '',
            address TEXT DEFAULT '',
            source TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new'
                CHECK(status IN ('new','contact','qualified','converted','lost')),
            rep_id INTEGER REFERENCES users(id),
            partner_id INTEGER REFERENCES partners(id),
            notes TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_crm_leads ON crm_leads(company_id, status);

        CREATE TABLE IF NOT EXISTS crm_opps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            partner_id INTEGER REFERENCES partners(id),
            lead_id INTEGER REFERENCES crm_leads(id),
            stage TEXT NOT NULL DEFAULT 'found'
                CHECK(stage IN ('found','proposal','nego','won','lost')),
            amount INTEGER NOT NULL DEFAULT 0,
            close_date TEXT DEFAULT '',
            rep_id INTEGER REFERENCES users(id),
            quote_id INTEGER REFERENCES quotations(id),
            lost_reason TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            closed_at TEXT DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_crm_opps ON crm_opps(company_id, stage);

        CREATE TABLE IF NOT EXISTS crm_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            partner_id INTEGER REFERENCES partners(id),
            lead_id INTEGER REFERENCES crm_leads(id),
            opp_id INTEGER REFERENCES crm_opps(id),
            kind TEXT NOT NULL DEFAULT 'call' CHECK(kind IN ('call','visit','meeting','email','etc')),
            act_date TEXT NOT NULL,
            subject TEXT NOT NULL,
            content TEXT DEFAULT '',
            rep_id INTEGER REFERENCES users(id),
            next_date TEXT DEFAULT '',
            next_action TEXT DEFAULT '',
            next_done INTEGER DEFAULT 0,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_crm_acts ON crm_activities(company_id, act_date);
        CREATE INDEX IF NOT EXISTS idx_crm_acts_partner ON crm_activities(partner_id);
    """)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(partners)")}
    for name, ddl in (
        ("rep_id", "INTEGER REFERENCES users(id)"),
        ("bank_name", "TEXT DEFAULT ''"),
        ("bank_account", "TEXT DEFAULT ''"),
        ("bank_holder", "TEXT DEFAULT ''"),
        ("grade_id", "INTEGER REFERENCES partner_grades(id)"),
        ("grade_fixed", "INTEGER DEFAULT 0"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE partners ADD COLUMN {name} {ddl}")

    # 기존 단일 담당자는 첫 담당자로 이관. partners.contact_* 컬럼은 이후 미사용
    conn.execute("""
        INSERT INTO partner_contacts (company_id, partner_id, name, phone, email, sort)
        SELECT company_id, id, contact_name, COALESCE(contact_phone, ''), COALESCE(contact_email, ''), 0
        FROM partners
        WHERE COALESCE(contact_name, '') != ''
          AND id NOT IN (SELECT partner_id FROM partner_contacts)
    """)

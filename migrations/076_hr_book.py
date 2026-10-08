# 급여 대행 위탁 여부 컬럼 추가, pay_items를 book(0=원 내부 포함) 기준으로 재구성.
# book 0은 client_companies에 행이 없음. 기존 FK로는 company_id=0 저장 불가. FK 제거


def up(conn):
    conn.execute("ALTER TABLE client_companies ADD COLUMN payroll_delegated INTEGER DEFAULT 0")

    conn.execute("""
        CREATE TABLE pay_items_076_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL DEFAULT 0,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT '지급' CHECK(kind IN ('지급','공제')),
            taxable INTEGER NOT NULL DEFAULT 1,
            tax_free_code TEXT DEFAULT '',
            tax_free_limit INTEGER DEFAULT 0,
            ordinary INTEGER NOT NULL DEFAULT 0,
            avg_wage INTEGER NOT NULL DEFAULT 1,
            bonus INTEGER NOT NULL DEFAULT 0,
            sort INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(company_id, code)
        )
    """)
    cols = (
        "id, company_id, code, name, kind, taxable, tax_free_code, tax_free_limit, "
        "ordinary, avg_wage, bonus, sort, active, created_at"
    )
    conn.execute(f"INSERT INTO pay_items_076_new ({cols}) SELECT {cols} FROM pay_items")
    conn.execute("DROP TABLE pay_items")
    conn.execute("ALTER TABLE pay_items_076_new RENAME TO pay_items")

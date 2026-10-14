# 거래처그룹, 단가그룹, 여신, 추가항목. 여신 체크 방식은 회사 단위(off/warn/block)


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS partner_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(company_id, name)
        );
        CREATE TABLE IF NOT EXISTS price_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            rate REAL NOT NULL DEFAULT 0,
            UNIQUE(company_id, name)
        );
        CREATE TABLE IF NOT EXISTS partner_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'text' CHECK(kind IN ('text','num')),
            sort INTEGER NOT NULL DEFAULT 0
        );
    """)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(partners)")}
    for name, ddl in (
        ("group_id", "INTEGER REFERENCES partner_groups(id)"),
        ("sale_pg_id", "INTEGER REFERENCES price_groups(id)"),
        ("buy_pg_id", "INTEGER REFERENCES price_groups(id)"),
        ("credit_limit", "INTEGER DEFAULT 0"),
        ("credit_days", "INTEGER DEFAULT 0"),
        ("extra", "TEXT DEFAULT '{}'"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE partners ADD COLUMN {name} {ddl}")

    cols = {r[1] for r in conn.execute("PRAGMA table_info(client_companies)")}
    for name in ("credit_limit_mode", "credit_days_mode"):
        if name not in cols:
            conn.execute(f"ALTER TABLE client_companies ADD COLUMN {name} TEXT DEFAULT 'off'")

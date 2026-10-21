# 부서 마스터. 전표/고정자산/근로자에 흩어진 부서 문자열을 장부별로 모아 코드 채번


def up(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS depts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            sort INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(company_id, code),
            UNIQUE(company_id, name)
        );
        CREATE INDEX IF NOT EXISTS idx_depts_book ON depts(company_id, is_active);
    """)

    by_book = {}
    for r in conn.execute(
        "SELECT COALESCE(company_id, 0) AS book, dept FROM employees WHERE TRIM(COALESCE(dept, '')) != ''"
    ):
        by_book.setdefault(r["book"], set()).add(r["dept"].strip())
    for r in conn.execute(
        "SELECT company_id AS book, dept FROM fixed_assets WHERE TRIM(COALESCE(dept, '')) != ''"
    ):
        by_book.setdefault(r["book"], set()).add(r["dept"].strip())
    for r in conn.execute(
        """SELECT d.company_id AS book, sl.dept AS dept FROM slip_lines sl
           JOIN erp_docs d ON sl.doc_id = d.id WHERE TRIM(COALESCE(sl.dept, '')) != ''"""
    ):
        by_book.setdefault(r["book"], set()).add(r["dept"].strip())

    for book, names in by_book.items():
        for i, name in enumerate(sorted(names), 1):
            conn.execute("INSERT INTO depts (company_id, code, name, sort) VALUES (?,?,?,?)",
                        (book, f"{i:03d}", name, i))

# 급여항목(pay_items) 도입. payslips의 고정 컬럼(base_salary/overtime_pay/
# disability_allowance/meal_allowance)을 payslip_items로 이관 후 컬럼 제거
# 확정된 명세서도 포함해 전부 백필. 지급합계가 gross_pay와 다르면 중단

DEFAULT_ITEMS = [
    # code, name, kind, taxable, tax_free_code, tax_free_limit, ordinary, avg_wage, bonus, sort
    ("BASE", "기본급", "지급", 1, "", 0, 1, 1, 0, 10),
    ("OT", "연장근로수당", "지급", 1, "", 0, 0, 1, 0, 20),
    ("NIGHT", "야간근로수당", "지급", 1, "", 0, 0, 1, 0, 30),
    ("HOLIDAY", "휴일근로수당", "지급", 1, "", 0, 0, 1, 0, 40),
    ("DISABLE", "장애인 근로지원금", "지급", 1, "", 0, 0, 1, 0, 50),
    ("MEAL", "식대", "지급", 1, "P01", 200000, 0, 1, 0, 60),
    ("BONUS", "상여금", "지급", 1, "", 0, 0, 0, 1, 70),
    ("ANNUAL", "연차수당", "지급", 1, "", 0, 0, 0, 1, 80),
]

OLD_COLS = ("base_salary", "overtime_pay", "disability_allowance", "meal_allowance")
OLD_COL_CODE = {
    "base_salary": "BASE",
    "overtime_pay": "OT",
    "disability_allowance": "DISABLE",
    "meal_allowance": "MEAL",
}

NEW_PAYSLIP_COLS = (
    "id", "employee_id", "pay_year", "pay_month", "gross_pay",
    "income_tax", "resident_tax", "national_pension", "health_insurance",
    "employment_insurance", "total_deduction", "net_pay", "pay_date",
    "created_at", "status", "long_care",
    "employer_pension", "employer_health", "employer_employment", "employer_accident",
)


def _create_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pay_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES client_companies(id),
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payslip_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payslip_id INTEGER NOT NULL REFERENCES payslips(id),
            item_id INTEGER NOT NULL REFERENCES pay_items(id),
            amount INTEGER NOT NULL DEFAULT 0,
            overridden INTEGER NOT NULL DEFAULT 0,
            UNIQUE(payslip_id, item_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payslip_items_payslip ON payslip_items(payslip_id)")


def _seed_default_items(conn):
    company_ids = [r[0] for r in conn.execute("SELECT id FROM client_companies")]
    for cid in company_ids:
        cnt = conn.execute("SELECT COUNT(*) FROM pay_items WHERE company_id=?", (cid,)).fetchone()[0]
        if cnt:
            continue
        for code, name, kind, taxable, tf_code, tf_limit, ordinary, avg_wage, bonus, sort in DEFAULT_ITEMS:
            conn.execute(
                """INSERT INTO pay_items (company_id, code, name, kind, taxable, tax_free_code,
                       tax_free_limit, ordinary, avg_wage, bonus, sort)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, code, name, kind, taxable, tf_code, tf_limit, ordinary, avg_wage, bonus, sort),
            )


def _backfill_payslip_items(conn):
    rows = conn.execute("""
        SELECT p.id, p.base_salary, p.overtime_pay, p.disability_allowance, p.meal_allowance,
               e.company_id
        FROM payslips p
        JOIN employees e ON e.id = p.employee_id
    """).fetchall()

    item_cache = {}

    def item_id_for(company_id, code):
        key = (company_id, code)
        if key not in item_cache:
            row = conn.execute(
                "SELECT id FROM pay_items WHERE company_id=? AND code=?", (company_id, code)
            ).fetchone()
            item_cache[key] = row[0] if row else None
        return item_cache[key]

    for r in rows:
        payslip_id, company_id = r["id"], r["company_id"]
        for col in OLD_COLS:
            amount = r[col]
            if not amount:
                continue
            item_id = item_id_for(company_id, OLD_COL_CODE[col])
            if item_id is None:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO payslip_items (payslip_id, item_id, amount) VALUES (?,?,?)",
                (payslip_id, item_id, amount),
            )


def _verify_backfill(conn):
    rows = conn.execute("SELECT id, gross_pay FROM payslips").fetchall()
    for r in rows:
        total = conn.execute(
            """SELECT COALESCE(SUM(pi.amount),0) FROM payslip_items pi
               JOIN pay_items it ON it.id = pi.item_id
               WHERE pi.payslip_id=? AND it.kind='지급'""",
            (r["id"],),
        ).fetchone()[0]
        if total != r["gross_pay"]:
            raise RuntimeError(
                f"payslip {r['id']} 지급항목 합계({total})가 gross_pay({r['gross_pay']})와 일치하지 않습니다"
            )


def _rebuild_payslips(conn):
    # 기존 payslips를 RENAME하면 payslip_items FK도 함께 변경됨. 새 테이블 쪽을 RENAME
    conn.execute("""
        CREATE TABLE payslips_073_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            pay_year INTEGER NOT NULL,
            pay_month INTEGER NOT NULL,
            gross_pay INTEGER NOT NULL,
            income_tax INTEGER DEFAULT 0,
            resident_tax INTEGER DEFAULT 0,
            national_pension INTEGER DEFAULT 0,
            health_insurance INTEGER DEFAULT 0,
            employment_insurance INTEGER DEFAULT 0,
            total_deduction INTEGER NOT NULL,
            net_pay INTEGER NOT NULL,
            pay_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'confirmed',
            long_care INTEGER DEFAULT 0,
            employer_pension INTEGER DEFAULT 0,
            employer_health INTEGER DEFAULT 0,
            employer_employment INTEGER DEFAULT 0,
            employer_accident INTEGER DEFAULT 0,
            premium_rule TEXT DEFAULT '',
            UNIQUE(employee_id, pay_year, pay_month)
        )
    """)
    cols = ", ".join(NEW_PAYSLIP_COLS)
    conn.execute(f"INSERT INTO payslips_073_new ({cols}) SELECT {cols} FROM payslips")
    conn.execute("DROP TABLE payslips")
    conn.execute("ALTER TABLE payslips_073_new RENAME TO payslips")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payslips_period ON payslips(pay_year, pay_month)")


def up(conn):
    # 앞 마이그레이션이 foreign_keys를 켜두면 DROP TABLE payslips가 실패
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        _create_tables(conn)
        _seed_default_items(conn)
        _backfill_payslip_items(conn)
        _verify_backfill(conn)
        _rebuild_payslips(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

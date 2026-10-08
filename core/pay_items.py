# code, name, kind, taxable, tax_free_code, tax_free_limit, ordinary, avg_wage, bonus, sort
DEFAULT_ITEMS = [
    ("BASE", "기본급", "지급", 1, "", 0, 1, 1, 0, 10),
    ("OT", "연장근로수당", "지급", 1, "", 0, 0, 1, 0, 20),
    ("NIGHT", "야간근로수당", "지급", 1, "", 0, 0, 1, 0, 30),
    ("HOLIDAY", "휴일근로수당", "지급", 1, "", 0, 0, 1, 0, 40),
    ("DISABLE", "장애인 근로지원금", "지급", 1, "", 0, 0, 1, 0, 50),
    ("MEAL", "식대", "지급", 1, "P01", 200000, 0, 1, 0, 60),
    ("BONUS", "상여금", "지급", 1, "", 0, 0, 0, 1, 70),
    ("ANNUAL", "연차수당", "지급", 1, "", 0, 0, 0, 1, 80),
]

PREMIUM_CODES = ("OT", "NIGHT", "HOLIDAY")


def ensure_default_items(conn, company_id):
    cnt = conn.execute("SELECT COUNT(*) FROM pay_items WHERE company_id=?", (company_id,)).fetchone()[0]
    if cnt:
        return
    for code, name, kind, taxable, tf_code, tf_limit, ordinary, avg_wage, bonus, sort in DEFAULT_ITEMS:
        conn.execute(
            """INSERT INTO pay_items (company_id, code, name, kind, taxable, tax_free_code,
                   tax_free_limit, ordinary, avg_wage, bonus, sort)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (company_id, code, name, kind, taxable, tf_code, tf_limit, ordinary, avg_wage, bonus, sort),
        )
    # GET 요청에서도 지연 시딩이 바로 반영되도록 즉시 커밋 (다음 호출의 재시딩 방지)
    conn.commit()


def get_items(conn, company_id, active_only=True):
    ensure_default_items(conn, company_id)
    sql = "SELECT * FROM pay_items WHERE company_id=?"
    if active_only:
        sql += " AND active=1"
    sql += " ORDER BY sort, id"
    return [dict(r) for r in conn.execute(sql, (company_id,)).fetchall()]


def get_item(conn, company_id, item_id):
    row = conn.execute(
        "SELECT * FROM pay_items WHERE id=? AND company_id=?", (item_id, company_id)
    ).fetchone()
    return dict(row) if row else None


def item_in_use(conn, item_id):
    return conn.execute(
        "SELECT 1 FROM payslip_items WHERE item_id=? LIMIT 1", (item_id,)
    ).fetchone() is not None


def next_sort(conn, company_id):
    row = conn.execute("SELECT MAX(sort) FROM pay_items WHERE company_id=?", (company_id,)).fetchone()
    return (row[0] or 0) + 10

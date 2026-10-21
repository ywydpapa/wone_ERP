# 결재 통합. 휴가/편의지원을 전자결재 문서에 연결하고 레거시 approvals 제거
# approval_presets.form_key는 CHECK 제약 없음. po, leave, accom 키 그대로 사용
import json
from datetime import date


def _approver(conn, book, form_key):
    row = conn.execute(
        "SELECT lines FROM approval_presets WHERE company_id=? AND form_key=?", (book, form_key)
    ).fetchone()
    lines = [(p["role"], p["user"]) for p in json.loads(row["lines"])] if row else []
    if any(r in ("결재", "합의") for r, _ in lines):
        return lines
    hr = conn.execute(
        "SELECT user_id FROM client_users WHERE company_id=? AND client_role IN ('all', 'hr') ORDER BY user_id LIMIT 1",
        (book,),
    ).fetchone()
    return [("결재", hr["user_id"])] if hr else []


def _attach(conn, table, doc_type, form_key, title_sql):
    rows = conn.execute(f"""
        SELECT r.id, e.user_id, e.company_id, u.name, {title_sql} AS title FROM {table} r
        JOIN employees e ON e.id = r.employee_id JOIN users u ON u.id = e.user_id
        WHERE r.status = 'pending' AND r.doc_id IS NULL
    """).fetchall()
    for r in rows:
        book = r["company_id"] or 0
        lines = _approver(conn, book, form_key)
        # 결재자 없는 회사는 문서 없이 둠. 근로자 취소 후 재신청 대상
        if not lines:
            continue
        doc_id = conn.execute(
            "INSERT INTO erp_docs (user_id, doc_type, title, content, status, company_id) VALUES (?,?,?,'','wait',?)",
            (r["user_id"], doc_type, r["title"], book),
        ).lastrowid
        conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (f"GW-{date.today().year}-{doc_id:04d}", doc_id))
        conn.execute(
            "INSERT INTO approval_lines (doc_id, step, approver_id, role, status, acted_at) "
            "VALUES (?,0,?,'기안','approved',datetime('now','localtime'))",
            (doc_id, r["user_id"]),
        )
        for step, (role, uid) in enumerate(lines, 1):
            conn.execute(
                "INSERT INTO approval_lines (doc_id, step, approver_id, role) VALUES (?,?,?,?)",
                (doc_id, step, uid, role),
            )
        conn.execute(
            "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,'기안','결재 통합 이관')",
            (doc_id, r["user_id"], r["name"]),
        )
        conn.execute(f"UPDATE {table} SET doc_id=? WHERE id=?", (doc_id, r["id"]))


def up(conn):
    conn.execute("ALTER TABLE leave_requests ADD COLUMN doc_id INTEGER REFERENCES erp_docs(id)")
    conn.execute("ALTER TABLE accommodation_requests ADD COLUMN doc_id INTEGER REFERENCES erp_docs(id)")
    conn.execute("ALTER TABLE purchase_requisitions ADD COLUMN approved_by INTEGER REFERENCES users(id)")
    conn.execute("ALTER TABLE purchase_requisitions ADD COLUMN approved_at TEXT")
    conn.execute("ALTER TABLE purchase_requisitions ADD COLUMN reject_reason TEXT")

    _attach(conn, "leave_requests", "leave", "leave",
            "'휴가신청 ' || e.name || ' ' || r.start_date || '~' || r.end_date")
    _attach(conn, "accommodation_requests", "accom", "accom", "'편의지원 ' || e.name || ' ' || r.title")

    # approvals에 걸려 있던 결재대기 발주는 결재 문서가 없음. 임시저장으로 되돌려 재요청
    conn.execute(
        "UPDATE purchase_orders SET status='draft', updated_at=datetime('now','localtime') "
        "WHERE status='pending_approval' AND doc_id IS NULL"
    )
    conn.execute("DROP TABLE IF EXISTS approvals")

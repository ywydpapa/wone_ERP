import json


def get_approval(conn, doc_type, doc_id, step=1):
    return conn.execute(
        "SELECT * FROM approvals WHERE doc_type=? AND doc_id=? AND step=? ORDER BY id DESC LIMIT 1",
        (doc_type, doc_id, step)
    ).fetchone()


def get_approvals(conn, doc_type, doc_id):
    return conn.execute(
        "SELECT * FROM approvals WHERE doc_type=? AND doc_id=? ORDER BY step",
        (doc_type, doc_id)
    ).fetchall()


def create_approval(conn, doc_type, doc_id, step=1, approver_id=None):
    conn.execute(
        """INSERT INTO approvals (doc_type, doc_id, step, approver_id)
           VALUES (?, ?, ?, ?)""",
        (doc_type, doc_id, step, approver_id)
    )
    conn.commit()


def approve(conn, doc_type, doc_id, approver_id, step=1):
    conn.execute(
        """UPDATE approvals SET status='approved', approver_id=?, acted_at=datetime('now','localtime')
           WHERE doc_type=? AND doc_id=? AND step=? AND status='pending'""",
        (approver_id, doc_type, doc_id, step)
    )
    conn.commit()


def reject(conn, doc_type, doc_id, approver_id, comment='', step=1):
    conn.execute(
        """UPDATE approvals SET status='rejected', approver_id=?, comment=?, acted_at=datetime('now','localtime')
           WHERE doc_type=? AND doc_id=? AND step=? AND status='pending'""",
        (approver_id, comment, doc_type, doc_id, step)
    )
    conn.commit()


# 전자결재 결재선. 검토/승인은 전표 2단 결재선의 기존 역할명
ACTING = ("검토", "승인", "결재", "합의")
LINE_ROLES = ("결재", "합의", "후결", "참조")
_ACTING_SQL = "('검토','승인','결재','합의')"


def current_line(conn, doc_id):
    return conn.execute(
        f"SELECT * FROM approval_lines WHERE doc_id=? AND status='pending' AND role IN {_ACTING_SQL} "
        "ORDER BY step LIMIT 1",
        (doc_id,)
    ).fetchone()


def parse_lines(form, users):
    roles, uids = form.getlist("line_role"), form.getlist("line_user")
    lines = []
    for role, uid in zip(roles, uids):
        if not uid:
            continue
        if role not in LINE_ROLES or not uid.isdigit() or int(uid) not in users:
            return None, "결재선을 확인해 주세요."
        lines.append((role, int(uid)))
    if not any(r in ("결재", "합의") for r, _ in lines):
        return None, "결재자를 1명 이상 지정해 주세요."
    if len({uid for _, uid in lines}) != len(lines):
        return None, "결재선에 같은 사람이 중복되어 있습니다."
    # 결재/합의는 입력 순서대로, 후결은 그 뒤, 참조는 최후순
    order = {"결재": 0, "합의": 0, "후결": 1, "참조": 2}
    return sorted(lines, key=lambda x: order[x[0]]), None


def insert_lines(conn, doc_id, uid, lines, is_draft, now):
    conn.execute(
        "INSERT INTO approval_lines (doc_id, step, approver_id, role, status, acted_at) VALUES (?,0,?,'기안',?,?)",
        (doc_id, uid, "pending" if is_draft else "approved", None if is_draft else now)
    )
    for step, (role, approver) in enumerate(lines, 1):
        conn.execute(
            "INSERT INTO approval_lines (doc_id, step, approver_id, role) VALUES (?,?,?,?)",
            (doc_id, step, approver, role)
        )


def box_sql(box, uid):
    # 문서함별 erp_docs 조건. 결재대기는 내 앞 순번이 모두 끝난 문서만
    mine_now = (
        f"SELECT al.doc_id FROM approval_lines al WHERE al.approver_id=? AND al.status='pending' AND al.role IN {_ACTING_SQL} "
        f"AND NOT EXISTS (SELECT 1 FROM approval_lines p WHERE p.doc_id=al.doc_id AND p.status='pending' "
        f"AND p.role IN {_ACTING_SQL} AND p.step < al.step)"
    )
    if box == "wait":
        return (
            f"((id IN ({mine_now}) AND status IN ('wait','progress','urgent')) "
            "OR (status='done' AND id IN (SELECT doc_id FROM approval_lines WHERE approver_id=? AND role='후결' AND status='pending')))",
            [uid, uid],
        )
    if box == "upcoming":
        return (
            f"status IN ('wait','progress','urgent') AND id NOT IN ({mine_now}) AND id IN "
            f"(SELECT doc_id FROM approval_lines WHERE approver_id=? AND status='pending' AND role IN {_ACTING_SQL})",
            [uid, uid],
        )
    if box == "sent":
        return "user_id=? AND status IN ('wait','progress','urgent')", [uid]
    if box == "draft":
        return "user_id=? AND status='draft'", [uid]
    if box == "ref":
        return "status != 'draft' AND id IN (SELECT doc_id FROM approval_lines WHERE approver_id=? AND role='참조')", [uid]
    acted = (
        "(user_id=? OR id IN (SELECT doc_id FROM approval_lines WHERE approver_id=? AND step > 0 "
        "AND role != '참조' AND status IN ('approved','final','rejected')))"
    )
    status = "status='rejected'" if box == "rejected" else "status IN ('done','approved','resolved')"
    return f"{status} AND {acted}", [uid, uid]


def preset_lines(conn, book, form_key):
    row = conn.execute(
        "SELECT lines FROM approval_presets WHERE company_id=? AND form_key=?", (book, form_key)
    ).fetchone()
    return json.loads(row["lines"]) if row else []

import json

from core import audit, books
from core.attendance import apply_overtime
from core.erp_log import log_activity
from core.leave import approve_leave, reject_leave, done_cancel
from core.notification import create_bulk_notifications, create_notification
from core.tz import now_kst, today_kst


# 전자결재 결재선. 검토/승인은 전표 2단 결재선의 기존 역할명
ACTING = ("검토", "승인", "결재", "합의")
LINE_ROLES = ("결재", "합의", "후결", "참조")
_ACTING_SQL = "('검토','승인','결재','합의')"
OPEN = ("wait", "pending", "progress", "urgent")
LINE_STATUS = {"pending": "대기", "approved": "승인", "final": "전결", "rejected": "반려", "skipped": "생략"}


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


def pick_lines(conn, book, form_key, uid, pick, cands):
    # 회사 기본 결재선 우선. 없으면 화면에서 고른 1인 결재
    users = {x["id"] for x in books.book_users(conn, book)} - {uid}
    lines = [(p["role"], p["user"]) for p in preset_lines(conn, book, form_key) if p["user"] in users]
    if any(r in ("결재", "합의") for r, _ in lines):
        return lines
    if pick in {c["id"] for c in cands}:
        return [("결재", pick)]
    return None


def hr_approvers(conn, book):
    if not book:
        return books.book_users(conn, book)
    return [dict(r) for r in conn.execute(
        """SELECT u.id, u.name, u.dept, u.position FROM users u JOIN client_users cu ON cu.user_id = u.id
           WHERE cu.company_id=? AND cu.client_role IN ('all', 'hr') ORDER BY u.name""", (book,)
    )]


def doc_lines(conn, doc_id):
    rows = [dict(r) for r in conn.execute(
        """SELECT al.*, u.name AS user_name, u.position AS user_position, ab.name AS acted_by_name
           FROM approval_lines al
           LEFT JOIN users u ON u.id = al.approver_id
           LEFT JOIN users ab ON ab.id = al.acted_by
           WHERE al.doc_id=? AND al.step > 0 ORDER BY al.step""",
        (doc_id,)
    )]
    for r in rows:
        r["status_label"] = LINE_STATUS.get(r["status"], r["status"])
        r["is_deputy"] = bool(r["acted_by"] and r["acted_by"] != r["approver_id"])
    return rows


def open_doc(conn, u, book, doc_type, title, content, lines):
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    doc_id = conn.execute(
        "INSERT INTO erp_docs (user_id, doc_type, title, content, status, company_id) VALUES (?,?,?,?,'wait',?)",
        (u["id"], doc_type, title, content, book),
    ).lastrowid
    doc_number = f"GW-{now_kst().year}-{doc_id:04d}"
    conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, doc_id))
    insert_lines(conn, doc_id, u["id"], lines, False, now)
    conn.execute(
        "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
        (doc_id, u["id"], u["name"], "기안", ""),
    )
    audit.log(conn, u["id"], "doc_submit", "doc", doc_id, f"{doc_number} {title}", company_id=book)
    create_notification(conn, current_line(conn, doc_id)["approver_id"], "결재 요청", title, f"/erp_doc/{doc_id}")
    return doc_id


def is_deputy_for(conn, company_id, approver_id, uid, on_date=None):
    on_date = on_date or today_kst().isoformat()
    return bool(conn.execute(
        "SELECT 1 FROM approval_deputies WHERE company_id=? AND user_id=? AND deputy_id=? "
        "AND start_date<=? AND end_date>=?",
        (company_id, approver_id, uid, on_date, on_date)
    ).fetchone())


def my_line(conn, doc, uid):
    # 순번이 온 결재/합의 라인만. 기안자 본인은 대결 지정과 무관하게 자기 문서 결재 불가
    line = current_line(conn, doc["id"]) if doc["status"] in OPEN else None
    if not line:
        return None
    if line["approver_id"] == uid:
        return line
    if doc["user_id"] != uid and is_deputy_for(conn, doc["company_id"], line["approver_id"], uid):
        return line
    return None


def rest_lines(conn, doc_id, step):
    return [r["id"] for r in conn.execute(
        f"SELECT id FROM approval_lines WHERE doc_id=? AND status='pending' AND step > ? AND role IN {_ACTING_SQL}",
        (doc_id, step)
    )]


def act(conn, doc, line, u, comment="", final=False):
    doc_id = doc["id"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    rest = rest_lines(conn, doc_id, line["step"])
    final = bool(final and rest)
    status = "done" if final or not rest else "progress"
    conn.execute(
        "UPDATE approval_lines SET status=?, comment=?, acted_at=?, acted_by=? WHERE id=?",
        ("final" if final else "approved", comment, now, u["id"], line["id"])
    )
    if final:
        conn.executemany("UPDATE approval_lines SET status='skipped' WHERE id=?", [(i,) for i in rest])
    conn.execute("UPDATE erp_docs SET status=?, approved_by=?, approved_at=? WHERE id=?",
                 (status, u["id"], now, doc_id))
    action = "전결" if final else "승인"
    if u["id"] != line["approver_id"]:
        action += "(대결)"
    conn.execute(
        "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
        (doc_id, u["id"], u["name"], action, comment)
    )
    audit.log(conn, u["id"], "doc_approve", "doc", doc_id, f"{doc['doc_number']} {doc['title']}", company_id=doc["company_id"])
    if status == "progress":
        create_notification(conn, current_line(conn, doc_id)["approver_id"], "결재 요청", doc["title"], f"/erp_doc/{doc_id}")
        return status
    if doc["doc_type"] in ON_DONE:
        ON_DONE[doc["doc_type"]](conn, doc, u, now)
    create_notification(conn, doc["user_id"], "결재 완료", doc["title"], f"/erp_doc/{doc_id}")
    ref_ids = [r["approver_id"] for r in conn.execute(
        "SELECT approver_id FROM approval_lines WHERE doc_id=? AND role='참조'", (doc_id,)
    )]
    if ref_ids:
        create_bulk_notifications(conn, ref_ids, "결재 완료(참조)", doc["title"], f"/erp_doc/{doc_id}")
    return status


def reject_doc(conn, doc, line, u, comment):
    doc_id = doc["id"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE approval_lines SET status='rejected', comment=?, acted_at=?, acted_by=? WHERE id=?",
        (comment, now, u["id"], line["id"])
    )
    conn.execute(
        "UPDATE erp_docs SET status='rejected', reject_reason=?, approved_by=?, approved_at=? WHERE id=?",
        (comment, u["id"], now, doc_id)
    )
    action = "반려(대결)" if u["id"] != line["approver_id"] else "반려"
    conn.execute(
        "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
        (doc_id, u["id"], u["name"], action, comment)
    )
    audit.log(conn, u["id"], "doc_reject", "doc", doc_id, f"{doc['doc_number']} {doc['title']}", company_id=doc["company_id"])
    if doc["doc_type"] in ON_REJECT:
        ON_REJECT[doc["doc_type"]](conn, doc, u, now, comment)
    create_notification(conn, doc["user_id"], "결재 반려", doc["title"], f"/erp_doc/{doc_id}")


def reopen_doc(conn, doc, u):
    # 반려 이력 보존 위해 같은 doc_id로 임시저장 복귀
    if doc["status"] != "rejected":
        return False
    conn.execute(
        "UPDATE erp_docs SET status='draft', approved_by=NULL, approved_at=NULL, reject_reason=NULL WHERE id=?",
        (doc["id"],)
    )
    conn.execute(
        "UPDATE approval_lines SET status='pending', comment=NULL, acted_at=NULL, acted_by=NULL "
        "WHERE doc_id=? AND step > 0",
        (doc["id"],)
    )
    conn.execute(
        "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
        (doc["id"], u["id"], u["name"], "재기안", "반려 문서 수정 후 재상신")
    )
    audit.log(conn, u["id"], "doc_reopen", "doc", doc["id"], f"{doc['doc_number']} {doc['title']}", company_id=doc["company_id"])
    return True


def withdraw_doc(conn, doc, u, status="draft"):
    # 첫 결재자가 처리하기 전까지만 회수 가능
    acted = conn.execute(
        "SELECT 1 FROM approval_lines WHERE doc_id=? AND step > 0 AND status != 'pending' AND role != '참조'", (doc["id"],)
    ).fetchone()
    if doc["status"] not in OPEN or acted:
        return False
    conn.execute("UPDATE erp_docs SET status=? WHERE id=?", (status, doc["id"]))
    conn.execute(
        "UPDATE approval_lines SET status='pending', comment=NULL, acted_at=NULL WHERE doc_id=?",
        (doc["id"],)
    )
    conn.execute(
        "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
        (doc["id"], u["id"], u["name"], "철회", "기안자 철회")
    )
    audit.log(conn, u["id"], "doc_withdraw", "doc", doc["id"], f"{doc['doc_number']} {doc['title']}", company_id=doc["company_id"])
    return True


def _post_slip(conn, doc, u, now):
    conn.execute("UPDATE erp_docs SET posted_at=? WHERE id=?", (now, doc["id"]))


def _po_done(conn, doc, u, now):
    po = conn.execute("SELECT id, po_number, company_id FROM purchase_orders WHERE doc_id=?", (doc["id"],)).fetchone()
    # 통합 전 그룹웨어 발주 양식 문서는 연결된 발주 없음
    if not po:
        return
    conn.execute("UPDATE purchase_orders SET status='confirmed', updated_at=? WHERE id=?", (now, po["id"]))
    log_activity(conn, u["id"], "approve", "purchase", po["id"], po["po_number"], f"발주 승인 {po['po_number']}")
    audit.log(conn, u["id"], "po_approve", "po", po["id"], po["po_number"], company_id=po["company_id"])


def _po_reject(conn, doc, u, now, comment):
    po = conn.execute("SELECT id, po_number, company_id FROM purchase_orders WHERE doc_id=?", (doc["id"],)).fetchone()
    if not po:
        return
    conn.execute("UPDATE purchase_orders SET status='draft', updated_at=? WHERE id=?", (now, po["id"]))
    log_activity(conn, u["id"], "reject", "purchase", po["id"], po["po_number"], f"발주 반려 {po['po_number']}")
    audit.log(conn, u["id"], "po_reject", "po", po["id"], po["po_number"], company_id=po["company_id"])


def _accom_set(conn, doc, u, now, status, note=None):
    conn.execute(
        "UPDATE accommodation_requests SET status=?, reviewed_by=?, reviewed_at=?, review_notes=? WHERE doc_id=?",
        (status, u["id"], now, note, doc["id"])
    )


def _pr_done(conn, doc, u, now):
    pr = conn.execute(
        "SELECT id, pr_number, company_id FROM purchase_requisitions WHERE doc_id=?", (doc["id"],)
    ).fetchone()
    if not pr:
        return
    conn.execute(
        "UPDATE purchase_requisitions SET status='approved', approved_by=?, approved_at=? WHERE id=?",
        (u["id"], now, pr["id"])
    )
    log_activity(conn, u["id"], "approve", "pr", pr["id"], pr["pr_number"], f"구매요청 승인 {pr['pr_number']}")
    audit.log(conn, u["id"], "pr_approve", "pr", pr["id"], pr["pr_number"], company_id=pr["company_id"])


def _pr_reject(conn, doc, u, now, comment):
    pr = conn.execute(
        "SELECT id, pr_number, company_id FROM purchase_requisitions WHERE doc_id=?", (doc["id"],)
    ).fetchone()
    if not pr:
        return
    conn.execute(
        "UPDATE purchase_requisitions SET status='rejected', approved_by=?, approved_at=?, reject_reason=? WHERE id=?",
        (u["id"], now, comment, pr["id"])
    )
    log_activity(conn, u["id"], "reject", "pr", pr["id"], pr["pr_number"], f"구매요청 반려 {pr['pr_number']}")
    audit.log(conn, u["id"], "pr_reject", "pr", pr["id"], pr["pr_number"], company_id=pr["company_id"])


def _overtime_done(conn, doc, u, now):
    extra = json.loads(doc["extra_fields"] or "{}")
    work_date = extra.get("work_date")
    mins = int(extra.get("ot_minutes") or 0)
    emp = conn.execute("SELECT id FROM employees WHERE user_id=?", (doc["user_id"],)).fetchone()
    # 양식 항목이 비어 있던 과거 문서는 반영 대상 없음
    if not work_date or mins <= 0 or not emp:
        return
    apply_overtime(conn, emp["id"], work_date, mins)
    audit.log(conn, u["id"], "overtime_approve", "attendance", emp["id"], f"{work_date} {mins}분",
              company_id=doc["company_id"])


ON_DONE = {
    "expense": _post_slip,
    "po": _po_done,
    "pr": _pr_done,
    "leave": approve_leave,
    "leave_cancel": done_cancel,
    "accom": lambda conn, doc, u, now: _accom_set(conn, doc, u, now, "approved"),
    "overtime": _overtime_done,
}
ON_REJECT = {
    "po": _po_reject,
    "pr": _pr_reject,
    "leave": reject_leave,
    "accom": lambda conn, doc, u, now, comment: _accom_set(conn, doc, u, now, "rejected", comment),
}

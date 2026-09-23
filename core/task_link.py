from core.constants import ERP_MODULE_LOG_MAP

# 전표-태스크 연결. 반출/격리/잠금의 공통 기반

def stamp_task(conn, request, user_id, module):
    task_id = request.session.get("erp_task_id")
    if not task_id:
        return None
    row = conn.execute(
        "SELECT t.erp_module, t.status FROM tasks t "
        "JOIN employees e ON t.assigned_to = e.id "
        "WHERE t.id = ? AND e.user_id = ?", (task_id, user_id)).fetchone()
    if not row or row["status"] in ("completed", "cancelled"):
        return None
    if module not in ERP_MODULE_LOG_MAP.get(row["erp_module"], []):
        return None
    return task_id


def task_locked(conn, task_id):
    if not task_id:
        return False
    row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return bool(row) and row["status"] == "completed"


def erp_scope(conn, user, alias):
    if user["role"] == "platform_staff":
        return "1=1", []
    return (f"({alias}.task_id IS NULL OR {alias}.task_id IN ("
            "SELECT t.id FROM tasks t "
            "JOIN work_requests wr ON t.work_request_id = wr.id "
            "JOIN employees e ON e.company_id = wr.company_id "
            "WHERE e.user_id = ?))", [user["id"]])

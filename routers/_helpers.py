import uuid
import pathlib
from starlette.responses import JSONResponse

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt", ".hwp", ".txt", ".zip"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024


async def save_upload(attachment, upload_dir="static/uploads/erp"):
    if not attachment or not attachment.filename:
        return ""
    ext = pathlib.Path(attachment.filename).suffix
    content_bytes = await attachment.read()
    if ext.lower() not in ALLOWED_EXTENSIONS:
        return JSONResponse({"error": "허용되지 않는 파일 형식입니다."}, status_code=400)
    if len(content_bytes) > MAX_UPLOAD_SIZE:
        return JSONResponse({"error": "파일 크기가 10MB를 초과합니다."}, status_code=413)
    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest = pathlib.Path(upload_dir)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / safe_name).write_bytes(content_bytes)
    return f"{attachment.filename}|{safe_name}"


def insert_approval_lines(conn, doc_id, uid, reviewer_id, approver_id, is_draft, now, uname, action_label):
    if is_draft:
        conn.execute(
            "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
            (doc_id, 0, uid, "기안", "pending")
        )
    else:
        conn.execute(
            "INSERT INTO approval_lines (doc_id, step, approver_id, role, status, acted_at) VALUES (?,?,?,?,?,?)",
            (doc_id, 0, uid, "기안", "approved", now)
        )
    conn.execute(
        "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
        (doc_id, 1, reviewer_id, "검토", "pending")
    )
    conn.execute(
        "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
        (doc_id, 2, approver_id, "승인", "pending")
    )
    conn.execute(
        "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
        (doc_id, uid, uname, action_label, "")
    )


def check_job_owner(conn, job_id, uid):
    owner = conn.execute("SELECT user_id FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not owner or owner["user_id"] != uid:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return None

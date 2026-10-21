import pathlib

from routers._helpers import save_upload

KINDS = ("계약서", "신분증", "통장", "자격", "기타")
# 신분증, 통장 사본 등 민감 서류이므로 문서/이미지만 허용. 확장자 위장 차단 위해 파일 시그니처 대조
SIGS = {".pdf": (b"%PDF",), ".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",)}
UPLOAD_DIR = "var/uploads/employee"


def list_files(conn, employee_id):
    return [dict(r) for r in conn.execute(
        """SELECT f.*, u.name AS uploaded_by_name FROM employee_files f
           LEFT JOIN users u ON u.id = f.uploaded_by
           WHERE f.employee_id=? ORDER BY f.id DESC""",
        (employee_id,),
    )]


async def save_file(conn, employee_id, company_id, kind, upload, uploaded_by):
    if kind not in KINDS:
        return None
    sigs = SIGS.get(pathlib.Path(upload.filename or "").suffix.lower())
    head = await upload.read(8)
    await upload.seek(0)
    if not sigs or not head.startswith(sigs):
        return None
    saved = await save_upload(upload, UPLOAD_DIR)
    if not saved or not isinstance(saved, str):
        return saved
    orig_name, safe_name = saved.split("|", 1)
    conn.execute(
        "INSERT INTO employee_files (company_id, employee_id, kind, name, path, uploaded_by) VALUES (?,?,?,?,?,?)",
        (company_id, employee_id, kind, orig_name, safe_name, uploaded_by),
    )
    return safe_name


def delete_file(conn, employee_id, file_id):
    row = conn.execute(
        "SELECT path FROM employee_files WHERE id=? AND employee_id=?", (file_id, employee_id)
    ).fetchone()
    if not row:
        return False
    (pathlib.Path(UPLOAD_DIR) / row["path"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM employee_files WHERE id=?", (file_id,))
    return True

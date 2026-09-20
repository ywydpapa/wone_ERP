import pathlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.deps import require_login, get_db

router = APIRouter()

BASE = pathlib.Path("var/uploads").resolve()
AREAS = {"erp", "deliverables", "jobs", "work_requests", "appeal", "leave", "certs"}


def _client_company(conn, uid):
    row = conn.execute("SELECT company_id FROM client_users WHERE user_id=?", (uid,)).fetchone()
    return row["company_id"] if row else None


def _worker_emp(conn, uid):
    row = conn.execute("SELECT id FROM employees WHERE user_id=?", (uid,)).fetchone()
    return row["id"] if row else None


def _owner_or_company(conn, row, user):
    if not row:
        return False
    if row["user_id"] == user["id"]:
        return True
    cid = _client_company(conn, user["id"])
    return bool(cid and cid == row["company_id"])


def _allowed(conn, area, name, user):
    if user["role"] == "platform_staff":
        return True
    uid = user["id"]

    if area == "erp":
        # 내부 ERP 증빙: 사내(비 client) 계정만
        return user["role"] != "client"

    if area == "deliverables":
        if user["role"] == "worker":
            emp = _worker_emp(conn, uid)
            return bool(conn.execute(
                "SELECT 1 FROM task_deliverables td JOIN tasks t ON td.task_id=t.id "
                "WHERE (td.file_path=? OR td.file_path LIKE '%|' || ?) "
                "AND (td.user_id=? OR t.assigned_to=?)",
                (name, name, uid, emp),
            ).fetchone())
        cid = _client_company(conn, uid)
        return bool(cid and conn.execute(
            "SELECT 1 FROM task_deliverables td "
            "JOIN tasks t ON td.task_id=t.id "
            "JOIN work_requests wr ON t.work_request_id=wr.id "
            "WHERE (td.file_path=? OR td.file_path LIKE '%|' || ?) AND wr.company_id=?",
            (name, name, cid),
        ).fetchone())

    if area == "work_requests":
        row = conn.execute(
            "SELECT wr.id, wr.company_id FROM work_request_attachments wa "
            "JOIN work_requests wr ON wa.request_id=wr.id "
            "WHERE wa.file_path=? OR wa.file_path LIKE '%|' || ?",
            (name, name),
        ).fetchone()
        if not row:
            return False
        cid = _client_company(conn, uid)
        if cid and cid == row["company_id"]:
            return True
        emp = _worker_emp(conn, uid)
        return bool(emp and conn.execute(
            "SELECT 1 FROM tasks WHERE work_request_id=? AND assigned_to=?",
            (row["id"], emp),
        ).fetchone())

    if area == "jobs":
        row = conn.execute(
            "SELECT j.user_id, e.company_id FROM jobs j "
            "LEFT JOIN employees e ON e.user_id=j.user_id "
            "WHERE j.attachment=? OR j.attachment LIKE '%|' || ?",
            (name, name),
        ).fetchone()
        return _owner_or_company(conn, row, user)

    if area == "appeal":
        row = conn.execute(
            "SELECT e.user_id, e.company_id FROM attendance a "
            "JOIN employees e ON a.employee_id=e.id "
            "WHERE a.appeal_file=? OR a.appeal_file LIKE '%|' || ?",
            (name, name),
        ).fetchone()
        return _owner_or_company(conn, row, user)

    if area == "leave":
        row = conn.execute(
            "SELECT e.user_id, e.company_id FROM leave_requests lr "
            "JOIN employees e ON lr.employee_id=e.id "
            "WHERE lr.attachment=? OR lr.attachment LIKE '%|' || ?",
            (name, name),
        ).fetchone()
        return _owner_or_company(conn, row, user)

    if area == "certs":
        row = conn.execute(
            "SELECT user_id, company_id FROM employees WHERE disability_cert_file LIKE '%/' || ?",
            (name,),
        ).fetchone()
        return _owner_or_company(conn, row, user)

    return False


@router.get("/files/{area}/{name}")
async def serve_file(area: str, name: str, user=Depends(require_login), conn=Depends(get_db)):
    if area not in AREAS or name.startswith("."):
        raise HTTPException(status_code=404)
    path = (BASE / area / name).resolve()
    if not str(path).startswith(str(BASE)) or not path.is_file():
        raise HTTPException(status_code=404)
    if not _allowed(conn, area, name, user):
        raise HTTPException(status_code=404)
    return FileResponse(path)

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core import audit, perms
from core.books import book_of
from core.deps import get_db, require_login, templates
from core.tz import now_kst

router = APIRouter()

PER_PAGE = 20

ROLE_LABELS = {"platform_staff": "운영", "client": "고객사", "worker": "근로자", "employee": "직원"}
CLIENT_ROLE_LABELS = {"all": "전체", "hr": "인사"}
LEVEL_LABELS = {"none": "없음", "view": "조회", "edit": "편집"}


def require_user_admin(request: Request, conn=Depends(get_db)):
    u = require_login(request)
    if u["role"] not in ("platform_staff", "client"):
        raise HTTPException(status_code=403)
    if u["role"] == "client":
        company = book_of(conn, u)
        if company is None:
            raise HTTPException(status_code=403)
        u = {**u, "company": company}
    return u


def _scope_where(u):
    if u["role"] == "platform_staff":
        return "", []
    return (
        " AND u.id IN (SELECT user_id FROM client_users WHERE company_id=? "
        "UNION SELECT user_id FROM employees WHERE company_id=?)",
        [u["company"], u["company"]],
    )


def _in_scope(conn, u, uid):
    where, params = _scope_where(u)
    return conn.execute(f"SELECT name FROM users u WHERE u.id=? {where}", [uid] + params).fetchone()


@router.get("/users", response_class=HTMLResponse)
async def user_list(request: Request, q: str = "", page: int = 1,
                    u: dict = Depends(require_user_admin), conn=Depends(get_db)):
    where = "WHERE 1=1"
    params = []
    scope_sql, scope_params = _scope_where(u)
    where += scope_sql
    params += scope_params
    if q:
        where += " AND (u.name LIKE ? OR u.username LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]

    base_sql = f"""SELECT u.id, u.name, u.username, u.role, u.locked_until,
                          cu.client_role AS client_role,
                          cc.name AS company_name
                   FROM users u
                   LEFT JOIN client_users cu ON cu.user_id = u.id
                   LEFT JOIN employees e ON e.user_id = u.id
                   LEFT JOIN client_companies cc ON cc.id = COALESCE(cu.company_id, e.company_id)
                   {where} ORDER BY u.name"""

    total = conn.execute(f"SELECT COUNT(*) FROM users u {where}", params).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    rows = [dict(r) for r in conn.execute(
        f"{base_sql} LIMIT {PER_PAGE} OFFSET {(page - 1) * PER_PAGE}", params
    ).fetchall()]

    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    ids = [r["id"] for r in rows]
    last_logins = {}
    group_levels = {}
    if ids:
        marks = ",".join("?" * len(ids))
        for r in conn.execute(
            f"SELECT username, MAX(at) AS last FROM login_attempts WHERE ok=1 AND username IN "
            f"(SELECT username FROM users WHERE id IN ({marks})) GROUP BY username", ids
        ).fetchall():
            last_logins[r["username"]] = r["last"]
        for r in conn.execute(
            f"SELECT user_id, group_key, level FROM user_perms WHERE user_id IN ({marks})", ids
        ).fetchall():
            group_levels.setdefault(r["user_id"], {})[r["group_key"]] = r["level"]

    for r in rows:
        r["role_label"] = ROLE_LABELS.get(r["role"], r["role"])
        r["client_role_label"] = CLIENT_ROLE_LABELS.get(r["client_role"] or "all", "전체")
        r["last_login"] = last_logins.get(r["username"])
        r["locked"] = bool(r["locked_until"] and r["locked_until"] > now)
        levels = group_levels.get(r["id"], {})
        r["perms"] = {g: levels.get(g, "edit") for g in perms.GROUPS}

    return templates.TemplateResponse(request=request, name="users/user_list.html", context={
        "request": request, "page_title": "사용자 관리", "rows": rows, "q": q,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/users?q={q}",
        "groups": perms.GROUPS, "level_labels": LEVEL_LABELS,
        "client_role_labels": CLIENT_ROLE_LABELS, "u_role": u["role"],
    })


@router.patch("/users/{uid}/perms")
async def user_perms_update(request: Request, uid: int,
                            u: dict = Depends(require_user_admin), conn=Depends(get_db)):
    target = _in_scope(conn, u, uid)
    if not target:
        raise HTTPException(status_code=404)

    form = await request.form()
    changes = {}
    for group in perms.GROUPS:
        new = form.get(f"perm_{group}")
        if new is None or new not in ("none", "view", "edit"):
            continue
        old = perms.level(conn, uid, group)
        if new == old:
            continue
        if group == "admin" and uid == u["id"] and new != "edit":
            return JSONResponse({"error": "본인의 관리 권한은 낮출 수 없습니다."}, status_code=400)
        changes[group] = [old, new]

    for group, (old, new) in changes.items():
        if new == "edit":
            conn.execute("DELETE FROM user_perms WHERE user_id=? AND group_key=?", (uid, group))
        else:
            conn.execute(
                "INSERT INTO user_perms (user_id, group_key, level) VALUES (?,?,?) "
                "ON CONFLICT(user_id, group_key) DO UPDATE SET level=excluded.level",
                (uid, group, new),
            )
    if changes:
        audit.log(conn, u["id"], "perm_update", "user", uid, target["name"], detail=changes)
    conn.commit()
    return {"ok": True}


@router.patch("/users/{uid}/lock")
async def user_unlock(uid: int, u: dict = Depends(require_user_admin), conn=Depends(get_db)):
    target = _in_scope(conn, u, uid)
    if not target:
        raise HTTPException(status_code=404)
    conn.execute("UPDATE users SET locked_until=NULL WHERE id=?", (uid,))
    audit.log(conn, u["id"], "user_unlock", "user", uid, target["name"])
    conn.commit()
    return {"ok": True}


@router.patch("/users/{uid}/role")
async def user_client_role_update(request: Request, uid: int,
                                  u: dict = Depends(require_user_admin), conn=Depends(get_db)):
    if u["role"] != "platform_staff":
        raise HTTPException(status_code=403)
    target = conn.execute("SELECT name, role FROM users WHERE id=?", (uid,)).fetchone()
    if not target or target["role"] != "client":
        raise HTTPException(status_code=404)

    form = await request.form()
    client_role = form.get("client_role")
    if client_role not in ("all", "hr"):
        return JSONResponse({"error": "담당 구분 값이 올바르지 않습니다."}, status_code=400)

    old = conn.execute("SELECT client_role FROM client_users WHERE user_id=?", (uid,)).fetchone()
    old_role = old["client_role"] if old else "all"
    conn.execute("UPDATE client_users SET client_role=? WHERE user_id=?", (client_role, uid))
    if client_role != old_role:
        audit.log(conn, u["id"], "role_change", "user", uid, target["name"],
                  detail={"client_role": [old_role, client_role]})
    conn.commit()
    return {"ok": True}

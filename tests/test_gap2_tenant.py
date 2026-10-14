import importlib.util
import os

from routers.files import _allowed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_095():
    path = os.path.join(ROOT, "migrations", "095_doc_company.py")
    spec = importlib.util.spec_from_file_location("m095", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_create_erp_doc_stamps_author_company(db, seed, login):
    a = seed["a"]["company"]
    r = login("a_wk").post("/api/erp_docs", data={
        "doc_type": "draft", "title": "그룹웨어 문서", "content": "본문",
        "line_role": ["결재"], "line_user": [str(seed["a"]["mgr"])],
    }, follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT company_id FROM erp_docs WHERE title='그룹웨어 문서'").fetchone()
    assert row["company_id"] == a


def test_other_company_doc_404_even_as_approver(db, seed, login):
    b = seed["b"]["company"]
    doc = db.execute(
        "INSERT INTO erp_docs (user_id, doc_type, title, status, company_id, attachment) "
        "VALUES (?,?,?,?,?,?)",
        (seed["b"]["mgr"], "draft", "나사 문서", "wait", b, "x|f_b.pdf"),
    ).lastrowid
    db.execute(
        "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,1,?,'결재','pending')",
        (doc, seed["a"]["wk"]),
    )
    db.commit()
    r = login("a_wk").get(f"/erp_doc/{doc}")
    assert r.status_code == 404


def test_allowed_direct_check_for_registered_erp_file(db, seed):
    b = seed["b"]["company"]
    db.execute(
        "INSERT INTO erp_docs (user_id, doc_type, title, status, company_id, attachment) "
        "VALUES (?,?,?,?,?,?)",
        (seed["b"]["mgr"], "draft", "나사 문서2", "wait", b, "x|f_b2.pdf"),
    )
    db.commit()
    a_mgr = {"id": seed["a"]["mgr"], "role": "client"}
    staff = {"id": seed["staff"], "role": "platform_staff"}
    assert _allowed(db, "erp", "f_b2.pdf", a_mgr) is False
    assert _allowed(db, "erp", "f_b2.pdf", staff) is True


def test_allowed_direct_check_for_unregistered_erp_file(seed, db):
    a_mgr = {"id": seed["a"]["mgr"], "role": "client"}
    staff = {"id": seed["staff"], "role": "platform_staff"}
    assert _allowed(db, "erp", "nope.pdf", a_mgr) is False
    assert _allowed(db, "erp", "nope.pdf", staff) is True


def test_migration_095_backfills_author_company(db, seed):
    a = seed["a"]["company"]
    doc = db.execute(
        "INSERT INTO erp_docs (user_id, doc_type, title, status) VALUES (?,?,?,?)",
        (seed["a"]["wk"], "draft", "백필 대상", "draft"),
    ).lastrowid
    db.commit()
    assert db.execute("SELECT company_id FROM erp_docs WHERE id=?", (doc,)).fetchone()["company_id"] == 0

    _load_095().up(db)
    db.commit()

    assert db.execute("SELECT company_id FROM erp_docs WHERE id=?", (doc,)).fetchone()["company_id"] == a

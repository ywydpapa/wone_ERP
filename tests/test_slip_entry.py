from core import books
from tests.conftest import csrf
from tests.test_slip_routes import _form

LINES = [{"code": "813", "debit": 500, "credit": 0}, {"code": "103", "debit": 0, "credit": 500}]


def test_month_list_and_view(db, seed, login):
    doc = books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-09-15", LINES, "9월 비품", "manual")
    books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-08-20", LINES, "8월 비품", "manual")
    db.commit()
    c = login("a_mgr")
    r = c.get("/slip_entry?ym=2026-09")
    assert r.status_code == 200
    assert "9월 비품" in r.text and "8월 비품" not in r.text
    assert 'id="slipForm"' in r.text and 'data-key="F8"' in r.text
    v = c.get(f"/slip_entry?id={doc}").text
    assert 'class="se-pick" aria-current="true"' in v
    assert 'id="slipForm"' not in v
    assert f'href="/erp_doc/{doc}"' in v


def test_day_filter(db, seed, login):
    books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-09-15", LINES, "15일분", "manual")
    books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-09-16", LINES, "16일분", "manual")
    db.commit()
    t = login("a_mgr").get("/slip_entry?ym=2026-09&day=15").text
    assert "15일분" in t and "16일분" not in t


def test_other_book_and_other_worker_hidden(db, seed, login):
    b = books.post(db, seed["b"]["company"], seed["b"]["wk"], "2026-09-15", LINES, "B사전표", "manual")
    m = books.post(db, seed["a"]["company"], seed["a"]["mgr"], "2026-09-15", LINES, "담당자전표", "manual")
    db.commit()
    c = login("a_wk")
    t = c.get("/slip_entry?ym=2026-09").text
    assert "B사전표" not in t and "담당자전표" not in t
    for doc, title in ((b, "B사전표"), (m, "담당자전표")):
        t = c.get(f"/slip_entry?id={doc}").text
        assert title not in t and 'action="/api/slip"' in t


def test_create_and_edit_stay_on_entry(db, seed, login):
    c = login("a_wk")
    data = _form(csrf(c), [("813", 500, 0, None), ("103", 0, 500, None)], seed["a"]["mgr"], back="entry", save_mode="draft")
    r = c.post("/api/slip", data=data, follow_redirects=False)
    doc = db.execute("SELECT id FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    assert r.headers["location"] == f"/slip_entry?id={doc}&saved=1"
    t = c.get(f"/slip_entry?id={doc}&saved=1").text
    assert f'action="/api/slip/{doc}"' in t
    assert 'name="back" value="entry"' in t
    r = c.post(f"/api/slip/{doc}", data=_form(csrf(c), [("813", 700, 0, None), ("103", 0, 700, None)], seed["a"]["mgr"], back="entry"),
               follow_redirects=False)
    assert r.headers["location"] == f"/slip_entry?id={doc}&saved=1"
    assert db.execute("SELECT slip_total FROM erp_docs WHERE id=?", (doc,)).fetchone()[0] == 700


def test_copy_prefills_new_form(db, seed, login):
    doc = books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-09-15", LINES, "원본", "manual")
    db.commit()
    t = login("a_wk").get(f"/slip_entry?ym=2026-09&copy={doc}").text
    assert 'action="/api/slip"' in t
    assert "[복사] 원본" in t


def test_bad_month_falls_back(login):
    assert login("a_mgr").get("/slip_entry?ym=2026-13&day=40").status_code == 200

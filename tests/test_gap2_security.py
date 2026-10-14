import core.rate_limit as rate_limit
from core.perms import group_of_path


def _set_perm(db, uid, group, level):
    db.execute(
        "INSERT INTO user_perms (user_id, group_key, level) VALUES (?,?,?) "
        "ON CONFLICT(user_id, group_key) DO UPDATE SET level=excluded.level",
        (uid, group, level),
    )
    db.commit()


def test_none_level_blocks_module_dashboard(db, seed, login):
    _set_perm(db, seed["a"]["wk"], "hr", "none")
    assert login("a_wk").get("/erp_hr").status_code == 403


def test_doc_paths_follow_approval_line_not_menu_group():
    assert group_of_path("/erp_doc/1") is None
    assert group_of_path("/api/erp_docs/1/approve") is None


def test_group_of_path_erp_fa_is_fi():
    assert group_of_path("/erp_fa") == "fi"


def test_forged_xff_ignored_without_trust_proxy(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUST_PROXY", False)
    req = type("R", (), {
        "headers": {"x-forwarded-for": "1.2.3.4"},
        "client": type("C", (), {"host": "127.0.0.1"})(),
    })()
    assert rate_limit.get_client_ip(req) == "127.0.0.1"

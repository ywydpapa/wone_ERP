import json
import re
from itertools import groupby

from core.help import GROUPS, PAGES, find_help


def test_find_help():
    assert find_help("/hr/attendance")["title"] == "근태 관리"
    assert find_help("/hr/attendance/3/edit") is PAGES["/hr/attendance/{att_id}/edit"]
    assert find_help("/nope") is None
    assert find_help("/platform/companies/new") is PAGES["/platform/companies/new"]
    assert find_help("/mypage/") is PAGES["/mypage"]
    assert find_help("/approval-lines/expense") is PAGES["/approval-lines/{form_key}"]


def test_related_exists():
    for p in PAGES.values():
        for r in p.get("related", []):
            assert r in PAGES, r


def test_panel(login):
    c = login("t_staff")
    html = c.get("/hr/attendance").text
    data = json.loads(re.search(r'id="helpData">(.*?)</script>', html, re.S).group(1))
    assert data["fields"][0]["name"] == "company"
    assert 'id="helpPanel"' not in c.get("/manual").text


def test_manual(login, raw_client):
    assert "근태 관리" in login("t_staff").get("/manual").text
    assert raw_client.get("/manual", follow_redirects=False).status_code in (302, 303, 307)


def test_sections_contiguous():
    for g in GROUPS:
        names = [k for k, _ in groupby(p["section"] for p in g["pages"].values())]
        assert len(names) == len(set(names)), g["id"]


def test_help_mode_menu(login):
    c = login("t_staff")
    html = c.get("/hr/attendance").text
    assert html.count("data-help-mode") == 2
    assert "<h3>입력 항목</h3>" in html
    assert "data-help-mode" not in c.get("/manual").text


# 헤드마우스 hm-target 클래스와 충돌 방지
def test_help_class_separate():
    with open("static/js/help.js", encoding="utf-8") as f:
        assert "hm-" not in f.read()


def test_manual_menu(login):
    for u in ("t_staff", "a_mgr", "a_wk"):
        assert 'href="/manual" data-code="SY1013"' in login(u).get("/").text


def test_tour_entry(login):
    c = login("t_staff")
    html = c.get("/hr/attendance").text
    assert html.count("data-help-tour") == 3
    assert "data-help-tour" not in c.get("/manual").text


def test_menu_without_help(login):
    html = login("t_staff").get("/manual").text
    assert "준비 중, 매뉴얼로 이동" in html
    assert html.count('class="dropdown help-drop"') == 1

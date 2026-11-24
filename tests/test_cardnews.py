import json
import pytest
from tests.conftest import csrf

def test_cardnews_routes_and_crud(login, db):
    client = login("t_staff")

    # 1. 목록 페이지 조회
    res = client.get("/cardnews")
    assert res.status_code == 200
    assert "카드뉴스" in res.text

    # 2. 신규 편집기 페이지 조회
    res_editor = client.get("/cardnews/editor")
    assert res_editor.status_code == 200
    assert "카드뉴스 편집기" in res_editor.text

    # 3. 프로젝트 저장 (신규 생성)
    new_data = {
        "title": "테스트 카드뉴스",
        "aspect_ratio": "1:1",
        "width": 1080,
        "height": 1080,
        "slides_json": json.dumps([{"bg": "#ffffff", "objects": []}]),
        "thumbnail": "data:image/png;base64,sample",
    }
    res_save = client.post("/cardnews/api/save", json=new_data)
    assert res_save.status_code == 200
    save_json = res_save.json()
    assert save_json["ok"] is True
    project_id = save_json["id"]
    assert project_id > 0

    # 4. 단일 프로젝트 조회 API
    res_get = client.get(f"/cardnews/api/{project_id}")
    assert res_get.status_code == 200
    proj = res_get.json()
    assert proj["title"] == "테스트 카드뉴스"
    assert proj["aspect_ratio"] == "1:1"

    # 5. 기존 프로젝트 편집기 열기
    res_edit_existing = client.get(f"/cardnews/editor?id={project_id}")
    assert res_edit_existing.status_code == 200
    assert "테스트 카드뉴스" in res_edit_existing.text

    # 6. 수정 저장
    update_data = {
        "id": project_id,
        "title": "수정된 카드뉴스",
        "aspect_ratio": "4:5",
        "width": 1080,
        "height": 1350,
        "slides_json": json.dumps([{"bg": "#000000", "objects": []}]),
        "thumbnail": "data:image/png;base64,updated",
    }
    res_update = client.post("/cardnews/api/save", json=update_data)
    assert res_update.status_code == 200
    assert res_update.json()["ok"] is True

    # 7. 수정 확인
    res_get_updated = client.get(f"/cardnews/api/{project_id}")
    assert res_get_updated.json()["title"] == "수정된 카드뉴스"

    # 8. 삭제
    res_del = client.post(f"/cardnews/api/{project_id}/delete")
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True

    # 9. 삭제 후 404 확인
    res_after_del = client.get(f"/cardnews/api/{project_id}")
    assert res_after_del.status_code == 404

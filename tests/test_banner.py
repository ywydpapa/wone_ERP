import json
import re
import pytest
from tests.conftest import csrf

def test_banner_routes_and_crud(login, db):
    client = login("t_staff")

    # 1. 배너 목록 페이지 조회
    res = client.get("/banner")
    assert res.status_code == 200
    assert "배너 제작 관리" in res.text

    # 2. 신규 배너 편집기 페이지 조회
    res_editor = client.get("/banner/editor")
    assert res_editor.status_code == 200
    assert "배너 편집기" in res_editor.text

    # 3. 배너 저장 (신규 생성)
    new_data = {
        "title": "2026 하반기 메인 프로모션 배너",
        "category": "web",
        "preset_name": "메인 웹 배너",
        "width": 1200,
        "height": 400,
        "canvas_json": json.dumps({"version": "5.3.0", "objects": []}),
        "thumbnail": "data:image/png;base64,sample_banner_thumb",
    }
    res_save = client.post("/banner/api/save", json=new_data)
    assert res_save.status_code == 200
    save_json = res_save.json()
    assert save_json["ok"] is True
    project_id = save_json["id"]
    assert project_id > 0

    # 4. 단일 배너 조회 API
    res_get = client.get(f"/banner/api/{project_id}")
    assert res_get.status_code == 200
    proj = res_get.json()
    assert proj["title"] == "2026 하반기 메인 프로모션 배너"
    assert proj["width"] == 1200
    assert proj["height"] == 400

    # 5. 기존 배너 편집기 열기
    res_edit_existing = client.get(f"/banner/editor?id={project_id}")
    assert res_edit_existing.status_code == 200
    assert "2026 하반기 메인 프로모션 배너" in res_edit_existing.text

    # 6. 배너 수정 저장
    update_data = {
        "id": project_id,
        "title": "수정된 프로모션 배너",
        "category": "sns",
        "preset_name": "유튜브 썸네일",
        "width": 1280,
        "height": 720,
        "canvas_json": json.dumps({"version": "5.3.0", "objects": [{"type": "text"}]}),
        "thumbnail": "data:image/png;base64,updated_thumb",
    }
    res_update = client.post("/banner/api/save", json=update_data)
    assert res_update.status_code == 200
    assert res_update.json()["ok"] is True

    # 7. 수정 확인
    res_get_updated = client.get(f"/banner/api/{project_id}")
    assert res_get_updated.json()["title"] == "수정된 프로모션 배너"
    assert res_get_updated.json()["width"] == 1280

    # 8. 배너 복제
    res_dup = client.post(f"/banner/api/{project_id}/duplicate")
    assert res_dup.status_code == 200
    dup_json = res_dup.json()
    assert dup_json["ok"] is True
    dup_id = dup_json["id"]
    assert dup_id != project_id

    # 복제본 조회
    res_get_dup = client.get(f"/banner/api/{dup_id}")
    assert "복사본" in res_get_dup.json()["title"]

    # 9. 삭제
    res_del = client.post(f"/banner/api/{project_id}/delete")
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True

    # 10. 삭제 후 404 확인
    res_after_del = client.get(f"/banner/api/{project_id}")
    assert res_after_del.status_code == 404


def test_banner_csrf_protection(raw_client, seed):
    # 로그인
    html = raw_client.get("/login").text
    tok = re.search(r"[a-f0-9]{64}", html).group(0)
    raw_client.post(
        "/login_check",
        data={"username": "a_mgr", "password": "1234", "csrf_token": tok},
        follow_redirects=False,
    )

    banner_data = {
        "title": "CSRF 테스트 배너",
        "category": "web",
        "preset_name": "메인 배너",
        "width": 1200,
        "height": 400,
        "canvas_json": "{}",
        "thumbnail": ""
    }

    # 1. X-CSRF-Token 헤더 없이 POST 요청 시 403 Forbidden 발생 확인
    res_no_csrf = raw_client.post("/banner/api/save", json=banner_data)
    assert res_no_csrf.status_code == 403

    # 2. 유효한 X-CSRF-Token 헤더와 함께 전송 시 정상 저장(200) 확인
    page_html = raw_client.get("/banner").text
    csrf_token = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([a-f0-9]{64})["\']', page_html).group(1)

    res_with_csrf = raw_client.post(
        "/banner/api/save",
        json=banner_data,
        headers={"X-CSRF-Token": csrf_token}
    )
    assert res_with_csrf.status_code == 200
    res_json = res_with_csrf.json()
    assert res_json["ok"] is True
    pid = res_json["id"]

    # 3. 배너 복제 및 삭제도 정상 작동 확인
    res_dup = raw_client.post(f"/banner/api/{pid}/duplicate", headers={"X-CSRF-Token": csrf_token})
    assert res_dup.status_code == 200
    assert res_dup.json()["ok"] is True

    res_del = raw_client.post(f"/banner/api/{pid}/delete", headers={"X-CSRF-Token": csrf_token})
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True


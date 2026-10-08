import os

import pytest

from core import books

sync_api = pytest.importorskip("playwright.sync_api")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS_FILES = ["base.css", "components.css", "pages.css", "dark.css"]
SCREEN_READ_JS = os.path.join(REPO_ROOT, "static", "js", "screen-read.js")


def _chrome_ok():
    try:
        with sync_api.sync_playwright() as p:
            b = p.chromium.launch(channel="chrome")
            b.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _chrome_ok(), reason="크롬 설치 안 됐거나 launch 실패")


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


def load(pg, html):
    pg.set_content(html, wait_until="domcontentloaded")
    for css in CSS_FILES:
        pg.add_style_tag(path=os.path.join(REPO_ROOT, "static", "css", css))
    pg.add_script_tag(path=SCREEN_READ_JS)


def get_lines(pg):
    return pg.evaluate("() => window.ScreenRead.lines(document.getElementById('main'))")


def test_balance_sheet_has_lines(db, seed, login, page):
    books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-09-10",
               [{"code": "103", "debit": 333333, "credit": 0}, {"code": "331", "debit": 0, "credit": 333333}],
               "자본금 납입", "manual")
    db.commit()
    html = login("a_mgr").get("/report/balance-sheet?as_of=2026-12-31").text
    load(page, html)
    lines = get_lines(page)
    assert lines
    assert any("333,333" in l for l in lines)
    assert any("자산 합계" in l for l in lines)


def test_dashboard_stat_card_merges_label_and_value(db, seed, login, page):
    html = login("a_mgr").get("/erp_dash").text
    load(page, html)
    lines = get_lines(page)
    assert "결재 기안 0건" in lines
    assert "결재 기안" not in lines
    assert "0건" not in lines


def test_form_grid_field_reads_label_and_value(db, seed, login, page):
    html = login("a_mgr").get("/items/new").text
    load(page, html)
    lines = get_lines(page)
    assert "품목코드, 비어 있음" in lines


def test_table_colspan_header_maps_correctly_and_easy_mode(db, seed, login, page):
    a = seed["a"]["company"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P1','테스트거래처',?)", (a,)).lastrowid
    books.post(db, a, seed["a"]["wk"], "2026-08-01",
               [{"code": "813", "debit": 50000, "credit": 0, "partner_id": pid}, {"code": "103", "debit": 0, "credit": 50000}],
               "이전월 통신비", "manual")
    books.post(db, a, seed["a"]["wk"], "2026-09-10",
               [{"code": "813", "debit": 70000, "credit": 0, "partner_id": pid}, {"code": "103", "debit": 0, "credit": 70000}],
               "통신비", "manual")
    db.commit()
    html = login("a_mgr").get(
        "/ledger/general?account_code=813&date_from=2026-09-01&date_to=2026-09-30"
    ).text
    load(page, html)

    lines = get_lines(page)
    joined = "\n".join(lines)

    # 이월(colspan) 행이 다음 칸 헤더(전표번호 등)로 잘못 매핑되지 않아야 함
    assert "전표번호 이월" not in joined
    assert "적요 이월" not in joined
    assert any("이월" in l and "차변 50,000" in l for l in lines)
    # tfoot 합계 행은 "합계,"로 시작
    assert any(l.startswith("합계,") and "차변 70,000" in l for l in lines)
    # 이지모드 전에는 col-opt(거래처)가 읽힘
    assert "테스트거래처" in joined

    page.eval_on_selector("body", "el => el.classList.add('easy-mode')")
    easy_lines = get_lines(page)
    easy_joined = "\n".join(easy_lines)
    assert "테스트거래처" not in easy_joined


def test_hidden_and_aria_hidden_not_read_no_duplicate(page):
    html = """
    <!doctype html><html><body>
    <main id="main">
      <p>보이는 문단입니다</p>
      <p hidden>숨긴 문단</p>
      <p style="display:none">display none 문단</p>
      <p aria-hidden="true">aria 숨김 문단</p>
      <p class="sr-only">스크린리더 전용 문단</p>
      <div><span aria-hidden="true">무시되는 숫자뱃지</span> 실제 내용</div>
      <details><summary>위젯 설정</summary><div>닫힌 패널 내용</div></details>
      <div><a href="/x" class="btn btn-sm">초기화</a><a href="/y">목록으로 돌아가기</a></div>
      <div><label for="d1">기간</label><input id="d1" type="date" value="2026-09-01"><span>~</span><input type="date" value="2026-09-30" aria-label="기간 종료"></div>
      <div class="form-grid">
        <label for="qty">수량</label>
        <div class="fg-field"><input id="qty" type="text" value="3"></div>
      </div>
    </main>
    </body></html>
    """
    load(page, html)
    lines = get_lines(page)
    joined = "\n".join(lines)

    assert "보이는 문단입니다" in lines
    assert "숨긴 문단" not in joined
    assert "display none 문단" not in joined
    assert "aria 숨김 문단" not in joined
    assert "스크린리더 전용 문단" not in joined
    assert "무시되는 숫자뱃지" not in joined
    assert "실제 내용" in joined
    assert "위젯 설정" in joined
    assert "닫힌 패널 내용" not in joined
    assert "초기화" not in joined
    assert "목록으로 돌아가기" in joined
    assert "기간, 2026-09-01" in lines
    assert "기간 종료, 2026-09-30" in lines
    assert "~" not in lines

    # label[for]로 짝지어진 수량 필드는 한 줄로만, 중복 없음
    assert lines.count("수량, 3") == 1
    assert len(lines) == len(set(lines))

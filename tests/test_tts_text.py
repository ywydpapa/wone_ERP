from core.tts_text import ko_text


def test_date():
    assert ko_text("20250130") == "이천이십오 년 일 월 삼십 일"
    assert ko_text("2025-06-10") == "이천이십오 년 유 월 십 일"
    assert ko_text("2025.10.03 마감") == "이천이십오 년 시 월 삼 일 마감"


def test_money():
    assert ko_text("1,234,000원") == "백이십삼만 사천 원"
    assert ko_text("10000원") == "만 원"
    assert ko_text("3.5%") == "삼 점 오 퍼센트"


def test_counter():
    assert ko_text("3명") == "세 명"
    assert ko_text("신규 21건") == "신규 이십일 건"
    assert ko_text("14:30") == "십사 시 삼십 분"
    assert ko_text("출근 08:50") == "출근 여덟 시 오십 분"
    assert ko_text("퇴근 09:00") == "퇴근 아홉 시"
    assert ko_text("9시 0분") == "아홉 시"
    assert ko_text("12시 5분") == "열두 시 오 분"
    assert ko_text("3시간") == "세 시간"


def test_digits():
    assert ko_text("010-1234-5678") == "공일공, 일이삼사, 오육칠팔"
    assert ko_text("123-45-67890") == "일이삼, 사오, 육칠팔구공"


def test_word():
    assert ko_text("고객사 현황") == "고객사 현 황"
    assert ko_text("저장") == "저장"

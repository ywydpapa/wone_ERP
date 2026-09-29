import re

# TTS 전 숫자/날짜를 한글 읽기로 풀어줌. 모델이 숫자를 외국어처럼 뭉개서 읽음
DIGITS = "영일이삼사오육칠팔구"
NATIVE = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
NATIVE_TEN = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]

# 모델이 잘못 읽는 단어. 들어보고 틀리면 추가
WORDS = {"현황": "현 황"}

DATE_RE = re.compile(r"(?<!\d)((?:19|20)\d\d)([-./]?)(\d\d)\2(\d\d)(?!\d)")
NUMS_RE = re.compile(r"(?<![\d-])\d{2,4}(?:-\d{2,5}){2}(?![\d-])")
TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d\d)(?!\d)")
TIME_KO_RE = re.compile(r"(?<!\d)(\d{1,2})\s?시(?!간)(?:\s?(\d{1,2})\s?분)?")
COUNTER_RE = re.compile(r"(?<!\d)(\d{1,2})\s?(명|개|살|가지|시간|번째)")


def sino(n):
    if n == 0:
        return "영"
    parts = []
    for unit in ["", "만", "억", "조"]:
        g = n % 10000
        n //= 10000
        if g:
            s = ""
            for d, u in zip(f"{g:04d}", ["천", "백", "십", ""]):
                d = int(d)
                if d:
                    s += ("" if d == 1 and u else DIGITS[d]) + u
            if unit == "만" and g == 1:
                s = ""
            parts.append(s + unit)
        if not n:
            break
    return " ".join(reversed(parts))


def native(n):
    return "스무" if n == 20 else NATIVE_TEN[n // 10] + NATIVE[n % 10]


def read_date(m):
    y, mon, d = int(m[1]), int(m[3]), int(m[4])
    if not (1 <= mon <= 12 and 1 <= d <= 31):
        return m[0]
    mon_txt = {6: "유", 10: "시"}.get(mon, sino(mon))
    return f"{sino(y)} 년 {mon_txt} 월 {sino(d)} 일"


def read_nums(m):
    return ", ".join("".join("공" if c == "0" else DIGITS[int(c)] for c in g) for g in m[0].split("-"))


def read_time(m):
    h, mi = int(m[1]), int(m[2] or 0)
    if h > 24 or mi > 59:
        return m[0]
    hour = native(h) if 1 <= h <= 12 else sino(h)
    return f"{hour} 시" + (f" {sino(mi)} 분" if mi else "")


def read_counter(m):
    n, unit = int(m[1]), m[2]
    if not n:
        return m[0]
    if n == 1 and unit == "번째":
        return "첫 번째"
    return f"{native(n)} {unit}"


def read_num(m):
    tail = m.string[m.end():m.end() + 1]
    return sino(int(m[0])) + (" " if tail and not tail.isspace() else "")


def ko_text(text):
    for k, v in WORDS.items():
        text = text.replace(k, v)
    text = DATE_RE.sub(read_date, text)
    text = NUMS_RE.sub(read_nums, text)
    text = TIME_RE.sub(read_time, text)
    text = TIME_KO_RE.sub(read_time, text)
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    text = text.replace("%", " 퍼센트")
    text = re.sub(r"(\d+)\.(\d+)", lambda m: sino(int(m[1])) + " 점 " + "".join(DIGITS[int(c)] for c in m[2]), text)
    text = COUNTER_RE.sub(read_counter, text)
    text = re.sub(r"\d+", read_num, text)
    return re.sub(r"\s+", " ", text).strip()

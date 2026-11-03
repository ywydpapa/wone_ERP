import csv
import hashlib
import io
import pathlib
from datetime import date, datetime

from openpyxl import load_workbook

# 프리셋별 필드 헤더명 후보. date, amt_in, amt_out 후보가 모두 매칭되면 그 프리셋으로 인식
PRESETS = {
    "kb": {"date": ["거래일시"], "memo": ["적요"], "party": ["보낸분/받는분"],
           "amt_out": ["출금액"], "amt_in": ["입금액"], "balance": ["잔액"]},
    "shinhan": {"date": ["거래일자"], "memo": ["적요"], "party": ["내용"],
                "amt_out": ["출금"], "amt_in": ["입금"], "balance": ["잔액"]},
    "woori": {"date": ["거래일시"], "memo": ["기재내용"],
              "amt_out": ["찾으신금액"], "amt_in": ["맡기신금액"], "balance": ["잔액"]},
    "hana": {"date": ["거래일시"], "memo": ["적요"],
             "amt_out": ["출금"], "amt_in": ["입금"], "balance": ["잔액"]},
    "nh": {"date": ["거래일자"], "memo": ["거래내용"],
           "amt_out": ["출금금액"], "amt_in": ["입금금액"], "balance": ["거래후잔액"]},
}

REQUIRED_FIELDS = ("date", "amt_in", "amt_out")
DT_FMTS = ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
           "%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d")

# 법인카드 사용내역 열 후보. 공급가액/부가세는 없는 카드사도 있어 필수에서 제외
CARD_FIELDS = {
    "approve_date": ["승인일자", "이용일자", "거래일자"],
    "approval_no": ["승인번호"],
    "merchant": ["가맹점명", "가맹점"],
    "merchant_biz_no": ["가맹점사업자번호", "사업자번호"],
    "total": ["이용금액", "승인금액", "결제금액"],
    "supply_amt": ["공급가액"],
    "vat": ["부가세", "세액"],
    "card_no": ["카드번호"],
}
CARD_REQUIRED = ("approve_date", "approval_no", "total")


def _norm_header(v):
    s = "" if v is None else str(v).strip()
    for ch in (" ", "\u00b7", "/"):
        s = s.replace(ch, "")
    return s


def read_rows(data, filename):
    ext = pathlib.Path(filename).suffix.lower()
    if ext == ".xlsx":
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        return [list(r) for r in wb.active.iter_rows(values_only=True)]
    if ext == ".csv":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp949")
        return list(csv.reader(io.StringIO(text)))
    raise ValueError(f"지원하지 않는 파일 형식: {filename}")


def find_header(rows, fields, required=REQUIRED_FIELDS):
    for idx, row in enumerate(rows[:20]):
        cells = {}
        for col, v in enumerate(row):
            norm = _norm_header(v)
            if norm and norm not in cells:
                cells[norm] = col
        cmap = {}
        for field, cands in fields.items():
            for cand in cands:
                col = cells.get(_norm_header(cand))
                if col is not None:
                    cmap[field] = col
                    break
        if all(f in cmap for f in required):
            return idx, cmap
    return None


def _cell(row, col):
    if col is None or col >= len(row):
        return None
    return row[col]


def _norm_dt(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        if v.hour or v.minute or v.second:
            return v.strftime("%Y-%m-%d %H:%M:%S")
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    if not s:
        return None
    for fmt in DT_FMTS:
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        return dt.strftime("%Y-%m-%d %H:%M:%S") if "%H" in fmt else dt.strftime("%Y-%m-%d")
    return None


def _norm_amt(v):
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).replace(",", "").replace(" ", "").strip()
    if s in ("", "-"):
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def parse(rows, cmap):
    txns = []
    for row in rows:
        at = _norm_dt(_cell(row, cmap.get("date")))
        if at is None:
            continue
        party = str(_cell(row, cmap.get("party")) or "").strip()
        memo = str(_cell(row, cmap.get("memo")) or "").strip() if "memo" in cmap else party
        txns.append({
            "txn_at": at, "memo": memo, "party": party,
            "amt_in": _norm_amt(_cell(row, cmap.get("amt_in"))),
            "amt_out": _norm_amt(_cell(row, cmap.get("amt_out"))),
            "balance": _norm_amt(_cell(row, cmap.get("balance"))) if "balance" in cmap else None,
        })
    return txns


def parse_card(rows, cmap):
    txns = []
    for row in rows:
        at = _norm_dt(_cell(row, cmap.get("approve_date")))
        appno = str(_cell(row, cmap.get("approval_no")) or "").strip()
        if at is None or not appno:
            continue
        total = _norm_amt(_cell(row, cmap.get("total")))
        supply = _norm_amt(_cell(row, cmap.get("supply_amt"))) if "supply_amt" in cmap else total
        vat = _norm_amt(_cell(row, cmap.get("vat"))) if "vat" in cmap else 0
        card_raw = str(_cell(row, cmap.get("card_no")) or "").replace("-", "").replace(" ", "")
        txns.append({
            "approve_date": at, "approval_no": appno,
            "merchant": str(_cell(row, cmap.get("merchant")) or "").strip(),
            "merchant_biz_no": str(_cell(row, cmap.get("merchant_biz_no")) or "").strip(),
            "supply_amt": supply, "vat": vat, "total": total, "card_no": card_raw[-4:],
        })
    return txns


def txn_hash(acct_id, t, seq=0):
    key = f"{acct_id}|{t['txn_at']}|{t['amt_in']}|{t['amt_out']}|{t['memo']}|{t['balance']}"
    # 잔액 미매핑 업로드는 동일 키 중복 거래가 실재하므로 파일 내 등장 순번으로 구분
    if t["balance"] is None and seq:
        key += f"|{seq}"
    return hashlib.sha1(key.encode()).hexdigest()

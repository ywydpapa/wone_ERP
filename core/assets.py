# 법인세법 시행규칙 별표4 정률법 상각률(천분율). 정액법은 1/내용연수 소수 셋째자리 절사
DB_RATES = {2: 777, 3: 632, 4: 528, 5: 451, 6: 394, 7: 349, 8: 313, 9: 284, 10: 259, 11: 239,
            12: 221, 13: 206, 14: 193, 15: 182, 16: 171, 17: 162, 18: 154, 19: 146, 20: 140}
METHODS = ("정액법", "정률법")
# 상각 완료 자산 비망가액
MEMO = 1000
DEPR_CODE = "816"
# 유형자산 계정별 감가상각누계액 계정
ACCUM = {"202": "207", "204": "209", "205": "210", "206": "211"}


def rate(a):
    if a["method"] == "정률법":
        return DB_RATES[a["life_years"]]
    return 1000 // a["life_years"]


def year_amount(a, year, acc, capex=0):
    acq_y, acq_m = int(a["acq_date"][:4]), int(a["acq_date"][5:7])
    end = 12
    if a["disposed_date"]:
        dy = int(a["disposed_date"][:4])
        if year > dy:
            return 0
        if year == dy:
            end = int(a["disposed_date"][5:7])
    if year < acq_y:
        return 0
    # 월할 상각. 취득월은 1개월로 계산
    months = end - (acq_m if year == acq_y else 1) + 1
    cost = a["acq_cost"] + capex
    left = cost - MEMO - acc
    if months <= 0 or left <= 0:
        return 0
    if a["method"] == "정액법":
        # 내용연수 만기월 도달 시 반올림 누적오차 없이 잔액을 전부 비망가액까지 상각
        elapsed = (year - acq_y) * 12 + end - acq_m + 1
        if not a["disposed_date"] and elapsed >= a["life_years"] * 12:
            return left
        # 연 상각액 = (취득가-비망가액) / 내용연수 원단위 반올림
        annual = (2 * (cost - MEMO) + a["life_years"]) // (2 * a["life_years"])
        return min(annual * months // 12, left)
    return min((cost - acc) * rate(a) * months // 12000, left)


def _capex_as_of(rows, year):
    # 법인세법상 자본적 지출은 월할 없이 지출 연도부터 장부가액에 합산해 상각
    return sum(amt for d, amt in rows if int(d[:4]) <= year)


def depr(conn, a, year):
    # 이전 연도 상각 미반영 시 당기 계산 불가
    done = {r["year"]: r["amount"] for r in conn.execute("SELECT year, amount FROM fa_depr WHERE asset_id=?", (a["id"],))}
    capex_rows = [(r["date"], r["amount"]) for r in conn.execute(
        "SELECT date, amount FROM fa_capex WHERE asset_id=?", (a["id"],))]
    acc = a["open_accum"]
    for y in range(a["open_year"] + 1, year):
        if y in done:
            acc += done[y]
        elif year_amount(a, y, acc, _capex_as_of(capex_rows, y)):
            return {"amount": 0, "accum": acc, "posted": False, "error": f"{y}년 상각 미반영"}
    if year <= a["open_year"]:
        return {"amount": 0, "accum": acc, "posted": False, "error": ""}
    if year in done:
        return {"amount": done[year], "accum": acc, "posted": True, "error": ""}
    return {"amount": year_amount(a, year, acc, _capex_as_of(capex_rows, year)), "accum": acc, "posted": False, "error": ""}

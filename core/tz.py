from datetime import datetime, date, timezone, timedelta

KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST)


def today_kst():
    return now_kst().date()

import glob
import json
import os
import re

HELP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "help")

GROUPS = []
for path in sorted(glob.glob(os.path.join(HELP_DIR, "*.json"))):
    with open(path, encoding="utf-8") as f:
        GROUPS.append(json.load(f))

PAGES = {}
for g in GROUPS:
    PAGES.update(g["pages"])

# 상세 화면 경로변수({id}) 매칭용. id는 숫자만 인정하므로 /new 같은 등록 화면 제외. 서식/모듈 키만 문자열
ROUTES = [(re.compile("^" + re.sub(r"\{\w+\}", r"\\d+", re.sub(r"\{(form_key|module)\}", "[a-z_]+", p)) + "$"), p)
          for p in PAGES if "{" in p]


def find_help(path):
    path = path.rstrip("/") or "/"
    if path in PAGES:
        return PAGES[path]
    for rx, p in ROUTES:
        if rx.match(path):
            return PAGES[p]

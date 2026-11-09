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

# 상세 화면 경로변수({id}) 매칭용
ROUTES = [(re.compile("^" + re.sub(r"\{\w+\}", "[^/]+", p) + "$"), p) for p in PAGES if "{" in p]


def find_help(path):
    if path in PAGES:
        return PAGES[path]
    for rx, p in ROUTES:
        if rx.match(path):
            return PAGES[p]

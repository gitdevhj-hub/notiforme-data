#!/usr/bin/env python3
"""
notices.json과 releases.json이 앱이 읽을 수 있는 형식인지 확인한다.
GitHub Actions가 두 파일을 고칠 때마다 자동으로 실행한다. (.github/workflows/check-notices.yml)
틀린 곳이 있으면 Actions가 빨간 X로 실패하고 무엇이 틀렸는지 알려준다.
"""

import datetime
import json
import sys

errors = []


def parse_time(text):
    """앱과 같은 규칙: "2026-11-11 09:00", "2026-11-11", "2026-11-11T09:00:00+09:00" """
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return datetime.datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return False


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as error:
        errors.append(f"{path}: JSON 형식이 틀렸어요 ({error.lineno}번째 줄 {error.colno}번째 글자 근처). 쉼표·따옴표·괄호를 확인해 주세요.")
        return None


notices = load("notices.json")
if notices is not None:
    items = notices.get("notices")
    if not isinstance(items, list):
        errors.append('notices.json: 맨 바깥은 { "notices": [ ... ] } 모양이어야 해요.')
        items = []
    seen = set()
    for i, n in enumerate(items, 1):
        where = f"notices.json {i}번째 공지"
        for key in ("id", "title", "body"):
            if not isinstance(n.get(key), str) or not n.get(key).strip():
                errors.append(f"{where}: \"{key}\"(글자)가 비어 있거나 없어요.")
        if not isinstance(n.get("canUseApp"), bool):
            errors.append(f"{where}: \"canUseApp\"는 true(앱 사용 가능) 또는 false(사용 불가)여야 해요. 따옴표 없이 써요.")
        if n.get("id") in seen:
            errors.append(f"{where}: id \"{n.get('id')}\"가 다른 공지와 같아요. 공지마다 달라야 해요.")
        seen.add(n.get("id"))
        start, end = parse_time(n.get("start")), parse_time(n.get("end"))
        for key, value in (("start", start), ("end", end)):
            if value is False:
                errors.append(f"{where}: \"{key}\" 날짜 형식이 틀렸어요. \"2026-11-11 09:00\"처럼 써 주세요.")
        if start and end and start >= end:
            errors.append(f"{where}: 끝(end)이 시작(start)보다 빨라요.")
        if n.get("link") and not str(n.get("link")).startswith("http"):
            errors.append(f"{where}: \"link\"는 https:// 로 시작해야 해요.")

releases = load("releases.json")
if releases is not None:
    items = releases.get("releases")
    if not isinstance(items, list):
        errors.append('releases.json: 맨 바깥은 { "releases": [ ... ] } 모양이어야 해요.')
        items = []
    for i, r in enumerate(items, 1):
        where = f"releases.json {i}번째 내역"
        for key in ("version", "date"):
            if not isinstance(r.get(key), str) or not r.get(key).strip():
                errors.append(f"{where}: \"{key}\"(글자)가 비어 있거나 없어요.")
        if parse_time(r.get("date")) in (None, False):
            errors.append(f"{where}: \"date\"는 \"2026-11-11\"처럼 써 주세요.")
        if not isinstance(r.get("items"), list) or not all(isinstance(x, str) for x in r.get("items", [])):
            errors.append(f"{where}: \"items\"는 [\"바뀐 점1\", \"바뀐 점2\"] 처럼 글자 목록이어야 해요.")
        if "popup" in r and not isinstance(r.get("popup"), bool):
            errors.append(f"{where}: \"popup\"은 true 또는 false여야 해요. 따옴표 없이 써요.")
        start, end = parse_time(r.get("start")), parse_time(r.get("end"))
        for key, value in (("start", start), ("end", end)):
            if value is False:
                errors.append(f"{where}: \"{key}\" 날짜 형식이 틀렸어요. \"2026-11-11 09:00\"처럼 써 주세요.")
        if start and end and start >= end:
            errors.append(f"{where}: 끝(end)이 시작(start)보다 빨라요.")

if errors:
    print("고칠 곳이 있어요:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("notices.json, releases.json 모두 앱이 읽을 수 있어요.")

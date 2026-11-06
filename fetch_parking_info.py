#!/usr/bin/env python3
"""
notiforme 주정차 정보 데이터(parking-info.json)를 공공데이터포털 오픈API로 받아 만든다.

GitHub Actions가 매달 자동으로 실행한다. (.github/workflows/update-data.yml)
직접 실행할 때:
    DATA_GO_KR_KEY=인증키 python3 fetch_parking_info.py

쓰는 데이터:
  1. 주정차 단속 CCTV → sources/cctv.json
     (전국CCTV표준데이터는 오픈API가 없어서, CSV를 받아 build_cctv.py로 미리 만들어 둔다)
  2. 전국어린이보호구역표준데이터 (오픈API) → 보호구역 시설 위치
  3. 전국주차장정보표준데이터 (오픈API)     → 주차장 위치와 이름

API 주소는 아래 기본값을 쓰고, 다르면 환경변수(SCHOOL_API, PARKING_API)로 바꾼다.
(공공데이터포털 > 마이페이지 > 활용신청한 API > "상세기능"에서 정확한 주소를 확인할 수 있다)

결과 형식은 앱의 ParkingInfoFile 과 같다.
  { "version": 3, "updatedAt": "2026-11-07",
    "cctv": [위도, 경도, 위도, 경도, ...],
    "schoolZones": [...], "parkingLots": [...],
    "parkingLotNames": ["○○ 공영주차장", ...],   # parkingLots 좌표 순서와 같음
    "parkingLotAttrs": ["GOP", ...],            # 구분·유형·요금 세 글자 (G공영/M민영, S노상/O노외, F무료/P유료/X혼합)
    "parkingLotSpaces": [120, ...] }            # 주차 면수 (모르면 0)
"""

import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# (환경변수가 비어 있으면 기본값을 쓴다. GitHub Actions에서 Variables를 안 만들면 빈 값이 들어온다)
SERVICES = {
    "school": os.environ.get("SCHOOL_API") or "https://api.data.go.kr/openapi/tn_pubr_public_child_prtc_zn_api",
    "parking": os.environ.get("PARKING_API") or "https://api.data.go.kr/openapi/tn_pubr_prkplce_info_api",
}

PAGE_SIZE = 1000
# 한국 범위를 벗어난 좌표는 잘못 입력된 값으로 보고 버린다.
LAT_RANGE = (33.0, 39.0)
LON_RANGE = (124.0, 132.0)


def fetch_all(url, key):
    """오픈API의 모든 페이지를 받아 항목(dict) 목록으로 돌려준다."""
    rows = []
    page = 1
    total = None
    while True:
        query = urllib.parse.urlencode({
            "serviceKey": key,          # 공공데이터포털의 "Decoding" 인증키 (여기서 한 번 인코딩한다)
            "pageNo": page,
            "numOfRows": PAGE_SIZE,
            "type": "json",
        })
        body = request_json(f"{url}?{query}")
        # 응답은 보통 {"response": {"header": ..., "body": ...}} 이지만, response 없이 오는 경우도 있다.
        root = body.get("response", body) if isinstance(body, dict) else {}
        header = root.get("header") or {}
        if str(header.get("resultCode", "00")) not in ("00", "0"):
            sys.exit(f"API 오류 ({url}): {header}")

        data = root.get("body") or {}
        items = data.get("items") or []
        if isinstance(items, dict):         # {"item": [...]} 형태도 있다
            items = items.get("item") or []
        if isinstance(items, dict):
            items = [items]

        if page == 1 and not items:
            # 원인을 볼 수 있도록 받은 응답 앞부분을 남긴다. (응답에 인증키는 들어 있지 않다)
            print("  받은 응답:", json.dumps(body, ensure_ascii=False)[:1500])
        rows.extend(items)

        total = int(data.get("totalCount") or 0)
        print(f"  {url.rsplit('/', 1)[-1]}: {len(rows):,}/{total:,}")
        if not items or len(rows) >= total:
            break
        page += 1
        time.sleep(0.2)                     # 서버에 부담을 주지 않도록
    return rows


def request_json(url, retries=3):
    """JSON을 받는다. 일시적인 오류는 몇 번 다시 시도한다."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                text = response.read().decode("utf-8")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # 인증키 오류 등은 XML로 온다
                sys.exit(f"JSON이 아닌 응답이 왔어요 (인증키·활용신청 확인):\n{text[:500]}")
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == retries - 1:
                sys.exit(f"요청 실패: {error}")
            time.sleep(3 * (attempt + 1))


def find_key(row, *candidates, contains=None):
    """항목에서 열 이름을 찾는다. 후보 이름이 정확히 있으면 그것을, 없으면 contains가 들어간 이름을 쓴다."""
    keys = list(row.keys())
    for candidate in candidates:
        for key in keys:
            if key.lower() == candidate.lower():
                return key
    if contains:
        for key in keys:
            if contains.lower() in key.lower():
                return key
    return None


def extract_points(rows, label, keep=lambda row: True, name_key=None, extra=None):
    """위도·경도를 뽑아 [위도, 경도, ...]로 이어 붙인다. 소수점 5자리(약 1m)로 줄이고 중복을 뺀다.
    name_key를 주면 이름 목록을, extra(row → 문자열)를 주면 그 값 목록을 같은 순서로 함께 만든다."""
    if not rows:
        sys.exit(f"{label}: 받은 데이터가 없어요.")
    lat_key = find_key(rows[0], "latitude", "lat", "la", contains="lat")
    lon_key = find_key(rows[0], "longitude", "lot", "lon", "lng", "lo", contains="lon")
    if not lat_key or not lon_key:
        sys.exit(f"{label}: 위도·경도 열을 찾지 못했어요. 있는 열: {list(rows[0].keys())}")

    seen, flat, names, extras = set(), [], [], []
    for row in rows:
        if not keep(row):
            continue
        try:
            lat = round(float(row[lat_key]), 5)
            lon = round(float(row[lon_key]), 5)
        except (TypeError, ValueError, KeyError):
            continue
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            continue
        if (lat, lon) in seen:
            continue
        seen.add((lat, lon))
        flat.extend([lat, lon])
        if name_key:
            names.append((row.get(name_key) or "").strip())
        if extra:
            extras.append(extra(row))
    return (flat, names, extras) if extra else (flat, names)


def main():
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not key:
        sys.exit("DATA_GO_KR_KEY(공공데이터포털 인증키)가 없어요.")

    print("단속 CCTV 읽는 중 (sources/cctv.json)")
    with open("sources/cctv.json", encoding="utf-8") as f:
        cctv_source = json.load(f)
    cctv = cctv_source["cctv"]
    print(f"  {len(cctv)//2:,}곳 (데이터 기준일 {cctv_source.get('dataDate', '?')})")

    print("어린이보호구역 받는 중")
    school_rows = fetch_all(SERVICES["school"], key)
    school, _ = extract_points(school_rows, "어린이보호구역")

    print("주차장 받는 중")
    parking_rows = fetch_all(SERVICES["parking"], key)
    first = parking_rows[0] if parking_rows else {}
    name_key = find_key(first, "prkplceNm", contains="nm")
    owner_key = find_key(first, "prkplceSe", contains="prkplcese")      # 주차장구분: 공영 / 민영
    type_key = find_key(first, "prkplceType", contains="type")          # 주차장유형: 노상 / 노외 / 부설
    fee_key = find_key(first, "parkingchrgeInfo", contains="chrgeinfo") # 요금정보: 무료 / 유료 / 혼합
    spaces_key = find_key(first, "prkcmprt", contains="cmprt")          # 주차구획수 (몇 대 댈 수 있는지)
    print(f"  항목: 구분={owner_key} 유형={type_key} 요금={fee_key} 면수={spaces_key}")
    if not (owner_key and type_key and fee_key):
        print(f"  ! 구분·유형·요금 항목을 다 찾지 못했어요. 있는 항목: {list(first.keys())}")

    def value(row, key):
        return str(row.get(key) or "") if key else ""

    def lot_attrs(row):
        """주차장 특성을 세 글자로 줄인다. 앱의 ParkingLotAttributes와 같은 규칙.
        1) 구분 G=공영 M=민영  2) 유형 S=노상 O=노외 B=부설  3) 요금 F=무료 P=유료 X=혼합  (모르면 ?)"""
        owner, kind, fee = value(row, owner_key), value(row, type_key), value(row, fee_key)
        return (
            ("G" if "공영" in owner else "M" if "민영" in owner else "?")
            + ("S" if "노상" in kind else "O" if "노외" in kind else "B" if "부설" in kind else "?")
            + ("X" if "혼합" in fee else "F" if "무료" in fee else "P" if "유료" in fee else "?")
        )

    def spaces(row):
        """주차 면수. 모르면 0"""
        try:
            return max(0, int(float(value(row, spaces_key) or 0)))
        except ValueError:
            return 0

    # 부설 주차장(건물·아파트에 딸린 곳)은 외부인이 못 쓰는 경우가 많아서 뺀다.
    # extra에는 "특성코드|면수"를 담았다가 아래에서 나눈다.
    parking, parking_names, parking_extra = extract_points(
        parking_rows, "주차장", name_key=name_key,
        keep=lambda row: "부설" not in value(row, type_key),
        extra=lambda row: f"{lot_attrs(row)}|{spaces(row)}",
    )
    parking_attrs = [item.split("|")[0] for item in parking_extra]
    parking_spaces = [int(item.split("|")[1]) for item in parking_extra]
    print(f"  공영 {sum(a[0] == 'G' for a in parking_attrs):,}곳 · 무료 {sum(a[2] == 'F' for a in parking_attrs):,}곳 (부설 제외)")

    # 너무 적으면 API 형식이 바뀐 것일 수 있으니 덮어쓰지 않는다.
    if len(cctv) // 2 < 100 or len(school) // 2 < 100 or len(parking) // 2 < 100:
        sys.exit(f"받은 개수가 너무 적어요 (CCTV {len(cctv)//2}, 보호구역 {len(school)//2}, 주차장 {len(parking)//2}). 파일을 바꾸지 않아요.")

    result = {
        "version": 3,
        "updatedAt": datetime.date.today().isoformat(),
        "cctv": cctv,
        "schoolZones": school,
        "parkingLots": parking,
        "parkingLotNames": parking_names,
        "parkingLotAttrs": parking_attrs,
        "parkingLotSpaces": parking_spaces,
    }
    with open("parking-info.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize("parking-info.json") / 1024
    print(f"단속 CCTV {len(cctv)//2:,}곳 · 어린이보호구역 {len(school)//2:,}곳 · 주차장 {len(parking)//2:,}곳")
    print(f"→ parking-info.json ({size_kb:,.0f} KB)")


if __name__ == "__main__":
    main()

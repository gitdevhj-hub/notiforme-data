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
  4. 전국무인교통단속카메라표준데이터 (오픈API, 경찰청) → 주정차 단속 카메라, 어린이·노인보호구역 카메라 (과속·신호만 하는 카메라는 뺀다)

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
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# (환경변수가 비어 있으면 기본값을 쓴다. GitHub Actions에서 Variables를 안 만들면 빈 값이 들어온다)
SERVICES = {
    "school": os.environ.get("SCHOOL_API") or "https://api.data.go.kr/openapi/tn_pubr_public_child_prtc_zn_api",
    "parking": os.environ.get("PARKING_API") or "https://api.data.go.kr/openapi/tn_pubr_prkplce_info_api",
    # 전국무인교통단속카메라표준데이터 (경찰청). 활용신청이 안 돼 있으면 건너뛰고 지난 데이터를 그대로 쓴다.
    "camera": os.environ.get("CAMERA_API") or "https://api.data.go.kr/openapi/tn_pubr_public_unmanned_traffic_camera_api",
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


def fetch_cameras(key):
    """무인교통단속카메라를 받아 (좌표, 특성) 두 목록으로 돌려준다. 실패하면 None (지난 데이터를 그대로 쓴다)
    특성은 "단속구분|제한속도|도로노선방향|보호구역구분|설치장소" 글자. 코드 값은 원본 그대로 둔다."""
    print("무인교통단속카메라 받는 중")
    try:
        rows = fetch_all(SERVICES["camera"], key)
    except SystemExit as error:
        print(f"  ! 무인교통단속카메라를 받지 못했어요 (활용신청·인증키 확인): {error}")
        return None
    if not rows:
        print("  ! 무인교통단속카메라 데이터가 비어 있어요.")
        return None
    first = rows[0]
    print(f"  있는 항목: {list(first.keys())}")
    kind_key = find_key(first, "regltSe", contains="regltse")          # 단속구분
    limit_key = find_key(first, "lmttVe", contains="lmtt")            # 제한속도
    dir_key = find_key(first, "roadRouteDrc", contains="drc")         # 도로노선방향
    zone_key = find_key(first, "prtcareaType", contains="prtcarea")   # 보호구역구분
    place_key = find_key(first, "itlpc", contains="itlpc")            # 설치장소
    print(f"  항목: 단속구분={kind_key} 제한속도={limit_key} 방향={dir_key} 보호구역={zone_key} 설치장소={place_key}")

    def clean(row, key):
        return str(row.get(key) or "").replace("|", " ").strip() if key else ""

    def codes(text):
        """"01+02", "4", "04" → {"1", "2"} / {"4"} (앞의 0을 뗀다)"""
        return {part.strip().lstrip("0") for part in text.replace(",", "+").split("+") if part.strip()}

    def camera_kind(row):
        """단속구분 → 한 글자. 실제 데이터의 설치장소·제한속도로 확인한 뜻:
        1 과속(S), 2 신호·과속(T), 3·4 주정차 등(P, 제한속도 0이 많음), 99 그 밖(O, 구간단속 등)"""
        found = codes(clean(row, kind_key))
        if found & {"3", "4"}: return "P"
        if "2" in found: return "T"
        if "1" in found: return "S"
        return "O"

    def camera_zone(row):
        """보호구역구분 → 한 글자. 2 어린이(C), 1 노인(E), 99·빈칸 없음(-)"""
        found = codes(clean(row, zone_key))
        if "2" in found: return "C"
        if "1" in found: return "E"
        return "-"

    def speed(row):
        try:
            return str(int(float(clean(row, limit_key) or 0)))
        except ValueError:
            return "0"

    def keep(row):
        """주차와 관계있는 카메라만 남긴다: 주정차 단속 카메라, 어린이·노인보호구역 카메라"""
        return camera_kind(row) == "P" or camera_zone(row) in ("C", "E")

    # 특성: "종류보호구역|제한속도|설치장소" 예) "PC|30|○○초교 앞"  (설치장소는 40자까지)
    points, _, attrs = extract_points(
        rows, "무인교통단속카메라", keep=keep,
        extra=lambda row: f"{camera_kind(row)}{camera_zone(row)}|{speed(row)}|{clean(row, place_key)[:40]}",
    )
    from collections import Counter
    print(f"  전체 {len(rows):,}곳 중 주차 관련 {len(points)//2:,}곳 남김 · 종류 {dict(Counter(a[:2] for a in attrs).most_common())}")
    return points, attrs


def previous_cameras():
    """지난번 파일에 있던 카메라 (이번에 못 받았을 때 쓴다)"""
    try:
        with open("parking-info.json", encoding="utf-8") as f:
            old = json.load(f)
        return old.get("cameras") or [], old.get("cameraAttrs") or []
    except (OSError, json.JSONDecodeError):
        return [], []


def address_road(address):
    """도로명주소에서 도로 이름만: "서울특별시 종로구 세종대로 12" → "세종대로", "중앙로123번길 4" → "중앙로123번길" """
    match = re.search(r"(\S+(?:대로|로|길))\s+(?:지하\s*)?\d", address)
    return match.group(1) if match else ""


def build_roads_file(result, school_roads):
    """표준노드링크(Release "nodelink"의 zip)가 있으면 카메라를 도로에 붙인 parking-roads.bin을 만든다.
    실패해도 주정차 정보는 그대로 올린다. 앱은 updatedAt이 다른 도로 파일은 쓰지 않는다."""
    zips = sorted(glob.glob("nodelink/*.zip") + glob.glob("nodelink/*.ZIP"))
    if not zips:
        print("도로망(nodelink/*.zip)이 없어서 도로 파일은 만들지 않아요.")
        return 0
    try:
        import build_roads
        print(f"도로망에 카메라 붙이는 중 ({os.path.basename(zips[-1])})")
        cctv, cameras, attrs = result["cctv"], result["cameras"], result["cameraAttrs"]
        targets = [(cctv[i], cctv[i + 1], build_roads.PARKING_RANGE, None, build_roads.SNAP) for i in range(0, len(cctv), 2)]
        for i in range(0, len(cameras), 2):
            code = attrs[i // 2]
            # 어린이보호구역 카메라는 더 넓게, 주정차 카메라는 보통, 그 밖(노인보호구역 과속 등)은 붙이기만
            reach = build_roads.ZONE_RANGE if code[1:2] == "C" else build_roads.PARKING_RANGE if code[:1] == "P" else 0
            targets.append((cameras[i], cameras[i + 1], reach, None, build_roads.SNAP))
        # 어린이보호구역 시설: 주소 도로(정문 앞 도로)에 붙인다. 주소 도로를 모르면 붙이지 않는다.
        zones = result["schoolZones"]
        for i in range(0, len(zones), 2):
            road = school_roads[i // 2] if i // 2 < len(school_roads) else ""
            targets.append((zones[i], zones[i + 1], build_roads.SCHOOL_RANGE, road or "\0", build_roads.SCHOOL_SNAP))
        roads, target_roads, stats = build_roads.build(zips[-1], targets)
        count = len(cctv) // 2
        camera_count = len(cameras) // 2
        blob = build_roads.encode(
            roads, target_roads[:count], target_roads[count:count + camera_count], result["updatedAt"],
            school_roads=target_roads[count + camera_count:],
        )
        with open("parking-roads.bin", "wb") as f:
            f.write(blob)
        print(f"  링크 {stats['links']:,}개 중 카메라 근처 선 {stats['pieces']:,}개 · 도로 {stats['roads']:,}개 · "
              f"카메라 {stats['attached']:,}/{stats['targets']:,}곳 붙음 → parking-roads.bin ({len(blob)/1024:,.0f} KB)")
        return len(blob)
    except Exception as error:  # 도로 파일은 없어도 앱이 거리로 판단한다
        print(f"  ! 도로 파일을 만들지 못했어요: {error!r}")
        return 0


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
    address_key = find_key(school_rows[0] if school_rows else {}, "rdnmadr", contains="rdnmadr")
    if not address_key:
        print(f"  ! 도로명주소 항목을 찾지 못했어요. 있는 항목: {list((school_rows or [{}])[0].keys())}")
    # 시설 주소의 도로 이름(정문 앞 도로일 가능성이 높다). 앱 파일에는 넣지 않고 도로 파일을 만들 때만 쓴다.
    school, _, school_roads = extract_points(
        school_rows, "어린이보호구역",
        extra=lambda row: address_road(str(row.get(address_key) or "")) if address_key else "",
    )
    print(f"  주소에서 도로 이름을 찾은 시설 {sum(bool(r) for r in school_roads):,}곳")

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

    cameras = fetch_cameras(key)
    if cameras is None:
        cameras = previous_cameras()
        print(f"  지난 데이터의 카메라 {len(cameras[0])//2:,}곳을 그대로 써요.")
    camera_points, camera_attrs = cameras

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
        # 무인교통단속카메라 (경찰청). 앱의 예전 버전은 이 항목을 읽지 않고 그냥 넘어간다.
        "cameras": camera_points,
        "cameraAttrs": camera_attrs,   # "종류보호구역|제한속도|설치장소". 종류 P주정차 S과속 T신호 O그밖, 보호구역 C어린이 E노인 -없음
    }
    with open("parking-info.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize("parking-info.json")
    roads_bytes = build_roads_file(result, school_roads)

    # 앱이 "새 데이터가 있는지"만 가볍게 확인하는 작은 파일
    meta = {
        "updatedAt": result["updatedAt"],
        "bytes": size,
        "roadsBytes": roads_bytes,
        "counts": {
            "cctv": len(cctv) // 2, "schoolZones": len(school) // 2,
            "parkingLots": len(parking) // 2, "cameras": len(camera_points) // 2,
        },
    }
    with open("parking-info-meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"단속 CCTV {len(cctv)//2:,}곳 · 어린이보호구역 {len(school)//2:,}곳 · 주차장 {len(parking)//2:,}곳 · 무인단속카메라 {len(camera_points)//2:,}곳")
    print(f"→ parking-info.json ({size/1024:,.0f} KB)")


if __name__ == "__main__":
    main()

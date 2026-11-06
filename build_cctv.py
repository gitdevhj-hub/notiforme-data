#!/usr/bin/env python3
"""
전국CCTV표준데이터 CSV → sources/cctv.json (주정차 단속 CCTV 위치만)

전국CCTV표준데이터는 오픈API 없이 CSV 파일로만 제공돼서, 몇 달에 한 번 직접 받아 이 스크립트로 줄인다.
  파일 받기: https://www.data.go.kr/data/15013094/standard.do
  실행:      python3 build_cctv.py CCTV정보.csv

고르는 기준:
  - 설치목적구분이 "교통단속" (지자체의 불법 주정차 단속 카메라가 여기에 들어간다)
  - 또는 촬영방면정보에 "주정차"가 들어간 것
결과(sources/cctv.json)는 매달 자동 갱신(fetch_parking_info.py) 때 다른 데이터와 합쳐진다.
"""

import csv
import io
import json
import sys

LAT_RANGE = (33.0, 39.0)
LON_RANGE = (124.0, 132.0)


def read_rows(path):
    raw = open(path, "rb").read()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return list(csv.DictReader(io.StringIO(raw.decode(encoding))))
        except UnicodeDecodeError:
            continue
    sys.exit("파일을 읽을 수 없어요 (인코딩 확인)")


def column(row, *keywords):
    for keyword in keywords:
        for key in row:
            if keyword in key.replace(" ", ""):
                return key
    sys.exit(f"열을 찾을 수 없어요: {keywords} / 있는 열: {list(row.keys())}")


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python3 build_cctv.py CCTV정보.csv")
    rows = read_rows(sys.argv[1])
    purpose = column(rows[0], "설치목적")
    direction = column(rows[0], "촬영방면")
    lat_col = column(rows[0], "WGS84위도", "위도")
    lon_col = column(rows[0], "WGS84경도", "경도")
    date_col = column(rows[0], "데이터기준일자")

    seen, flat, newest = set(), [], ""
    for row in rows:
        if not (row.get(purpose) == "교통단속" or "주정차" in (row.get(direction) or "")):
            continue
        try:
            lat = round(float(row[lat_col]), 5)
            lon = round(float(row[lon_col]), 5)
        except (TypeError, ValueError):
            continue
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            continue
        if (lat, lon) in seen:
            continue
        seen.add((lat, lon))
        flat.extend([lat, lon])
        newest = max(newest, row.get(date_col) or "")

    result = {"dataDate": newest, "count": len(flat) // 2, "cctv": flat}
    with open("sources/cctv.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    print(f"전체 {len(rows):,}대 중 주정차 단속 {len(flat)//2:,}곳 → sources/cctv.json (데이터 기준일 {newest})")


if __name__ == "__main__":
    main()

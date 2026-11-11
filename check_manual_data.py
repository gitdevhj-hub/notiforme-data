"""관리자가 손으로 갱신하는 데이터가 오래됐는지 매달 확인하고, 할 때가 되면 이슈로 알린다.

1. 단속 CCTV (전국CCTV표준데이터, CSV로만 받을 수 있음)
   공공데이터포털 페이지에서 원본 수정일을 읽어, 우리 데이터 기준일보다 새로우면 알린다.
   그와 별개로 우리 데이터 기준일에서 6개월이 지나면 알린다.
2. 도로망 (표준노드링크, Release "nodelink")
   올린 지 1년이 지나면 알린다. (국가교통정보센터는 해외 접속이 막혀 새 파일이 나왔는지 확인할 수 없다)
3. 공공데이터포털 인증키 활용기간
   저장소 변수 DATA_KEY_EXPIRES(예: 2028-11-01)가 있으면 30일 전부터 알린다.

알릴 일은 notices-due/ 폴더에 "제목.md" 파일로 쓴다. Actions가 파일마다 이슈를 만든다.
"""
import datetime as dt
import json
import os
import re
import urllib.request

TODAY = dt.date.today()
OUT = "notices-due"
os.makedirs(OUT, exist_ok=True)


def due(title, body):
    print(f"→ 알림: {title}")
    with open(os.path.join(OUT, title.replace("/", "-") + ".md"), "w", encoding="utf-8") as f:
        f.write(body)


def parse_date(text):
    try:
        return dt.date.fromisoformat(text.strip()[:10])
    except ValueError:
        return None


# 1. 단속 CCTV
cctv_page = "https://www.data.go.kr/data/15013094/standard.do"
ours = parse_date(json.load(open("sources/cctv.json", encoding="utf-8")).get("dataDate", ""))
source = None
try:
    request = urllib.request.Request(cctv_page, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(request, timeout=30).read().decode("utf-8", "replace")
    for label in ("수정일", "데이터 기준일자", "등록일"):
        match = re.search(label + r"[^0-9]{0,200}?(\d{4})[-.](\d{2})[-.](\d{2})", html, re.S)
        if match:
            source = dt.date(*map(int, match.groups()))
            print(f"단속 CCTV 원본 {label}: {source}")
            break
    if not source:
        print("단속 CCTV 원본 날짜를 페이지에서 찾지 못했어요.")
except Exception as error:
    print(f"단속 CCTV 페이지를 읽지 못했어요: {error!r}")

print(f"우리 단속 CCTV 데이터 기준일: {ours}")
how_cctv = f"""하는 방법 (README "단속 CCTV"):
1. [전국CCTV표준데이터]({cctv_page})에서 CSV 받기
2. Mac에서 `python3 build_cctv.py 받은파일.csv` 실행 → sources/cctv.json이 바뀜
3. 커밋·push 하면 Actions가 주정차 정보를 다시 만들어요
"""
if ours and source and source > ours:
    due("단속 CCTV 데이터 갱신 필요", f"공공데이터포털의 전국CCTV표준데이터가 새로 바뀌었어요. (원본 {source}, 우리 데이터 {ours})\n\n{how_cctv}")
elif ours and (TODAY - ours).days > 183:
    # 페이지의 수정일이 실제 데이터보다 늦게 바뀌는 경우도 있어서, 6개월이 지나면 원본과 관계없이 알린다.
    due("단속 CCTV 데이터 갱신 필요", f"우리 단속 CCTV 데이터가 6개월 넘었어요. (기준일 {ours}, 원본 페이지 날짜 {source or '확인 못 함'})\n새 데이터가 있는지 확인해 주세요.\n\n{how_cctv}")

# 2. 도로망
published = parse_date(os.environ.get("NODELINK_PUBLISHED", ""))
print(f"도로망 올린 날: {published}")
if published and (TODAY - published).days > 365:
    due("도로망(표준노드링크) 갱신 필요", f"""도로망을 올린 지 1년이 넘었어요. (올린 날 {published})
새 도로에 생긴 카메라가 도로에 붙지 않아 거리로만 판단돼요.

하는 방법 (README "도로망: 표준노드링크"):
1. [국가교통정보센터 표준노드링크](https://www.its.go.kr/nodelink/nodelinkRef)에서 맨 위 최신 NODELINKDATA.zip 받기
2. [Release nodelink](https://github.com/gitdevhj-hub/notiforme-data/releases/tag/nodelink) → Edit → 예전 zip 지우고 새 zip 올리기 → Update release
""")

# 3. 인증키
expires = parse_date(os.environ.get("DATA_KEY_EXPIRES", ""))
print(f"인증키 만료일: {expires or '(DATA_KEY_EXPIRES 없음)'}")
if expires and (expires - TODAY).days <= 30:
    due("공공데이터포털 인증키 연장 필요", f"""공공데이터포털 인증키 활용기간이 {expires}에 끝나요. 끝나면 매달 자동 갱신이 실패해요.

하는 방법:
1. [공공데이터포털 마이페이지](https://www.data.go.kr/iim/main/mypageMain.do) > 데이터활용 > Open API > 활용신청 현황
2. 신청마다 "연장 신청"
3. 연장된 만료일로 저장소 변수 DATA_KEY_EXPIRES를 바꾸기 (Settings > Secrets and variables > Actions > Variables)
""")

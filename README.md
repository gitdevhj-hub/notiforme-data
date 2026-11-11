# notiforme-data

notiforme 앱의 "주정차 정보" 기능이 쓰는 공공데이터 파일을 만들고 보관하는 저장소예요.

- **parking-info.json**: 앱이 내려받는 파일
  (주정차 단속 CCTV, 어린이보호구역, 주차장 위치와 이름)
- **parking-roads.bin**: 카메라를 도로에 붙인 도로 파일 (앱이 "같은 도로인지" 판단할 때 씀, 약 1.4MB)
- 매달 GitHub Actions가 공공데이터포털 오픈API로 새로 받아 갱신해요.
  (`.github/workflows/update-data.yml`, `fetch_parking_info.py`)

## 처음 설정

1. 공공데이터포털(data.go.kr)에서 아래 두 데이터의 **오픈API 활용신청**
   - [전국어린이보호구역표준데이터](https://www.data.go.kr/data/15012891/standard.do)
   - [전국주차장정보표준데이터](https://www.data.go.kr/data/15012896/standard.do)
2. 마이페이지에서 **일반 인증키(Decoding)** 복사
3. 이 저장소 Settings > Secrets and variables > Actions > **New repository secret**
   - Name: `DATA_GO_KR_KEY`
   - Secret: 복사한 인증키
4. Actions 탭 > "주정차 정보 데이터 갱신" > **Run workflow**

API 주소가 기본값과 다르면 같은 화면의 Variables 탭에 `SCHOOL_API`, `PARKING_API`로 넣으면 돼요.

## 단속 CCTV (몇 달에 한 번 직접)

[전국CCTV표준데이터](https://www.data.go.kr/data/15013094/standard.do)는 오픈API가 없고 CSV로만 받을 수 있어요.

1. CSV 내려받기 (약 80MB)
2. `python3 build_cctv.py CCTV정보.csv` → `sources/cctv.json` (주정차 단속용만, 약 250KB)
3. `sources/cctv.json`을 올리면 Actions가 자동으로 parking-info.json을 다시 만들어요.

고르는 기준: 설치목적구분이 "교통단속"이거나 촬영방면정보에 "주정차"가 들어간 CCTV

## 도로망: 표준노드링크 (1년에 한두 번 직접)

국가교통정보센터는 해외 접속을 막아 두어서 Actions가 직접 받지 못해요. 한국에서 받아 Release에 올려 주세요.

1. [국가교통정보센터 표준노드링크](https://www.its.go.kr/nodelink/nodelinkRef)에서 맨 위 최신 `NODELINKDATA.zip` 받기 (약 250MB, 압축 풀지 않음)
2. [Releases](https://github.com/gitdevhj-hub/notiforme-data/releases)에서 `nodelink` 릴리스를 열고 Edit
   → 예전 zip은 지우고(휴지통 아이콘) 새 zip을 끌어다 놓기 → Update release
3. 올리면 Actions가 자동으로 parking-roads.bin을 다시 만들어요. (`build_roads.py`)

만드는 방법: 카메라 근처(주정차 100m, 어린이보호구역 150m + 25m)의 도로 구간만 남기고,
이름이 같은 도로는 하나로 묶고, 카메라마다 가장 가까운 도로(25m 안)를 붙여요.
매달 카메라 데이터가 바뀌면 마지막으로 올린 도로망에 다시 붙여요.

## 공지사항·업데이트 내역 관리

앱 업데이트 없이 여기서 파일만 고치면 앱에 바로 반영돼요. (GitHub 서버 캐시 때문에 최대 5분쯤 걸릴 수 있어요)

**파일 안에 설명이 있어요:** 두 파일 모두 맨 위 `_설명`에 항목별 뜻, `_예시`에 그대로 복사해 쓸 수 있는 모양이 있어요. 앱은 `_`로 시작하는 항목을 읽지 않아요.

**고치는 법 (웹에서):** 저장소에서 파일 이름 클릭 → 오른쪽 위 연필 아이콘 → 고치기 → 오른쪽 위 "Commit changes" → 다시 "Commit changes"
고친 뒤 [Actions 탭](../../actions)에 초록 체크가 뜨면 형식이 맞는 거예요. 빨간 X면 눌러서 무엇이 틀렸는지 보고 고쳐요.

### 공지사항: `notices.json`

```json
{
  "notices": [
    {
      "id": "2026-11-maintenance",
      "title": "서버 점검 안내",
      "body": "11월 12일 새벽 2시부터 4시까지 주정차 정보 데이터 점검이 있어요.",
      "start": "2026-11-11 09:00",
      "end": "2026-11-12 04:00",
      "canUseApp": true,
      "link": "https://example.com",
      "linkTitle": "자세히 보기"
    }
  ]
}
```

| 항목 | 뜻 | 꼭 써야 하나 |
|---|---|---|
| `id` | 공지마다 다른 이름. "일주일 동안 보지 않기"를 공지별로 기억할 때 써요. 내용을 크게 바꿔서 다시 보여주고 싶으면 id도 바꿔요. | 필수 |
| `title` | 제목 | 필수 |
| `body` | 내용. 줄을 바꾸려면 `\n` | 필수 |
| `start`, `end` | 보여줄 기간. `"2026-11-11 09:00"`처럼 한국 시간. 비우거나 빼면 제한 없음. end 시각이 되면 사라져요. | 선택 |
| `canUseApp` | `true`: 앱을 쓸 수 있음 → [닫기] [일주일 동안 보지 않기] 버튼<br>`false`: 앱을 쓸 수 없음 → 화면을 덮고 닫을 수 없음, [다시 확인] 버튼만 | 필수 (따옴표 없이) |
| `link`, `linkTitle` | 공지 안에 넣을 링크와 그 글자 | 선택 |

- 앱을 켤 때마다(1분에 한 번까지) 확인해서, 기간 안의 공지를 바로 띄워요.
- [닫기]를 누르면 다음에 앱을 켤 때 다시 떠요. [일주일 동안 보지 않기]는 그 공지만 일주일 동안 안 떠요.
- 공지가 여러 개면 위에 있는 것부터 하나씩 떠요. `canUseApp: false` 공지는 무조건 먼저 떠요.
- 공지를 끝내려면 그 공지를 지우거나 `end`를 지난 시각으로 바꿔요.

### 업데이트 내역: `releases.json`

```json
{
  "releases": [
    {
      "version": "1.0.1",
      "date": "2026-12-01",
      "title": "주차장 안내가 좋아졌어요",
      "items": ["바뀐 점 하나", "바뀐 점 둘"]
    }
  ]
}
```

- 새 버전은 **맨 위**에 추가해요. 앱은 적힌 순서 그대로 보여줘요.
- 설정 > 업데이트 내역에서 글로 보기만 해요. (앱을 켤 때 뜨지 않아요)
- `version`이 지금 설치된 앱 버전과 같으면 "지금 쓰고 있는 버전이에요"가 붙어요.

## 데이터 출처 (라이선스 표기)

출처: 공공데이터포털(www.data.go.kr). 아래 데이터를 가공해 사용해요.

| 데이터 | 제공 기관 | 쓰는 곳 | 원본 |
|---|---|---|---|
| 전국CCTV표준데이터 | 행정안전부 (지방자치단체 제공) | 주정차 단속 CCTV 위치 | [data.go.kr/data/15013094](https://www.data.go.kr/data/15013094/standard.do) |
| 전국무인교통단속카메라표준데이터 | 경찰청 · 지방자치단체 | 무인 단속 카메라 위치·단속 종류·제한속도·보호구역 여부 | [data.go.kr/data/15028200](https://www.data.go.kr/data/15028200/standard.do) |
| 전국어린이보호구역표준데이터 | 경찰청 · 교육부 (지방자치단체 제공) | 어린이보호구역 대상 시설 위치 | [data.go.kr/data/15012891](https://www.data.go.kr/data/15012891/standard.do) |
| 표준노드링크 | 국토교통부 · 국가교통정보센터 | 도로 구간 (카메라가 차와 같은 도로인지) | [its.go.kr/nodelink](https://www.its.go.kr/nodelink/nodelinkRef) |
| 전국주차장정보표준데이터 | 지방자치단체 | 주차장 위치·이름·구분·요금·면수 | [공공데이터포털 검색](https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=%EC%A0%84%EA%B5%AD%EC%A3%BC%EC%B0%A8%EC%9E%A5%EC%A0%95%EB%B3%B4%ED%91%9C%EC%A4%80%EB%8D%B0%EC%9D%B4%ED%84%B0) |


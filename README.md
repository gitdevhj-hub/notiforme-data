# notiforme-data

notiforme 앱의 "주정차 정보" 기능이 쓰는 공공데이터 파일을 만들고 보관하는 저장소예요.

- **parking-info.json**: 앱이 내려받는 파일
  (주정차 단속 CCTV, 어린이보호구역, 주차장 위치와 이름)
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

## 데이터 출처

공공데이터포털(data.go.kr) 표준데이터. 각 데이터의 이용허락 범위(공공누리)를 따라요.

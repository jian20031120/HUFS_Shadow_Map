# GIS 도형 기본 모델 (2026-10-04)

현재 app.py는 GIS SHP 도형만 지도와 그림자에 사용한다. OSM-GIS 매칭 및 API 높이 보완은 실행하지 않는다. OpenStreetMap은 배경 타일이며, 기존 캠퍼스 경계는 data/campus_boundary.geojson으로 분리했다. 기존 buildings.geojson 건물은 읽지 않는다.

SHP bbox 87건을 읽고 실제 캠퍼스 polygon과 intersects 필터를 적용하여 75건을 사용한다. 경계에 걸친 건물은 GIS 원래 도형을 보존한다. 기본 조건(층당 3m, fallback 15m, 수동 입력 없음): A16 6건 / A26 5건 / fallback 64건.

높이 우선순위: 사용자 입력 > 유효 A16 > 유효 A26 × 층당 높이 > fallback. 0은 등록 높이 없음으로 처리하며 tooltip에는 원본 A16/A26을 보여준다. GIS 윤곽은 EPSG:5186에서 EPSG:4326으로 변환된다. 계산은 EPSG:32652 미터 좌표계에서 수행하고 모든 건물 바닥을 제거한 뒤 캠퍼스로 clip하고 4326으로 되돌린다. 시간·높이·도형·태양위치를 캐시 입력으로 사용한다.

참고하여 읽은 코드(전체 복사 없음):
- https://github.com/Prabin-Hasham/shadenav/blob/main/app.py
- https://github.com/Prabin-Hasham/shadenav/blob/main/shadenav/sun.py
- https://github.com/Prabin-Hasham/shadenav/blob/main/shadenav/shadows.py
- https://github.com/CMU-SALUS-Lab/salusshadow/blob/main/salusshadow.py

공통 원리인 pvlib apparent_elevation/azimuth, h/tan(elevation), 태양 반대 방향 sweep를 기존 shadow_model.py와 연결했다. shadow_model.py 자체와 ASTER 자료는 변경하지 않았다. gis_scene.py는 높이 우선순위와 전체 그림자의 건물 바닥 제거/clip을 담당한다.

검증: .venv/bin/python verify_gis_primary.py
75개 Folium 도형이 GIS geometry와 같음, 각 건물 높이 우선순위, 시간 변경, 캠퍼스 clipping, 건물 바닥 제외, CRS 왕복 오차 1mm 미만, ASTER 실행 및 수동 높이 우선 검증.

아래는 이전 구현 이력이며 OSM-GIS 매칭 구조는 현재 비활성이다.

---

## 로컬 GIS SHP 연결 (2026-10-04)

기본 높이 자료는 이제 `다운로드한 GIS SHP`다. 기존 브이월드 API는 선택 시에만 사용한다. 로컬 SHP에는 API 키가 필요 없다.

`data/public_buildings`는 별도로 내려받은 `AL_D010_41_20260909` 원본 폴더에 대한 로컬 심볼릭 링크다. 원본 3개 묶음을 복제·변경하지 않았다. 원본 폴더를 옮기면 링크도 새 위치로 변경해야 한다.

3개 묶음을 pyogrio로 직접 검사했다. 모두 EPSG:5186, CP949이며 A0~A28이 있다. A16=높이(m), A26=지상층수, A24=건물명, A25=동명, A1=GIS건물통합식별번호. 필드 의미는 아래 공식 보고서 표 5-15(본문 88~89쪽)와 대조했다.
https://www.ktdb.go.kr/DATA/pblcte/20250805093928585.pdf

전체 건수: 원본 1,000,000 / (2) 1,000,000 / (3) 298,133. 캠퍼스 bbox를 각 SHP의 CRS로 변환한 뒤 `pyogrio.read_dataframe(bbox=..., columns=..., max_features=10001)`로 83 / 4 / 0건만 읽었다. 전체 DataFrame을 만들지 않는다. 공간 인덱스가 없을 때 디스크상 검색은 발생할 수 있다.

`data/gis_buildings_cache.json`에 원래 좌표·속성의 bbox 부분집합과 WGS84 정규화 자료를 별도 저장한다. 파일명·크기·수정 시각 및 캠퍼스 경계가 바뀌면 재추출한다. 동일 자료는 날짜·시간 변경 시 재검색하지 않는다. `SHP 자료 다시 읽기`로 수동 갱신 가능하다.

캠퍼스와 겹치는 GIS 도형은 75개. OSM 24개 중 확실한 매칭 11, 불확실 10, 후보 없음 3. 확실한 매칭에서 등록 높이는 0건, 지상층수 적용은 4건(도서관 4층, 자연과학관 5층, 생활관 7층, 모현학사 5층)이다. OSM 층수 기반 1건, fallback 19건. 높이 0은 미등록으로 처리했다. 불확실한 후보에서 높이를 가져오지 않는다.

사용자 입력 > GIS 실제 높이 > GIS 층수×층당 높이 > OSM 높이 > OSM 층수×층당 높이 > fallback. 기존 공간 매칭 기준과 shadow_model.py를 그대로 유지한다. 원본 OSM geometry는 교체하지 않는다.

`data/gis_matching_report.json`은 수동 입력 없는 층당 3m/fallback 15m 조건의 감사용 결과다. 실제 앱에서는 사용자 수정값과 현재 층당 높이가 우선하며 CSV/GeoJSON에 그 결과를 담는다.

검증: `python -m unittest test_public_buildings test_gis_buildings` (7개 통과). Streamlit 실제 캐시를 사용한 ASTER·평지 모드, 수동 높이 우선, 다운로드 버튼 및 반복 실행 시 SHP 재읽기 없음 확인.

---

# 공공자료를 이용한 건물 높이 보완

공식 문서 확인: 2026-09-29. 브이월드 건축물정보 명세의 표시 갱신일: 2026-09-23.

## 데이터 선택

- 국토교통부 GIS건물통합정보 소개: https://www.data.go.kr/data/15123970/openapi.do
- 실제 연결: VWorld 2D 데이터 API 2.0 `LT_C_BLDGINFO`, `GetFeature`
- 공식 요청·속성 명세: https://www.vworld.kr/dev/v4dv_2ddataguide2_s002.do?svcIde=bldginfo&apiVer=2
- 요청 주소: https://api.vworld.kr/req/data
- 건축HUB 건축물대장(표제부 등) 대안: https://www.data.go.kr/data/15134735/openapi.do

이번 구현은 도형과 높이·층수를 같은 응답에서 받는 VWorld를 사용한다. 건축물대장 표제부를 별도로 호출하거나 이름/동일 지번만으로 연결하지 않는다. 표제부의 상세 필드/API 경로는 이번 구현에 사용하지 않았다.

공식 확인 필드: `height` 건물높이, `grnd_flr` 지상층수, `bld_nm` 건물명칭, `dong_nm` 건물동명칭. GeoJSON `geometry`로 매칭하며 `id`가 있으면 식별자로 사용한다. 없는 경우 원본 feature SHA-256 해시를 식별자로 사용한다(공식 대장 ID로 가장하지 않는다). 건물높이는 공공 등록값이지 현장 실측 보증이 아니다. 0/결측/잘못된 숫자는 높이 없음으로 처리한다.

## 사용

1. 브이월드에서 데이터 API에 사용할 인증키를 발급한다. TMAP 키와 공공데이터포털 일반 서비스키는 호환되지 않는다.
2. Streamlit 왼쪽 '공공데이터 높이 보완'에서 인증키와 발급 시 등록한 URL을 입력한다. 키는 password 입력이며 파일에 저장하지 않는다. 환경변수 `VWORLD_API_KEY`, `VWORLD_DOMAIN`도 지원한다.
3. '캠퍼스 공공자료 조회·갱신'을 누른다. 실패하면 기존 캐시를 유지하고 OSM/수동/가정 높이 계산을 계속한다.
4. 매칭 결과 표에서 등록 높이, 지상층수, 최종 적용 높이, 근거, 공공자료 ID/출처, 매칭 점수를 확인한다.
5. 최종 결과를 CSV/GeoJSON으로 다운로드하거나 '현재 보완 결과를 data 폴더에 저장'한다.

인증된 실제 캠퍼스 응답은 키 입력 전에는 검증할 수 없다. 현재 보완된 건물 수를 미리 보장하지 않는다. 자료의 누락, 도형 불일치, 오래된 높이 때문에 fallback은 남을 수 있다.

## 범위·캐시

요청 `geomFilter`에 기존 OSM 캠퍼스 polygon(WGS84)을 전달한다. 전국 조회 없음. 응답 중 내부 대표점이 캠퍼스에 있는 건물만 사용한다. EPSG:4326을 명시하고 페이지 전체를 확인한다. 최대 10페이지/10,000건, 면적 10km² 이내로 제한한다. 인증/응답/페이지 오류가 있으면 불완전한 캐시를 쓰지 않는다.

- `data/buildings.geojson`: 원본 OSM, 변경하지 않는다.
- `data/public_buildings_cache.json`: 조회 성공 후 생성. `raw_api_responses`는 API 원본 응답(인증키가 되돌아오면 삭제 처리), `normalized`는 캠퍼스 필터 및 높이/층수 숫자 검증 후의 가공 자료. 출처, 조회 시각, 키를 제외한 요청 조건, 캠퍼스 해시 포함. 키/등록 URL/오류 URL은 저장하지 않는다.
- `data/buildings_enriched.geojson`: 명시적 저장 버튼으로 생성. OSM geometry와 원래 속성을 보존하고 `height_enrichment`에 최종 높이·근거·매칭 결과·설정 추가. 사용자 입력은 현재 세션에서 계산하고 저장 버튼/다운로드로 보관한다. 이 파일을 자동으로 수동 높이 입력에 재적용하지 않는다.

조회 버튼 외에는 네트워크 요청하지 않는다. 시간/날짜/층당 높이를 바꾸어도 캐시를 재사용한다. 원본과 가공 자료는 서로 다른 이름과 객체로 보관한다.

## 매칭·우선순위

거리·면적 비교는 기존 EPSG:32652 변환을 사용한다. 30m 이내 후보를 찾고, IoU ≥ 0.60, 각 polygon 면적의 ≥ 70% 중첩, 중심점 거리 ≤ 20m를 모두 요구한다. 첫째·둘째 후보의 IoU 차이 ≥ 0.20, 동일 공공 건물에 대한 다른 OSM 후보와의 차이 ≥ 0.20도 요구한다. 이 기준은 보수적 휴리스틱이며 동일 건물을 수학적으로 보증하지 않는다. 이름은 설명용이며 판정에 사용하지 않는다. 연결되지 않은 후보 값은 높이에 반영하지 않는다.

사용자 입력 → 공공 등록 높이 → 공공 지상층수 × 설정 층당 높이 → OSM height → OSM levels × 설정 층당 높이 → fallback(또는 계산 제외).

`shadow_model.py`, ASTER 자료, TMAP 구현은 변경하지 않는다. 기본 배경 지도만 OpenStreetMap으로 선택한다.

## 검증

프로젝트 가상환경에서 `python -m unittest test_public_buildings.py`.
테스트는 합성 도형과 모의 API 응답을 사용하며 실제 공공 조회 결과로 저장하지 않는다. 우선순위, 이름만 같은 다른 건물 제외, 중복·모호한 매칭 제외, 캠퍼스 밖 제외, 페이지 누락/인증/통신 오류 시 기존 캐시 보존, 인증키 미저장을 검증한다.

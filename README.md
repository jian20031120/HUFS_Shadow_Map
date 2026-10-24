# HUFS Shadow Map

한국외국어대학교 캠퍼스의 건물·나무 그림자를 날짜와 시간에 따라 확인하는 Streamlit 프로젝트입니다.

- GIS 건물 윤곽과 등록 높이·층수에 따른 그림자 계산
- 건축물대장 자료와 GIS 건물의 자동·수동 연결
- 평지 그림자 및 ASTER 지형을 반영한 근사 계산
- 지도에서 나무 수관을 입력하고 그림자 표시
- OpenStreetMap 배경지도와 VWorld 항공영상 선택

## 실행

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

앱 실행에는 아래 GIS 원본 자료도 필요합니다. VWorld 항공영상은 앱에서 API 키를 입력하거나 `VWORLD_API_KEY` 환경변수를 설정하면 사용할 수 있습니다.

## 데이터

캠퍼스 경계, 캠퍼스 범위의 GIS 캐시, 건축물대장 가공 CSV, 연결 결과와 지형 자료는 저장소에 포함합니다.

대용량 원본 자료는 로컬에 유지하고 Git 업로드에서 제외합니다.

- `data/public_buildings`: GIS 원본 폴더 또는 해당 폴더를 가리키는 로컬 심볼릭 링크. 다른 컴퓨터에서는 원본을 별도로 준비해야 합니다. 현재 코드는 `AL_D010_41_20260909`, `AL_D010_41_20260909(2)`, `AL_D010_41_20260909(3)` 각 묶음의 `.shp`, `.dbf`, `.shx`, `.prj`, `.fix` 파일을 확인합니다. 캐시가 있어도 원본 파일 확인은 필요합니다.
- `data/building_register/mart_djy_03.txt`: 약 3.8GB의 건축물대장 원본. 현재 앱은 추출된 캠퍼스 CSV를 읽습니다.
- `data/building_master/`: 건물 원본 SHP 묶음. 가공된 연결·검증 결과는 별도로 포함합니다.

가상환경, Python 캐시, API 키·인증서 파일, 로컬 설정과 기존 작업 백업 코드는 업로드에서 제외합니다. API 키는 앱에서 입력하거나 환경변수로 설정하고 저장소에 커밋하지 마세요.

구현 이력과 자료 출처는 [PUBLIC_DATA.md](PUBLIC_DATA.md)를 참고하세요.

## 기존 검증 명령

```sh
python -m unittest test_public_buildings test_gis_buildings
python verify_gis_primary.py
```

GIS 원본을 사용하는 검증은 해당 로컬 데이터가 준비되어 있어야 합니다.

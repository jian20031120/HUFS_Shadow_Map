# 데이터와 계산

## 실행 자료

앱은 `data/`의 캠퍼스 경계, 건물 윤곽, 등록 정보와 GBA 높이 자료를 읽습니다.
앱을 켤 때 원본 자료를 다시 다운로드하지 않습니다.

| 자료 | 용도 |
| --- | --- |
| `campus_boundary.geojson` | 서비스 범위 |
| `gis_buildings_cache.json`, `buildings.geojson` | 건물 윤곽·이름 |
| `gba_campus.geojson` | 위성 기반 건물 높이 |
| `gba_height_campus.npz`, `gba_height_campus_meta.json` | 3m 높이 격자 |
| `building_register/`, `manual_matches.csv` | 등록 정보의 연결 |

원본 GIS 윤곽 75개와 OSM 보완 윤곽 9개를 사용합니다.
등록 높이 6개, 층수 추정 5개, GBA 윤곽 추정 10개, 격자 추정 53개로 74개 건물의 그림자를 계산합니다.
높이 미확보 10개는 그림자를 만들지 않지만 경로가 건물 내부를 통과하지 않도록 윤곽을 피합니다.
이름과 윤곽을 연결한 17개 건물을 목적지로 제공합니다.

연구 기록, 미확보 높이 목록, 이전 검사 결과는 `data/research/`에 보존했습니다.
이 자료는 웹 실행에 사용하지 않습니다. 원본 다운로드 캐시는 Git에서 제외되는 `.cache/downloads/`에 둡니다.

## 경로 계산

현재 위치에서 선택한 건물 바깥의 접근 지점까지 계산합니다.
격자 모델에서 햇빛 노출 거리를 먼저 줄이고, 노출 거리가 같은 후보에서는 총 이동 거리를 줄입니다.
기본 격자는 3m이며 전체 계산량에 맞춰 간격을 조정합니다.

건물 윤곽 밖의 캠퍼스 지면을 이동 가능하다고 가정합니다.
실제 통행 제한, 물 영역, 경사·울타리·계단과 출입구는 검증하지 않았습니다.
그늘은 평지와 태양 위치를 이용한 추정으로 구름과 나무 그늘을 반영하지 않습니다.
높이 추정과 격자 해상도 때문에 실제 그늘과 차이가 있으며, 전 구간 그늘이나 연속 지면의 전역 최적 경로를 보장하지 않습니다.

## 자료 갱신

기존 스냅샷으로 실행할 때는 이 과정이 필요 없습니다.
갱신이 필요할 때만 개발 의존성을 설치하고 해당 명령을 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m scripts.fetch_osm
.\.venv\Scripts\python.exe -m scripts.fetch_gba
.\.venv\Scripts\python.exe -m scripts.fetch_gba_height
```

새 자료를 수집한 뒤에는 건물 수와 높이 연결 결과를 확인해야 합니다.
기존 스냅샷과 원본 자료를 임의로 섞으면 이름·높이 연결이 달라질 수 있습니다.

## 출처와 이용 조건

- 국토교통부·VWorld GIS건물통합정보 및 건축물대장
- [GlobalBuildingAtlas · Zhu 외, 2025](https://doi.org/10.5194/essd-17-6647-2025)
- [GBA 배포 자료](https://source.coop/tge-labs/globalbuildingatlas-lod1)
- [© OpenStreetMap 기여자](https://www.openstreetmap.org/copyright)

GBA 높이는 CC BY-NC 4.0, OSM 자료는 ODbL 조건을 따릅니다.

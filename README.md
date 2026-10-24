# HUFS 그늘길

한국외국어대학교 글로벌캠퍼스에서 현재 위치부터 선택한 건물까지 그늘을 우선하는 안내선을 보여주는 웹 데모입니다.
이미 설치했다면 프로젝트 폴더의 PowerShell에서 아래 명령으로 사이트를 엽니다.

```powershell
.\.venv\Scripts\python.exe start_web.py
```

주소는 http://127.0.0.1:8501 입니다. 실행기는 서버를 시작하거나 기존 서버를 재사용하고 브라우저를 엽니다.
브라우저 없이 서버만 켜려면 명령 끝에 `--no-browser`를 붙입니다.

## 처음 설치

검증 환경은 Windows, Python 3.14입니다. 프로젝트 폴더에서 실행합니다.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe start_web.py
```

## TMAP 키 설정

프로젝트 루트의 `.env`를 열고 발급받은 TMAP 앱 키를 넣습니다. 계정 아이디·비밀번호는 입력하지 않습니다.

```dotenv
TMAP_APP_KEY=
```

키가 비어 있으면 OpenStreetMap 지도로 실행합니다. TMAP 로드에 실패하면 지도 안의 `기본 지도로 보기`를 누릅니다.
운영체제의 `TMAP_APP_KEY` 환경변수가 있으면 `.env`보다 우선합니다. 실제 `.env`와 비밀 설정은 Git에서 제외합니다.

## 사용 방법

1. `내 위치로 찾기`를 누르고 브라우저의 위치 사용에 동의합니다.
2. 도착 건물 검색에서 17개 학교 건물 중 하나를 선택합니다.
3. 녹색 면은 예상 그늘, 진한 녹색 선은 그늘 구간, 주황색 선은 햇빛 구간입니다.
4. 파란 점과 원은 현재 위치와 위치 오차, 파란 건물 윤곽은 선택한 목적지입니다.
5. 이동한 뒤에는 `위치 갱신`을 누릅니다. 건물이나 시간을 바꾸면 안내선을 다시 계산합니다.

현재 위치가 캠퍼스 안에서 확인돼야 안내선을 계산합니다. 교외에서는 건물 검색과 지도 미리보기를 사용할 수 있습니다.
위치 권한을 거부했거나 좌표가 오래됐거나 오차가 큰 경우에는 위치 갱신 안내를 따릅니다.
위치는 현재 세션에서만 사용하며 파일·URL·로그에 저장하거나 공용 계산 캐시에 넣지 않습니다.

기본 시간은 현재 한국 시각입니다. 밤에는 시간 메뉴에서 오전 9시·정오 12시·오후 3시를 선택해 시연할 수 있습니다.
휴대폰 위치 기능에는 HTTPS가 필요합니다. PC의 localhost에서는 실행할 수 있지만 HTTP 사설 IP 접속은 제한될 수 있습니다.

## 시연 범위

안내선은 보행로에 제한하지 않고 건물 윤곽을 피하도록 계산하며, 실제 통행 가능 여부는 검증하지 않았습니다.
도착점은 건물 바깥의 계산된 접근 지점으로 실제 출입구가 아니며, 100% 그늘 경로를 보장하지 않습니다.
84개 건물 윤곽 중 높이를 확보한 74개로 그림자를 계산합니다. 추정 높이와 평지 가정이 포함돼 실제 그늘과 다를 수 있습니다.

## 폴더와 개발

```text
app.py, start_web.py   웹 실행 진입점
hufs_shadow/          지도·위치·그늘·목적지 계산
components/           브라우저 위치·시간 조작
assets/background.jpg 공통 배경
data/                 실행용 캠퍼스 자료
data/research/        보존한 조사·검증 자료
scripts/              선택적인 데이터 수집·갱신 도구
tests/                현재 기능 회귀 테스트
docs/data_sources.md  자료 출처와 계산 한계
```

개발·자료 갱신 도구와 테스트가 필요할 때만 추가 의존성을 설치합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

자료 출처와 수집·추정의 한계는 [데이터 안내](docs/data_sources.md)를 참고하세요.

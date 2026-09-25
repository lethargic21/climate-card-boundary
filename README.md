# 경계에서 끊긴 혜택 - 기후동행카드 역별 지하철 승차 Staggered DiD

팀 **사당역9번출구**가 한겨레×숲과나눔 「AI와 함께하는 교통문제 해결을 위한 데이터 분석 공모전」에 제출하는 분석의 코드와 데이터입니다.

- 보고서 PDF: [`report/사당역9번출구_분석보고서.pdf`](report/사당역9번출구_분석보고서.pdf)
- 원고: [`report/분석보고서.md`](report/분석보고서.md)

서울시 기후동행카드(2024-01-27부터)가 어느 역에서 얼마나 지하철 이용을 늘렸는지 역 단위로 추정합니다. 혜택이 끊기는 행정 경계 바로 바깥에서 무슨 일이 있었는지도 함께 봅니다. 적용 지역이 여러 차례 넓어진 점을 이용해 staggered DiD(Callaway & Sant'Anna 2021)를 씁니다.

## 핵심 결과

1. **서울 안:** 비도심 196역의 첫해 승차 효과는 +0.13%(95% CI −1.72–+1.99)로 0과 구분되지 않습니다. 출퇴근 주거지형 역은 0이고, 혼합형 역에서만 +2.1%입니다.
2. **경계 바깥:** 혜택이 끊기는 경계 바로 바깥 미적용 8역의 승차가 출시 직후부터 4.7%(SE 1.6) 줄었습니다. 역 앞 서울 버스로 옮겨 간 흔적은 없고, 적용이 확대된 뒤에도 회복되지 않았습니다.
3. **탄소:** 설문 비율 4%를 적용하면 서울 안 절감은 연 128–1,896t입니다. 경계 이탈분의 25–100%가 승용차로 갔다면 배출이 연 867–3,469t 늘 수 있습니다(조건부).

## 그림

![그림 1. 적용 연혁과 분석 역](outputs/figures/fig1_timeline_map.png)

**그림 1.** 기후동행카드 적용 연혁(왼쪽)과 분석 역 구분(오른쪽). 1차 링은 끝내 미적용인 경계 바깥 첫 두 정거장입니다(계양 제외 8역).

![그림 2. C1·C5 event-study](outputs/figures/fig2_event_study.png)

**그림 2.** 적용 전후 지하철 승차 변화(전년 같은 주 대비, 통근권 대조 역 대비). 점은 추정치, 세로선은 95% 신뢰구간(역 단위 부트스트랩 999회)입니다. 음영 왼쪽은 2022년 가짜 처리(사전추세 검정)입니다.

![그림 3. 경계 바깥 이탈](outputs/figures/fig3_boundary.png)

**그림 3.** 행정 경계 바깥의 지하철 이탈. ① 거리별 효과 ② 1차 링 8역 월별 추정 ③ 역 앞 서울 버스가 닿는 역과 닿지 않는 역의 비교.

![그림 4. 탄소 변화 범위](outputs/figures/fig4_carbon.png)

**그림 4.** 연간 CO2 변화 범위(로그 눈금). 막대는 1년차 점추정부터 95% 상한까지이고, 속 빈 점은 서울 전 역으로 외삽한 상한입니다. 계수의 출처는 [`data/reference/emission_factors.csv`](data/reference/emission_factors.csv)에 있습니다.

모든 수치의 원표는 `outputs/tables/`에 있습니다. 결정·가정·진행 기록은 [`STATUS.md`](STATUS.md)에 있습니다.

## 재현

### 1. 환경

[uv](https://docs.astral.sh/uv/)로 고정합니다. Python 3.12이고, 직접 의존성은 `pyproject.toml`, 전체는 `uv.lock`에 있습니다.

```bash
uv sync
```

pip를 쓰려면 `pip install -r requirements.txt`(uv.lock에서 내보낸 고정 목록)도 됩니다. 작업 폴더가 OneDrive 같은 동기화 폴더 안이면 `UV_PROJECT_ENVIRONMENT`로 가상환경을 폴더 밖에 두세요.

### 2. 데이터 받기 (`01`, 원본은 `data/raw/`에 저장, 커밋 제외, 약 240MB)

[서울 열린데이터광장](https://data.seoul.go.kr)에 가입해 **일반 인증키**를 받은 뒤 `.env`에 넣습니다. 형식은 `.env.example`을 따릅니다.

```bash
cp .env.example .env   # SEOUL_API_KEY=발급받은 키
uv run python src/01_fetch_ridership.py probe                              # 제공 기간·노선 점검
uv run python src/01_fetch_ridership.py files --start 2022 --end 2022      # 2022 일별(연 파일)
uv run python src/01_fetch_ridership.py files --start 202301 --end 202608  # 2023년부터 일별(월 파일)
uv run python src/01_fetch_ridership.py daily --start 20260901 --end 20260921
uv run python src/01_fetch_ridership.py hourly --start 201901 --end 201912
uv run python src/01_fetch_ridership.py hourly --start 202201 --end 202608
uv run python src/01_fetch_ridership.py geo                                # 역·정류장 좌표
uv run python src/01_fetch_ridership.py bus --start 202301 --end 202512    # 서울 버스 정류장별 승차
```

이미 받은 파일은 건너뜁니다. 일별 API는 최근 약 7개월만 보관하므로, 과거 일별 자료는 데이터셋 파일로 받습니다(`files`).

### 3. 분석 (전체 약 2분)

`03`이 `02`보다 먼저입니다. `02`가 `03`이 만든 역 배정표(`cohort_map.csv`)를 쓰기 때문입니다.

```bash
uv run python src/03_cohort_map.py        # 역별 코호트·제외 사유 → data/reference/cohort_map.csv
uv run python src/02_build_panel.py       # 역 × 주·월 패널 → data/processed/
uv run python src/04_did_cs.py            # CS-DiD 주 사양·강건성·2019 진단·HonestDiD
uv run python src/05_event_study.py       # 진단용 event-study 그림
uv run python src/06_heterogeneity.py     # 역 유형 군집·유형별 효과, 시간대·요일, 경계 흡수·1차 링 보강
uv run python src/07_bus_substitution.py  # 경계 이탈의 서울 버스 대체 검정
uv run python src/08_carbon.py            # 탄소 범위, 경계 역효과, 서울시 발표 역산
uv run python src/09_figures.py           # 보고서 그림 4장
uv run python report/build_pdf.py         # 보고서 PDF(Chrome 또는 Edge 필요)
```

- `06_heterogeneity.py`는 인자로 일부만 돌릴 수 있습니다(`types` `tod` `boundary` `ring`).
- 실행 결과표는 모두 `outputs/tables/`에 쓰입니다. 부트스트랩 시드가 고정되어 있어 같은 결과가 재현됩니다.

### 포함된 파생 데이터

`data/processed/`(약 3MB)는 저장소에 포함했습니다: 주·월 패널, 2023년 역별 시간대 프로필, 역 유형.

- 그래서 원본을 받지 않고도 `04`·`05`·`06`·`08`을 바로 돌릴 수 있습니다.
- `07`과 `09`는 원본의 좌표·버스 자료가 필요합니다(`01 geo`·`bus`).
- 파생 데이터를 처음부터 다시 만들려면 2절의 수집 뒤 `03` → `02` → `06 types` 순서로 실행합니다.

## 데이터 출처

| 자료 | 제공처 | 받는 법 | 쓰는 곳 |
|---|---|---|---|
| 역별 일별 승하차 | 서울 열린데이터광장 [OA-12914](https://data.seoul.go.kr/dataList/OA-12914/S/1/datasetView.do) 「서울시 지하철호선별 역별 승하차 인원 정보」 | `01 files`(데이터셋 파일), `01 daily`(API `CardSubwayStatsNew`) | 주 패널 |
| 역별 월×시간대 승하차 | 서울 열린데이터광장 API `CardSubwayTime` | `01 hourly` | 월 패널, 역 유형, 행락형 판정 |
| 버스 노선·정류장별 승차 | 서울 열린데이터광장 API `CardBusTimeNew` | `01 bus` | 버스 대체 검정 |
| 역·정류장 좌표 | 서울 열린데이터광장 API `subwayStationMaster`, `busStopLocationXyInfo` | `01 geo` | 버스 연결, 지도 |
| 적용 연혁 | 서울시 보도자료 | 수작업, 원문 주소는 [`cohort_timeline.csv`](data/reference/cohort_timeline.csv) | 처리 코호트 |
| 탄소 계수 | 서울시 교통이용 통계·차량 통행속도, 국가교통DB, 환경부 온실가스종합정보센터 배출계수, 서울시 기후동행카드 보도자료 | 수작업, 원문 주소는 [`emission_factors.csv`](data/reference/emission_factors.csv) | 탄소 환산 |

- 열린데이터광장 자료는 공공누리 제1유형(출처표시)입니다.
- 이 자료에는 신분당선, 김포골드라인, 인천도시철도, 경전철, 경기 버스가 없습니다.

## 구조

```
data/raw/        원본(커밋 제외)          data/reference/  규칙·수작업 참조표(출처 포함)
data/processed/  파생 패널(포함)          src/             01–09 파이프라인
outputs/         그림·결과표              report/          보고서 원고와 PDF 빌드
```

# 기후동행카드 자연실험 — 역별 지하철 승차 Staggered DiD

서울시 기후동행카드(2024-01-27~)가 **어느 역에서 얼마나** 지하철 이용을 늘렸는지 역 단위로 추정합니다.
함께 **혜택이 끊기는 행정 경계 바로 바깥에서 무슨 일이 있었는지**와 탄소 환산 범위를 봅니다.
적용 지역이 여러 차례 넓어진 점을 이용해 staggered DiD(Callaway & Sant'Anna 2021)를 씁니다.

> 한겨레×숲과나눔 「AI와 함께하는 교통문제 해결을 위한 데이터 분석 공모전」 제출용 — 보고서 초안 단계
> (`report/분석보고서_초안.md`, PDF는 `report/build_pdf.py`로 생성)

## 주요 결과 (초안)

- **서울 안의 평균 효과는 작습니다.** 서울 비도심 196역의 첫해 승차 효과는 +0.13%(95% CI −1.72~+1.99%)입니다. 사전추세 가짜 처리는 +0.09%(SE 0.77)였습니다.
  - 역 유형(k-means)별로 보면 출퇴근 주거지형은 0이고, 혼합형에서 +2.1%(SE 0.8)입니다.
- **경계 바로 바깥에서는 이용이 줄었습니다.** 끝내 미적용인 경계 바깥 첫 두 정거장 8역의 승차가 −4.7%(SE 1.6), 하차가 −4.8% 줄었습니다. 한 단계 먼 역에서는 −1.7%입니다.
  - 역 앞 서울 버스로 옮겨 간 흔적은 없습니다: 버스가 닿는 역과 닿지 않는 역의 차이는 −0.6%p(SE 2.6)입니다.
  - 나중에 적용 지역이 넓어진 곳에서도 되돌아오지 않았습니다.
- **탄소는 범위로만 제시합니다.** 서울시 설문 비율 4%를 적용하면 연 78~1,157t입니다. 경계 이탈분의 25~100%가 승용차로 갔다면 연 +529~2,116t이 늘 수 있습니다(조건부).

| 그림 | 파일 |
|---|---|
| 1. 적용 연혁과 분석 역 구분 | [`fig1_timeline_map.png`](outputs/figures/fig1_timeline_map.png) |
| 2. C1·C5 event-study(전년 같은 주 대비) | [`fig2_event_study.png`](outputs/figures/fig2_event_study.png) |
| 3. 경계 바깥 이탈: 거리 기울기·월별 추정·서울 버스 도달별 | [`fig3_boundary.png`](outputs/figures/fig3_boundary.png) |
| 4. 탄소 변화 범위 | [`fig4_carbon.png`](outputs/figures/fig4_carbon.png) |

모든 수치의 원표는 `outputs/tables/`에 있습니다. 진행 기록과 결정, 가정은 [`STATUS.md`](STATUS.md)에 있습니다.

## 처리 코호트

| 코호트 | 적용일 | 지역 |
|---|---|---|
| C1 | 2024-01-27 | 서울 전역 (+8호선 성남 구간 등 서울시 건설 구간) |
| C2 | 2024-03-30 | 김포골드라인 (데이터 미포함) |
| C3 | 2024-08-10 | 진접선·별내선 (남양주·구리, 데이터 미포함) |
| C4 | 2024-11-30 | 고양·과천 |
| C5 | 2025-05-03 | 성남 (수인분당선·경강선) |
| C6 | 2025-08-09 | 하남 (5호선) |

근거 링크는 [`data/reference/cohort_timeline.csv`](data/reference/cohort_timeline.csv)에, 역별 배정은
[`data/reference/cohort_map.csv`](data/reference/cohort_map.csv)에 있습니다.

## 데이터

- 서울 열린데이터광장 「서울시 지하철호선별 역별 승하차 인원 정보」(OA-12914): 일별(파일 2022-01~2026-08, API 2026-09)과 월×시간대(API `CardSubwayTime`, 2019, 2022~).
  - 서울교통공사·코레일·공항철도·9호선·신림선·우이신설선이 들어 있습니다. **신분당선·김포골드라인·인천도시철도·경전철은 없습니다.**
- 서울 버스 노선·정류장별 승차(API `CardBusTimeNew`, 2023~2025), 버스정류소 위치(`busStopLocationXyInfo`), 지하철 역사 마스터(`subwayStationMaster`).
- 탄소 계수는 [`data/reference/emission_factors.csv`](data/reference/emission_factors.csv)의 가정값입니다(출처 확인 전).

## 재현

환경은 [uv](https://docs.astral.sh/uv/)로 고정합니다. Python 3.12이고, 직접 의존성은 `pyproject.toml`, 전체는 `uv.lock`에 있습니다.
pip를 쓰려면 `pip install -r requirements.txt`(uv.lock에서 내보낸 고정 목록)도 됩니다.

```bash
uv sync
cp .env.example .env   # SEOUL_API_KEY 입력
# 1) 수집 (data/raw/, 이미 받은 파일은 건너뜀)
uv run python src/01_fetch_ridership.py probe                          # 제공 기간·노선 점검
uv run python src/01_fetch_ridership.py hourly --start 201901 --end 201912
uv run python src/01_fetch_ridership.py hourly --start 202201 --end 202608
uv run python src/01_fetch_ridership.py files --start 2022 --end 2022      # 2022 일별(연 파일)
uv run python src/01_fetch_ridership.py files --start 202301 --end 202608  # 2023~ 일별(월 파일)
uv run python src/01_fetch_ridership.py daily --start 20260901 --end 20260921
uv run python src/01_fetch_ridership.py geo                            # 역·정류장 좌표
uv run python src/01_fetch_ridership.py bus --start 202301 --end 202512    # 서울 버스 정류장별 승차
# 2) 분석 (전체 약 2분)
uv run python src/03_cohort_map.py        # data/reference/cohort_map.csv
uv run python src/02_build_panel.py       # 역 × 주·월 패널
uv run python src/04_did_cs.py            # CS-DiD 주 사양·강건성·2019 진단·HonestDiD
uv run python src/05_event_study.py       # 진단용 event-study 그림
uv run python src/06_heterogeneity.py     # 역 유형 군집·유형별 효과, 시간대·요일, 경계 흡수·1차 링 보강
uv run python src/07_bus_substitution.py  # 경계 이탈의 서울 버스 대체 검정
uv run python src/08_carbon.py            # 탄소 범위, 경계 역효과, 서울시 발표 역산
uv run python src/09_figures.py           # 보고서 그림 4장
uv run python report/build_pdf.py         # 보고서 md → PDF (Chrome 또는 Edge 필요)
```

- `06_heterogeneity.py`는 인자로 일부만 돌릴 수 있습니다(`types` `tod` `boundary` `ring`).
- 작업 폴더가 OneDrive 같은 동기화 폴더 안이면 `UV_PROJECT_ENVIRONMENT`로 환경을 폴더 밖에 두세요.
- 일별 자료는 API가 최근 약 7개월만 보관하므로, 과거분은 데이터셋 파일로 받습니다.

## 구조

```
data/raw/        원본(커밋 제외)   data/reference/  수작업·규칙 기반 참조표
data/processed/  파생 패널         src/             01~09 파이프라인
outputs/         그림·표           report/          보고서 원고·PDF 빌드
```

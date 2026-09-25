# 기후동행카드 자연실험 — 역별 지하철 승차 Staggered DiD

서울시 기후동행카드(2024-01-27~)가 **어느 역에서 얼마나** 지하철 이용을 늘렸는지 역 단위로 추정하고,
탄소 절감 범위와 적용 확대 우선순위를 제안합니다. 적용 지역이 여섯 차례에 걸쳐 넓어진 점을 이용한
staggered DiD(Callaway & Sant'Anna 2021)를 씁니다.

> 한겨레×숲과나눔 「AI와 함께하는 교통문제 해결을 위한 데이터 분석 공모전」 제출용 — 작업 중

## 처리 코호트

| 코호트 | 적용일 | 지역 |
|---|---|---|
| C1 | 2024-01-27 | 서울 전역 (+8호선 성남 구간 등 서울시 건설 구간) |
| C2 | 2024-03-30 | 김포골드라인 |
| C3 | 2024-08-10 | 진접선·별내선 (남양주·구리) |
| C4 | 2024-11-30 | 고양·과천 |
| C5 | 2025-05-03 | 성남 (수인분당선·경강선) |
| C6 | 2025-08-09 | 하남 (5호선) |

근거 링크는 [`data/reference/cohort_timeline.csv`](data/reference/cohort_timeline.csv), 역별 배정은
[`data/reference/cohort_map.csv`](data/reference/cohort_map.csv).

## 데이터

- 서울 열린데이터광장 「서울시 지하철호선별 역별 승하차 인원 정보」(OA-12914) — 일별(파일·API), 월×시간대(API)
  - 서울교통공사·코레일·공항철도·9호선·신림선·우이신설선 포함, **신분당선·김포골드라인·인천도시철도 미포함**

## 재현

환경은 [uv](https://docs.astral.sh/uv/)로 고정합니다(Python 3.12, 직접 의존성은 `pyproject.toml`, 전체는 `uv.lock`).
pip를 쓰려면 `pip install -r requirements.txt`(uv.lock에서 내보낸 고정 목록)도 됩니다.

```bash
uv sync
cp .env.example .env   # SEOUL_API_KEY 입력
uv run python src/01_fetch_ridership.py probe                          # 제공 기간·노선 점검
uv run python src/01_fetch_ridership.py hourly --start 201901 --end 201912
uv run python src/01_fetch_ridership.py hourly --start 202201 --end 202608
uv run python src/01_fetch_ridership.py files --start 202301 --end 202608  # 일별 CSV(데이터셋 파일)
uv run python src/01_fetch_ridership.py daily --start 20260901 --end 20260921
uv run python src/03_cohort_map.py                                     # data/reference/cohort_map.csv
uv run python src/02_build_panel.py                                    # 역 × 주·월 패널
uv run python src/04_did_cs.py                                         # CS-DiD·2019 진단·HonestDiD
uv run python src/05_event_study.py                                    # event-study 그림
uv run python src/06_heterogeneity.py                                  # 시간대·요일, 경계 흡수
```

작업 폴더가 OneDrive 같은 동기화 폴더 안이면 `UV_PROJECT_ENVIRONMENT`로 환경을 폴더 밖에 두세요.

일별 자료는 API가 최근 약 7개월만 보관하므로 과거분은 데이터셋 파일로 받습니다.
`08`(탄소)·`09`(그림) 스크립트는 작업 중입니다.

## 구조

```
data/raw/        원본(커밋 제외)   data/reference/  수작업·규칙 기반 참조표
data/processed/  파생 패널         src/             01~09 파이프라인
outputs/         그림·표           report/          보고서 원고
```

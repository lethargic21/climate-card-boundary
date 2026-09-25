"""역(복합역) × 주 패널 생성.  [미구현]

입력
- data/raw/seoul_daily_csv/CARD_SUBWAY_MONTH_YYYYMM.csv  2023-01~2026-02 일별 (데이터셋 파일, 다운로드 승인 대기)
- data/raw/seoul_daily_api/*.json                         2026-03~ 일별 (01_fetch_ridership.py daily)
- data/raw/seoul_hourly_api/*.json                        월×시간대 (강건성용 월 패널)
- data/reference/cohort_map.csv
출력
- data/processed/panel_week.parquet   complex × 주(토~금): 승차, 하차, cohort, 처리 주
- data/processed/panel_month.parquet  complex × 월

규칙: 주는 토요일 시작(처리일 6개가 모두 토요일). 역명 정규화·복합역 매핑은 cohort_map.csv를 따른다.
2026-03·2026-07 원본은 같은 행이 두 번 들어 있으므로 중복 제거 후 합산한다.
"""

if __name__ == "__main__":
    raise SystemExit("미구현 — STATUS.md '진행 > 다음 단계' 참고")

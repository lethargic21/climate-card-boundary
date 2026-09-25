"""Callaway & Sant'Anna(2021) staggered DiD.  [미구현]

결과변수 log(주간 승차) (STATUS.md 결정 필요 2), 단위 복합역, 대조군 never-treated(+후발 코호트 not-yet-treated).
순서: 사전추세 검정 → ATT(g,t) → 코호트·기간 집계. 추론은 역 클러스터 + 사전기간 가짜 처리일 분포.
입력 data/processed/panel_week.parquet → 출력 outputs/tables/att_*.csv
"""

if __name__ == "__main__":
    raise SystemExit("미구현 — STATUS.md 참고")

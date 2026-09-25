"""처리군 내부 이질성 + 경계역 흡수 효과.  [미구현]

1. 역 유형 클러스터링(AI 요소): 시간대별 승차 프로필 + 역 특성(고령 비율, 자가용 등록률, 도심 거리,
   환승 여부)으로 처리 역을 유형화
2. 유형별·특성별 하위집단 CS-DiD ATT (04_did_cs.py의 추정 함수를 하위집단에 적용)
3. 경계역 흡수 효과: boundary_in 역의 추가 효과, boundary_out 역의 변화
출력 outputs/tables/heterogeneity_*.csv
"""

if __name__ == "__main__":
    raise SystemExit("미구현 — STATUS.md 참고")

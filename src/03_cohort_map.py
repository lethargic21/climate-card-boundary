"""역(노선×역) → 처리 코호트·처리일·제외 사유 맵 생성.

입력
- data/raw/seoul_hourly_api/*.json   분석기간 역 목록(원표기)·규모 확인 (01_fetch_ridership.py hourly)
- data/reference/cohort_timeline.csv  코호트별 처리일 (공식 보도자료로 확인한 수작업 표)
출력
- data/reference/cohort_map.csv

규칙은 모두 이 파일의 사전에 있다. 산출 CSV를 손으로 고치지 말고 여기서 고친 뒤 다시 돌린다.
분석 단위는 물리적 역(complex, 환승역 합산)이다. 환승역은 개찰구 귀속 규칙 때문에 한 노선 값이
0에 가까운 경우가 많아(예: 6호선 연신내 월 70명) 노선별 값을 그대로 쓰면 안 된다.

제외 코드 (;로 연결, 공란 = 주 추정 포함)
  boundary_in / boundary_out  처리 경계의 안쪽 첫 역 / 바깥 1~2역 (흡수 효과 절에서 따로 사용)
  c1_outside_seoul            서울 밖이지만 C1부터 적용된 역(8호선 성남·7호선 광명/장암·3호선 지축)
  gtx / new_station / line_opening  분석기간 중 개통·신설 영향 (line_openings.csv)
  mixed_cohort                복합역 안에서 노선별 처리 시점이 다름
  alight_only                 출시부터 하차만 허용된 예외 구간(부분 처리)
  data_artifact               해당 노선이 서지 않는 역에 찍힌 잔여 집계(월 0~10명)
  tiny                        복합역 2023년(사전기간) 월 승차 중앙값 < 3,000명
  outside_capital_region      충남·강원 역
  leisure                     행락형 역 — 주 추정에서 뺀다(NT 역은 "전체 대조군" 강건성에는 넣는다).
                              2022-05~12(거리두기 해제 뒤, 추정 기간 밖) 일평균 승차 log의 최대−최소가
                              C1 주 표본 역 분포의 95백분위를 넘는 서울 밖 역(NT·C4~C6)
  not_in_data                 서울 데이터셋 미포함 노선·역
  no_pre_period               처리일과 개통일이 같음
"""
from __future__ import annotations

import calendar
import json

import numpy as np
import pandas as pd

from common import DATA_RAW, DATA_REFERENCE, normalize_station

ANALYSIS_START, ANALYSIS_END = "202301", "202608"
SEASON_REF = ("202205", "202212")  # 행락형 판정 기준기간
TINY_MONTHLY_ON = 3000
LEISURE_QUANTILE = 0.95

# 역명 정규화(괄호 부기 제거·개명)는 common.normalize_station
# 이름이 같은 다른 역 / 이름이 다른 같은 역
HOMONYMS = {("5호선", "양평"): "양평(5호선)", ("중앙선", "양평"): "양평(중앙선)",
            ("2호선", "신촌"): "신촌(2호선)", ("경의선", "신촌"): "신촌(경의선)"}
SAME_COMPLEX = {"총신대입구": "이수"}

# 서울 밖 역 (노선, 시도, 시군구, 역). 여기에 없으면 서울. 좌표 기반 검증 전 — STATUS.md 가정 참조.
OUTSIDE_SEOUL = [
    ("3호선", "경기", "고양시", ["지축"]),
    ("5호선", "경기", "하남시", ["미사", "하남풍산", "하남시청", "하남검단산"]),
    ("7호선", "경기", "의정부시", ["장암"]),
    ("7호선", "경기", "광명시", ["철산", "광명사거리"]),
    ("7호선", "경기", "부천시", ["까치울", "부천종합운동장", "춘의", "신중동", "부천시청", "상동"]),
    ("7호선", "인천", "부평구", ["삼산체육관", "굴포천", "부평구청", "산곡"]),
    ("7호선", "인천", "서구", ["석남"]),
    ("8호선", "경기", "성남시", ["남위례", "산성", "남한산성입구", "단대오거리", "신흥", "수진", "모란"]),
    ("경강선", "경기", "성남시", ["판교", "성남", "이매"]),
    ("경강선", "경기", "광주시", ["삼동", "경기광주", "초월", "곤지암"]),
    ("경강선", "경기", "이천시", ["신둔도예촌", "이천", "부발"]),
    ("경강선", "경기", "여주시", ["세종대왕릉", "여주"]),
    ("경부선", "경기", "광명시", ["광명"]),
    ("경부선", "경기", "안양시", ["석수", "관악", "안양", "명학"]),
    ("경부선", "경기", "군포시", ["금정", "군포", "당정"]),
    ("경부선", "경기", "의왕시", ["의왕"]),
    ("경부선", "경기", "수원시", ["성균관대", "화서", "수원", "세류"]),
    ("경부선", "경기", "화성시", ["병점", "서동탄"]),
    ("경부선", "경기", "오산시", ["세마", "오산대", "오산"]),
    ("경부선", "경기", "평택시", ["진위", "송탄", "서정리", "평택지제", "평택"]),
    ("경부선", "충남", "천안시", ["성환", "직산", "두정", "천안"]),
    ("경원선", "경기", "의정부시", ["망월사", "회룡", "의정부", "가능", "녹양"]),
    ("경원선", "경기", "양주시", ["양주", "덕계", "덕정"]),
    ("경원선", "경기", "동두천시", ["지행", "동두천중앙", "보산", "동두천", "소요산"]),
    ("경원선", "경기", "연천군", ["청산", "전곡", "연천"]),
    ("경의선", "경기", "고양시", ["한국항공대", "강매", "행신", "능곡", "대곡", "곡산", "백마", "풍산", "일산", "탄현"]),
    ("경의선", "경기", "파주시", ["야당", "운정", "금릉", "금촌", "월롱", "파주", "문산", "운천", "임진강"]),
    ("경의선", "인천", "계양구", ["계양"]),
    ("경의선", "인천", "서구", ["검암"]),
    ("경인선", "경기", "부천시", ["역곡", "소사", "부천", "중동", "송내"]),
    ("경인선", "인천", "부평구", ["부개", "부평", "백운", "동암"]),
    ("경인선", "인천", "남동구", ["간석"]),
    ("경인선", "인천", "미추홀구", ["주안", "도화", "제물포"]),
    ("경인선", "인천", "", ["도원"]),
    ("경인선", "인천", "중구", ["동인천", "인천"]),
    ("경춘선", "경기", "구리시", ["갈매"]),
    ("경춘선", "경기", "남양주시", ["별내", "퇴계원", "사릉", "금곡", "평내호평", "천마산", "마석"]),
    ("경춘선", "경기", "가평군", ["대성리", "청평", "상천", "가평", "굴봉산"]),
    ("경춘선", "강원", "춘천시", ["백양리", "강촌", "김유정", "남춘천", "춘천"]),
    ("공항철도 1호선", "인천", "계양구", ["계양"]),
    ("공항철도 1호선", "인천", "서구", ["검암", "청라국제도시"]),
    ("공항철도 1호선", "인천", "중구", ["영종", "운서", "공항화물청사", "인천공항1터미널", "인천공항2터미널"]),
    ("과천선", "경기", "과천시", ["선바위", "경마공원", "대공원", "과천", "정부과천청사"]),
    ("과천선", "경기", "안양시", ["인덕원", "평촌", "범계"]),
    ("분당선", "경기", "성남시", ["가천대", "태평", "모란", "야탑", "이매", "서현", "수내", "정자", "미금", "오리"]),
    ("분당선", "경기", "용인시", ["죽전", "보정", "구성", "신갈", "기흥", "상갈"]),
    ("분당선", "경기", "수원시", ["청명", "영통", "망포", "매탄권선", "수원시청", "매교", "수원"]),
    ("서해선", "경기", "부천시", ["원종", "부천종합운동장"]),
    ("수인선", "경기", "수원시", ["고색", "오목천"]),
    ("수인선", "경기", "화성시", ["어천", "야목"]),
    ("수인선", "경기", "안산시", ["사리"]),
    ("수인선", "경기", "시흥시", ["달월", "월곶"]),
    ("수인선", "인천", "남동구", ["소래포구", "인천논현", "호구포", "남동인더스파크"]),
    ("수인선", "인천", "연수구", ["원인재", "연수", "송도"]),
    ("수인선", "인천", "미추홀구", ["인하대", "숭의"]),
    ("수인선", "인천", "중구", ["신포", "인천"]),
    ("안산선", "경기", "군포시", ["산본", "수리산", "대야미"]),
    ("안산선", "경기", "안산시", ["반월", "상록수", "한대앞", "중앙", "고잔", "초지", "안산", "신길온천"]),
    ("안산선", "경기", "시흥시", ["정왕", "오이도"]),
    ("일산선", "경기", "고양시", ["지축", "삼송", "원흥", "원당", "화정", "대곡", "백석", "마두", "정발산", "주엽", "대화"]),
    ("장항선", "충남", "천안시", ["봉명", "쌍용"]),
    ("장항선", "충남", "아산시", ["아산", "탕정", "배방", "온양온천", "신창"]),
    ("중앙선", "경기", "구리시", ["구리"]),
    ("중앙선", "경기", "남양주시", ["도농", "양정", "덕소", "도심", "팔당", "운길산"]),
    ("중앙선", "경기", "양평군", ["양수", "신원", "국수", "아신", "오빈", "양평", "원덕", "용문", "지평"]),
]

# 서울 밖인데 C1부터 적용: 서울시가 건설한 구간(공식 이용범위 '3호선 전구간' '7호선 온수~장암' '8호선 전구간')
C1_OUTSIDE = {("3호선", "지축"), ("일산선", "지축"), ("7호선", "장암"), ("7호선", "철산"), ("7호선", "광명사거리")} | {
    ("8호선", s) for s in ["남위례", "산성", "남한산성입구", "단대오거리", "신흥", "수진", "모란"]}
SEOUL_EXCEPT = {("서해선", "김포공항"): "C4"}  # 서해선은 출시 범위 밖, 고양 확대 때 편입
LATER = {
    "C4": {"일산선": ["삼송", "원흥", "원당", "화정", "대곡", "백석", "마두", "정발산", "주엽", "대화"],
           "경의선": ["한국항공대", "강매", "행신", "능곡", "대곡", "곡산", "백마", "풍산", "일산", "탄현"],
           "과천선": ["선바위", "경마공원", "대공원", "과천", "정부과천청사"],
           "중앙선": ["구리"]},
    "C5": {"분당선": ["가천대", "태평", "모란", "야탑", "이매", "서현", "수내", "정자", "미금", "오리"],
           "경강선": ["판교", "성남", "이매"]},
    "C6": {"5호선": ["미사", "하남풍산", "하남시청", "하남검단산"]},
}

# 복합역 단위 제외 (역명 = complex 키)
BOUNDARY_IN = {"도봉산", "불암산", "신내", "양원", "구리", "강일", "복정", "남태령", "금천구청", "온수",
               "김포공항", "수색", "지축", "탄현", "정부과천청사", "오리", "이매"}
BOUNDARY_OUT = {"망월사", "회룡", "갈매", "별내", "도농", "양정", "미사", "하남풍산", "가천대", "태평", "야탑",
                "선바위", "경마공원", "석수", "관악", "광명", "역곡", "소사", "계양", "검암", "원종",
                "부천종합운동장", "한국항공대", "강매", "삼송", "원흥", "야당", "운정", "인덕원", "평촌",
                "죽전", "보정", "삼동", "경기광주"}
OPENING = {"수서": "gtx", "구성": "gtx", "성남": "gtx;new_station", "서울역": "gtx", "연신내": "gtx",
           "대곡": "gtx", "암사역사공원": "new_station", "암사": "line_opening", "능곡": "line_opening",
           "원종": "new_station", "부천종합운동장": "new_station", "청산": "new_station",
           "전곡": "new_station", "연천": "new_station", "소요산": "line_opening",
           # 신림선 단독역: 2022-05-28 개통 뒤 수요 정착기가 사전기간에 겹침(환승 복합역은 유지)
           **{s: "line_opening" for s in ["서울지방병무청", "보라매공원", "보라매병원", "당곡", "서원",
                                          "서울대벤처타운", "관악산"]}}
ALIGHT_ONLY = {"인천공항1터미널", "인천공항2터미널"}
ARTIFACT_ROWS = {("경의선", "계양"), ("경의선", "검암"), ("경의선", "김포공항")} | {
    ("7호선", s) for s in ["까치울", "부천종합운동장", "춘의", "신중동", "부천시청", "상동", "삼산체육관", "굴포천",
                          "부평구청", "산곡", "석남"]}
NOTES = {
    **{s: "서해선 직결(2023-08-26) 영향 — 사전기간 2023-09 이후 권장" for s in ["일산", "풍산", "백마", "곡산"]},
    **{s: "C1~C6 기간 하차만 허용(부분 처리) — 승차 기준으로만 분석" for s in ["미사", "하남풍산", "하남시청", "하남검단산"]},
    "구리": "적용일 미확인(2024-08-02 협약 때 미적용, 2024-11-21 보도엔 포함) — C4 가정",
    "지축": "C1 적용은 공식 이용범위('3호선 전구간')에서 추정",
    "장암": "C1 적용은 공식 이용범위('7호선 온수~장암')에서 추정",
    "철산": "C1 적용은 공식 이용범위('7호선 온수~장암')에서 추정",
    "광명사거리": "C1 적용은 공식 이용범위('7호선 온수~장암')에서 추정",
}

# 서울 데이터셋에 없는 처리·대조 역 (문서화용). (노선, 시도, 시군구, 코호트, 역, 추가 코드, 메모)
NOT_IN_DATA = [
    ("김포골드라인", "경기", "김포시", "C2", ["양촌", "구래", "마산", "장기", "운양", "걸포북변", "사우", "풍무", "고촌"], "",
     "C2 전체가 데이터 밖 — 김포시·운영사 자료 필요"),
    ("김포골드라인", "서울", "", "C2", ["김포공항"], "", ""),
    ("4호선(진접선)", "경기", "남양주시", "C3", ["별내별가람", "오남", "진접"], "", "C3 분석 불가"),
    ("8호선(별내선)", "경기", "구리시", "C3", ["장자호수공원", "구리", "동구릉"], "no_pre_period", "개통일=적용일"),
    ("8호선(별내선)", "경기", "남양주시", "C3", ["다산", "별내"], "no_pre_period", "개통일=적용일"),
    ("서해선", "경기", "고양시", "C4", ["일산", "풍산", "백마", "곡산", "대곡", "능곡"], "", "같은 역의 경의선 값만 있음"),
    ("서해선", "경기", "부천시", "NT", ["소사"], "", ""),
    ("서해선", "경기", "시흥시", "NT", ["소새울", "시흥대야", "신천", "신현", "시흥시청", "시흥능곡"], "", ""),
    ("서해선", "경기", "안산시", "NT", ["달미", "선부", "초지", "시우", "원시"], "", ""),
    ("신분당선", "서울", "", "PL", ["신사", "논현", "신논현", "강남", "양재", "양재시민의숲", "청계산입구"], "",
     "within-city placebo 후보지만 데이터셋 미제공"),
    ("신분당선", "경기", "성남시", "PL", ["판교", "정자", "미금"], "", ""),
    ("신분당선", "경기", "용인시", "PL", ["동천", "수지구청", "성복", "상현"], "", ""),
    ("신분당선", "경기", "수원시", "PL", ["광교중앙", "광교"], "", ""),
]


def load_raw() -> pd.DataFrame:
    """월×시간대 원본 전체(2022~) → 노선·정규화 역명·월·월 승차."""
    frames = [pd.DataFrame(json.loads(p.read_text(encoding="utf-8")))
              for p in sorted((DATA_RAW / "seoul_hourly_api").glob("CardSubwayTime_*.json"))]
    df = pd.concat(frames).drop_duplicates()  # 2026-03·2026-07은 같은 행이 두 번 적재돼 있음
    on_cols = [c for c in df.columns if c.endswith("_GET_ON_NOPE")]
    df["on"] = df[on_cols].apply(pd.to_numeric).sum(axis=1)
    df["line"] = df.SBWY_ROUT_LN_NM
    df["station"] = [normalize_station(ln, s) for ln, s in zip(df.line, df.STTN)]
    return df[["line", "station", "STTN", "USE_MM", "on"]]


def load_universe(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw[raw.USE_MM.between(ANALYSIS_START, ANALYSIS_END)]
    out = df.groupby(["line", "station"], sort=False).agg(
        station_raw=("STTN", lambda s: "|".join(sorted(set(s)))),
        first_month=("USE_MM", "min"), last_month=("USE_MM", "max"))
    # 규모 기준(tiny, 개찰구 공용 판정)은 사전기간(2023)만 쓴다 — 사후 승차로 표본을 고르지 않기 위해
    pre = df[df.USE_MM.str.startswith("2023")].groupby(["line", "station"]).on.median().rename("on_median_2023")
    return out.join(pre).reset_index()


def season_amplitude(raw: pd.DataFrame, rows: pd.DataFrame) -> pd.Series:
    """복합역별 기준기간 일평균 승차 log의 최대−최소. 기준기간 중 빠진 달이 있으면 NaN."""
    keys = rows.loc[~rows.artifact, ["line", "station", "complex"]]
    ref = raw[raw.USE_MM.between(*SEASON_REF)].merge(keys, on=["line", "station"])
    monthly = ref.groupby(["complex", "USE_MM"]).on.sum().reset_index()
    days = [calendar.monthrange(int(ym[:4]), int(ym[4:]))[1] for ym in monthly.USE_MM]
    monthly["y"] = np.log(monthly.on / days)
    n_ref = int(SEASON_REF[1]) - int(SEASON_REF[0]) + 1
    amp = monthly.groupby("complex").y.agg(lambda s: s.max() - s.min() if len(s) == n_ref else np.nan)
    return amp.rename("season_amp")


def add_leisure(rows: pd.DataFrame) -> None:
    """C1 주 표본의 계절 진폭 95백분위를 넘는 서울 밖 역(NT와 후발 코호트)에 leisure 코드를 붙인다.
    후발 코호트 처리 역도 같은 기준을 쓴다 — 행락형을 뺀 주 대조군에는 이런 역과 비교할 대조가 없다(예: 대공원).
    C1은 기준선을 정의하는 집단이라 적용하지 않는다."""
    main_c1 = rows[(rows.cohort == "C1") & (rows.exclude_reason == "")].drop_duplicates("complex")
    threshold = main_c1.season_amp.quantile(LEISURE_QUANTILE)
    hit = rows.cohort.isin(["NT", "C4", "C5", "C6"]) & (rows.season_amp > threshold)
    rows.loc[hit, "exclude_reason"] = [";".join(filter(None, [r, "leisure"])) for r in rows.loc[hit, "exclude_reason"]]
    print(f"행락형 기준선(C1 계절 진폭 {LEISURE_QUANTILE:.0%} 분위): {threshold:.3f} → NT {hit.sum()}행")


def assign(rows: pd.DataFrame) -> pd.DataFrame:
    where = {(ln, s): (sido, sgg) for ln, sido, sgg, names in OUTSIDE_SEOUL for s in names}
    later = {(ln, s): c for c, lines in LATER.items() for ln, names in lines.items() for s in names}

    def cohort(ln: str, s: str, sido: str) -> str:
        if (ln, s) in SEOUL_EXCEPT:
            return SEOUL_EXCEPT[(ln, s)]
        if sido == "서울" or (ln, s) in C1_OUTSIDE:
            return "C1"
        return later.get((ln, s), "NT")

    rows[["sido", "sigungu"]] = [where.get((ln, s), ("서울", "")) for ln, s in zip(rows.line, rows.station)]
    rows["cohort"] = [cohort(ln, s, sd) for ln, s, sd in zip(rows.line, rows.station, rows.sido)]
    rows["complex"] = [HOMONYMS.get((ln, s), SAME_COMPLEX.get(s, s)) for ln, s in zip(rows.line, rows.station)]
    rows["artifact"] = [(ln, s) in ARTIFACT_ROWS for ln, s in zip(rows.line, rows.station)]

    real = rows[~rows.artifact]
    cx = real.groupby("complex").agg(n_cohorts=("cohort", "nunique"), on_total=("on_median_2023", "sum"),
                                     n_lines=("line", "size"), sido=("sido", "first"))
    c1_out = set(real.loc[(real.cohort == "C1") & (real.sido != "서울"), "complex"])

    def codes(r) -> str:
        out = ["data_artifact"] if r.artifact else []
        c = r.complex
        out += ["boundary_in"] * (c in BOUNDARY_IN) + ["boundary_out"] * (c in BOUNDARY_OUT)
        out += ["c1_outside_seoul"] * (c in c1_out)
        out += OPENING[c].split(";") if c in OPENING else []
        out += ["alight_only"] * (c in ALIGHT_ONLY)
        if c in cx.index and cx.at[c, "n_cohorts"] > 1:
            out.append("mixed_cohort")
        if c in cx.index and cx.at[c, "on_total"] < TINY_MONTHLY_ON:
            out.append("tiny")
        out += ["outside_capital_region"] * (r.sido in ("충남", "강원"))
        return ";".join(dict.fromkeys(out))

    def note(r) -> str:
        out = [NOTES[r.complex]] if r.complex in NOTES else []
        if (not r.artifact and r.complex in cx.index and cx.at[r.complex, "n_lines"] > 1
                and r.on_median_2023 < 0.01 * cx.at[r.complex, "on_total"]):
            out.append("개찰구 공용 — 노선별 값 무의미, 복합역 합산만 사용")
        if r.artifact:
            out.append("해당 노선 미정차 역의 잔여 집계")
        return " / ".join(out)

    rows["exclude_reason"] = rows.apply(codes, axis=1)
    rows["note"] = rows.apply(note, axis=1)
    rows["in_data"] = "Y"
    return rows


def not_in_data_rows() -> pd.DataFrame:
    recs = []
    for ln, sido, sgg, coh, names, extra, memo in NOT_IN_DATA:
        for s in names:
            recs.append({"line": ln, "station": s, "sido": sido, "sigungu": sgg, "cohort": coh,
                         "complex": s, "exclude_reason": ";".join(filter(None, ["not_in_data", extra])),
                         "note": memo, "in_data": "N"})
    return pd.DataFrame(recs)


def main() -> None:
    timeline = pd.read_csv(DATA_REFERENCE / "cohort_timeline.csv", dtype=str)
    dates = dict(zip(timeline.cohort, timeline.treat_date))

    raw = load_raw()
    in_data = assign(load_universe(raw))
    in_data = in_data.join(season_amplitude(raw, in_data), on="complex")
    add_leisure(in_data)

    rows = pd.concat([in_data, not_in_data_rows()], ignore_index=True)
    rows["treat_date"] = rows.cohort.map(dates).fillna("")
    rows["season_amp"] = rows.season_amp.round(3)
    cols = ["station", "line", "cohort", "treat_date", "exclude_reason", "complex", "sido", "sigungu",
            "note", "in_data", "station_raw", "first_month", "last_month", "on_median_2023", "season_amp"]
    out = rows[cols].fillna("")
    out.to_csv(DATA_REFERENCE / "cohort_map.csv", index=False, encoding="utf-8-sig")

    # 요약: 주 추정에 들어가는 복합역 수 (데이터 있음 + 제외 사유 없음)
    kept = out[(out.in_data == "Y") & (out.exclude_reason == "")]
    print("주 추정 포함 복합역 수 (코호트별):")
    print(kept.groupby("cohort").complex.nunique().to_string())
    full_nt = out[(out.in_data == "Y") & (out.cohort == "NT") & out.exclude_reason.isin(["", "leisure"])]
    print(f"전체 대조군(강건성, 행락형 포함) NT 복합역: {full_nt.complex.nunique()}")
    codes = out.loc[out.in_data == "Y", "exclude_reason"].str.split(";").explode()
    print("\n제외 코드별 행 수 (데이터 있는 행):")
    print(codes[codes != ""].value_counts().to_string())
    print(f"\n총 {len(out)}행 (데이터 있음 {int((out.in_data == 'Y').sum())}, 없음 {int((out.in_data == 'N').sum())})")


if __name__ == "__main__":
    main()

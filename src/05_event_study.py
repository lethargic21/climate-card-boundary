"""Event-study 그림 — 코호트별 사전추세 진단.

C1은 월 자료(2022 포함, 전년 동기 대비)로, C4·C5·C6은 주 자료(4주 묶음)로 그린다.
처리 직전 한 주기(기준 연도)는 정의상 0이라 점을 찍지 않고 음영으로만 표시한다.
출력 outputs/figures/event_study_by_cohort.png, outputs/tables/event_study_by_cohort.csv(그림 값)
"""
from __future__ import annotations

import importlib.util
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from common import OUT_FIGURES, OUT_TABLES, ROOT  # noqa: E402

_spec = importlib.util.spec_from_file_location("did_cs", ROOT / "src" / "04_did_cs.py")
did = importlib.util.module_from_spec(_spec)
sys.modules["did_cs"] = did  # dataclass가 모듈을 sys.modules에서 찾는다
_spec.loader.exec_module(did)

INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE, SURFACE, SHADE = "#e1e0d9", "#c3c2b7", "#fcfcfb", "#f0efec"
SERIES = "#2a78d6"
PANELS = {
    "C1": ("C1 서울 — 월, 2022 사전 포함", "month"),
    "C4": ("C4 고양·과천 — 주(4주 묶음)", "week"),
    "C5": ("C5 성남 — 주(4주 묶음)", "week"),
    "C6": ("C6 하남 — 주(4주 묶음)", "week"),
}


def cohort_events(spec: "did.Spec", width: int) -> pd.DataFrame:
    wide, G, _ = did.to_wide(spec)
    cycle = 52 if spec.freq == "week" else 12
    cells, contrib = did.att_gt(wide, G, spec.base, spec.control, cycle)
    agg = did.Aggregator(cells, contrib)
    sizes = G.value_counts()
    frames = []
    for g, name in G.attrs["cohort_names"].items():
        ev = did.event_study(agg, width, select=(cells.g == g).to_numpy())
        ev["cohort"], ev["freq"], ev["n_units"] = name, spec.freq, int(sizes[g])
        frames.append(ev)
    return pd.concat(frames, ignore_index=True)


def draw(ax, ev: pd.DataFrame, title: str, freq: str) -> None:
    cycle = 52 if freq == "week" else 12
    x = ev.e_start  # 묶음 시작점
    y, lo, hi = 100 * ev.est, 100 * ev.lo, 100 * ev.hi
    ax.set_facecolor(SURFACE)
    ax.axvspan(-cycle, 0, color=SHADE, lw=0, zorder=0)
    ax.text(-cycle / 2, 0.97, "기준 연도(정의상 0)", transform=ax.get_xaxis_transform(),
            ha="center", va="top", fontsize=7.5, color=MUTED)
    ax.axhline(0, color=BASELINE, lw=1, zorder=1)
    ax.axvline(0, color=MUTED, lw=1, zorder=1)
    ax.text(0.5, 0.03, " 적용", transform=ax.get_xaxis_transform(), fontsize=7.5, color=INK2, va="bottom")
    ax.vlines(x, lo, hi, color=SERIES, lw=1.2, alpha=0.55, zorder=2)
    ax.plot(x, y, "o", ms=4.5, color=SERIES, mec=SURFACE, mew=1.2, zorder=3)
    ax.set_title(f"{title}  ·  {int(ev.n_units.iloc[0])}역", fontsize=9.5, color=INK, loc="left")
    ax.set_xlabel("적용 후 개월" if freq == "month" else "적용 후 주", fontsize=8, color=INK2)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.tick_params(colors=MUTED, labelsize=7.5, length=0)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)


def main() -> None:
    plt.rcParams.update({"font.family": "NanumGothic", "axes.unicode_minus": False})
    month = cohort_events(did.Spec("month_seasonal_2022", freq="month"), width=1)
    week = cohort_events(did.Spec("week_seasonal"), width=4)
    ev = pd.concat([month[month.cohort == "C1"], week[week.cohort != "C1"]], ignore_index=True)
    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    ev.to_csv(OUT_TABLES / "event_study_by_cohort.csv", index=False, encoding="utf-8-sig")

    fig, axes = plt.subplots(2, 2, figsize=(10, 6.4), facecolor=SURFACE)
    for ax, (name, (title, freq)) in zip(axes.flat, PANELS.items()):
        draw(ax, ev[ev.cohort == name], title, freq)
        if name == "C1":  # K-패스 2024-05-01 = C1 첫 처리월(2024-02)로부터 3개월
            ax.axvline(3, color=MUTED, lw=0.8, ls=(0, (2, 2)), zorder=1)
            ax.text(3.4, 0.90, "K-패스", transform=ax.get_xaxis_transform(), fontsize=7.5, color=INK2)
    axes[0, 0].set_ylabel("처리 - 대조 (%)", fontsize=8, color=INK2)
    axes[1, 0].set_ylabel("처리 - 대조 (%)", fontsize=8, color=INK2)
    fig.suptitle("사전추세 진단: 전년 동기 대비 log 승차, 처리 역 - 통근권 대조 역",
                 x=0.01, ha="left", fontsize=11.5, color=INK)
    fig.text(0.01, 0.005, "점 = CS-DiD 추정치, 세로선 = 95% 신뢰구간(역 단위 부트스트랩 999회). "
             "음영 = 처리 직전 1년(비교 기준). 적용 전 점이 0에서 벗어나면 평행추세 위반.",
             fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    OUT_FIGURES.mkdir(parents=True, exist_ok=True)
    out = OUT_FIGURES / "event_study_by_cohort.png"
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    print(f"저장: {out}")


if __name__ == "__main__":
    main()

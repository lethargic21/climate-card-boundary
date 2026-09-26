"""보고서 원고(md) → 주최측 [붙임2] 분석보고서 양식 레이아웃 HTML → PDF(A4). Chrome(없으면 Edge) headless로 인쇄한다.

양식 구조: 상단에 로고 2개(한겨레·숲과나눔)와 제목, 그 아래 2열 표(왼쪽 항목명 열은 회색 고정폭, 오른쪽은 내용).
- 원고의 '## 항목명' 하나가 표의 한 행이다(항목명·순서는 양식 그대로). '<!-- 표 끝 -->' 아래는 표 밖 별도 제목이다.
- 항목마다 따로 표를 만들고 항목명을 높이 0의 thead에 둔다. Chrome은 쪽이 바뀌면 thead를 되풀이하므로
  행이 쪽 경계에서 끊겨도 다음 쪽 위에 항목명이 다시 보인다.
- 내용은 문단·그림·표 단위로 표의 행을 나눠 그 사이에서만 쪽이 바뀌게 하고, 그림·표 행은 쪽 안에서 잘리지 않게 한다.
- PDF 파일명은 공모전 규칙(팀명_분석보고서.pdf)에 따라 '이름/팀명' 항목에서 만든다('이름 / 팀명'이면 '/' 뒤).
- 본문 쪽수는 '분석도구 및 참고문헌' 행을 뺀 판을 한 번 더 인쇄해 센다(양식: 본문 5장 내외, 표지·참고문헌 제외).

실행: python report/build_pdf.py [원고.md]   (기본: report/분석보고서.md)
출력: 원고와 같은 이름의 .html(중간물), 팀명_분석보고서.pdf
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
BROWSERS = [Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),   # 인쇄가 끝난 뒤 돌아온다
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")]  # 먼저 돌아올 수 있어 파일을 기다린다
TABLE_END = "<!-- 표 끝 -->"
EXCLUDED_FROM_BODY = "분석도구 및 참고문헌"
LABEL_HTML = {"정책제안 및 기대효과": "정책제안<br>및 기대효과", "분석결과 이미지(필수)": "분석결과 이미지<br>(필수)"}
HEADER = """
<header class="doc-head">
  <img class="logo hani" src="assets/BIN0002.png" alt="한겨레">
  <div class="titles">
    <div class="sub">- AI와 함께하는 교통문제 해결을 위한 데이터 분석 공모전 -</div>
    <div class="main">분석보고서</div>
  </div>
  <img class="logo sup" src="assets/BIN0001.png" alt="재단법인 숲과나눔">
</header>
"""

CSS = """
@page { size: A4; margin: 14mm 15mm 13mm 15mm;
  @bottom-center { content: counter(page); font-family: "NanumGothic"; font-size: 8pt; color: #777; } }
html { font-family: "NanumGothic", "Malgun Gothic", sans-serif; font-size: 8.7pt; line-height: 1.48; color: #141414; }
body { margin: 0; }
a { color: inherit; text-decoration: none; }
.doc-head { display: flex; align-items: center; justify-content: space-between; gap: 4mm;
  border-top: 0.9pt solid #333; border-bottom: 0.9pt solid #333; padding: 2.4mm 1mm; margin-bottom: 3.5mm; }
.doc-head .logo.hani { height: 6.6mm; }
.doc-head .logo.sup { height: 8.7mm; }
.doc-head .titles { text-align: center; flex: 1; }
.doc-head .sub { font-size: 9pt; letter-spacing: -0.2pt; color: #333; }
.doc-head .main { font-size: 17pt; font-weight: bold; letter-spacing: 1pt; margin-top: 0.6mm; }
table.item { width: 100%; border-collapse: collapse; table-layout: fixed; margin: 0; }
table.item col.lab { width: 23mm; }
table.item > thead > tr > th { height: 0; padding: 0; border-top: 0.8pt solid #444; position: relative; }
table.item > thead > tr > th.lab span { position: absolute; top: 2.3mm; left: 1mm; right: 1mm; text-align: center;
  font-size: 8.7pt; font-weight: bold; line-height: 1.35; word-break: keep-all; }
table.item > tbody > tr > td { vertical-align: top; }
table.item > tbody > tr > td.lab { background: #e3e3e3; border-left: 0.8pt solid #444; border-right: 0.6pt solid #444; }
table.item > tbody > tr > td.con { border-right: 0.8pt solid #444; padding: 0 3mm; }
table.item > tbody > tr:first-child > td { padding-top: 2.3mm; height: 7mm; }
table.item > tbody > tr:last-child > td { padding-bottom: 2.3mm; }
table.item.last > tbody > tr:last-child > td { border-bottom: 0.8pt solid #444; }
table.item > tbody > tr.keep { break-inside: avoid; }
td.con p { margin: 0 0 1.3mm; text-align: justify; word-break: keep-all; }
td.con ul, td.con ol { margin: 0 0 1.3mm; padding-left: 4.5mm; }
td.con li { margin-bottom: 0.8mm; text-align: justify; word-break: keep-all; }
td.con h3 { font-size: 9.4pt; margin: 1.2mm 0 1.4mm; padding-bottom: 0.6mm; border-bottom: 0.5pt solid #aaa; }
figure { margin: 1mm 0 2.4mm; break-inside: avoid; }
figure img { width: 84%; display: block; margin: 0 auto; }  /* 본문 5장 내외에 맞춰 그림을 줄였다 */
figcaption, p.caption { font-size: 7.6pt; line-height: 1.4; color: #3c3c3c; margin: 1mm 0 0; text-align: justify; }
div.tbl { break-inside: avoid; margin: 0.6mm 0 2.4mm; }
div.tbl p.caption { margin: 0 0 1mm; }
td.con table { border-collapse: collapse; width: 100%; font-size: 7.6pt; line-height: 1.35; break-inside: avoid; margin: 0.6mm 0 2mm; }
td.con table th, td.con table td { border-top: 0.5pt solid #b5b5b5; border-bottom: 0.5pt solid #b5b5b5;
  padding: 1.1mm 1.6mm; text-align: center; vertical-align: middle; }
td.con table th { background: #f0efeb; font-weight: bold; }
td.con table td:first-child, td.con table th:first-child { text-align: left; }
table.item.data td.con table th, table.item.data td.con table td { border: 0.5pt solid #b5b5b5; text-align: left; }
table.item.data td.con table { table-layout: fixed; font-size: 7.1pt; break-inside: auto; }
table.item.data td.con table tr { break-inside: avoid; }  /* 목록 표: 행 단위로만 다음 쪽으로(머리행 되풀이) */
table.item.data td.con table th:nth-child(1) { width: 30%; }
table.item.data td.con table th:nth-child(2) { width: 12.5%; }
table.item.data td.con table th:nth-child(3) { width: 13.5%; }
table.item.data td.con table td:nth-child(4) { word-break: break-all; font-size: 6.3pt; }
section.after h2 { font-size: 10.5pt; margin: 5mm 0 1.6mm; padding-bottom: 0.8mm; border-bottom: 0.7pt solid #666; break-after: avoid; }
section.after p { margin: 0 0 1.6mm; text-align: justify; word-break: keep-all; }
code { font-size: 7.8pt; }
"""


def to_html(md_text: str) -> str:
    out = markdown.markdown(md_text, extensions=["tables"])
    out = re.sub(r"<p>((?:그림|표) \d+\.)", r'<p class="caption"><b>\1</b>', out)
    out = re.sub(r'<p><img (.*?)\s*/?></p>\s*<p class="caption">(.*?)</p>',
                 r"<figure><img \1><figcaption>\2</figcaption></figure>", out, flags=re.S)
    # 표 캡션과 표를 한 덩어리로(쪽이 바뀌어도 떨어지지 않게)
    return re.sub(r'(<p class="caption"><b>표 \d+\.</b>.*?</p>\s*<table>.*?</table>)',
                  r'<div class="tbl">\1</div>', out, flags=re.S)


def split_blocks(md_text: str) -> list[str]:
    """빈 줄로 나눈 md 블록. 그림 줄 + '그림 N.' 캡션, '표 N.' 캡션 + 표는 한 블록으로 묶는다."""
    raw = [b.strip() for b in re.split(r"\n\s*\n", md_text) if b.strip()]
    blocks: list[str] = []
    for b in raw:
        if blocks and (b.startswith("그림 ") and blocks[-1].startswith("![")
                       or b.startswith("|") and re.match(r"표 \d+\.", blocks[-1])):
            blocks[-1] = blocks[-1] + "\n\n" + b
        else:
            blocks.append(b)
    return blocks


def render_item(label: str, md_text: str, last: bool) -> str:
    rows = []
    for b in split_blocks(md_text):
        h = to_html(b)
        # 그림·표 행은 쪽 안에서 자르지 않는다. 단 활용 데이터 목록 표는 행 단위로 다음 쪽에 이어지게 둔다
        keep = " keep" if ("<figure" in h or ("<table" in h and label != "활용 데이터")) else ""
        rows.append(f'<tr class="blk{keep}"><td class="lab"></td><td class="con">{h}</td></tr>')
    cls = "item" + (" data" if label == "활용 데이터" else "") + (" last" if last else "")
    lab = LABEL_HTML.get(label, html.escape(label))
    return (f'<table class="{cls}"><colgroup><col class="lab"><col class="con"></colgroup>'
            f'<thead><tr><th class="lab"><span>{lab}</span></th><th class="con"></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def parse(md_text: str) -> tuple[list[tuple[str, str]], str]:
    text = re.sub(r"^\s*<!--.*?-->\s*", "", md_text, count=1, flags=re.S)  # 머리 주석
    if TABLE_END not in text:
        raise ValueError(f"원고에 '{TABLE_END}' 표시가 없다")
    table_part, after = text.split(TABLE_END, 1)
    parts = re.split(r"^## (.+?)\s*$", table_part, flags=re.M)
    items = [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts), 2)]
    return items, after.strip()


def page(items: list[tuple[str, str]], after: str, title: str) -> str:
    body = "".join(render_item(lab, md, i == len(items) - 1) for i, (lab, md) in enumerate(items))
    after_html = f'<section class="after">{to_html(after)}</section>' if after else ""
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f"<style>{CSS}</style></head><body>{HEADER}{body}{after_html}</body></html>")


def print_pdf(html_path: Path, pdf_path: Path) -> int:
    browser = next((b for b in BROWSERS if b.exists()), None)
    if browser is None:
        raise FileNotFoundError("Edge·Chrome을 찾지 못함")
    pdf_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:  # 사용자 브라우저 프로필과 분리
        subprocess.run([str(browser), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={profile}", f"--print-to-pdf={pdf_path}", html_path.as_uri()],
                       check=True, timeout=180, capture_output=True)
        size = -1
        for _ in range(240):
            now = pdf_path.stat().st_size if pdf_path.exists() else -1
            if now > 0 and now == size:
                break
            size = now
            time.sleep(0.5)
        else:
            raise TimeoutError(f"PDF가 만들어지지 않음: {pdf_path}")
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf_path.read_bytes()))


def main() -> None:
    md_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE / "분석보고서.md"
    items, after = parse(md_path.read_text(encoding="utf-8"))
    names = dict(items)
    team = names.get("이름/팀명", "").strip().splitlines()[0].split("/")[-1].strip() if names.get("이름/팀명") else ""
    if not team or re.search(r'[\[\]<>:"/\\|?*]', team):
        raise ValueError("'이름/팀명' 항목에 파일명으로 쓸 수 있는 팀명이 필요하다")
    title = f"{team}_분석보고서"
    html_path, pdf_path = md_path.with_suffix(".html"), md_path.with_name(f"{title}.pdf")
    html_path.write_text(page(items, after, title), encoding="utf-8")
    total = print_pdf(html_path, pdf_path)

    # 참고문헌 행을 뺀 판을 따로 인쇄해 본문 쪽수를 센다(임시 파일은 지운다)
    tmp_html, tmp_pdf = md_path.with_name("_body_only.html"), md_path.with_name("_body_only.pdf")
    tmp_html.write_text(page([it for it in items if it[0] != EXCLUDED_FROM_BODY], after, title), encoding="utf-8")
    body_pages = print_pdf(tmp_html, tmp_pdf)
    tmp_html.unlink()
    tmp_pdf.unlink()
    print(f"저장: {pdf_path} - 전체 {total}쪽, 본문(참고문헌 행 제외) {body_pages}쪽")


if __name__ == "__main__":
    main()

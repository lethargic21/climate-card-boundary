"""보고서 원고(md) → HTML → PDF(A4). Edge(없으면 Chrome) headless로 인쇄한다.

원고의 `<!-- pagebreak -->`로 표지 / 본문 / 참고문헌을 나눈다. 본문만 따로 한 번 더 인쇄해
공모전 규정(본문 5장 이내, 표지·참고문헌 제외)을 확인할 수 있게 본문 쪽수를 출력한다.
'그림 N.'·'표 N.'으로 시작하는 문단은 캡션으로 꾸미고, 바로 앞 그림과 한 덩어리로 묶는다.

실행: python report/build_pdf.py [원고.md]   (기본: report/분석보고서_초안.md)
출력: 원고와 같은 이름의 .html, .pdf
"""
from __future__ import annotations

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
BODY_PAGE_LIMIT = 5

CSS = """
@page { size: A4; margin: 17mm 20mm 15mm 20mm;
  @bottom-center { content: counter(page); font-family: "NanumGothic"; font-size: 8pt; color: #777; } }
@page :first { @bottom-center { content: none; } }
html { font-family: "NanumGothic", "Malgun Gothic", sans-serif; font-size: 9.3pt; line-height: 1.55; color: #141414; }
body { margin: 0; }
section.body, section.back { break-before: page; }
section.cover { min-height: 245mm; display: flex; flex-direction: column; justify-content: center; }
section.cover h1 { font-size: 26pt; margin: 0 0 10pt; letter-spacing: -0.5pt; }
section.cover p { margin: 0 0 7pt; font-size: 10.5pt; }
section.cover p:nth-of-type(1) { font-size: 13pt; margin-bottom: 36pt; }
h2 { font-size: 11.6pt; margin: 9pt 0 4pt; padding-bottom: 2pt; border-bottom: 0.6pt solid #999; break-after: avoid; }
p { margin: 0 0 4.5pt; text-align: justify; word-break: keep-all; }
ul, ol { margin: 0 0 5pt; padding-left: 15pt; }
li { margin-bottom: 2pt; text-align: justify; word-break: keep-all; }
figure { margin: 5pt 0 7pt; break-inside: avoid; }
figure img { width: 100%; display: block; }
figcaption, p.caption { font-size: 7.9pt; line-height: 1.45; color: #3c3c3c; margin: 2pt 0 0; }
p.caption { margin: 6pt 0 2pt; }
div.tbl { break-inside: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 8pt; margin: 2pt 0 7pt; break-inside: avoid; }
th, td { border-top: 0.5pt solid #b5b5b5; border-bottom: 0.5pt solid #b5b5b5; padding: 1.6pt 4pt; text-align: center; }
th { background: #f2f1ed; font-weight: bold; }
td:first-child, th:first-child { text-align: left; }
code { font-size: 8pt; }
"""


def to_html(md_text: str) -> str:
    html = markdown.markdown(md_text, extensions=["tables"])
    html = re.sub(r"<p>((?:그림|표) \d+\.)", r'<p class="caption"><b>\1</b>', html)
    html = re.sub(r'<p><img (.*?)\s*/?></p>\s*<p class="caption">(.*?)</p>',
                  r"<figure><img \1><figcaption>\2</figcaption></figure>", html, flags=re.S)
    # 표 캡션과 표를 한 덩어리로(쪽이 바뀌어도 떨어지지 않게)
    return re.sub(r'(<p class="caption"><b>표 \d+\.</b>.*?</p>\s*<table>.*?</table>)',
                  r'<div class="tbl">\1</div>', html, flags=re.S)


def page(sections: list[tuple[str, str]], title: str) -> str:
    body = "".join(f'<section class="{cls}">{to_html(md)}</section>' for cls, md in sections)
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{title}</title>'
            f"<style>{CSS}</style></head><body>{body}</body></html>")


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
    md_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE / "분석보고서_초안.md"
    parts = md_path.read_text(encoding="utf-8").split("<!-- pagebreak -->")
    if len(parts) != 3:
        raise ValueError("원고는 <!-- pagebreak --> 두 개로 표지·본문·참고문헌을 나눠야 한다")
    title = md_path.stem
    sections = list(zip(["cover", "body", "back"], parts))
    html_path, pdf_path = md_path.with_suffix(".html"), md_path.with_suffix(".pdf")
    html_path.write_text(page(sections, title), encoding="utf-8")
    total = print_pdf(html_path, pdf_path)

    # 본문만 따로 인쇄해 쪽수를 센다(임시 파일은 지운다)
    tmp_html, tmp_pdf = md_path.with_name("_body_only.html"), md_path.with_name("_body_only.pdf")
    tmp_html.write_text(page([("body-only", parts[1])], title), encoding="utf-8")
    body_pages = print_pdf(tmp_html, tmp_pdf)
    tmp_html.unlink()
    tmp_pdf.unlink()
    flag = "OK" if body_pages <= BODY_PAGE_LIMIT else f"초과(규정 {BODY_PAGE_LIMIT}장)"
    print(f"저장: {pdf_path} — 전체 {total}쪽, 본문 {body_pages}쪽 {flag}")


if __name__ == "__main__":
    main()

"""Render README.md (with its screenshots) to a PDF for TikTok's pre-publication review.

    uv run --with markdown python tools/readme_pdf.py [--date 2026-11-20]

Writes dist/BigGamePulse_draft_publication_<date>.pdf using headless Google Chrome.
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: Letter; margin: 0.7in 0.65in; }
body { font: 10.5pt/1.45 -apple-system, "Helvetica Neue", Arial, sans-serif; color: #111; }
h1 { font-size: 22pt; margin: 0 0 6pt; }
h2 { font-size: 15pt; margin: 18pt 0 6pt; border-bottom: 1px solid #ddd; padding-bottom: 3pt; break-after: avoid; }
h3 { font-size: 12pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
img { max-width: 100%; border: 1px solid #ddd; border-radius: 4px; display: block; margin: 4pt 0 12pt; break-inside: avoid; }
p:has(+ p > img) { break-after: avoid; } p:has(> img) { break-inside: avoid; margin: 0; }
h2 + p, h2 + table { break-before: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; margin: 6pt 0 10pt; break-inside: avoid; }
th, td { border: 1px solid #ccc; padding: 3pt 5pt; text-align: left; vertical-align: top; } th { background: #f3f3f3; }
code { font: 8.5pt Menlo, monospace; background: #f4f4f4; padding: 0 2pt; }
pre { background: #f6f6f6; padding: 6pt 8pt; font-size: 8pt; white-space: pre-wrap; break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { margin: 8pt 0; padding: 6pt 10pt; background: #f5f7fb; border-left: 3px solid #2a78d6; }
.cover { border: 1px solid #ccc; padding: 10pt 12pt; margin-bottom: 16pt; font-size: 9.5pt; background: #fafafa; }
.cover b { display: inline-block; min-width: 120pt; }
"""

COVER = """<div class="cover">
<div><b>Document</b>Draft publication for TikTok pre-publication review (Research Tools Terms III(f))</div>
<div><b>Researcher</b>Ge Zhang, Research Assistant, Stanford University</div>
<div><b>Research API client</b>1789748711</div>
<div><b>Planned venue</b>Public GitHub repository (currently private): github.com/geoz-lab/Stanford-Cal_Big-Game-Pulse</div>
<div><b>Contents</b>This README and the screenshots below, exactly as they will be published. Aggregate results only; no comment text, captions, usernames, video IDs or links.</div>
<div><b>Draft date</b>{date}</div>
{extra}</div>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--note", default="", help="extra line for the cover box, e.g. what changed since the last copy")
    a = ap.parse_args()
    day = dt.date.fromisoformat(a.date)
    body = markdown.markdown((ROOT / "README.md").read_text(), extensions=["tables", "fenced_code"])
    body = body.replace('src="docs/', f'src="file://{ROOT}/docs/')
    extra = f"<div><b>Changes</b>{a.note}</div>" if a.note else ""
    cover = COVER.format(date=day.strftime("%B %-d, %Y"), extra=extra)
    html = (f'<!doctype html><html><head><meta charset="utf-8"><title>Big Game Pulse: draft publication for '
            f'TikTok review</title><style>{CSS}</style></head><body>{cover}{body}</body></html>')
    out = ROOT / "dist" / f"BigGamePulse_draft_publication_{day.isoformat()}.pdf"
    out.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "publication.html"
        src.write_text(html)
        subprocess.run([CHROME, "--headless=new", f"--user-data-dir={tmp}/prof", "--disable-gpu",
                        "--allow-file-access-from-files", "--no-pdf-header-footer", f"--print-to-pdf={out}",
                        src.as_uri()], check=True, capture_output=True)
    print(out)


if __name__ == "__main__":
    main()

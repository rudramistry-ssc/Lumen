"""Bundle the frontend into one self-contained HTML file.

Usage (from the frontend/ folder):
    python tools/build_single.py            -> dist/lumen.html (open by double-clicking)
    python tools/build_single.py --fragment -> dist/lumen-fragment.html (body-only, for hosting inside another page)
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
html = (ROOT / "index.html").read_text(encoding="utf-8")


def inline_css(m):
    return "<style>\n" + (ROOT / m.group(1)).read_text(encoding="utf-8") + "\n</style>"


def inline_js(m):
    code = (ROOT / m.group(1)).read_text(encoding="utf-8").replace("</script", "<\\/script")
    return "<script>\n" + code + "\n</script>"


html = re.sub(r'<link rel="stylesheet" href="(?!https?:)([^"]+)">', inline_css, html)
html = re.sub(r'<script src="([^"]+)"></script>', inline_js, html)

out = ROOT / "dist"
out.mkdir(exist_ok=True)

if "--fragment" in sys.argv:
    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    body = re.search(r"<body[^>]*>(.*)</body>", html, re.S).group(1)
    head = re.sub(r"<meta[^>]*>\s*", "", head)  # host page provides charset/viewport
    frag = head.strip() + '\n<script>document.body.classList.add("show-intro");</script>\n' + body.strip() + "\n"
    (out / "lumen-fragment.html").write_text(frag, encoding="utf-8")
    print("wrote", out / "lumen-fragment.html")
else:
    (out / "lumen.html").write_text(html, encoding="utf-8")
    print("wrote", out / "lumen.html")

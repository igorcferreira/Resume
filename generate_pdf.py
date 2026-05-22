#!/usr/bin/env -S uv run

import os
import re
import shutil
import subprocess
import tempfile

# WeasyPrint needs Homebrew's pango/glib shared libraries
_brew_prefix = subprocess.run(
    ["brew", "--prefix"], capture_output=True, text=True
).stdout.strip()
if _brew_prefix:
    os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", f"{_brew_prefix}/lib")

import markdown  # noqa: E402
from PIL import Image  # noqa: E402
from weasyprint import HTML  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MAX_IMAGE_WIDTH = 800
PAGE_WIDTH_MM = 210
MARGIN_V_MM = 20
MARGIN_H_MM = 18

BODY_CSS = """
body {
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.5;
    color: #1a1a1a;
    max-width: 174mm;
}
h1 {
    font-size: 22pt;
    font-weight: 700;
    margin-bottom: 4px;
    color: #111;
    border-bottom: 2px solid #333;
    padding-bottom: 6px;
}
h2 {
    font-size: 14pt;
    font-weight: 600;
    color: #222;
    margin-top: 20px;
    margin-bottom: 8px;
    border-bottom: 1px solid #ccc;
    padding-bottom: 4px;
}
h3 {
    font-size: 12pt;
    font-weight: 600;
    color: #333;
    margin-top: 14px;
    margin-bottom: 4px;
}
p { margin: 6px 0; }
ul { margin: 4px 0; padding-left: 20px; }
li { margin: 2px 0; }
a { color: #1a5276; text-decoration: none; }
strong { font-weight: 600; }
table { width: 100%; border-collapse: collapse; margin: 12px 0; }
th, td { text-align: center; padding: 6px; vertical-align: top; }
th { font-weight: 600; font-size: 9pt; color: #555; }
img {
    max-width: 100%;
    height: auto;
    max-height: 280px;
    border-radius: 4px;
    display: block;
    margin: 0 auto;
}
"""


def page_css(height_mm: float) -> str:
    return (
        f"@page {{ size: {PAGE_WIDTH_MM}mm {height_mm}mm; "
        f"margin: {MARGIN_V_MM}mm {MARGIN_H_MM}mm; }}\n"
        + BODY_CSS
    )


def optimize_images(tmp_dir: str) -> None:
    for root, _, files in os.walk(os.path.join(tmp_dir, "images")):
        for fname in files:
            fpath = os.path.join(root, fname)
            ext = fname.lower().rsplit(".", 1)[-1] if "." in fname else ""
            if ext not in ("jpg", "jpeg", "png"):
                continue
            try:
                with Image.open(fpath) as img:
                    if img.width > MAX_IMAGE_WIDTH:
                        ratio = MAX_IMAGE_WIDTH / img.width
                        new_size = (MAX_IMAGE_WIDTH, int(img.height * ratio))
                        img = img.resize(new_size, Image.LANCZOS)
                    img = img.convert("RGB")
                    out = fpath.rsplit(".", 1)[0] + ".jpg"
                    img.save(out, "JPEG", quality=80, optimize=True)
                    if out != fpath:
                        os.remove(fpath)
            except Exception:
                pass


def build_html(html_body: str, css: str) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head><body>{html_body}</body></html>"
    )


def convert(md_path: str, pdf_path: str) -> None:
    tmp_dir = tempfile.mkdtemp()
    try:
        images_src = os.path.join(SCRIPT_DIR, "images")
        images_dst = os.path.join(tmp_dir, "images")
        shutil.copytree(images_src, images_dst)
        optimize_images(tmp_dir)

        with open(md_path, "r", encoding="utf-8") as f:
            md_text = f.read()

        md_text = re.sub(r"\.png\)", ".jpg)", md_text)
        md_text = re.sub(r"\.jpeg\)", ".jpg)", md_text)

        html_body = markdown.markdown(md_text, extensions=["tables", "smarty"])

        # Pass 1: render with an oversized page to measure actual content height
        tall_css = page_css(9999)
        doc = HTML(string=build_html(html_body, tall_css), base_url=tmp_dir)
        rendered = doc.render()
        page = rendered.pages[0]
        content_block = page._page_box.children[0]
        content_bottom_px = content_block.position_y + content_block.margin_height()
        content_height_mm = (content_bottom_px / 96) * 25.4 + MARGIN_V_MM

        # Pass 2: render with the exact page height
        fitted_css = page_css(content_height_mm)
        HTML(
            string=build_html(html_body, fitted_css), base_url=tmp_dir
        ).write_pdf(pdf_path)
        print(f"Created {pdf_path}")
    finally:
        shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    pairs = [
        ("CV.md", "CV.pdf"),
        ("CV-BR.md", "CV-BR.pdf"),
    ]
    for md_file, pdf_file in pairs:
        md_path = os.path.join(SCRIPT_DIR, md_file)
        pdf_path = os.path.join(SCRIPT_DIR, pdf_file)
        if os.path.exists(md_path):
            convert(md_path, pdf_path)
        else:
            print(f"Skipped {md_file} (not found)")

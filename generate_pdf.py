#!/usr/bin/env -S uv run

import os
import re
import shutil
import tempfile
from urllib.parse import unquote

import markdown
import pymupdf
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MAX_IMAGE_WIDTH = 800
PAGE_WIDTH_MM = 210
MARGIN_V_MM = 20
MARGIN_H_MM = 18

PT_PER_MM = 72 / 25.4
MAX_IMAGE_HEIGHT_PT = 210  # 280px at 96 dpi
# Tall enough to hold the whole CV in one layout pass
MEASURE_HEIGHT_PT = 100_000

BODY_CSS = """
body {
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.5;
    color: #1a1a1a;
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
    display: block;
    margin: 0 auto;
}
"""


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


def size_images(html_body: str, assets_dir: str) -> str:
    """Give every <img> an explicit size, since MuPDF ignores max-width/max-height."""
    content_width = (PAGE_WIDTH_MM - 2 * MARGIN_H_MM) * PT_PER_MM

    def replace(match: re.Match) -> str:
        tag = match.group(0)
        src_match = re.search(r'src="([^"]+)"', tag)
        if not src_match:
            return tag
        # MuPDF resolves image paths literally, so decode "%20" and friends
        src = unquote(src_match.group(1))
        tag = tag.replace(src_match.group(0), f'src="{src}"')
        try:
            with Image.open(os.path.join(assets_dir, src)) as img:
                aspect = img.width / img.height
        except OSError:
            return tag
        height = MAX_IMAGE_HEIGHT_PT
        width = height * aspect
        if width > content_width:
            width, height = content_width, content_width / aspect
        return tag.replace("<img", f'<img style="width:{width:.1f}pt;height:{height:.1f}pt"', 1)

    return re.sub(r"<img\b[^>]*>", replace, html_body)


def build_html(html_body: str, assets_dir: str) -> str:
    html_body = size_images(html_body, assets_dir)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        f"<body>{html_body}</body></html>"
    )


def render_pdf(html: str, assets_dir: str, pdf_path: str) -> None:
    """Lay the HTML out on a single A4-wide page whose height fits the content."""
    archive = pymupdf.Archive(assets_dir)
    content_width = (PAGE_WIDTH_MM - 2 * MARGIN_H_MM) * PT_PER_MM
    margin_h = MARGIN_H_MM * PT_PER_MM
    margin_v = MARGIN_V_MM * PT_PER_MM

    # Pass 1: lay out into an oversized area to measure the content height
    story = pymupdf.Story(html=html, user_css=BODY_CSS, archive=archive)
    more, filled = story.place(pymupdf.Rect(0, 0, content_width, MEASURE_HEIGHT_PT))
    if more:
        raise RuntimeError("Content taller than the measuring area")
    content_height = pymupdf.Rect(filled).y1

    # Pass 2: draw onto a page with the exact height
    page_rect = pymupdf.Rect(
        0, 0, PAGE_WIDTH_MM * PT_PER_MM, content_height + 2 * margin_v
    )
    where = pymupdf.Rect(
        margin_h, margin_v, margin_h + content_width, margin_v + content_height + 1
    )
    story = pymupdf.Story(html=html, user_css=BODY_CSS, archive=archive)
    writer = pymupdf.DocumentWriter(pdf_path)
    device = writer.begin_page(page_rect)
    story.place(where)
    story.draw(device)
    writer.end_page()
    writer.close()


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
        render_pdf(build_html(html_body, tmp_dir), tmp_dir, pdf_path)
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

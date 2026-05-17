#!/usr/bin/env python3
"""Compress PDFs at 300 DPI while removing center light-gray neutral watermarks."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image


def human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{value:.1f}GB"


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"missing required tool: {name}")
    return path


def page_count(pdf: Path) -> int | None:
    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        return None
    proc = subprocess.run(
        [pdfinfo, str(pdf)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return None
    match = re.search(r"^Pages:\s+(\d+)\s*$", proc.stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def sorted_rendered_pages(tmpdir: Path, prefix_name: str) -> list[Path]:
    pages = list(tmpdir.glob(f"{prefix_name}-*.png"))

    def key(path: Path) -> int:
        match = re.search(r"-(\d+)\.png$", path.name)
        return int(match.group(1)) if match else 0

    return sorted(pages, key=key)


def estimate_background(arr: np.ndarray) -> np.ndarray:
    h, w, _ = arr.shape
    corner = max(24, min(h, w) // 60)
    samples = np.concatenate(
        [
            arr[:corner, :corner].reshape(-1, 3),
            arr[:corner, -corner:].reshape(-1, 3),
            arr[-corner:, :corner].reshape(-1, 3),
            arr[-corner:, -corner:].reshape(-1, 3),
        ],
        axis=0,
    )
    samples_f = samples.astype(np.float32)
    luma = 0.299 * samples_f[:, 0] + 0.587 * samples_f[:, 1] + 0.114 * samples_f[:, 2]
    light = samples[luma >= 235]
    if len(light) < 32:
        return np.array([255, 255, 255], dtype=np.uint8)
    return np.median(light, axis=0).astype(np.uint8)


def remove_center_gray_watermark(
    image: Image.Image,
    gray_min: int,
    gray_max: int,
    neutral_delta: int,
    center_x: tuple[float, float],
    center_y: tuple[float, float],
) -> Image.Image:
    arr = np.array(image.convert("RGB"), dtype=np.uint8)
    h, w, _ = arr.shape
    bg = estimate_background(arr)

    arr_i = arr.astype(np.int16)
    maxc = arr_i.max(axis=2)
    minc = arr_i.min(axis=2)
    luma = 0.299 * arr_i[:, :, 0] + 0.587 * arr_i[:, :, 1] + 0.114 * arr_i[:, :, 2]

    x0, x1 = int(w * center_x[0]), int(w * center_x[1])
    y0, y1 = int(h * center_y[0]), int(h * center_y[1])
    region = np.zeros((h, w), dtype=bool)
    region[y0:y1, x0:x1] = True

    neutral_gray = (maxc - minc) <= neutral_delta
    watermark_tone = (luma >= gray_min) & (luma <= gray_max)
    not_background = luma <= 248
    mask = region & neutral_gray & watermark_tone & not_background

    out = arr.copy()
    out[mask] = bg
    return Image.fromarray(out)


def render_pdf(pdf: Path, tmpdir: Path, dpi: int) -> list[Path]:
    pdftoppm = require_tool("pdftoppm")
    prefix = tmpdir / "page"
    proc = subprocess.run(
        [pdftoppm, "-r", str(dpi), "-png", str(pdf), str(prefix)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "pdftoppm failed")
    pages = sorted_rendered_pages(tmpdir, "page")
    if not pages:
        raise RuntimeError("no pages rendered")
    return pages


def combine_jpegs(jpegs: list[Path], output_pdf: Path, dpi: int, quality: int) -> None:
    images: list[Image.Image] = []
    try:
        for jpg in jpegs:
            images.append(Image.open(jpg).convert("RGB"))
        images[0].save(
            output_pdf,
            "PDF",
            save_all=True,
            append_images=images[1:],
            resolution=dpi,
            quality=quality,
        )
    finally:
        for image in images:
            image.close()


def output_path_for(pdf: Path, output_dir: Path | None) -> Path:
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / pdf.name
    return pdf.with_name(f"{pdf.stem}.cleaned.pdf")


def process_pdf(pdf: Path, args: argparse.Namespace) -> tuple[bool, str]:
    if not pdf.exists():
        return False, f"FAIL\t{pdf}\tmissing file"
    if pdf.suffix.lower() != ".pdf":
        return False, f"FAIL\t{pdf}\tnot a PDF"

    original_size = pdf.stat().st_size
    original_pages = page_count(pdf)
    backup_path: Path | None = None

    with tempfile.TemporaryDirectory(prefix="pdf-handout-cleaner-") as td:
        tmpdir = Path(td)
        rendered = render_pdf(pdf, tmpdir, args.dpi)
        processed_jpegs: list[Path] = []

        for index, page in enumerate(rendered, start=1):
            with Image.open(page) as img:
                cleaned = remove_center_gray_watermark(
                    img,
                    gray_min=args.gray_min,
                    gray_max=args.gray_max,
                    neutral_delta=args.neutral_delta,
                    center_x=(args.center_x_min, args.center_x_max),
                    center_y=(args.center_y_min, args.center_y_max),
                )
                out_jpg = tmpdir / f"processed-{index:04d}.jpg"
                cleaned.save(
                    out_jpg,
                    "JPEG",
                    quality=args.quality,
                    optimize=True,
                    dpi=(args.dpi, args.dpi),
                )
                if args.preview_dir and index == 1:
                    args.preview_dir.mkdir(parents=True, exist_ok=True)
                    cleaned.save(args.preview_dir / f"{pdf.stem}-page1-preview.jpg", "JPEG", quality=90)
                processed_jpegs.append(out_jpg)

        if args.replace:
            output_pdf = pdf.with_name(f".{pdf.stem}.cleaning-{os.getpid()}.pdf")
        else:
            output_pdf = output_path_for(pdf, args.output_dir)

        combine_jpegs(processed_jpegs, output_pdf, args.dpi, args.quality)

        output_size = output_pdf.stat().st_size
        output_pages = page_count(output_pdf)
        rendered_pages = len(rendered)
        expected_pages = original_pages if original_pages is not None else rendered_pages

        if output_size <= 0:
            output_pdf.unlink(missing_ok=True)
            raise RuntimeError("output PDF is empty")
        if output_pages is not None and output_pages != expected_pages:
            output_pdf.unlink(missing_ok=True)
            raise RuntimeError(f"page count mismatch: input={expected_pages}, output={output_pages}")
        if not args.allow_growth and output_size > original_size * args.max_size_ratio:
            output_pdf.unlink(missing_ok=True)
            raise RuntimeError(
                f"output grew too much: {human_size(original_size)} -> {human_size(output_size)}"
            )

        if args.replace:
            if args.backup:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup_path = pdf.with_name(f"{pdf.stem}.backup-{stamp}{pdf.suffix}")
                shutil.copy2(pdf, backup_path)
            os.replace(output_pdf, pdf)

    final_size = pdf.stat().st_size if args.replace else output_path_for(pdf, args.output_dir).stat().st_size
    pages_text = original_pages if original_pages is not None else "?"
    target = "replaced" if args.replace else "written"
    backup_text = f"\tbackup={backup_path.name}" if backup_path else ""
    return True, (
        f"OK\t{pdf}\tpages={pages_text}\t"
        f"{human_size(original_size)} -> {human_size(final_size)}\t{target}{backup_text}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compress PDFs at 300 DPI and remove center light-gray neutral watermarks."
    )
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--quality", type=int, default=82)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--preview-dir", type=Path)
    parser.add_argument("--allow-growth", action="store_true")
    parser.add_argument("--max-size-ratio", type=float, default=1.10)
    parser.add_argument("--gray-min", type=int, default=165)
    parser.add_argument("--gray-max", type=int, default=245)
    parser.add_argument("--neutral-delta", type=int, default=18)
    parser.add_argument("--center-x-min", type=float, default=0.12)
    parser.add_argument("--center-x-max", type=float, default=0.88)
    parser.add_argument("--center-y-min", type=float, default=0.08)
    parser.add_argument("--center-y-max", type=float, default=0.92)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not 1 <= args.quality <= 95:
        print("quality must be between 1 and 95", file=sys.stderr)
        return 2
    if args.replace and args.output_dir:
        print("--replace cannot be combined with --output-dir", file=sys.stderr)
        return 2

    failed = False
    try:
        require_tool("pdftoppm")
    except RuntimeError as exc:
        print(f"FAIL\tsetup\t{exc}", file=sys.stderr)
        return 2

    for pdf in args.pdfs:
        try:
            ok, line = process_pdf(pdf.expanduser().resolve(), args)
            failed = failed or not ok
            print(line)
        except Exception as exc:  # noqa: BLE001
            failed = True
            print(f"FAIL\t{pdf}\t{exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

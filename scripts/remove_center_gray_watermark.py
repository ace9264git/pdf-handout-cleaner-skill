#!/usr/bin/env python3
"""Orchestrate native-resolution center watermark removal for image PDFs."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import fitz


WORKER = Path(__file__).with_name("watermark_page_worker.py")


def human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{value:.1f}GB"


def process_pdf(pdf: Path, args: argparse.Namespace) -> str:
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        raise RuntimeError("input is not a PDF file")

    original_size = pdf.stat().st_size
    source = fitz.open(pdf)
    try:
        original_rects = [(page.rect.width, page.rect.height) for page in source]
    finally:
        source.close()

    if args.replace:
        target = pdf.with_name(f".{pdf.stem}.watermark-removal-{os.getpid()}.pdf")
    elif args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        target = args.output_dir / pdf.name
    else:
        target = pdf.with_name(f"{pdf.stem}.cleaned.pdf")

    with tempfile.TemporaryDirectory(prefix="pdf-watermark-remover-") as temp_name:
        temp_dir = Path(temp_name)
        page_pdfs: list[Path] = []

        for page_number in range(len(original_rects)):
            page_pdf = temp_dir / f"page-{page_number + 1:04d}.pdf"
            command = [
                sys.executable,
                str(WORKER),
                "--pdf",
                str(pdf),
                "--page",
                str(page_number),
                "--output",
                str(page_pdf),
                "--gray-min",
                str(args.gray_min),
                "--gray-max",
                str(args.gray_max),
                "--dark-max",
                str(args.dark_max),
                "--neutral-delta",
                str(args.neutral_delta),
                "--protect-radius",
                str(args.protect_radius),
                "--center-x-min",
                str(args.center_x_min),
                "--center-x-max",
                str(args.center_x_max),
                "--center-y-min",
                str(args.center_y_min),
                "--center-y-max",
                str(args.center_y_max),
            ]
            if args.preview_dir and page_number == 0:
                args.preview_dir.mkdir(parents=True, exist_ok=True)
                command.extend(
                    ["--preview", str(args.preview_dir / f"{pdf.stem}-page1.png")]
                )

            worker = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if worker.returncode != 0:
                detail = worker.stderr.strip() or worker.stdout.strip() or "worker failed"
                raise RuntimeError(f"page {page_number + 1}: {detail}")
            page_pdfs.append(page_pdf)

        pdfunite = shutil.which("pdfunite")
        if not pdfunite:
            raise RuntimeError("missing required tool: pdfunite")
        merge = subprocess.run(
            [pdfunite, *(str(path) for path in page_pdfs), str(target)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if merge.returncode != 0:
            raise RuntimeError(merge.stderr.strip() or "pdfunite failed")

    check = fitz.open(target)
    try:
        if check.page_count != len(original_rects):
            target.unlink(missing_ok=True)
            raise RuntimeError("page count mismatch")
        for index, expected in enumerate(original_rects):
            rect = check[index].rect
            if abs(rect.width - expected[0]) > 0.01 or abs(rect.height - expected[1]) > 0.01:
                target.unlink(missing_ok=True)
                raise RuntimeError(f"page {index + 1}: page dimensions changed")
    finally:
        check.close()

    backup: Path | None = None
    if args.replace:
        if args.backup:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = pdf.with_name(f"{pdf.stem}.backup-{stamp}{pdf.suffix}")
            shutil.copy2(pdf, backup)
        os.replace(target, pdf)
        final = pdf
    else:
        final = target

    backup_text = f" backup={backup.name}" if backup else ""
    return (
        f"OK\t{pdf}\tpages={len(original_rects)}\t"
        f"{human_size(original_size)} -> {human_size(final.stat().st_size)}{backup_text}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove center light-gray watermarks without downsampling PDF pages."
    )
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--preview-dir", type=Path)
    parser.add_argument("--gray-min", type=float, default=185.0)
    parser.add_argument("--gray-max", type=float, default=254.8)
    parser.add_argument("--dark-max", type=float, default=175.0)
    parser.add_argument("--neutral-delta", type=int, default=18)
    parser.add_argument("--protect-radius", type=int, default=5)
    parser.add_argument("--center-x-min", type=float, default=0.12)
    parser.add_argument("--center-x-max", type=float, default=0.88)
    parser.add_argument("--center-y-min", type=float, default=0.18)
    parser.add_argument("--center-y-max", type=float, default=0.82)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.replace and args.output_dir:
        print("--replace cannot be combined with --output-dir", file=sys.stderr)
        return 2
    if not WORKER.is_file():
        print(f"missing page worker: {WORKER}", file=sys.stderr)
        return 2

    failed = False
    for item in args.pdfs:
        pdf = item.expanduser().resolve()
        try:
            print(process_pdf(pdf, args), flush=True)
        except Exception as exc:  # noqa: BLE001
            failed = True
            print(f"FAIL\t{pdf}\t{exc}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

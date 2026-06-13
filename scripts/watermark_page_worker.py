#!/usr/bin/env python3
"""Internal one-page pixel worker for pdf-handout-cleaner."""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import fitz
import numpy as np
from PIL import Image, ImageFilter


def estimate_background(arr: np.ndarray) -> np.ndarray:
    height, width, _ = arr.shape
    edge = max(32, min(height, width) // 80)
    samples = np.concatenate(
        (
            arr[:edge, :edge].reshape(-1, 3),
            arr[:edge, -edge:].reshape(-1, 3),
            arr[-edge:, :edge].reshape(-1, 3),
            arr[-edge:, -edge:].reshape(-1, 3),
        )
    )
    light = samples[samples.min(axis=1) >= 240]
    if len(light) < 64:
        return np.array([255, 255, 255], dtype=np.uint8)
    return np.median(light, axis=0).astype(np.uint8)


def main_image(page: fitz.Page) -> int:
    candidates: list[tuple[float, int]] = []
    page_area = page.rect.width * page.rect.height
    for item in page.get_images(full=True):
        xref = item[0]
        for rect in page.get_image_rects(xref):
            coverage = (rect.width * rect.height) / page_area if page_area else 0
            candidates.append((coverage, xref))
    if not candidates:
        raise RuntimeError("no raster image found")
    coverage, xref = max(candidates)
    if coverage < 0.90:
        raise RuntimeError(f"full-page image coverage is only {coverage:.1%}")
    return xref


def clean(image: Image.Image, args: argparse.Namespace) -> Image.Image:
    arr = np.asarray(image.convert("RGB"))
    values = arr.astype(np.int16)
    max_channel = values.max(axis=2)
    min_channel = values.min(axis=2)
    luminance = (
        0.299 * values[:, :, 0]
        + 0.587 * values[:, :, 1]
        + 0.114 * values[:, :, 2]
    )
    height, width = luminance.shape

    dark = Image.fromarray((luminance < args.dark_max).astype(np.uint8) * 255)
    protected = np.asarray(
        dark.filter(ImageFilter.MaxFilter(args.protect_radius * 2 + 1))
    ) > 0

    center = np.zeros((height, width), dtype=bool)
    center[
        int(height * args.center_y_min) : int(height * args.center_y_max),
        int(width * args.center_x_min) : int(width * args.center_x_max),
    ] = True
    neutral = (max_channel - min_channel) <= args.neutral_delta
    watermark = (
        center
        & neutral
        & (luminance >= args.gray_min)
        & (luminance < args.gray_max)
        & ~protected
    )

    result = arr.copy()
    result[watermark] = estimate_background(arr)
    return Image.fromarray(result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--page", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--gray-min", required=True, type=float)
    parser.add_argument("--gray-max", required=True, type=float)
    parser.add_argument("--dark-max", required=True, type=float)
    parser.add_argument("--neutral-delta", required=True, type=int)
    parser.add_argument("--protect-radius", required=True, type=int)
    parser.add_argument("--center-x-min", required=True, type=float)
    parser.add_argument("--center-x-max", required=True, type=float)
    parser.add_argument("--center-y-min", required=True, type=float)
    parser.add_argument("--center-y-max", required=True, type=float)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    document = fitz.open(args.pdf)
    try:
        page = document[args.page]
        extracted = document.extract_image(main_image(page))
        page_size = (page.rect.width, page.rect.height)
    finally:
        document.close()

    with Image.open(io.BytesIO(extracted["image"])) as image:
        cleaned = clean(image, args)
        png = io.BytesIO()
        cleaned.save(png, format="PNG", optimize=True)
        if args.preview:
            preview = cleaned.copy()
            preview.thumbnail((1400, 2000))
            preview.save(args.preview, format="PNG")

    output = fitz.open()
    try:
        new_page = output.new_page(width=page_size[0], height=page_size[1])
        new_page.insert_image(new_page.rect, stream=png.getvalue(), keep_proportion=False)
        output.save(args.output, garbage=4, deflate=True)
    finally:
        output.close()


if __name__ == "__main__":
    main()

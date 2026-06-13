#!/usr/bin/env python3
"""Low-memory whole-book worker for center watermark removal."""

from __future__ import annotations

import argparse
import gc
from pathlib import Path

import cv2
import fitz
import numpy as np


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


def estimate_background(image: np.ndarray) -> np.ndarray:
    height, width, _ = image.shape
    edge = max(32, min(height, width) // 80)
    samples = np.concatenate(
        (
            image[:edge, :edge].reshape(-1, 3),
            image[:edge, -edge:].reshape(-1, 3),
            image[-edge:, :edge].reshape(-1, 3),
            image[-edge:, -edge:].reshape(-1, 3),
        )
    )
    light = samples[samples.min(axis=1) >= 240]
    if len(light) < 64:
        return np.array([255, 255, 255], dtype=np.uint8)
    return np.median(light, axis=0).astype(np.uint8)


def clean(image: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    height, width, _ = image.shape
    kernel_size = args.protect_radius * 2 + 1
    kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
    background = estimate_background(image)
    x0, x1 = int(width * args.center_x_min), int(width * args.center_x_max)
    y0, y1 = int(height * args.center_y_min), int(height * args.center_y_max)

    for tile_y0 in range(y0, y1, args.tile_rows):
        tile_y1 = min(tile_y0 + args.tile_rows, y1)
        ext_y0 = max(0, tile_y0 - args.protect_radius)
        ext_y1 = min(height, tile_y1 + args.protect_radius)
        extended = image[ext_y0:ext_y1, x0:x1]
        gray_extended = cv2.cvtColor(extended, cv2.COLOR_BGR2GRAY)
        protected_extended = cv2.dilate(
            (gray_extended < args.dark_max).astype(np.uint8), kernel, iterations=1
        )
        offset0 = tile_y0 - ext_y0
        offset1 = offset0 + tile_y1 - tile_y0
        roi = image[tile_y0:tile_y1, x0:x1]
        gray_roi = gray_extended[offset0:offset1]
        protected_roi = protected_extended[offset0:offset1]
        blue, green, red = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
        max_channel = np.maximum(np.maximum(blue, green), red)
        min_channel = np.minimum(np.minimum(blue, green), red)
        mask = (
            ((max_channel - min_channel) <= args.neutral_delta)
            & (gray_roi >= args.gray_min)
            & (gray_roi < args.gray_max)
            & (protected_roi == 0)
        )
        roi[mask] = background
    return image


def encode_near_size(
    image: np.ndarray, target_size: int, quality_min: int, quality_max: int
) -> tuple[bytes, int]:
    best_data: bytes | None = None
    best_quality = quality_min
    best_distance = float("inf")
    low, high = quality_min, quality_max
    while low <= high:
        quality = (low + high) // 2
        ok, encoded = cv2.imencode(
            ".jpg",
            image,
            [cv2.IMWRITE_JPEG_QUALITY, quality, cv2.IMWRITE_JPEG_OPTIMIZE, 1],
        )
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        data = encoded.tobytes()
        distance = abs(len(data) - target_size)
        if distance < best_distance:
            best_data, best_quality, best_distance = data, quality, distance
        if len(data) < target_size:
            low = quality + 1
        elif len(data) > target_size:
            high = quality - 1
        else:
            break
    if best_data is None:
        raise RuntimeError("JPEG encoding failed")
    return best_data, best_quality


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
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
    parser.add_argument("--quality-min", required=True, type=int)
    parser.add_argument("--quality-max", required=True, type=int)
    parser.add_argument("--tile-rows", required=True, type=int)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(args.pdf)
    try:
        total = document.page_count
        for page_number in range(total):
            page = document[page_number]
            extracted = document.extract_image(main_image(page))
            page_size = (page.rect.width, page.rect.height)
            image = cv2.imdecode(
                np.frombuffer(extracted["image"], dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if image is None:
                raise RuntimeError(f"page {page_number + 1}: unable to decode image")
            cleaned = clean(image, args)
            jpeg, quality = encode_near_size(
                cleaned, len(extracted["image"]), args.quality_min, args.quality_max
            )

            if args.preview and page_number == 0:
                preview = cleaned
                scale = min(1400 / preview.shape[1], 2000 / preview.shape[0], 1.0)
                if scale < 1.0:
                    preview = cv2.resize(
                        preview, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
                    )
                cv2.imwrite(str(args.preview), preview)

            page_pdf = args.output_dir / f"page-{page_number + 1:04d}.pdf"
            output = fitz.open()
            try:
                new_page = output.new_page(width=page_size[0], height=page_size[1])
                new_page.insert_image(new_page.rect, stream=jpeg, keep_proportion=False)
                output.save(page_pdf, garbage=4, deflate=True)
            finally:
                output.close()
            if args.verbose:
                print(
                    f"page {page_number + 1}/{total} quality={quality} "
                    f"bytes={len(jpeg)} target={len(extracted['image'])}",
                    flush=True,
                )
            del image, cleaned, jpeg, extracted
            gc.collect()
    finally:
        document.close()


if __name__ == "__main__":
    main()

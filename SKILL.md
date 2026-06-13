---
name: pdf-handout-cleaner
description: Remove the known large center light-gray watermark from image-based Chinese teaching PDFs while preserving native pixel dimensions and keeping output size close to the original. Use for requests such as "去中间水印", "去中间浅灰水印", or "只去水印不要明显改变大小". Do not use for side, dark, colored, unknown, or vector/text-layer watermarks without inspecting the PDF first.
metadata:
  short-description: Remove center watermarks at near-original size
---

# PDF Center Watermark Remover

Remove only the known large pale-gray watermark in the middle of image-based teaching PDFs. Preserve every page's native pixel dimensions and adapt JPEG quality so the final PDF remains within 95%-105% of the original file size. Do not render at 300 DPI.

## Preflight

Confirm the PDF is image-based and each page contains one full-page raster image. The script stops on unsupported page structures.

Do not use this workflow for:
- Side, dark, colored, or unknown watermarks.
- Answer masking, annotations, or layout edits.
- PDFs whose selectable text/vector structure must remain intact.

## Default Command

```bash
python3 scripts/remove_center_gray_watermark.py --replace FILE1.pdf FILE2.pdf
```

Without `--replace`, the script writes `NAME.cleaned.pdf`. Use `--backup` only when the user explicitly requests a backup.

## Method

- Extract the full-page image at its native resolution.
- Protect dark text and nearby antialiasing pixels.
- In the center region only, whiten neutral light-gray pixels that are not connected to dark content.
- Re-encode each cleaned page as JPEG at the quality closest to that page's original embedded-image size.
- Rebuild at the original page dimensions without downsampling.

## Validation

- Work through a temporary output and replace the source only after success.
- Require identical page count and page dimensions.
- Require final size to remain between 95% and 105% of the source PDF.
- If the size check fails, leave the original untouched and report the failure.
- For a new watermark design, inspect a sample before batch processing.

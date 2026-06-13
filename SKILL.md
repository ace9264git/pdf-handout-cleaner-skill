---
name: pdf-handout-cleaner
description: Remove the known large center light-gray watermark from image-based Chinese teaching PDFs without downsampling or size-oriented compression. Use for requests such as "去中间水印", "去中间浅灰水印", or "只去水印不要压缩". Do not use for side, dark, colored, unknown, or vector/text-layer watermarks without inspecting the PDF first.
metadata:
  short-description: Remove center gray PDF watermarks losslessly
---

# PDF Center Watermark Remover

Remove only the known large pale-gray watermark in the middle of image-based teaching PDFs. Preserve each page's native pixel dimensions and rebuild with lossless PNG images. Do not render at 300 DPI and do not optimize for file size.

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
- Rebuild the PDF from lossless PNG pages at the original page dimensions.

## Validation

- Work through a temporary output and replace the source only after success.
- Require identical page count and page dimensions.
- Do not reject file-size growth; lossless output is expected to be larger.
- For a new watermark design, inspect a sample before batch processing.

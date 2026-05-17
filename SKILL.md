---
name: pdf-handout-cleaner
description: Compress teaching/handout PDFs at 300 DPI and remove the known center light-gray neutral watermark. Use when the user asks to batch process PDFs with phrases like "压缩去水印", "300 DPI 压缩", "去中间灰色水印", or "教辅 PDF 压缩并去水印". Do not use for answer blanking, side/dark watermarks, layout annotation, or unknown watermark types without stopping to ask.
metadata:
  short-description: Compress PDFs and remove center gray watermarks
---

# PDF Handout Cleaner

Use this skill only for the stable workflow: render each PDF page at 300 DPI, remove center light-gray neutral watermark pixels, and rebuild a smaller PDF.

## Boundaries

Use the script for:
- Chinese teaching/handout PDFs with a pale gray watermark in the middle of the page.
- Batch requests like "压缩去水印" where visual text fidelity matters more than preserving selectable text.

Do not use this workflow for:
- Answer-area blanking or masking.
- Adding side notes, annotations, or layout changes.
- Side watermarks, dark/black watermarks, colored watermarks, or watermarks over complex backgrounds.
- Jobs where the user needs the original selectable text/vector PDF structure preserved.

If the watermark type is not clearly the known center light-gray watermark, stop and ask before processing.

## Default Command

From this skill directory:

```bash
python3 scripts/clean_center_gray_watermark.py --replace --dpi 300 --quality 82 FILE1.pdf FILE2.pdf
```

Use `--backup` only when the user asks for a backup or the replacement is not explicitly requested. If the user says to delete/replace originals and keep the original filenames, use `--replace` without `--backup`.

## Operating Rules

- Batch all requested PDFs in one script call.
- Keep output names the same only when `--replace` is used.
- Do not run image previews by default for the known center-gray workflow.
- For uncertain watermark types, use `--preview-dir` or inspect a rendered page before replacing anything.
- Keep terminal output concise: one status line per PDF is enough.
- Report only the processed file count, failures, and whether originals were replaced or backed up.

## Validation

The script must leave the original PDF untouched unless all checks pass:
- Input and output page counts match.
- Output file is non-empty.
- Output size is not abnormally larger than input unless `--allow-growth` is set.
- At least one page rendered successfully.

If a file fails, keep the original and report the failure.

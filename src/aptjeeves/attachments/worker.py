"""Child-process entry point: parse one untrusted document and print JSON.

Invoked as ``python -m aptjeeves.attachments.worker`` with a JSON request on
stdin. Only a safe error category is ever written on failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from aptjeeves.attachments.config import AttachmentConfig
from aptjeeves.attachments.extractors import AttachmentExtractionError, extract_blocks


def main() -> int:
    request = json.loads(sys.stdin.read())
    config = AttachmentConfig(
        max_pages=int(request["max_pages"]),
        max_text_chars=int(request["max_text_chars"]),
        spreadsheet_row_cap=int(request["spreadsheet_row_cap"]),
        ocr_backend=str(request.get("ocr_backend", "none")),
        ocr_min_confidence=float(request.get("ocr_min_confidence", 0.6)),
        ocr_max_pages=int(request.get("ocr_max_pages", 10)),
        ocr_page_min_chars=int(request.get("ocr_page_min_chars", 25)),
        ocr_min_image_side=int(request.get("ocr_min_image_side", 200)),
        ocr_min_text_chars=int(request.get("ocr_min_text_chars", 30)),
        isolate=False,
    )
    try:
        result = extract_blocks(request["kind"], Path(request["path"]), config)
    except AttachmentExtractionError as exc:
        sys.stdout.write(json.dumps({"error": exc.category}))
        return 0
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

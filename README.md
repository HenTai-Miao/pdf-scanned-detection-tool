# scanspy

Detect whether one PDF file or direct PDF URL is scanned, then print a Spring Boot `R<T>`-style JSON response.

## Usage

```powershell
uv run python scanspy.py C:\path\to\file.pdf
uv run python scanspy.py https://example.com/file.pdf
uv run scanspy C:\path\to\file.pdf
uv run scanspy C:\path\to\a.pdf C:\path\to\b.pdf https://example.com/c.pdf
```

The project pins Python through `.python-version`; run it with `uv` so CPython 3.13.13 is used instead of the system Python.

## Windows EXE Build

Build the Windows x64 command-line release on a Windows machine:

```powershell
.\scripts\build-windows.ps1
```

The script uses PyInstaller onefile console mode and writes:

- `dist\scanspy.exe`
- `release\scanspy-windows-x64\scanspy.exe`
- `release\scanspy-windows-x64\README-用户使用.txt`
- `release\scanspy-windows-x64.zip`

End users do not need Python, uv, or project dependencies. They can run the exe by full path:

```powershell
C:\path\to\scanspy.exe "C:\path\to\file.pdf"
C:\path\to\scanspy.exe "https://example.com/file.pdf"
```

Inputs are validated before PDF parsing:

- Local input must be a `.pdf` path.
- Link input must use `http://` or `https://`, and the URL path must end with `.pdf`.
- Invalid inputs return `INVALID_ARGUMENT`.

For HTTP/HTTPS inputs, the PDF is downloaded to the system temporary directory (`%TMP%` / `%TEMP%` on Windows) under a `scanspy-*` folder, analyzed there, and then deleted automatically before the command returns.

## Detection Engine

PDF scan detection uses only the public `ocr-detection.detect_ocr()` API on Python 3.13.13. The project maps the library result directly into document types:

- `status=true` -> `SCANNED`
- `status=partial` -> `MIXED_SCANNED`
- `status=false` -> `STANDARD`

The public API does not expose an `EMPTY` status. Blank PDFs follow the library result and are returned as `SCANNED` because `detect_ocr()` returns `status=true` for blank pages.

`scannedPages` comes from the page list returned by `detect_ocr()`. The public API does not return total page count, text page count, or confidence, so this project no longer infers those values from PDF internals. `pageCount` is only filled for `SCANNED` results where `status=true` means every listed page needs OCR; otherwise it is `0`. `textPages` is always `0`, and `confidence` is always `0.0`.

## Result Data

Successful and failed calls both return `data` as a list so Java can deserialize a stable `R<List<ScanDetectResult>>` DTO. Each input PDF or direct PDF URL has one result item:

```json
[
  {
    "code": 200,
    "success": true,
    "source": "C:\\path\\to\\file.pdf",
    "fileName": "file.pdf",
    "fileSize": 12345,
    "suffix": "PDF",
    "scanned": false,
    "type": "STANDARD",
    "confidence": 0.0,
    "pageCount": 0,
    "scannedPages": 0,
    "textPages": 0,
    "sourceType": "FILE"
  }
]
```

Success and failure items use the same fields in the same order. On item failure, that item's `code` is `400` and `type` is `UNKNOWN`. Error details live only on the outer `R` through `msg` and `errorCode`. If any item fails, the outer `R` uses `code=400` and `success=false`, while `data` still contains every input result.

Enum-style constants are defined in `src/scanspy/enums.py`:

- `DocumentType`: `STANDARD`, `SCANNED`, `MIXED_SCANNED`, `EMPTY`, `UNKNOWN`
- `PageType`: `TEXT_PAGE`, `SCANNED_PAGE`, `UNKNOWN_PAGE`
- `SourceType`: `FILE`, `URL`, `UNKNOWN`
- `ErrorCode`: `INVALID_ARGUMENT`, `PARTIAL_FAILURE`, `PDF_NOT_FOUND`, `PDF_NOT_FILE`, `PDF_DOWNLOAD_ERROR`, `PDF_URL_NOT_PDF`, `PDF_PARSE_ERROR`, `PDF_EMPTY`

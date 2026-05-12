import io
import json
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fitz
from ocr_detection import detect_ocr

from scanspy.cli import main
from scanspy.enums import DocumentType, ErrorCode, PageType, SourceType


def write_text_pdf(path: Path, pages: int = 1) -> None:
    doc = fitz.open()
    for page_index in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text(
            (72, 96),
            f"This is a normal searchable PDF page {page_index + 1}. " * 8,
            fontsize=12,
        )
    doc.save(path)
    doc.close()


def write_scanned_page(page: fitz.Page) -> None:
    rect = page.rect
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 900, 1200), False)
    pix.clear_with(240)
    page.insert_image(rect, stream=pix.tobytes("png"))


def write_scanned_pdf(path: Path, pages: int = 1, ocr_text: bool = False) -> None:
    doc = fitz.open()
    for page_index in range(pages):
        page = doc.new_page(width=595, height=842)
        write_scanned_page(page)
        if ocr_text:
            page.insert_text(
                (72, 96),
                f"OCR text layer for scanned page {page_index + 1}. " * 8,
                fontsize=12,
            )
    doc.save(path)
    doc.close()


def write_mixed_pdf(path: Path) -> None:
    doc = fitz.open()
    text_page = doc.new_page(width=595, height=842)
    text_page.insert_text((72, 96), "This page is text based. " * 20, fontsize=12)
    scanned_page = doc.new_page(width=595, height=842)
    write_scanned_page(scanned_page)
    doc.save(path)
    doc.close()


def write_scanned_with_blank_pdf(path: Path) -> None:
    doc = fitz.open()
    scanned_page = doc.new_page(width=595, height=842)
    write_scanned_page(scanned_page)
    doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()


def write_blank_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()


def run_cli(*args: str) -> tuple[int, dict]:
    stdout = io.StringIO()
    exit_code = main(list(args), stdout=stdout)
    return exit_code, json.loads(stdout.getvalue())


def test_standard_pdf_returns_r_wrapped_standard_result(tmp_path: Path) -> None:
    pdf = tmp_path / "standard.pdf"
    write_text_pdf(pdf, pages=2)

    exit_code, payload = run_cli(str(pdf))

    assert exit_code == 0
    assert payload["code"] == 200
    assert payload["success"] is True
    assert payload["msg"] == "操作成功"
    assert payload["errorCode"] == ""
    assert len(payload["data"]) == 1
    result = payload["data"][0]
    assert result["code"] == 200
    assert result["success"] is True
    assert result["source"] == str(pdf)
    assert result["fileName"] == "standard.pdf"
    assert result["fileSize"] == pdf.stat().st_size
    assert result["suffix"] == "PDF"
    assert result["scanned"] is False
    assert result["type"] == "STANDARD"
    assert result["pageCount"] == 0
    assert result["scannedPages"] == 0
    assert result["textPages"] == 0
    assert result["confidence"] == 0.0
    assert result["sourceType"] == "FILE"


def test_scanned_pdf_returns_scanned_true(tmp_path: Path) -> None:
    pdf = tmp_path / "scanned.pdf"
    write_scanned_pdf(pdf, pages=2)

    exit_code, payload = run_cli(str(pdf))

    assert exit_code == 0
    result = payload["data"][0]
    assert result["scanned"] is True
    assert result["type"] == "SCANNED"
    assert result["pageCount"] == 2
    assert result["scannedPages"] == 2
    assert result["textPages"] == 0
    assert result["confidence"] == 0.0


def test_searchable_image_pdf_follows_ocr_detection_public_status(tmp_path: Path) -> None:
    pdf = tmp_path / "ocr-scanned.pdf"
    write_scanned_pdf(pdf, pages=1, ocr_text=True)

    exit_code, payload = run_cli(str(pdf))

    library_result = detect_ocr(
        pdf,
        parallel=False,
        include_images=False,
        accuracy_mode=False,
        metadata_only=False,
    )
    assert exit_code == 0
    assert library_result["status"] == "false"
    result = payload["data"][0]
    assert result["scanned"] is False
    assert result["type"] == "STANDARD"
    assert result["scannedPages"] == 0


def test_mixed_pdf_returns_mixed_scanned(tmp_path: Path) -> None:
    pdf = tmp_path / "mixed.pdf"
    write_mixed_pdf(pdf)

    exit_code, payload = run_cli(str(pdf))

    assert exit_code == 0
    result = payload["data"][0]
    assert result["scanned"] is True
    assert result["type"] == "MIXED_SCANNED"
    assert result["pageCount"] == 0
    assert result["scannedPages"] == 1
    assert result["textPages"] == 0


def test_scanned_pdf_with_blank_pages_uses_ocr_detection_status(tmp_path: Path) -> None:
    pdf = tmp_path / "scanned-with-blank.pdf"
    write_scanned_with_blank_pdf(pdf)

    exit_code, payload = run_cli(str(pdf))

    assert exit_code == 0
    result = payload["data"][0]
    assert result["scanned"] is True
    assert result["type"] == "SCANNED"
    assert result["pageCount"] == 2
    assert result["scannedPages"] == 2
    assert result["textPages"] == 0


def test_blank_pdf_follows_ocr_detection_public_status(tmp_path: Path) -> None:
    pdf = tmp_path / "blank.pdf"
    write_blank_pdf(pdf)

    exit_code, payload = run_cli(str(pdf))

    library_result = detect_ocr(
        pdf,
        parallel=False,
        include_images=False,
        accuracy_mode=False,
        metadata_only=False,
    )
    assert exit_code == 0
    assert library_result == {"status": "true", "pages": [1]}
    result = payload["data"][0]
    assert result["scanned"] is True
    assert result["type"] == DocumentType.SCANNED.value
    assert result["pageCount"] == 1
    assert result["scannedPages"] == 1
    assert result["textPages"] == 0


def test_missing_file_returns_r_wrapped_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"

    exit_code, payload = run_cli(str(missing))

    assert exit_code == 1
    assert payload["code"] == 400
    assert payload["success"] is False
    assert payload["msg"] == "PDF文件不存在"
    assert payload["errorCode"] == ErrorCode.PDF_NOT_FOUND.value
    assert payload["data"] == [{
        "code": 400,
        "success": False,
        "source": str(missing),
        "fileName": "missing.pdf",
        "fileSize": 0,
        "suffix": "PDF",
        "scanned": False,
        "type": DocumentType.UNKNOWN.value,
        "confidence": 0.0,
        "pageCount": 0,
        "scannedPages": 0,
        "textPages": 0,
        "sourceType": SourceType.FILE.value,
    }]


def test_non_pdf_local_argument_is_rejected_before_file_lookup(tmp_path: Path) -> None:
    not_pdf = tmp_path / "input.txt"
    not_pdf.write_text("not a pdf", encoding="utf-8")

    exit_code, payload = run_cli(str(not_pdf))

    assert exit_code == 1
    assert payload["code"] == 400
    assert payload["success"] is False
    assert payload["msg"] == "输入必须是PDF文件或链接"
    assert payload["errorCode"] == ErrorCode.INVALID_ARGUMENT.value
    assert payload["data"] == [{
        "code": 400,
        "success": False,
        "source": str(not_pdf),
        "fileName": "input.txt",
        "fileSize": not_pdf.stat().st_size,
        "suffix": "TXT",
        "scanned": False,
        "type": DocumentType.UNKNOWN.value,
        "confidence": 0.0,
        "pageCount": 0,
        "scannedPages": 0,
        "textPages": 0,
        "sourceType": SourceType.UNKNOWN.value,
    }]


def test_unsupported_link_scheme_is_rejected() -> None:
    source = "ftp://example.com/file.pdf"

    exit_code, payload = run_cli(source)

    assert exit_code == 1
    assert payload["msg"] == "输入必须是PDF文件或链接"
    assert payload["errorCode"] == ErrorCode.INVALID_ARGUMENT.value
    assert payload["data"][0]["source"] == source
    assert payload["data"][0]["fileName"] == "file.pdf"
    assert payload["data"][0]["fileSize"] == 0
    assert payload["data"][0]["suffix"] == "PDF"
    assert payload["data"][0]["sourceType"] == SourceType.UNKNOWN.value


def test_url_path_suffix_must_be_pdf_even_if_content_is_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "remote.pdf"
    write_text_pdf(pdf)

    class Handler(BaseHTTPRequestHandler):
        called = False

        def do_GET(self) -> None:
            Handler.called = True
            body = pdf.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = f"http://127.0.0.1:{server.server_port}/remote.docx"
        exit_code, payload = run_cli(source)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert Handler.called is False
    assert exit_code == 1
    assert payload["msg"] == "输入必须是PDF文件或链接"
    assert payload["errorCode"] == ErrorCode.INVALID_ARGUMENT.value
    assert payload["data"][0]["source"] == source
    assert payload["data"][0]["fileName"] == "remote.docx"
    assert payload["data"][0]["fileSize"] == 0
    assert payload["data"][0]["suffix"] == "DOCX"


def test_corrupt_pdf_returns_parse_error(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nnot a real pdf")

    exit_code, payload = run_cli(str(corrupt))

    assert exit_code == 1
    assert payload["code"] == 400
    assert payload["success"] is False
    assert payload["msg"] == "PDF解析失败"
    assert payload["errorCode"] == ErrorCode.PDF_PARSE_ERROR.value
    result = payload["data"][0]
    assert result["code"] == 400
    assert result["type"] == DocumentType.UNKNOWN.value
    assert result["sourceType"] == SourceType.FILE.value


def test_direct_pdf_url_is_downloaded_and_detected(tmp_path: Path) -> None:
    pdf = tmp_path / "remote.pdf"
    write_text_pdf(pdf)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = pdf.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        exit_code, payload = run_cli(f"http://127.0.0.1:{server.server_port}/remote.pdf")
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert exit_code == 0
    result = payload["data"][0]
    assert result["sourceType"] == "URL"
    assert result["fileName"] == "remote.pdf"
    assert result["fileSize"] == pdf.stat().st_size
    assert result["suffix"] == "PDF"
    assert result["type"] == "STANDARD"


def test_direct_pdf_url_temp_download_is_deleted(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "remote.pdf"
    temp_root = tmp_path / "custom-temp"
    temp_root.mkdir()
    write_text_pdf(pdf)
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = pdf.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        exit_code, payload = run_cli(f"http://127.0.0.1:{server.server_port}/remote.pdf")
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert exit_code == 0
    assert payload["data"][0]["sourceType"] == "URL"
    assert list(temp_root.glob("scanspy-*")) == []


def test_non_pdf_url_returns_direct_pdf_error() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"<html>not a pdf</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        exit_code, payload = run_cli(f"http://127.0.0.1:{server.server_port}/page")
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert exit_code == 1
    assert payload["code"] == 400
    assert payload["success"] is False
    assert payload["msg"] == "输入必须是PDF文件或链接"
    assert payload["errorCode"] == ErrorCode.INVALID_ARGUMENT.value
    result = payload["data"][0]
    assert result["code"] == 400
    assert result["type"] == DocumentType.UNKNOWN.value
    assert result["sourceType"] == SourceType.UNKNOWN.value


def test_root_script_entrypoint_outputs_json(tmp_path: Path) -> None:
    pdf = tmp_path / "standard.pdf"
    write_text_pdf(pdf)
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scanspy.py", str(pdf)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"][0]["type"] == "STANDARD"


def test_multiple_inputs_return_one_result_per_pdf(tmp_path: Path) -> None:
    standard = tmp_path / "standard.pdf"
    scanned = tmp_path / "scanned.pdf"
    missing = tmp_path / "missing.pdf"
    write_text_pdf(standard)
    write_scanned_pdf(scanned)

    exit_code, payload = run_cli(str(standard), str(scanned), str(missing))

    assert exit_code == 1
    assert payload["code"] == 400
    assert payload["success"] is False
    assert payload["msg"] == "部分PDF处理失败"
    assert payload["errorCode"] == ErrorCode.PARTIAL_FAILURE.value
    assert [item["source"] for item in payload["data"]] == [
        str(standard),
        str(scanned),
        str(missing),
    ]
    assert [item["success"] for item in payload["data"]] == [True, True, False]
    assert [item["code"] for item in payload["data"]] == [200, 200, 400]
    assert [item["type"] for item in payload["data"]] == [
        DocumentType.STANDARD.value,
        DocumentType.SCANNED.value,
        DocumentType.UNKNOWN.value,
    ]
    assert payload["data"][2]["code"] == 400


def test_success_and_failure_data_items_have_same_response_schema(tmp_path: Path) -> None:
    standard = tmp_path / "standard.pdf"
    missing = tmp_path / "missing.pdf"
    write_text_pdf(standard)

    _, payload = run_cli(str(standard), str(missing))

    success_item, failure_item = payload["data"]
    expected_keys = [
        "code",
        "success",
        "source",
        "fileName",
        "fileSize",
        "suffix",
        "scanned",
        "type",
        "confidence",
        "pageCount",
        "scannedPages",
        "textPages",
        "sourceType",
    ]
    assert list(success_item.keys()) == expected_keys
    assert list(failure_item.keys()) == expected_keys


def test_enums_expose_java_style_codes() -> None:
    assert DocumentType.STANDARD.value == "STANDARD"
    assert DocumentType.SCANNED.value == "SCANNED"
    assert DocumentType.MIXED_SCANNED.value == "MIXED_SCANNED"
    assert DocumentType.EMPTY.value == "EMPTY"
    assert DocumentType.UNKNOWN.value == "UNKNOWN"
    assert PageType.SCANNED_PAGE.value == "SCANNED_PAGE"
    assert SourceType.FILE.value == "FILE"
    assert SourceType.URL.value == "URL"
    assert ErrorCode.PDF_PARSE_ERROR.value == "PDF_PARSE_ERROR"
    assert ErrorCode.PARTIAL_FAILURE.value == "PARTIAL_FAILURE"


def test_production_detection_uses_only_ocr_detection_public_api() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cli_source = (repo_root / "src" / "scanspy" / "cli.py").read_text(encoding="utf-8")

    assert "from ocr_detection import OCRStatus, detect_ocr" in cli_source
    assert "ocr_detection._detector" not in cli_source
    assert "PDFAnalyzer" not in cli_source
    assert "OCRPageType" not in cli_source

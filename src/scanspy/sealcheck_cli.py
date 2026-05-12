from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Iterable, TextIO
from urllib.parse import unquote, urlparse

import fitz
import requests

from scanspy.enums import ErrorCode, SourceType


HTTP_TIMEOUT_SECONDS = 20


class SealCheckError(Exception):
    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        source_type: SourceType = SourceType.UNKNOWN,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.source_type = source_type


def main(argv: Iterable[str] | None = None, stdout: TextIO | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    output = sys.stdout if stdout is None else stdout

    if not args:
        _write_json(
            output,
            _wrap_failure(
                [_error_result("", SourceType.UNKNOWN)],
                "参数错误",
                ErrorCode.INVALID_ARGUMENT,
            ),
        )
        return 1

    processed_results = [_check_one(source) for source in args]
    results = [item for item, _, _ in processed_results]
    failed_results = [
        (item, message, error_code)
        for item, message, error_code in processed_results
        if error_code is not None
    ]
    if failed_results:
        message = failed_results[0][1] if len(args) == 1 else "部分PDF签章检测失败"
        error_code = (
            failed_results[0][2]
            if len(args) == 1
            else ErrorCode.PARTIAL_FAILURE
        )
        _write_json(output, _wrap_failure(results, str(message), error_code))
        return 1

    _write_json(output, _success(results))
    return 0


def check_input(source: str) -> dict[str, object]:
    if _is_url(source):
        return _check_url(source)
    return _check_file(Path(source), SourceType.FILE)


def _check_one(source: str) -> tuple[dict[str, object], str, ErrorCode | None]:
    validation_error = _validate_source(source)
    if validation_error is not None:
        message, error_code = validation_error
        return (
            _error_result(source, SourceType.UNKNOWN),
            message,
            error_code,
        )

    try:
        result = check_input(source)
    except SealCheckError as exc:
        return (
            _error_result(source, exc.source_type),
            exc.message,
            exc.error_code,
        )

    return _success_result(source, result), "", None


def _validate_source(source: str) -> tuple[str, ErrorCode] | None:
    path = Path(source)
    if path.drive:
        if path.suffix.lower() != ".pdf":
            return "输入必须是PDF文件或链接", ErrorCode.INVALID_ARGUMENT
        return None

    parsed = urlparse(source)
    if parsed.scheme:
        if not _is_url(source):
            return "输入必须是PDF文件或链接", ErrorCode.INVALID_ARGUMENT
        if Path(unquote(parsed.path)).suffix.lower() != ".pdf":
            return "输入必须是PDF文件或链接", ErrorCode.INVALID_ARGUMENT
        return None

    if path.suffix.lower() != ".pdf":
        return "输入必须是PDF文件或链接", ErrorCode.INVALID_ARGUMENT

    return None


def _check_url(url: str) -> dict[str, object]:
    try:
        response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SealCheckError("PDF下载失败", ErrorCode.PDF_DOWNLOAD_ERROR, SourceType.URL) from exc

    content = response.content
    content_type = response.headers.get("Content-Type", "").lower()
    if "pdf" not in content_type and not content.startswith(b"%PDF"):
        raise SealCheckError("链接不是PDF直链", ErrorCode.PDF_URL_NOT_PDF, SourceType.URL)
    if not content.startswith(b"%PDF"):
        raise SealCheckError("链接内容不是有效PDF", ErrorCode.PDF_URL_NOT_PDF, SourceType.URL)

    with tempfile.TemporaryDirectory(prefix="sealcheck-") as tmp_dir:
        pdf_path = Path(tmp_dir) / "download.pdf"
        pdf_path.write_bytes(content)
        result = _check_file(pdf_path, SourceType.URL)
        result["fileSize"] = len(content)
        return result


def _check_file(path: Path, source_type: SourceType) -> dict[str, object]:
    if not path.exists():
        raise SealCheckError("PDF文件不存在", ErrorCode.PDF_NOT_FOUND, source_type)
    if not path.is_file():
        raise SealCheckError("PDF路径不是文件", ErrorCode.PDF_NOT_FILE, source_type)

    try:
        has_signature = _has_signature_marker(path)
    except Exception as exc:
        raise SealCheckError("PDF解析失败", ErrorCode.PDF_PARSE_ERROR, source_type) from exc

    return {
        "hasSignature": has_signature,
        "sourceType": source_type.value,
    }


def _has_signature_marker(path: Path) -> bool:
    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise ValueError("not a pdf")

    if _has_signature_marker_in_bytes(data):
        return True

    doc = fitz.open(path)
    try:
        for page in doc:
            for widget in page.widgets() or []:
                if str(getattr(widget, "field_type_string", "")).lower() == "signature":
                    return True
        return False
    finally:
        doc.close()


def _has_signature_marker_in_bytes(data: bytes) -> bool:
    compact = re.sub(rb"\s+", b"", data)
    if b"/FT/Sig" in compact:
        return True
    return b"/ByteRange[" in compact and b"/Type/Sig" in compact


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _source_metadata(
    source: str,
    source_type: SourceType,
    file_size: int | None = None,
) -> dict[str, object]:
    parsed = urlparse(source)
    if parsed.scheme and parsed.netloc:
        file_name = Path(unquote(parsed.path)).name
    else:
        file_name = Path(source).name

    suffix = Path(file_name).suffix.removeprefix(".").upper()
    if file_size is None:
        file_size = 0 if parsed.scheme and parsed.netloc else _local_file_size(source)

    return {
        "fileName": file_name,
        "fileSize": file_size,
        "suffix": suffix,
    }


def _local_file_size(source: str) -> int:
    path = Path(source)
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _success(data: list[dict[str, object]]) -> dict[str, object]:
    return {
        "code": 200,
        "success": True,
        "data": data,
        "msg": "操作成功",
        "errorCode": "",
    }


def _wrap_failure(
    data: list[dict[str, object]],
    message: str,
    error_code: ErrorCode,
) -> dict[str, object]:
    return {
        "code": 400,
        "success": False,
        "data": data,
        "msg": message,
        "errorCode": error_code.value,
    }


def _success_result(source: str, result: dict[str, object]) -> dict[str, object]:
    source_type = SourceType(str(result["sourceType"]))
    file_size = result.get("fileSize")
    metadata = _source_metadata(
        source,
        source_type,
        int(file_size) if isinstance(file_size, int) else None,
    )
    return {
        "code": 200,
        "success": True,
        "source": source,
        "fileName": metadata["fileName"],
        "fileSize": metadata["fileSize"],
        "suffix": metadata["suffix"],
        "hasSignature": result["hasSignature"],
        "sourceType": result["sourceType"],
    }


def _error_result(source: str, source_type: SourceType) -> dict[str, object]:
    metadata = _source_metadata(source, source_type)
    return {
        "code": 400,
        "success": False,
        "source": source,
        "fileName": metadata["fileName"],
        "fileSize": metadata["fileSize"],
        "suffix": metadata["suffix"],
        "hasSignature": False,
        "sourceType": source_type.value,
    }


def _write_json(output: TextIO, payload: dict[str, object]) -> None:
    output.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    output.write("\n")

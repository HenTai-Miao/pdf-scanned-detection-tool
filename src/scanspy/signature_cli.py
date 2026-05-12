from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, TextIO
from urllib.parse import unquote, urlparse

import fitz
import requests
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.diff_analysis import ModificationLevel
from pyhanko.sign.validation import validate_pdf_signature

from scanspy.cli import HTTP_TIMEOUT_SECONDS, ScanSpyError, _is_url, _source_metadata
from scanspy.enums import ErrorCode, SourceType


def main(argv: Iterable[str] | None = None, stdout: TextIO | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    output = sys.stdout if stdout is None else stdout

    if not args:
        _write_json(
            output,
            _wrap_failure(
                [_error_result("", ErrorCode.INVALID_ARGUMENT, SourceType.UNKNOWN)],
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
            _error_result(source, error_code, SourceType.UNKNOWN),
            message,
            error_code,
        )

    try:
        result = check_input(source)
    except ScanSpyError as exc:
        return (
            _error_result(source, exc.error_code, exc.source_type),
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
        raise ScanSpyError("PDF下载失败", ErrorCode.PDF_DOWNLOAD_ERROR, SourceType.URL) from exc

    content = response.content
    content_type = response.headers.get("Content-Type", "").lower()
    if "pdf" not in content_type and not content.startswith(b"%PDF"):
        raise ScanSpyError("链接不是PDF直链", ErrorCode.PDF_URL_NOT_PDF, SourceType.URL)
    if not content.startswith(b"%PDF"):
        raise ScanSpyError("链接内容不是有效PDF", ErrorCode.PDF_URL_NOT_PDF, SourceType.URL)

    with tempfile.TemporaryDirectory(prefix="signspy-") as tmp_dir:
        pdf_path = Path(tmp_dir) / "download.pdf"
        pdf_path.write_bytes(content)
        result = _check_file(pdf_path, SourceType.URL)
        result["fileSize"] = len(content)
        return result


def _check_file(path: Path, source_type: SourceType) -> dict[str, object]:
    if not path.exists():
        raise ScanSpyError("PDF文件不存在", ErrorCode.PDF_NOT_FOUND, source_type)
    if not path.is_file():
        raise ScanSpyError("PDF路径不是文件", ErrorCode.PDF_NOT_FILE, source_type)

    try:
        with path.open("rb") as stream:
            reader = PdfFileReader(stream)
            signatures = [
                _signature_detail(reader, embedded_signature, index)
                for index, embedded_signature in enumerate(reader.embedded_signatures, start=1)
            ]
    except ScanSpyError:
        raise
    except Exception as exc:
        try:
            signatures = _fallback_signature_details(path)
        except Exception as fallback_exc:
            raise ScanSpyError(
                "PDF解析失败",
                ErrorCode.PDF_PARSE_ERROR,
                source_type,
            ) from fallback_exc
        if not signatures:
            raise ScanSpyError("PDF解析失败", ErrorCode.PDF_PARSE_ERROR, source_type) from exc

    return {
        "hasSignature": bool(signatures),
        "signatureCount": len(signatures),
        "allSignaturesValid": bool(signatures)
        and all(bool(item["signatureValid"]) for item in signatures),
        "allSignaturesIntact": bool(signatures)
        and all(bool(item["signatureIntact"]) for item in signatures),
        "signatures": signatures,
        "sourceType": source_type.value,
    }


def _signature_detail(
    reader: PdfFileReader,
    embedded_signature: object,
    index: int,
) -> dict[str, object]:
    status = _validate_signature(embedded_signature)
    visible = _is_visible_signature(embedded_signature)
    return {
        "index": index,
        "fieldName": str(getattr(embedded_signature, "field_name", "")),
        "pageNumber": _signature_page_number(reader, embedded_signature) if visible else 0,
        "visible": visible,
        "signatureValid": status["valid"],
        "signatureIntact": status["intact"],
        "signerName": _signer_name(embedded_signature),
        "signTime": _sign_time(embedded_signature),
    }


def _validate_signature(embedded_signature: object) -> dict[str, bool]:
    try:
        status = validate_pdf_signature(embedded_signature)
    except Exception:
        return {"valid": False, "intact": False}

    modification_level = getattr(status, "modification_level", None)
    signature_intact = bool(getattr(status, "intact", False)) and (
        modification_level != ModificationLevel.OTHER
    )
    return {
        "valid": bool(getattr(status, "valid", False)),
        "intact": signature_intact,
    }


def _is_visible_signature(embedded_signature: object) -> bool:
    rect = _signature_rect(embedded_signature)
    if len(rect) != 4:
        return False

    try:
        x1, y1, x2, y2 = [float(value) for value in rect]
    except (TypeError, ValueError):
        return False

    return x2 > x1 and y2 > y1


def _signature_rect(embedded_signature: object) -> list[object]:
    sig_field = getattr(embedded_signature, "sig_field", {})
    try:
        rect = sig_field.get("/Rect", [])
    except AttributeError:
        return []
    return list(rect or [])


def _signature_page_number(reader: PdfFileReader, embedded_signature: object) -> int:
    sig_field = getattr(embedded_signature, "sig_field", {})
    try:
        page_object = sig_field["/P"]
    except Exception:
        return 0

    page_ref = getattr(page_object, "container_ref", None)
    if page_ref is None:
        return 0

    page_count = _page_count(reader)
    for page_index in range(page_count):
        try:
            candidate_ref = reader._walk_page_tree(page_index, False)[0]
            candidate_page = candidate_ref.get_object()
        except Exception:
            continue

        if getattr(candidate_page, "container_ref", None) == page_ref:
            return page_index + 1

    return 0


def _page_count(reader: PdfFileReader) -> int:
    try:
        return int(reader.root["/Pages"]["/Count"])
    except Exception:
        return 0


def _signer_name(embedded_signature: object) -> str:
    signer_cert = getattr(embedded_signature, "signer_cert", None)
    subject = getattr(signer_cert, "subject", None)
    return str(getattr(subject, "human_friendly", "") or "")


def _sign_time(embedded_signature: object) -> str:
    timestamp = getattr(embedded_signature, "self_reported_timestamp", None)
    if timestamp is None:
        return ""
    try:
        return timestamp.isoformat()
    except AttributeError:
        return str(timestamp)


def _fallback_signature_details(path: Path) -> list[dict[str, object]]:
    data = path.read_bytes()
    signature_objects = _signature_objects_from_bytes(data)
    if not signature_objects:
        return []

    widgets_by_signature = _signature_widgets_from_bytes(data, path)
    signatures = []
    for index, signature_object in enumerate(signature_objects, start=1):
        widgets = widgets_by_signature.get(int(signature_object["objectId"]), [])
        visible_widgets = [
            widget
            for widget in widgets
            if widget["visible"] and int(widget["pageNumber"]) > 0
        ]
        selected_widget = visible_widgets[0] if visible_widgets else (widgets[0] if widgets else {})
        visible = bool(visible_widgets)
        signatures.append({
            "index": index,
            "fieldName": str(
                selected_widget.get("fieldName")
                or f"signature obj {signature_object['objectId']}"
            ),
            "pageNumber": int(selected_widget.get("pageNumber", 0)) if visible else 0,
            "visible": visible,
            "signatureValid": False,
            "signatureIntact": False,
            "signerName": "",
            "signTime": str(signature_object.get("signTime", "")),
        })
    return signatures


def _signature_objects_from_bytes(data: bytes) -> list[dict[str, object]]:
    objects = []
    for object_id, body in _iter_pdf_objects(data):
        body_without_spaces = re.sub(rb"\s+", b"", body)
        if b"/ByteRange" not in body:
            continue
        if b"/Type/Sig" not in body_without_spaces:
            continue
        objects.append({
            "objectId": object_id,
            "signTime": _pdf_date_to_iso(_extract_pdf_literal(body, b"/M")),
        })
    return objects


def _signature_widgets_from_bytes(
    data: bytes,
    path: Path,
) -> dict[int, list[dict[str, object]]]:
    page_numbers_by_xref = _page_numbers_by_xref(path)
    widgets_by_signature: dict[int, list[dict[str, object]]] = {}

    for _object_id, body in _iter_pdf_objects(data):
        body_without_spaces = re.sub(rb"\s+", b"", body)
        if b"/FT/Sig" not in body_without_spaces:
            continue

        signature_ref = _extract_indirect_ref(body, b"/V")
        if signature_ref is None:
            continue

        rect = _extract_rect(body)
        page_ref = _extract_indirect_ref(body, b"/P")
        page_number = page_numbers_by_xref.get(page_ref, 0) if page_ref else 0
        field_name = _extract_pdf_literal(body, b"/T")
        widgets_by_signature.setdefault(signature_ref, []).append({
            "fieldName": field_name,
            "pageNumber": page_number,
            "visible": _rect_is_visible(rect),
        })

    for widgets in widgets_by_signature.values():
        widgets.sort(key=lambda item: int(item["pageNumber"]) or 10**9)
    return widgets_by_signature


def _iter_pdf_objects(data: bytes) -> Iterable[tuple[int, bytes]]:
    pattern = re.compile(rb"(?s)(\d+)\s+\d+\s+obj\b(.*?)endobj")
    for match in pattern.finditer(data):
        yield int(match.group(1)), match.group(2)


def _extract_indirect_ref(body: bytes, key: bytes) -> int | None:
    match = re.search(re.escape(key) + rb"\s+(\d+)\s+\d+\s+R", body)
    if match is None:
        return None
    return int(match.group(1))


def _extract_pdf_literal(body: bytes, key: bytes) -> str:
    match = re.search(
        re.escape(key) + rb"\s*\(((?:\\.|[^\\)])*)\)",
        body,
        flags=re.S,
    )
    if match is None:
        return ""
    return _decode_pdf_literal(match.group(1))


def _decode_pdf_literal(value: bytes) -> str:
    result = bytearray()
    index = 0
    while index < len(value):
        current = value[index]
        if current != 0x5C:
            result.append(current)
            index += 1
            continue

        index += 1
        if index >= len(value):
            break

        escaped = value[index]
        if 48 <= escaped <= 55:
            digits = [escaped]
            index += 1
            while index < len(value) and len(digits) < 3 and 48 <= value[index] <= 55:
                digits.append(value[index])
                index += 1
            result.append(int(bytes(digits), 8))
            continue

        mapped = {
            ord("n"): ord("\n"),
            ord("r"): ord("\r"),
            ord("t"): ord("\t"),
            ord("b"): ord("\b"),
            ord("f"): ord("\f"),
            ord("("): ord("("),
            ord(")"): ord(")"),
            ord("\\"): ord("\\"),
        }.get(escaped)
        if mapped is not None:
            result.append(mapped)
        elif escaped not in {ord("\n"), ord("\r")}:
            result.append(escaped)
        index += 1

    return result.decode("utf-8", errors="replace")


def _extract_rect(body: bytes) -> list[float]:
    match = re.search(rb"/Rect\s*\[([^\]]+)\]", body, flags=re.S)
    if match is None:
        return []
    values = re.findall(rb"[-+]?(?:\d+\.\d+|\d+)", match.group(1))
    return [float(value) for value in values[:4]]


def _rect_is_visible(rect: list[float]) -> bool:
    if len(rect) != 4:
        return False
    x1, y1, x2, y2 = rect
    return x2 > x1 and y2 > y1


def _page_numbers_by_xref(path: Path) -> dict[int, int]:
    doc = fitz.open(path)
    try:
        return {
            int(doc.load_page(page_index).xref): page_index + 1
            for page_index in range(doc.page_count)
        }
    finally:
        doc.close()


def _pdf_date_to_iso(value: str) -> str:
    if not value:
        return ""

    text = value[2:] if value.startswith("D:") else value
    match = re.match(
        r"^(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([Zz]|[+-]\d{2}'?\d{2}'?)?",
        text,
    )
    if match is None:
        return value

    year = int(match.group(1))
    month = int(match.group(2) or "1")
    day = int(match.group(3) or "1")
    hour = int(match.group(4) or "0")
    minute = int(match.group(5) or "0")
    second = int(match.group(6) or "0")
    tzinfo = _pdf_date_timezone(match.group(7) or "")
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=tzinfo).isoformat()
    except ValueError:
        return value


def _pdf_date_timezone(value: str) -> timezone | None:
    if not value:
        return None
    if value.upper() == "Z":
        return timezone.utc

    sign = 1 if value[0] == "+" else -1
    digits = re.sub(r"\D", "", value[1:])
    if len(digits) < 2:
        return None

    hours = int(digits[:2])
    minutes = int(digits[2:4] or "0")
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


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
        "signatureCount": result["signatureCount"],
        "allSignaturesValid": result["allSignaturesValid"],
        "allSignaturesIntact": result["allSignaturesIntact"],
        "signatures": result["signatures"],
        "sourceType": result["sourceType"],
    }


def _error_result(
    source: str,
    error_code: ErrorCode,
    source_type: SourceType,
) -> dict[str, object]:
    metadata = _source_metadata(source, source_type)
    return {
        "code": 400,
        "success": False,
        "source": source,
        "fileName": metadata["fileName"],
        "fileSize": metadata["fileSize"],
        "suffix": metadata["suffix"],
        "hasSignature": False,
        "signatureCount": 0,
        "allSignaturesValid": False,
        "allSignaturesIntact": False,
        "signatures": [],
        "sourceType": source_type.value,
    }


def _write_json(output: TextIO, payload: dict[str, object]) -> None:
    output.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    output.write("\n")

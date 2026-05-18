from __future__ import annotations

import atexit
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from enum import Enum
import math
import os
from pathlib import Path

import fitz

from scanspy.enums import DocumentType


FULL_PAGE_IMAGE_AREA_RATIO = 0.75
FULL_PAGE_IMAGE_DIMENSION_RATIO = 0.85
FULL_PAGE_VECTOR_DIMENSION_RATIO = 0.85
FULL_PAGE_VECTOR_AREA_RATIO = 0.25
EDGE_MARGIN_RATIO = 0.12
PARALLEL_PAGE_THRESHOLD = 8
WORKER_ENV_VAR = "SCANSPY_PDF_WORKERS"
_WORKER_DOC: fitz.Document | None = None


class StructuralPageType(Enum):
    STANDARD_PAGE = "STANDARD_PAGE"
    SCANNED_PAGE = "SCANNED_PAGE"
    OCR_SCANNED_PAGE = "OCR_SCANNED_PAGE"
    BLANK_PAGE = "BLANK_PAGE"


@dataclass(frozen=True)
class PageClassification:
    page_type: StructuralPageType
    has_text: bool


@dataclass(frozen=True)
class PDFClassification:
    document_type: DocumentType
    page_count: int
    scanned_pages: int
    text_pages: int


def classify_pdf(path: Path, workers: int | None = None) -> PDFClassification:
    worker_count = 1
    doc = fitz.open(path)
    try:
        page_count = doc.page_count
        worker_count = _resolve_worker_count(page_count, workers)
        if worker_count <= 1:
            page_results = [_classify_page(page) for page in doc]
        else:
            page_results = []
    finally:
        doc.close()

    if worker_count > 1:
        page_results = _classify_pages_parallel(path, page_count, worker_count)

    return _summarize_page_results(page_results)


def _summarize_page_results(page_results: list[PageClassification]) -> PDFClassification:
    scanned_pages = sum(
        1
        for result in page_results
        if result.page_type
        in {StructuralPageType.SCANNED_PAGE, StructuralPageType.OCR_SCANNED_PAGE}
    )
    text_pages = sum(1 for result in page_results if result.has_text)
    has_ocr_scanned_page = any(
        result.page_type == StructuralPageType.OCR_SCANNED_PAGE
        for result in page_results
    )

    if scanned_pages and (text_pages or has_ocr_scanned_page):
        document_type = DocumentType.MIXED_SCANNED
    elif scanned_pages:
        document_type = DocumentType.SCANNED
    else:
        document_type = DocumentType.STANDARD

    return PDFClassification(
        document_type=document_type,
        page_count=len(page_results),
        scanned_pages=scanned_pages,
        text_pages=text_pages,
    )


def _classify_pages_parallel(
    path: Path,
    page_count: int,
    worker_count: int,
) -> list[PageClassification]:
    chunk_size = max(1, page_count // (worker_count * 4))
    with ProcessPoolExecutor(
        max_workers=worker_count,
        initializer=_init_worker,
        initargs=(str(path),),
    ) as executor:
        return list(
            executor.map(
                _classify_worker_page,
                range(page_count),
                chunksize=chunk_size,
            )
        )


def _init_worker(path: str) -> None:
    global _WORKER_DOC
    _WORKER_DOC = fitz.open(path)
    atexit.register(_close_worker_doc)


def _close_worker_doc() -> None:
    global _WORKER_DOC
    if _WORKER_DOC is not None:
        _WORKER_DOC.close()
        _WORKER_DOC = None


def _classify_worker_page(page_index: int) -> PageClassification:
    if _WORKER_DOC is None:
        raise RuntimeError("PDF worker document is not initialized")
    return _classify_page(_WORKER_DOC.load_page(page_index))


def _resolve_worker_count(
    page_count: int,
    requested_workers: int | None,
) -> int:
    if page_count < PARALLEL_PAGE_THRESHOLD:
        return 1

    worker_count = requested_workers
    if worker_count is None:
        worker_count = _configured_worker_count()
    if worker_count is None:
        worker_count = _available_cpu_count()

    return min(page_count, max(1, worker_count))


def _configured_worker_count() -> int | None:
    value = os.getenv(WORKER_ENV_VAR)
    if value is None or not value.strip():
        return None

    normalized = value.strip().lower()
    if normalized == "all":
        return _available_cpu_count()

    try:
        worker_count = int(normalized)
    except ValueError:
        return None

    if worker_count <= 0:
        return _available_cpu_count()
    return worker_count


def _available_cpu_count() -> int:
    process_cpu_count = getattr(os, "process_cpu_count", None)
    if process_cpu_count is not None:
        cpu_count = process_cpu_count()
    else:
        cpu_count = os.cpu_count()
    return max(1, cpu_count or 1)


def _classify_page(page: fitz.Page) -> PageClassification:
    has_text = bool((page.get_text("text") or "").strip())
    if _has_full_page_image(page):
        page_type = (
            StructuralPageType.OCR_SCANNED_PAGE
            if has_text
            else StructuralPageType.SCANNED_PAGE
        )
        return PageClassification(
            page_type=page_type,
            has_text=has_text,
        )

    drawings = page.get_drawings()
    if _has_full_page_vector_from_drawings(page, drawings):
        page_type = (
            StructuralPageType.OCR_SCANNED_PAGE
            if has_text
            else StructuralPageType.SCANNED_PAGE
        )
        return PageClassification(
            page_type=page_type,
            has_text=has_text,
        )

    if has_text or drawings:
        return PageClassification(
            page_type=StructuralPageType.STANDARD_PAGE,
            has_text=has_text,
        )

    return PageClassification(
        page_type=StructuralPageType.BLANK_PAGE,
        has_text=False,
    )


def _has_full_page_image(page: fitz.Page) -> bool:
    page_rect = page.rect
    image_rects: list[fitz.Rect] = []
    for image in page.get_images(full=True):
        xref = image[0]
        for rect in page.get_image_rects(xref):
            clipped_rect = rect & page_rect
            if clipped_rect.is_empty:
                continue
            if _is_near_full_page_rect(clipped_rect, page_rect):
                return True
            image_rects.append(clipped_rect)

    return _rects_cover_page(image_rects, page_rect)


def _has_full_page_vector_from_drawings(page: fitz.Page, drawings: list[dict]) -> bool:
    drawing_rects = [
        drawing["rect"]
        for drawing in drawings
        if drawing.get("rect") is not None and not drawing["rect"].is_empty
        and _is_visible_nonwhite_drawing(drawing)
    ]
    if not drawing_rects:
        return False

    bounds = _rects_bounds(drawing_rects)
    if not _is_near_full_page_rect(
        bounds,
        page.rect,
        dimension_ratio=FULL_PAGE_VECTOR_DIMENSION_RATIO,
    ):
        return False

    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return False

    vector_area_ratio = min(
        sum(rect.width * rect.height for rect in drawing_rects) / page_area,
        1.0,
    )
    return vector_area_ratio >= FULL_PAGE_VECTOR_AREA_RATIO


def _is_visible_nonwhite_drawing(drawing: dict) -> bool:
    fill = drawing.get("fill")
    fill_opacity = drawing.get("fill_opacity")
    if fill is not None and (fill_opacity is None or fill_opacity > 0.05):
        if not _is_near_white(fill):
            return True

    color = drawing.get("color")
    stroke_opacity = drawing.get("stroke_opacity")
    if color is not None and (stroke_opacity is None or stroke_opacity > 0.05):
        if not _is_near_white(color):
            return True

    return False


def _is_near_white(color: tuple[float, ...]) -> bool:
    return len(color) >= 3 and min(color[:3]) >= 0.95


def _rects_cover_page(rects: list[fitz.Rect], page_rect: fitz.Rect) -> bool:
    if not rects:
        return False

    bounds = _rects_bounds(rects)
    if not _is_near_full_page_rect(bounds, page_rect):
        return False

    occupied_cells: set[tuple[int, int]] = set()
    grid_size = 24
    cell_width = page_rect.width / grid_size
    cell_height = page_rect.height / grid_size
    if cell_width <= 0 or cell_height <= 0:
        return False

    for rect in rects:
        start_column = _first_covered_cell(rect.x0, page_rect.x0, cell_width)
        end_column = _last_covered_cell(rect.x1, page_rect.x0, cell_width)
        start_row = _first_covered_cell(rect.y0, page_rect.y0, cell_height)
        end_row = _last_covered_cell(rect.y1, page_rect.y0, cell_height)

        start_column = max(start_column, 0)
        start_row = max(start_row, 0)
        end_column = min(end_column, grid_size - 1)
        end_row = min(end_row, grid_size - 1)
        if start_column > end_column or start_row > end_row:
            continue

        for row in range(start_row, end_row + 1):
            for column in range(start_column, end_column + 1):
                occupied_cells.add((row, column))

    return len(occupied_cells) / (grid_size * grid_size) >= FULL_PAGE_IMAGE_AREA_RATIO


def _first_covered_cell(value: float, origin: float, cell_size: float) -> int:
    return math.ceil((value - origin) / cell_size - 0.5)


def _last_covered_cell(value: float, origin: float, cell_size: float) -> int:
    return math.floor((value - origin) / cell_size - 0.5)


def _rects_bounds(rects: list[fitz.Rect]) -> fitz.Rect:
    x0 = min(rect.x0 for rect in rects)
    y0 = min(rect.y0 for rect in rects)
    x1 = max(rect.x1 for rect in rects)
    y1 = max(rect.y1 for rect in rects)
    return fitz.Rect(x0, y0, x1, y1)


def _is_near_full_page_rect(
    rect: fitz.Rect,
    page_rect: fitz.Rect,
    dimension_ratio: float = FULL_PAGE_IMAGE_DIMENSION_RATIO,
) -> bool:
    width_ratio = rect.width / page_rect.width if page_rect.width > 0 else 0.0
    height_ratio = rect.height / page_rect.height if page_rect.height > 0 else 0.0
    if width_ratio < dimension_ratio or height_ratio < dimension_ratio:
        return False

    x_margin = page_rect.width * EDGE_MARGIN_RATIO
    y_margin = page_rect.height * EDGE_MARGIN_RATIO
    return (
        rect.x0 <= page_rect.x0 + x_margin
        and rect.y0 <= page_rect.y0 + y_margin
        and rect.x1 >= page_rect.x1 - x_margin
        and rect.y1 >= page_rect.y1 - y_margin
    )

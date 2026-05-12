from enum import Enum


class StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class DocumentType(StringEnum):
    STANDARD = "STANDARD"
    SCANNED = "SCANNED"
    MIXED_SCANNED = "MIXED_SCANNED"
    EMPTY = "EMPTY"
    UNKNOWN = "UNKNOWN"


class PageType(StringEnum):
    TEXT_PAGE = "TEXT_PAGE"
    SCANNED_PAGE = "SCANNED_PAGE"
    UNKNOWN_PAGE = "UNKNOWN_PAGE"


class SourceType(StringEnum):
    FILE = "FILE"
    URL = "URL"
    UNKNOWN = "UNKNOWN"


class ErrorCode(StringEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    PDF_NOT_FOUND = "PDF_NOT_FOUND"
    PDF_NOT_FILE = "PDF_NOT_FILE"
    PDF_DOWNLOAD_ERROR = "PDF_DOWNLOAD_ERROR"
    PDF_URL_NOT_PDF = "PDF_URL_NOT_PDF"
    PDF_PARSE_ERROR = "PDF_PARSE_ERROR"
    PDF_EMPTY = "PDF_EMPTY"


# 中文说明：
# DocumentType 文档类型：
# - STANDARD：标准 PDF，可提取文本，非扫描件
# - SCANNED：ocr-detection 公开 API 返回 status=true，全部页需要 OCR
# - MIXED_SCANNED：ocr-detection 公开 API 返回 status=partial，部分页需要 OCR
# - EMPTY：保留兼容；严格公开 API 模式不会返回该类型，空白 PDF 会跟随库返回 SCANNED
# - UNKNOWN：未知类型，通常用于解析失败或输入错误
#
# PageType 页面类型：
# - TEXT_PAGE：文本页，可提取文本占主导
# - SCANNED_PAGE：扫描页，图片覆盖页面主体
# - UNKNOWN_PAGE：未知页面，文本和图片特征都不明显
#
# SourceType 输入来源：
# - FILE：本地 PDF 文件
# - URL：PDF 直链 URL
# - UNKNOWN：未知来源，通常用于参数错误
#
# ErrorCode 错误码：
# - INVALID_ARGUMENT：参数错误，例如没有传入 PDF 或 URL
# - PARTIAL_FAILURE：批量输入中至少有一个 PDF 处理失败
# - PDF_NOT_FOUND：本地 PDF 文件不存在
# - PDF_NOT_FILE：传入路径不是文件
# - PDF_DOWNLOAD_ERROR：PDF URL 下载失败
# - PDF_URL_NOT_PDF：URL 不是有效 PDF 直链或内容不是 PDF
# - PDF_PARSE_ERROR：PDF 文件损坏或无法解析
# - PDF_EMPTY：PDF 没有页面

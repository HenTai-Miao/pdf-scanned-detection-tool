import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitz

from scanspy.signature_cli import main


def write_text_pdf(path: Path, pages: int = 1) -> None:
    doc = fitz.open()
    for page_index in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 96), f"Signature test page {page_index + 1}", fontsize=12)
    doc.save(path)
    doc.close()


def write_signed_pdf(path: Path, signer_name: str = "Test Signer") -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers

    work_dir = path.parent
    base_pdf = work_dir / "base.pdf"
    signed_once = work_dir / "signed-once.pdf"
    key_path = work_dir / "key.pem"
    cert_path = work_dir / "cert.pem"
    write_text_pdf(base_pdf, pages=2)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, signer_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ScanSpy Test"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    signer = signers.SimpleSigner.load(str(key_path), str(cert_path))

    with base_pdf.open("rb") as inf, signed_once.open("wb") as outf:
        writer = IncrementalPdfFileWriter(inf)
        meta = signers.PdfSignatureMetadata(field_name="Sig1")
        spec = fields.SigFieldSpec(
            sig_field_name="Sig1",
            on_page=0,
            box=(50, 50, 250, 120),
        )
        signers.PdfSigner(meta, signer=signer, new_field_spec=spec).sign_pdf(
            writer,
            output=outf,
        )

    with signed_once.open("rb") as inf, path.open("wb") as outf:
        writer = IncrementalPdfFileWriter(inf)
        meta = signers.PdfSignatureMetadata(field_name="Sig2")
        spec = fields.SigFieldSpec(
            sig_field_name="Sig2",
            on_page=1,
            box=(50, 50, 250, 120),
        )
        signers.PdfSigner(meta, signer=signer, new_field_spec=spec).sign_pdf(
            writer,
            output=outf,
        )


def write_malformed_signed_pdf(path: Path) -> None:
    write_signed_pdf(path)
    content = path.read_bytes()

    def corrupt_first_signature(match: re.Match[bytes]) -> bytes:
        return match.group(1) + (b"0" * len(match.group(2))) + match.group(3)

    corrupted, replacements = re.subn(
        rb"(/Contents\s*<)([0-9A-Fa-f]+)(>\s*/ByteRange\s*\[[^\]]+\])",
        corrupt_first_signature,
        content,
        count=1,
        flags=re.S,
    )
    assert replacements == 1
    path.write_bytes(corrupted)


def run_cli(*args: str) -> tuple[int, dict]:
    stdout = io.StringIO()
    exit_code = main(list(args), stdout=stdout)
    return exit_code, json.loads(stdout.getvalue())


def test_unsigned_pdf_returns_empty_signature_summary(tmp_path: Path) -> None:
    pdf = tmp_path / "unsigned.pdf"
    write_text_pdf(pdf)

    exit_code, payload = run_cli(str(pdf))

    assert exit_code == 0
    assert payload["code"] == 200
    assert payload["success"] is True
    result = payload["data"][0]
    assert result == {
        "code": 200,
        "success": True,
        "source": str(pdf),
        "fileName": "unsigned.pdf",
        "fileSize": pdf.stat().st_size,
        "suffix": "PDF",
        "hasSignature": False,
        "signatureCount": 0,
        "allSignaturesValid": False,
        "allSignaturesIntact": False,
        "signatures": [],
        "sourceType": "FILE",
    }


def test_multiple_visible_signatures_return_details_and_page_numbers(tmp_path: Path) -> None:
    pdf = tmp_path / "signed.pdf"
    write_signed_pdf(pdf)

    exit_code, payload = run_cli(str(pdf))

    assert exit_code == 0
    result = payload["data"][0]
    assert result["hasSignature"] is True
    assert result["signatureCount"] == 2
    assert result["allSignaturesValid"] is True
    assert result["allSignaturesIntact"] is True
    signatures = result["signatures"]
    assert [item["index"] for item in signatures] == [1, 2]
    assert [item["fieldName"] for item in signatures] == ["Sig1", "Sig2"]
    assert [item["pageNumber"] for item in signatures] == [1, 2]
    assert [item["visible"] for item in signatures] == [True, True]
    assert all(item["signatureValid"] is True for item in signatures)
    assert all(item["signatureIntact"] is True for item in signatures)
    assert all("Test Signer" in item["signerName"] for item in signatures)
    assert all(item["signTime"] for item in signatures)


def test_malformed_signature_contents_fall_back_to_structural_signature_details(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "malformed-signed.pdf"
    write_malformed_signed_pdf(pdf)

    exit_code, payload = run_cli(str(pdf))

    assert exit_code == 0
    result = payload["data"][0]
    assert result["hasSignature"] is True
    assert result["signatureCount"] == 2
    assert result["allSignaturesValid"] is False
    assert result["allSignaturesIntact"] is False
    signatures = result["signatures"]
    assert [item["index"] for item in signatures] == [1, 2]
    assert [item["fieldName"] for item in signatures] == ["Sig1", "Sig2"]
    assert [item["pageNumber"] for item in signatures] == [1, 2]
    assert [item["visible"] for item in signatures] == [True, True]
    assert all(item["signatureValid"] is False for item in signatures)
    assert all(item["signatureIntact"] is False for item in signatures)
    assert all(item["signerName"] == "" for item in signatures)
    assert all(item["signTime"] for item in signatures)


def test_signature_success_and_failure_items_have_same_schema(tmp_path: Path) -> None:
    unsigned = tmp_path / "unsigned.pdf"
    missing = tmp_path / "missing.pdf"
    write_text_pdf(unsigned)

    exit_code, payload = run_cli(str(unsigned), str(missing))

    assert exit_code == 1
    assert payload["msg"] == "部分PDF签章检测失败"
    assert payload["errorCode"] == "PARTIAL_FAILURE"
    success_item, failure_item = payload["data"]
    expected_keys = [
        "code",
        "success",
        "source",
        "fileName",
        "fileSize",
        "suffix",
        "hasSignature",
        "signatureCount",
        "allSignaturesValid",
        "allSignaturesIntact",
        "signatures",
        "sourceType",
    ]
    assert list(success_item.keys()) == expected_keys
    assert list(failure_item.keys()) == expected_keys
    assert failure_item["hasSignature"] is False
    assert failure_item["signatures"] == []

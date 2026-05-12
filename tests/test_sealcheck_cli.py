import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitz

from scanspy.sealcheck_cli import main


def write_text_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 96), "Unsigned PDF", fontsize=12)
    doc.save(path)
    doc.close()


def write_signed_pdf(path: Path) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers

    base_pdf = path.parent / "base.pdf"
    key_path = path.parent / "key.pem"
    cert_path = path.parent / "cert.pem"
    write_text_pdf(base_pdf)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Seal Test Signer"),
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

    with base_pdf.open("rb") as inf, path.open("wb") as outf:
        writer = IncrementalPdfFileWriter(inf)
        meta = signers.PdfSignatureMetadata(field_name="SealSig")
        spec = fields.SigFieldSpec(
            sig_field_name="SealSig",
            on_page=0,
            box=(50, 50, 250, 120),
        )
        signers.PdfSigner(meta, signer=signer, new_field_spec=spec).sign_pdf(
            writer,
            output=outf,
        )


def run_cli(*args: str) -> tuple[int, dict]:
    stdout = io.StringIO()
    exit_code = main(list(args), stdout=stdout)
    return exit_code, json.loads(stdout.getvalue())


def test_unsigned_pdf_returns_has_signature_false(tmp_path: Path) -> None:
    pdf = tmp_path / "unsigned.pdf"
    write_text_pdf(pdf)

    exit_code, payload = run_cli(str(pdf))

    assert exit_code == 0
    assert payload["success"] is True
    assert payload["errorCode"] == ""
    assert payload["data"] == [{
        "code": 200,
        "success": True,
        "source": str(pdf),
        "fileName": "unsigned.pdf",
        "fileSize": pdf.stat().st_size,
        "suffix": "PDF",
        "hasSignature": False,
        "sourceType": "FILE",
    }]


def test_signed_pdf_returns_has_signature_true(tmp_path: Path) -> None:
    pdf = tmp_path / "signed.pdf"
    write_signed_pdf(pdf)

    exit_code, payload = run_cli(str(pdf))

    assert exit_code == 0
    result = payload["data"][0]
    assert result["hasSignature"] is True
    assert result["sourceType"] == "FILE"


def test_sealcheck_success_and_failure_items_have_same_schema(tmp_path: Path) -> None:
    unsigned = tmp_path / "unsigned.pdf"
    missing = tmp_path / "missing.pdf"
    write_text_pdf(unsigned)

    exit_code, payload = run_cli(str(unsigned), str(missing))

    assert exit_code == 1
    assert payload["msg"] == "部分PDF签章检测失败"
    assert payload["errorCode"] == "PARTIAL_FAILURE"
    expected_keys = [
        "code",
        "success",
        "source",
        "fileName",
        "fileSize",
        "suffix",
        "hasSignature",
        "sourceType",
    ]
    assert list(payload["data"][0].keys()) == expected_keys
    assert list(payload["data"][1].keys()) == expected_keys
    assert payload["data"][1]["hasSignature"] is False


def test_sealcheck_cli_does_not_import_other_cli_detection_modules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "src" / "scanspy" / "sealcheck_cli.py").read_text(
        encoding="utf-8"
    )

    assert "from scanspy.cli import" not in source
    assert "ocr_detection" not in source
    assert "pyhanko" not in source

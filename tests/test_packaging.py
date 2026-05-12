import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_is_declared_as_dev_dependency() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    dev_dependencies = pyproject["dependency-groups"]["dev"]

    assert any(dependency.startswith("pyinstaller") for dependency in dev_dependencies)


def test_windows_packaging_entrypoint_delegates_to_cli_main() -> None:
    entrypoint = REPO_ROOT / "packaging" / "scanspy_main.py"

    source = entrypoint.read_text(encoding="utf-8")

    assert "from scanspy.cli import main" in source
    assert "raise SystemExit(main())" in source


def test_windows_build_script_creates_onefile_release_bundle() -> None:
    build_script = REPO_ROOT / "scripts" / "build-windows.ps1"

    source = build_script.read_text(encoding="utf-8")

    assert "--onefile" in source
    assert "--console" in source
    assert "--name" in source
    assert "scanspy" in source
    assert "--noupx" in source
    assert "--collect-all" in source
    assert "ocr_detection" in source
    assert "pdfplumber" in source
    assert "fitz" in source
    assert "release\\scanspy-windows-x64" in source
    assert "ReadmeFileName" in source
    assert "0x7528" in source
    assert "0x6237" in source
    assert "0x4F7F" in source
    assert "Compress-Archive" in source

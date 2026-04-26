from __future__ import annotations

from pathlib import Path

from app.services import document_service


def test_list_local_files_returns_safe_metadata(tmp_path, monkeypatch) -> None:
    root = tmp_path / "sample_filings"
    nested = root / "AAPL" / "2025"
    nested.mkdir(parents=True)
    readme = root / "README.md"
    readme.write_text("docs", encoding="utf-8")
    filing = nested / "aapl-10k.htm"
    filing.write_text("<html />", encoding="utf-8")

    monkeypatch.setattr(document_service, "LOCAL_FILINGS_ROOT", root)

    entries = document_service.list_local_files()

    assert [entry.relative_path for entry in entries] == [
        "AAPL",
        "AAPL/2025",
        "AAPL/2025/aapl-10k.htm",
        "README.md",
    ]
    file_entry = next(entry for entry in entries if entry.relative_path.endswith("aapl-10k.htm"))
    assert file_entry.kind == "file"
    assert file_entry.extension == ".htm"
    assert file_entry.size_bytes == len("<html />")
    assert Path(file_entry.local_path).is_absolute()


def test_list_local_files_empty_when_root_missing(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setattr(document_service, "LOCAL_FILINGS_ROOT", missing)

    assert document_service.list_local_files() == []

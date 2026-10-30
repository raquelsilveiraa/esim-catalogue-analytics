"""Ingestion reconciliation and source-preservation regressions."""
import csv
import hashlib
from pathlib import Path

import pytest

from src.config import RAW_DIRECTORY, REQUIRED_COLUMNS, UNLIMITED_LABEL
from src.loader import discover_supplier_files, load_supplier_files
from src.pipeline import run_pipeline


def write_catalogue(path: Path, rows: list[list[str]], columns=REQUIRED_COLUMNS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)


def source_row(sku: str = "test-1") -> list[str]:
    return [sku, "Test Supplier", "Original name", "NA", "Am\u00e9rique du Nord",
            "5", "5 Go", "7", "12.50", "EUR", "5G", "oui"]


def test_discovery_order_rows_traceability_and_na(tmp_path):
    write_catalogue(tmp_path / "z.csv", [source_row("z-1"), source_row("z-2")])
    write_catalogue(tmp_path / "nested" / "a.csv", [source_row("a-1")])
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")
    result = load_supplier_files(tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in discover_supplier_files(tmp_path)] == ["nested/a.csv", "z.csv"]
    assert result.files_discovered == result.files_successfully_loaded == 2
    assert result.files_failed == 0
    assert result.raw_rows_read == result.rows_returned == 3
    assert result.data.source_file.tolist() == ["nested/a.csv", "z.csv", "z.csv"]
    assert result.data.source_record_number.tolist() == [1, 1, 2]
    assert result.data.country_code.tolist() == ["NA"] * 3
    assert result.data.price.tolist() == ["12.50"] * 3
    assert all(report.sha256 == hashlib.sha256((tmp_path / report.source_file).read_bytes()).hexdigest()
               for report in result.files)


@pytest.mark.parametrize("contents,rule", [
    (b"", "empty_file"),
    ((",".join(REQUIRED_COLUMNS) + "\n").encode(), "empty_file"),
    ((",".join(REQUIRED_COLUMNS) + '\n"unterminated').encode(), "malformed_csv"),
    ((",".join(REQUIRED_COLUMNS) + "\na,b\n").encode(), "malformed_csv"),
    (b"\xff", "invalid_encoding"),
    (b"sku,sku\na,b\n", "invalid_header"),
])
def test_rejected_files_are_reported_and_other_files_are_attempted(tmp_path, contents, rule):
    (tmp_path / "a_bad.csv").write_bytes(contents)
    write_catalogue(tmp_path / "z_good.csv", [source_row()])
    result = load_supplier_files(tmp_path)
    assert result.files_discovered == 2
    assert result.files_successfully_loaded == result.files_failed == 1
    assert result.rows_returned == 1
    assert rule in {finding.rule for finding in result.files[0].findings}
    assert result.files[0].sha256 == hashlib.sha256(contents).hexdigest()


def test_unreadable_file_does_not_hide_other_files(tmp_path, monkeypatch):
    write_catalogue(tmp_path / "a.csv", [source_row()])
    write_catalogue(tmp_path / "b.csv", [source_row()])
    original_read = Path.read_bytes

    def controlled_read(path):
        if path.name == "a.csv":
            raise PermissionError("Synthetic denied read")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", controlled_read)
    result = load_supplier_files(tmp_path)
    assert result.files_failed == result.files_successfully_loaded == 1
    assert result.files[0].sha256 is None
    assert result.files[0].findings[0].rule == "unreadable_file"


def test_schema_evolution_and_missing_columns(tmp_path):
    write_catalogue(tmp_path / "extra.csv", [source_row() + ["preserved"]], (*REQUIRED_COLUMNS, "new_attribute"))
    write_catalogue(tmp_path / "missing.csv", [source_row()[:-1]], REQUIRED_COLUMNS[:-1])
    result = load_supplier_files(tmp_path)
    assert result.files_failed == result.files_successfully_loaded == 1
    assert result.raw_rows_read == 2
    assert result.rows_returned == 1
    assert result.data.new_attribute.tolist() == ["preserved"]
    assert result.files[0].findings[0].rule == "additional_column"
    assert result.files[1].findings[0].rule == "missing_required_column"
    validation = run_pipeline(tmp_path).validation
    assert {finding.rule for finding in validation.findings} >= {"additional_column", "missing_required_column"}


def test_reserved_metadata_column_cannot_overwrite_business_data(tmp_path):
    write_catalogue(tmp_path / "collision.csv", [source_row() + ["original"]], (*REQUIRED_COLUMNS, "source_file"))
    result = load_supplier_files(tmp_path)
    assert result.files_failed == 1
    assert "reserved_column_collision" in {finding.rule for finding in result.files[0].findings}


def test_multiline_fields_preserve_logical_record_numbers(tmp_path):
    row = source_row()
    row[2] = "Original\nmultiline name"
    write_catalogue(tmp_path / "a.csv", [row, source_row("test-2")])
    result = load_supplier_files(tmp_path)
    assert result.data.product_name.iloc[0] == row[2]
    assert result.data.source_record_number.tolist() == [1, 2]


def test_missing_and_empty_directory_are_explicit(tmp_path):
    with pytest.raises(NotADirectoryError):
        load_supplier_files(tmp_path / "absent")
    result = run_pipeline(tmp_path)
    assert result.ingestion.files_discovered == 0
    assert result.validation.findings[0].rule == "empty_catalogue"


# Immutable hashes captured in the approved read-only profiling, before the move.
BASELINE_HASHES = {
    "4sesim.csv": "3c1e26f48782c0be68a8f4489bff1032a0ed154a79a2cda2d80f4a19d2fe5890",
    "airalo.csv": "f4f8f96492e91acedcf03d7e34b7c798acb14e67638de0f885236711d3479dac",
    "alosim.csv": "7453924cac5c94aed6a5de6dcd9291b0c4a19290fe47afe789b7a61468f316c6",
    "esimx.csv": "0d897a0a18dcf9d6cf3bcc8414b614852e1acd4f3af8935b2fec2bfb06fcdf2d",
    "flexiroam.csv": "6fd2be08b785f0b736ef97ab5b8a9a8f1cabf9abad8886897ae5dc735b639832",
    "gigsky.csv": "53ae1383353e5139d6e84ba58bf76a028a5bf01031deae54067c1135b8add0d1",
    "holafly.csv": "4abbddaf0174d414cc7ceee5ae85ec077f2a89d8a5233cd059419f76244a0c70",
    "instabridge.csv": "d45fc2762bd813821802064c22d8739fd58e2f2481d289ab50e8382c97987e56",
    "jambosim.csv": "f140eb4294e70d9bd7f7eb66e50f66b0bf190b1c0b7433497e61e8fb038123c2",
    "jetpac.csv": "891c64c473e19a34ec14670b0decf3dad9b7afa4c24385c7fffca95447b1cd8c",
    "maya.csv": "85c0cb74249c42e4fbc0fdbc4b8dc9117be231bab3ca4334984409b6a0d675f3",
    "nomad.csv": "54d825afe4debc1354a136dab59d2dcb782ec41b5fb00bde45f266d37236cbfb",
    "roamic.csv": "5731681685b6a0eaf4fe8608814031d8f51ebcfc8f5a5d5b1cb423e5be8f14ff",
    "saily.csv": "6b73ebc76b9d842eec50f049e79fcd76eea5562afd7e3d1367b0c0b06b119765",
    "truphone.csv": "fb0cd4a33df7f390f81ad0714f0fb06e0e8d7b374d35b3104ee064904283e160",
    "ubigi.csv": "f4cc2711fec79ebc401d429a914e43437024941b3452fbe098fb7671576b9bf5",
    "yatelo.csv": "a2575af26f6a7ab3d01ab7bf018653864629409fd45669baf96a1c4fe7290844",
    "yesim.csv": "adb198f5fe316833cfcdb89849dd3a8b606f28a7e8f495e90a46a465d83e9e08",
}


def test_complete_real_catalogue_matches_approved_baseline():
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in RAW_DIRECTORY.glob("*.csv")}
    assert before == BASELINE_HASHES
    result = run_pipeline()
    ingestion, validation = result.ingestion, result.validation
    assert ingestion.files_discovered == ingestion.files_successfully_loaded == 18
    assert ingestion.files_failed == 0
    assert ingestion.raw_rows_read == ingestion.rows_returned == 5056
    data = ingestion.data
    assert data.country_code.eq("NA").sum() == 192
    assert data.data_gb.eq("").sum() == 653
    assert data.data_display.eq(UNLIMITED_LABEL).sum() == 653
    assert (data.data_gb.eq("") == data.data_display.eq(UNLIMITED_LABEL)).all()
    assert not data.duplicated(["provider", "sku"]).any()
    assert not data.duplicated("sku").any()
    assert data.currency.eq("EUR").all()
    assert len(validation.business_critical_errors) == 5056
    assert not validation.business_critical_errors.any()
    assert not validation.findings
    assert not data[list(REQUIRED_COLUMNS)].isna().any().any()
    for report in ingestion.files:
        rows = data[data.source_file.eq(report.source_file)]
        with (RAW_DIRECTORY / report.source_file).open(encoding="utf-8", newline="") as stream:
            original = list(csv.reader(stream))
        assert rows[list(REQUIRED_COLUMNS)].values.tolist() == original[1:]
        assert rows.source_record_number.tolist() == list(range(1, len(rows) + 1))
        assert report.sha256 == BASELINE_HASHES[report.source_file]
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in RAW_DIRECTORY.glob("*.csv")}
    assert after == before

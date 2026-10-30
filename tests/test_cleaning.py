"""Cleaning and quality reconciliation preserve every source record."""
import csv
from decimal import Decimal

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.cleaning import clean_catalogue
from src.config import REQUIRED_COLUMNS, UNLIMITED_LABEL
from src.pipeline import run_pipeline
from src.validation import validate_catalogue


def source_plan(**changes):
    row = dict(zip(REQUIRED_COLUMNS, ["one", "Supplier A", "Original name", "NA",
               "Am\u00e9rique du Nord", "5", "5 Go", "7", "12.50", "EUR", "5G", "oui"]))
    row.update(source_file="source.csv", source_record_number=1)
    row.update(changes)
    return row


def test_cleaning_preserves_source_and_approved_missing_semantics():
    data = pd.DataFrame([source_plan(), source_plan(sku="two", source_record_number=2,
                          data_gb="", data_display=UNLIMITED_LABEL)])
    original = data.copy(deep=True)
    cleaned = clean_catalogue(data, validate_catalogue(data))
    assert len(cleaned) == len(data) == 2
    assert cleaned.price.tolist() == [Decimal("12.50")] * 2
    assert cleaned.data_gb.iloc[0] == Decimal(5)
    assert pd.isna(cleaned.data_gb.iloc[1])
    assert cleaned.source_data_gb.tolist() == ["5", ""]
    assert cleaned.source_price.tolist() == ["12.50"] * 2
    assert cleaned.country_code.tolist() == ["NA"] * 2
    assert cleaned.data_display.iloc[1] == UNLIMITED_LABEL
    assert cleaned.is_analytically_eligible.all()
    assert_frame_equal(data, original)


def test_invalid_future_row_stays_traceable_with_exclusion_reasons():
    data = pd.DataFrame([source_plan(price="bad", top_up="unknown")])
    cleaned = clean_catalogue(data, validate_catalogue(data))
    assert len(cleaned) == 1
    assert cleaned.source_file.iloc[0] == "source.csv"
    assert cleaned.source_record_number.iloc[0] == 1
    assert cleaned.source_price.iloc[0] == "bad"
    assert pd.isna(cleaned.price.iloc[0])
    assert not cleaned.is_analytically_eligible.iloc[0]
    assert set(cleaned.exclusion_reasons.iloc[0]) == {"numeric_parseability", "unknown_top_up"}


@pytest.mark.parametrize("price", ["12.50", "15.00"])
def test_duplicate_identities_remain_unresolved_without_row_loss(price):
    data = pd.DataFrame([source_plan(), source_plan(price=price, source_record_number=2)])
    cleaned = clean_catalogue(data, validate_catalogue(data))
    assert len(cleaned) == 2
    assert not cleaned.is_analytically_eligible.any()
    assert all("unresolved_duplicate_business_key" in rules for rules in cleaned.exclusion_reasons)


def test_quality_summary_uses_actual_failures_and_rows(tmp_path):
    rows = [source_plan(), source_plan(sku="two", source_record_number=2, price="bad")]
    with (tmp_path / "source.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(REQUIRED_COLUMNS)
        writer.writerows([[row[c] for c in REQUIRED_COLUMNS] for row in rows])
    (tmp_path / "bad.csv").write_bytes(b'header\n"unterminated')
    result = run_pipeline(tmp_path)
    quality = result.data_quality
    assert quality["files_discovered"] == quality["files_loaded"] + quality["files_failed"] == 2
    assert quality["files_failed"] == 1
    assert quality["raw_rows"] == quality["ingested_rows"] == quality["validated_rows"] == 2
    assert quality["analytically_eligible_rows"] == quality["analytically_ineligible_rows"] == 1
    assert quality["validation_findings"] == len(result.validation.findings) == 2
    assert quality["critical_errors"] == 2
    assert quality["rows_with_critical_errors"] == 1
    assert quality["raw_row_count_complete"] is False
    assert result.metrics["total_products"] == 1


def test_cleaning_rejects_misaligned_validation_and_metadata_collisions():
    data = pd.DataFrame([source_plan()])
    validation = validate_catalogue(data)
    with pytest.raises(ValueError, match="align"):
        clean_catalogue(data.set_axis([99]), validation)
    data["source_price"] = "supplier value"
    with pytest.raises(ValueError, match="conflict"):
        clean_catalogue(data, validation)

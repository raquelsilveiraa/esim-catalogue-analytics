"""Orchestrate traceable catalogue stages and summarize actual data quality."""
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

from .cleaning import clean_catalogue
from .config import RAW_DIRECTORY
from .loader import IngestionResult, load_supplier_files
from .metrics import aggregate_catalogue, calculate_metrics
from .transformation import transform_catalogue
from .validation import ValidationResult, validate_catalogue


@dataclass(frozen=True)
class PipelineResult:
    ingestion: IngestionResult
    validation: ValidationResult
    analytical_catalogue: pd.DataFrame
    metrics: dict[str, int | float | Decimal | None]
    aggregations: dict[str, pd.DataFrame]
    data_quality: dict


def summarize_data_quality(ingestion: IngestionResult, validation: ValidationResult,
                           catalogue: pd.DataFrame) -> dict:
    """Count findings separately from rows; rejected row totals may be partial.

    raw_rows counts parsed records, including rejected-file prefixes. When files
    cannot be fully parsed, unknown raw totals are explicitly flagged.
    """
    eligible = int(catalogue.is_analytically_eligible.sum())
    keys = ingestion.data[["provider", "sku"]]
    duplicate = keys.duplicated(keep=False)
    return {
        "files_discovered": ingestion.files_discovered,
        "files_loaded": ingestion.files_successfully_loaded,
        "files_failed": ingestion.files_failed,
        "raw_rows": ingestion.raw_rows_read,
        "raw_row_count_complete": not any(
            any(f.rule in {"unreadable_file", "invalid_encoding", "malformed_csv", "invalid_header"}
                for f in report.findings) for report in ingestion.files),
        "ingested_rows": ingestion.rows_returned,
        "validated_rows": len(validation.business_critical_errors),
        "analytically_eligible_rows": eligible,
        "analytically_ineligible_rows": len(catalogue) - eligible,
        "parsed_rows_in_rejected_files": sum(r.rows_read for r in ingestion.files if not r.loaded),
        "validation_findings": len(validation.findings),
        "critical_errors": sum(f.severity in {"ERROR", "BLOCKER"} for f in validation.findings),
        "rows_with_critical_errors": int(validation.business_critical_errors.sum()),
        "findings_by_severity": dict(Counter(f.severity for f in validation.findings)),
        "duplicate_business_keys": len(keys.loc[duplicate].drop_duplicates()),
        "duplicate_business_key_rows": int(duplicate.sum()),
        "unlimited_plans": int(catalogue.is_unlimited.eq(True).sum()),
    }


def run_pipeline(raw_directory: Path = RAW_DIRECTORY) -> PipelineResult:
    ingestion = load_supplier_files(raw_directory)
    validation = validate_catalogue(ingestion.data, ingestion.files)
    cleaned = clean_catalogue(ingestion.data, validation)
    catalogue = transform_catalogue(cleaned)
    return PipelineResult(ingestion, validation, catalogue,
                          calculate_metrics(catalogue), aggregate_catalogue(catalogue),
                          summarize_data_quality(ingestion, validation, catalogue))


if __name__ == "__main__":
    result = run_pipeline()
    print(json.dumps({"data_quality": result.data_quality, "metrics": result.metrics}, indent=2, default=str))

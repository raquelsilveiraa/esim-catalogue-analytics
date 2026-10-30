"""Conservative typed copy with explicit row eligibility; no row removal."""
import pandas as pd

from .config import REQUIRED_COLUMNS, TRACEABILITY_COLUMNS
from .validation import ValidationResult, _number


def clean_catalogue(data: pd.DataFrame, validation: ValidationResult) -> pd.DataFrame:
    """Preserve source numeric tokens and attach exclusion rules to every row.

    Duplicate identities remain unresolved: all occurrences are excluded until
    a duplicate-resolution policy is approved, including identical duplicates.
    """
    if not set((*REQUIRED_COLUMNS, *TRACEABILITY_COLUMNS)).issubset(data.columns):
        raise ValueError("Cleaning requires the complete ingestion schema.")
    if not validation.business_critical_errors.index.equals(data.index):
        raise ValueError("Validation flags must align with source rows.")
    identity = list(TRACEABILITY_COLUMNS)
    if data.duplicated(identity).any():
        raise ValueError("Source file and record number must identify rows uniquely.")
    added = {"source_price", "source_data_gb", "source_validity_days",
             "has_business_critical_error", "is_analytically_eligible", "exclusion_reasons"}
    if added.intersection(data.columns):
        raise ValueError("Source columns conflict with analytical metadata.")
    result = data.copy(deep=True)
    reasons: dict[tuple, list[str]] = {}
    global_rules = []
    for finding in validation.findings:
        if finding.severity not in {"ERROR", "BLOCKER"}:
            continue
        if finding.source_record_number is not None:
            key = (finding.source_file, finding.source_record_number)
            reasons.setdefault(key, []).append(finding.rule)
        elif finding.source_file is None:
            global_rules.append(finding.rule)
    duplicate = data.duplicated(["provider", "sku"], keep=False).tolist()
    exclusions = []
    for position, row in enumerate(data.to_dict("records")):
        rules = list(global_rules) + reasons.get(tuple(row[c] for c in identity), [])
        if validation.business_critical_errors.iloc[position] and not rules:
            rules.append("business_critical_validation_error")
        if duplicate[position]:
            rules.append("unresolved_duplicate_business_key")
        exclusions.append(tuple(sorted(set(rules))))
    for column in ("price", "data_gb", "validity_days"):
        result[f"source_{column}"] = data[column].copy()
        # Reuse validation parsing so conversion cannot silently accept new syntax.
        converted = []
        for value in data[column]:
            number = _number(value)
            converted.append(number if number is not None and number.is_finite() else None)
        result[column] = pd.Series(converted, index=data.index, dtype=object)
    result["has_business_critical_error"] = validation.business_critical_errors.to_numpy(copy=True)
    result["exclusion_reasons"] = exclusions
    result["is_analytically_eligible"] = [not rules for rules in exclusions]
    return result

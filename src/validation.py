"""Non-mutating contract validation, separate from analytical eligibility."""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence

import pandas as pd

from .config import (
    Finding, NETWORK_VALUES, REGIONAL_DESTINATIONS, REQUIRED_COLUMNS, Severity,
    TOP_UP_VALUES, TRACEABILITY_COLUMNS, UNLIMITED_LABEL,
)
from .loader import FileReport


@dataclass(frozen=True)
class ValidationResult:
    findings: tuple[Finding, ...]
    business_critical_errors: pd.Series


def _is_missing(value: object) -> bool:
    return bool(pd.isna(value)) or str(value).strip() == ""


def _number(value: object) -> Decimal | None:
    if _is_missing(value):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def validate_catalogue(data: pd.DataFrame,
                       file_reports: Sequence[FileReport] = ()) -> ValidationResult:
    """Return findings and positional error flags without changing source values.

    Flags indicate ERROR/BLOCKER findings, not complete KPI eligibility. In
    particular, non-EUR records remain present but cannot enter later EUR metrics.
    """
    findings = [finding for report in file_reports for finding in report.findings]
    critical = pd.Series(False, index=data.index, name="has_business_critical_error")
    if data.empty and not file_reports:
        findings.append(Finding("BLOCKER", "empty_catalogue", None, None, None,
                                None, None, "No catalogue records or file reports were supplied."))
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(data.columns))
    for column in missing_columns:
        findings.append(Finding("BLOCKER", "missing_required_column", column,
                                None, None, None, None, "Required business column is missing."))
    if missing_columns:
        critical.iloc[:] = True
        return ValidationResult(tuple(findings), critical)
    if not file_reports:
        for column in sorted(set(data.columns) - set(REQUIRED_COLUMNS) - set(TRACEABILITY_COLUMNS)):
            findings.append(Finding("WARNING", "additional_column", column, None, None,
                                    None, None, "Additional source column is preserved."))

    # Use positional indices internally so repeated caller index labels stay safe.
    records = data.to_dict("records")

    def add(position: int, severity: Severity, rule: str, column: str, message: str) -> None:
        row = records[position]
        record_number = row.get("source_record_number")
        findings.append(Finding(
            severity, rule, column,
            None if _is_missing(row.get("source_file")) else str(row["source_file"]),
            None if _is_missing(record_number) else int(record_number),
            None if _is_missing(row.get("sku")) else str(row["sku"]),
            None if _is_missing(row.get(column)) else str(row[column]), message,
        ))
        if severity in {"ERROR", "BLOCKER"}:
            critical.iloc[position] = True

    for position, row in enumerate(records):
        for column in ("sku", "provider", "product_name", "country_code", "country_name",
                       "data_display", "currency", "network", "top_up"):
            if _is_missing(row[column]):
                add(position, "ERROR", "required_value", column, "Required value is missing or blank.")
        for column in ("price", "validity_days"):
            value = _number(row[column])
            if value is None:
                add(position, "ERROR", "numeric_parseability", column, "A numeric value is required.")
            elif not value.is_finite():
                add(position, "ERROR", "finite_number", column, "Value must be finite.")
            else:
                if value <= 0:
                    add(position, "ERROR", "positive_number", column, "Value must be greater than zero.")
                if column == "validity_days" and value != value.to_integral_value():
                    add(position, "ERROR", "integer_validity", column, "Validity must be an integer number of days.")
                if column == "price" and value.as_tuple().exponent < -2 and any(value.as_tuple().digits[value.as_tuple().exponent + 2:]):
                    add(position, "ERROR", "price_precision", column, "EUR price must have no fractional cent.")
        allowance = _number(row["data_gb"])
        if row["data_display"] == UNLIMITED_LABEL:
            if not _is_missing(row["data_gb"]):
                add(position, "ERROR", "unlimited_allowance", "data_gb", "Unlimited plans must have empty/null data_gb.")
        else:
            if allowance is None:
                add(position, "ERROR", "finite_allowance", "data_gb", "Finite plans require numeric data_gb.")
            elif not allowance.is_finite() or allowance <= 0:
                add(position, "ERROR", "positive_finite_allowance", "data_gb", "Finite allowance must be finite and positive.")
            display = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?) Go", str(row["data_display"]))
            if display is None and not _is_missing(row["data_display"]):
                add(position, "WARNING", "unknown_data_display", "data_display", "Unrecognized allowance display requires review.")
            elif display and allowance is not None and allowance.is_finite():
                if allowance != Decimal(display.group(1)):
                    add(position, "ERROR", "allowance_display_conflict", "data_display", "Displayed allowance differs from data_gb.")
        for column, allowed, rule in (
            ("currency", {"EUR"}, "unsupported_currency"),
            ("network", NETWORK_VALUES, "unknown_network"),
            ("top_up", TOP_UP_VALUES, "unknown_top_up"),
        ):
            if not _is_missing(row[column]) and row[column] not in allowed:
                message = ("Non-EUR price is ineligible for EUR metrics; no conversion is applied."
                           if column == "currency" else "Unrecognized value requires explicit review.")
                severity = "ERROR" if column in {"currency", "top_up"} else "WARNING"
                add(position, severity, rule, column, message)
        code = row["country_code"]
        if code in REGIONAL_DESTINATIONS and row["country_name"] != REGIONAL_DESTINATIONS[code]:
            add(position, "ERROR", "regional_destination_conflict", "country_name", "Name conflicts with approved regional coverage code.")

    def groups(columns: tuple[str, ...]) -> list[list[int]]:
        grouped: dict[tuple[str, ...], list[int]] = {}
        for position, row in enumerate(records):
            if all(not _is_missing(row[column]) for column in columns):
                key = tuple(str(row[column]) for column in columns)
                grouped.setdefault(key, []).append(position)
        return list(grouped.values())

    for positions in groups(("provider", "sku")):
        if len(positions) < 2:
            continue
        def signature(position: int, columns: tuple[str, ...], semantic: bool = False) -> tuple:
            values = []
            for column in columns:
                value = records[position][column]
                numeric = _number(value) if column in {"price", "data_gb", "validity_days"} else None
                if semantic and numeric is not None and numeric.is_finite():
                    values.append(numeric)
                else:
                    values.append(None if _is_missing(value) else str(value))
            return tuple(values)

        signatures = {signature(p, REQUIRED_COLUMNS) for p in positions}
        semantic_signatures = {signature(p, REQUIRED_COLUMNS, True) for p in positions}
        price_values = {signature(p, ("price",), True) for p in positions}
        attributes = {signature(p, tuple(c for c in REQUIRED_COLUMNS if c != "price"), True)
                      for p in positions}
        severity: Severity
        if len(signatures) == 1:
            rule, severity = "identical_business_duplicate", "INFO"
        elif len(semantic_signatures) == 1:
            rule, severity = "semantically_identical_duplicate", "INFO"
        elif len(price_values) > 1 and len(attributes) == 1:
            rule, severity = "duplicate_price_conflict", "ERROR"
        elif len(price_values) > 1:
            rule, severity = "duplicate_price_and_attribute_conflict", "ERROR"
        else:
            rule, severity = "duplicate_attribute_conflict", "ERROR"
        cross_file = len({records[p].get("source_file") for p in positions}) > 1
        for position in positions:
            add(position, severity, rule, "sku",
                f"Repeated (provider, sku); cross-file={cross_file}. All occurrences are retained.")
    for positions in groups(("sku",)):
        if len({records[p]["provider"] for p in positions}) > 1:
            for position in positions:
                add(position, "WARNING", "global_sku_collision", "sku", "SKU occurs under multiple providers.")
    for positions in groups(("source_file",)) if "source_file" in data.columns else []:
        if len({records[p]["provider"] for p in positions if not _is_missing(records[p]["provider"])}) > 1:
            for position in positions:
                add(position, "WARNING", "multiple_file_providers", "provider", "File contains multiple providers; review source consistency.")
    for key, mapped in (("country_code", "country_name"), ("country_name", "country_code")):
        for positions in groups((key,)):
            values = {records[p][mapped] for p in positions if not _is_missing(records[p][mapped])}
            if len(values) > 1:
                for position in positions:
                    add(position, "ERROR", "destination_mapping_conflict", mapped,
                        f"One {key} maps to multiple {mapped} values.")
    return ValidationResult(tuple(findings), critical)

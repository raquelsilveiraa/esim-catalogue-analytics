"""Approved catalogue contract; source business values remain unchanged.

Later metrics must average GB over valid finite plans only. Unlimited plans
keep null GB, currencies are never converted, and top-up mappings are explicit.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RAW_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "raw"
REQUIRED_COLUMNS = (
    "sku", "provider", "product_name", "country_code", "country_name",
    "data_gb", "data_display", "validity_days", "price", "currency",
    "network", "top_up",
)
TRACEABILITY_COLUMNS = ("source_file", "source_record_number")
UNLIMITED_LABEL = "Illimit\u00e9"
TOP_UP_VALUES = {"oui": True, "non": False}
NETWORK_VALUES = frozenset({"4G", "5G"})
REGIONAL_DESTINATIONS = {
    "EU": "Europe", "AS": "Asie", "NA": "Am\u00e9rique du Nord", "WW": "Monde",
}
Severity = Literal["BLOCKER", "ERROR", "WARNING", "INFO"]


@dataclass(frozen=True)
class Finding:
    severity: Severity
    rule: str
    column: str | None
    source_file: str | None
    source_record_number: int | None
    sku: str | None
    observed_value: str | None
    message: str

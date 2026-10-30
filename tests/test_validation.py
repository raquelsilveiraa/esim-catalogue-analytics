"""Business-critical contract cases; validation must preserve all input rows."""
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.config import UNLIMITED_LABEL
from src.validation import validate_catalogue


@pytest.fixture
def finite_plan():
    return {
        "sku": "test-1", "provider": "Test Supplier", "product_name": "Original name",
        "country_code": "NA", "country_name": "Am\u00e9rique du Nord", "data_gb": "5",
        "data_display": "5 Go", "validity_days": "7", "price": "12.50",
        "currency": "EUR", "network": "5G", "top_up": "oui",
        "source_file": "test.csv", "source_record_number": 1,
    }


def test_valid_finite_and_unlimited_plans_preserve_input(finite_plan):
    unlimited = dict(finite_plan, sku="test-2", data_gb="", data_display=UNLIMITED_LABEL,
                     source_record_number=2)
    data = pd.DataFrame([finite_plan, unlimited])
    original = data.copy(deep=True)
    result = validate_catalogue(data)
    assert not result.findings
    assert not result.business_critical_errors.any()
    assert_frame_equal(data, original)


@pytest.mark.parametrize("changes,rule", [
    ({"data_display": UNLIMITED_LABEL}, "unlimited_allowance"),
    ({"data_gb": ""}, "finite_allowance"),
    ({"data_gb": "nonsense"}, "finite_allowance"),
    ({"data_gb": "-1"}, "positive_finite_allowance"),
    ({"data_gb": "Infinity"}, "positive_finite_allowance"),
    ({"data_display": "10 Go"}, "allowance_display_conflict"),
    ({"price": "invalid"}, "numeric_parseability"),
    ({"price": "-1"}, "positive_number"),
    ({"price": "0"}, "positive_number"),
    ({"price": "Infinity"}, "finite_number"),
    ({"price": "NaN"}, "finite_number"),
    ({"price": "12.501"}, "price_precision"),
    ({"validity_days": "invalid"}, "numeric_parseability"),
    ({"validity_days": "7.5"}, "integer_validity"),
    ({"validity_days": "0"}, "positive_number"),
    ({"validity_days": "-7"}, "positive_number"),
    ({"validity_days": "Infinity"}, "finite_number"),
    ({"sku": "  "}, "required_value"),
    ({"provider": None}, "required_value"),
    ({"product_name": ""}, "required_value"),
    ({"currency": "USD"}, "unsupported_currency"),
    ({"top_up": "unknown"}, "unknown_top_up"),
    ({"country_name": "Namibia"}, "regional_destination_conflict"),
])
def test_contract_errors_are_traceable_and_non_mutating(finite_plan, changes, rule):
    data = pd.DataFrame([dict(finite_plan, **changes)])
    original = data.copy(deep=True)
    result = validate_catalogue(data)
    finding = next(f for f in result.findings if f.rule == rule)
    assert finding.severity == "ERROR"
    assert finding.source_file == "test.csv"
    assert finding.source_record_number == 1
    assert finding.column
    assert result.business_critical_errors.tolist() == [True]
    assert_frame_equal(data, original)


@pytest.mark.parametrize("changes,rule", [
    ({"network": "6G"}, "unknown_network"),
    ({"data_display": "Daily offer"}, "unknown_data_display"),
])
def test_unknown_representations_are_reported(finite_plan, changes, rule):
    result = validate_catalogue(pd.DataFrame([dict(finite_plan, **changes)]))
    assert [(f.severity, f.rule) for f in result.findings] == [("WARNING", rule)]
    assert not result.business_critical_errors.any()


@pytest.mark.parametrize("changes,rule", [
    ({}, "identical_business_duplicate"),
    ({"price": "12.500", "data_gb": "5.0"}, "semantically_identical_duplicate"),
    ({"price": "15"}, "duplicate_price_conflict"),
    ({"network": "4G"}, "duplicate_attribute_conflict"),
    ({"price": "15", "network": "4G"}, "duplicate_price_and_attribute_conflict"),
])
def test_duplicate_classification_marks_all_occurrences(finite_plan, changes, rule):
    second = dict(finite_plan, **changes)
    second.update(source_file="second.csv", source_record_number=2)
    data = pd.DataFrame([finite_plan, second], index=[0, 0])
    original = data.copy(deep=True)
    result = validate_catalogue(data)
    duplicate_findings = [f for f in result.findings if f.rule == rule]
    assert len(duplicate_findings) == 2
    assert all("cross-file=True" in f.message for f in duplicate_findings)
    assert result.business_critical_errors.tolist() == ["conflict" in rule] * 2
    assert_frame_equal(data, original)


def test_global_sku_collision_is_separate_from_business_identity(finite_plan):
    second = dict(finite_plan, provider="Other Supplier", source_file="other.csv")
    result = validate_catalogue(pd.DataFrame([finite_plan, second]))
    assert [f.rule for f in result.findings] == ["global_sku_collision"] * 2
    assert not result.business_critical_errors.any()


def test_conflicting_destination_mapping_marks_both_rows(finite_plan):
    first = dict(finite_plan, country_code="FR", country_name="France")
    second = dict(first, sku="test-2", country_name="Different name", source_record_number=2)
    result = validate_catalogue(pd.DataFrame([first, second]))
    assert [f.rule for f in result.findings] == ["destination_mapping_conflict"] * 2
    assert result.business_critical_errors.all()


def test_multiple_providers_and_missing_schema_are_reported(finite_plan):
    second = dict(finite_plan, sku="test-2", provider="Other Supplier")
    result = validate_catalogue(pd.DataFrame([finite_plan, second]))
    assert [f.rule for f in result.findings] == ["multiple_file_providers"] * 2
    data = pd.DataFrame([finite_plan]).drop(columns="price")
    original = data.copy(deep=True)
    result = validate_catalogue(data)
    assert result.findings[0].severity == "BLOCKER"
    assert result.business_critical_errors.all()
    assert_frame_equal(data, original)


def test_no_arbitrary_statistical_limits(finite_plan):
    row = dict(finite_plan, price="1E100", data_gb="50", data_display="50 Go", validity_days="3650")
    result = validate_catalogue(pd.DataFrame([row]))
    assert not result.findings


def test_multiple_errors_do_not_remove_or_impute_values(finite_plan):
    data = pd.DataFrame([dict(finite_plan, sku="", price="bad", data_gb=None)])
    original = data.copy(deep=True)
    result = validate_catalogue(data)
    assert len(result.findings) >= 3
    assert len(result.business_critical_errors) == len(data) == 1
    assert_frame_equal(data, original)

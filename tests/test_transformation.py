"""Approved flags and finite EUR price-per-GB calculations."""
from decimal import Decimal

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.cleaning import clean_catalogue
from src.config import UNLIMITED_LABEL
from src.transformation import transform_catalogue
from src.validation import validate_catalogue
from test_cleaning import source_plan


@pytest.mark.parametrize("price,network,top_up,over,has_5g,has_top_up", [
    ("100", "4G", "non", False, False, False),
    ("100.01", "5G", "oui", True, True, True),
])
def test_finite_flags_boundary_and_ratio(price, network, top_up, over, has_5g, has_top_up):
    source = pd.DataFrame([source_plan(price=price, network=network, top_up=top_up)])
    cleaned = clean_catalogue(source, validate_catalogue(source))
    original = cleaned.copy(deep=True)
    transformed = transform_catalogue(cleaned)
    row = transformed.iloc[0]
    assert not row.is_unlimited
    assert bool(row.is_over_100) is over
    assert bool(row.has_5g) is has_5g
    assert bool(row.has_top_up) is has_top_up
    assert row.price_per_gb == Decimal(price) / Decimal(5)
    assert row.top_up == top_up
    assert_frame_equal(cleaned, original)


def test_unlimited_plan_has_no_numeric_allowance_or_ratio():
    data = pd.DataFrame([source_plan(data_gb="", data_display=UNLIMITED_LABEL)])
    result = transform_catalogue(clean_catalogue(data, validate_catalogue(data)))
    assert result.is_unlimited.iloc[0]
    assert pd.isna(result.data_gb.iloc[0])
    assert pd.isna(result.price_per_gb.iloc[0])


@pytest.mark.parametrize("changes", [
    {"data_gb": "0", "data_display": "0 Go"},
    {"data_gb": "Infinity"},
    {"price": "bad"},
    {"currency": "USD"},
    {"data_display": UNLIMITED_LABEL},
])
def test_invalid_or_ineligible_plan_never_gets_a_ratio(changes):
    data = pd.DataFrame([source_plan(**changes)])
    result = transform_catalogue(clean_catalogue(data, validate_catalogue(data)))
    assert len(result) == 1
    assert not result.is_analytically_eligible.iloc[0]
    assert pd.isna(result.price_per_gb.iloc[0])


def test_unknown_capabilities_do_not_become_false():
    data = pd.DataFrame([source_plan(network="6G", top_up="unknown")])
    result = transform_catalogue(clean_catalogue(data, validate_catalogue(data)))
    assert pd.isna(result.has_5g.iloc[0])
    assert pd.isna(result.has_top_up.iloc[0])


def test_failed_numeric_conversion_does_not_invent_unlimited_semantics():
    data = pd.DataFrame([source_plan(data_gb="invalid", data_display=UNLIMITED_LABEL)])
    result = transform_catalogue(clean_catalogue(data, validate_catalogue(data)))
    assert not result.is_unlimited.iloc[0]
    assert not result.is_analytically_eligible.iloc[0]
    assert result.source_data_gb.iloc[0] == "invalid"


def test_missing_display_stays_traceable_without_unlimited_inference():
    data = pd.DataFrame([source_plan(data_display=None)])
    result = transform_catalogue(clean_catalogue(data, validate_catalogue(data)))
    assert not result.is_unlimited.iloc[0]
    assert not result.is_analytically_eligible.iloc[0]

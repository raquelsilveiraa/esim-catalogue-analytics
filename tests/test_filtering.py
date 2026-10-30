"""Selection tests use a hand-calculated catalogue and existing metric functions."""
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.cleaning import clean_catalogue
from src.config import UNLIMITED_LABEL
from src.filtering import filter_catalogue
from src.metrics import calculate_metrics
from src.transformation import transform_catalogue
from src.validation import validate_catalogue
from test_cleaning import source_plan


@pytest.fixture
def catalogue():
    data = pd.DataFrame([
        source_plan(sku="one", price="100", network="4G", top_up="non"),
        source_plan(sku="two", source_record_number=2, price="120", data_gb="",
                    data_display=UNLIMITED_LABEL),
        source_plan(sku="three", source_record_number=3, provider="Supplier B", price="20",
                    country_code="FR", country_name="France"),
    ])
    return transform_catalogue(clean_catalogue(data, validate_catalogue(data)))


@pytest.mark.parametrize("filters,skus", [
    ({}, ["one", "two", "three"]),
    ({"providers": ["Supplier A"]}, ["one", "two"]),
    ({"networks": ["5G"]}, ["two", "three"]),
    ({"unlimited": True}, ["two"]),
    ({"unlimited": False}, ["one", "three"]),
    ({"top_up": False}, ["one"]),
    ({"destinations": ["NA"]}, ["one", "two"]),
    ({"providers": ["Supplier A"], "networks": ["5G"], "unlimited": True,
      "top_up": True, "destinations": ["NA"]}, ["two"]),
    ({"providers": ["Supplier B"], "unlimited": True}, []),
])
def test_filters_preserve_rows_and_do_not_mutate_source(catalogue, filters, skus):
    original = catalogue.copy(deep=True)
    filtered = filter_catalogue(catalogue, **filters)
    assert filtered.sku.tolist() == skus
    assert calculate_metrics(filtered)["total_products"] == len(skus)
    assert_frame_equal(catalogue, original)


def test_filtered_metrics_keep_their_denominators(catalogue):
    filtered = filter_catalogue(catalogue, providers=["Supplier A"])
    metrics = calculate_metrics(filtered)
    assert metrics["total_products"] == 2
    assert metrics["average_price"] == 110
    assert metrics["products_over_100"] == 1
    assert metrics["finite_plan_count"] == 1
    assert metrics["average_finite_data_gb"] == 5
    assert metrics["unlimited_plan_share"] == 0.5
    assert metrics["five_g_plan_share"] == 0.5


def test_unknown_flag_is_not_selected_as_false(catalogue):
    catalogue.loc[catalogue.sku.eq("one"), "has_top_up"] = pd.NA
    assert filter_catalogue(catalogue, top_up=False).empty


def test_price_range_includes_both_boundaries_without_mutation(catalogue):
    from decimal import Decimal

    original = catalogue.copy(deep=True)
    result = filter_catalogue(catalogue, price_range=(Decimal("100"), Decimal("120")))
    assert result.sku.tolist() == ["one", "two"]
    assert filter_catalogue(catalogue, providers=["Supplier A"], unlimited=False,
        price_range=(Decimal("100"), Decimal("100"))).sku.tolist() == ["one"]
    assert filter_catalogue(catalogue, price_range=(Decimal("121"), Decimal("200"))).empty
    with pytest.raises(ValueError, match="lower bound"):
        filter_catalogue(catalogue, price_range=(Decimal("120"), Decimal("100")))
    assert_frame_equal(catalogue, original)

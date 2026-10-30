"""Hand-calculated populations, filter safety, and full-catalogue regression."""
import math

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from src.cleaning import clean_catalogue
from src.config import UNLIMITED_LABEL
from src.metrics import aggregate_catalogue, calculate_metrics
from src.pipeline import run_pipeline
from src.transformation import transform_catalogue
from src.validation import validate_catalogue
from test_cleaning import source_plan


@pytest.fixture
def analytical_sample():
    rows = [
        source_plan(price="10", data_gb="1", data_display="1 Go", network="4G", top_up="non"),
        source_plan(sku="two", source_record_number=2, price="100", data_gb="3", data_display="3 Go"),
        source_plan(sku="three", source_record_number=3, provider="Supplier B", price="150",
                    data_gb="", data_display=UNLIMITED_LABEL, country_code="FR", country_name="France"),
        source_plan(sku="invalid", source_record_number=4, price="-100"),
    ]
    data = pd.DataFrame(rows)
    return transform_catalogue(clean_catalogue(data, validate_catalogue(data)))


def test_hand_calculated_metrics_and_denominators(analytical_sample):
    original = analytical_sample.copy(deep=True)
    metrics = calculate_metrics(analytical_sample)
    assert metrics["total_products"] == metrics["eur_price_population"] == 3
    assert metrics["products_over_100"] == 1
    assert metrics["minimum_price"] == 10
    assert metrics["maximum_price"] == 150
    assert metrics["average_price"] == pytest.approx(260 / 3)
    assert metrics["median_price"] == 100
    assert metrics["finite_plan_count"] == 2
    assert metrics["average_finite_data_gb"] == 2
    assert metrics["unlimited_plan_count"] == 1
    assert metrics["unlimited_plan_share"] == pytest.approx(1 / 3)
    assert metrics["five_g_plan_count"] == metrics["top_up_plan_count"] == 2
    assert metrics["five_g_plan_share"] == metrics["top_up_plan_share"] == pytest.approx(2 / 3)
    assert metrics["provider_count"] == metrics["destination_count"] == 2
    tables = aggregate_catalogue(analytical_sample)
    providers = tables["by_provider"].set_index("provider")
    assert providers.product_count.to_dict() == {"Supplier A": 2, "Supplier B": 1}
    assert providers.average_price.to_dict() == {"Supplier A": 55, "Supplier B": 150}
    for table in tables.values():
        assert table.product_count.sum() == metrics["total_products"]
    assert_frame_equal(analytical_sample, original)


def test_filters_reuse_identical_metric_definitions(analytical_sample):
    filtered = analytical_sample.loc[analytical_sample.provider.eq("Supplier A")]
    metrics = calculate_metrics(filtered)
    assert metrics["total_products"] == 2
    assert metrics["average_price"] == metrics["median_price"] == 55
    assert metrics["average_finite_data_gb"] == 2
    assert metrics["unlimited_plan_share"] == 0
    assert metrics["five_g_plan_share"] == 0.5


def test_empty_and_unlimited_only_populations(analytical_sample):
    metrics = calculate_metrics(analytical_sample.iloc[:0])
    assert metrics["total_products"] == 0
    for name in ("minimum_price", "maximum_price", "average_price", "median_price",
                 "average_finite_data_gb", "unlimited_plan_share", "five_g_plan_share", "top_up_plan_share"):
        assert metrics[name] is None
    assert all(table.empty for table in aggregate_catalogue(analytical_sample.iloc[:0]).values())
    unlimited = analytical_sample.loc[analytical_sample.is_unlimited]
    metrics = calculate_metrics(unlimited)
    assert metrics["average_finite_data_gb"] is None
    assert metrics["finite_plan_count"] == 0
    assert metrics["unlimited_plan_share"] == 1


def test_unknown_network_has_explicit_known_denominator():
    data = pd.DataFrame([source_plan(network="6G")])
    catalogue = transform_catalogue(clean_catalogue(data, validate_catalogue(data)))
    metrics = calculate_metrics(catalogue)
    assert metrics["total_products"] == 1
    assert metrics["five_g_known_population"] == 0
    assert metrics["five_g_plan_share"] is None


def test_complete_analytical_catalogue_matches_approved_baseline():
    result = run_pipeline()
    quality, metrics = result.data_quality, result.metrics
    assert quality["files_discovered"] == quality["files_loaded"] == 18
    assert quality["files_failed"] == 0
    assert quality["raw_rows"] == quality["ingested_rows"] == quality["validated_rows"] == 5056
    assert quality["analytically_eligible_rows"] == 5056
    assert quality["analytically_ineligible_rows"] == 0
    assert quality["raw_row_count_complete"] is True
    assert quality["critical_errors"] == quality["validation_findings"] == quality["duplicate_business_keys"] == 0
    assert result.analytical_catalogue.country_code.eq("NA").sum() == 192
    assert quality["unlimited_plans"] == metrics["unlimited_plan_count"] == 653
    assert metrics["finite_plan_count"] == 4403
    assert metrics["total_products"] == metrics["eur_price_population"] == 5056
    assert metrics["products_over_100"] == 56
    assert metrics["minimum_price"] == 5.36
    assert metrics["maximum_price"] == 154.63
    assert metrics["average_price"] == pytest.approx(29.301257911392405)
    assert metrics["average_finite_data_gb"] == pytest.approx(14.491483079718375)
    assert metrics["provider_count"] == 18
    assert metrics["five_g_plan_count"] == 1754
    assert metrics["top_up_plan_count"] == 2738
    assert all(table.product_count.sum() == 5056 for table in result.aggregations.values())
    assert result.analytical_catalogue.loc[result.analytical_catalogue.is_unlimited, "price_per_gb"].isna().all()
    assert all(math.isfinite(float(v)) for v in result.analytical_catalogue.price_per_gb.dropna())


def test_extreme_valid_prices_do_not_become_floating_point_infinity():
    from decimal import Decimal

    source = pd.DataFrame([source_plan(price="1E400")])
    catalogue = transform_catalogue(clean_catalogue(source, validate_catalogue(source)))
    metrics = calculate_metrics(catalogue)
    assert metrics["total_products"] == 1
    for key in ("minimum_price", "maximum_price", "average_price", "median_price"):
        assert metrics[key] == Decimal("1E400")
        assert metrics[key].is_finite()


def test_explicit_regional_entries_never_aggregate_national_coverage(analytical_sample):
    from src.metrics import summarize_regional_destinations

    regions = summarize_regional_destinations(analytical_sample).set_index("country_code")
    assert regions.product_count.to_dict() == {"EU": 0, "AS": 0, "NA": 2, "WW": 0}
    assert regions.loc["NA", "share"] == pytest.approx(2 / 3)
    assert "FR" not in regions.index
    assert calculate_metrics(analytical_sample)["products_over_100_share"] == pytest.approx(1 / 3)


def test_price_per_gb_summary_uses_existing_finite_eligible_ratios(analytical_sample):
    from src.metrics import summarize_price_per_gb

    summary, providers = summarize_price_per_gb(analytical_sample)
    assert summary["population"] == 2
    assert summary["average"] == pytest.approx((10 + 100 / 3) / 2)
    assert summary["minimum"] == 10
    assert summary["maximum"] == pytest.approx(100 / 3)
    assert providers.provider.tolist() == ["Supplier A"]
    unlimited = analytical_sample.loc[analytical_sample.is_unlimited]
    empty_summary, empty_providers = summarize_price_per_gb(unlimited)
    assert empty_summary["population"] == 0
    assert empty_summary["average"] is None
    assert empty_providers.empty


def test_characteristic_counts_and_shares_reconcile(analytical_sample):
    from src.metrics import summarize_characteristics

    tables = summarize_characteristics(analytical_sample)
    for table in tables.values():
        assert table.product_count.sum() == 3
        assert table.share.sum() == pytest.approx(1)
    assert tables["network"].set_index("category").product_count.to_dict() == {"4G": 1, "5G": 2}
    assert tables["top_up"].set_index("category").product_count.to_dict() == {True: 2, False: 1}

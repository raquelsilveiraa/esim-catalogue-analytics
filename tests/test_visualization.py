"""Distribution visualization preserves the existing EUR price population."""
from decimal import Decimal

import pandas as pd
from pandas.testing import assert_frame_equal

from app import build_price_histogram


def test_histogram_uses_real_eligible_eur_observations_without_mutation():
    data = pd.DataFrame({
        "price": [Decimal("10"), Decimal("20"), Decimal("100"), Decimal("999"), Decimal("500")],
        "currency": ["EUR", "EUR", "EUR", "USD", "EUR"],
        "is_analytically_eligible": [True, True, True, True, False],
    })
    original = data.copy(deep=True)
    figure = build_price_histogram(data)
    assert figure.data[0].type == "histogram"
    assert list(figure.data[0].x) == [10, 20, 100]
    assert figure.data[0].histnorm is None
    assert figure.data[0].xbins.size is None
    assert_frame_equal(data, original)


def test_histogram_handles_empty_and_filtered_populations():
    data = pd.DataFrame({"price": [Decimal("12.50")], "currency": ["EUR"],
                         "is_analytically_eligible": [True]})
    figure = build_price_histogram(data)
    assert list(figure.data[0].x) == [12.5]
    empty = build_price_histogram(data.iloc[:0])
    assert sum(len(trace.x) for trace in empty.data) == 0

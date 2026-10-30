"""Composable catalogue selection; KPI definitions stay in metrics.py."""
from collections.abc import Sequence
from decimal import Decimal

import pandas as pd


def filter_catalogue(data: pd.DataFrame, *, providers: Sequence[str] = (),
                     destinations: Sequence[str] = (), networks: Sequence[str] = (),
                     unlimited: bool | None = None,
                     top_up: bool | None = None,
                     price_range: tuple[Decimal, Decimal] | None = None) -> pd.DataFrame:
    """Return a copy; empty selections mean all values, unknown flags do not match."""
    mask = pd.Series(True, index=data.index)
    for column, selected in (("provider", providers), ("country_code", destinations),
                             ("network", networks)):
        if selected:
            mask &= data[column].isin(selected)
    for column, selected in (("is_unlimited", unlimited), ("has_top_up", top_up)):
        if selected is not None:
            mask &= data[column].eq(selected).fillna(False)
    if price_range is not None:
        lower, upper = price_range
        if lower > upper:
            raise ValueError("Price range lower bound must not exceed upper bound.")
        mask &= data["currency"].eq("EUR") & data["price"].between(lower, upper).fillna(False)
    return data.loc[mask].copy()

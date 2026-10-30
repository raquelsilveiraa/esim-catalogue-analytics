"""Derived fields from approved representations, without source mutation."""
from decimal import Decimal, localcontext

import pandas as pd

from .config import TOP_UP_VALUES, UNLIMITED_LABEL
from .validation import _is_missing


def transform_catalogue(data: pd.DataFrame) -> pd.DataFrame:
    """Keep unknown capabilities null; derive EUR ratios only for eligible plans."""
    fields = {"is_unlimited", "is_over_100", "has_5g", "has_top_up", "price_per_gb"}
    if fields.intersection(data.columns):
        raise ValueError("Source columns conflict with derived analytical fields.")
    result = data.copy(deep=True)
    unlimited_values, over_values, network_values, top_up_values, ratios = [], [], [], [], []
    for row in data.to_dict("records"):
        allowance, price = row["data_gb"], row["price"]
        unlimited = (isinstance(row["data_display"], str)
                     and row["data_display"] == UNLIMITED_LABEL
                     and _is_missing(row["source_data_gb"]))
        finite = isinstance(allowance, Decimal) and allowance.is_finite() and allowance > 0
        valid_price = isinstance(price, Decimal) and price.is_finite() and price > 0
        eur_price = valid_price and row["currency"] == "EUR"
        unlimited_values.append(unlimited)
        over_values.append(price > 100 if eur_price else pd.NA)
        network_values.append({"4G": False, "5G": True}.get(row["network"], pd.NA))
        top_up_values.append(TOP_UP_VALUES.get(row["top_up"], pd.NA))
        ratio = None
        if row["is_analytically_eligible"] and not unlimited and finite and eur_price:
            with localcontext() as context:
                context.prec = max(28, len(price.as_tuple().digits) + len(allowance.as_tuple().digits) + 8)
                ratio = price / allowance
        ratios.append(ratio)
    for column, values in (("is_unlimited", unlimited_values), ("is_over_100", over_values),
                           ("has_5g", network_values), ("has_top_up", top_up_values)):
        result[column] = pd.array(values, dtype="boolean")
    result["price_per_gb"] = pd.Series(ratios, index=data.index, dtype=object)
    return result

"""Filter-safe metrics; eligibility is applied inside every public calculation.

Product counts use eligible rows. Price metrics use eligible EUR rows. GB means
use eligible finite plans with known positive GB. Capability shares use known
flags, with their denominators returned explicitly. Empty means/shares are None.
"""
from decimal import Decimal, localcontext
import math

import pandas as pd

from .config import REGIONAL_DESTINATIONS


def _numeric_result(value: Decimal) -> float | Decimal:
    """Keep extreme finite values decimal rather than returning float infinity."""
    converted = float(value)
    return converted if math.isfinite(converted) else value


def _average(values: list[Decimal]) -> float | Decimal | None:
    if not values:
        return None
    # Enough significant digits to sum prices exactly before the final division.
    with localcontext() as context:
        context.prec = max(28, max(v.adjusted() for v in values)
                           - min(v.as_tuple().exponent for v in values) + len(str(len(values))) + 4)
        return _numeric_result(sum(values, Decimal(0)) / len(values))


def _share(count: int, population: int) -> float | None:
    return count / population if population else None


def calculate_metrics(data: pd.DataFrame) -> dict[str, int | float | Decimal | None]:
    """Calculate numeric, unformatted KPIs for the supplied filtered catalogue."""
    eligible = data.loc[data.is_analytically_eligible]
    eur = eligible.loc[eligible.currency.eq("EUR") & eligible.price.notna()]
    prices = sorted(eur.price.tolist())
    finite = eligible.loc[eligible.is_unlimited.eq(False) & eligible.data_gb.notna()]
    total = len(eligible)
    unlimited = int(eligible.is_unlimited.eq(True).sum())
    metrics = {
        "total_products": total,
        "eur_price_population": len(prices),
        "products_over_100": int(eur.is_over_100.eq(True).sum()),
        "products_over_100_share": _share(int(eur.is_over_100.eq(True).sum()), total),
        "minimum_price": _numeric_result(prices[0]) if prices else None,
        "maximum_price": _numeric_result(prices[-1]) if prices else None,
        "average_price": _average(prices),
        "median_price": _average(prices[(len(prices)-1)//2:len(prices)//2+1]) if prices else None,
        "finite_plan_count": len(finite),
        "average_finite_data_gb": _average(finite.data_gb.tolist()),
        "provider_count": int(eligible.provider.nunique()),
        "destination_count": int(eligible.country_code.nunique()),
        "unlimited_plan_count": unlimited,
        "unlimited_plan_share": _share(unlimited, total),
    }
    for field, prefix in (("has_5g", "five_g"), ("has_top_up", "top_up")):
        known = int(eligible[field].notna().sum())
        count = int(eligible[field].eq(True).sum())
        metrics[f"{prefix}_plan_count"] = count
        metrics[f"{prefix}_known_population"] = known
        metrics[f"{prefix}_plan_share"] = _share(count, known)
    return metrics


def aggregate_catalogue(data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return deterministic tables for dashboard filters without UI logic."""
    eligible = data.loc[data.is_analytically_eligible]
    provider = eligible.groupby("provider", sort=True).size().rename("product_count").to_frame()
    eur = eligible.loc[eligible.currency.eq("EUR") & eligible.price.notna()]
    provider["eur_price_population"] = eur.groupby("provider").size().reindex(provider.index, fill_value=0)
    provider["average_price"] = pd.Series(
        {name: _average(group.price.tolist()) for name, group in eur.groupby("provider")}, dtype=object)
    destination = eligible.groupby(["country_code", "country_name"], sort=True).size().rename("product_count").reset_index()
    network = eligible.groupby("network", sort=True, dropna=False).size().rename("product_count").reset_index()
    allowance = eligible.groupby("is_unlimited", sort=True, dropna=False).size().rename("product_count").reset_index()
    return {"by_provider": provider.reset_index(), "by_destination": destination,
            "by_network": network, "finite_vs_unlimited": allowance}


def summarize_regional_destinations(data: pd.DataFrame) -> pd.DataFrame:
    """Count only explicit regional/world products, never inferred country coverage."""
    destinations = aggregate_catalogue(data)["by_destination"]
    counts = destinations.groupby("country_code").product_count.sum()
    total = calculate_metrics(data)["total_products"]
    return pd.DataFrame([
        {"country_code": code, "country_name": name,
         "product_count": int(counts.get(code, 0)),
         "share": _share(int(counts.get(code, 0)), total)}
        for code, name in REGIONAL_DESTINATIONS.items()
    ])


def summarize_price_per_gb(data: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Summarize existing valid finite EUR ratios without deriving them again."""
    population = data.loc[data.is_analytically_eligible & data.currency.eq("EUR")
                          & data.is_unlimited.eq(False) & data.price_per_gb.notna()]
    ratios = sorted(population.price_per_gb.tolist())
    summary = {
        "population": len(ratios),
        "average": _average(ratios),
        "median": _average(ratios[(len(ratios)-1)//2:len(ratios)//2+1]) if ratios else None,
        "minimum": _numeric_result(ratios[0]) if ratios else None,
        "maximum": _numeric_result(ratios[-1]) if ratios else None,
    }
    providers = pd.DataFrame([
        {"provider": name, "finite_plan_count": len(group),
         "average_price_per_gb": _average(group.price_per_gb.tolist())}
        for name, group in population.groupby("provider", sort=True)
    ], columns=["provider", "finite_plan_count", "average_price_per_gb"])
    return summary, providers


def summarize_characteristics(data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Count all known and unknown categories; shares use the eligible population."""
    tables = aggregate_catalogue(data)
    metrics = calculate_metrics(data)
    total = metrics["total_products"]
    network = tables["by_network"].rename(columns={"network": "category"})
    plans = tables["finite_vs_unlimited"].rename(columns={"is_unlimited": "category"})
    known, count = metrics["top_up_known_population"], metrics["top_up_plan_count"]
    recharge = pd.DataFrame({"category": [True, False, None],
                             "product_count": [count, known-count, total-known]})
    result = {"network": network, "plans": plans,
              "top_up": recharge.loc[recharge.product_count.gt(0)].copy()}
    for table in result.values():
        table["share"] = table.product_count.map(lambda count: _share(int(count), total))
    return result

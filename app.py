
import base64
import hashlib
import logging
from html import escape
from pathlib import Path
from decimal import Decimal, DecimalException

import pandas as pd
import plotly.express as px
from plotly.graph_objects import Figure
import streamlit as st

from src.config import RAW_DIRECTORY
from src.filtering import filter_catalogue
from src.loader import discover_supplier_files
from src.metrics import (aggregate_catalogue, calculate_metrics, summarize_characteristics,
                         summarize_price_per_gb, summarize_regional_destinations)
from src.pipeline import PipelineResult, run_pipeline

FILTER_KEYS = ("providers", "destinations", "networks", "plan_type", "top_up", "price_range")
ACCENT = "#2584EF"
ASSET_DIRECTORY = Path(__file__).resolve().parent / "assets"


ICON_PATHS = {
    "catalogue": '<path d="M7 3h8l4 4v14H5V3h2Z"/><path d="M14 3v5h5M8 12h8M8 16h6"/>',
    "price": '<path d="m3 12 9-9h9v9l-9 9-9-9Z"/><circle cx="17" cy="7" r="1"/>',
    "data": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
    "bars": '<path d="M5 20v-7M12 20V8M19 20V3"/>',
}


def interface_icon(name: str) -> str:
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
            'aria-hidden="true">' + ICON_PATHS[name] + '</svg>')


def restore_catalogue() -> None:
    reset_filters()
    st.session_state["navigation"] = "Vue d'ensemble"


@st.cache_data(show_spinner=False, max_entries=2)
def load_catalogue(source_fingerprint: tuple[tuple[str, str], ...]) -> PipelineResult:
    # Content hashes invalidate the cache even if file size/timestamps are retained.
    return run_pipeline()


def source_fingerprint() -> tuple[tuple[str, str], ...]:
    """Let the loader report unreadable files rather than aborting cache lookup."""
    entries = []
    for path in discover_supplier_files():
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digest = "unreadable"
        entries.append((path.relative_to(RAW_DIRECTORY).as_posix(), digest))
    return tuple(entries)


def format_number(value: int | float | Decimal | None, decimals: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")


def format_currency(value: int | float | Decimal | None) -> str:
    return "—" if value is None else f"{format_number(value, 2)} €"


def reset_filters() -> None:
    # Explicit defaults notify browser widgets; deleting keys can leave stale chips.
    st.session_state.update({
        "providers": [], "destinations": [], "networks": [],
        "plan_type": "Tous", "top_up": "Tous",
    })
    if "catalogue_price_bounds" in st.session_state:
        st.session_state["price_range"] = st.session_state["catalogue_price_bounds"]
    else:
        st.session_state.pop("price_range", None)
    st.session_state.pop("open_price_analysis", None)


def horizontal_chart(frame: pd.DataFrame, category: str, measure: str,
                     title: str | None = None, *, currency: bool = False,
                     height: int | None = None, unit: str = "") -> None:
    if title:
        st.markdown(f"#### {title}")
    if frame.empty:
        st.caption("Aucune donnée disponible pour cette comparaison.")
        return
    chart = frame.sort_values([measure, category], ascending=[True, False]).copy()
    chart["display_value"] = chart[measure].map(
        lambda value: format_currency(value) + unit if currency else format_number(value))
    figure = px.bar(chart, x=measure, y=category, orientation="h", text="display_value",
                    custom_data=["display_value"], color_discrete_sequence=[ACCENT])
    figure.update_traces(textposition="outside", cliponaxis=False,
                         hovertemplate="%{y}<br>%{customdata[0]}<extra></extra>")
    figure.update_layout(template="plotly_white", height=height or max(160, len(chart) * 20 + 40), showlegend=False,
        margin=dict(l=0, r=64, t=5, b=15), separators=", ",
        font=dict(family="Arial, sans-serif", size=13, color="#33496B"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(title=None, automargin=True, fixedrange=True),
        xaxis=dict(title=None, rangemode="tozero", showgrid=False, showticklabels=False,
                   zeroline=False, fixedrange=True), bargap=0.32)
    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})


def build_price_histogram(data: pd.DataFrame) -> Figure:
    """Visualize actual observations from the eligible EUR price population."""
    population = data.loc[data.is_analytically_eligible & data.currency.eq("EUR") & data.price.notna()]
    figure = px.histogram(x=population.price.map(float).tolist(),
                          labels={"x": "Prix (€)", "y": "Nombre d'offres"},
                          color_discrete_sequence=[ACCENT])
    # Plotly chooses the classes from observations; no fabricated bin counts.
    figure.update_traces(hovertemplate="Prix : %{x} €<br>Offres : %{y}<extra></extra>",
                         marker=dict(line=dict(color="white", width=1)))
    figure.update_layout(template="plotly_white", height=240, showlegend=False,
        margin=dict(l=8,r=8,t=8,b=8), separators=", ", bargap=.06,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Arial, sans-serif", size=12, color="#33496B"),
        xaxis=dict(title="Prix (€)", rangemode="tozero"),
        yaxis=dict(title="Nombre d'offres", rangemode="tozero", tickformat="d", gridcolor="#edf2f8"))
    return figure


def render_small_metrics(items: list[tuple[str, str]], key: str) -> None:
    """Format existing calculations as secondary tiles rather than primary KPIs."""
    st.markdown(f'<div class="analysis-tiles" data-analysis="{escape(key, quote=True)}" role="list">'+''.join(
        f'<div class="analysis-tile" role="listitem"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in items)+'</div>', unsafe_allow_html=True)


def render_cards(metrics: dict) -> None:
    price_range = f"{format_currency(metrics['minimum_price'])} – {format_currency(metrics['maximum_price'])}"
    cards = [
        ("Offres", format_number(metrics["total_products"]),
         f"{format_number(metrics['provider_count'])} fournisseurs · {format_number(metrics['destination_count'])} destinations"),
        ("Prix moyen", format_currency(metrics["average_price"]),
         f"Médiane : {format_currency(metrics['median_price'])}<br>{price_range}"),
        ("Data moyenne", f"{format_number(metrics['average_finite_data_gb'], 2)} Go"
         if metrics["average_finite_data_gb"] is not None else "—",
         f"Sur {format_number(metrics['finite_plan_count'])} forfaits limités"),
        ("Offres > 100 €", format_number(metrics["products_over_100"]),
         f"{format_number(metrics['products_over_100_share'] * 100, 1)} % du catalogue"
         if metrics["products_over_100_share"] is not None else "Aucune offre sélectionnée"),
    ]
    for column, (label, value, secondary), name in zip(st.columns(4), cards, ICON_PATHS):
        with column, st.container(border=True, key=f"kpi_{name}"):
            icon_column, value_column = st.columns([1, 4], gap="small")
            with icon_column:
                st.markdown(f'<div class="kpi-icon icon-{name}">{interface_icon(name)}</div>', unsafe_allow_html=True)
            with value_column:
                st.metric(label, value)
                st.markdown(f'<div class="kpi-secondary">{secondary}</div>', unsafe_allow_html=True)


def render_regional_panel(selected: pd.DataFrame) -> None:
    st.markdown('<div class="panel-title">Offres par destination / zone</div>', unsafe_allow_html=True)
    map_column, legend = st.columns([2, 1], gap="small")
    with map_column:
        st.image(str(ASSET_DIRECTORY / "world_context.svg"), use_container_width=True)
    with legend:
        for row in summarize_regional_destinations(selected).itertuples():
            share = format_number(row.share * 100, 1) + " %" if row.share is not None else "—"
            st.markdown(f'<div class="region-row"><span><i class="region-dot region-{row.country_code}"></i>{escape(row.country_name)}</span>'
                f'<span><strong>{format_number(row.product_count)}</strong>'
                f'<small>({share})</small></span></div>', unsafe_allow_html=True)
    st.markdown('<div class="map-note">ⓘ Les zones régionales et mondiales sont distinctes des destinations nationales.</div>', unsafe_allow_html=True)


def render_offer_table(selected: pd.DataFrame) -> None:
    details = selected[["provider", "product_name", "country_name", "data_display",
                        "validity_days", "price", "network", "top_up"]].copy()
    details["top_up"] = details.top_up.map({"oui": "Oui", "non": "Non"}).fillna("Inconnue")
    details = details.rename(columns={"provider": "Fournisseur", "product_name": "Offre / nom du produit",
        "country_name": "Destination / zone", "data_display": "Données", "validity_days": "Validité (jours)",
        "price": "Prix", "network": "Réseau", "top_up": "Recharge"})
    # Styler changes display text while retaining numeric values for table sorting.
    styled = details.style.format({"Prix": format_currency, "Validité (jours)": format_number}).set_properties(
        subset=["Prix", "Validité (jours)"], **{"text-align": "right"})
    st.dataframe(styled, hide_index=True, use_container_width=True, height=260,
        column_config={
            "Fournisseur": st.column_config.TextColumn(width="small"),
            "Offre / nom du produit": st.column_config.TextColumn(width="large"),
            "Destination / zone": st.column_config.TextColumn(width="medium"),
            "Données": st.column_config.TextColumn(width="small"),
            "Validité (jours)": st.column_config.NumberColumn(width="small"),
            "Prix": st.column_config.NumberColumn(width="small"),
            "Réseau": st.column_config.TextColumn(width="small"),
            "Recharge": st.column_config.TextColumn(width="small"),
        })


def render_characteristics(selected: pd.DataFrame, metrics: dict) -> None:
    summaries = summarize_characteristics(selected)
    palettes = {
        "network": {"4G": "#064EAD", "5G": "#32A5FF"},
        "plans": {"Limité": "#0878EE", "Illimité": "#FF736A"},
        "top_up": {"Oui": "#0878EE", "Non": "#FF665E"},
    }
    for column, (key, title) in zip(st.columns(3),
            (("network", "Réseau déclaré"), ("plans", "Type de forfait"), ("top_up", "Recharge disponible"))):
        with column, st.container(border=True, key=f"donut_{key}"):
            st.markdown(f'<div class="donut-title">{escape(title)}</div>', unsafe_allow_html=True)
            chart = summaries[key].copy()
            chart["label"] = chart.category.map(
                {True: "Illimité", False: "Limité"} if key == "plans" else
                {True: "Oui", False: "Non"} if key == "top_up" else {}).fillna(
                    chart.category.astype(str) if key == "network" else "Inconnue")
            if key == "plans":
                chart = chart.sort_values("category")
            chart["display"] = chart.apply(lambda row:
                f"{format_number(row.product_count)} · {format_number(row.share * 100, 1)} %", axis=1)
            colors = {label: palettes[key].get(label, "#7A879D") for label in chart.label}
            ring, legend = st.columns([1, 1.2], gap="small")
            with ring:
                figure = px.pie(chart, names="label", values="product_count", hole=0.74,
                    custom_data=["display"], color="label", color_discrete_map=colors)
                figure.update_traces(sort=False, textinfo="none", marker=dict(line=dict(color="white", width=2)),
                    hovertemplate="%{label}<br>%{customdata[0]}<extra></extra>")
                figure.update_layout(height=140, margin=dict(l=1,r=1,t=4,b=4), showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)", annotations=[dict(x=.5,y=.5,xref="paper",yref="paper",
                        text=f"<b>{format_number(metrics['total_products'])}</b><br>offres", showarrow=False,
                        font=dict(size=11,color="#0C2044"))])
                st.plotly_chart(figure, use_container_width=True, key=f"characteristic_{key}",
                                config={"displayModeBar": False})
            with legend:
                rows = []
                for row in chart.itertuples():
                    color = colors[row.label]
                    rows.append(f'<div class="donut-legend"><span><i style="background:{color}"></i>{escape(row.label)}</span>'
                        f'<span><strong>{format_number(row.product_count)}</strong> ({format_number(row.share * 100, 1)} %)</span></div>')
                st.markdown('<div class="donut-legend-list">'+''.join(rows)+'</div>', unsafe_allow_html=True)


def render_supplier_ranking(table: pd.DataFrame) -> None:
    ranked = table.sort_values(["average_price", "provider"], ascending=[False, True]).head(10)
    maximum = ranked.average_price.max()
    rows = []
    for row in ranked.itertuples():
        width = float(row.average_price / maximum) * 94 if maximum else 0
        rows.append(f'<div class="supplier-row"><span title="{escape(row.provider, quote=True)}">{escape(row.provider)}</span>'
            f'<div class="supplier-track"><div style="width:{width:.3f}%"></div></div>'
            f'<span>{format_currency(row.average_price)}</span></div>')
    st.markdown('<div class="supplier-ranking">'+''.join(rows)+'</div>', unsafe_allow_html=True)


def render_secondary(selected: pd.DataFrame, metrics: dict, tables: dict) -> None:
    ratios, by_provider = summarize_price_per_gb(selected)
    with st.expander("**Analyse des prix** · Prix moyen, médiane, fourchette et prix par Go (forfaits limités)", expanded=False, icon=":material/euro:"):
        render_small_metrics([
            ("Prix moyen", format_currency(metrics["average_price"])),
            ("Médiane", format_currency(metrics["median_price"])),
            ("Minimum", format_currency(metrics["minimum_price"])),
            ("Maximum", format_currency(metrics["maximum_price"])),
            ("Offres > 100 €", format_number(metrics["products_over_100"])),
        ], "price")
        st.plotly_chart(build_price_histogram(selected), use_container_width=True,
                        key="price_distribution", config={"displayModeBar": False})
        st.markdown("#### Prix par Go — forfaits limités")
        st.caption(f"{format_number(ratios['population'])} offres limitées éligibles en EUR. Aucun prix par Go n'est attribué aux forfaits illimités.")
        render_small_metrics([
            (label, format_currency(ratios[key]) + "/Go" if ratios[key] is not None else "—")
            for label, key in (("Prix/Go moyen", "average"), ("Médiane", "median"), ("Minimum", "minimum"), ("Maximum", "maximum"))
        ], "price_per_gb")
    with st.expander("**Fournisseurs** · Nombre d'offres, prix moyen et prix par Go (forfaits limités)", expanded=False, icon=":material/group:"):
        left, right = st.columns(2)
        with left:
            horizontal_chart(tables["by_provider"], "provider", "product_count", "Nombre d'offres par fournisseur")
        with right:
            horizontal_chart(tables["by_provider"], "provider", "average_price", "Prix moyen par fournisseur", currency=True)
        horizontal_chart(by_provider, "provider", "average_price_per_gb", "Prix/Go moyen — forfaits limités", currency=True, unit="/Go")
    with st.expander("**Caractéristiques des offres** · Réseau, type de forfait, recharge", expanded=False, icon=":material/format_list_bulleted:"):
        render_characteristics(selected, metrics)
    with st.expander("**Détails du catalogue** · Explorer toutes les offres (filtres appliqués)", expanded=False, icon=":material/table_view:"):
        render_offer_table(selected)


def render_quality(result: PipelineResult, *, expanded: bool = False) -> None:
    quality = result.data_quality
    with st.expander("**Qualité des données** · Fichiers, validation, erreurs", expanded=expanded, icon=":material/verified:"):
        st.caption("Périmètre : ensemble des fichiers sources, indépendamment des filtres.")
        checks = [
            (f"{format_number(quality['files_loaded'])} fichiers fournisseurs traités", quality["files_failed"] == 0),
            (f"{format_number(quality['raw_rows'])} lignes sources", quality["raw_row_count_complete"]),
            (f"{format_number(quality['analytically_eligible_rows'])} offres analytiquement éligibles", quality["analytically_ineligible_rows"] == 0),
            (f"{format_number(quality['analytically_ineligible_rows'])} ligne(s) exclue(s)", quality["analytically_ineligible_rows"] == 0),
            (f"{format_number(quality['critical_errors'])} erreur(s) de validation ou blocage(s)", quality["critical_errors"] == 0),
            (f"{format_number(quality['duplicate_business_keys'])} identité(s) fournisseur/SKU répétée(s)", quality["duplicate_business_keys"] == 0),
        ]
        st.markdown('<div class="quality-checks">'+''.join(
            f'<div class="quality-check"><span class="quality-{"ok" if valid else "review"}">{"✓" if valid else "!"}</span>'
            f'<span>{escape(label)}</span></div>' for label, valid in checks)+'</div>', unsafe_allow_html=True)
        st.caption(f"{format_number(quality['files_discovered'])} fichiers détectés · {format_number(quality['files_failed'])} fichier(s) en échec.")
        st.caption(
            f"Chaque offre conserve sa provenance. {format_number(quality['unlimited_plans'])} forfaits illimités gardent data_gb nul ; ils sont identifiés "
            "explicitement, sans inventer de volume de données. Le code NA est conservé "
            "et désigne l'Amérique du Nord.")
        if not quality["raw_row_count_complete"]:
            st.warning("Le nombre de lignes sources est partiel : certains fichiers n'ont pas pu être lus intégralement.")
        if quality["validation_findings"]:
            st.write(f"{format_number(quality['validation_findings'])} signalement(s) de validation au total.")
        if result.ingestion.files:
            st.caption("Traçabilité par fichier source")
            st.dataframe(pd.DataFrame([
                {"Fichier source": report.source_file,
                 "État": "Traité" if report.loaded else "Échec — fichier à examiner",
                 "Lignes lues": report.rows_read}
                for report in result.ingestion.files]), hide_index=True, use_container_width=True, height=190)


def render_methodology() -> None:
    with st.expander("**Méthodologie** · Sources, règles de calcul et définitions", expanded=False, icon=":material/menu_book:"):
        st.markdown(
            "- Tous les fichiers fournisseurs sont découverts et consolidés automatiquement.\n"
            "- Les contrôles de qualité précèdent les transformations ; les lignes exclues restent traçables.\n"
            "- Les prix sont analysés en EUR, sans conversion de devise. Le seuil de 100 € est strict.\n"
            "- La moyenne en Go porte uniquement sur les forfaits limités disposant d'un volume valide. Les forfaits illimités ne reçoivent aucun volume artificiel.\n"
            "- Les filtres recalculent les indicateurs sur les offres éligibles sélectionnées.\n"
            "- Les parts 5G et recharge utilisent les valeurs connues ; les valeurs inconnues ne deviennent pas « non ».\n"
            "- Les destinations incluent des pays, des régions et une couverture mondiale.")


def main() -> None:
    st.set_page_config(page_title="MyBestSim — Catalogue eSIM", layout="wide", initial_sidebar_state="expanded")
    st.markdown("<style>" + (ASSET_DIRECTORY / "dashboard.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)
    with st.sidebar:
        logo = base64.b64encode((ASSET_DIRECTORY / "bestsim.png").read_bytes()).decode("ascii")
        st.markdown(f'<div class="wordmark"><img src="data:image/png;base64,{logo}" alt="Mascotte MyBestSim">'
                    '<span>MyBest<span>Sim</span></span></div>', unsafe_allow_html=True)
        with st.container(key="navigation_menu"):
            navigation = st.radio("Navigation", ("Vue d'ensemble", "Explorer les offres", "Qualité des données"),
                              key="navigation", label_visibility="collapsed")
        st.divider()
    header_title, header_action = st.columns([3.8, 1])
    with header_title:
        st.title("Analyse du catalogue eSIM")
    with header_action:
        st.button("Catalogue complet", icon=":material/database:", on_click=restore_catalogue,
                  help="Réinitialiser les filtres et revenir à la vue d'ensemble.", use_container_width=True)
    try:
        with st.spinner("Chargement et contrôle du catalogue…"):
            result = load_catalogue(source_fingerprint())
    except (OSError, ValueError, DecimalException):
        logging.exception("Catalogue loading failed")
        st.error("Le catalogue ne peut pas être chargé. Vérifiez la disponibilité et le format des fichiers fournisseurs.")
        st.stop()
    quality = result.data_quality
    if quality["files_failed"] or quality["analytically_ineligible_rows"]:
        st.warning("Catalogue partiel : certains fichiers ou certaines offres sont exclus. Consultez la qualité des données.")
    eligible = result.analytical_catalogue.loc[result.analytical_catalogue.is_analytically_eligible]
    if eligible.empty:
        st.error("Aucune offre éligible n'est disponible. Consultez le bilan de qualité des données.")
        render_quality(result)
        render_methodology()
        st.stop()
    full_metrics = result.metrics
    st.session_state["catalogue_price_bounds"] = (
        float(full_metrics["minimum_price"]), float(full_metrics["maximum_price"]))
    with st.sidebar:
        filter_title, filter_reset = st.columns([1, 1.25])
        with filter_title:
            st.markdown("#### Filtres")
        with filter_reset:
            st.button("Réinitialiser", icon=":material/restart_alt:", on_click=reset_filters, use_container_width=True)
        providers = st.multiselect("Fournisseur", sorted(eligible.provider.unique()), key="providers", placeholder="Tous les fournisseurs")
        labels = eligible.set_index("country_code").country_name.to_dict()
        destinations = st.multiselect("Destination / zone", sorted(labels, key=lambda code: labels[code]),
            key="destinations", placeholder="Toutes les destinations", format_func=lambda code: f"{labels[code]} ({code})")
        networks = st.multiselect("Réseau", sorted(eligible.network.unique()), key="networks", placeholder="Tous les réseaux")
        with st.expander("Plus de filtres", expanded=False):
            with st.container(key="plan_filter"):
                plan_type = st.radio("Type de forfait", ("Tous", "Limité", "Illimité"), key="plan_type", horizontal=True)
            with st.container(key="top_up_filter"):
                top_up = st.radio("Recharge", ("Tous", "Oui", "Non"), key="top_up", horizontal=True)
            lower, upper = st.session_state["catalogue_price_bounds"]
            # Keep one source for the widget value, including after an explicit reset.
            st.session_state.setdefault("price_range", (lower, upper))
            price_range = st.slider("Fourchette de prix (€)", min_value=lower, max_value=upper,
                value=None, step=0.01, key="price_range", disabled=lower == upper,
                format="%.2f €") if lower < upper else (lower, upper)
            if lower == upper:
                st.caption(f"Prix unique : {format_currency(lower)}")
            else:
                st.markdown(f'<div class="price-bounds" role="status" aria-live="polite" aria-label="Fourchette sélectionnée"><span>{format_currency(price_range[0])}</span>'
                            f'<span>{format_currency(price_range[1])}</span></div>', unsafe_allow_html=True)
    bounds = tuple(Decimal(str(value)) for value in price_range)
    active_price_range = bounds if price_range != (lower, upper) else None
    selected = filter_catalogue(eligible, providers=providers, destinations=destinations, networks=networks,
        unlimited={"Tous": None, "Limité": False, "Illimité": True}[plan_type],
        top_up={"Tous": None, "Oui": True, "Non": False}[top_up], price_range=active_price_range)
    metrics = calculate_metrics(selected)
    render_cards(metrics)
    if selected.empty:
        st.info("Aucune offre ne correspond à ces filtres. Modifiez votre sélection ou réinitialisez les filtres.")
    elif navigation == "Vue d'ensemble":
        tables = aggregate_catalogue(selected)
        left, right = st.columns([1.38, 1], gap="small")
        with left, st.container(border=True, key="overview_regions"):
            render_regional_panel(selected)
        with right, st.container(border=True, key="overview_suppliers"):
            title_column, action_column = st.columns([2.5, 1])
            with title_column:
                st.markdown('<div class="panel-title">Prix moyen par fournisseur</div>', unsafe_allow_html=True)
            with action_column:
                with st.popover("Voir tous →"):
                    all_providers = tables["by_provider"].rename(columns={"provider": "Fournisseur", "product_count": "Offres", "average_price": "Prix moyen", "eur_price_population": "Offres en EUR"})
                    st.dataframe(all_providers.style.format({"Prix moyen": format_currency}), hide_index=True, use_container_width=True)
            render_supplier_ranking(tables["by_provider"])
        render_secondary(selected, metrics, tables)
    elif navigation == "Explorer les offres":
        st.subheader("Explorer les offres")
        st.caption("Toutes les offres de la sélection · colonnes triables")
        render_offer_table(selected)
    render_quality(result, expanded=navigation == "Qualité des données")
    render_methodology()


if __name__ == "__main__":
    main()

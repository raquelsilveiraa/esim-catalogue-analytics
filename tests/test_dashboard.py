"""Runtime checks for the real Streamlit app, filters, and clear failures."""
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def accordion_nodes(app):
    # Streamlit 1.40 AppTest classifies icon-bearing expanders as status blocks.
    return [*app.expander, *app.status]



def test_dashboard_baseline_charts_filter_reset_and_empty_state():
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    assert not app.error
    assert not any(caption.value.startswith("Une vue consolidée") for caption in app.caption)
    assert len(app.metric) == 4
    assert [metric.value for metric in app.metric] == ["5 056", "29,30 €", "14,49 Go", "56"]
    secondary = " ".join(item.value for item in app.markdown)
    for expected in ("18 fournisseurs", "54 destinations", "5,36 €", "154,63 €", "20,70 €", "4 403", "1,1 %"):
        assert expected in secondary
    assert any("653" in caption.value for caption in app.caption)
    assert len(app.get("plotly_chart")) == 7
    import json
    histogram = next(json.loads(chart.proto.spec)["data"][0] for chart in app.get("plotly_chart")
                     if json.loads(chart.proto.spec)["data"][0]["type"] == "histogram")
    assert len(histogram["x"]) == 5056
    assert all(not expander.proto.expanded for expander in accordion_nodes(app))
    app.sidebar.multiselect(key="providers").set_value(["Airalo"]).run()
    assert not app.exception
    assert app.metric[0].value == "722"
    assert any("1 fournisseurs" in item.value for item in app.markdown)
    app.sidebar.radio(key="plan_type").set_value("Illimité").run()
    assert not app.exception
    assert app.metric[0].value == "91"
    assert app.metric[2].value == "—"
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert app.metric[0].value == "5 056"
    assert app.sidebar.multiselect(key="providers").value == []
    app.sidebar.multiselect(key="providers").set_value(["4S eSIM"]).run()
    app.sidebar.multiselect(key="destinations").set_value(["JP"]).run()
    assert not app.exception
    assert any("Aucune offre ne correspond" in message.value for message in app.info)
    assert len(app.get("plotly_chart")) == 0


def test_dashboard_loading_failure_has_a_french_message(monkeypatch):
    def fail_loading():
        raise OSError("Synthetic catalogue failure")

    st.cache_data.clear()
    monkeypatch.setattr("src.pipeline.run_pipeline", fail_loading)
    try:
        app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
        assert not app.exception
        assert len(app.error) == 1
        assert "Le catalogue ne peut pas être chargé" in app.error[0].value
        assert "Synthetic" not in app.error[0].value
    finally:
        st.cache_data.clear()


def test_dashboard_reports_partial_catalogue_without_hiding_failures(monkeypatch):
    from dataclasses import replace
    from src.config import Finding
    from src.pipeline import run_pipeline

    baseline = run_pipeline()
    failed_report = replace(baseline.ingestion.files[0], loaded=False,
        findings=(Finding("BLOCKER", "unreadable_file", None,
                          baseline.ingestion.files[0].source_file, None, None, None,
                          "Synthetic denied read"),))
    partial_ingestion = replace(baseline.ingestion,
        files=(failed_report, *baseline.ingestion.files[1:]))
    quality = dict(baseline.data_quality, files_loaded=17, files_failed=1,
                   critical_errors=1, validation_findings=1, raw_row_count_complete=False)
    partial = replace(baseline, ingestion=partial_ingestion, data_quality=quality)
    st.cache_data.clear()
    monkeypatch.setattr("src.pipeline.run_pipeline", lambda: partial)
    try:
        app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
        assert not app.exception
        assert any("Catalogue partiel" in warning.value for warning in app.warning)
        assert any("nombre de lignes sources est partiel" in warning.value for warning in app.warning)
        assert any("Échec" in str(table.value) for table in app.dataframe)
    finally:
        st.cache_data.clear()


def test_refactored_navigation_and_each_filter_recalculate_the_same_population():
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert app.sidebar.radio(key="navigation").options == ["Vue d'ensemble", "Explorer les offres", "Qualité des données"]
    app.sidebar.multiselect(key="networks").set_value(["5G"]).run()
    assert not app.exception
    assert app.metric[0].value == "1 754"
    app.sidebar.button[0].click().run()
    app.sidebar.radio(key="plan_type").set_value("Limité").run()
    assert app.metric[0].value == "4 403"
    app.sidebar.button[0].click().run()
    app.sidebar.radio(key="top_up").set_value("Oui").run()
    assert app.metric[0].value == "2 738"
    app.sidebar.button[0].click().run()
    app.sidebar.multiselect(key="destinations").set_value(["NA"]).run()
    assert app.metric[0].value == "192"
    app.sidebar.radio(key="navigation").set_value("Explorer les offres").run()
    assert not app.exception
    offers = next(table.value for table in app.dataframe if "Fournisseur" in table.value.columns)
    assert len(offers) == 192
    assert offers["Destination / zone"].eq("Amérique du Nord").all()
    app.sidebar.radio(key="navigation").set_value("Qualité des données").run()
    assert not app.exception
    assert any(expander.proto.expanded and "Qualité des données" in expander.label for expander in accordion_nodes(app))
    app.sidebar.button[0].click().run()
    assert app.metric[0].value == "5 056"


def test_price_range_filter_is_inclusive_and_combines_with_provider():
    from decimal import Decimal
    from src.filtering import filter_catalogue
    from src.metrics import calculate_metrics
    from src.pipeline import run_pipeline

    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.sidebar.multiselect(key="providers").set_value(["Airalo"]).run()
    app.sidebar.slider(key="price_range").set_value((10.0, 20.0)).run()
    expected = calculate_metrics(filter_catalogue(run_pipeline().analytical_catalogue,
        providers=["Airalo"], price_range=(Decimal("10"), Decimal("20"))))
    assert not app.exception
    assert app.metric[0].value == str(expected["total_products"])
    assert expected["minimum_price"] >= 10
    assert expected["maximum_price"] <= 20
    app.sidebar.button[0].click().run()
    assert app.sidebar.slider(key="price_range").value == (5.36, 154.63)
    assert app.metric[0].value == "5 056"


def test_visual_correction_has_real_mascot_six_collapsed_sections_and_three_donuts():
    import base64
    import json

    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    main_sections = [item for item in accordion_nodes(app) if item.label != "Plus de filtres"]
    assert [item.label.split("**")[1] for item in main_sections] == [
        "Analyse des prix", "Fournisseurs", "Caractéristiques des offres", "Détails du catalogue",
        "Qualité des données", "Méthodologie"]
    assert all(not item.proto.expanded for item in main_sections)
    mascot = APP_PATH.parent / "assets" / "bestsim.png"
    assert mascot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    encoded = base64.b64encode(mascot.read_bytes()).decode("ascii")
    assert any(encoded in item.value and 'alt="Mascotte MyBestSim"' in item.value
               for item in app.sidebar.markdown)
    pies = [json.loads(chart.proto.spec)["data"][0] for chart in app.get("plotly_chart")
            if json.loads(chart.proto.spec)["data"][0]["type"] == "pie"]
    assert len(pies) == 3
    assert all(pie["hole"] == 0.74 for pie in pies)
    assert all(len(set(pie["marker"]["colors"])) == len(pie["labels"]) for pie in pies)
    assert [pie["labels"] for pie in pies] == [["4G", "5G"], ["Limité", "Illimité"], ["Oui", "Non"]]
    assert [pie["values"] for pie in pies] == [[3302, 1754], [4403, 653], [2738, 2318]]
    assert not app.get("progress")
    app.sidebar.radio(key="plan_type").set_value("Illimité").run()
    assert not app.exception
    pie_values = [json.loads(chart.proto.spec)["data"][0]["values"] for chart in app.get("plotly_chart")
                  if json.loads(chart.proto.spec)["data"][0]["type"] == "pie"]
    assert all(sum(values) == 653 for values in pie_values)


def test_catalogue_complete_control_resets_filters_and_navigation():
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.sidebar.multiselect(key="providers").set_value(["Airalo"]).run()
    app.sidebar.multiselect(key="networks").set_value(["5G"]).run()
    app.sidebar.slider(key="price_range").set_value((10.0, 20.0)).run()
    app.sidebar.radio(key="navigation").set_value("Explorer les offres").run()
    control = next(button for button in app.button if button.label == "Catalogue complet")
    control.click().run()
    assert not app.exception
    assert app.sidebar.radio(key="navigation").value == "Vue d'ensemble"
    assert app.metric[0].value == "5 056"
    assert app.sidebar.multiselect(key="providers").value == []
    assert app.sidebar.multiselect(key="networks").value == []
    assert app.sidebar.slider(key="price_range").value == (5.36, 154.63)
    assert not app.warning


def test_overview_regional_entries_supplier_ranking_and_compact_quality_evidence():
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    markup = " ".join(item.value for item in app.markdown)
    for code, count in (("EU", 206), ("AS", 194), ("NA", 192), ("WW", 186)):
        row = next(item.value for item in app.markdown if 'class="region-row"' in item.value and f"region-{code}" in item.value)
        assert f"<strong>{count}</strong>" in row
    ranking = next(item.value for item in app.markdown if 'class="supplier-ranking"' in item.value)
    assert ranking.count('class="supplier-row"') == 10
    assert ranking.index("Yesim") < ranking.index("Flexiroam") < ranking.index("JamboSIM")
    assert "32,10 €" in ranking and "29,76 €" in ranking
    quality = next(item.value for item in app.markdown if 'class="quality-checks"' in item.value)
    for expected in ("18 fichiers fournisseurs traités", "5 056 lignes sources", "5 056 offres analytiquement éligibles",
                     "0 ligne(s) exclue(s)", "0 erreur(s) de validation", "0 identité(s) fournisseur/SKU"):
        assert expected in quality
    offers = next(table.value for table in app.dataframe if "Fournisseur" in table.value.columns and "Données" in table.value.columns)
    assert len(offers) == 5056
    sources = next(table.value for table in app.dataframe if "Fichier source" in table.value.columns)
    assert len(sources) == 18

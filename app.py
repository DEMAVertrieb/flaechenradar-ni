"""
FlächenRadar NI – Prüf- & Entscheidungswerkzeug für Entsiegelung & Klimaanpassung
Version 3.0 (B2G / B2B / B2C)

Start:  streamlit run app.py

Optionale Umgebungsvariablen:
  CRM_WEBHOOK_URL   – Endpoint für Vorgangsübergabe (POST JSON). Ohne Wert: kein Versand.
  DRIVE_FOLDER_URL  – Link zum Projektordner.
  KATASTER_CACHE    – Ordner für zwischengespeicherte Katasterdaten (Standard: ./kataster)
"""

import json
import math
import os
import re
import uuid
from datetime import datetime

import folium
import pandas as pd
import requests
import streamlit as st
from folium.plugins import Draw
from fpdf import FPDF
from shapely.geometry import shape as _shape
from streamlit_folium import st_folium

import kataster as ek
from gebuehren import FOERDER_KULISSE_NI, REGION_WERLTE, gebuehr

# ==============================================================================
# 0. KONFIGURATION
# ==============================================================================
st.set_page_config(
    page_title="FlächenRadar NI · Prüf- & Entscheidungswerkzeug",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CRM_WEBHOOK_URL = os.getenv("CRM_WEBHOOK_URL", "").strip()
DRIVE_FOLDER_URL = os.getenv("DRIVE_FOLDER_URL", "").strip()
BEARBEITUNGS_ZIEL_STUNDEN = 24
MINDEST_FLAECHE_M2 = 10
BAGATELL_ZUSCHUSS_EUR = 2_000
DE_MINIMIS_EUR = 300_000
KARTE_MAX_FLURSTUECKE = 250

DEFAULT_PU_ASPHALT_EUR_M2 = 68.0
DEFAULT_RUECKBAU_EUR_M2 = {
    "Asphalt": 22.0,
    "Beton": 30.0,
    "Pflaster": 14.0,
    "Schotter / wassergebunden": 8.0,
    "Sonstige": 20.0,
}
DEFAULT_UNTERBAU_EUR_M2 = {
    "Asphalt": 12.0,
    "Beton": 15.0,
    "Pflaster": 9.0,
    "Schotter / wassergebunden": 6.0,
    "Sonstige": 12.0,
}
NUTZUNGS_FAKTOR = {
    "Gewerbefläche / Parkplatz": 1.10,
    "Hoffläche": 1.00,
    "Geh- und Radweg": 0.90,
    "Sonstige": 1.00,
}
ALKIS_ZU_NUTZUNG = {
    "IndustrieUndGewerbeflaeche": "Gewerbefläche / Parkplatz",
    "FlaecheGemischterNutzung": "Hoffläche",
    "Wohnbauflaeche": "Hoffläche",
    "Weg": "Geh- und Radweg",
    "Platz": "Gewerbefläche / Parkplatz",
}
STUFEN_FARBE = {5: "#059669", 4: "#65A30D", 3: "#D97706"}

DEFAULT_PRECHECK_A_STUFE = 4
DEFAULT_PRECHECK_A_FL = 1000
DEFAULT_PRECHECK_B_STUFE = 3
DEFAULT_PRECHECK_B_FL = 300

MODUS_META = {
    "B2G": {
        "label": "Kommune (B2G)",
        "kurz": "Kommunale Flächen- & Entsiegelungsprüfung (§ 19 NKlimaG)",
        "titel": "Welche Flächen in Ihrem Gemeindegebiet bieten ein prüfenswertes Entsiegelungspotenzial?",
        "hinweis": (
            "Unterstützt Erfassung, Priorisierung und Vorlagenbildung im Kontext des Entsiegelungskatasters.NI. "
            "Vorläufige, nicht rechtsverbindliche Einschätzung – ersetzt keine Planung, Genehmigung oder Förderentscheidung."
        ),
        "b2b_default": True,
        "default_nutzung": "Geh- und Radweg",
    },
    "B2B": {
        "label": "Gewerbe & Eigentümer (B2B)",
        "kurz": "Wirtschaftlichkeit, Förderansatz, Gebührenlage & Erhalt der Nutzbarkeit",
        "titel": "Wie tragfähig ist eine Entsiegelung oder Teilentsiegelung auf Ihrer Betriebs- oder Objektfläche?",
        "hinweis": (
            "Vorläufige Richtwertprüfung unter Berücksichtigung von Förderkulisse, Netto-Eigenanteil, "
            "möglichem Gebühreneffekt und laufender Nutzbarkeit (Befahrbarkeit, Parken, Andienung)."
        ),
        "b2b_default": True,
        "default_nutzung": "Gewerbefläche / Parkplatz",
    },
    "B2C": {
        "label": "Privat (B2C)",
        "kurz": "Einfache Ersteinschätzung für Hof, Einfahrt und private Flächen",
        "titel": "Welche Entsiegelungs- oder Versickerungsmöglichkeiten passen zu Ihrer Fläche?",
        "hinweis": (
            "Unverbindliche Ersteinschätzung in verständlicher Sprache mit realistischem Kostenrahmen, "
            "möglichem Förderhinweis und klaren nächsten Schritten – ohne Fachjargon."
        ),
        "b2b_default": False,
        "default_nutzung": "Hoffläche",
    },
}

# ==============================================================================
# 1. SESSION-STATE
# ==============================================================================
ss = st.session_state
for k, v in {
    "zielgruppe": "B2G",
    "nachtmodus": False,
    "flaeche": 1250,
    "system_id": None,
    "scan_zeit": None,
    "crm_status": "off",
    "polygon_m2": 0.0,
    "flurstueck": None,
    "adresse": "",
    "nutzung_sel": "Geh- und Radweg",
    "cache_hinweis_shown": False,
}.items():
    ss.setdefault(k, v)


def uebernehme_polygon():
    if ss.polygon_m2 > 0:
        ss.flaeche = int(round(ss.polygon_m2))
        ss.flurstueck = None


def uebernehme_flurstueck(props):
    ss.flurstueck = props
    ss.flaeche = int(props["EntFl"])
    ss.adresse = props["Flurstueck"]
    ss.nutzung_sel = ALKIS_ZU_NUTZUNG.get(props.get("HauptTN"), "Sonstige")


# ==============================================================================
# 2. DESIGN & STYLING (Helles Tageslicht-Standard + optionaler Nachtmodus)
# ==============================================================================
dark = bool(ss.nachtmodus)
if dark:
    bg_app = "radial-gradient(1200px 600px at 10% -10%, #10233F 0%, #0B1220 60%)"
    card_bg = "#111A2B"
    kpi_bg = "#0D1524"
    border_col = "#1F2A3D"
    text_main = "#F1F5F9"
    text_muted = "#94A3B8"
    text_sub = "#64748B"
    accent_col = "#14B8A6"
    accent_soft = "#0F2A24"
    accent_val = "#2DD4BF"
    map_tiles = "CartoDB dark_matter"
else:
    bg_app = "linear-gradient(180deg, #F4F7FA 0%, #EDF2F7 100%)"
    card_bg = "#FFFFFF"
    kpi_bg = "#F8FAFC"
    border_col = "#D8E1EB"
    text_main = "#0F2942"
    text_muted = "#475569"
    text_sub = "#64748B"
    accent_col = "#0F766E"
    accent_soft = "#ECFDF5"
    accent_val = "#0F766E"
    map_tiles = "CartoDB positron"

st.markdown(
    f"""
<style>
#MainMenu, footer, header[data-testid="stHeader"] {{visibility:hidden; height:0;}}
.block-container {{padding-top:1.1rem; padding-bottom:2.2rem; max-width:1380px;}}
.stApp {{background:{bg_app}; color:{text_main};}}

.fr-top {{
  background:{card_bg}; border:1px solid {border_col}; border-radius:14px;
  padding:16px 20px; margin-bottom:16px;
  display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:14px;
  box-shadow:0 2px 10px rgba(15,41,66,0.04);
}}
.fr-kicker {{font-size:11px; letter-spacing:.14em; font-weight:700; color:{accent_col}; text-transform:uppercase;}}
.fr-h1 {{font-size:23px; font-weight:750; color:{text_main}; margin:2px 0 3px 0; line-height:1.2;}}
.fr-lead {{font-size:13px; color:{text_muted}; margin:0;}}

.fr-seal {{
  background:{kpi_bg}; border:1px solid {border_col}; border-left:4px solid {accent_col};
  border-radius:10px; padding:10px 14px; font-size:11.5px; color:{text_muted}; line-height:1.5;
  min-width:240px;
}}
.fr-seal b {{color:{text_main};}}

.fr-mode-banner {{
  background:{card_bg}; border:1px solid {border_col}; border-radius:12px;
  padding:14px 18px; margin-bottom:16px;
}}
.fr-mode-title {{font-size:16px; font-weight:700; color:{text_main}; margin:2px 0 5px 0;}}
.fr-mode-desc {{font-size:13px; color:{text_muted}; margin:0; line-height:1.5;}}

.st-key-card1, .st-key-card2, .st-key-card3, .st-key-card4 {{
  background:{card_bg}; border:1px solid {border_col}; border-radius:14px;
  padding:18px; box-shadow:0 2px 10px rgba(15,41,66,0.04);
}}
.step {{font-size:11px; letter-spacing:.14em; color:{accent_col}; font-weight:700; text-transform:uppercase;}}
.step-title {{font-size:17px; color:{text_main}; font-weight:700; margin:2px 0 12px 0;}}

.kpi {{
  background:{kpi_bg}; border:1px solid {border_col}; border-radius:10px;
  padding:12px 14px; margin-bottom:10px;
}}
.kpi .l {{font-size:11px; color:{text_muted}; text-transform:uppercase; letter-spacing:.06em; font-weight:600;}}
.kpi .v {{font-size:21px; color:{text_main}; font-weight:750; font-variant-numeric:tabular-nums; margin-top:3px;}}
.kpi .h {{font-size:12px; color:{text_sub}; margin-top:3px; line-height:1.35;}}
.kpi.accent {{border-color:{accent_col}; background:{accent_soft};}}
.kpi.accent .v {{color:{accent_val};}}
.kpi.muted .v {{color:{text_muted}; font-size:17px;}}

.srow {{
  display:flex; justify-content:space-between; align-items:center; gap:12px;
  padding:8px 0; border-bottom:1px dashed {border_col}; font-size:13px;
}}
.srow .k {{color:{text_muted};}}
.srow .val {{color:{text_main}; font-weight:600; text-align:right; font-size:12.5px;}}

.pill {{display:inline-block; padding:2px 9px; border-radius:999px; font-size:11.5px; font-weight:600; white-space:nowrap;}}
.pill.ok {{background:#DCFCE7; color:#166534;}}
.pill.warn {{background:#FEF3C7; color:#92400E;}}
.pill.bad {{background:#FEE2E2; color:#991B1B;}}
.pill.off {{background:#E2E8F0; color:#334155;}}

.flst {{
  background:{accent_soft}; border:1px solid {accent_col}; border-radius:10px;
  padding:10px 12px; margin:8px 0; font-size:12.5px; color:{text_main}; line-height:1.45;
}}
.next-step {{
  background:{kpi_bg}; border:1px solid {border_col}; border-radius:10px;
  padding:10px 12px; margin-top:10px; font-size:12.5px; color:{text_main}; line-height:1.45;
}}
.stButton>button, .stDownloadButton>button, .stLinkButton>a {{
  width:100%; border-radius:8px !important; font-weight:700 !important; min-height:42px;
}}
.stButton>button[kind="primary"] {{
  background:{accent_col} !important; border:none !important; color:#FFFFFF !important;
}}
.fr-foot {{
  font-size:11.5px; color:{text_sub}; border-top:1px solid {border_col};
  margin-top:22px; padding-top:12px; line-height:1.55;
}}
@media (max-width: 768px) {{
  .fr-h1 {{font-size:20px;}}
  .fr-seal {{width:100%;}}
  .kpi .v {{font-size:19px;}}
}}
</style>
""",
    unsafe_allow_html=True,
)


# ==============================================================================
# 3. HILFSFUNKTIONEN
# ==============================================================================
def zahl(x: float, nk: int = 0) -> str:
    return f"{x:,.{nk}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def eur(x: float, nk: int = 0) -> str:
    return f"{zahl(x, nk)} €"


def eur_spanne(betrag: float, spanne_pct: float = 0.15) -> str:
    unten = max(0.0, betrag * (1.0 - spanne_pct))
    oben = max(unten, betrag * (1.0 + spanne_pct))
    return f"{eur(unten)} – {eur(oben)}"


def kpi(label, value, hint="", cls=""):
    st.markdown(
        f'<div class="kpi {cls}"><div class="l">{label}</div><div class="v">{value}</div>'
        f'<div class="h">{hint}</div></div>',
        unsafe_allow_html=True,
    )


def srow(k, v):
    st.markdown(
        f'<div class="srow"><span class="k">{k}</span><span class="val">{v}</span></div>',
        unsafe_allow_html=True,
    )


def polygon_flaeche_m2(coords) -> float:
    if len(coords) < 3:
        return 0.0
    lat0 = math.radians(sum(c[1] for c in coords) / len(coords))
    R = 6_371_008.8
    pts = [(math.radians(lon) * R * math.cos(lat0), math.radians(lat) * R) for lon, lat in coords]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2


@st.cache_data(show_spinner=False, ttl=86_400)
def katalog():
    return ek.lade_katalog()


@st.cache_data(show_spinner=False, max_entries=20)
def entpot(gemeinde: str):
    return ek.lade_entpot(katalog()[gemeinde])


@st.cache_resource(show_spinner=False, max_entries=5)
def index_fuer(gemeinde: str):
    return ek.Index(entpot(gemeinde)[0])


# ==============================================================================
# 4. KOPFZEILE, ZIELGRUPPEN-MODUS & SIDEBAR
# ==============================================================================
mode_cols = st.columns([2.2, 1.3, 0.8], gap="small")
with mode_cols[0]:
    auswahl_modus = st.radio(
        "Prüfkontext / Zielgruppe",
        options=["B2G", "B2B", "B2C"],
        format_func=lambda m: MODUS_META[m]["label"],
        index=["B2G", "B2B", "B2C"].index(ss.zielgruppe),
        horizontal=True,
        label_visibility="collapsed",
    )
    if auswahl_modus != ss.zielgruppe:
        ss.zielgruppe = auswahl_modus
        ss.nutzung_sel = MODUS_META[auswahl_modus]["default_nutzung"]
with mode_cols[2]:
    ss.nachtmodus = st.toggle("Nachtmodus", value=ss.nachtmodus)

aktiv_modus = MODUS_META[ss.zielgruppe]
pruef_stand = ss.system_id or "Entwurf (ohne Scan)"

st.markdown(
    f"""
<div class="fr-top">
  <div>
    <div class="fr-kicker">FLÄCHENRADAR NI · LANDESKATASTER &amp; VORPRÜFUNG</div>
    <div class="fr-h1">Entsiegelungs- &amp; Klimaanpassungs-Werkzeug</div>
    <p class="fr-lead">Prüfung, Einordnung und Vorbereitung für Kommune, Gewerbe und Privat · Beratung &amp; Koordination: DEMA Vertrieb GbR</p>
  </div>
  <div class="fr-seal">
    <b>FlächenRadar-Prüfsiegel</b><br>
    Kennung: <b>{pruef_stand}</b><br>
    Modus: <b>{aktiv_modus["label"]}</b> · Stand: {datetime.now():%d.%m.%Y}
  </div>
</div>
<div class="fr-mode-banner">
  <div class="fr-kicker">{aktiv_modus["label"]} · {aktiv_modus["kurz"]}</div>
  <div class="fr-mode-title">{aktiv_modus["titel"]}</div>
  <p class="fr-mode-desc">{aktiv_modus["hinweis"]}</p>
</div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Kriterien der Ersteinschätzung")
    st.caption("Schwellenwerte für Priorität A und B in Karte & Flächenübersicht")
    pc_a_stufe = st.slider("Priorität A: min. Potenzialstufe", 3, 5, DEFAULT_PRECHECK_A_STUFE, key="pc_a_stufe")
    pc_a_fl = st.number_input("Priorität A: min. Fläche (m²)", 100, 5000, DEFAULT_PRECHECK_A_FL, step=100, key="pc_a_fl")
    pc_b_stufe = st.slider("Priorität B: min. Potenzialstufe", 2, 5, DEFAULT_PRECHECK_B_STUFE, key="pc_b_stufe")
    pc_b_fl = st.number_input("Priorität B: min. Fläche (m²)", 50, 2000, DEFAULT_PRECHECK_B_FL, step=50, key="pc_b_fl")
    st.divider()
    st.caption("Richtwert: Priorität A ≥ Stufe 4 + ≥ 1.000 m² · Priorität B ≥ Stufe 3 + ≥ 300 m²")

try:
    KATALOG = katalog()
    kat_ok = True
except Exception:
    KATALOG, kat_ok = {}, False

col1, col2, col3 = st.columns([1.25, 1, 1], gap="medium")

# ==============================================================================
# 5. STEP 1 – STANDORT, FLURSTÜCK & KATASTER
# ==============================================================================
with col1:
    with st.container(key="card1"):
        st.markdown(
            '<div class="step">Schritt 1 · Standort &amp; Kataster</div>'
            '<div class="step-title">Fläche &amp; Entsiegelungspotenzial prüfen</div>',
            unsafe_allow_html=True,
        )

        gemeinden = sorted(KATALOG) if kat_ok else REGION_WERLTE
        if "Haselünne, Stadt" in gemeinden:
            g_default = gemeinden.index("Haselünne, Stadt")
        elif "Werlte" in gemeinden:
            g_default = gemeinden.index("Werlte")
        else:
            g_default = 0

        a, b = st.columns([1.4, 1])
        gemeinde = a.selectbox("Gemeinde (Entsiegelungskataster.NI)", gemeinden, index=g_default)
        min_stufe = b.selectbox(
            "Landes-Potenzial ab Stufe",
            [5, 4, 3],
            index=1,
            format_func=lambda s: {5: "5 – sehr hoch", 4: "4 – hoch", 3: "3 – mittel"}[s],
        )

        feats, kstat = ([], None)
        if kat_ok:
            with st.spinner(f"Katasterdaten für {gemeinde} werden geladen …"):
                try:
                    feats, kstat = entpot(gemeinde)
                    if not ss.cache_hinweis_shown:
                        st.info(
                            "Katasterdaten werden je Gemeinde einmalig geladen (ca. 10–15 MB) und lokal "
                            "zwischengespeichert (in der Cloud-Umgebung vorläufig / nicht dauerhaft).",
                            icon="ℹ️",
                        )
                        ss.cache_hinweis_shown = True
                except Exception as e:
                    st.error(f"Katasterdaten konnten nicht geladen werden: {e}")
        else:
            st.warning("Kataster-Katalog derzeit nicht erreichbar – manuelle Prüfung aktiv.")

        def live_prioritaet(p: dict) -> str:
            s, fl = p.get("Stufe", 0), p.get("EntFl", 0)
            tn = p.get("HauptTN")
            if s >= pc_a_stufe and fl >= pc_a_fl and tn in ek.B2B_NUTZUNGEN:
                return "A"
            if s >= pc_b_stufe and fl >= pc_b_fl:
                return "B"
            return "C"

        for f in feats:
            f["properties"]["PreCheck"] = live_prioritaet(f["properties"])

        filter_label = (
            "Nur kommunale / gewerbliche / öffentliche Nutzungen filtern"
            if ss.zielgruppe != "B2C"
            else "Auch auf gewerbliche/öffentliche Nutzungen einschränken (aus = alle Flächen sichtbar)"
        )
        nur_b2b = st.toggle(filter_label, value=aktiv_modus["b2b_default"])

        sicht = [
            f
            for f in feats
            if f["properties"]["Stufe"] >= min_stufe
            and (not nur_b2b or f["properties"]["HauptTN"] in ek.B2B_NUTZUNGEN)
        ][:KARTE_MAX_FLURSTUECKE]

        fs_geom = None
        if ss.flurstueck:
            fs_geom = next(
                (f["geometry"] for f in feats if f["properties"]["Fsk"] == ss.flurstueck["Fsk"]),
                None,
            )
        if fs_geom:
            c = _shape(fs_geom).centroid
            center, zoom = (c.y, c.x), 17
        elif sicht:
            c = _shape(sicht[0]["geometry"]).centroid
            center, zoom = (c.y, c.x), 14
        else:
            center, zoom = (52.85, 7.67), 12

        m = folium.Map(location=center, zoom_start=zoom, tiles=map_tiles, control_scale=True)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri World Imagery",
            name="Luftbild (Orthophoto)",
        ).add_to(m)
        if sicht:
            folium.GeoJson(
                {"type": "FeatureCollection", "features": sicht},
                name="Landes-Entsiegelungspotenzial",
                style_function=lambda f: {
                    "color": STUFEN_FARBE.get(f["properties"]["Stufe"], "#64748B"),
                    "weight": 1.3,
                    "fillOpacity": 0.35,
                },
                highlight_function=lambda f: {"weight": 3, "fillOpacity": 0.6},
                tooltip=folium.GeoJsonTooltip(
                    fields=["Flurstueck", "Nutzung", "EntFl", "VerAnt_pct", "EntPot", "PreCheck"],
                    aliases=["Flurstück", "Nutzung", "Landes-Potenzial (m²)", "Versiegelt (%)", "Stufe", "Einordnung"],
                ),
            ).add_to(m)
        folium.LayerControl(position="topright").add_to(m)
        Draw(
            export=False,
            position="topleft",
            draw_options={"polyline": False, "circle": False, "marker": False, "circlemarker": False},
            edit_options={"edit": True, "remove": True},
        ).add_to(m)

        st.caption(
            f"{len(sicht)} Flurstücke angezeigt (max. {KARTE_MAX_FLURSTUECKE}). "
            "Flurstück in der Karte anklicken oder eigene Prüffläche einzeichnen."
        )
        out = st_folium(
            m,
            height=340,
            use_container_width=True,
            returned_objects=["last_object_clicked", "all_drawings"],
            key=f"map_{gemeinde}",
        )

        klick = (out or {}).get("last_object_clicked")
        treffer = None
        if klick and feats:
            treffer = index_fuer(gemeinde).finde(klick["lng"], klick["lat"])
        if treffer:
            p = treffer["properties"]
            st.markdown(
                f'<div class="flst"><b>{p["Flurstueck"]}</b> · {p["Gmd"]}<br>'
                f'Nutzung: {p["Nutzung"]} · Flurstück: {zahl(ek.num(p["FlstFl_m2"]))} m² · '
                f'Versiegelungsanteil: {p["VerAnt_pct"]} %<br>'
                f'<b>Landes-Entsiegelungspotenzial: {zahl(p["EntFl"])} m²</b> ({p["EntPot"]}) · '
                f'Einordnung: <b>{p["PreCheck"]}</b></div>',
                unsafe_allow_html=True,
            )
            st.button("Flurstück für Prüfung übernehmen", on_click=uebernehme_flurstueck, args=(p,), type="secondary")

        drawings = (out or {}).get("all_drawings") or []
        ss.polygon_m2 = sum(
            polygon_flaeche_m2(f["geometry"]["coordinates"][0])
            for f in drawings
            if f.get("geometry", {}).get("type") == "Polygon"
        )
        if ss.polygon_m2 > 0:
            st.button(
                f"Eingezeichnete Fläche übernehmen ({zahl(ss.polygon_m2)} m²)",
                on_click=uebernehme_polygon,
            )

        st.divider()
        firma_label = "Kommune / Behörde / Flächenträger" if ss.zielgruppe == "B2G" else "Name / Betrieb / Objektträger"
        firma = st.text_input(firma_label, value="", placeholder="z. B. Stadt/Gemeinde oder Betrieb")
        a, b = st.columns([1, 2])
        plz = a.text_input("PLZ", value="49740", max_chars=5)
        strasse = b.text_input("Lage / Adresse / Flurstück", key="adresse", placeholder="optional")
        plz_ok = bool(re.fullmatch(r"\d{5}", plz or ""))
        if plz and not plz_ok:
            st.error("Bitte eine gültige fünfstellige Postleitzahl eingeben.")

        kulisse_label = st.selectbox(
            "Förderkulisse (Niedersachsen & Bund – vorläufig)",
            list(FOERDER_KULISSE_NI.keys()),
            index=0,
        )
        kulisse_info = FOERDER_KULISSE_NI[kulisse_label]
        c, d = st.columns(2)
        belag = c.selectbox("Vorhandener Belag", list(DEFAULT_RUECKBAU_EUR_M2))
        nutzung = d.selectbox("Nutzungsart", list(NUTZUNGS_FAKTOR), key="nutzung_sel")
        flaeche = st.number_input(
            "Prüffläche (m²)",
            min_value=0,
            step=50,
            key="flaeche",
            help="Landes-Potenzial oder eigene Prüffläche; praktische Umsetzbarkeit wird vor Ort geprüft.",
        )

        scan_triggered = st.button(
            "▶ PRÜFUNG & ERSTEINSCHÄTZUNG STARTEN",
            type="primary",
            disabled=(flaeche < MINDEST_FLAECHE_M2 or not plz_ok),
        )
        if flaeche < MINDEST_FLAECHE_M2:
            st.warning(
                f"Prüfung erst ab {MINDEST_FLAECHE_M2} m² sinnvoll (aktuell: {flaeche} m²). "
                "Bitte Fläche erhöhen oder ein Flurstück/Polygon übernehmen."
            )

# ==============================================================================
# 6. BERECHNUNGS- & ANNAHMENLOGIK (Transparent & nachvollziehbar)
# ==============================================================================
g_info = gebuehr(gemeinde)
with st.expander("Annahmen & Richtwerte offenlegen (transparente Berechnungsgrundlage)"):
    p1, p2, p3, p4 = st.columns(4)
    pu_preis = p1.number_input(
        "Durchlässiger Belag / PU-Asphalt inkl. Einbau (€/m²)",
        value=DEFAULT_PU_ASPHALT_EUR_M2,
        step=1.0,
    )
    rueckbau = p2.number_input(f"Rückbau {belag} (€/m²)", value=DEFAULT_RUECKBAU_EUR_M2[belag], step=1.0)
    unterbau = p3.number_input(
        f"Unterbau-Anpassung {belag} (€/m²)", value=DEFAULT_UNTERBAU_EUR_M2[belag], step=1.0
    )
    gebuehr_satz = p4.number_input(
        f"Niederschlagswassergebühr {gemeinde} (€/m²·a)",
        value=float(g_info["satz"] or 0.0),
        step=0.05,
        key=f"geb_{gemeinde}",
        help=g_info["hinweis"],
    )
    q1, _ = st.columns(2)
    foerder_quote_manuell = q1.number_input(
        "Angenommene Förderquote (%)",
        0,
        100,
        int(kulisse_info["quote_default"]),
        help=f"Orientierungswert der Kulisse: {kulisse_info['quote_default']} % (vorbehaltlich Förderprüfung).",
    )
    st.caption(f"**{kulisse_info['code']}** · {kulisse_info['traeger']} — {kulisse_info['hinweis']}")

preis_m2 = (pu_preis + rueckbau + unterbau) * NUTZUNGS_FAKTOR[nutzung]
kosten = flaeche * preis_m2
hinweise = []
programm = kulisse_label
quote = float(foerder_quote_manuell)
foerderfaehig = quote > 0
if not foerderfaehig:
    hinweise.append("Keine Förderquote hinterlegt – passende Förderprogramme für Kommune/Land/Bund prüfen.")
zuschuss = kosten * quote / 100 if foerderfaehig else 0.0
if foerderfaehig and zuschuss < BAGATELL_ZUSCHUSS_EUR and quote > 0:
    hinweise.append(f"Voraussichtlicher Zuschuss unter {eur(BAGATELL_ZUSCHUSS_EUR)} – Bagatellgrenzen prüfen.")
if zuschuss > DE_MINIMIS_EUR:
    hinweise.append(f"De-minimis-Obergrenze ({eur(DE_MINIMIS_EUR)}) in der Berechnung berücksichtigt.")
    zuschuss = DE_MINIMIS_EUR
if gebuehr_satz <= 0:
    hinweise.append(
        f"Für {gemeinde} ist kein laufender Niederschlagswassergebührensatz hinterlegt. "
        "Weitere Argumente: Starkregenvorsorge, Entlastung der Entwässerung und Erhalt der Flächennutzung."
    )
hinweise.append("Untergrund, Leitungen, Schutzgebiete und Entwässerung müssen vor Ort bzw. fachlich geprüft werden.")
hinweise.append(
    "Vorläufige, unverbindliche Einschätzung – keine verbindliche Planung, Förderzusage oder Preisgarantie. "
    "Beratung & Koordination: DEMA Vertrieb GbR; Ausführung über Fachbetriebe."
)

eigenanteil = max(0.0, kosten - zuschuss)
ersparnis = flaeche * gebuehr_satz
amortisation = eigenanteil / ersparnis if ersparnis > 0 else float("inf")
eff_quote = zuschuss / kosten * 100 if kosten else 0.0

if scan_triggered:
    ss.system_id = f"FR-{datetime.now():%Y%m%d}-{plz}-{uuid.uuid4().hex[:4].upper()}"
    ss.scan_zeit = datetime.now()
    payload = {
        "system_id": ss.system_id,
        "zielgruppe": ss.zielgruppe,
        "firma": firma,
        "plz": plz,
        "adresse": strasse,
        "gemeinde": gemeinde,
        "flurstueck": (ss.flurstueck or {}).get("Fsk"),
        "flaeche_m2": flaeche,
        "bestand": belag,
        "nutzung": nutzung,
        "programm": programm,
        "foerderquote": round(eff_quote, 1),
        "kosten": round(kosten, 2),
        "zuschuss": round(zuschuss, 2),
        "eigenanteil": round(eigenanteil, 2),
        "quelle": "FlaechenRadar_NI_v3",
        "zeitstempel": ss.scan_zeit.isoformat(),
    }
    if CRM_WEBHOOK_URL:
        try:
            ss.crm_status = "ok" if requests.post(CRM_WEBHOOK_URL, json=payload, timeout=8).ok else "fail"
        except Exception:
            ss.crm_status = "fail"
    else:
        ss.crm_status = "off"

# ==============================================================================
# 7. STEP 2 – EINORDNUNG, DATENLAGE & NÄCHSTE SCHRITTE
# ==============================================================================
with col2:
    with st.container(key="card2"):
        st.markdown(
            '<div class="step">Schritt 2 · Einordnung &amp; Ablauf</div>'
            '<div class="step-title">Prüfstatus &amp; nächste Schritte</div>',
            unsafe_allow_html=True,
        )
        srow("Prüfkennung", ss.system_id or "– noch nicht ausgelöst –")
        pc = (ss.flurstueck or {}).get("PreCheck")
        srow(
            "Ersteinschätzung Fläche",
            {
                "A": '<span class="pill ok">Priorität A · hoch</span>',
                "B": '<span class="pill warn">Priorität B · prüfen</span>',
                "C": '<span class="pill off">Priorität C · nachrangig</span>',
            }.get(pc, '<span class="pill off">manuell / Polygon</span>'),
        )
        srow("Förderkulisse", programm)
        srow(
            "Förderhinweis",
            '<span class="pill ok">Ansatz vorhanden</span>'
            if zuschuss > 0
            else '<span class="pill warn">Prüfung erforderlich</span>',
        )
        geb_pill = (
            f'<span class="pill ok">{zahl(gebuehr_satz, 2)} €/m²·a</span>'
            if gebuehr_satz > 0
            else '<span class="pill warn">kein Satz hinterlegt</span>'
            if g_info["status"] == "keine"
            else '<span class="pill off">nicht hinterlegt</span>'
        )
        srow(f"NW-Gebühr ({gemeinde})", geb_pill)

        if ss.scan_zeit:
            h = (datetime.now() - ss.scan_zeit).total_seconds() / 3600
            rest = BEARBEITUNGS_ZIEL_STUNDEN - h
            status_pill = (
                f'<span class="pill ok">erfasst · {zahl(max(0.0, rest), 1)} h Zielzeitfenster</span>'
                if h < BEARBEITUNGS_ZIEL_STUNDEN
                else '<span class="pill warn">zur Nachbearbeitung offen</span>'
            )
        else:
            status_pill = '<span class="pill off">bereit zur Prüfung</span>'
        srow("Bearbeitungsstatus", status_pill)
        srow(
            "Vorgangsübergabe",
            {
                "ok": '<span class="pill ok">Vorgang übergeben</span>',
                "fail": '<span class="pill bad">Übergabe fehlgeschlagen</span>',
                "off": '<span class="pill off">nur lokal erfasst</span>',
            }[ss.crm_status],
        )

        st.markdown(
            """
<div class="next-step">
  <b>Ablauf nach der Prüfung:</b><br>
  1. Fläche &amp; Annahmen prüfen · 2. Fotos/Pläne ergänzen · 3. Vor-Ort-Check klären ·
  4. Förder- &amp; Gebührenlage prüfen · 5. Fachbetriebskoordination · 6. Unterlagen sichern
</div>
""",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        uploads = st.file_uploader(
            "Unterlagen ergänzen (Fotos, Lagepläne, PDF – zweckgebunden)",
            type=["png", "jpg", "jpeg", "pdf"],
            accept_multiple_files=True,
        )
        if uploads:
            bilder = [u for u in uploads if u.type.startswith("image/")]
            st.caption(f"{len(uploads)} Datei(en) · {len(bilder)} Foto(s) · {len(uploads) - len(bilder)} PDF(s)")
            if bilder:
                st.image(bilder[:4], width=90)
        if DRIVE_FOLDER_URL:
            st.link_button("📂 Projektordner öffnen", DRIVE_FOLDER_URL)
        else:
            st.button("📂 Projektordner öffnen", disabled=True, help="DRIVE_FOLDER_URL nicht gesetzt.")


# ==============================================================================
# 8. STEP 3 – KENNzahlen JE ZIELGRUPPE + PRÜFBERICHT (PDF)
# ==============================================================================
def _pdf_text(val) -> str:
    ersetzungen = {
        "€": "EUR",
        "²": "2",
        "³": "3",
        "–": "-",
        "—": "-",
        "·": "-",
        "•": "-",
        "®": "(R)",
        "≥": ">=",
        "≤": "<=",
        "÷": "/",
        "„": '"',
        "“": '"',
        "”": '"',
        "’": "'",
        "‘": "'",
        "\u00a0": " ",
    }
    s = str(val if val is not None else "")
    for alt, neu in ersetzungen.items():
        s = s.replace(alt, neu)
    return s.encode("latin-1", "replace").decode("latin-1")


def baue_pdf() -> bytes:
    pdf = FPDF()
    pdf.add_page()
    font_candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]
    fam = "Helvetica"
    t = _pdf_text
    for fp, bp in font_candidates:
        if os.path.exists(fp) and os.path.exists(bp):
            try:
                pdf.add_font("DV", "", fp)
                pdf.add_font("DV", "B", bp)
                fam = "DV"
                t = lambda val: str(val if val is not None else "")
                break
            except Exception:
                fam = "Helvetica"
                t = _pdf_text

    pdf.set_fill_color(15, 118, 110)
    pdf.rect(0, 0, 210, 6, "F")
    pdf.set_y(14)
    pdf.set_font(fam, "B", 9)
    pdf.set_text_color(15, 118, 110)
    pdf.cell(0, 5, t("FLÄCHENRADAR NI · PRÜF- & ENTSCHEIDUNGSWERKZEUG"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(fam, "B", 17)
    pdf.set_text_color(15, 41, 66)
    pdf.cell(0, 9, t("Vorprüfbericht Entsiegelung & Einordnung"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(fam, "", 9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(
        0,
        5,
        t(
            f"Kennung: {ss.system_id or 'Entwurf'} · Modus: {aktiv_modus['label']} · "
            f"Erstellt: {datetime.now():%d.%m.%Y %H:%M}"
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)

    def block(titel, zeilen):
        pdf.set_font(fam, "B", 11)
        pdf.set_text_color(15, 41, 66)
        pdf.cell(0, 8, t(titel), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(216, 225, 235)
        for k, v in zeilen:
            pdf.set_font(fam, "", 10)
            pdf.set_text_color(71, 85, 105)
            pdf.cell(88, 7, t(k), border="B")
            pdf.set_text_color(15, 41, 66)
            pdf.cell(0, 7, t(v), border="B", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    block(
        "1. Objekt & Prüfumfang",
        [
            ("Träger / Kunde", firma or "–"),
            ("Gemeinde / PLZ", f"{gemeinde} · {plz}"),
            ("Lage / Adresse / Flurstück", strasse or "–"),
            ("Geprüfte Fläche", f"{zahl(flaeche)} m² ({zahl(flaeche / 10_000, 2)} ha)"),
            ("Belag / Nutzungsart", f"{belag} / {nutzung}"),
        ],
    )
    fs = ss.flurstueck
    if fs:
        block(
            "2. Landeskataster (Entsiegelungskataster.NI)",
            [
                ("Flurstückskennzeichen", fs["Fsk"]),
                ("ALKIS-Nutzung", fs["Nutzung"]),
                ("Flurstücksfläche", f"{zahl(ek.num(fs['FlstFl_m2']))} m²"),
                ("Versiegelungsanteil", f"{fs['VerAnt_pct']} %"),
                ("Landes-Entsiegelungspotenzial", f"{zahl(fs['EntFl'])} m²"),
                ("Potenzialstufe", fs["EntPot"]),
                ("Einordnung", fs["PreCheck"]),
            ],
        )
    block(
        "3. Vorläufige Kosten-, Förder- & Gebühreneinschätzung",
        [
            ("Richtwert Quadratmeterpreis", f"{eur(preis_m2, 2)} / m²"),
            ("Investitionsrahmen (ca. +/-15 %)", eur_spanne(kosten)),
            ("Förderkulisse / Ansatzquote", f"{programm} · {zahl(eff_quote)} %"),
            ("Fördercode", kulisse_info.get("code", "–")),
            ("Voraussichtlicher Zuschuss", eur(zuschuss)),
            ("Vorläufiger Netto-Eigenanteil", eur(eigenanteil)),
            (
                "Niederschlagswassergebühr",
                f"{zahl(gebuehr_satz, 2)} €/m²·a" if gebuehr_satz > 0 else "kein Satz hinterlegt",
            ),
            ("Rechnerische Gebührenentlastung / Jahr", eur(ersparnis)),
            (
                "Grobe Amortisationsrichtung",
                "entfällt mangels Gebührensatz" if math.isinf(amortisation) else f"ca. {zahl(amortisation, 1)} Jahre",
            ),
        ],
    )

    pdf.set_font(fam, "B", 10)
    pdf.set_text_color(15, 41, 66)
    pdf.cell(0, 7, t("4. Nächste Schritte"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(fam, "", 9)
    pdf.set_text_color(71, 85, 105)
    for schritt in [
        "1. Fläche, Nutzung und Landesdaten mit den örtlichen Gegebenheiten abgleichen.",
        "2. Unterlagen (Fotos, Lageplan, Entwässerung/Leitungen) bei Bedarf ergänzen.",
        "3. Vor-Ort-Prüfung sowie Förder- und Gebührenlage verbindlich klären.",
        "4. Abstimmung & Koordination über DEMA Vertrieb GbR; Ausführung über Fachbetriebe.",
    ]:
        pdf.multi_cell(0, 5, t(schritt), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font(fam, "B", 10)
    pdf.set_text_color(15, 41, 66)
    pdf.cell(0, 7, t("5. Hinweise, Grenzen & Verortung"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(fam, "", 8.5)
    pdf.set_text_color(100, 116, 139)
    for h in hinweise:
        pdf.multi_cell(0, 4.5, t(f"- {h}"), new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(
        0,
        4.5,
        t(
            f"Katasterquelle: {ek.QUELLE} (downloads.entsiegelungskataster.niedersachsen.de) · "
            f"Gebührenhinweis: {g_info['hinweis']} ({g_info['quelle']}). "
            "Ein Angebot der DEMA Vertrieb GbR (Beratung, Vorprüfung & Koordination; keine Planungs-, "
            "Rechts- oder Förderzusage; DSGVO-konforme, zweckgebundene Datenverarbeitung)."
        ),
    )
    return bytes(pdf.output())


with col3:
    with st.container(key="card3"):
        st.markdown(
            '<div class="step">Schritt 3 · Kennzahlen &amp; Einordnung</div>'
            f'<div class="step-title">Auswertung ({aktiv_modus["label"]})</div>',
            unsafe_allow_html=True,
        )

        if ss.zielgruppe == "B2G":
            kpi(
                "Prüffläche im Fokus",
                f"{zahl(flaeche)} m² ({zahl(flaeche / 10_000, 2)} ha)",
                f"Nutzung: {nutzung} · Belag: {belag}",
                cls="accent",
            )
            kpi(
                "Vorläufiger Investitionsrahmen",
                eur_spanne(kosten),
                f"Richtwert {eur(preis_m2, 2)}/m² · vorbehaltlich Planung & Vergabe",
            )
            kpi(
                "Mögliche Förderkulisse (Richtwert)",
                f"{zahl(eff_quote)} % · {eur(zuschuss)}",
                f"{programm} · vorläufig, keine Förderzusage",
            )
        elif ss.zielgruppe == "B2B":
            kpi(
                "Voraussichtlicher Zuschuss / Quote",
                f"{eur(zuschuss)} ({zahl(eff_quote)} %)",
                f"Vorläufig, förderabhängig · {programm}",
                cls="accent",
            )
            kpi(
                "Vorläufiger Netto-Eigenanteil",
                eur(eigenanteil),
                f"Investitionsrahmen ca. {eur_spanne(kosten)} · Betrieb bleibt nutzbar",
            )
            kpi(
                "Richtwert Kalkulation",
                f"{eur(preis_m2, 2)} / m²",
                f"{zahl(flaeche)} m² · {belag} → durchlässiger Belag",
            )
        else:
            kpi(
                "Geprüfte Fläche",
                f"{zahl(flaeche)} m²",
                "Regenwasser kann vor Ort versickern; Nutzung & Zustand vor Ort prüfen",
                cls="accent",
            )
            kpi(
                "Voraussichtlicher Kostenrahmen",
                eur_spanne(kosten),
                f"Unverbindliche Spanne für {belag} und Einbau inkl. Nebenarbeiten",
            )
            kpi(
                "Möglicher Förderanteil (Richtwert)",
                f"{zahl(eff_quote)} % (ca. {eur(zuschuss)})",
                "Förderfähigkeit vorab prüfen; keine Zusage",
            )

        k1, k2 = st.columns(2)
        with k1:
            if gebuehr_satz > 0:
                kpi("Gebührenentlastung / Jahr", eur(ersparnis), f"bei {zahl(gebuehr_satz, 2)} €/m²·a")
            else:
                kpi("Gebührenentlastung / Jahr", "kein Satz", f"{gemeinde}: kein Gebührensatz", cls="muted")
        with k2:
            kpi(
                "Grobe Amortisation",
                "entfällt" if math.isinf(amortisation) else f"ca. {zahl(amortisation, 1)} J.",
                "rein rechnerisch über Gebühr",
                cls="muted" if math.isinf(amortisation) else "",
            )

        for h in hinweise[:-1]:
            st.warning(h, icon="⚠️")
        st.caption("ℹ️ " + hinweise[-1])
        st.download_button(
            "📄 PRÜFBERICHT (PDF) HERUNTERLADEN",
            data=baue_pdf(),
            file_name=f"Pruefbericht_{ss.system_id or gemeinde}.pdf",
            mime="application/pdf",
        )

if scan_triggered:
    msg = {
        "ok": "Vorgang an Zielsystem übergeben.",
        "fail": "Vorgangsübergabe fehlgeschlagen – lokal erfasst.",
        "off": "Kein Ziel-Webhook hinterlegt – Vorgang lokal erfasst.",
    }[ss.crm_status]
    (st.success if ss.crm_status == "ok" else st.info)(
        f"Prüfung erfasst · Kennung {ss.system_id} · {msg}"
    )

# ==============================================================================
# 9. STEP 4 – FLÄCHENÜBERSICHT & GEMEINDEVERGLEICH
# ==============================================================================
st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
with st.container(key="card4"):
    st.markdown(
        '<div class="step">Schritt 4 · Flächenübersicht &amp; Vergleich</div>'
        '<div class="step-title">Prüfflächen &amp; Gemeindevergleich</div>',
        unsafe_allow_html=True,
    )
    tab1, tab2 = st.tabs([f"Flächenübersicht {gemeinde}", "Gemeindevergleich"])

    with tab1:
        anfragen = [f["properties"] for f in feats if f["properties"]["PreCheck"] in ("A", "B")]
        if anfragen:
            df = pd.DataFrame(
                [
                    {
                        "Einordnung": p["PreCheck"],
                        "Flurstück": p["Flurstueck"],
                        "Kennzeichen": p["Fsk"],
                        "Ortsteil": p["Gmd"],
                        "Nutzung": p["Nutzung"],
                        "Potenzialstufe": p["EntPot"],
                        "Versiegelt %": p["VerAnt_pct"],
                        "Landes-Potenzial m²": p["EntFl"],
                        "Kostenrahmen ca. €": round(p["EntFl"] * preis_m2, -2),
                        "Gebühreneffekt €/a": round(p["EntFl"] * gebuehr_satz),
                    }
                    for p in anfragen
                ]
            )
            a, b, c = st.columns(3)
            a.metric("Priorität A (hoch)", zahl((df["Einordnung"] == "A").sum()))
            b.metric("Priorität B (prüfen)", zahl((df["Einordnung"] == "B").sum()))
            c.metric(
                "Landes-Potenzial (Priorität A)",
                f"{zahl(df.loc[df['Einordnung'] == 'A', 'Landes-Potenzial m²'].sum() / 10_000, 1)} ha",
            )
            filt = st.multiselect("Einordnung filtern", ["A", "B"], default=["A"])
            dfa = df[df["Einordnung"].isin(filt)]
            st.dataframe(
                dfa,
                use_container_width=True,
                hide_index=True,
                height=320,
                column_config={
                    "Landes-Potenzial m²": st.column_config.NumberColumn(format="%d"),
                    "Kostenrahmen ca. €": st.column_config.NumberColumn(format="%d €"),
                    "Gebühreneffekt €/a": st.column_config.NumberColumn(format="%d €"),
                },
            )
            sel = {p["Fsk"] for p in anfragen if p["PreCheck"] in filt}
            gj = {
                "type": "FeatureCollection",
                "name": f"FlaechenRadar_Flaechen_{gemeinde}",
                "attribution": ek.QUELLE,
                "features": [f for f in feats if f["properties"]["Fsk"] in sel],
            }
            e1, e2 = st.columns(2)
            e1.download_button(
                "⬇ Übersicht als CSV exportieren",
                dfa.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                file_name=f"FlaechenRadar_{gemeinde}.csv",
                mime="text/csv",
            )
            e2.download_button(
                "⬇ Flächen als GeoJSON (GIS / Kommune)",
                json.dumps(gj, ensure_ascii=False).encode(),
                file_name=f"FlaechenRadar_{gemeinde}.geojson",
                mime="application/geo+json",
            )
            st.caption(
                "Hinweis: Das Kataster weist Flurstücke ohne Eigentümerangaben aus. "
                "Eigentums- und Ortsangaben sind bei Bedarf vor Ort bzw. über zuständige Stellen zu klären."
            )
        else:
            st.info("Für die aktuelle Filterauswahl liegen keine Flächen in Priorität A oder B vor.")

    with tab2:
        auswahl = st.multiselect(
            "Gemeinden vergleichen",
            gemeinden,
            default=[g for g in REGION_WERLTE if g in gemeinden],
        )
        if st.button("Gemeindevergleich berechnen", type="secondary"):
            ss.vergleich = auswahl
        if ss.get("vergleich"):
            rows = []
            prog = st.progress(0.0, text="Katasterdaten werden ausgewertet …")
            for i, g in enumerate(ss.vergleich):
                try:
                    _, s = entpot(g)
                except Exception:
                    continue
                gi = gebuehr(g)
                rows.append(
                    {
                        "Gemeinde": g,
                        "Flurstücke": s["flurstuecke"],
                        "Stufe 5": s["stufe"][5],
                        "Stufe 4": s["stufe"][4],
                        "Priorität A": s["a_leads"],
                        "Priorität B": s["b_leads"],
                        "Landes-Potenzial A (ha)": round(s["entfl_b2b_hoch"] / 10_000, 1),
                        "NW-Gebühr": (
                            f"{zahl(gi['satz'], 2)} €/m²"
                            if gi["satz"]
                            else "kein Satz hinterlegt"
                            if gi["status"] == "keine"
                            else "unbekannt"
                        ),
                        "Quelle Gebühr": gi["quelle"],
                    }
                )
                prog.progress((i + 1) / len(ss.vergleich), text=f"{g} ausgewertet")
            prog.empty()
            vdf = pd.DataFrame(rows).sort_values("Landes-Potenzial A (ha)", ascending=False)
            st.dataframe(
                vdf,
                use_container_width=True,
                hide_index=True,
                height=520,
                column_config={"Quelle Gebühr": st.column_config.LinkColumn(display_text="Satzung")},
            )
            st.download_button(
                "⬇ Vergleich als CSV exportieren",
                vdf.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                file_name="FlaechenRadar_Gemeindevergleich.csv",
                mime="text/csv",
            )

st.markdown(
    f"""<div class="fr-foot">
<b>FlächenRadar NI</b> · Ein Angebot der <b>DEMA Vertrieb GbR</b> (Beratung, Vorprüfung &amp; Koordination; Ausführung über Fachbetriebe).<br>
Unverbindliche, vorläufige Einschätzung – keine verbindliche Planung, Baugenehmigung, Förderzusage oder Preisgarantie.<br>
Katastergrundlage: {ek.QUELLE} · <a href="https://downloads.entsiegelungskataster.niedersachsen.de/" target="_blank">Entsiegelungskataster.NI</a> ·
Gebührenstand: 11.10.2026 (im Parameterbereich anpassbar).<br>
Kriterien (aktuell): Priorität A ≥ Stufe {pc_a_stufe} + ≥ {zahl(pc_a_fl)} m² · Priorität B ≥ Stufe {pc_b_stufe} + ≥ {zahl(pc_b_fl)} m².<br>
Datenschutz: Eingaben und Uploads werden zweckgebunden zur Prüfung verwendet.
</div>""",
    unsafe_allow_html=True,
)

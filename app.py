"""
FlächenRadar NI – Digitale Flächen- & Entsiegelungsanalyse
Version 3.4 (Förderrichtlinien NI Nov 2026 · KfW 444 / NBank / KliKoNi · Mobil-gestapelt)
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
from shapely.geometry import mapping as _mapping
from shapely.geometry import shape as _shape
from streamlit_folium import st_folium

import kataster as ek
from gebuehren import FOERDER_KULISSE_NI, REGION_WERLTE, gebuehr

st.set_page_config(
    page_title="FlächenRadar NI · Flächen- & Entsiegelungsanalyse",
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
KARTE_MAX_FLURSTUECKE = 120

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

KULISSE_KEYS = list(FOERDER_KULISSE_NI.keys())
DEFAULT_KULISSE_MODUS = {
    "B2G": KULISSE_KEYS[0],   # KfW 444 NKK – Modul D.2 (50 %)
    "B2B": KULISSE_KEYS[-1],  # Kein Landesprogramm / Lokale Prüfung (0 %)
    "B2C": KULISSE_KEYS[-1],  # Kein Landesprogramm / Lokale Prüfung (0 %)
}

MODUS_META = {
    "B2G": {
        "nav": "B2G · Kommune",
        "label": "Kommune (B2G)",
        "kurz": "Kommunale Flächen- & Entsiegelungsanalyse (§ 19 NKlimaG · Pflichtfrist 31.12.2026)",
        "titel": "Welche Flächen im Gemeindegebiet bieten ein prüfenswertes Entsiegelungspotenzial?",
        "hinweis": (
            "Unterstützt Erfassung, Priorisierung und Vorlagenbildung auf Basis des Entsiegelungskatasters.NI "
            "(§ 19 NKlimaG, Ersterfassung bis 31.12.2026). Vorläufige Einschätzung – ersetzt keine Fachplanung oder Förderprüfung."
        ),
        "b2b_default": True,
        "default_nutzung": "Geh- und Radweg",
    },
    "B2B": {
        "nav": "B2B · Gewerbe",
        "label": "Gewerbe & Eigentümer (B2B)",
        "kurz": "Wirtschaftlichkeit, Gebührenlage, Starkregenvorsorge & Erhalt der Nutzbarkeit",
        "titel": "Wie tragfähig ist eine Entsiegelung oder Teilentsiegelung auf Ihrer Betriebs- oder Objektfläche?",
        "hinweis": (
            "Vorläufige Richtwertprüfung zu Investitionsrahmen, möglichem Gebühreneffekt und Nutzbarkeit. "
            "In Niedersachsen besteht aktuell kein flächendeckendes Landesprogramm für Gewerbeflächen – lokale Programme prüfen."
        ),
        "b2b_default": True,
        "default_nutzung": "Gewerbefläche / Parkplatz",
    },
    "B2C": {
        "nav": "B2C · Privat",
        "label": "Privat (B2C)",
        "kurz": "Einfache Ersteinschätzung für Hof, Einfahrt und private Flächen",
        "titel": "Welche Entsiegelungs- oder Versickerungsmöglichkeiten passen zu Ihrer Fläche?",
        "hinweis": (
            "Unverbindliche Ersteinschätzung mit realistischem Kostenrahmen und Fokus auf Versickerung, "
            "Starkregenvorsorge und Kühlung. Auf Landesebene existiert derzeit keine private Entsiegelungsförderung (0 % Standard)."
        ),
        "b2b_default": False,
        "default_nutzung": "Hoffläche",
    },
}

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
    "kulisse_sel": DEFAULT_KULISSE_MODUS["B2G"],
    "cache_hinweis_shown": False,
}.items():
    ss.setdefault(k, v)


def setze_modus(m: str):
    ss.zielgruppe = m
    ss.nutzung_sel = MODUS_META[m]["default_nutzung"]
    ss.kulisse_sel = DEFAULT_KULISSE_MODUS[m]


def uebernehme_polygon():
    if ss.polygon_m2 > 0:
        ss.flaeche = int(round(ss.polygon_m2))
        ss.flurstueck = None


def uebernehme_flurstueck(props):
    ss.flurstueck = props
    ss.flaeche = int(props["EntFl"])
    ss.adresse = props["Flurstueck"]
    ss.nutzung_sel = ALKIS_ZU_NUTZUNG.get(props.get("HauptTN"), "Sonstige")


dark = bool(ss.nachtmodus)
if dark:
    bg_app = "#0B1220"
    card_bg = "#131D31"
    kpi_bg = "#0E1626"
    border_col = "#2A3B58"
    text_main = "#F8FAFC"
    text_muted = "#CBD5E1"
    text_sub = "#94A3B8"
    accent_col = "#14B8A6"
    accent_text_btn = "#06201D"
    accent_soft = "#112E2B"
    accent_val = "#5EEAD4"
    map_tiles = "CartoDB dark_matter"
else:
    bg_app = "#F4F6F9"
    card_bg = "#FFFFFF"
    kpi_bg = "#F8FAFC"
    border_col = "#CBD5E1"
    text_main = "#0F172A"
    text_muted = "#1E293B"
    text_sub = "#475569"
    accent_col = "#0F766E"
    accent_text_btn = "#FFFFFF"
    accent_soft = "#E6F4F1"
    accent_val = "#0F766E"
    map_tiles = "CartoDB positron"

st.markdown(
    f"""
<style>
#MainMenu, footer, header[data-testid="stHeader"] {{visibility:hidden; height:0;}}
.block-container {{padding-top:0.8rem; padding-bottom:2rem; max-width:1380px;}}
.stApp {{background:{bg_app}; color:{text_main};}}
.stApp p, .stApp label, .stApp span, .stApp li, .stApp h1, .stApp h2, .stApp h3 {{color:{text_main};}}

.fr-header {{
  background:{card_bg}; border:1px solid {border_col}; border-radius:12px;
  padding:14px 16px; margin-bottom:12px;
  display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:10px;
}}
.fr-brand-kicker {{font-size:11px; font-weight:800; letter-spacing:.12em; color:{accent_col} !important; text-transform:uppercase;}}
.fr-brand-title {{font-size:20px; font-weight:800; color:{text_main} !important; margin:2px 0 0 0; line-height:1.25;}}
.fr-seal {{
  background:{kpi_bg}; border:1px solid {border_col}; border-left:4px solid {accent_col};
  border-radius:8px; padding:8px 12px; font-size:12px; color:{text_muted} !important; line-height:1.45;
}}
.fr-seal b {{color:{text_main} !important;}}

.fr-mode-banner {{
  background:{card_bg}; border:1px solid {border_col}; border-radius:12px;
  padding:14px 16px; margin-bottom:14px;
}}
.fr-mode-title {{font-size:16px; font-weight:750; color:{text_main} !important; margin:4px 0;}}
.fr-mode-desc {{font-size:13px; color:{text_muted} !important; margin:0; line-height:1.5;}}

.st-key-card1, .st-key-card2, .st-key-card3, .st-key-card4 {{
  background:{card_bg}; border:1px solid {border_col}; border-radius:12px;
  padding:16px; margin-bottom:12px;
}}
.step {{font-size:11px; letter-spacing:.12em; color:{accent_col} !important; font-weight:800; text-transform:uppercase;}}
.step-title {{font-size:17px; color:{text_main} !important; font-weight:750; margin:2px 0 12px 0;}}

.kpi {{
  background:{kpi_bg}; border:1px solid {border_col}; border-radius:10px;
  padding:12px 14px; margin-bottom:10px;
}}
.kpi .l {{font-size:11px; color:{text_sub} !important; text-transform:uppercase; letter-spacing:.06em; font-weight:700;}}
.kpi .v {{font-size:20px; color:{text_main} !important; font-weight:800; font-variant-numeric:tabular-nums; margin-top:3px;}}
.kpi .h {{font-size:12px; color:{text_muted} !important; margin-top:3px; line-height:1.35;}}
.kpi.accent {{border-color:{accent_col}; background:{accent_soft};}}
.kpi.accent .v {{color:{accent_val} !important;}}

.srow {{
  display:flex; justify-content:space-between; align-items:center; gap:10px;
  padding:8px 0; border-bottom:1px dashed {border_col}; font-size:13px;
}}
.srow .k {{color:{text_muted} !important;}}
.srow .val {{color:{text_main} !important; font-weight:700; text-align:right; font-size:12.5px;}}

.pill {{display:inline-block; padding:2px 9px; border-radius:999px; font-size:11.5px; font-weight:700; white-space:nowrap;}}
.pill.ok {{background:#DCFCE7; color:#14532D !important;}}
.pill.warn {{background:#FEF3C7; color:#78350F !important;}}
.pill.bad {{background:#FEE2E2; color:#7F1D1D !important;}}
.pill.off {{background:#E2E8F0; color:#1E293B !important;}}

.flst {{
  background:{accent_soft}; border:1px solid {accent_col}; border-radius:10px;
  padding:10px 12px; margin:8px 0; font-size:12.5px; color:{text_main} !important; line-height:1.45;
}}
.next-step {{
  background:{kpi_bg}; border:1px solid {border_col}; border-radius:10px;
  padding:10px 12px; margin-top:10px; font-size:12.5px; color:{text_main} !important; line-height:1.45;
}}
.stButton>button, .stDownloadButton>button, .stLinkButton>a {{
  width:100%; border-radius:8px !important; font-weight:700 !important; min-height:42px;
  color:{text_main} !important; border-color:{border_col} !important; background:{card_bg} !important;
}}
.stButton>button[kind="primary"] {{
  background:{accent_col} !important; border-color:{accent_col} !important; color:{accent_text_btn} !important;
}}
.fr-foot {{
  font-size:12px; color:{text_muted} !important; background:{card_bg};
  border:1px solid {border_col}; border-radius:12px;
  margin-top:18px; padding:14px 16px; line-height:1.55;
}}

@media (max-width: 768px) {{
  div[data-testid="stHorizontalBlock"] {{
    flex-direction: column !important;
    gap: 10px !important;
  }}
  div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
    width: 100% !important;
    flex: 1 1 100% !important;
  }}
  .fr-brand-title {{font-size:18px;}}
  .fr-seal {{width:100%;}}
}}
</style>
""",
    unsafe_allow_html=True,
)


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


@st.cache_data(show_spinner=False, max_entries=30)
def karten_geojson(gemeinde: str, min_stufe: int, nur_b2b: bool, limit: int):
    feats, _ = entpot(gemeinde)
    gefiltert = [
        f
        for f in feats
        if f["properties"]["Stufe"] >= min_stufe
        and (not nur_b2b or f["properties"]["HauptTN"] in ek.B2B_NUTZUNGEN)
    ][:limit]
    leichte_features = []
    for f in gefiltert:
        geom = _shape(f["geometry"]).simplify(0.000015, preserve_topology=True)
        props = f["properties"]
        leichte_features.append(
            {
                "type": "Feature",
                "geometry": _mapping(geom),
                "properties": {
                    "Flurstueck": props["Flurstueck"],
                    "Nutzung": props["Nutzung"],
                    "EntFl": props["EntFl"],
                    "VerAnt_pct": props["VerAnt_pct"],
                    "EntPot": props["EntPot"],
                    "Stufe": props["Stufe"],
                },
            }
        )
    center = (52.85, 7.67)
    if leichte_features:
        c = _shape(leichte_features[0]["geometry"]).centroid
        center = (c.y, c.x)
    return {"type": "FeatureCollection", "features": leichte_features}, len(leichte_features), center


# Expliziter Header mit direkten Navigationspfaden (B2G / B2B / B2C)
nav_cols = st.columns([1, 1, 1, 0.9], gap="small")
for idx, m_key in enumerate(["B2G", "B2B", "B2C"]):
    with nav_cols[idx]:
        if st.button(
            MODUS_META[m_key]["nav"],
            key=f"nav_{m_key}",
            type="primary" if ss.zielgruppe == m_key else "secondary",
        ):
            setze_modus(m_key)
with nav_cols[3]:
    ss.nachtmodus = st.toggle("Nachtmodus", value=ss.nachtmodus)

aktiv_modus = MODUS_META[ss.zielgruppe]
pruef_stand = ss.system_id or "Entwurf (ohne Scan)"

st.markdown(
    f"""
<div class="fr-header">
  <div>
    <div class="fr-brand-kicker">FLÄCHENRADAR NI · DIGITALE FLÄCHENANALYSE</div>
    <div class="fr-brand-title">Entsiegelungs- &amp; Klimaanpassungs-Radar</div>
  </div>
  <div class="fr-seal">
    <b>Prüfsiegel</b> · Kennung: <b>{pruef_stand}</b><br>
    Pfad: <b>{aktiv_modus["label"]}</b> · Stand: {datetime.now():%d.%m.%Y}
  </div>
</div>
<div class="fr-mode-banner">
  <div class="fr-brand-kicker">{aktiv_modus["label"]} · {aktiv_modus["kurz"]}</div>
  <div class="fr-mode-title">{aktiv_modus["titel"]}</div>
  <p class="fr-mode-desc">{aktiv_modus["hinweis"]}</p>
</div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Parameter & Kriterien")
    pc_a_stufe = st.slider("Priorität A: min. Potenzialstufe", 3, 5, DEFAULT_PRECHECK_A_STUFE, key="pc_a_stufe")
    pc_a_fl = st.number_input("Priorität A: min. Fläche (m²)", 100, 5000, DEFAULT_PRECHECK_A_FL, step=100, key="pc_a_fl")
    pc_b_stufe = st.slider("Priorität B: min. Potenzialstufe", 2, 5, DEFAULT_PRECHECK_B_STUFE, key="pc_b_stufe")
    pc_b_fl = st.number_input("Priorität B: min. Fläche (m²)", 50, 2000, DEFAULT_PRECHECK_B_FL, step=50, key="pc_b_fl")
    max_karte = st.slider("Max. Flurstücke auf Karte", 50, 300, KARTE_MAX_FLURSTUECKE, step=25)

try:
    KATALOG = katalog()
    kat_ok = True
except Exception:
    KATALOG, kat_ok = {}, False

col1, col2, col3 = st.columns([1.25, 1, 1], gap="medium")

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
            try:
                feats, kstat = entpot(gemeinde)
                if not ss.cache_hinweis_shown:
                    st.info(
                        "Katasterdaten werden je Gemeinde einmalig geladen und in der Cloud-Umgebung "
                        "vorläufig zwischengespeichert.",
                        icon="ℹ️",
                    )
                    ss.cache_hinweis_shown = True
            except Exception as e:
                st.error(f"Katasterdaten konnten nicht geladen werden: {e}")

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
            else "Nur gewerbliche/öffentliche Nutzungen zeigen (aus = alle Flächen)"
        )
        nur_b2b = st.toggle(filter_label, value=aktiv_modus["b2b_default"], key="toggle_b2b")
        gj_karte, anzahl_sicht, default_center = karten_geojson(gemeinde, min_stufe, nur_b2b, max_karte)

        fs_geom = None
        if ss.flurstueck:
            fs_geom = next(
                (f["geometry"] for f in feats if f["properties"]["Fsk"] == ss.flurstueck["Fsk"]),
                None,
            )
        if fs_geom:
            c = _shape(fs_geom).centroid
            center, zoom = (c.y, c.x), 17
        elif anzahl_sicht > 0:
            center, zoom = default_center, 14
        else:
            center, zoom = (52.85, 7.67), 12

        m = folium.Map(location=center, zoom_start=zoom, tiles=map_tiles, control_scale=True)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri World Imagery",
            name="Luftbild (Orthophoto)",
        ).add_to(m)
        if anzahl_sicht > 0:
            folium.GeoJson(
                gj_karte,
                name="Landes-Entsiegelungspotenzial",
                style_function=lambda f: {
                    "color": STUFEN_FARBE.get(f["properties"]["Stufe"], "#64748B"),
                    "weight": 1.3,
                    "fillOpacity": 0.35,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["Flurstueck", "Nutzung", "EntFl", "VerAnt_pct", "EntPot"],
                    aliases=["Flurstück", "Nutzung", "Landes-Potenzial (m²)", "Versiegelt (%)", "Stufe"],
                ),
            ).add_to(m)
        folium.LayerControl(position="topright").add_to(m)
        Draw(
            export=False,
            position="topleft",
            draw_options={"polyline": False, "circle": False, "marker": False, "circlemarker": False},
            edit_options={"edit": True, "remove": True},
        ).add_to(m)

        st.caption(f"{anzahl_sicht} Flurstücke angezeigt (max. {max_karte}). Fläche anklicken oder einzeichnen.")
        out = st_folium(
            m,
            height=290,
            use_container_width=True,
            returned_objects=["last_object_clicked", "all_drawings"],
            key=f"map_{gemeinde}",
        )

        klick = (out or {}).get("last_object_clicked")
        treffer = index_fuer(gemeinde).finde(klick["lng"], klick["lat"]) if (klick and feats) else None
        if treffer:
            p = treffer["properties"]
            st.markdown(
                f'<div class="flst"><b>{p["Flurstueck"]}</b> · {p["Gmd"]}<br>'
                f'Nutzung: {p["Nutzung"]} · Flurstück: {zahl(ek.num(p["FlstFl_m2"]))} m² · '
                f'Versiegelungsanteil: {p["VerAnt_pct"]} %<br>'
                f'<b>Landes-Entsiegelungspotenzial: {zahl(p["EntFl"])} m²</b> ({p["EntPot"]})</div>',
                unsafe_allow_html=True,
            )
            st.button("Flurstück für Prüfung übernehmen", on_click=uebernehme_flurstueck, args=(p,))

        drawings = (out or {}).get("all_drawings") or []
        ss.polygon_m2 = sum(
            polygon_flaeche_m2(f["geometry"]["coordinates"][0])
            for f in drawings
            if f.get("geometry", {}).get("type") == "Polygon"
        )
        if ss.polygon_m2 > 0:
            st.button(f"Eingezeichnete Fläche übernehmen ({zahl(ss.polygon_m2)} m²)", on_click=uebernehme_polygon)

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
            "Förderkulisse (Stand Nov. 2026 – vorläufig)",
            KULISSE_KEYS,
            key="kulisse_sel",
        )
        kulisse_info = FOERDER_KULISSE_NI[kulisse_label]
        c, d = st.columns(2)
        belag = c.selectbox("Vorhandener Belag", list(DEFAULT_RUECKBAU_EUR_M2))
        nutzung = d.selectbox("Nutzungsart", list(NUTZUNGS_FAKTOR), key="nutzung_sel")
        flaeche = st.number_input("Prüffläche (m²)", min_value=0, step=50, key="flaeche")

        scan_triggered = st.button(
            "▶ PRÜFUNG & ERSTEINSCHÄTZUNG STARTEN",
            type="primary",
            disabled=(flaeche < MINDEST_FLAECHE_M2 or not plz_ok),
        )
        if flaeche < MINDEST_FLAECHE_M2:
            st.warning(f"Prüfung erst ab {MINDEST_FLAECHE_M2} m² sinnvoll (aktuell: {flaeche} m²).")

g_info = gebuehr(gemeinde)
with st.expander("Annahmen, Förderquote & Richtwerte offenlegen"):
    p1, p2, p3, p4 = st.columns(4)
    pu_preis = p1.number_input("Wasserdurchlässiger Belag (€/m²)", value=DEFAULT_PU_ASPHALT_EUR_M2, step=1.0)
    rueckbau = p2.number_input(f"Rückbau {belag} (€/m²)", value=DEFAULT_RUECKBAU_EUR_M2[belag], step=1.0)
    unterbau = p3.number_input(f"Unterbau {belag} (€/m²)", value=DEFAULT_UNTERBAU_EUR_M2[belag], step=1.0)
    gebuehr_satz = p4.number_input(
        f"NW-Gebühr {gemeinde} (€/m²·a)",
        value=float(g_info["satz"] or 0.0),
        step=0.05,
        key=f"geb_{gemeinde}",
    )
    foerder_quote_manuell = st.number_input(
        "Angenommene Förderquote (%)",
        0,
        100,
        int(kulisse_info["quote_default"]),
        key=f"quote_{kulisse_info['code']}",
        help=f"Regelförderung der Kulisse: {kulisse_info['quote_default']} % (max. {kulisse_info['quote_max']} %).",
    )
    st.info(f"**{kulisse_info['code']}** · {kulisse_info['traeger']}: {kulisse_info['hinweis']}")

preis_m2 = (pu_preis + rueckbau + unterbau) * NUTZUNGS_FAKTOR[nutzung]
kosten = flaeche * preis_m2
hinweise = []
programm = kulisse_label
quote = float(foerder_quote_manuell)
zuschuss = kosten * quote / 100 if quote > 0 else 0.0
max_k = kulisse_info.get("max_kosten_eur")
if max_k and kosten > max_k and quote > 0:
    zuschuss = max_k * quote / 100
    hinweise.append(f"Förderfähige Kosten auf Programm-Obergrenze ({eur(max_k)}) gedeckelt.")

if "KfW 444" in kulisse_info["code"]:
    hinweise.append(
        "KfW 444 Pflichtkriterien: Vollständige Entkopplung von der Kanalisation (Versickerung vor Ort), "
        "keine Altlastensanierung als Hauptzweck, Antrag zwingend vor Maßnahmenbeginn (Frist: 31.12.2026)."
    )
elif "KliKoNi" in kulisse_info["code"]:
    hinweise.append("KliKoNi (2026–2028) befindet sich in Ausarbeitung – Fördersätze nach Richtlinienstart prüfen.")
elif quote == 0:
    hinweise.append(
        "Keine automatische Landesförderquote angesetzt – lokale kommunale Programme sowie Beratung "
        "über Kommune, NBank oder KEAN prüfen."
    )

if quote > 0 and zuschuss < BAGATELL_ZUSCHUSS_EUR:
    hinweise.append(f"Voraussichtlicher Zuschuss unter {eur(BAGATELL_ZUSCHUSS_EUR)} – Bagatellgrenzen prüfen.")
if ss.zielgruppe == "B2B" and zuschuss > DE_MINIMIS_EUR:
    hinweise.append(f"De-minimis-Obergrenze ({eur(DE_MINIMIS_EUR)}) berücksichtigt.")
    zuschuss = DE_MINIMIS_EUR
if gebuehr_satz <= 0:
    hinweise.append(
        f"Für {gemeinde} ist kein laufender Niederschlagswassergebührensatz hinterlegt – Fokus auf "
        "Starkregenvorsorge, Entwässerungsentlastung und Hitzeschutz."
    )
hinweise.append("Untergrund, Leitungen, Schutzgebiete und Versickerungsfähigkeit müssen vor Ort geprüft werden.")
hinweise.append("Vorläufige, unverbindliche Einschätzung – keine Planung, Förderzusage oder Preisgarantie.")

eigenanteil = max(0.0, kosten - zuschuss)
ersparnis = flaeche * gebuehr_satz
amortisation = eigenanteil / ersparnis if ersparnis > 0 else float("inf")
eff_quote = zuschuss / kosten * 100 if kosten else 0.0

if scan_triggered:
    ss.system_id = f"FR-{datetime.now():%Y%m%d}-{plz}-{uuid.uuid4().hex[:4].upper()}"
    ss.scan_zeit = datetime.now()
    if CRM_WEBHOOK_URL:
        try:
            payload = {
                "system_id": ss.system_id,
                "zielgruppe": ss.zielgruppe,
                "gemeinde": gemeinde,
                "flaeche_m2": flaeche,
                "programm": kulisse_info["code"],
                "kosten": round(kosten, 2),
                "zuschuss": round(zuschuss, 2),
                "quelle": "FlaechenRadar_NI_v3_4",
            }
            ss.crm_status = "ok" if requests.post(CRM_WEBHOOK_URL, json=payload, timeout=8).ok else "fail"
        except Exception:
            ss.crm_status = "fail"
    else:
        ss.crm_status = "off"

with col2:
    with st.container(key="card2"):
        st.markdown(
            '<div class="step">Schritt 2 · Förderkulisse &amp; Ablauf</div>'
            '<div class="step-title">Prüfstatus &amp; Fördercheck</div>',
            unsafe_allow_html=True,
        )
        srow("Prüfkennung", ss.system_id or "– noch nicht ausgelöst –")
        srow("Förderkulisse", kulisse_info["code"])
        srow("Befristung / Status", kulisse_info["befristung"])
        geb_pill = (
            f'<span class="pill ok">{zahl(gebuehr_satz, 2)} €/m²·a</span>'
            if gebuehr_satz > 0
            else '<span class="pill warn">kein Satz hinterlegt</span>'
        )
        srow(f"NW-Gebühr ({gemeinde})", geb_pill)
        srow(
            "Vorgangsübergabe",
            {
                "ok": '<span class="pill ok">übergeben</span>',
                "fail": '<span class="pill bad">fehlgeschlagen</span>',
                "off": '<span class="pill off">nur lokal erfasst</span>',
            }[ss.crm_status],
        )

        st.markdown("**Aktuelle Förderkulisse offiziell prüfen:**")
        l1, l2 = st.columns(2)
        with l1:
            st.link_button("🔗 KfW 444 (NKK)", "https://www.kfw.de/inlandsfoerderung/%C3%96ffentliche-Einrichtungen/Energetische-Stadtsanierung/F%C3%B6rderprodukte/Nat%C3%BCrlicher-Klimaschutz-in-Kommunen-(444)/")
        with l2:
            st.link_button("🔗 NBank & KEAN", "https://www.nbank.de/")

        st.markdown(
            """
<div class="next-step">
  <b>Ablauf nach der Prüfung:</b><br>
  1. Fläche &amp; Entkopplung prüfen · 2. Fotos/Pläne ergänzen · 3. Vor-Ort-Check &amp; Altlasten klären ·
  4. Förderantrag vor Maßnahmenbeginn stellen · 5. Fachplanung / Umsetzung anfragen
</div>
""",
            unsafe_allow_html=True,
        )
        uploads = st.file_uploader(
            "Unterlagen ergänzen (Fotos, Lagepläne, PDF)",
            type=["png", "jpg", "jpeg", "pdf"],
            accept_multiple_files=True,
        )
        if uploads:
            st.caption(f"{len(uploads)} Datei(en) ausgewählt.")
        if DRIVE_FOLDER_URL:
            st.link_button("📂 Projektordner öffnen", DRIVE_FOLDER_URL)
        else:
            st.button("📂 Projektordner öffnen", disabled=True)


def _pdf_text(val) -> str:
    ersetzungen = {"€": "EUR", "²": "2", "³": "3", "–": "-", "—": "-", "·": "-", "\u00a0": " "}
    s = str(val if val is not None else "")
    for alt, neu in ersetzungen.items():
        s = s.replace(alt, neu)
    return s.encode("latin-1", "replace").decode("latin-1")


def baue_pdf() -> bytes:
    pdf = FPDF()
    pdf.add_page()
    t = _pdf_text
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, t("FlaechenRadar NI - Vorpruefbericht"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, t(f"Kennung: {ss.system_id or 'Entwurf'} | Modus: {aktiv_modus['label']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, t(f"Gemeinde: {gemeinde} | Flaeche: {zahl(flaeche)} m2"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, t(f"Foerderkulisse: {kulisse_info['code']} ({zahl(eff_quote)} %)"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, t(f"Kostenrahmen: {eur_spanne(kosten)} | Zuschuss: {eur(zuschuss)} | Eigenanteil: {eur(eigenanteil)}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    for h in hinweise:
        pdf.multi_cell(0, 5, t(f"- {h}"), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


with col3:
    with st.container(key="card3"):
        st.markdown(
            '<div class="step">Schritt 3 · Kennzahlen &amp; Einordnung</div>'
            f'<div class="step-title">Auswertung ({aktiv_modus["label"]})</div>',
            unsafe_allow_html=True,
        )
        if ss.zielgruppe == "B2G":
            kpi("Prüffläche im Fokus", f"{zahl(flaeche)} m² ({zahl(flaeche / 10_000, 2)} ha)", f"Nutzung: {nutzung}", cls="accent")
            kpi("Vorläufiger Investitionsrahmen", eur_spanne(kosten), f"Richtwert {eur(preis_m2, 2)}/m²")
            kpi("Mögliche Förderkulisse", f"{zahl(eff_quote)} % · {eur(zuschuss)}", f"{kulisse_info['code']} · Eigenanteil ca. {eur(eigenanteil)}")
        elif ss.zielgruppe == "B2B":
            kpi("Voraussichtlicher Zuschuss", f"{eur(zuschuss)} ({zahl(eff_quote)} %)", kulisse_info["code"], cls="accent")
            kpi("Vorläufiger Netto-Eigenanteil", eur(eigenanteil), f"Rahmen {eur_spanne(kosten)}")
            kpi("Richtwert Kalkulation", f"{eur(preis_m2, 2)} / m²", f"{zahl(flaeche)} m² · {belag}")
        else:
            kpi("Geprüfte Fläche", f"{zahl(flaeche)} m²", "Regenwasser kann vor Ort versickern", cls="accent")
            kpi("Voraussichtlicher Kostenrahmen", eur_spanne(kosten), f"Für {belag} inkl. Nebenarbeiten")
            kpi("Möglicher Förderanteil", f"{zahl(eff_quote)} % (ca. {eur(zuschuss)})", "Auf Landesebene 0 % Standard – lokal prüfen")

        for h in hinweise[:-1]:
            st.warning(h, icon="⚠️")
        st.caption("ℹ️ " + hinweise[-1])
        st.download_button(
            "📄 PRÜFBERICHT (PDF) HERUNTERLADEN",
            data=baue_pdf(),
            file_name=f"Pruefbericht_{ss.system_id or gemeinde}.pdf",
            mime="application/pdf",
        )

st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
with st.container(key="card4"):
    st.markdown(
        '<div class="step">Schritt 4 · Flächenübersicht</div>'
        '<div class="step-title">Prüfflächen im Überblick</div>',
        unsafe_allow_html=True,
    )
    anfragen = [f["properties"] for f in feats if f["properties"]["PreCheck"] in ("A", "B")]
    if anfragen:
        df = pd.DataFrame(
            [
                {
                    "Einordnung": p["PreCheck"],
                    "Flurstück": p["Flurstueck"],
                    "Nutzung": p["Nutzung"],
                    "Landes-Potenzial m²": p["EntFl"],
                    "Kostenrahmen ca. €": round(p["EntFl"] * preis_m2, -2),
                }
                for p in anfragen
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True, height=260)
        st.download_button(
            "⬇ Übersicht als CSV exportieren",
            df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
            file_name=f"FlaechenRadar_{gemeinde}.csv",
            mime="text/csv",
        )
    else:
        st.info("Für die aktuelle Filterauswahl liegen keine Flächen in Priorität A oder B vor.")

st.markdown(
    f"""<div class="fr-foot">
<b>FlächenRadar NI</b> · Digitale Flächen-, Entsiegelungs- &amp; Wirtschaftlichkeitsanalyse.<br>
Rechtsrahmen &amp; Förderstand: § 19 NKlimaG (Ersterfassung bis 31.12.2026), § 1a NNatSchG, KfW 444 (NKK), NBank, KliKoNi (Stand Nov. 2026).<br>
Unverbindliche, vorläufige Einschätzung – keine verbindliche Planung, Baugenehmigung, Förderzusage oder Preisgarantie.<br>
Katastergrundlage: {ek.QUELLE} · <a href="https://downloads.entsiegelungskataster.niedersachsen.de/" target="_blank">Entsiegelungskataster.NI</a>
</div>""",
    unsafe_allow_html=True,
)

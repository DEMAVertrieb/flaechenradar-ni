"""
FlächenRadar NI – Entsiegelungs- & Klimaanpassungs-Dashboard
Version 2.2

Start:  streamlit run app.py

Optionale Umgebungsvariablen:
  CRM_WEBHOOK_URL   – Endpoint für Lead-Übergabe (POST JSON). Ohne Wert: kein CRM-Versand.
  DRIVE_FOLDER_URL  – Link zum Google-Drive-Projektordner.
  KATASTER_CACHE    – Ordner für heruntergeladene Katasterdaten (Standard: ./kataster)
"""

import json
import math
import os
import re
import uuid
from datetime import datetime, timedelta

import folium
import pandas as pd
from shapely.geometry import shape as _shape
import requests
import streamlit as st
from folium.plugins import Draw
from fpdf import FPDF
from streamlit_folium import st_folium

import kataster as ek
from gebuehren import REGION_WERLTE, gebuehr, FOERDER_KULISSE_NI

# ==============================================================================
# 0. KONFIGURATION
# ==============================================================================
st.set_page_config(
    page_title="FlächenRadar NI",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CRM_WEBHOOK_URL = os.getenv("CRM_WEBHOOK_URL", "").strip()
DRIVE_FOLDER_URL = os.getenv("DRIVE_FOLDER_URL", "").strip()
SLA_STUNDEN = 24
MIN_FLAECHE_M2 = 10
BAGATELL_ZUSCHUSS_EUR = 2_000
DE_MINIMIS_EUR = 300_000
KARTE_MAX_FLURSTUECKE = 250  # Cloud-RAM-Schutz (Free Tier ~1 GB)

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
STUFEN_FARBE = {5: "#10B981", 4: "#84CC16", 3: "#F59E0B"}

# Pre-Check-Defaults (über Sidebar überschreibbar)
DEFAULT_PRECHECK_A_STUFE = 4
DEFAULT_PRECHECK_A_FL = 1000
DEFAULT_PRECHECK_B_STUFE = 3
DEFAULT_PRECHECK_B_FL = 300

# ==============================================================================
# 1. STYLING
# ==============================================================================
st.markdown(
    """
<style>
#MainMenu, footer, header[data-testid="stHeader"] {visibility:hidden; height:0;}
.block-container {padding-top:1.2rem; padding-bottom:2rem; max-width:100%;}
.stApp {background: radial-gradient(1200px 600px at 10% -10%, #10233F 0%, #0B1220 55%);}
.fr-header {display:flex; justify-content:space-between; align-items:flex-end;
  border-bottom:1px solid #1F2A3D; padding-bottom:14px; margin-bottom:18px;}
.fr-brand {font-size:11px; letter-spacing:.18em; color:#10B981; font-weight:700;}
.fr-title {font-size:26px; font-weight:750; color:#F8FAFC; line-height:1.15; margin-top:4px;}
.fr-sub {font-size:13px; color:#94A3B8; margin-top:4px;}
.fr-meta {text-align:right; font-size:12px; color:#64748B; line-height:1.6;}
.fr-meta b {color:#CBD5E1; font-weight:600;}
.st-key-card1, .st-key-card2, .st-key-card3, .st-key-card4 {
  background:#111A2B; border:1px solid #1F2A3D; border-radius:12px; padding:18px 18px 20px 18px;}
.step {font-size:11px; letter-spacing:.14em; color:#10B981; font-weight:700;}
.step-title {font-size:17px; color:#F1F5F9; font-weight:700; margin:2px 0 12px 0;}
.kpi {background:#0D1524; border:1px solid #1F2A3D; border-radius:10px; padding:12px 14px; margin-bottom:10px;}
.kpi .l {font-size:11px; color:#94A3B8; text-transform:uppercase; letter-spacing:.08em;}
.kpi .v {font-size:22px; color:#F8FAFC; font-weight:700; font-variant-numeric:tabular-nums; margin-top:2px;}
.kpi .h {font-size:12px; color:#64748B; margin-top:2px;}
.kpi.accent {border-color:#10B98155; background:linear-gradient(180deg,#0F2A24 0%,#0D1524 100%);}
.kpi.accent .v {color:#34D399;}
.kpi.muted .v {color:#94A3B8; font-size:18px;}
.srow {display:flex; justify-content:space-between; align-items:center; gap:12px; padding:9px 0;
  border-bottom:1px dashed #1F2A3D; font-size:13px;}
.srow .k {color:#94A3B8; white-space:nowrap;}
.srow .val {color:#E2E8F0; font-family:ui-monospace,Menlo,monospace; font-size:12.5px; text-align:right;}
.pill {display:inline-block; padding:2px 9px; border-radius:999px; font-size:11.5px; font-weight:600; white-space:nowrap;}
.pill.ok {background:#064E3B; color:#6EE7B7;} .pill.warn {background:#4A3510; color:#FCD34D;}
.pill.bad {background:#4C1414; color:#FCA5A5;} .pill.off {background:#1E293B; color:#94A3B8;}
.flst {background:#0D1524; border:1px solid #10B98155; border-radius:10px; padding:10px 12px; margin:8px 0; font-size:12.5px; color:#CBD5E1;}
.flst b {color:#F8FAFC;}
.stButton>button, .stDownloadButton>button, .stLinkButton>a {width:100%; border-radius:8px !important; font-weight:700 !important;}
.stButton>button[kind="primary"] {background:#10B981 !important; border:none !important; color:#04140F !important;}
.stButton>button[kind="primary"]:hover {background:#34D399 !important;}
.fr-foot {font-size:11.5px; color:#64748B; border-top:1px solid #1F2A3D; margin-top:22px; padding-top:12px;}
.fr-foot a {color:#94A3B8;}
</style>
""",
    unsafe_allow_html=True,
)


# ==============================================================================
# 2. HILFSFUNKTIONEN
# ==============================================================================
def zahl(x: float, nk: int = 0) -> str:
    return f"{x:,.{nk}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def eur(x: float, nk: int = 0) -> str:
    return f"{zahl(x, nk)} €"


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
# 3. SESSION-STATE
# ==============================================================================
ss = st.session_state
for k, v in {
    "flaeche": 1250,
    "system_id": None,
    "scan_zeit": None,
    "crm_status": "off",
    "polygon_m2": 0.0,
    "flurstueck": None,
    "adresse": "",
    "nutzung_sel": "Gewerbefläche / Parkplatz",
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
    n = ALKIS_ZU_NUTZUNG.get(props.get("HauptTN"), "Sonstige")
    ss.nutzung_sel = n


# ==============================================================================
# 4. HEADER + SIDEBAR (Pre-Check-Regeln)
# ==============================================================================
st.markdown(
    f"""
<div class="fr-header"><div>
  <div class="fr-brand">FLÄCHENRADAR NI</div>
  <div class="fr-title">Entsiegelungs- & Klimaanpassungs-Dashboard</div>
  <div class="fr-sub">Entsiegelungspotenzial (Entsiegelungskataster.NI), Gebührenlage und Wirtschaftlichkeitsabschätzung</div>
</div><div class="fr-meta"><b>Version 2.2</b><br>Stand {datetime.now():%d.%m.%Y, %H:%M} Uhr</div></div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Pre-Check-Regeln")
    st.caption("Live-Filter für A/B-Leads (Karte & Lead-Liste)")
    pc_a_stufe = st.slider("A-Lead: min. Potenzialstufe", 3, 5, DEFAULT_PRECHECK_A_STUFE, key="pc_a_stufe")
    pc_a_fl = st.number_input("A-Lead: min. entsiegelbare Fläche (m²)", 100, 5000, DEFAULT_PRECHECK_A_FL, step=100, key="pc_a_fl")
    pc_b_stufe = st.slider("B-Lead: min. Potenzialstufe", 2, 5, DEFAULT_PRECHECK_B_STUFE, key="pc_b_stufe")
    pc_b_fl = st.number_input("B-Lead: min. entsiegelbare Fläche (m²)", 50, 2000, DEFAULT_PRECHECK_B_FL, step=50, key="pc_b_fl")
    st.divider()
    st.caption("Standard: A ≥ Stufe 4 + ≥ 1.000 m² · B ≥ Stufe 3 + ≥ 300 m²")

try:
    KATALOG = katalog()
    kat_ok = True
except Exception:
    KATALOG, kat_ok = {}, False

col1, col2, col3 = st.columns([1.25, 1, 1], gap="medium")

# ==============================================================================
# 5. STEP 1 – GEO- & OBJEKTDATEN (mit Kataster)
# ==============================================================================
with col1:
    with st.container(key="card1"):
        st.markdown(
            '<div class="step">STEP 1</div><div class="step-title">Geo- & Objektdaten</div>',
            unsafe_allow_html=True,
        )

        gemeinden = sorted(KATALOG) if kat_ok else REGION_WERLTE
        # Default: Haselünne falls vorhanden, sonst Werlte
        if "Haselünne, Stadt" in gemeinden:
            g_default = gemeinden.index("Haselünne, Stadt")
        elif "Werlte" in gemeinden:
            g_default = gemeinden.index("Werlte")
        else:
            g_default = 0
        a, b = st.columns([1.4, 1])
        gemeinde = a.selectbox("Gemeinde (Entsiegelungskataster.NI)", gemeinden, index=g_default)
        min_stufe = b.selectbox(
            "Potenzial ab Stufe",
            [5, 4, 3],
            index=1,
            format_func=lambda s: {5: "5 – sehr hoch", 4: "4 – hoch", 3: "3 – mittel"}[s],
        )

        feats, kstat = ([], None)
        if kat_ok:
            with st.spinner(f"Lade Katasterdaten {gemeinde} …"):
                try:
                    feats, kstat = entpot(gemeinde)
                    if not ss.cache_hinweis_shown:
                        st.info(
                            "Hinweis: Katasterdaten werden beim ersten Aufruf einer Gemeinde einmalig geladen "
                            "(ca. 10–15 MB) und lokal gecacht. Bei Streamlit Cloud ist der Cache ephemer.",
                            icon="ℹ️",
                        )
                        ss.cache_hinweis_shown = True
                except Exception as e:
                    st.error(f"Katasterdaten konnten nicht geladen werden: {e}")
        else:
            st.warning("Kataster-Katalog nicht erreichbar – manuelle Eingabe aktiv.")

        # Live Pre-Check auf Basis der Sidebar-Regeln neu berechnen
        def live_precheck(p: dict) -> str:
            s, fl = p.get("Stufe", 0), p.get("EntFl", 0)
            tn = p.get("HauptTN")
            if s >= pc_a_stufe and fl >= pc_a_fl and tn in ek.B2B_NUTZUNGEN:
                return "A"
            if s >= pc_b_stufe and fl >= pc_b_fl:
                return "B"
            return "C"

        for f in feats:
            f["properties"]["PreCheck"] = live_precheck(f["properties"])

        nur_b2b = st.toggle(
            "Nur B2B-Nutzungen (Gewerbe, Mischgebiet, öffentl. Einrichtungen, Sport, Plätze)",
            value=True,
        )
        sicht = [
            f
            for f in feats
            if f["properties"]["Stufe"] >= min_stufe
            and (not nur_b2b or f["properties"]["HauptTN"] in ek.B2B_NUTZUNGEN)
        ][:KARTE_MAX_FLURSTUECKE]

        # ── Karte ────────────────────────────────────────────────────────────
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

        m = folium.Map(location=center, zoom_start=zoom, tiles="CartoDB dark_matter", control_scale=True)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri World Imagery",
            name="Luftbild",
        ).add_to(m)
        if sicht:
            folium.GeoJson(
                {"type": "FeatureCollection", "features": sicht},
                name="Entsiegelungspotenzial",
                style_function=lambda f: {
                    "color": STUFEN_FARBE.get(f["properties"]["Stufe"], "#64748B"),
                    "weight": 1.2,
                    "fillOpacity": 0.35,
                },
                highlight_function=lambda f: {"weight": 3, "fillOpacity": 0.6},
                tooltip=folium.GeoJsonTooltip(
                    fields=["Flurstueck", "Nutzung", "EntFl", "VerAnt_pct", "EntPot", "PreCheck"],
                    aliases=["Flurstück", "Nutzung", "entsiegelbar (m²)", "versiegelt (%)", "Potenzial", "Pre-Check"],
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
            f"{len(sicht)} Flurstücke angezeigt (größte zuerst, max. {KARTE_MAX_FLURSTUECKE}). "
            "Flurstück anklicken oder eigene Fläche einzeichnen."
        )
        out = st_folium(
            m,
            height=360,
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
                f'Nutzung {p["Nutzung"]} · Flurstück {zahl(ek.num(p["FlstFl_m2"]))} m² · '
                f'versiegelt {p["VerAnt_pct"]} % · <b>entsiegelbar {zahl(p["EntFl"])} m²</b> · '
                f'Potenzial {p["EntPot"]} · Pre-Check <b>{p["PreCheck"]}</b></div>',
                unsafe_allow_html=True,
            )
            st.button("Flurstück übernehmen", on_click=uebernehme_flurstueck, args=(p,), type="secondary")

        drawings = (out or {}).get("all_drawings") or []
        ss.polygon_m2 = sum(
            polygon_flaeche_m2(f["geometry"]["coordinates"][0])
            for f in drawings
            if f.get("geometry", {}).get("type") == "Polygon"
        )
        if ss.polygon_m2 > 0:
            st.button(
                f"Eingezeichnete Fläche übernehmen: {zahl(ss.polygon_m2)} m²",
                on_click=uebernehme_polygon,
            )

        st.divider()
        firma = st.text_input("Kunde / Objektträger", value="", placeholder="z. B. Gewerbebetrieb Musterweg GmbH")
        a, b = st.columns([1, 2])
        plz = a.text_input("PLZ", value="49740", max_chars=5)  # Haselünne
        strasse = b.text_input("Adresse / Flurstück", key="adresse", placeholder="optional")
        plz_ok = bool(re.fullmatch(r"\d{5}", plz or ""))
        if plz and not plz_ok:
            st.error("PLZ muss aus genau 5 Ziffern bestehen.")

        kulisse_label = st.selectbox(
            "Förderkulisse (Niedersachsen & Bund)",
            list(FOERDER_KULISSE_NI.keys()),
            index=0,
        )
        kulisse_info = FOERDER_KULISSE_NI[kulisse_label]
        c, d = st.columns(2)
        belag = c.selectbox("Bestandsbelag", list(DEFAULT_RUECKBAU_EUR_M2))
        nutzung = d.selectbox("Nutzungsart", list(NUTZUNGS_FAKTOR), key="nutzung_sel")
        flaeche = st.number_input(
            "Projektfläche (m²)",
            min_value=0,
            step=50,
            key="flaeche",
            help="Bei Übernahme eines Flurstücks: entsiegelbare Oberfläche laut Kataster.",
        )

        scan_triggered = st.button(
            "▶ STARTE FLÄCHENRADAR-SCAN",
            type="primary",
            disabled=(flaeche < MIN_FLAECHE_M2 or not plz_ok),
        )
        if flaeche < MIN_FLAECHE_M2:
            st.error(f"Hard-Lock: Fläche ({flaeche} m²) unter Mindestgröße {MIN_FLAECHE_M2} m².")

# ==============================================================================
# 6. KALKULATIONS-ENGINE
# ==============================================================================
g_info = gebuehr(gemeinde)
with st.expander("Kalkulationsparameter (Musterwerte – vor Kundeneinsatz prüfen)"):
    p1, p2, p3, p4 = st.columns(4)
    pu_preis = p1.number_input(
        "PU-Asphalt / wasserdurchlässiger Belag inkl. Einbau (€/m²)",
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
    q1, q2 = st.columns(2)
    foerder_quote_manuell = q1.number_input(
        "Förderquote (%)",
        0,
        100,
        int(kulisse_info["quote_default"]),
        help=f"Richtwert aus Kulisse: {kulisse_info['quote_default']} %. Jederzeit überschreibbar.",
    )
    st.caption(f"**{kulisse_info['code']}** · {kulisse_info['traeger']}  \n{kulisse_info['hinweis']}")

preis_m2 = (pu_preis + rueckbau + unterbau) * NUTZUNGS_FAKTOR[nutzung]
kosten = flaeche * preis_m2
hinweise = []
programm = kulisse_label
quote = float(foerder_quote_manuell)
foerderfaehig = quote > 0
if not foerderfaehig:
    hinweise.append("Keine Förderquote hinterlegt – Förderprogramm für Land/Kommune prüfen.")
zuschuss = kosten * quote / 100 if foerderfaehig else 0.0
if foerderfaehig and zuschuss < BAGATELL_ZUSCHUSS_EUR and quote > 0:
    hinweise.append(f"Zuschuss unter Bagatellgrenze ({eur(BAGATELL_ZUSCHUSS_EUR)}) – ggf. prüfen.")
if zuschuss > DE_MINIMIS_EUR:
    hinweise.append(f"De-minimis-Deckel {eur(DE_MINIMIS_EUR)} angewendet.")
    zuschuss = DE_MINIMIS_EUR
if gebuehr_satz <= 0:
    hinweise.append(
        f"{gemeinde}: keine laufende Niederschlagswassergebühr bekannt – "
        "Wirtschaftlichkeit über Gebührenersparnis entfällt. Argumente: Starkregen-/Überflutungsschutz, "
        "Entfall von Rückhalte-/Versickerungsauflagen, Flächennutzung bleibt erhalten."
    )
hinweise.append(f"Fördercode: {kulisse_info['code']} · {kulisse_info['hinweis']}")
hinweise.append("Maßnahmenbeginn erst nach Förderzusage. Alle Angaben sind unverbindliche Richtwerte.")
eigenanteil = max(0.0, kosten - zuschuss)
ersparnis = flaeche * gebuehr_satz
amortisation = eigenanteil / ersparnis if ersparnis > 0 else float("inf")
eff_quote = zuschuss / kosten * 100 if kosten else 0.0

if scan_triggered:
    ss.system_id = f"FR-{datetime.now():%Y%m%d}-{plz}-{uuid.uuid4().hex[:4].upper()}"
    ss.scan_zeit = datetime.now()
    payload = {
        "system_id": ss.system_id,
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
        "leadquelle": "FlächenRadar_NI",
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
# 7. STEP 2 – TRIAGE & PROZESS
# ==============================================================================
with col2:
    with st.container(key="card2"):
        st.markdown(
            '<div class="step">STEP 2</div><div class="step-title">Triage- & Prozess-Status</div>',
            unsafe_allow_html=True,
        )
        srow("System-ID", ss.system_id or "– noch kein Scan –")
        pc = (ss.flurstueck or {}).get("PreCheck")
        srow(
            "Kataster-Pre-Check",
            {
                "A": '<span class="pill ok">A · Top-Lead</span>',
                "B": '<span class="pill warn">B · prüfen</span>',
                "C": '<span class="pill off">C · nachrangig</span>',
            }.get(pc, '<span class="pill off">kein Flurstück</span>'),
        )
        srow("Förderprogramm", programm)
        srow(
            "Förderstatus",
            '<span class="pill ok">förderfähig</span>'
            if zuschuss > 0
            else '<span class="pill warn">Prüfung nötig</span>',
        )
        geb_pill = (
            f'<span class="pill ok">{zahl(gebuehr_satz, 2)} €/m²·a</span>'
            if gebuehr_satz > 0
            else '<span class="pill warn">keine lfd. Gebühr</span>'
            if g_info["status"] == "keine"
            else '<span class="pill off">Satz unbekannt</span>'
        )
        srow(f"NW-Gebühr {gemeinde}", geb_pill)
        if ss.scan_zeit:
            h = (datetime.now() - ss.scan_zeit).total_seconds() / 3600
            rest = SLA_STUNDEN - h
            pill = (
                f'<span class="pill ok">konform · {zahl(rest, 1)} h Rest</span>'
                if h < SLA_STUNDEN * 0.75
                else f'<span class="pill warn">kritisch · {zahl(rest, 1)} h Rest</span>'
                if h < SLA_STUNDEN
                else '<span class="pill bad">SLA überschritten</span>'
            )
        else:
            pill = '<span class="pill off">startet mit Scan</span>'
        srow(f"PSI / SLA-Timer ({SLA_STUNDEN} h)", pill)
        srow(
            "CRM Phase 01",
            {
                "ok": '<span class="pill ok">Lead übertragen</span>',
                "fail": '<span class="pill bad">Übertragung fehlgeschlagen</span>',
                "off": '<span class="pill off">Webhook nicht konfiguriert</span>',
            }[ss.crm_status],
        )

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        uploads = st.file_uploader(
            "Dokumenten-Check: Bestandspläne / Fotos",
            type=["png", "jpg", "jpeg", "pdf"],
            accept_multiple_files=True,
        )
        if uploads:
            bilder = [u for u in uploads if u.type.startswith("image/")]
            st.caption(f"{len(uploads)} Datei(en) · {len(bilder)} Foto(s) · {len(uploads) - len(bilder)} PDF(s)")
            if bilder:
                st.image(bilder[:4], width=90)
        if DRIVE_FOLDER_URL:
            st.link_button("📂 DRIVE-ORDNER ÖFFNEN", DRIVE_FOLDER_URL)
        else:
            st.button("📂 DRIVE-ORDNER ÖFFNEN", disabled=True, help="DRIVE_FOLDER_URL setzen.")


# ==============================================================================
# 8. STEP 3 – FINANCIAL ENGINEERING + PDF
# ==============================================================================
def _pdf_text(val) -> str:
    ersetzungen = {
        "€": "EUR", "²": "2", "³": "3",
        "–": "-", "—": "-", "·": "-", "•": "-",
        "®": "(R)", "≥": ">=", "≤": "<=", "÷": "/",
        "„": '"', "“": '"', "”": '"', "’": "'", "‘": "'",
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

    pdf.set_fill_color(16, 185, 129)
    pdf.rect(0, 0, 210, 6, "F")
    pdf.set_y(14)
    pdf.set_font(fam, "B", 9)
    pdf.set_text_color(16, 150, 110)
    pdf.cell(0, 5, t("FLÄCHENRADAR NI"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(fam, "B", 18)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 10, t("Vorprüfbericht Entsiegelung & Wirtschaftlichkeit"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(fam, "", 9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(
        0,
        5,
        t(f"System-ID {ss.system_id or 'ohne Scan'} · erstellt {datetime.now():%d.%m.%Y %H:%M}"),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(5)

    def block(titel, zeilen):
        pdf.set_font(fam, "B", 11)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 8, t(titel), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(226, 232, 240)
        for k, v in zeilen:
            pdf.set_font(fam, "", 10)
            pdf.set_text_color(71, 85, 105)
            pdf.cell(85, 7, t(k), border="B")
            pdf.set_text_color(15, 23, 42)
            pdf.cell(0, 7, t(v), border="B", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    block(
        "1. Objekt",
        [
            ("Kunde / Objektträger", firma or "–"),
            ("Gemeinde / PLZ", f"{gemeinde} · {plz}"),
            ("Adresse / Flurstück", strasse or "–"),
            ("Projektfläche", f"{zahl(flaeche)} m²"),
            ("Bestandsbelag / Nutzung", f"{belag} / {nutzung}"),
        ],
    )
    fs = ss.flurstueck
    if fs:
        block(
            "2. Kataster (Entsiegelungskataster.NI)",
            [
                ("Flurstückskennzeichen", fs["Fsk"]),
                ("Hauptnutzung", fs["Nutzung"]),
                ("Flurstücksfläche", f"{zahl(ek.num(fs['FlstFl_m2']))} m²"),
                ("Versiegelungsanteil", f"{fs['VerAnt_pct']} %"),
                ("Entsiegelbare Oberfläche", f"{zahl(fs['EntFl'])} m²"),
                ("Entsiegelungspotenzial", fs["EntPot"]),
                ("Pre-Check", fs["PreCheck"]),
            ],
        )
    block(
        "3. Wirtschaftlichkeit (Schätzung)",
        [
            ("Kalkulierter Preis", f"{eur(preis_m2, 2)} / m²"),
            ("Investitionsvolumen", eur(kosten)),
            ("Förderprogramm / Quote", f"{programm} · {zahl(eff_quote)} %"),
            ("Fördercode", kulisse_info.get("code", "–")),
            ("Zuschuss", eur(zuschuss)),
            ("Netto-Eigenanteil", eur(eigenanteil)),
            (
                "Niederschlagswassergebühr",
                f"{zahl(gebuehr_satz, 2)} €/m²·a" if gebuehr_satz > 0 else "keine laufende Gebühr bekannt",
            ),
            ("Ersparnis / Jahr", eur(ersparnis)),
            (
                "Amortisation über Gebühr",
                "entfällt" if math.isinf(amortisation) else f"{zahl(amortisation, 1)} Jahre",
            ),
        ],
    )
    pdf.set_font(fam, "B", 10)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 7, t("Hinweise"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(fam, "", 9)
    pdf.set_text_color(71, 85, 105)
    for h in hinweise:
        pdf.multi_cell(0, 5, t(f"- {h}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font(fam, "", 8)
    pdf.set_text_color(148, 163, 184)
    pdf.multi_cell(
        0,
        4,
        t(
            "Unverbindliche Vorabschätzung auf Basis von Musterwerten - keine Förderzusage, kein Angebot. "
            f"Katasterdaten: {ek.QUELLE} (downloads.entsiegelungskataster.niedersachsen.de). "
            f"Gebührenangabe: {g_info['hinweis']} {g_info['quelle']}"
        ),
    )
    return bytes(pdf.output())

with col3:
    with st.container(key="card3"):
        st.markdown(
            '<div class="step">STEP 3</div><div class="step-title">Financial Engineering</div>',
            unsafe_allow_html=True,
        )
        kpi(
            "Investitionsvolumen (netto, ca.)",
            eur(kosten),
            f"{zahl(flaeche)} m² × {eur(preis_m2, 2)}/m² · {belag} → PU-Asphalt",
        )
        kpi("Staatlicher Zuschuss", eur(zuschuss), f"{zahl(eff_quote)} % effektiv · {programm}")
        kpi("Netto-Eigenanteil", eur(eigenanteil), "nach Abzug Zuschuss", cls="accent")
        k1, k2 = st.columns(2)
        with k1:
            if gebuehr_satz > 0:
                kpi("Ersparnis / Jahr", eur(ersparnis), f"{zahl(gebuehr_satz, 2)} €/m²·a")
            else:
                kpi("Ersparnis / Jahr", "keine Gebühr", f"{gemeinde}: kein NW-Gebührensatz", cls="muted")
        with k2:
            kpi(
                "Amortisation",
                "entfällt" if math.isinf(amortisation) else f"{zahl(amortisation, 1)} J.",
                "Eigenanteil ÷ Ersparnis",
                cls="muted" if math.isinf(amortisation) else "",
            )
        for h in hinweise[:-1]:
            st.warning(h, icon="⚠️")
        st.caption("⏱ " + hinweise[-1])
        st.download_button(
            "🖨️ PRÜFBERICHT (PDF) HERUNTERLADEN",
            data=baue_pdf(),
            file_name=f"Pruefbericht_{ss.system_id or gemeinde}.pdf",
            mime="application/pdf",
        )

if scan_triggered:
    msg = {
        "ok": "Lead an CRM übertragen.",
        "fail": "CRM-Übertragung fehlgeschlagen.",
        "off": "CRM-Webhook nicht konfiguriert – Lead nur lokal erfasst.",
    }[ss.crm_status]
    (st.success if ss.crm_status == "ok" else st.info)(
        f"FlächenRadar ausgeführt · {ss.system_id} · {msg}"
    )

# ==============================================================================
# 9. REGIONALRADAR – Lead-Liste & Gemeindevergleich
# ==============================================================================
st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
with st.container(key="card4"):
    st.markdown(
        '<div class="step">STEP 4</div><div class="step-title">Regionalradar – Lead-Liste & Gemeindevergleich</div>',
        unsafe_allow_html=True,
    )
    tab1, tab2 = st.tabs([f"Lead-Liste {gemeinde}", "Gemeindevergleich"])

    with tab1:
        leads = [f["properties"] for f in feats if f["properties"]["PreCheck"] in ("A", "B")]
        if leads:
            df = pd.DataFrame(
                [
                    {
                        "Pre-Check": p["PreCheck"],
                        "Flurstück": p["Flurstueck"],
                        "Kennzeichen": p["Fsk"],
                        "Ortsteil": p["Gmd"],
                        "Nutzung": p["Nutzung"],
                        "Potenzial": p["EntPot"],
                        "versiegelt %": p["VerAnt_pct"],
                        "entsiegelbar m²": p["EntFl"],
                        "Invest. ca. €": round(p["EntFl"] * preis_m2, -2),
                        "Gebührenersparnis €/a": round(p["EntFl"] * gebuehr_satz),
                    }
                    for p in leads
                ]
            )
            a, b, c = st.columns(3)
            a.metric("A-Leads (Top)", zahl((df["Pre-Check"] == "A").sum()))
            b.metric("B-Leads (prüfen)", zahl((df["Pre-Check"] == "B").sum()))
            c.metric(
                "Entsiegelbar in A-Leads",
                f"{zahl(df.loc[df['Pre-Check'] == 'A', 'entsiegelbar m²'].sum() / 10_000, 1)} ha",
            )
            filt = st.multiselect("Pre-Check", ["A", "B"], default=["A"])
            dfa = df[df["Pre-Check"].isin(filt)]
            st.dataframe(
                dfa,
                use_container_width=True,
                hide_index=True,
                height=320,
                column_config={
                    "entsiegelbar m²": st.column_config.NumberColumn(format="%d"),
                    "Invest. ca. €": st.column_config.NumberColumn(format="%d €"),
                    "Gebührenersparnis €/a": st.column_config.NumberColumn(format="%d €"),
                },
            )
            # Export
            sel = {p["Fsk"] for p in leads if p["PreCheck"] in filt}
            gj = {
                "type": "FeatureCollection",
                "name": f"FlächenRadar_Leads_{gemeinde}",
                "attribution": ek.QUELLE,
                "features": [f for f in feats if f["properties"]["Fsk"] in sel],
            }
            e1, e2 = st.columns(2)
            e1.download_button(
                "⬇ Lead-Liste als CSV",
                dfa.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                file_name=f"FlächenRadar_Leads_{gemeinde}.csv",
                mime="text/csv",
            )
            e2.download_button(
                "⬇ Lead-Flächen als GeoJSON (für GIS / Kommune)",
                json.dumps(gj, ensure_ascii=False).encode(),
                file_name=f"FlächenRadar_Leads_{gemeinde}.geojson",
                mime="application/geo+json",
            )
            st.caption(
                "Hinweis: Das Kataster liefert Flurstücke ohne Eigentümerangaben. Eigentümerdaten nur bei "
                "berechtigtem Interesse über das Katasteramt – für die Ansprache Adresse/Betrieb vor Ort ermitteln."
            )
        else:
            st.info("Keine A/B-Leads für diese Auswahl.")

    with tab2:
        auswahl = st.multiselect(
            "Vergleichsgemeinden",
            gemeinden,
            default=[g for g in REGION_WERLTE if g in gemeinden],
        )
        if st.button("Vergleich berechnen", type="secondary"):
            ss.vergleich = auswahl
        if ss.get("vergleich"):
            rows = []
            prog = st.progress(0.0, text="Lade Katasterdaten …")
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
                        "A-Leads": s["a_leads"],
                        "B-Leads": s["b_leads"],
                        "entsiegelbar A-Leads ha": round(s["entfl_b2b_hoch"] / 10_000, 1),
                        "NW-Gebühr": (
                            f"{zahl(gi['satz'], 2)} €/m²"
                            if gi["satz"]
                            else "keine lfd. Gebühr"
                            if gi["status"] == "keine"
                            else "unbekannt"
                        ),
                        "Quelle Gebühr": gi["quelle"],
                    }
                )
                prog.progress((i + 1) / len(ss.vergleich), text=f"{g} geladen")
            prog.empty()
            vdf = pd.DataFrame(rows).sort_values("entsiegelbar A-Leads ha", ascending=False)
            st.dataframe(
                vdf,
                use_container_width=True,
                hide_index=True,
                height=560,
                column_config={"Quelle Gebühr": st.column_config.LinkColumn(display_text="Satzung")},
            )
            st.download_button(
                "⬇ Vergleich als CSV",
                vdf.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                file_name="FlächenRadar_Regionalvergleich.csv",
                mime="text/csv",
            )

st.markdown(
    f"""<div class="fr-foot">Unverbindliche Vorabschätzung – keine Förderzusage und kein Angebot.
Katasterdaten: {ek.QUELLE} · <a href="https://downloads.entsiegelungskataster.niedersachsen.de/" target="_blank">Download-Portal</a>.
Pre-Check (aktuell): A ≥ Stufe {pc_a_stufe} + ≥ {zahl(pc_a_fl)} m² (B2B) · B ≥ Stufe {pc_b_stufe} + ≥ {zahl(pc_b_fl)} m².
Gebühren: Recherchestand 11.10.2026, je Gemeinde im Parameterbereich überschreibbar.
Förderangaben sind unverbindliche Richtwerte – verbindliche Prüfung obliegt der Förderstelle.</div>""",
    unsafe_allow_html=True,
)

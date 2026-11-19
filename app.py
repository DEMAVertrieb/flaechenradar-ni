"""
FlächenRadar DE – Bundesweites Geben-und-Nehmen-Interface & Daten-Asset
Version 5.0 (Radical Simple · Deutschlandweit · Strukturiertes Event-Schema)
"""

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st

st.set_page_config(
    page_title="FlächenRadar · Regenwasser-, Hitze- & Satzungs-Check",
    page_icon="💧",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def get_secret(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:
        pass
    return os.getenv(name, default).strip()


CRM_WEBHOOK_URL = get_secret("CRM_WEBHOOK_URL", "")
APP_PASSWORD = get_secret("APP_PASSWORD", "")

DATA_DIR = Path("data")
UPLOAD_DIR = DATA_DIR / "uploads"
EVENTS_FILE = DATA_DIR / "events_log.jsonl"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def plz_zu_bundesland(plz: str) -> str:
    """Ordnet eine 5-stellige deutsche PLZ zuverlässig dem Bundesland zu."""
    if not re.fullmatch(r"\d{5}", plz or ""):
        return "Unbekannt"
    p2 = int(plz[:2])
    p3 = int(plz[:3])
    if p2 in (1, 2, 4, 8, 9):
        return "Sachsen"
    if p2 in (3, 15, 16) or (144 <= p3 <= 149) or (193 <= p3 <= 193):
        return "Brandenburg"
    if 10 <= p2 <= 14:
        return "Berlin"
    if 17 <= p2 <= 19:
        return "Mecklenburg-Vorpommern"
    if 20 <= p2 <= 22:
        return "Hamburg"
    if 23 <= p2 <= 25:
        return "Schleswig-Holstein"
    if p2 in (26, 27, 29, 30, 31, 37, 38, 49) or (287 <= p3 <= 288):
        return "Niedersachsen"
    if p2 == 28:
        return "Bremen"
    if p2 in (6, 7, 39):
        return "Sachsen-Anhalt"
    if (32 <= p2 <= 33) or (40 <= p2 <= 48) or (50 <= p2 <= 53) or (57 <= p2 <= 59):
        return "Nordrhein-Westfalen"
    if (34 <= p2 <= 36) or (60 <= p2 <= 65):
        return "Hessen"
    if (54 <= p2 <= 56) or (66 <= p2 <= 67):
        return "Rheinland-Pfalz"
    if p2 == 66:
        return "Saarland"
    if (68 <= p2 <= 79) or (88 <= p2 <= 89):
        return "Baden-Württemberg"
    if (80 <= p2 <= 87) or (90 <= p2 <= 97):
        return "Bayern"
    if 98 <= p2 <= 99:
        return "Thüringen"
    return "Deutschland (Sonstige)"


ANLIEGEN_MAP = {
    "gebuehren_pruefen": {
        "label": "💧 Regenwassergebühr & Satzung prüfen",
        "kurz": "Gebührenlast & Einsparpotenzial durch Entkopplung einordnen",
    },
    "entsiegelung_wasserdurchlaessig": {
        "label": "🧱 Entsiegelung & wasserdurchlässige Fläche",
        "kurz": "Parkplatz, Hof, Weg oder Zufahrt versickerungsfähig gestalten",
    },
    "starkregen_schwammstadt": {
        "label": "🌊 Starkregen & Schwammstadt-Rückhalt",
        "kurz": "Überflutungsschutz und Regenwasserspeicherung vor Ort",
    },
    "hitzeinsel_mikroklima": {
        "label": "🌡️ Hitzeinsel & Aufheizung reduzieren",
        "kurz": "Kühlung und Mikroklima auf Gewerbe-, Kommunal- oder Privatflächen",
    },
    "bplan_baugenehmigung": {
        "label": "📐 Bebauungsplan & Bauauflagen",
        "kurz": "Vorgaben zu Versickerung, Rückhaltung und Begrünung erfüllen",
    },
    "satzung_hochladen": {
        "label": "📄 Kommunale Satzung / B-Plan hochladen",
        "kurz": "Aktuelle Abwassersatzung, Amtsblatt oder B-Plan einreichen",
    },
}

NUTZUNGSARTEN = [
    "Keine Angabe",
    "Gewerbe / Parkplatz / Logistik",
    "Kommune / Öffentliche Fläche / Weg",
    "Wohnanlage / Mehrfamilienhaus",
    "Privat / Hof / Einfahrt",
]

ss = st.session_state
for k, v in {
    "session_id": f"SES-{uuid.uuid4().hex[:10].upper()}",
    "last_event": None,
    "last_mehrwert": None,
}.items():
    ss.setdefault(k, v)


def speichere_event(event_data: dict) -> dict:
    """Speichert jedes Signal im verbindlichen Daten-Schema (JSONL + optional Webhook)."""
    record = {
        "event_id": f"EVT-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:5].upper()}",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "bundesland": event_data.get("bundesland", "Unbekannt"),
        "region_landkreis": event_data.get("region_landkreis", ""),
        "ort": event_data.get("ort", ""),
        "plz": event_data.get("plz", ""),
        "anliegen": event_data.get("anliegen", ""),
        "flaeche_m2": event_data.get("flaeche_m2"),
        "nutzungsart": event_data.get("nutzungsart", ""),
        "satzung_hochgeladen": bool(event_data.get("satzung_hochgeladen", False)),
        "datei_referenz": event_data.get("datei_referenz", ""),
        "interesse_signal": event_data.get("interesse_signal", "unbekannt"),
        "kontakt": event_data.get("kontakt", ""),
        "notiz": event_data.get("notiz", ""),
        "quelle": event_data.get("quelle", "oeffentlich"),
        "session_id": ss.session_id,
    }
    try:
        with EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    if CRM_WEBHOOK_URL:
        try:
            requests.post(CRM_WEBHOOK_URL, json=record, timeout=6)
        except Exception:
            pass
    return record


def generiere_mehrwert(bundesland: str, ort: str, anliegen: str, flaeche: int, nutzung: str) -> dict:
    """Liefert sofortigen, ehrlichen Mehrwert passend zu Region, Anliegen und Fläche."""
    ort_txt = ort.strip() or bundesland
    fl_txt = f"ca. {flaeche:,} m²".replace(",", ".") if flaeche and flaeche > 0 else "Ihre Fläche"

    if anliegen == "gebuehren_pruefen":
        spanne_unten = round(flaeche * 0.35 * 10) if flaeche else 0
        spanne_oben = round(flaeche * 1.40 * 10) if flaeche else 0
        hinweis_10j = (
            f"Bei {fl_txt} summiert sich eine gesplittete Niederschlagswassergebühr (je nach Kommune typischerweise "
            f"0,35 € bis 1,40 €/m²·a) über 10 Jahre auf **ca. {spanne_unten:,} € bis {spanne_oben:,} €**.".replace(",", ".")
            if flaeche
            else "In den meisten deutschen Städten und Gemeinden wird Niederschlagswasser getrennt nach versiegelter Fläche abgerechnet."
        )
        return {
            "titel": f"Gebühren- & Satzungs-Einordnung für {ort_txt} ({bundesland})",
            "text": (
                f"{hinweis_10j}\n\n"
                "**Wichtigste Hebel:**\n"
                "1. **Abflussbeiwert / Ermäßigung prüfen:** Viele Abwassersatzungen reduzieren die Gebühr um 50 % bis 100 %, "
                "wenn Flächen dauerhaft wasserdurchlässig ausgeführt oder vom Kanalnetz abgekoppelt werden.\n"
                "2. **Aktuelle Satzungsänderungen beachten:** Zahlreiche Kommunen führen die gesplittete Gebühr neu ein oder passen Sätze an.\n"
                "3. **Nächster Schritt:** Abwassersatzung der Kommune (Stichwort *Niederschlagswassergebühr / versiegelte Fläche*) prüfen."
            ),
        }

    if anliegen == "entsiegelung_wasserdurchlaessig":
        return {
            "titel": f"Orientierung: Wasserdurchlässige Gestaltung ({fl_txt})",
            "text": (
                f"Für **{nutzung}** in **{ort_txt}** bietet der Umbau auf wasserdurchlässige Systeme einen doppelten Effekt: "
                "Die Fläche bleibt voll belastbar und nutzbar, während Regenwasser direkt versickert.\n\n"
                "**Worauf es in der Praxis ankommt:**\n"
                "1. **Untergrund & Versickerungsfähigkeit:** Bindige Böden (Lehm/Ton) benötigen einen entsprechend dimensionierten "
                "Speicher- und Tragschichtaufbau.\n"
                "2. **Schutzgebiete & Altlasten:** In Wasserschutzgebieten oder auf vorbelasteten Gewerbeflächen gelten besondere Vorgaben.\n"
                "3. **Förder- & Satzungsabgleich:** Kommunale Klimafonds, Städtebauförderung oder KfW-Programme für Kommunen prüfen."
            ),
        }

    if anliegen == "starkregen_schwammstadt":
        puffer_m3 = round(flaeche * 0.045, 1) if flaeche else 0
        puffer_txt = f" (ca. **{puffer_m3} m³** bzw. {int(puffer_m3 * 1000):,} Liter Puffervolumen)".replace(",", ".") if flaeche else ""
        return {
            "titel": f"Schwammstadt- & Starkregen-Check für {ort_txt}",
            "text": (
                f"Bei Starkregen überlastet abfließendes Oberflächenwasser Kanäle und gefährdet Gebäude. "
                f"Ein wasserdurchlässiger Aufbau hält Niederschlag direkt in der Fläche zurück{puffer_txt}.\n\n"
                "**Sinnvolle Schritte:**\n"
                "1. **Fließwege prüfen:** Wohin läuft Wasser bei Extremregen über 30–50 l/m² in einer Stunde ab?\n"
                "2. **Rückstauschutz & Dezentralität:** Flächenentwässerung vom Misch-/Regenwasserkanal entkoppeln.\n"
                "3. **Kommunale Starkregenkarten:** Viele Länder (z. B. NI, NRW, BW, BY) stellen kostenlose Starkregengefahrenkarten bereit."
            ),
        }

    if anliegen == "hitzeinsel_mikroklima":
        return {
            "titel": f"Hitzeentlastung & Mikroklima ({ort_txt})",
            "text": (
                "Dichte, dunkle Asphalt- und Betonflächen speichern im Sommer extreme Wärme und strahlen sie bis in die Nacht ab. "
                "Offenporige, wasserdurchlässige Beläge und Teilentsiegelung senken die Oberflächentemperatur spürbar.\n\n"
                "**Empfohlene Maßnahmen:**\n"
                "1. **Verdunstungskühlung nutzen:** Gespeicherte Feuchtigkeit im Aufbau kühlt die Umgebungsluft an Hitzetagen.\n"
                "2. **Kombination mit Verschattung:** Randbereiche entsiegeln und mit standortgerechten Bäumen oder Mulden kombinieren."
            ),
        }

    if anliegen == "bplan_baugenehmigung":
        return {
            "titel": f"Bebauungsplan & Bauauflagen in {ort_txt} ({bundesland})",
            "text": (
                "Immer mehr Kommunen schreiben in Bebauungsplänen und Gestaltungssatzungen vor, dass Niederschlagswasser auf dem "
                "Grundstück versickert oder zurückgehalten werden muss und Vollversiegelungen begrenzt sind.\n\n"
                "**Checkliste für Bauherren & Planer:**\n"
                "1. **GRZ / Versiegelungsgrad prüfen:** Wasserdurchlässige Beläge werden je nach Satzung oft günstiger angerechnet.\n"
                "2. **Entwässerungsantrag:** Versickerungsnachweis (z. B. nach DWA-A 138) frühzeitig mit der Kommune abstimmen."
            ),
        }

    return {
        "titel": f"Vielen Dank für den Satzungs- / B-Plan-Beitrag zu {ort_txt}",
        "text": (
            f"Ihr Hinweis für **{ort_txt} ({bundesland})** wurde strukturiert erfasst. "
            "Aktuelle kommunale Satzungen und Bebauungspläne helfen dabei, Eigentümern und Planern vor Ort "
            "verlässliche Orientierung zu Gebühren und Versickerungsvorgaben zu geben."
        ),
    }


st.markdown(
    """
<style>
#MainMenu, footer, header[data-testid="stHeader"] {visibility:hidden; height:0;}
.block-container {padding-top:1.1rem; padding-bottom:2rem; max-width:760px;}
.hero {
  border:1px solid rgba(148,163,184,0.35); border-radius:14px;
  padding:18px 20px; margin-bottom:14px;
}
.kicker {font-size:11px; font-weight:800; letter-spacing:.11em; color:#0F766E; text-transform:uppercase;}
.title {font-size:23px; font-weight:800; margin:4px 0 6px 0; line-height:1.25;}
.sub {font-size:14px; opacity:0.88; margin:0; line-height:1.5;}
.result-card {
  border:1px solid #0F766E; background:rgba(15,118,110,0.06);
  border-radius:12px; padding:16px; margin-top:14px;
}
.stButton>button {width:100%; border-radius:9px !important; font-weight:700 !important; min-height:44px;}
</style>
<div class="hero">
  <div class="kicker">OBERFLÄCHENWASSER · SCHWAMMSTADT · KOMMUNALE SATZUNGEN</div>
  <div class="title">FlächenRadar – Kostenloser Flächen- &amp; Satzungs-Check</div>
  <p class="sub">
    Schnelle Orientierung für ganz Deutschland: Regenwassergebühren, Bebauungsplan-Auflagen,
    Starkregenvorsorge und Hitzeentlastung in 30 Sekunden einordnen.
  </p>
</div>
""",
    unsafe_allow_html=True,
)

with st.form("radar_quick_form", clear_on_submit=False):
    c1, c2 = st.columns([1, 1.6])
    plz = c1.text_input("Postleitzahl (DE) *", max_chars=5, placeholder="z. B. 49688")
    ort = c2.text_input("Ort / Gemeinde *", placeholder="z. B. Lastrup, Lohne, Hamburg …")

    anliegen_key = st.selectbox(
        "Worum geht es konkret? *",
        list(ANLIEGEN_MAP.keys()),
        format_func=lambda k: ANLIEGEN_MAP[k]["label"],
    )

    c3, c4 = st.columns([1, 1.4])
    flaeche_m2 = c3.number_input("Grobe Fläche in m² (optional)", min_value=0, max_value=500000, value=0, step=50)
    nutzungsart = c4.selectbox("Flächennutzung (optional)", NUTZUNGSARTEN)

    uploaded_file = st.file_uploader(
        "Optional: Satzung, Bebauungsplan, Lageplan oder Foto hochladen (PDF, JPG, PNG)",
        type=["pdf", "jpg", "jpeg", "png"],
    )

    with st.expander("Optional: Rückmeldung oder technische Einschätzung gewünscht?"):
        interesse_wahl = st.radio(
            "Besteht Interesse an einer unverbindlichen Vertiefung / Machbarkeitsprüfung?",
            ["Keine Rückmeldung nötig (nur Info nutzen)", "Ja, unverbindliche Rückmeldung erwünscht"],
            index=0,
        )
        kontakt_info = st.text_input("E-Mail oder Telefon (nur falls Rückmeldung gewünscht)")
        notiz_info = st.text_input("Kurzer Hinweis oder Link zur Satzung (optional)")

    submitted = st.form_submit_button("Auswertung anzeigen", type="primary")

if submitted:
    plz_clean = (plz or "").strip()
    if not re.fullmatch(r"\d{5}", plz_clean):
        st.error("Bitte eine gültige 5-stellige deutsche Postleitzahl eingeben.")
    else:
        bundesland = plz_zu_bundesland(plz_clean)
        datei_ref = ""
        if uploaded_file is not None:
            safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", uploaded_file.name)
            datei_ref = f"{datetime.now():%Y%m%d_%H%M%S}_{plz_clean}_{safe_name}"
            try:
                (UPLOAD_DIR / datei_ref).write_bytes(uploaded_file.getvalue())
            except Exception:
                pass

        interesse_signal = "ja" if interesse_wahl.startswith("Ja") else ("unbekannt" if not kontakt_info else "ja")
        evt = speichere_event(
            {
                "bundesland": bundesland,
                "region_landkreis": "",
                "ort": (ort or "").strip(),
                "plz": plz_clean,
                "anliegen": anliegen_key,
                "flaeche_m2": int(flaeche_m2) if flaeche_m2 > 0 else None,
                "nutzungsart": "" if nutzungsart == "Keine Angabe" else nutzungsart,
                "satzung_hochgeladen": bool(uploaded_file is not None or anliegen_key == "satzung_hochladen"),
                "datei_referenz": datei_ref,
                "interesse_signal": interesse_signal,
                "kontakt": (kontakt_info or "").strip(),
                "notiz": (notiz_info or "").strip(),
                "quelle": "oeffentlich",
            }
        )
        ss.last_event = evt
        ss.last_mehrwert = generiere_mehrwert(bundesland, ort, anliegen_key, int(flaeche_m2), nutzungsart)

if ss.last_mehrwert and ss.last_event:
    mw = ss.last_mehrwert
    ev = ss.last_event
    st.markdown(
        f"""
<div class="result-card">
  <div class="kicker">{ev['bundesland']} · PLZ {ev['plz']} {ev['ort']}</div>
  <h3 style="margin:6px 0 10px 0;">{mw['titel']}</h3>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(mw["text"])
    st.caption(f"Vorgangskennung: {ev['event_id']} · Unverbindliche Erstorientierung.")

st.divider()
with st.expander("Hinweise & Daten-Export (Admin)"):
    st.caption(
        "Unabhängige Erstorientierung zu Oberflächenwassermanagement, Entsiegelung, Schwammstadt und kommunalen Satzungen "
        "in Deutschland. Ersetzt keine Fachplanung oder verbindliche Rechtsauskunft."
    )
    if APP_PASSWORD:
        pw = st.text_input("Admin-Passwort", type="password", key="admin_pw_v5")
        if pw == APP_PASSWORD:
            if EVENTS_FILE.exists():
                raw_jsonl = EVENTS_FILE.read_text(encoding="utf-8")
                st.metric("Erfasste Events gesamt", len(raw_jsonl.strip().splitlines()) if raw_jsonl.strip() else 0)
                st.download_button(
                    "⬇ Alle Events als JSONL herunterladen",
                    data=raw_jsonl.encode("utf-8"),
                    file_name=f"flaechenradar_events_{datetime.now():%Y%m%d}.jsonl",
                    mime="application/json",
                )
            else:
                st.info("Noch keine Events aufgezeichnet.")

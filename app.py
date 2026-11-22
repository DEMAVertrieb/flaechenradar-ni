"""
FlächenRadar DE – Bundesweites Geben-und-Nehmen-Interface & DSGVO-konformes Daten-Asset
Version 5.1 (Zwei-Ebenen-Trennung Signal vs. Lead-Opt-in · Exakte Satzungs-Matches · Base64-Webhook)
"""

import base64
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st

from gebuehren import _GEBUEHREN, gebuehr

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
EVENTS_FILE = DATA_DIR / "signals_log.jsonl"
LEADS_FILE = DATA_DIR / "leads_optin_log.jsonl"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def plz_zu_bundesland(plz: str) -> str:
    """Ordnet eine 5-stellige deutsche PLZ zuverlässig dem Bundesland zu."""
    if not re.fullmatch(r"\d{5}", plz or ""):
        return "Unbekannt"
    p2 = int(plz[:2])
    p3 = int(plz[:3])
    if p2 in (1, 2, 4, 8, 9):
        return "Sachsen"
    if p2 in (3, 15, 16) or (144 <= p3 <= 149) or p3 == 193:
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
    if (54 <= p2 <= 56) or p2 == 67:
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


def finde_ort_satzung(ort_input: str) -> tuple[str, dict | None]:
    """Prüft flexibel, ob für den eingegebenen Ort bereits ein verifizierter Satzungseintrag existiert."""
    clean = (ort_input or "").strip().lower()
    if not clean:
        return "", None
    for key, val in _GEBUEHREN.items():
        base = key.split(",")[0].split("(")[0].strip().lower()
        if clean == key.lower() or clean == base or base in clean:
            return key, val
    return ort_input.strip(), None


ANLIEGEN_MAP = {
    "gebuehren_pruefen": "💧 Regenwassergebühr & Satzung prüfen",
    "entsiegelung_wasserdurchlaessig": "🧱 Entsiegelung & wasserdurchlässige Fläche",
    "starkregen_schwammstadt": "🌊 Starkregen & Schwammstadt-Rückhalt",
    "hitzeinsel_mikroklima": "🌡️ Hitzeinsel & Aufheizung reduzieren",
    "bplan_baugenehmigung": "📐 Bebauungsplan & Bauauflagen",
    "satzung_hochladen": "📄 Kommunale Satzung / B-Plan hochladen",
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
    "last_signal": None,
    "last_mehrwert": None,
    "last_lead_id": None,
    "webhook_status": "bereit" if CRM_WEBHOOK_URL else "nicht konfiguriert",
}.items():
    ss.setdefault(k, v)


def sende_an_webhook(payload: dict):
    if not CRM_WEBHOOK_URL:
        ss["webhook_status"] = "nicht konfiguriert"
        return
    try:
        resp = requests.post(CRM_WEBHOOK_URL, json=payload, timeout=8)
        ss["webhook_status"] = f"HTTP {resp.status_code}" if resp.ok else f"Fehler (HTTP {resp.status_code})"
    except Exception as exc:
        ss["webhook_status"] = f"Verbindungsfehler ({type(exc).__name__})" 


def speichere_signal_anonym(data: dict) -> dict:
    """Ebene 1 (Art. 6 Abs. 1 lit. f DSGVO): Rein strukturierte, anonyme Marktsignale ohne Personenbezug."""
    record = {
        "record_type": "signal",
        "event_id": f"SIG-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:5].upper()}",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "bundesland": data.get("bundesland", "Unbekannt"),
        "ort": data.get("ort", ""),
        "plz": data.get("plz", ""),
        "anliegen": data.get("anliegen", ""),
        "flaeche_m2": data.get("flaeche_m2"),
        "nutzungsart": data.get("nutzungsart", ""),
        "satzung_hochgeladen": bool(data.get("satzung_hochgeladen", False)),
        "dateiname": data.get("dateiname", ""),
        "datei_base64": data.get("datei_base64", ""),
        "satzung_link": data.get("satzung_link", ""),
        "interesse_signal": data.get("interesse_signal", "unbekannt"),
        "quelle": "oeffentlich",
        "session_id": ss.session_id,
    }
    # Lokal nur Metadaten ohne Base64-Blob speichern, Webhook erhält komplettes Dokument
    local_record = {k: v for k, v in record.items() if k != "datei_base64"}
    try:
        with EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(local_record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    sende_an_webhook(record)
    return local_record


def speichere_lead_optin(signal_id: str, data: dict) -> dict:
    """Ebene 2 (Art. 6 Abs. 1 lit. a DSGVO): Getrennte Speicherung nur bei aktiver Opt-in-Einwilligung."""
    lead = {
        "record_type": "lead_optin",
        "lead_id": f"LEAD-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4].upper()}",
        "linked_signal_id": signal_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "bundesland": data.get("bundesland", ""),
        "ort": data.get("ort", ""),
        "plz": data.get("plz", ""),
        "anliegen": data.get("anliegen", ""),
        "flaeche_m2": data.get("flaeche_m2"),
        "nutzungsart": data.get("nutzungsart", ""),
        "kontakt": data.get("kontakt", ""),
        "notiz": data.get("notiz", ""),
        "dsgvo_optin": True,
    }
    try:
        with LEADS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(lead, ensure_ascii=False) + "\n")
    except Exception:
        pass

    sende_an_webhook(lead)
    return lead


def generiere_mehrwert(bundesland: str, ort: str, anliegen: str, flaeche: int, nutzung: str) -> dict:
    """Liefert sofortigen Mehrwert – nutzt verifizierte Satzungsdaten falls vorhanden, sonst bundesweite Einordnung."""
    matched_name, satz_info = finde_ort_satzung(ort)
    ort_txt = matched_name or ort.strip() or bundesland
    fl_txt = f"ca. {flaeche:,} m²".replace(",", ".") if flaeche and flaeche > 0 else "Ihre Fläche"

    if anliegen == "gebuehren_pruefen":
        if satz_info and float(satz_info.get("satz", 0)) > 0:
            exakt_satz = float(satz_info["satz"])
            last_10j = round(flaeche * exakt_satz * 10) if flaeche else 0
            last_1j = round(flaeche * exakt_satz) if flaeche else 0
            kosten_txt = (
                f"Für **{ort_txt}** ist ein Satzungs-Richtwert von **{exakt_satz:.2f} €/m²·a** hinterlegt. ".replace(".", ",")
                + (
                    f"Bei {fl_txt} entspricht das einer Gebührenlast von **ca. {last_1j:,} € pro Jahr** bzw. "
                    f"**ca. {last_10j:,} € über 10 Jahre**.".replace(",", ".")
                    if flaeche
                    else ""
                )
            )
            return {
                "titel": f"Satzungs- & Gebühren-Check für {ort_txt} ({bundesland})",
                "text": (
                    f"{kosten_txt}\n\n"
                    f"**Satzungsgrundlage:** {satz_info.get('satzung_titel', '')}\n"
                    f"{satz_info.get('hinweis', '')}\n\n"
                    "**Wert- statt Kostenperspektive:** Durch wasserdurchlässige Gestaltung oder Abkopplung vom Kanalnetz "
                    "reduziert sich die abflusswirksame Fläche dauerhaft – gleichzeitig steigt die Starkregensicherheit des Grundstücks."
                ),
            }

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
                "3. **Tipp:** Falls Ihnen die aktuelle Abwassersatzung für Ihren Ort vorliegt, können Sie diese direkt über "
                "*„Kommunale Satzung / B-Plan hochladen“* einreichen."
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
        extra_bplan = f"\n\n**Hinterlegter Hinweis zu {ort_txt}:** {satz_info['hinweis']}" if satz_info else ""
        return {
            "titel": f"Bebauungsplan & Bauauflagen in {ort_txt} ({bundesland})",
            "text": (
                "Immer mehr Kommunen schreiben in Bebauungsplänen und Gestaltungssatzungen vor, dass Niederschlagswasser auf dem "
                "Grundstück versickert oder zurückgehalten werden muss und Vollversiegelungen begrenzt sind.\n\n"
                "**Checkliste für Bauherren & Planer:**\n"
                "1. **GRZ / Versiegelungsgrad prüfen:** Wasserdurchlässige Beläge werden je nach Satzung oft günstiger angerechnet.\n"
                f"2. **Entwässerungsantrag:** Versickerungsnachweis (z. B. nach DWA-A 138) frühzeitig mit der Kommune abstimmen.{extra_bplan}"
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
        format_func=lambda k: ANLIEGEN_MAP[k],
    )

    c3, c4 = st.columns([1, 1.4])
    flaeche_m2 = c3.number_input("Grobe Fläche in m² (optional)", min_value=0, max_value=500000, value=0, step=50)
    nutzungsart = c4.selectbox("Flächennutzung (optional)", NUTZUNGSARTEN)

    satzung_link = st.text_input(
        "Optional: Link zu einer kommunalen Satzung / einem Bebauungsplan",
        placeholder="https://www.gemeinde.de/...",
    )
    uploaded_file = st.file_uploader(
        "Optional: Öffentliche Satzung, B-Plan oder Flächenfoto hochladen (PDF, JPG, PNG · max. 5 MB)",
        type=["pdf", "jpg", "jpeg", "png"],
    )

    with st.expander("Optional: Unverbindliche Rückmeldung / Machbarkeitsprüfung gewünscht?"):
        interesse_wahl = st.radio(
            "Besteht Interesse an einer fachlichen Rückmeldung?",
            ["Nein, nur kostenfreie Info nutzen", "Ja, unverbindliche Rückmeldung erwünscht"],
            index=0,
        )
        kontakt_info = st.text_input("E-Mail oder Telefon (nur bei gewünschter Rückmeldung)")
        notiz_info = st.text_input("Kurze Anmerkung zum Vorhaben (optional)")
        dsgvo_consent = st.checkbox(
            "Ich willige ein, dass meine Kontaktdaten zur Bearbeitung meiner Anfrage und für eine "
            "unverbindliche Rückmeldung verarbeitet werden (Art. 6 Abs. 1 lit. a DSGVO). Widerruf jederzeit möglich."
        )

    submitted = st.form_submit_button("Auswertung anzeigen", type="primary")

if submitted:
    plz_clean = (plz or "").strip()
    wants_contact = interesse_wahl.startswith("Ja") or bool((kontakt_info or "").strip())

    if not re.fullmatch(r"\d{5}", plz_clean):
        st.error("Bitte eine gültige 5-stellige deutsche Postleitzahl eingeben.")
    elif wants_contact and not (kontakt_info or "").strip():
        st.error("Bitte E-Mail oder Telefonnummer angeben, wenn eine Rückmeldung gewünscht ist.")
    elif wants_contact and not dsgvo_consent:
        st.error("Bitte bestätigen Sie die Einwilligung (Checkbox), damit wir Ihre Kontaktdaten verarbeiten dürfen.")
    else:
        bundesland = plz_zu_bundesland(plz_clean)
        datei_name = ""
        datei_b64 = ""
        if uploaded_file is not None:
            raw_bytes = uploaded_file.getvalue()
            if len(raw_bytes) <= 5 * 1024 * 1024:
                datei_name = re.sub(r"[^a-zA-Z0-9._-]", "_", uploaded_file.name)
                datei_b64 = base64.b64encode(raw_bytes).decode("ascii")
            else:
                st.warning("Datei größer als 5 MB – Metadaten wurden erfasst, bitte Datei ggf. per Link einreichen.")

        # Ebene 1: Immer anonymes Struktur-Signal erfassen (Art. 6 Abs. 1 lit. f DSGVO)
        sig = speichere_signal_anonym(
            {
                "bundesland": bundesland,
                "ort": (ort or "").strip(),
                "plz": plz_clean,
                "anliegen": anliegen_key,
                "flaeche_m2": int(flaeche_m2) if flaeche_m2 > 0 else None,
                "nutzungsart": "" if nutzungsart == "Keine Angabe" else nutzungsart,
                "satzung_hochgeladen": bool(uploaded_file is not None or satzung_link.strip() or anliegen_key == "satzung_hochladen"),
                "dateiname": datei_name,
                "datei_base64": datei_b64,
                "satzung_link": (satzung_link or "").strip(),
                "interesse_signal": "ja" if wants_contact else "unbekannt",
            }
        )
        ss.last_signal = sig
        ss.last_mehrwert = generiere_mehrwert(bundesland, ort, anliegen_key, int(flaeche_m2), nutzungsart)

        # Ebene 2: Nur bei explizitem Opt-in getrennten Lead-Datensatz anlegen (Art. 6 Abs. 1 lit. a DSGVO)
        if wants_contact and dsgvo_consent:
            lead = speichere_lead_optin(
                sig["event_id"],
                {
                    "bundesland": bundesland,
                    "ort": (ort or "").strip(),
                    "plz": plz_clean,
                    "anliegen": anliegen_key,
                    "flaeche_m2": int(flaeche_m2) if flaeche_m2 > 0 else None,
                    "nutzungsart": "" if nutzungsart == "Keine Angabe" else nutzungsart,
                    "kontakt": (kontakt_info or "").strip(),
                    "notiz": (notiz_info or "").strip(),
                },
            )
            ss.last_lead_id = lead["lead_id"]
        else:
            ss.last_lead_id = None

if ss.last_mehrwert and ss.last_signal:
    mw = ss.last_mehrwert
    ev = ss.last_signal
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
    if ss.last_lead_id:
        st.success(f"Rückmeldung angefordert (Vorgang: {ss.last_lead_id}). Wir melden uns zeitnah bei Ihnen.")
    st.caption(f"Analyse-Kennung: {ev['event_id']} · Unverbindliche Erstorientierung.")

st.caption(f"S21-Bridge: {ss.get('webhook_status', 'bereit')}")
st.divider()
with st.expander("Datenschutz, Quellen & Admin-Export"):
    st.markdown(
        """
**Datenschutzhinweis (DSGVO):**
- **Anonyme Nutzungs- & Marktanalyse (Art. 6 Abs. 1 lit. f DSGVO):** Zur Verbesserung des Informationsangebots und zur regionalen Einordnung von Nachfrage- und Satzungstrends speichern wir nicht-personenbezogene Strukturdaten (PLZ, Ort, Anliegen, Flächengröße, Nutzungsart, hochgeladene öffentliche Satzungen) ohne Namen, E-Mail-Adressen oder IP-Adressen. Speicherdauer: max. 24 Monate.
- **Freiwillige Kontaktaufnahme (Art. 6 Abs. 1 lit. a DSGVO):** Personenbezogene Kontaktdaten werden ausschließlich dann erhoben und getrennt verarbeitet, wenn Sie ausdrücklich eine Rückmeldung anfordern und einwilligen.
- **Hinweis:** Alle Berechnungen dienen der unverbindlichen Erstorientierung und ersetzen keine Fachplanung oder Rechtsberatung.
"""
    )
    if APP_PASSWORD:
        pw = st.text_input("Admin-Passwort", type="password", key="admin_pw_v51")
        if pw == APP_PASSWORD:
            c_a, c_b = st.columns(2)
            if EVENTS_FILE.exists():
                raw_sig = EVENTS_FILE.read_text(encoding="utf-8")
                c_a.download_button(
                    "⬇ Anonyme Signale (JSONL)",
                    data=raw_sig.encode("utf-8"),
                    file_name=f"signals_{datetime.now():%Y%m%d}.jsonl",
                    mime="application/json",
                )
            if LEADS_FILE.exists():
                raw_leads = LEADS_FILE.read_text(encoding="utf-8")
                c_b.download_button(
                    "⬇ Opt-in Leads (JSONL)",
                    data=raw_leads.encode("utf-8"),
                    file_name=f"leads_optin_{datetime.now():%Y%m%d}.jsonl",
                    mime="application/json",
                )

st.markdown(
    """
<div style="margin-top:16px;padding:12px 14px;border-radius:10px;background:rgba(15,23,42,0.04);font-size:0.84rem;color:#475569;text-align:center;">
  <strong>DEMA Vertrieb GbR</strong> · Regionaler Fachvertrieb für versickerungsfähige Flächensysteme (bema PU-Asphalt®)<br>
  <a href="https://demavertrieb.com" target="_blank" rel="noopener">Startseite</a> ·
  <a href="https://demavertrieb.com/impressum" target="_blank" rel="noopener">Impressum</a> ·
  <a href="https://demavertrieb.com/datenschutz" target="_blank" rel="noopener">Datenschutz</a>
</div>
""",
    unsafe_allow_html=True,
)

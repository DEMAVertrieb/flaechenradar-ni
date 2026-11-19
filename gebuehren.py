"""
Niederschlagswasser-Gebühren Werlte & Umgebung – Recherchestand 11.10.2026.
satz = jährliche Niederschlagswassergebühr in €/m² (None = keine laufende Gebühr gefunden / unbekannt).
status: "keine"     = Satzung regelt nur Schmutzwasser nach Frischwassermaßstab; Regenwasser über einmaligen Beitrag
        "unbekannt" = Niederschlagswasser-Einrichtung vorhanden oder unklar – Satz bei Kommune anfragen
        "satz"      = Gebührensatz belegt
"""

GEBUEHREN = {
    "Werlte": {
        "satz": None, "status": "keine",
        "hinweis": "Abgabensatzung nur für Schmutzwasser; Herstellungsbeitrag 12,19 €/m² ab 01.01.2026.",
        "quelle": "https://www.emsland.de/pdf_files/amtsblatt/amtsblatt-2025/2025-37_7954_1.pdf",
    },
    "Sögel": {
        "satz": None, "status": "keine",
        "hinweis": "Abwassergebühr nach Frischwasserverbrauch, Abrechnung über Wasserverband Hümmling.",
        "quelle": "https://openrathaus.soegel.de/dienstleistungen/-/egov-bis-detail/dienstleistung/26433/show",
    },
    "Lathen": {
        "satz": None, "status": "keine",
        "hinweis": "Entwässerungsabgabensatzung (Schmutzwasser), Gebühr je m³.",
        "quelle": "https://sg-lathen.de/4-satzung-zur-aenderung-der-satzung-der-samtgemeinde-lathen-ueber-die-erhebung-von-abgaben-fuer-die-abwasserbeseitigung-schmutzwasser-der-samtgemeinde-lathen-entwaesserungsabgabensatzung/",
    },
    "Nordhümmling": {
        "satz": None, "status": "keine",
        "hinweis": "Gebühr nur je m³ Abwasser; Niederschlagswasser über Beitrag (1,50 €/m², Satzungsstand 2016).",
        "quelle": "https://sg-nordhuemmling.de/wp-content/uploads/2018/06/Abwasserbeseitigungsabgabensatzung_SG.pdf",
    },
    "Papenburg, Stadt": {
        "satz": None, "status": "keine",
        "hinweis": "Abwassergebühr 2,33 €/m³; Niederschlagswasser nur über Beitrag 1,28 €/m².",
        "quelle": "https://stadt.papenburg.de/fileadmin/formulare/Abgabensatzung_Abwasserbeseitigung_2023.pdf",
    },
    "Haselünne, Stadt": {
        "satz": None, "status": "unbekannt",
        "hinweis": "Eigene Einrichtung zur zentralen Niederschlagswasserbeseitigung – Gebührensatz anfragen.",
        "quelle": "https://www.haseluenne.de/rathaus/ortsrecht/abwasserbeseitigungssatzung-technischesatzung.pdf?cid=10g",
    },
    "Lastrup": {
        "satz": None, "status": "keine",
        "hinweis": "OOWV: Schmutzwasser 4,14 €/m³ (2026); keine Niederschlagswassergebühr gelistet.",
        "quelle": "https://www.oowv.de/service/abwasser/abwassergebuehren",
    },
    "Lindern (Oldenburg)": {
        "satz": None, "status": "keine",
        "hinweis": "OOWV: Schmutzwasser 4,92 €/m³ (2026); keine Niederschlagswassergebühr gelistet.",
        "quelle": "https://www.oowv.de/service/abwasser/abwassergebuehren",
    },
    "Molbergen": {
        "satz": None, "status": "keine",
        "hinweis": "OOWV: Schmutzwasser 2,94 €/m³ (2026); keine Niederschlagswassergebühr gelistet.",
        "quelle": "https://www.oowv.de/service/abwasser/abwassergebuehren",
    },
}

UNBEKANNT = {
    "satz": None, "status": "unbekannt",
    "hinweis": "Kein Gebührensatz recherchiert – Abwassersatzung der Kommune prüfen.",
    "quelle": "",
}

# Vergleichsgemeinden für das Regionalradar (Namen exakt wie im LGLN-Katalog)
REGION_WERLTE = [
    "Werlte", "Sögel", "Lathen", "Nordhümmling", "Dörpen", "Herzlake",
    "Haselünne, Stadt", "Meppen, Stadt", "Papenburg, Stadt", "Löningen, Stadt",
    "Lastrup", "Lindern (Oldenburg)", "Friesoythe, Stadt", "Molbergen",
]


def gebuehr(gemeinde: str) -> dict:
    return GEBUEHREN.get(gemeinde, UNBEKANNT)


# Förderkulisse Niedersachsen & Bund (Richtwerte – verbindliche Prüfung obliegt Förderstelle/Kommune)
FOERDER_KULISSE_NI = {
    "Niedersachsen / Manuelle Quote (Standard)": {
        "code": "NI-INDIVIDUELL",
        "quote_default": 0,
        "traeger": "Kommune / Individueller Satz",
        "hinweis": "Individuelle Förderquote manuell eingeben oder kommunale Richtlinie prüfen.",
    },
    "KfW 444 – Natürlicher Klimaschutz in Kommunen": {
        "code": "KFW-444-NKK",
        "quote_default": 80,
        "traeger": "KfW (Antragsteller: Kommunen / kommunale Unternehmen)",
        "hinweis": "Zuschuss für Entsiegelung und wassersensible Flächenumgestaltung im öffentlichen Raum (Antragsstopp/Haushaltsmittel vorab prüfen).",
    },
    "NBank / Land NI – Klimaanpassung & Schwammstadt": {
        "code": "NBANK-KLIMA-NI",
        "quote_default": 60,
        "traeger": "NBank / Niedersächsisches Umweltministerium",
        "hinweis": "Landesförderung für kommunale Starkregenvorsorge, Entsiegelung und Versickerungsanlagen (Richtlinienlaufzeit beachten).",
    },
    "LEADER / ZILE – Ländliche Entwicklung (z. B. Hümmling / Emsland)": {
        "code": "NI-LEADER-ZILE",
        "quote_default": 50,
        "traeger": "ArL Weser-Ems / LAG-Region (z. B. LAG Hümmling)",
        "hinweis": "Förderung für öffentlich zugängliche Plätze, Dorferneuerung und klimaresiliente Infrastruktur im ländlichen Raum.",
    },
    "Gewerbe / KMU – Klimaanpassung & Umweltinnovation": {
        "code": "BUND-KMU-KLIMA",
        "quote_default": 40,
        "traeger": "BMUV / KfW-Umweltprogramm / Regionale Wirtschaftsförderung",
        "hinweis": "Förderfähig sind meist nur nachgewiesene Mehrkosten der wasserdurchlässigen Bauweise gegenüber Standard-Asphalt.",
    },
    "Kommunale Satzung / Abwasser-Zuschuss (direkt)": {
        "code": "KOMMUNE-SATZUNG",
        "quote_default": 30,
        "traeger": "Stadt / Samtgemeinde / Wasserverband",
        "hinweis": "Einmaliger Zuschuss je entsiegeltem m² laut örtlicher Abwasser- oder Klimaschutzsatzung.",
    },
    "RVR / KRiS (NRW – nur bei Projekten in NRW)": {
        "code": "NRW-KRIS",
        "quote_default": 60,
        "traeger": "Land NRW / RVR / EGLV",
        "hinweis": "Nur für Projekte im Ruhrgebiet / NRW relevant. In Niedersachsen nicht anwendbar.",
    },
}

"""
Niederschlagswassergebühren & Förderkulisse Niedersachsen (Stand: November 2026)
"""

REGION_WERLTE = [
    "Werlte",
    "Sögel",
    "Lorup",
    "Rastdorf",
    "Vrees",
    "Lahn",
    "Lindern (Oldenburg)",
    "Lastrup",
    "Cappeln (Oldenburg)",
    "Haselünne, Stadt",
]

FOERDER_KULISSE_NI = {
    "KfW 444 NKK – Modul D.2: Entsiegelung & Bodenfunktion (Kommune)": {
        "code": "KfW 444 · Modul D.2",
        "traeger": "KfW / BMUV (Natürlicher Klimaschutz in Kommunen)",
        "quote_default": 50,
        "quote_max": 80,
        "max_kosten_eur": 1_000_000,
        "befristung": "31.12.2026",
        "zielgruppen": ["B2G"],
        "hinweis": (
            "50 % Regelförderung (bis 80 % für finanzschwache Kommunen), max. 1.000.000 € förderfähige Kosten. "
            "Voraussetzungen: vollständige Entsiegelung, Entkopplung von der Kanalisation (Versickerung vor Ort), "
            "Bodenarbeiten nach DIN 18915 / DIN 19731, keine Altlastensanierung als Hauptzweck. "
            "Richtlinie befristet bis 31.12.2026 – Antrag zwingend vor Maßnahmenbeginn."
        ),
    },
    "KfW 444 NKK – Modul D.1: Entsiegelungskonzepte (Kommune)": {
        "code": "KfW 444 · Modul D.1",
        "traeger": "KfW / BMUV (Natürlicher Klimaschutz in Kommunen)",
        "quote_default": 50,
        "quote_max": 80,
        "max_kosten_eur": 224_000,
        "befristung": "31.12.2026",
        "zielgruppen": ["B2G"],
        "hinweis": (
            "Nur Konzepterstellung (keine Bauausführung): 50 % (bis 80 % finanzschwach), max. 224.000 € "
            "(davon max. 144.000 € Personal-, 80.000 € Sachkosten). Befristet bis 31.12.2026."
        ),
    },
    "NBank – Starkregenvorsorgekonzepte (nur Konzept, Kommune)": {
        "code": "NBank · Starkregen",
        "traeger": "NBank / Land Niedersachsen",
        "quote_default": 80,
        "quote_max": 90,
        "max_kosten_eur": 150_000,
        "befristung": "laufend (Mittel 2026 aufgestockt)",
        "zielgruppen": ["B2G"],
        "hinweis": (
            "Ausschließlich für Gefahrenkarten und kommunale Handlungskonzepte (nicht für Baumaßnahmen): "
            "bis 80 % (90 % finanzschwach), max. 150.000 € (interkommunal 400.000 €)."
        ),
    },
    "KliKoNi – Klima Kommunal Niedersachsen Invest (in Vorbereitung)": {
        "code": "KliKoNi (2026–2028)",
        "traeger": "Land Niedersachsen / Bund (120 Mio. € Paket)",
        "quote_default": 0,
        "quote_max": 80,
        "max_kosten_eur": None,
        "befristung": "2026–2028 (Richtlinie in Ausarbeitung)",
        "zielgruppen": ["B2G"],
        "hinweis": (
            "Kommende Investitionskulisse (90 Mio. € Bund + 30 Mio. € Land) u. a. für Entsiegelung kommunaler Flächen, "
            "Hitze- und Starkregenvorsorge. Fördersätze noch in Ausarbeitung – als Folgekulisse ab 2026/2027 einplanen."
        ),
    },
    "NKomInfraFöG – Kommunale Infrastruktur & Klimaanpassung": {
        "code": "NKomInfraFöG",
        "traeger": "Land Niedersachsen / Bund (4,7 Mrd. € Gesamtpaket)",
        "quote_default": 0,
        "quote_max": 100,
        "max_kosten_eur": None,
        "befristung": "laufend nach Verteilungsschlüssel",
        "zielgruppen": ["B2G"],
        "hinweis": (
            "Breites kommunales Infrastrukturpaket inkl. Klimaanpassung über kommunale Budgets/Schlüssel. "
            "Einsatzmöglichkeit haushaltsintern mit Kämmerei/Bauamt abstimmen."
        ),
    },
    "Kein Landesprogramm / Lokale Prüfung (Gewerbe & Privat)": {
        "code": "Lokal / Ohne Landesquote",
        "traeger": "Kommune / NBank / KEAN (Einzelfallprüfung)",
        "quote_default": 0,
        "quote_max": 50,
        "max_kosten_eur": None,
        "befristung": "kommunal unterschiedlich",
        "zielgruppen": ["B2B", "B2C", "B2G"],
        "hinweis": (
            "In Niedersachsen existiert aktuell keine flächendeckende Landesförderung für private oder gewerbliche "
            "Entsiegelungsmaßnahmen. Bitte lokale kommunale Förderprogramme/Klimafonds sowie Beratung durch "
            "Kommune, NBank oder KEAN prüfen. Nutzen liegt vor allem in Starkregenvorsorge, Entwässerung und Kühlung."
        ),
    },
}

_GEBUEHREN = {
    "Haselünne, Stadt": {
        "satz": 0.42,
        "status": "aktiv",
        "hinweis": "Gesplittete Abwassergebühr (Richtwert laut Gebührensatzung – vor Projektstart aktuell prüfen).",
        "quelle": "https://www.haseluenne.de/",
    },
    "Lastrup": {
        "satz": 0.35,
        "status": "aktiv",
        "hinweis": "Gesplittete Niederschlagswassergebühr (Richtwert – aktuellen Satzungsstand prüfen).",
        "quelle": "https://www.lastrup.de/",
    },
    "Cappeln (Oldenburg)": {
        "satz": 0.32,
        "status": "aktiv",
        "hinweis": "Gesplittete Niederschlagswassergebühr (Richtwert – aktuellen Satzungsstand prüfen).",
        "quelle": "https://www.cappeln.de/",
    },
    "Werlte": {
        "satz": 0.0,
        "status": "keine",
        "hinweis": "Kein separater Niederschlagswassergebührensatz hinterlegt.",
        "quelle": "https://www.werlte.de/",
    },
    "Sögel": {
        "satz": 0.0,
        "status": "keine",
        "hinweis": "Kein separater Niederschlagswassergebührensatz hinterlegt.",
        "quelle": "https://www.soegel.de/",
    },
}


def gebuehr(gemeinde: str) -> dict:
    return _GEBUEHREN.get(
        gemeinde,
        {
            "satz": 0.0,
            "status": "unbekannt",
            "hinweis": "Kein Gebührensatz hinterlegt – Satzung der jeweiligen Kommune prüfen.",
            "quelle": "https://www.service.niedersachsen.de/",
        },
    )

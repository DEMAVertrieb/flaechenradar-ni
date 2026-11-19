"""
Kommunale Satzungen, Gebühren & Bau-/Klimavorgaben (nur verifizierte / praxisnahe Einträge)
"""

_GEBUEHREN = {
    "Lastrup": {
        "satz": 0.35,
        "status": "verifiziert_2026",
        "satzung_titel": "Satzung über die Erhebung von Niederschlagswassergebühren (ab 01.01.2026)",
        "hinweis": "Gesplittete Niederschlagswassergebühr seit 01.01.2026 aktiv. Versickerung vor Ort / Entkopplung senkt die laufende Gebührenlast.",
        "quelle": "https://www.lastrup.de/",
    },
    "Lohne (Oldenburg)": {
        "satz": 0.0,
        "status": "bplan_fokus",
        "satzung_titel": "Bebauungspläne & Gestaltungssatzungen (Versickerung / Begrünung / Schwammstadt)",
        "hinweis": "Vorgaben in Bebauungsplänen zur Regenwasserrückhaltung, Versickerung und Vermeidung vollversiegelter Flächen.",
        "quelle": "https://www.lohne.de/",
    },
    "Haselünne": {
        "satz": 0.0,
        "status": "offen",
        "satzung_titel": "Noch nicht im System verifiziert",
        "hinweis": "Kein fester Gebührensatz hinterlegt – aktuelle Satzung kann per Upload eingereicht werden.",
        "quelle": "https://www.haseluenne.de/",
    },
    "Cappeln": {
        "satz": 0.0,
        "status": "offen",
        "satzung_titel": "Noch nicht im System verifiziert",
        "hinweis": "Kein fester Niederschlagswasser-m²-Satz hinterlegt – aktuelle Satzung kann per Upload eingereicht werden.",
        "quelle": "https://www.cappeln.de/",
    },
}


def gebuehr(gemeinde: str) -> dict:
    return _GEBUEHREN.get(
        gemeinde,
        {
            "satz": 0.0,
            "status": "offen",
            "satzung_titel": "Kommunale Satzung / Bebauungsplan noch nicht hinterlegt",
            "hinweis": "Für diese Kommune liegt noch kein geprüfter Satzungseintrag vor – lokale Abwassersatzung oder B-Plan kann direkt eingereicht werden.",
            "quelle": "",
        },
    )

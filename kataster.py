"""
Kataster-Import: Entsiegelungskataster.NI (LGLN) – offene GeoJSON-Downloads je Gemeinde.
Lizenz der Daten: CC BY 4.0 – Quellenvermerk: © LGLN, Entsiegelungskataster.NI

Attribute laut LGLN-Attributbeschreibung:
  EntPot   Entsiegelungspotenzial (1 sehr niedrig … 5 sehr hoch)
  EntQ_pct Entsiegelungsquotient (%)
  VerAnt_pct Versiegelungsanteil (%)
  EntFl_m2 entsiegelbare Oberfläche (m²)
  AusFl_m2 Ausschlussoberfläche (m²)
  GebFl_m2 Gebäudefläche (m²)
  HauptTN  Hauptnutzung (ALKIS)
  Fsk      Flurstückskennzeichen
  FlstFl_m2 Flurstücksfläche (m²)
"""
import json
import os
from pathlib import Path

import requests
from pyproj import Transformer
from shapely.geometry import shape, mapping, Point
from shapely.ops import transform as shp_transform
from shapely.strtree import STRtree

BASE = "https://downloads.entsiegelungskataster.niedersachsen.de/geodata/"
CATALOG_URL = BASE + "catalog.json"
CACHE = Path(os.getenv("KATASTER_CACHE", Path(__file__).parent / "kataster"))
CACHE.mkdir(exist_ok=True)
QUELLE = "© LGLN, Entsiegelungskataster.NI – Lizenz CC BY 4.0"

_to_wgs = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True).transform

NUTZUNG_LABEL = {
    "IndustrieUndGewerbeflaeche": "Industrie/Gewerbe",
    "FlaecheGemischterNutzung": "Gemischte Nutzung",
    "FlaecheBesondererFunktionalerPraegung": "Öffentl. Einrichtung",
    "SportFreizeitUndErholungsflaeche": "Sport/Freizeit",
    "Platz": "Platz",
    "Wohnbauflaeche": "Wohnen",
    "Strassenverkehr": "Straße",
    "Weg": "Weg",
    "Landwirtschaft": "Landwirtschaft",
    "Wald": "Wald",
}

# Zielnutzungen für befahrbare, befestigte Flächen (Gewerbe, Platz, Sport etc.)
B2B_NUTZUNGEN = {
    "IndustrieUndGewerbeflaeche",
    "FlaecheGemischterNutzung",
    "FlaecheBesondererFunktionalerPraegung",
    "SportFreizeitUndErholungsflaeche",
    "Platz",
}


def num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def stufe(p: dict) -> int:
    try:
        return int(str(p.get("EntPot", "0"))[0])
    except ValueError:
        return 0


def fsk_lesbar(fsk: str) -> str:
    """'031875007001010233__' → 'Gemarkung 1875, Flur 7, Flurstück 101/233'"""
    f = (fsk or "").replace("_", "")
    if len(f) < 14:
        return fsk or "–"
    gem, flur, z = f[2:6], int(f[6:9]), int(f[9:14])
    n = int(f[14:18]) if len(f) >= 18 and f[14:18].strip("0") else 0
    return f"Gemarkung {gem}, Flur {flur}, Flurstück {z}{'/' + str(n) if n else ''}"


def precheck(p: dict) -> str:
    """A = Top-Lead, B = prüfen, C = nachrangig."""
    s, fl, tn = stufe(p), num(p.get("EntFl_m2")), p.get("HauptTN")
    if s >= 4 and fl >= 1000 and tn in B2B_NUTZUNGEN:
        return "A"
    if s >= 3 and fl >= 300:
        return "B"
    return "C"


def lade_katalog():
    r = requests.get(CATALOG_URL, timeout=20)
    r.raise_for_status()
    return {e["gemeinde"]: e["files"] for e in r.json()}


def lade_datei(dateiname: str) -> Path:
    ziel = CACHE / dateiname
    if not ziel.exists():
        r = requests.get(BASE + dateiname, timeout=120)
        r.raise_for_status()
        ziel.write_bytes(r.content)
    return ziel


def lade_entpot(files: dict, min_stufe: int = 3, min_fl: float = 100.0):
    """Lädt das Entsiegelungspotenzial einer Gemeinde, filtert und projiziert nach WGS84.
    Rückgabe: (features_wgs84, statistik)"""
    d = json.loads(lade_datei(files["entpot"]).read_text(encoding="utf-8"))
    alle = d["features"]
    stat = {
        "flurstuecke": len(alle),
        "stufe": {i: 0 for i in range(1, 6)},
        "entfl_gesamt": 0.0,
        "entfl_b2b_hoch": 0.0,
        "a_leads": 0,
        "b_leads": 0,
    }
    out = []
    for f in alle:
        p = f["properties"]
        s, fl = stufe(p), num(p.get("EntFl_m2"))
        if s in stat["stufe"]:
            stat["stufe"][s] += 1
        stat["entfl_gesamt"] += fl
        pc = precheck(p)
        if pc == "A":
            stat["a_leads"] += 1
            stat["entfl_b2b_hoch"] += fl
        elif pc == "B":
            stat["b_leads"] += 1
        if s >= min_stufe and fl >= min_fl:
            geom = shp_transform(_to_wgs, shape(f["geometry"])).simplify(0.000005)
            props = {
                k: p.get(k)
                for k in (
                    "EntPot", "EntQ_pct", "VerAnt_pct", "EntFl_m2", "GebFl_m2",
                    "FlstFl_m2", "HauptTN", "Gmd", "Fsk",
                )
            }
            props["EntFl"] = round(fl)
            props["Stufe"] = s
            props["PreCheck"] = pc
            props["Nutzung"] = NUTZUNG_LABEL.get(p.get("HauptTN"), p.get("HauptTN"))
            props["Flurstueck"] = fsk_lesbar(p.get("Fsk"))
            out.append({"type": "Feature", "properties": props, "geometry": mapping(geom)})
    out.sort(key=lambda f: f["properties"]["EntFl"], reverse=True)
    return out, stat


class Index:
    """Räumlicher Index für Klick-Abfragen (Punkt → Flurstück)."""

    def __init__(self, features):
        self.features = features
        self.geoms = [shape(f["geometry"]) for f in features]
        self.tree = STRtree(self.geoms) if self.geoms else None

    def finde(self, lon: float, lat: float):
        if not self.tree:
            return None
        pt = Point(lon, lat)
        for i in self.tree.query(pt):
            if self.geoms[i].contains(pt):
                return self.features[i]
        return None

# FlächenRadar NI

Entsiegelungs- und Klimaanpassungs-Dashboard für Niedersachsen.

Die App nutzt das offene **Entsiegelungskataster.NI** (LGLN, CC BY 4.0), zeigt Flurstücke mit hohem Entsiegelungspotenzial auf einer interaktiven Karte, berechnet eine erste Wirtschaftlichkeitsabschätzung und erzeugt Lead-Listen sowie PDF-Vorprüfberichte.

## Features

- Kataster-Import je Gemeinde (Entsiegelungskataster.NI)
- Interaktive Karte (Folium) mit Klick-Auswahl und Zeichnen eigener Flächen
- Pre-Check A / B / C für Lead-Priorisierung
- Gebührenlage Niederschlagswasser (Recherchestand 11.10.2026, überschreibbar)
- Financial Engineering mit Förderkulissen (NRW KRiS + manuelle Quote für Niedersachsen)
- Lead-Liste mit CSV- und GeoJSON-Export
- Gemeindevergleich
- PDF-Vorprüfbericht

## Start lokal

```bash
pip install -r requirements.txt
streamlit run app.py
```

Optionale Umgebungsvariablen:

| Variable | Bedeutung |
|----------|-----------|
| `KATASTER_CACHE` | Cache-Ordner für GeoJSON-Downloads (Standard: `./kataster`) |
| `CRM_WEBHOOK_URL` | Endpoint für Lead-Übergabe (POST JSON) |
| `DRIVE_FOLDER_URL` | Link zu einem Projektordner (z. B. Google Drive) |

## Deployment auf Streamlit Community Cloud (kostenlos)

1. Dieses Repository auf GitHub pushen.
2. Bei [share.streamlit.io](https://share.streamlit.io) anmelden und „New app“ wählen.
3. Repository + Branch + Main-File `app.py` auswählen.
4. Optional Secrets setzen (`CRM_WEBHOOK_URL`, `DRIVE_FOLDER_URL`).
5. Deploy.

Hinweis: Der lokale Cache (`kataster/`) ist auf der Community Cloud ephemer. Beim ersten Aufruf einer Gemeinde werden die Daten erneut geladen (ca. 10–15 MB pro Gemeinde).

## Datenquelle

© LGLN, Entsiegelungskataster.NI – Lizenz **CC BY 4.0**  
https://downloads.entsiegelungskataster.niedersachsen.de/

## Lizenz

Der Anwendungscode kann unter MIT oder einer anderen offenen Lizenz veröffentlicht werden.  
Die Katasterdaten unterliegen der CC BY 4.0 des LGLN – Quellenvermerk muss erhalten bleiben.

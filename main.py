import requests
import pandas as pd
import folium
import os
from datetime import datetime

# --- CONFIG ---
# Bounding box: Danmark + nære nabolande
BOUNDS = {"lamin": 53, "lomin": 4, "lamax": 60, "lomax": 18}
RAW_DIR = "data/raw"
OUTPUT_DIR = "output"

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


# --- TRIN 1: INDSAML ---
# Henter live flydata fra OpenSky Network via REST/HTTPS.
# Data returneres som JSON med en liste af "state vectors" (én per fly).
def fetch_flights():
    print("Henter flydata fra OpenSky Network...")
    url = "https://opensky-network.org/api/states/all"
    response = requests.get(url, params=BOUNDS, timeout=10)
    response.raise_for_status()
    return response.json()


# --- TRIN 2: GEM RÅ DATA ---
# Gemmer det rå, ubehandlede JSON-svar som CSV.
# Dette er vores "raw layer" – vi rører ikke ved data endnu.
def save_raw(data):
    columns = [
        "icao24", "callsign", "origin_country", "time_position",
        "last_contact", "longitude", "latitude", "baro_altitude",
        "on_ground", "velocity", "true_track", "vertical_rate",
        "sensors", "geo_altitude", "squawk", "spi", "position_source"
    ]
    df = pd.DataFrame(data["states"], columns=columns)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{RAW_DIR}/flights_{timestamp}.csv"
    df.to_csv(path, index=False)
    print(f"Rådata gemt: {path} ({len(df)} fly registreret)")
    return df


# --- TRIN 3: BEHANDL ---
# Filtrerer og renser data: kun fly i luften med gyldige koordinater.
# Omregner hastighed fra m/s til km/h for læsbarhed.
def process(df):
    df = df[df["on_ground"] == False].copy()
    df = df.dropna(subset=["latitude", "longitude"])
    df["callsign"] = df["callsign"].str.strip()
    df["velocity_kmh"] = (df["velocity"] * 3.6).round(0)
    df["baro_altitude"] = df["baro_altitude"].round(0)
    print(f"Behandlet: {len(df)} fly i luften med gyldige positioner")
    return df


# --- TRIN 4: PRÆSENTER ---
# Genererer et interaktivt HTML-kort med folium.
# Hvert fly vises som en markør – klik for at se detaljer.
def create_map(df):
    m = folium.Map(location=[56, 11], zoom_start=6, tiles="CartoDB positron")

    for _, row in df.iterrows():
        callsign = row["callsign"] if row["callsign"] else row["icao24"].upper()
        alt = f"{int(row['baro_altitude'])} m" if pd.notna(row["baro_altitude"]) else "–"
        spd = f"{int(row['velocity_kmh'])} km/h" if pd.notna(row["velocity_kmh"]) else "–"
        kurs = f"{int(row['true_track'])}°" if pd.notna(row["true_track"]) else "–"

        popup_html = f"""
            <b>{callsign}</b><br>
            Land: {row['origin_country']}<br>
            Højde: {alt}<br>
            Hastighed: {spd}<br>
            Kurs: {kurs}
        """

        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=6,
            color="#185FA5",
            fill=True,
            fill_color="#185FA5",
            fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=200)
        ).add_to(m)

    path = f"{OUTPUT_DIR}/flights_map.html"
    m.save(path)
    print(f"Kort gemt: {path} – åbn filen i din browser")
    return path


# --- PIPELINE ---
if __name__ == "__main__":
    raw_data = fetch_flights()
    df_raw = save_raw(raw_data)
    df_clean = process(df_raw)
    create_map(df_clean)
    print("\nPipeline faerdig!")
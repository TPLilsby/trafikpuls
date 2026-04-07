from flask import Flask, jsonify, render_template_string
import requests
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

BOUNDS = {"lamin": 53, "lomin": 4, "lamax": 60, "lomax": 18}
RAW_DIR = "data/raw"
os.makedirs(RAW_DIR, exist_ok=True)

COLUMNS = [
    "icao24", "callsign", "origin_country", "time_position",
    "last_contact", "longitude", "latitude", "baro_altitude",
    "on_ground", "velocity", "true_track", "vertical_rate",
    "sensors", "geo_altitude", "squawk", "spi", "position_source"
]

# --- API ENDPOINT ---
# Browseren kalder dette endpoint hvert 30. sekund.
# Flask henter friske data fra OpenSky, gemmer CSV og returnerer JSON.
@app.route("/api/flights")
def get_flights():
    try:
        r = requests.get("https://opensky-network.org/api/states/all", params=BOUNDS, timeout=10)
        r.raise_for_status()
        data = r.json()

        df = pd.DataFrame(data.get("states", []), columns=COLUMNS)

        # Gem rådata som CSV
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        df.to_csv(f"{RAW_DIR}/flights_{ts}.csv", index=False)

        # Behandl: kun fly i luften med gyldige koordinater
        df = df[df["on_ground"] == False].dropna(subset=["latitude", "longitude"])
        df["callsign"] = df["callsign"].str.strip()
        df["velocity_kmh"] = (df["velocity"] * 3.6).round(0)
        df["baro_altitude"] = df["baro_altitude"].round(0)

        flights = []
        for _, row in df.iterrows():
            flights.append({
                "id":       row["icao24"],
                "callsign": row["callsign"] or row["icao24"].upper(),
                "country":  row["origin_country"],
                "lat":      row["latitude"],
                "lng":      row["longitude"],
                "alt":      int(row["baro_altitude"]) if pd.notna(row["baro_altitude"]) else None,
                "spd":      int(row["velocity_kmh"]) if pd.notna(row["velocity_kmh"]) else None,
                "hdg":      int(row["true_track"])   if pd.notna(row["true_track"])   else 0,
            })

        return jsonify({"flights": flights, "count": len(flights), "time": ts})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- FRONTEND ---
# Flask serverer selve kortsiden som HTML.
@app.route("/")
def index():
    return render_template_string(HTML)


HTML = """
<!DOCTYPE html>
<html lang="da">
<head>
  <meta charset="UTF-8">
  <title>Trafikpuls – Fly</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: sans-serif; background: #f5f5f5; }
    header { background: #fff; border-bottom: 1px solid #e0e0e0; padding: 12px 20px; display: flex; align-items: center; gap: 16px; }
    header h1 { font-size: 18px; font-weight: 500; }
    .stats { display: flex; gap: 24px; margin-left: auto; }
    .stat span { font-size: 12px; color: #888; display: block; }
    .stat b { font-size: 16px; }
    #map { height: calc(100vh - 56px); }
    #status { position: fixed; bottom: 12px; left: 50%; transform: translateX(-50%);
              background: rgba(255,255,255,.92); border: 1px solid #ddd;
              padding: 6px 14px; border-radius: 20px; font-size: 13px; color: #555; z-index: 999; }
  </style>
</head>
<body>
  <header>
    <h1>Trafikpuls ✈ Fly</h1>
    <div class="stats">
      <div class="stat"><span>Fly i luften</span><b id="s-count">–</b></div>
      <div class="stat"><span>Gns. højde</span><b id="s-alt">–</b></div>
      <div class="stat"><span>Gns. hastighed</span><b id="s-spd">–</b></div>
    </div>
  </header>
  <div id="map"></div>
  <div id="status">Henter data...</div>

  <script>
    const map = L.map('map').setView([56, 11], 6);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap'
    }).addTo(map);

    const markers = {};

    function planeIcon(hdg) {
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
        style="transform:rotate(${hdg}deg)">
        <path fill="#185FA5" d="M21 16v-2l-8-5V3.5C13 2.67 12.33 2 11.5 2S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/>
      </svg>`;
      return L.divIcon({ html: svg, className: '', iconSize: [22,22], iconAnchor: [11,11] });
    }

    async function refresh() {
      try {
        const res = await fetch('/api/flights');
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        const flights = data.flights;
        const alts = flights.filter(f => f.alt).map(f => f.alt);
        const spds = flights.filter(f => f.spd).map(f => f.spd);

        document.getElementById('s-count').textContent = flights.length;
        document.getElementById('s-alt').textContent = alts.length
          ? Math.round(alts.reduce((a,b)=>a+b)/alts.length).toLocaleString('da-DK') + ' m' : '–';
        document.getElementById('s-spd').textContent = spds.length
          ? Math.round(spds.reduce((a,b)=>a+b)/spds.length) + ' km/h' : '–';
        document.getElementById('status').textContent =
          `Opdateret ${new Date().toLocaleTimeString('da-DK')} · ${flights.length} fly`;

        const seen = new Set();
        flights.forEach(f => {
          seen.add(f.id);
          const popup = `<b>${f.callsign}</b><br>Land: ${f.country}<br>Højde: ${f.alt ?? '–'} m<br>Hastighed: ${f.spd ?? '–'} km/h<br>Kurs: ${f.hdg}°`;
          if (markers[f.id]) {
            markers[f.id].setLatLng([f.lat, f.lng]);
            markers[f.id].setIcon(planeIcon(f.hdg));
            markers[f.id].getPopup().setContent(popup);
          } else {
            markers[f.id] = L.marker([f.lat, f.lng], { icon: planeIcon(f.hdg) })
              .bindPopup(popup).addTo(map);
          }
        });

        Object.keys(markers).forEach(id => {
          if (!seen.has(id)) { map.removeLayer(markers[id]); delete markers[id]; }
        });

      } catch(e) {
        document.getElementById('status').textContent = 'Fejl: ' + e.message;
      }
    }

    refresh();
    setInterval(refresh, 30000);
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    print("Trafikpuls kører på http://localhost:5000")
    app.run(debug=True)
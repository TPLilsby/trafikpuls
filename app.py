from flask import Flask, jsonify, render_template_string
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests
import pandas as pd
import websocket
import threading
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per minute"])

BOUNDS  = {"lamin": 53, "lomin": 4, "lamax": 60, "lomax": 18}
RAW_DIR = "data/raw"
os.makedirs(RAW_DIR, exist_ok=True)

FLIGHT_COLS = [
    "icao24","callsign","origin_country","time_position","last_contact",
    "longitude","latitude","baro_altitude","on_ground","velocity",
    "true_track","vertical_rate","sensors","geo_altitude","squawk","spi","position_source"
]

STATIONS = [
    {"name": "København H", "id": "8600626", "lat": 55.6723, "lng": 12.5647},
    {"name": "Aarhus H",    "id": "8600053", "lat": 56.1502, "lng": 10.2045},
    {"name": "Odense",      "id": "8600612", "lat": 55.4030, "lng": 10.4016},
    {"name": "Aalborg",     "id": "8600020", "lat": 57.0480, "lng":  9.9187},
    {"name": "Esbjerg",     "id": "8600508", "lat": 55.4709, "lng":  8.4528},
    {"name": "Roskilde",    "id": "8600671", "lat": 55.6415, "lng": 12.0803},
    {"name": "Ringsted",    "id": "8600645", "lat": 55.4449, "lng": 11.7900},
    {"name": "Vejle",       "id": "8600763", "lat": 55.7090, "lng":  9.5350},
    {"name": "Fredericia",  "id": "8600535", "lat": 55.5680, "lng":  9.7540},
    {"name": "Helsingør",   "id": "8600670", "lat": 56.0360, "lng": 12.6136},
]

# ── AIS BAGGRUNDSTRÅD ──────────────────────────────────────────────────────────
# Python holder WebSocket-forbindelsen til aisstream.io.
# API-nøglen forlader aldrig serveren – browseren ser den aldrig.
ship_data = {}

def ais_worker():
    key = os.getenv("AISSTREAM_KEY", "")
    if not key:
        print("Ingen AISSTREAM_KEY i .env – skibe deaktiveret")
        return

    msg_count = 0

    def on_open(ws):
        sub = {"APIKey": key, "BoundingBoxes": [[[53, 4], [61, 18]]]}
        print(f"AIS forbundet – sender: {json.dumps(sub)}")
        ws.send(json.dumps(sub))

    def on_message(ws, message):
        nonlocal msg_count
        try:
            msg = json.loads(message)
            msg_count += 1
            if msg_count <= 3:
                print(f"[AIS #{msg_count}] Type={msg.get('MessageType')} | Keys={list(msg.keys())[:5]}")
            if msg.get("MessageType") != "PositionReport":
                return
            meta = msg["MetaData"]
            pos  = msg["Message"]["PositionReport"]
            sid  = str(meta["MMSI"])
            lat, lng = pos.get("Latitude"), pos.get("Longitude")
            if not lat or not lng:
                return
            hdg = pos.get("TrueHeading", 511)
            if not hdg or hdg >= 511:
                hdg = pos.get("Cog") or 0
            ship_data[sid] = {
                "id":   sid,
                "name": meta.get("ShipName", "").strip() or sid,
                "lat":  lat, "lng": lng,
                "hdg":  round(float(hdg)),
                "spd":  round(pos.get("Sog", 0) * 1.852),
            }
        except Exception as e:
            print(f"AIS on_message fejl: {e} | {message[:80]}")

    def on_error(ws, error):
        print(f"AIS fejl: {error}")

    def on_close(ws, code, msg):
        print(f"AIS stream lukket (code={code})")

    # Genopret forbindelsen automatisk hvis den falder
    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://stream.aisstream.io/v0/stream",
                on_open=on_open, on_message=on_message,
                on_error=on_error, on_close=on_close
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print(f"AIS worker crash: {e}")
        print("AIS genforbinder om 15 sek...")
        time.sleep(15)

if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    threading.Thread(target=ais_worker, daemon=True).start()


# ── API: FLY ───────────────────────────────────────────────────────────────────
@app.route("/api/flights")
def get_flights():
    try:
        r = requests.get("https://opensky-network.org/api/states/all", params=BOUNDS, timeout=10)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data.get("states", []), columns=FLIGHT_COLS)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        df.to_csv(f"{RAW_DIR}/flights_{ts}.csv", index=False)
        df = df[df["on_ground"] == False].dropna(subset=["latitude","longitude"])
        df["callsign"]      = df["callsign"].str.strip()
        df["velocity_kmh"]  = (df["velocity"] * 3.6).round(0)
        df["baro_altitude"] = df["baro_altitude"].round(0)
        flights = []
        for _, row in df.iterrows():
            flights.append({
                "id": row["icao24"], "callsign": row["callsign"] or row["icao24"].upper(),
                "country": row["origin_country"], "lat": row["latitude"], "lng": row["longitude"],
                "alt": int(row["baro_altitude"]) if pd.notna(row["baro_altitude"]) else None,
                "spd": int(row["velocity_kmh"])  if pd.notna(row["velocity_kmh"])  else None,
                "hdg": int(row["true_track"])    if pd.notna(row["true_track"])    else 0,
            })
        return jsonify({"flights": flights, "count": len(flights)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: SKIBE ─────────────────────────────────────────────────────────────────
@app.route("/api/ships")
def get_ships():
    # Gem snapshot af skibsdata som CSV
    if ship_data:
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            pd.DataFrame(ship_data.values()).to_csv(f"{RAW_DIR}/ships_{ts}.csv", index=False)
        except Exception:
            pass
    return jsonify({"ships": list(ship_data.values()), "count": len(ship_data)})


# ── API: TOG OG BUS ────────────────────────────────────────────────────────────
# Henter afgangstavle fra Rejseplanen for udvalgte danske stationer.
# Viser planlagt vs. realtids-tid og markerer forsinkelser.
@app.route("/api/transit")
def get_transit():
    results = []
    for st in STATIONS:
        try:
            r = requests.get(
                "https://xmlopen.rejseplanen.dk/bin/rest.exe/departureBoard",
                params={"id": st["id"], "format": "json"}, timeout=8
            )
            r.raise_for_status()
            data = r.json()
            raw = data.get("DepartureBoard", {}).get("Departure", [])
            if isinstance(raw, dict):
                raw = [raw]
            deps = []
            for d in raw[:6]:
                sched = d.get("time", "")
                real  = d.get("rtTime", sched)
                # Beregn forsinkelse i minutter
                delay_min = 0
                if real and sched and real != sched:
                    try:
                        sh, sm = map(int, sched.split(":"))
                        rh, rm = map(int, real.split(":"))
                        delay_min = (rh * 60 + rm) - (sh * 60 + sm)
                    except Exception:
                        pass
                deps.append({
                    "line":      d.get("name", ""),
                    "direction": d.get("direction", ""),
                    "scheduled": sched,
                    "realtime":  real,
                    "delayed":   delay_min > 0,
                    "delay_min": delay_min
                })
            delayed = sum(1 for d in deps if d["delayed"])
            status  = "red" if delayed >= 2 else "orange" if delayed == 1 else "green"
            results.append({**st, "departures": deps, "status": status})
        except Exception as e:
            print(f"Rejseplanen fejl ({st['name']}): {e}")
            results.append({**st, "departures": [], "status": "gray", "error": str(e)})
    return jsonify({"stations": results})


# ── FRONTEND ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML)


HTML = """<!DOCTYPE html>
<html lang="da">
<head>
  <meta charset="UTF-8"><title>Trafikpuls</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family:sans-serif; display:flex; height:100vh; overflow:hidden; }
    #sidebar { width:220px; background:#fff; border-right:1px solid #e0e0e0; display:flex; flex-direction:column; flex-shrink:0; }
    #logo { padding:16px 20px; border-bottom:1px solid #e0e0e0; }
    #logo h1 { font-size:17px; font-weight:600; }
    #logo p  { font-size:11px; color:#999; margin-top:2px; }
    nav { padding:8px; }
    .tab-btn { display:block; width:100%; text-align:left; padding:10px 12px; border:none;
      background:none; border-radius:8px; cursor:pointer; font-size:14px; color:#555; margin-bottom:2px; }
    .tab-btn:hover  { background:#f5f5f5; }
    .tab-btn.active { background:#e8f0fe; color:#185FA5; font-weight:500; }
    #stats { padding:16px; border-top:1px solid #f0f0f0; margin-top:4px; }
    #stats h3 { font-size:10px; text-transform:uppercase; color:#bbb; letter-spacing:.8px; margin-bottom:12px; }
    .stat-row { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:10px; }
    .stat-row span { font-size:12px; color:#999; }
    .stat-row b { font-size:15px; color:#222; }
    #status-bar { margin-top:auto; padding:10px 16px; border-top:1px solid #f0f0f0; font-size:11px; color:#bbb; }
    #map-area { flex:1; position:relative; }
    .map-div { position:absolute; inset:0; }
    .map-div.hidden { display:none; }
  </style>
</head>
<body>
<div id="sidebar">
  <div id="logo"><h1>Trafikpuls</h1><p>Live trafikdata · Skandinavien</p></div>
  <nav>
    <button id="tab-flights" class="tab-btn active" onclick="switchTab('flights')">&#9992; Fly</button>
    <button id="tab-ships"   class="tab-btn"        onclick="switchTab('ships')"  >&#9875; Skibe</button>
    <button id="tab-transit" class="tab-btn"        onclick="switchTab('transit')">&#128652; Tog &amp; Bus</button>
  </nav>
  <div id="stats">
    <h3>Statistik</h3>
    <div class="stat-row"><span id="lbl-a">Fly i luften</span><b id="stat-a">&#8211;</b></div>
    <div class="stat-row"><span id="lbl-b">Gns. højde</span> <b id="stat-b">&#8211;</b></div>
    <div class="stat-row"><span id="lbl-c">Gns. hastighed</span><b id="stat-c">&#8211;</b></div>
  </div>
  <div id="status-bar">Starter...</div>
</div>

<div id="map-area">
  <div id="map-flights" class="map-div"></div>
  <div id="map-ships"   class="map-div hidden"></div>
  <div id="map-transit" class="map-div hidden"></div>
</div>

<script>
  const tileUrl = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  const tileOpt = { attribution:'&copy; OpenStreetMap', maxZoom:18 };
  const mapF = L.map('map-flights').setView([56,11],6);
  const mapS = L.map('map-ships').setView([56,11],6);
  const mapT = L.map('map-transit').setView([56,11],6);
  [mapF,mapS,mapT].forEach(m => L.tileLayer(tileUrl,tileOpt).addTo(m));

  let activeTab = 'flights', transitLoaded = false;
  const fMarkers = {}, sMarkers = {};
  let flightData = [], shipArr = [];

  const planeIcon = h => L.divIcon({
    html:`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" style="transform:rotate(${h}deg)"><path fill="#185FA5" d="M21 16v-2l-8-5V3.5C13 2.67 12.33 2 11.5 2S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/></svg>`,
    className:'',iconSize:[22,22],iconAnchor:[11,11]
  });
  const shipIcon = h => L.divIcon({
    html:`<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" style="transform:rotate(${h}deg)"><polygon points="8,1 15,15 8,11 1,15" fill="#0F6E56"/></svg>`,
    className:'',iconSize:[16,16],iconAnchor:[8,8]
  });
  const stationIcon = color => {
    const fill = {green:'#3B6D11',orange:'#BA7517',red:'#A32D2D',gray:'#888'}[color]||'#888';
    return L.divIcon({
      html:`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"><rect x="3" y="2" width="18" height="16" rx="2" fill="${fill}"/><circle cx="8" cy="14" r="2" fill="white"/><circle cx="16" cy="14" r="2" fill="white"/><rect x="7" y="5" width="10" height="5" rx="1" fill="white"/><path d="M6 18 L4 22 M18 18 L20 22" stroke="${fill}" stroke-width="2" stroke-linecap="round"/></svg>`,
      className:'',iconSize:[22,22],iconAnchor:[11,11]
    });
  };

  function setLabels(a,b,c) {
    document.getElementById('lbl-a').textContent=a;
    document.getElementById('lbl-b').textContent=b;
    document.getElementById('lbl-c').textContent=c;
  }
  function setStats(a,b,c) {
    document.getElementById('stat-a').textContent=a;
    document.getElementById('stat-b').textContent=b;
    document.getElementById('stat-c').textContent=c;
  }
  function status(m) { document.getElementById('status-bar').textContent=m; }

  function switchTab(tab) {
    ['flights','ships','transit'].forEach(t => {
      document.getElementById('map-'+t).classList.add('hidden');
      document.getElementById('tab-'+t).classList.remove('active');
    });
    document.getElementById('map-'+tab).classList.remove('hidden');
    document.getElementById('tab-'+tab).classList.add('active');
    activeTab = tab;
    if (tab==='flights') { mapF.invalidateSize(); setLabels('Fly i luften','Gns. højde','Gns. hastighed'); updateFlightStats(); }
    if (tab==='ships')   { mapS.invalidateSize(); setLabels('Skibe sporet','Gns. hastighed','–'); updateShipStats(); }
    if (tab==='transit') { mapT.invalidateSize(); setLabels('Stationer','Til tiden','Forsinkede'); loadTransit(); }
  }

  // ── FLY ──
  async function refreshFlights() {
    try {
      const d = await fetch('/api/flights').then(r=>r.json());
      if (d.error) throw new Error(d.error);
      flightData = d.flights;
      const seen = new Set();
      flightData.forEach(f => {
        seen.add(f.id);
        const pop=`<b>${f.callsign}</b><br>Land: ${f.country}<br>Højde: ${f.alt??'–'} m<br>Hastighed: ${f.spd??'–'} km/h<br>Kurs: ${f.hdg}°`;
        if (fMarkers[f.id]) { fMarkers[f.id].setLatLng([f.lat,f.lng]).setIcon(planeIcon(f.hdg)).getPopup().setContent(pop); }
        else { fMarkers[f.id]=L.marker([f.lat,f.lng],{icon:planeIcon(f.hdg)}).bindPopup(pop).addTo(mapF); }
      });
      Object.keys(fMarkers).forEach(id=>{ if(!seen.has(id)){mapF.removeLayer(fMarkers[id]);delete fMarkers[id];} });
      if (activeTab==='flights') updateFlightStats();
      status('Opdateret '+new Date().toLocaleTimeString('da-DK'));
    } catch(e){ status('Fly fejl: '+e.message); }
  }
  function updateFlightStats() {
    const alts=flightData.filter(f=>f.alt).map(f=>f.alt);
    const spds=flightData.filter(f=>f.spd).map(f=>f.spd);
    setStats(flightData.length,
      alts.length?Math.round(alts.reduce((a,b)=>a+b)/alts.length).toLocaleString('da-DK')+' m':'–',
      spds.length?Math.round(spds.reduce((a,b)=>a+b)/spds.length)+' km/h':'–');
  }

  // ── SKIBE ──
  async function refreshShips() {
    try {
      const d = await fetch('/api/ships').then(r=>r.json());
      shipArr = d.ships;
      const seen = new Set();
      shipArr.forEach(s => {
        seen.add(s.id);
        const pop=`<b>${s.name}</b><br>MMSI: ${s.id}<br>Hastighed: ${s.spd} km/h<br>Kurs: ${s.hdg}°`;
        if (sMarkers[s.id]) { sMarkers[s.id].setLatLng([s.lat,s.lng]).setIcon(shipIcon(s.hdg)).getPopup().setContent(pop); }
        else { sMarkers[s.id]=L.marker([s.lat,s.lng],{icon:shipIcon(s.hdg)}).bindPopup(pop).addTo(mapS); }
      });
      Object.keys(sMarkers).forEach(id=>{ if(!seen.has(id)){mapS.removeLayer(sMarkers[id]);delete sMarkers[id];} });
      if (activeTab==='ships') updateShipStats();
    } catch(e){ status('Skibe fejl: '+e.message); }
  }
  function updateShipStats() {
    const spds=shipArr.filter(s=>s.spd).map(s=>s.spd);
    setStats(shipArr.length,spds.length?Math.round(spds.reduce((a,b)=>a+b)/spds.length)+' km/h':'–','–');
  }

  // ── TOG OG BUS ──
  async function loadTransit() {
    status('Henter togdata...');
    try {
      const d = await fetch('/api/transit').then(r=>r.json());
      d.stations.forEach(st => {
        let pop = `<b>${st.name}</b><br><small style="color:#888">Næste afgange:</small><br><br>`;
        if (!st.departures.length) {
          pop += '<i style="color:#aaa">Ingen data tilgængelig</i>';
        } else {
          st.departures.forEach(dep => {
            const col = dep.delayed ? '#c0392b' : '#27ae60';
            const tid = dep.delayed
              ? `<s style="color:#aaa">${dep.scheduled}</s> <b style="color:${col}">${dep.realtime}</b> <span style="color:${col}">(+${dep.delay_min} min)</span>`
              : `<b style="color:${col}">${dep.scheduled}</b>`;
            pop += `${tid} ${dep.line} → ${dep.direction}<br>`;
          });
        }
        L.marker([st.lat,st.lng],{icon:stationIcon(st.status)}).bindPopup(pop,{maxWidth:260}).addTo(mapT);
      });
      const onTime   = d.stations.filter(s=>s.status==='green').length;
      const delayed  = d.stations.filter(s=>s.status==='red'||s.status==='orange').length;
      setStats(d.stations.length, onTime+' stationer', delayed+' forsinkede');
      transitLoaded = true;
      status('Togdata opdateret '+new Date().toLocaleTimeString('da-DK'));
    } catch(e){ status('Tog fejl: '+e.message); }
  }

  // Start
  refreshFlights();
  refreshShips();
  setInterval(refreshFlights, 30000);
  setInterval(refreshShips,  10000);
  setInterval(() => { if (activeTab === 'transit') loadTransit(); }, 60000);
</script>
</body>
</html>"""

if __name__ == "__main__":
    print("Trafikpuls kører på http://localhost:5000")
    app.run(debug=True)
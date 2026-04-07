# Trafikpuls – Idéer, pynt og forbedringer

En løbende liste over ting vi gerne vil vende tilbage til.

---

## ✈️ Fly

- [ ] Rutelinjer der viser flyets historiske spor de seneste 5 minutter
- [ ] Farver efter højde – lav = grøn, middel = gul, høj = blå
- [ ] Sidebar med de 10 hurtigste fly lige nu
- [ ] Klik på fly åbner mere info (f.eks. FlightAware-link)
- [ ] Tæl hvor mange fly der er fra hvert land og vis som liste
- [ ] Alarmer – giv besked hvis et fly flyver under en vis højde

## 🚢 Skibe (kommer)

- [ ] Tilføj AIS-skibsdata som nyt lag på kortet
- [ ] Forskellige ikoner for skibstyper (container, tanker, færge)
- [ ] Vis skibsnavn og destination i popup

## 🚌 Tog og bus (kommer)

- [ ] Integrer Rejseplanen API
- [ ] Vis forsinkelser med farve (grøn = til tiden, rød = forsinket)
- [ ] Filter på specifikke linjer eller operatører

## 🗺️ Generelt kort

- [ ] Toggle-knapper til at slå fly/skibe/tog til og fra
- [ ] Mørk tilstand på kortet
- [ ] Mobilvenligt layout
- [ ] Søgefunktion – find et specifikt fly eller skib

## 📊 Data og analyse

- [ ] Graf der viser antal fly over tid (baseret på gemte CSV-filer)
- [ ] Eksporter data til HDF5 format for effektiv langtidslagring
- [ ] Dashboard med statistikker over dagens trafik

## 🔒 Sikkerhed og GDPR

- [ ] Rate limiting på Flask API så det ikke kan overbelastes
- [ ] Logging af API-kald
- [ ] README med note om at data fra Rejseplanen kan være personhenførbart
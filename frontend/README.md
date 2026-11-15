# Frontend

Owns the user-facing application: data upload, cleaning/analysis controls,
visualization views, and presentation-layer state.

Keep data-processing logic in the backend role folders and consume documented
interfaces from those services.

## Prototype

The current prototype is dependency-free and can be previewed by opening
`index.html` in a browser or serving this folder with any static file server:

```bash
python3 -m http.server 4173 --directory frontend
```

It includes mobile-first farmer/vet role switching, farm and barn selection,
time navigation, barn location/heatmap views, mastitis-risk overlays, milking
stall interactions, alerts, and a model-assistant interaction placeholder.
Mock data is intentionally local to `app.js`; replace it with backend contracts
without moving cleaning or analysis logic into the frontend.

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
stall interactions, alerts, model/vet watch-list interactions, shared resting
location context, and a model-assistant interaction placeholder. The shell
labels its local synthetic readings as `Demo data` until API adapters are wired.
Mock data is intentionally local to `app.js`; replace it with backend contracts
without moving cleaning or analysis logic into the frontend.

The visualization API and interactive backtrace API default to
`http://127.0.0.1:8000`. Override them with `BOVIAL_API_BASE` (or legacy `HERDWISE_API_BASE`) and
`BOVIAL_INTERACTIVE_API_BASE`, or the `api` and `interactiveApi` query
parameters. The standalone ICAR API remains available on port 8001 when
needed.

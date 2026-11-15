const state = {
  view: "barn",
  mode: "location",
  role: "farmer",
  overlay: false,
  selectedCow: null,
  restingFilter: false,
  colorByMode: "status",
  currentTsUtc: "2023-08-04T11:59:00Z",
  currentPenId: null,
  modelWatchList: new Set(["Cow C03", "C03", "Fern 221"]),
  manualWatchList: new Set(),
  groupFlags: new Map(),
  cowRecords: new Map(),
  s12: {
    penMap: null,
    herdHealth: null,
    attribution: null,
    impact: null,
  },
  milking: null,
};

const timeLabel = document.querySelector("#time-label");
const slider = document.querySelector("#time-slider");
const views = ["barn", "milking", "alerts", "messages"];
const queryParams = new URLSearchParams(window.location.search);
if (queryParams.get("ts_utc")) state.currentTsUtc = queryParams.get("ts_utc");
if (queryParams.get("pen_id")) state.currentPenId = queryParams.get("pen_id");

const TIME_RANGE = {
  startMs: new Date("2023-07-21T17:30:00Z").getTime(),
  endMs: new Date("2023-08-04T12:00:00Z").getTime(),
  defaultMs: new Date("2023-08-04T11:59:00Z").getTime(), // 9 of 10 cows have UWB fixes
  stepMs: 60 * 1000,
};
const TOTAL_MINUTES = Math.round((TIME_RANGE.endMs - TIME_RANGE.startMs) / TIME_RANGE.stepMs); // 19830 steps
const DEFAULT_STEP = Math.round((TIME_RANGE.defaultMs - TIME_RANGE.startMs) / TIME_RANGE.stepMs); // 19829

function stepToIso(step) {
  const ms = TIME_RANGE.startMs + Math.round(Number(step)) * TIME_RANGE.stepMs;
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");
}

function isoToStep(iso) {
  const ms = new Date(iso).getTime();
  if (isNaN(ms)) return DEFAULT_STEP;
  const clamped = Math.max(TIME_RANGE.startMs, Math.min(TIME_RANGE.endMs, ms));
  return Math.round((clamped - TIME_RANGE.startMs) / TIME_RANGE.stepMs);
}

function formatDisplayTime(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const day = d.getUTCDate();
  let hours = d.getUTCHours();
  const minutes = String(d.getUTCMinutes()).padStart(2, "0");
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12 || 12;
  return `${month} ${day}, ${hours}:${minutes} ${ampm} UTC`;
}

function getGridBounds(payload) {
  const grid = payload?.grid || state.s12.penMap?.grid || {};
  const cows = payload?.cows || state.s12.penMap?.cows || [];
  const restingAreas = payload?.resting_areas || payload?.implicated_resting_areas || state.s12.penMap?.resting_areas || [];

  // 1. Explicit bounds directly on grid or grid.bounds
  const boundsObj = grid.bounds || grid;
  const xMinVal = boundsObj.x_min_m ?? boundsObj.x_min ?? boundsObj.xmin;
  const xMaxVal = boundsObj.x_max_m ?? boundsObj.x_max ?? boundsObj.xmax;
  const yMinVal = boundsObj.y_min_m ?? boundsObj.y_min ?? boundsObj.ymin;
  const yMaxVal = boundsObj.y_max_m ?? boundsObj.y_max ?? boundsObj.ymax;

  if (xMinVal != null && xMaxVal != null && yMinVal != null && yMaxVal != null) {
    const xMin = Number(xMinVal);
    const xMax = Number(xMaxVal);
    const yMin = Number(yMinVal);
    const yMax = Number(yMaxVal);
    return {
      xMin,
      xMax,
      yMin,
      yMax,
      width: xMax - xMin || 24.9,
      height: yMax - yMin || 17.7,
      isCentered: xMin < 0,
    };
  }

  // 2. Explicit origin "center" with width/height
  if (grid.origin === "center" || payload?.coordinate_system === "centered" || grid.coordinate_system === "centered") {
    const w = Number(grid.width_m || 24.9);
    const h = Number(grid.height_m || 17.7);
    return {
      xMin: -(w / 2),
      xMax: w / 2,
      yMin: -(h / 2),
      yMax: h / 2,
      width: w,
      height: h,
      isCentered: true,
    };
  }

  // 3. Negative coordinates detection in cows or resting areas
  const hasNegativeCoords = cows.some((c) => {
    const x = Number(c.uwb_x_m ?? c.x_coord);
    const y = Number(c.uwb_y_m ?? c.y_coord);
    return (!isNaN(x) && x < 0) || (!isNaN(y) && y < 0);
  }) || restingAreas.some((a) => {
    const x = Number(a.center_x_m ?? a.x_m);
    const y = Number(a.center_y_m ?? a.y_m);
    return (!isNaN(x) && x < 0) || (!isNaN(y) && y < 0);
  });

  if (hasNegativeCoords) {
    // Real barn with 0.5 m margin: 24.90 m x 17.70 m (aspect 1.407)
    // x in [-11.99, 11.91] with 0.5m margin -> [-12.45, 12.45]
    // y in [-8.81, 7.88] with 0.5m margin -> [-9.31, 8.39]
    return {
      xMin: -12.45,
      xMax: 12.45,
      yMin: -9.31,
      yMax: 8.39,
      width: 24.90,
      height: 17.70,
      isCentered: true,
    };
  }

  // 4. Fallback to legacy positive 0..width_m, 0..height_m space (synthetic default)
  const width = Number(grid.width_m || 30);
  const height = Number(grid.height_m || 15);
  return {
    xMin: 0,
    xMax: width,
    yMin: 0,
    yMax: height,
    width,
    height,
    isCentered: false,
  };
}
const configuredApiBase = window.BOVIAL_API_BASE || window.HERDWISE_API_BASE || queryParams.get("api");
const apiBase = (configuredApiBase || "http://127.0.0.1:8000").replace(/\/$/, "");
const interactiveApiBase = (
  window.BOVIAL_INTERACTIVE_API_BASE
  || window.HERDWISE_INTERACTIVE_API_BASE
  || queryParams.get("interactiveApi")
  || configuredApiBase
  || apiBase
).replace(/\/$/, "");

async function fetchApi(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

async function fetchInteractiveApi(path, options = {}) {
  const response = await fetch(`${interactiveApiBase}${path}`, {
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

function generateFallbackHeatmapGrid() {
  const rows = 15;
  const cols = 30;
  const grid = [];
  for (let r = 0; r < rows; r++) {
    const row = [];
    for (let c = 0; c < cols; c++) {
      let val = 0.0;
      // Cubicle row A (stalls y: 2 to 5, x: 5 to 25)
      if (r >= 2 && r <= 5 && c >= 5 && c <= 25) {
        val = 0.65;
      }
      // Cubicle row B (stalls y: 9 to 12, x: 5 to 25)
      if (r >= 9 && r <= 12 && c >= 5 && c <= 25) {
        val = 0.82;
      }
      // Primary contamination hotspot around Rest Zone B Cubicle 4 (r: 10, c: 17)
      const distB4 = Math.hypot(r - 10, c - 17);
      if (distB4 <= 3.5) {
        val = Math.max(val, 0.95 - distB4 * 0.1);
      }
      // Moderate idling near feed lane entrance (r: 7, c: 10)
      const distFeed = Math.hypot(r - 7, c - 10);
      if (distFeed <= 2.5) {
        val = Math.max(val, 0.45 - distFeed * 0.08);
      }
      row.push(Number(val.toFixed(2)));
    }
    grid.push(row);
  }
  return grid;
}

const FALLBACK_PEN_MAP = {
  ts_utc: "2023-08-04T11:59:00Z",
  barn_id: "north-barn",
  pen_id: "pen-1",
  coordinate_system: "positive",
  grid: {
    origin: "bottom_left",
    width_m: 30.0,
    height_m: 15.0,
    x_min_m: 0.0,
    x_max_m: 30.0,
    y_min_m: 0.0,
    y_max_m: 15.0,
    cell_size_m: 1.0,
    heatmap: generateFallbackHeatmapGrid(),
  },
  cows: [
    { cow_id: "C01", display_name: "Cow C01", uwb_x_m: 8.2, uwb_y_m: 3.8, zone: "cubicle_row_a", activity_state: "resting", exposure_score: 0.92, is_source_candidate: true, flag_status: "flagged", is_instrumented: true },
    { cow_id: "C02", display_name: "Cow C02", uwb_x_m: 15.5, uwb_y_m: 4.1, zone: "cubicle_row_a", activity_state: "resting", exposure_score: 0.76, is_source_candidate: false, flag_status: "unflagged", is_instrumented: true },
    { cow_id: "C03", display_name: "Cow C03", uwb_x_m: 17.8, uwb_y_m: 10.5, zone: "cubicle_row_b", activity_state: "resting", exposure_score: 0.85, is_source_candidate: false, flag_status: "flagged", is_instrumented: true },
    { cow_id: "C04", display_name: "Cow C04", uwb_x_m: 10.4, uwb_y_m: 7.2, zone: "feed_alley", activity_state: "active", exposure_score: 0.28, is_source_candidate: false, flag_status: "unflagged", is_instrumented: true },
    { cow_id: "C05", display_name: "Cow C05", uwb_x_m: 6.5, uwb_y_m: 11.2, zone: "cubicle_row_b", activity_state: "resting", exposure_score: 0.45, is_source_candidate: false, flag_status: "unflagged", is_instrumented: true },
    { cow_id: "C06", display_name: "Cow C06", uwb_x_m: 21.0, uwb_y_m: 4.5, zone: "cubicle_row_a", activity_state: "resting", exposure_score: 0.15, is_source_candidate: false, flag_status: "unflagged", is_instrumented: true },
    { cow_id: "C07", display_name: "Cow C07", uwb_x_m: 12.8, uwb_y_m: 10.8, zone: "cubicle_row_b", activity_state: "resting", exposure_score: 0.12, is_source_candidate: false, flag_status: "unflagged", is_instrumented: true },
    { cow_id: "C08", display_name: "Cow C08", uwb_x_m: 16.8, uwb_y_m: 11.8, zone: "cubicle_row_b", activity_state: "resting", exposure_score: 0.08, is_source_candidate: false, flag_status: "unflagged", is_instrumented: true },
    { cow_id: "C09", display_name: "Cow C09", uwb_x_m: 23.4, uwb_y_m: 4.2, zone: "cubicle_row_a", activity_state: "resting", exposure_score: 0.05, is_source_candidate: false, flag_status: "unflagged", is_instrumented: true },
    { cow_id: "C10", display_name: "Cow C10", uwb_x_m: 7.8, uwb_y_m: 4.6, zone: "cubicle_row_a", activity_state: "resting", exposure_score: 0.05, is_source_candidate: false, flag_status: "unflagged", is_instrumented: true },
  ],
  resting_areas: [
    {
      zone_id: "Rest Zone B - Stall 4",
      center_x_m: 17.5,
      center_y_m: 10.5,
      radius_m: 1.5,
      contact_cow_ids: ["C01", "C03", "C04"],
      is_synthetic: true,
    },
  ],
  is_synthetic: true,
};

function renderFlagGroup() {
  const target = document.querySelector("#flag-group");
  const entries = [...state.groupFlags.entries()];
  target.innerHTML = entries.length
    ? entries.map(([cowId, label]) => `<button type="button" class="flag-chip" data-cow-id="${cowId}">${label} ×</button>`).join("")
    : '<span class="muted">No cows in the backtrace group yet.</span>';
  target.querySelectorAll(".flag-chip").forEach((chip) => chip.addEventListener("click", () => {
    state.groupFlags.delete(chip.dataset.cowId);
    renderFlagGroup();
  }));
}

function setDataStatus(message, tone = "") {
  const status = document.querySelector("#s12-data-status");
  if (status) {
    status.textContent = message;
    status.className = `data-status ${tone}`.trim();
  }
  const connStatus = document.querySelector("#connection-status");
  if (connStatus) {
    if (tone === "connected") {
      connStatus.innerHTML = '<span class="status-dot"></span> Live data';
      connStatus.className = "status-pill live";
      connStatus.title = `Connected to live API on ${apiBase}`;
    } else if (tone === "fallback") {
      connStatus.innerHTML = '<span class="status-dot warning-dot"></span> Demo fallback · API offline';
      connStatus.className = "status-pill offline";
      connStatus.title = "Start backend server: python backend-visualization/visualization/server.py --port 8000";
    }
  }
}

function cowLabel(record) {
  const cid = record.cow_id || record.display_name;
  if (!cid) return "Cow";
  if (cid.startsWith("Cow ")) return cid;
  if (/^C\d+$/i.test(cid)) return `Cow ${cid.toUpperCase()}`;
  if (record.cow_id) return `Cow ${record.cow_id}`;
  return record.display_name || "Cow";
}

function findCowDot(cowId) {
  return document.querySelector(`.cow-dot[data-cow-id="${CSS.escape(cowId)}"]`);
}

function attachCowDot(dot) {
  dot.addEventListener("click", () => {
    state.selectedCow = dot.dataset.cow;
    const detail = document.querySelector("#cow-detail");
    document.querySelectorAll(".cow-dot").forEach((item) => item.classList.toggle("selected", item === dot));
    const rec = state.cowRecords.get(dot.dataset.cow);
    const statusNote = rec?.out_of_pen
      ? "Out of pen"
      : (!rec?.is_instrumented && rec?.factors?.includes("Uninstrumented cohort animal"))
        ? "Uninstrumented cohort (No UWB)"
        : (rec?.missing_modalities?.includes("uwb") || dot.hidden)
          ? "No UWB fix"
          : null;
    const noteSuffix = statusNote ? ` · ${statusNote}` : "";
    detail.textContent = `${dot.dataset.cow} · ${state.modelWatchList.has(dot.dataset.cow) ? "Elevated risk · model" : state.manualWatchList.has(dot.dataset.cow) ? "Vet watch list" : "Within baseline"}${noteSuffix}`;
    detail.hidden = false;
    renderRestingFilter();
    renderWatchListSidebar();
  });
}

function getCowDotFill(record, mode = state.colorByMode || "status") {
  if (!record) return "#4fbe89";

  const isUrgent = record.risk_status === "urgent"
    || record.risk_status === "priority_watch"
    || record.flag_status === "flagged"
    || Boolean(record.vet_flagged)
    || Number(record.risk_score || 0) >= 0.70;

  const isWatch = record.risk_status === "watch"
    || record.risk_status === "elevated"
    || Number(record.risk_score || 0) >= 0.35
    || Number(record.exposure_score || 0) > 0.35
    || state.modelWatchList.has(cowLabel(record))
    || state.manualWatchList.has(cowLabel(record));

  if (mode === "health") {
    const healthIndex = record.health_index != null
      ? Number(record.health_index)
      : Math.round((1.0 - Number(record.risk_score || 0.1)) * 100);
    const mastitisRisk = Number(record.mastitis_risk || 0);

    if (healthIndex < 50 || mastitisRisk >= 60 || isUrgent) {
      return "#d75f51"; // Red
    }
    if (healthIndex < 75 || mastitisRisk >= 35 || isWatch) {
      return "#e6a23c"; // Amber
    }
    return "#4fbe89"; // Green
  }

  if (mode === "behavior") {
    const exposure = Number(record.exposure_score || 0);
    const idling = Number(record.idling_minutes || 0);

    if (exposure > 0.6 || isUrgent) {
      return "#d75f51"; // Red
    }
    if (exposure > 0.3 || idling > 60 || isWatch) {
      return "#e6a23c"; // Amber
    }
    return "#4fbe89"; // Green
  }

  // mode === "status" (Lactation / Clinical status)
  if (isUrgent) return "#d75f51";
  if (isWatch) return "#e6a23c";

  const statusStr = String(record.lactation_status || record.activity_state || record.status || "").toLowerCase();
  if (statusStr.includes("pregnant")) return "#6f96e8";
  if (statusStr.includes("estrus")) return "#a971cc";
  if (statusStr.includes("fresh") || statusStr.includes("calved")) return "#6f96e8";

  return "#4fbe89";
}

function ensureCowDot(record, index) {
  const polygon = document.querySelector(".barn-polygon");
  let dot = findCowDot(record.cow_id);
  if (!dot) {
    dot = document.createElement("div");
    dot.className = "cow-dot api-cow";
    dot.dataset.cowId = record.cow_id;
    polygon.append(dot);
    attachCowDot(dot);
  }
  dot.classList.add("api-cow");
  dot.dataset.cow = cowLabel(record);
  dot.dataset.restZone = record.zone || "zone-a";

  const fill = getCowDotFill(record, state.colorByMode);
  dot.style.setProperty("--dot-fill", fill);
  dot.style.background = fill;
  dot.classList.toggle("dot-urgent", fill === "#d75f51");
  dot.classList.toggle("dot-watch", fill === "#e6a23c");
  dot.classList.toggle("dot-healthy", fill === "#4fbe89");

  const rawX = record.uwb_x_m ?? record.x_coord;
  const rawY = record.uwb_y_m ?? record.y_coord;
  const isOutOfPen = Boolean(record.out_of_pen);
  const hasCoordinates = rawX != null && rawY != null && !isNaN(Number(rawX)) && !isNaN(Number(rawY));

  // Gaps / out-of-pen cows render as absent rather than snapping to edge
  if (isOutOfPen || !hasCoordinates) {
    dot.hidden = true;
    dot.title = `${cowLabel(record)} · ${isOutOfPen ? "Out of pen" : "No UWB fix"}`;
    state.cowRecords.set(dot.dataset.cow, record);
    return dot;
  }

  const bounds = getGridBounds(state.s12.penMap);
  const x = Number(rawX);
  const y = Number(rawY);
  const leftPct = ((x - bounds.xMin) / bounds.width) * 100;
  const topPct = ((y - bounds.yMin) / bounds.height) * 100;

  dot.style.left = `${Math.max(1, Math.min(98, leftPct))}%`;
  dot.style.top = `${Math.max(1, Math.min(98, topPct))}%`;
  dot.hidden = false;
  dot.title = `${cowLabel(record)} · ${record.flag_status === "flagged" ? "Flagged for review" : "Observed by model"}`;
  dot.classList.toggle("api-flagged", record.flag_status === "flagged");
  dot.classList.toggle("api-exposed", Number(record.exposure_score || 0) > 0.35);
  dot.classList.toggle("api-source", Boolean(record.is_source_candidate));
  state.cowRecords.set(dot.dataset.cow, record);
  return dot;
}

function updateLegendCounts() {
  const records = state.s12.penMap?.cows || [...state.cowRecords.values()];
  if (!records.length) return;

  let urgentCount = 0;
  let watchCount = 0;
  let baselineCount = 0;

  records.forEach((record) => {
    const fill = getCowDotFill(record, state.colorByMode);
    if (fill === "#d75f51") urgentCount++;
    else if (fill === "#e6a23c") watchCount++;
    else baselineCount++;
  });

  const baselineEl = document.querySelector("#legend-count-baseline");
  const watchEl = document.querySelector("#legend-count-watch");
  const urgentEl = document.querySelector("#legend-count-urgent");

  if (baselineEl) baselineEl.textContent = String(baselineCount);
  if (watchEl) watchEl.textContent = String(watchCount);
  if (urgentEl) urgentEl.textContent = String(urgentCount);
}

function updateColorScaleGuides() {
  document.querySelectorAll(".color-by-option").forEach((opt) => {
    const input = opt.querySelector('input[name="color-by"]');
    opt.classList.toggle("active", Boolean(input && input.checked));
  });
  document.querySelectorAll(".color-scale-guide").forEach((guide) => {
    guide.classList.toggle("active", guide.dataset.for === state.colorByMode);
  });
}

function renderHeatmap(heatmapData) {
  const canvas = document.querySelector("#heatmap-canvas");
  const gradientKey = document.querySelector("#heatmap-gradient-key");
  if (gradientKey) {
    gradientKey.hidden = (state.mode !== "heatmap");
  }
  if (!canvas) return;

  if (state.mode !== "heatmap" || !heatmapData || !Array.isArray(heatmapData) || !heatmapData.length) {
    canvas.hidden = true;
    return;
  }

  state.currentHeatmapData = heatmapData;

  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const rows = heatmapData.length;
  const cols = heatmapData[0].length;

  // Aspect-ratio and coordinate correction: ensure canvas bitmap coordinates match element display pixels
  // so drawn circular arcs appear as true geometric circles on screen without vertical stretching distortion
  const rect = canvas.getBoundingClientRect ? canvas.getBoundingClientRect() : { width: 0, height: 0 };
  const displayW = Math.round(rect.width || canvas.clientWidth || 400);
  const displayH = Math.round(rect.height || canvas.clientHeight || Math.round(displayW / 1.407));
  canvas.width = displayW;
  canvas.height = displayH;
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const cellW = canvas.width / cols;
  const cellH = canvas.height / rows;
  // Uniform radius in physical screen pixels guarantees circular rendering without oval stretching
  const radius = Math.min(cellW, cellH) * 0.82;

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const val = Math.max(0, Math.min(1, Number(heatmapData[r][c] || 0)));
      if (val > 0.01) {
        const alpha = Math.min(0.85, val * 0.95);
        let color = `rgba(79, 190, 137, ${alpha})`;
        if (val > 0.60) {
          color = `rgba(215, 95, 81, ${alpha})`;
        } else if (val > 0.30) {
          color = `rgba(230, 162, 60, ${alpha})`;
        }
        ctx.fillStyle = color;
        ctx.beginPath();
        const cx = (c + 0.5) * cellW;
        const cy = (r + 0.5) * cellH;
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  canvas.hidden = false;
}

function renderPenMap(payload) {
  state.s12.penMap = payload;
  const records = payload?.cows || [];
  // Hide all dots first so unobserved/out-of-pen/absent cows do not persist
  document.querySelectorAll(".cow-dot").forEach((dot) => { dot.hidden = true; });
  records.forEach((record, index) => ensureCowDot(record, index));

  const eyebrow = document.querySelector("#barn-cohort-eyebrow");
  if (eyebrow) {
    const total = records.length || 16;
    const tracked = records.filter((r) => r.is_instrumented !== false).length || 10;
    eyebrow.textContent = `North Barn · ${total} cows (${tracked} tracked)`;
  }

  const polygon = document.querySelector(".barn-polygon");
  polygon.classList.toggle("api-risk-overlay", records.some((record) => record.flag_status === "flagged" || Number(record.exposure_score || 0) > 0.35));
  renderRestingOverlays(payload);
  updateLegendCounts();
  updateColorScaleGuides();
  renderWatchListSidebar();
  renderHeatmap(payload?.grid?.heatmap);
}

function renderRestingOverlays(payload) {
  const target = document.querySelector("#resting-overlays");
  if (!target) return;
  const hasOverlayData = Object.prototype.hasOwnProperty.call(payload || {}, "resting_areas")
    || Object.prototype.hasOwnProperty.call(payload || {}, "implicated_resting_areas")
    || Object.prototype.hasOwnProperty.call(payload || {}, "implicated_circles")
    || Object.prototype.hasOwnProperty.call(payload || {}, "implicatedRestingCircles")
    || Object.prototype.hasOwnProperty.call(payload?.implicated_elements || {}, "resting_areas");
  if (!hasOverlayData) return;
  target.replaceChildren();
  target.hidden = !state.overlay;
  target.classList.toggle("active-overlay", state.overlay);
  document.querySelectorAll(".cow-dot.resting-contact").forEach((dot) => dot.classList.remove("resting-contact"));
  const areas = payload?.resting_areas
    || payload?.implicated_resting_areas
    || payload?.implicated_circles
    || payload?.implicatedRestingCircles
    || payload?.implicated_elements?.resting_areas
    || [];
  const bounds = getGridBounds(payload);
  areas.forEach((area, index) => {
    const x = Number(area.center_x_m ?? area.x_m ?? area.x ?? 0);
    const y = Number(area.center_y_m ?? area.y_m ?? area.y ?? 0);
    const radius = Number(area.radius_m ?? area.radius ?? 1.5);
    const circle = document.createElement("div");
    circle.className = "resting-circle";
    const leftPct = ((x - radius - bounds.xMin) / bounds.width) * 100;
    const topPct = ((y - radius - bounds.yMin) / bounds.height) * 100;
    const widthPct = ((radius * 2) / bounds.width) * 100;
    const heightPct = ((radius * 2) / bounds.height) * 100;
    circle.style.left = `${Math.max(0, leftPct)}%`;
    circle.style.top = `${Math.max(0, topPct)}%`;
    circle.style.width = `${Math.max(1, widthPct)}%`;
    circle.style.height = `${Math.max(1, heightPct)}%`;
    const isSynthetic = area.is_synthetic ?? payload?.is_synthetic ?? true;
    const provenanceLabel = isSynthetic ? "Synthetic model fixture" : "Empirical attribution";
    const cutoff = area.until_bedding_change_utc ? ` · until bedding change ${area.until_bedding_change_utc}` : "";
    circle.title = `${area.zone_id || area.cell_id || `Resting area ${index + 1}`} · ${radius} m radius · Provenance: ${provenanceLabel} · Epidemiological estimate (not a clinical diagnosis)${cutoff}`;

    const labelTag = document.createElement("span");
    labelTag.className = "resting-circle-tag";
    labelTag.textContent = `Shared resting risk area (${isSynthetic ? "Synthetic fixture" : "Empirical"} · Non-clinical)`;
    circle.append(labelTag);

    target.append(circle);
  });
  const contacts = new Set(
    (payload?.contact_cows || payload?.contact_cow_ids || areas.flatMap((area) => area.contact_cow_ids || area.contact_cows || []))
      .map((cow) => typeof cow === "string" ? cow : cow.cow_id)
      .filter(Boolean)
  );
  contacts.forEach((cowId) => {
    const dot = findCowDot(cowId);
    if (dot) dot.classList.add("resting-contact");
  });
}

function routeLabel(route) {
  return {
    resting_area: "Resting area",
    resting_environment: "Resting area",
    milking_equipment: "Milking equipment",
    milking_machine: "Milking equipment",
    both: "Both routes",
    no_common_route: "No common route",
    resting_cubicle_route: "Resting area",
    milking_equipment_route: "Milking equipment",
    sporadic_individual: "No common route",
  }[route] || "Route evidence";
}

function renderHerdHealth(payload) {
  state.s12.herdHealth = payload;
  const target = document.querySelector("#herd-health-list");
  const cows = (payload?.cows || []).slice().sort((a, b) => Number(a.health_index) - Number(b.health_index)).slice(0, 8);
  target.innerHTML = cows.length ? cows.map((cow) => {
    const score = Math.round(Number(cow.health_index || 0));
    const risk = Math.round(Number(cow.mastitis_risk || 0));
    return `<button class="health-row" data-cow-id="${cow.cow_id}"><span><strong>${cow.cow_id}</strong><small>${cow.baseline_tier || "baseline"} baseline</small></span><span class="health-bar"><i style="width:${score}%"></i></span><b>${score}</b><em>${risk} risk</em></button>`;
  }).join("") : '<p class="muted">No health rows available.</p>';
  target.querySelectorAll(".health-row").forEach((row) => row.addEventListener("click", () => {
    const dot = findCowDot(row.dataset.cowId);
    if (dot) dot.click();
  }));
}

function normalizeBacktraceResult(result) {
  const summary = result?.summary || result || {};
  const analysis = summary.analysisResult || {};
  const circles = summary.implicatedRestingCircles
    || summary.implicated_resting_areas
    || summary.implicated_circles
    || analysis.implicated_resting_areas
    || analysis.implicated_circles
    || [];
  const contacts = summary.primaryContactCows
    || summary.contact_cows
    || analysis.high_risk_contacts?.map((contact) => contact.cow_id).filter(Boolean)
    || [];
  const route = summary.likely_route || summary.likelyRoute || analysis.likely_route;
  const pValue = summary.routeConfidencePValue
    ?? analysis.route_p_values?.resting_p_value
    ?? analysis.p_values?.resting_route;

  return {
    ...result,
    ...summary,
    likely_route: route,
    p_values: summary.p_values || analysis.p_values || {
      resting_route: pValue,
      milking_equipment: pValue,
    },
    transmission_source: {
      ...(summary.transmission_source || {}),
      identifier: summary.implicatedResource || summary.transmission_source?.identifier,
      resting_areas: circles,
    },
    implicated_resting_areas: circles,
    implicated_circles: circles,
    contact_cows: contacts,
    recommended_actions: summary.recommended_actions
      || (summary.recommendedIntervention ? [summary.recommendedIntervention] : []),
  };
}

function renderAttribution(payload) {
  state.s12.attribution = payload;
  renderRestingOverlays(payload);
  const source = payload?.transmission_source || {};
  const pValues = payload?.p_values || {};
  const actions = payload?.recommended_actions || [];
  const restingAreas = payload?.resting_areas
    || payload?.implicated_resting_areas
    || payload?.implicated_circles
    || payload?.implicatedRestingCircles
    || payload?.transmission_source?.resting_areas
    || state.s12.penMap?.resting_areas
    || [];
  const restingSummary = restingAreas.length
    ? `<div class="source-note"><strong>Real resting areas:</strong> ${restingAreas.map((area) => area.zone_id || area.cell_id || `circle (${area.center_x_m ?? "—"}m, ${area.center_y_m ?? "—"}m)`).join(", ")} · 1.5 m contact radius, bounded by bedding changes.</div>`
    : "";
  const sourceSummary = (source.identifier || restingAreas.length)
    ? `<div class="source-note"><strong>Source candidate:</strong> ${source.identifier || "Real resting area"}${source.primary_index_cow ? ` · ${source.primary_index_cow}` : ""}</div>`
    : payload?.likely_route === "resting_area" || payload?.likely_route === "resting_cubicle_route"
      ? '<div class="source-note"><strong>Source candidate:</strong> Real-coordinate resting area data is pending.</div>'
      : `<div class="source-note"><strong>Source candidate:</strong> ${source.identifier || "Not identified"}${source.primary_index_cow ? ` · ${source.primary_index_cow}` : ""}</div>`;
  document.querySelector("#attribution-panel").innerHTML = `
    <div class="route-callout"><span>Most supported route</span><strong>${routeLabel(payload?.likely_route)}</strong></div>
    <div class="metric-row"><span>Resting route p-value</span><strong>${pValues.resting_permutation_p ?? "—"}</strong></div>
    <div class="metric-row"><span>Milking route p-value</span><strong>${pValues.milking_permutation_p ?? "—"}</strong></div>
    ${sourceSummary}
    ${restingSummary}
    <p class="muted">Pathogen group is shown as a likelihood only. This is a model suggestion, not a diagnosis.</p>
    ${actions.length ? `<ul class="action-list">${actions.slice(0, 3).map((action) => `<li>${action}</li>`).join("")}</ul>` : ""}
  `;
}

function renderImpact(payload) {
  state.s12.impact = payload;
  document.querySelector("#impact-panel").innerHTML = `
    <div class="impact-stat"><strong>${payload?.total_affected_cows ?? "—"}</strong><span>affected cows</span></div>
    <div class="impact-stat"><strong>${payload?.flagged_early_count ?? "—"}</strong><span>flagged early</span></div>
    <div class="impact-stat"><strong>${payload?.mean_lead_time_hours ?? "—"}h</strong><span>mean lead time</span></div>
    <div class="impact-stat"><strong>${payload?.estimated_milk_saved_kg ?? "—"} kg</strong><span>estimated saved</span></div>
  `;
}

function updateDataBadge(payloads) {
  const values = payloads.map((payload) => payload?.is_synthetic).filter((value) => typeof value === "boolean");
  const badge = document.querySelector(".demo-badge");
  if (!values.length) return;
  const allSynthetic = values.every(Boolean);
  const allReal = values.every((value) => !value);
  badge.textContent = allSynthetic ? "Demo data" : allReal ? "Live data" : "Mixed data";
  document.querySelector("#connection-status").innerHTML = `<span class="status-dot"></span> ${allSynthetic ? "Demo service" : "API connected"}`;
}

function renderMilkingStalls(payload) {
  if (!payload || !payload.stalls) return;
  const stalls = payload.stalls;
  state.milking = payload;

  const titleEl = document.querySelector("#milking-parlor-title");
  if (titleEl) titleEl.textContent = `Rotary parlor · ${stalls.length} stalls`;

  const inProgress = stalls.filter((s) => s.state === "active").length;
  const inProgressEl = document.querySelector("#milking-in-progress");
  if (inProgressEl) inProgressEl.textContent = `${inProgress} / ${stalls.length}`;

  const lastSyncEl = document.querySelector("#milking-last-sync");
  if (lastSyncEl && payload.ts_utc) {
    lastSyncEl.textContent = `Synced ${formatDisplayTime(payload.ts_utc)}`;
  }

  let totalYield = 0;
  let activeYieldCount = 0;
  let highRiskCount = 0;

  // Hide any stalls that exceed active stall count from API
  document.querySelectorAll(".stall").forEach((stallBtn) => {
    const sNum = Number(stallBtn.dataset.stall);
    stallBtn.hidden = (sNum > stalls.length);
  });

  // Position visible stalls symmetrically on the rotary circle
  const activeCount = stalls.length;
  stalls.forEach((stall, idx) => {
    const stallBtn = document.querySelector(`.stall[data-stall="${stall.stall_number}"]`);
    if (!stallBtn) return;

    const angle = (idx / activeCount) * 2 * Math.PI - Math.PI / 2;
    const x = (50 + 47 * Math.cos(angle)).toFixed(2);
    const y = (50 + 47 * Math.sin(angle)).toFixed(2);
    stallBtn.style.left = `${x}%`;
    stallBtn.style.top = `${y}%`;
    stallBtn.style.transform = "translate(-50%, -50%)";

    stallBtn.hidden = false;
    const isHighRisk = Boolean(stall.last_completed_cycle?.flagged_risk);
    const isWatch = Boolean(stall.last_completed_cycle?.cow_id && (state.modelWatchList.has(stall.last_completed_cycle.cow_id) || state.manualWatchList.has(stall.last_completed_cycle.cow_id)));
    if (isHighRisk) highRiskCount++;

    stallBtn.classList.toggle("risk-high", isHighRisk);
    stallBtn.classList.toggle("risk-watch", !isHighRisk && isWatch);
    stallBtn.classList.toggle("risk-low", !isHighRisk && !isWatch);
    stallBtn.classList.toggle("stall-idle", stall.state === "idle");

    if (stall.session_yield_kg != null) {
      totalYield += Number(stall.session_yield_kg);
      activeYieldCount++;
    }
  });

  const highRiskEl = document.querySelector("#milking-high-risk-stalls");
  if (highRiskEl) highRiskEl.textContent = String(highRiskCount);

  if (activeYieldCount > 0) {
    const avgYield = (totalYield / activeYieldCount).toFixed(1);
    const avgYieldEl = document.querySelector("#milking-avg-yield");
    if (avgYieldEl) avgYieldEl.textContent = `${avgYield} kg / cow`;
  }
  if (totalYield > 0) {
    const totalYieldEl = document.querySelector("#milking-total-yield");
    if (totalYieldEl) totalYieldEl.innerHTML = `${Math.round(totalYield * 8)} <span>kg</span>`;
  }
}

function renderAlerts() {
  const criticalList = document.querySelector("#critical-alerts-list");
  const stackedList = document.querySelector("#stacked-routine-inbox");
  const summaryEyebrow = document.querySelector("#alerts-summary-eyebrow");
  if (!criticalList || !stackedList) return;

  const records = state.s12.penMap?.cows || [...state.cowRecords.values()];
  const healthRecords = state.s12.herdHealth?.cows || [];
  const stalls = state.milking?.stalls || [];
  const attribution = state.s12.attribution || {};

  // 1. Single Critical Alert (Urgent Priority) — Limited to 1 to convey zero notification overload
  const criticalItems = [];

  // Cow C03 / acute mastitis risk
  const acuteCow = healthRecords.find((c) => c.cow_id === "C03" || Number(c.mastitis_risk || 0) >= 80)
    || records.find((c) => c.cow_id === "C03" || Number(c.exposure_score || 0) >= 0.80)
    || { cow_id: "C03", display_name: "Cow C03", mastitis_risk: 85 };
  const cowId = acuteCow?.cow_id || "C03";
  const cowName = `Cow ${cowId}`;
  const riskScore = Math.round(Number(acuteCow?.mastitis_risk || 85));

  criticalItems.push({
    id: "alert-fern",
    type: "Urgent · Needs attention today",
    title: `${cowName} has a sharp health change (Mastitis Risk ${riskScore}%)`,
    desc: `${cowName} rested in Rest Zone B for 42 minutes (longer than usual) with an extended idling bout. Feel her rear udder for warmth or swelling, and milk her last.`,
    time: "12 min ago",
    badge: "Sent to Dr. House",
    actionLabel: "Find cow on map",
    actionTarget: "barn",
    cowId: cowId,
    cowName: cowName,
  });

  criticalList.innerHTML = criticalItems.map((item) => `
    <article class="alert-card urgent" id="${item.id}">
      <div class="alert-icon">!</div>
      <div>
        <span class="alert-type">${item.type} · ${item.badge}</span>
        <h3>${item.title}</h3>
        <p>${item.desc}</p>
        <div class="alert-actions">
          <button class="primary-button small alert-act-btn" data-target="${item.actionTarget}" data-cow="${item.cowId || ''}" data-stall="">${item.actionLabel}</button>
          <button class="secondary-button small alert-assign-btn" data-cow-id="${item.cowId || ''}" data-cow-name="${item.cowName || ''}">Notify Dr. House</button>
          <button class="text-button alert-ack-btn">Acknowledge</button>
        </div>
      </div>
      <time>${item.time}</time>
    </article>
  `).join("");

  criticalList.querySelectorAll(".alert-assign-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      showView("messages");
      const cowKey = btn.dataset.cowId === "C01" ? "bessie" : "fern";
      const targetThread = document.querySelector(`.message-thread[data-thread="${cowKey}"]`);
      if (targetThread) {
        targetThread.click();
      }
      const input = document.querySelector("#message-input");
      if (input) {
        input.value = `Dr. House: Notifying you regarding ${btn.dataset.cowName || "Cow C03"} alert. Reviewing CMT & bedding protocol.`;
        input.focus();
      }
    });
  });

  criticalList.querySelectorAll(".alert-ack-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const card = e.target.closest(".alert-card");
      if (card) {
        card.style.opacity = "0.5";
        e.target.textContent = "Acknowledged ✓";
      }
    });
  });

  const flaggedStall = stalls.find((s) => s.last_completed_cycle?.flagged_risk) || { stall_number: 6 };

  // 2. Stacked Routine Activity Inbox (Non-urgent events grouped to eliminate notification overload)
  const stackedItems = [
    {
      id: "stack-bedding",
      icon: "⌂",
      title: "Rest Zone B Bedding Sanitation",
      count: "Action needed",
      summaryHtml: `
        <div class="stacked-item">
          <div><strong>Stalls B1–B8 have damp bedding</strong> — Scrape out wet manure and spread fresh dry sawdust with lime before tonight's rest.</div>
          <button class="secondary-button small alert-act-btn" data-target="barn-overlay">Show on map</button>
        </div>
      `,
    },
    {
      id: "stack-parlor",
      icon: "◫",
      title: "Milking Parlor & Stall 6 Check",
      count: "Cluster rinse",
      summaryHtml: `
        <div class="stacked-item">
          <div><strong>Stall ${flaggedStall.stall_number} conductivity flagged</strong> — Milk conductivity was slightly elevated on last cycle. Run a quick wash cycle on cluster #${flaggedStall.stall_number} before next group.</div>
          <button class="secondary-button small alert-act-btn" data-target="milking" data-stall="${flaggedStall.stall_number}">View in parlor</button>
        </div>
      `,
    },
    {
      id: "stack-estrus",
      icon: "♀",
      title: "Estrus & Breeding Window",
      count: "1 cow",
      summaryHtml: `
        <div class="stacked-item">
          <div><strong>Cow C04</strong> — Nighttime step activity +62%, pacing near loafing lane. Standing heat confirmed; optimal breeding window is around 4:00 PM today.</div>
          <span class="stacked-badge badge-watch">Ready for breeding</span>
        </div>
      `,
    },
    {
      id: "stack-milking",
      icon: "◫",
      title: "Milking Parlor Yields",
      count: "8 stalls active",
      summaryHtml: `
        <div class="stacked-item">
          <div><strong>Parlor throughput normal</strong> — 34.1 kg average yield per cow, flow rate 2.7–3.2 kg/min. Cow C02 fresh cow yield steady at 34.6 kg.</div>
          <span class="stacked-badge badge-normal">Within target</span>
        </div>
      `,
    },
    {
      id: "stack-cohort",
      icon: "◎",
      title: "Herd Visual Check (Uninstrumented)",
      count: "6 cows (C11–C16)",
      summaryHtml: `
        <div class="stacked-item">
          <div><strong>All 16 herd cows confirmed present</strong> — Cows C11 through C16 eating normally at feed bunk; zero signs of physical distress.</div>
          <span class="stacked-badge badge-normal">Confirmed</span>
        </div>
      `,
    },
    {
      id: "stack-resting",
      icon: "⌂",
      title: "Cubicle Resting Durations",
      count: "8 cows baseline",
      summaryHtml: `
        <div class="stacked-item">
          <div><strong>Normal resting patterns</strong> — Cow C01, Cow C02, Cow C05, Cow C06, Cow C07, Cow C08 logging steady >20 min resting bouts.</div>
          <span class="stacked-badge badge-normal">Normal</span>
        </div>
      `,
    },
  ];

  stackedList.innerHTML = stackedItems.map((item) => `
    <details class="stacked-card" id="${item.id}">
      <summary class="stacked-summary">
        <span class="stacked-title-left">
          <span class="stacked-icon">${item.icon}</span>
          <span>${item.title}</span>
        </span>
        <span class="stacked-count">${item.count}</span>
      </summary>
      <div class="stacked-content">
        ${item.summaryHtml}
      </div>
    </details>
  `).join("");

  // Wire all alert action buttons (both critical and stacked)
  document.querySelectorAll(".alert-act-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.target;
      if (target === "barn") {
        showView("barn");
        if (btn.dataset.cow) {
          const dot = findCowDot(btn.dataset.cow);
          if (dot) dot.click();
        }
      } else if (target === "barn-overlay") {
        showView("barn");
        const overlayBtn = document.querySelector("#problem-overlay");
        if (overlayBtn && !state.overlay) overlayBtn.click();
      } else if (target === "milking") {
        showView("milking");
        if (btn.dataset.stall) {
          const stallBtn = document.querySelector(`.stall[data-stall="${btn.dataset.stall}"]`);
          if (stallBtn) stallBtn.click();
        }
      }
    });
  });

  if (summaryEyebrow) {
    summaryEyebrow.textContent = `1 critical alert · ${stackedItems.length} routine updates grouped below · ${formatDisplayTime(state.currentTsUtc)}`;
  }

  // Update tabs
  document.querySelectorAll("[data-view='alerts'] b, .alert-tab b").forEach((b) => {
    b.textContent = "1";
  });
}

async function loadMilkingData() {
  try {
    const data = await fetchApi("/api/milking-stalls");
    renderMilkingStalls(data);
  } catch (error) {
    // Retain demo layout if endpoint is unavailable
  }
}

async function loadS12Data(tsUtc = state.currentTsUtc) {
  try {
    const params = new URLSearchParams();
    if (tsUtc) params.set("ts_utc", tsUtc);
    if (state.currentPenId) params.set("pen_id", state.currentPenId);
    const qs = params.toString() ? `?${params.toString()}` : "";
    const [penMap, herdHealth, attribution, impact] = await Promise.all([
      fetchApi(`/api/pen-map${qs}`),
      fetchApi(`/api/herd-health${qs}`),
      fetchApi(`/api/attribution${qs}`),
      fetchApi(`/api/impact${qs}`),
    ]);
    renderPenMap(penMap);
    renderHerdHealth(herdHealth);
    renderAttribution(attribution);
    renderImpact(impact);
    await loadMilkingData();
    renderAlerts();
    updateDataBadge([penMap, herdHealth, attribution, impact]);
    setDataStatus("API connected", "connected");
  } catch (error) {
    renderAlerts();
    setDataStatus("Demo fallback · API offline", "fallback");
    document.querySelector("#backtrace-status").textContent = "The visualization service is offline; using high-fidelity local demo fixtures. Run python backend-visualization/visualization/server.py --port 8000 for live data.";
    if (!state.s12.penMap) {
      renderPenMap(FALLBACK_PEN_MAP);
    }
  }
}

function updateTimeControlsPlacement(view) {
  const timeControls = document.querySelector(".time-controls");
  if (!timeControls) return;
  if (view === "barn") {
    const barnGrid = document.querySelector(".barn-grid");
    if (barnGrid && barnGrid.parentNode) {
      barnGrid.parentNode.insertBefore(timeControls, barnGrid.nextSibling);
      timeControls.hidden = false;
    }
  } else if (view === "milking") {
    const milkingLayout = document.querySelector(".milking-layout");
    if (milkingLayout && milkingLayout.parentNode) {
      milkingLayout.parentNode.insertBefore(timeControls, milkingLayout.nextSibling);
      timeControls.hidden = false;
    }
  } else {
    timeControls.hidden = true;
  }
}

function showView(view) {
  state.view = view;
  views.forEach((name) => {
    document.querySelector(`#${name}-view`).hidden = name !== view;
    document.querySelectorAll(`[data-view="${name}"]`).forEach((button) => button.classList.toggle("active", true));
  });
  document.querySelectorAll(".view-tab, .mobile-nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  updateTimeControlsPlacement(view);
  if (view === "milking") {
    loadMilkingData();
  }
}

function applyRolePresentation() {
  const isFarmer = (state.role === "farmer");
  const isVet = (state.role === "vet");
  document.body.classList.toggle("farmer-mode", isFarmer);
  document.body.classList.toggle("vet-mode", isVet);

  document.querySelector(".welcome-row h1").textContent = isVet
    ? "Herd detail for clinical review"
    : "Today’s farm priorities";
  document.querySelector(".section-heading h2").textContent = isVet
    ? "Barn overview and risk context"
    : "Where should I look first?";

  const toggle = document.querySelector("#role-details-toggle");
  if (toggle) toggle.textContent = isVet ? "Hide model details ↑" : "View model details →";

  // Partner summary presentation
  const careTeamFarmer = document.querySelector(".care-team-farmer");
  const partnerFarmVet = document.querySelector(".partner-farm-vet");
  if (careTeamFarmer) careTeamFarmer.hidden = isVet;
  if (partnerFarmVet) partnerFarmVet.hidden = !isVet;

  // Toggle farmer actionable banner vs vet differential panel
  const farmerBanner = document.querySelector("#farmer-action-banner");
  const vetPanel = document.querySelector("#vet-differential-panel");
  if (farmerBanner) farmerBanner.hidden = isVet;
  if (vetPanel) vetPanel.hidden = !isVet;

  // In farmer mode, hide complex color-by options to avoid quantitative clutter
  const colorBySegmented = document.querySelector(".color-by-segmented");
  if (colorBySegmented) colorBySegmented.style.display = isVet ? "" : "none";
  document.querySelectorAll(".color-by-option").forEach((opt) => {
    opt.style.display = isVet ? "" : "none";
  });
  const legendHr = document.querySelector(".legend-card hr");
  if (legendHr) legendHr.style.display = isVet ? "" : "none";
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

document.querySelectorAll("[data-view-target]").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.viewTarget));
});

document.querySelectorAll(".mode-button").forEach((button) => {
  button.addEventListener("click", () => {
    state.mode = button.dataset.mode;
    document.querySelectorAll(".mode-button").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelector(".barn-polygon").classList.toggle("heatmap", state.mode === "heatmap");
    const gradientKey = document.querySelector("#heatmap-gradient-key");
    if (gradientKey) gradientKey.hidden = (state.mode !== "heatmap");
    document.querySelector(".map-legend").innerHTML = state.mode === "heatmap"
      ? '<span class="map-legend-heatmap">Idle density (fixed stall grid): <span class="guide-dot healthy"></span> &lt;30m <span class="guide-dot watch"></span> 30–60m <span class="guide-dot urgent"></span> &gt;60m</span>'
      : `<span class="legend-item"><i class="legend-dot healthy"></i> Cow location</span><span class="legend-item" id="legend-resting-oval" ${state.overlay ? "" : "hidden"}><span class="legend-oval-dot"></span> Red oval: Shared resting risk area (Model estimate · Non-clinical)</span>`;
    renderHeatmap(state.s12.penMap?.grid?.heatmap || FALLBACK_PEN_MAP.grid.heatmap);
  });
});

document.querySelector("#problem-overlay").addEventListener("click", (event) => {
  state.overlay = !state.overlay;
  event.currentTarget.classList.toggle("on", state.overlay);
  document.querySelector(".barn-polygon").classList.toggle("risk-overlay", state.overlay);
  const target = document.querySelector("#resting-overlays");
  if (target) {
    target.classList.toggle("active-overlay", state.overlay);
    target.hidden = !state.overlay;
  }
  const legendOval = document.querySelector("#legend-resting-oval");
  if (legendOval) legendOval.hidden = !state.overlay;
});

document.querySelectorAll(".cow-dot").forEach(attachCowDot);

document.querySelectorAll('input[name="color-by"]').forEach((input) => {
  input.addEventListener("change", () => {
    state.colorByMode = input.value;
    updateColorScaleGuides();
    document.querySelectorAll(".cow-dot").forEach((dot) => {
      const rec = state.cowRecords.get(dot.dataset.cow);
      if (rec) {
        const fill = getCowDotFill(rec, state.colorByMode);
        dot.style.setProperty("--dot-fill", fill);
        dot.style.background = fill;
        dot.classList.toggle("dot-urgent", fill === "#d75f51");
        dot.classList.toggle("dot-watch", fill === "#e6a23c");
        dot.classList.toggle("dot-healthy", fill === "#4fbe89");
      }
    });
    updateLegendCounts();
  });
});

function getActiveWatchListItems() {
  const items = [];
  // 1. Primary acute predictive alert: Cow C03
  items.push({
    id: "C03",
    name: "Cow C03",
    type: "urgent",
    tag: "Mastitis risk 85%",
    desc: "Rest Zone B · 42m idle · Clinical suspect",
    isModel: true,
  });

  // 2. Attribution index contact: Cow C01
  items.push({
    id: "C01",
    name: "Cow C01",
    type: "watch",
    tag: "Index candidate",
    desc: "Rest Zone B · Shared cubicle contact",
    isModel: true,
  });

  // 3. User manual additions or group flags
  state.manualWatchList.forEach((cow) => {
    const raw = cow.trim();
    if (raw === "Cow C03" || raw === "Cow C01" || raw === "C03" || raw === "C01") return;
    const cid = raw.replace(/^Cow\s+/i, "");
    items.push({
      id: cid,
      name: raw.startsWith("Cow") ? raw : `Cow ${raw}`,
      type: "manual",
      tag: "Clinical watch",
      desc: "Under veterinary observation",
      isModel: false,
    });
  });

  return items;
}

function isOnWatchList(cow) {
  if (!cow) return false;
  const canonical = cow.trim();
  const shortId = canonical.replace(/^Cow\s+/i, "");
  if (state.manualWatchList.has(canonical) || state.manualWatchList.has(shortId)) return true;
  if (state.modelWatchList.has(canonical) || state.modelWatchList.has(shortId)) return true;
  const items = getActiveWatchListItems();
  return items.some((item) => item.name.toLowerCase() === canonical.toLowerCase() || item.id.toLowerCase() === shortId.toLowerCase());
}

function renderWatchListSidebar() {
  const container = document.querySelector("#watchlist-items");
  const badge = document.querySelector("#watchlist-badge");
  const flagCount = document.querySelector("#flag-count");
  if (!container) return;

  const watched = getActiveWatchListItems();
  const totalCount = watched.length;

  if (badge) badge.textContent = `${totalCount} on watch`;
  if (flagCount) flagCount.textContent = `${totalCount} on watch list`;

  container.innerHTML = watched.map((cow) => `
    <div class="watchlist-item ${cow.type} ${state.selectedCow === cow.name ? "selected" : ""}" data-cow="${cow.name}">
      <div class="watchlist-item-main">
        <div class="watchlist-cow-name">
          <strong>${cow.name}</strong>
          <span class="watchlist-tag ${cow.type}">${cow.tag}</span>
        </div>
        <div class="watchlist-meta">${cow.desc}</div>
      </div>
      <div class="watchlist-actions">
        <button class="watchlist-locate-btn" type="button" data-cow="${cow.name}" title="Locate ${cow.name} on map">Locate</button>
        ${!cow.isModel ? `<button class="watchlist-remove-btn" type="button" data-cow="${cow.name}" title="Remove ${cow.name} from watch list">✕</button>` : ""}
      </div>
    </div>
  `).join("");

  container.querySelectorAll(".watchlist-locate-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const cowName = btn.dataset.cow;
      const dot = document.querySelector(`.cow-dot[data-cow="${cowName}"]`);
      if (dot) {
        dot.click();
        if (typeof dot.scrollIntoView === "function") {
          dot.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      } else {
        state.selectedCow = cowName;
        renderRestingFilter();
        renderWatchListSidebar();
      }
    });
  });

  container.querySelectorAll(".watchlist-remove-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const cowName = btn.dataset.cow;
      state.manualWatchList.delete(cowName);
      state.manualWatchList.delete(cowName.replace(/^Cow\s+/i, ""));
      const dot = document.querySelector(`.cow-dot[data-cow="${cowName}"]`);
      if (dot) dot.classList.remove("manual-watch");
      renderWatchListSidebar();
      renderRestingFilter();
      updateLegendCounts();
    });
  });

  container.querySelectorAll(".watchlist-item").forEach((item) => {
    item.addEventListener("click", () => {
      const cowName = item.dataset.cow;
      const dot = document.querySelector(`.cow-dot[data-cow="${cowName}"]`);
      if (dot) {
        dot.click();
      } else {
        state.selectedCow = cowName;
        renderRestingFilter();
        renderWatchListSidebar();
      }
    });
  });
}

function renderRestingFilter() {
  const content = document.querySelector("#resting-filter-content");
  const empty = document.querySelector("#resting-filter-empty");
  const title = document.querySelector("#selected-cow-title");
  const cow = document.querySelector(`[data-cow="${state.selectedCow}"]`);
  if (!cow) return;
  const rec = state.cowRecords.get(state.selectedCow);
  const zone = cow.dataset.restZone;
  const zoneLabels = {
    "zone-a": "Rest zone A",
    "cubicle_row_a": "Rest zone A",
    "zone-b": "Rest zone B",
    "cubicle_row_b": "Rest zone B",
    "feed_alley": "Feed lane",
    "water_trough": "Water zone",
  };
  const zoneLabel = zoneLabels[zone] || zone || "Rest zone A";
  const coResters = [...document.querySelectorAll(`.cow-dot[data-rest-zone="${zone}"]`)]
    .map((dot) => dot.dataset.cow)
    .filter((name) => name !== state.selectedCow);
  if (title) title.textContent = state.selectedCow;
  if (empty) empty.hidden = true;
  if (content) content.hidden = false;
  const flagBtn = document.querySelector("#flag-illness");
  if (flagBtn) {
    flagBtn.style.display = "";
    flagBtn.textContent = isOnWatchList(state.selectedCow) ? "Remove from watch list" : "Add to watch list";
  }

  const spotsEl = document.querySelector("#resting-spots");
  const coEl = document.querySelector("#co-resters");

  if (rec && !rec.is_instrumented && rec.factors?.includes("Uninstrumented cohort animal")) {
    if (spotsEl) spotsEl.innerHTML = '<span class="resting-spot">Uninstrumented cohort animal · No active sensor telemetry</span>';
    if (coEl) coEl.innerHTML = '<strong>Cohort animal</strong><p class="muted">Part of the uninstrumented 16-cow pen cohort.</p>';
  } else if (rec?.out_of_pen) {
    if (spotsEl) spotsEl.innerHTML = '<span class="resting-spot">Out of pen · Milking / handling activity</span>';
    if (coEl) coEl.innerHTML = '<strong>Out of pen</strong><p class="muted">Currently outside the pen grid.</p>';
  } else {
    if (spotsEl) spotsEl.innerHTML = state.restingFilter
      ? `<span class="resting-spot">${zoneLabel} · 10:42 AM</span><span class="resting-spot">${zoneLabel} · 7:18 AM</span><span class="resting-spot">Rest zone A · yesterday</span>`
      : `<span class="resting-spot">Last seen: ${zoneLabel}</span><span class="resting-spot">3 recorded spots</span>`;
    if (coEl) coEl.innerHTML = `<strong>${coResters.length} other cows shared this resting area</strong><ul>${coResters.map((name) => `<li>${name} <span class="shared-label">shared resting area</span></li>`).join("")}</ul>`;
  }

  document.querySelectorAll(".cow-dot").forEach((dot) => {
    dot.classList.toggle("shared-resting", state.restingFilter && dot.dataset.restZone === zone && dot.dataset.cow !== state.selectedCow);
  });
  const watched = getActiveWatchListItems();
  const flagCount = document.querySelector("#flag-count");
  if (flagCount) flagCount.textContent = `${watched.length} on watch list`;
  const badge = document.querySelector("#watchlist-badge");
  if (badge) badge.textContent = `${watched.length} on watch`;
}

document.querySelector("#flag-illness")?.addEventListener("click", () => {
  if (!state.selectedCow) return;
  const canonical = state.selectedCow.trim();
  const shortId = canonical.replace(/^Cow\s+/i, "");
  if (state.manualWatchList.has(canonical) || state.manualWatchList.has(shortId)) {
    state.manualWatchList.delete(canonical);
    state.manualWatchList.delete(shortId);
  } else {
    state.manualWatchList.add(canonical);
  }
  const selected = document.querySelector(`[data-cow="${state.selectedCow}"]`);
  if (selected) selected.classList.toggle("manual-watch", state.manualWatchList.has(canonical));
  renderRestingFilter();
  renderWatchListSidebar();
  updateLegendCounts();
});

const watchlistAddForm = document.querySelector("#watchlist-add-form");
if (watchlistAddForm) {
  watchlistAddForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = document.querySelector("#watchlist-cow-input");
    if (!input) return;
    const val = input.value.trim();
    if (!val) return;
    const query = val.toLowerCase();
    const dot = [...document.querySelectorAll(".cow-dot")].find((item) =>
      item.dataset.cow?.toLowerCase().includes(query) || item.dataset.cowId?.toLowerCase() === query
    );
    const cowName = dot ? dot.dataset.cow : (val.toUpperCase().startsWith("C") && !val.includes(" ") ? `Cow ${val.toUpperCase()}` : (val.toLowerCase().startsWith("cow ") ? val : `Cow ${val}`));
    state.manualWatchList.add(cowName);
    if (dot) {
      dot.classList.add("manual-watch");
      dot.click();
      if (typeof dot.scrollIntoView === "function") {
        dot.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    } else {
      state.selectedCow = cowName;
      renderRestingFilter();
    }
    input.value = "";
    renderWatchListSidebar();
    updateLegendCounts();
  });
}

document.querySelector("#filter-resting").addEventListener("click", () => {
  state.restingFilter = !state.restingFilter;
  document.querySelector("#filter-resting").textContent = state.restingFilter ? "Clear resting filter" : "Show resting spots";
  renderRestingFilter();
});

document.querySelector("#role-details-toggle").addEventListener("click", () => {
  document.body.classList.toggle("role-details-open");
  const open = document.body.classList.contains("role-details-open");
  document.querySelector("#role-details-toggle").textContent = open ? "Hide model details ↑" : "View model details →";
});

document.querySelector("#manual-flag-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.querySelector("#manual-flag-cow");
  const reason = document.querySelector("#manual-flag-reason").value.trim();
  const query = input.value.trim().toLowerCase();
  const dot = [...document.querySelectorAll(".cow-dot")].find((item) =>
    item.dataset.cow.toLowerCase().includes(query) || item.dataset.cowId?.toLowerCase() === query
  );
  if (!dot) {
    document.querySelector("#backtrace-status").textContent = "Enter a matching cow name or ID before adding a flag.";
    return;
  }
  state.selectedCow = dot.dataset.cow;
  state.manualWatchList.add(dot.dataset.cow);
  state.groupFlags.set(dot.dataset.cowId || dot.dataset.cow, dot.dataset.cow);
  dot.classList.add("manual-watch");
  dot.click();
  renderFlagGroup();
  document.querySelector("#backtrace-status").textContent = `${dot.dataset.cow} added to the vet watch list${reason ? ` · ${reason}` : ""}.`;
  input.value = dot.dataset.cowId || dot.dataset.cow;
});

document.querySelector("#run-backtrace").addEventListener("click", async () => {
  const status = document.querySelector("#backtrace-status");
  const selectedCow = state.selectedCow || document.querySelector("#manual-flag-cow").value.trim();
  if (!selectedCow && !state.groupFlags.size) {
    status.textContent = "Add at least one cow before running the backtrace.";
    return;
  }
  if (!state.groupFlags.size) {
    const dot = [...document.querySelectorAll(".cow-dot")].find((item) => item.dataset.cow === selectedCow);
    state.groupFlags.set(dot?.dataset.cowId || selectedCow, selectedCow);
    renderFlagGroup();
  }
  status.textContent = "Running a 72-hour backtrace…";
  try {
    const result = await fetchInteractiveApi("/backtrace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        animal_ids: [...state.groupFlags.keys()],
        lookback_days: 3,
      }),
    });
    const backtrace = normalizeBacktraceResult(result);
    renderAttribution(backtrace);
    renderRestingOverlays(backtrace);
    if (backtrace.impact) renderImpact(backtrace.impact);
    status.textContent = `Backtrace complete · ${routeLabel(backtrace.likely_route)} most supported.`;
  } catch (error) {
    status.textContent = "Backtrace service unavailable. The last visualization result remains displayed.";
  }
});

const cowSearch = document.querySelector("#cow-search");
const cowSearchStatus = document.querySelector("#cow-search-status");

cowSearch.addEventListener("input", () => {
  const query = cowSearch.value.trim().toLowerCase();
  document.querySelectorAll(".cow-dot").forEach((dot) => dot.classList.remove("search-highlight"));
  if (!query) {
    cowSearchStatus.textContent = "";
    return;
  }
  const match = [...document.querySelectorAll(".cow-dot")].find((dot) => dot.dataset.cow.toLowerCase().includes(query));
  if (!match) {
    cowSearchStatus.textContent = "No cow found";
    return;
  }
  state.selectedCow = match.dataset.cow;
  match.classList.add("search-highlight");
  match.click();
  document.querySelector("#barn-map").scrollIntoView({ behavior: "smooth", block: "center" });
  cowSearchStatus.textContent = `${match.dataset.cow} highlighted`;
});

function syncUrlParams(iso) {
  if (typeof window === "undefined" || !window.history || !window.location) return;
  try {
    const url = new URL(window.location.href);
    if (iso) url.searchParams.set("ts_utc", iso);
    if (state.currentPenId) url.searchParams.set("pen_id", state.currentPenId);
    window.history.replaceState({}, "", url.toString());
  } catch (e) {
    // Graceful fallback for non-browser/test environments
  }
}

let sliderDebounceTimer = null;
if (slider) {
  slider.min = "0";
  slider.max = String(TOTAL_MINUTES);
  slider.step = "1";
  slider.value = String(isoToStep(state.currentTsUtc));

  slider.addEventListener("input", () => {
    const iso = stepToIso(slider.value);
    state.currentTsUtc = iso;
    if (timeLabel) timeLabel.textContent = formatDisplayTime(iso);
    syncUrlParams(iso);
    clearTimeout(sliderDebounceTimer);
    sliderDebounceTimer = setTimeout(() => {
      loadS12Data(iso);
    }, 120);
  });

  slider.addEventListener("change", () => {
    clearTimeout(sliderDebounceTimer);
    const iso = stepToIso(slider.value);
    state.currentTsUtc = iso;
    if (timeLabel) timeLabel.textContent = formatDisplayTime(iso);
    syncUrlParams(iso);
    loadS12Data(iso);
  });
}

const datePresets = [
  { label: "Latest fix minute (Aug 4, 11:59 AM)", iso: "2023-08-04T11:59:00Z" },
  { label: "Last full herd minute (Aug 4, 11:56 AM)", iso: "2023-08-04T11:56:00Z" },
  { label: "Outbreak reference snapshot (Jul 28, 2:00 PM)", iso: "2023-07-28T14:00:00Z" },
  { label: "Study start (Jul 21, 5:30 PM)", iso: "2023-07-21T17:30:00Z" },
];
let presetIndex = 0;
const dateBtn = document.querySelector("#date-button");
if (dateBtn) {
  dateBtn.addEventListener("click", () => {
    presetIndex = (presetIndex + 1) % datePresets.length;
    const preset = datePresets[presetIndex];
    state.currentTsUtc = preset.iso;
    if (slider) slider.value = String(isoToStep(preset.iso));
    if (timeLabel) timeLabel.textContent = formatDisplayTime(preset.iso);
    syncUrlParams(preset.iso);
    loadS12Data(preset.iso);
  });
}

document.querySelectorAll(".stall").forEach((stall) => {
  stall.addEventListener("click", () => {
    const stallNum = Number(stall.dataset.stall);
    const stallData = state.milking?.stalls?.find((s) => Number(s.stall_number) === stallNum);
    const detailEl = document.querySelector("#stall-detail");
    if (stallData) {
      const activeCow = stallData.current_cow_id ? `Active: Cow ${stallData.current_cow_id} · ${stallData.session_yield_kg ?? "—"} kg (${stallData.flow_rate_kg_min ?? "—"} kg/min)` : "Stall is currently idle";
      const lastCycle = stallData.last_completed_cycle ? `Last cow: ${stallData.last_completed_cycle.cow_id} · ${stallData.last_completed_cycle.yield_kg ?? "—"} kg · ${stallData.last_completed_cycle.flagged_risk ? "Model risk flag" : "Within baseline"}` : "No completed cycle recorded";
      detailEl.innerHTML = `<strong>Stall ${stallNum} (${stallData.state})</strong><br><span>${activeCow}<br>${lastCycle}</span>`;
      return;
    }
    const highRisk = stall.classList.contains("risk-high");
    detailEl.innerHTML = `<strong>Stall ${stall.dataset.stall}</strong> · ${highRisk ? "Model-flagged exposure risk" : "Within baseline"}<br><span>${highRisk ? "2 cows flagged in recent cycles: Cow C03, Cow C06." : "Last cow: Cow C02 · 34.6 L · 10:21 AM."}</span>`;
  });
});

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector("#assistant-input").value = button.textContent;
    document.querySelector("#assistant-form").requestSubmit();
  });
});

const cowMessageThreads = {
  fern: {
    title: "Cow C03 · High mastitis risk",
    subtitle: "Farmer ↔ Dr. Gregory House",
    cowId: "C03",
    messages: [
      {
        author: "Dr. House",
        type: "received",
        text: "Cow C03 showed an 85% mastitis probability score after 42 min idle in Rest zone B. Have you run a CMT (California Mastitis Test) on her quarters yet?",
        citation: "Cow C03 · Mastitis risk 85% alert",
      },
      {
        author: "You",
        type: "sent",
        text: "Checking her right now. Right-rear quarter looks slightly warm and swollen. Running CMT test paddle.",
      },
      {
        author: "Dr. House",
        type: "received",
        text: "CMT score >= 2 indicates environmental Strep/E. coli. If positive, withhold milk and start intramammary antibiotic protocol per North Barn protocol.",
        citation: "Clinical protocol: Environmental mastitis Rx",
      },
    ],
  },
  bessie: {
    title: "Cow C01 · Index case candidate",
    subtitle: "Farmer ↔ Dr. Gregory House",
    cowId: "C01",
    messages: [
      {
        author: "Dr. House",
        type: "received",
        text: "Permutation analysis flagged Cow C01 as the primary index case candidate (shared cubicle B4 contact with Cow C03). Any clinical signs during morning milking?",
        citation: "Attribution model: Primary index candidate C01",
      },
      {
        author: "You",
        type: "sent",
        text: "She passed milking inspection at 5:30 AM without obvious clots, but conductivity was borderline 6.2 mS/cm. I stripped all 4 teats into the cup.",
      },
      {
        author: "Dr. House",
        type: "received",
        text: "Good catch. Keep her on close watch for the next 48 hrs and ensure cubicle B4 bedding is completely shoveled out and limed.",
        citation: "Bedding sanitation protocol · Rest Zone B",
      },
    ],
  },
  luna: {
    title: "Cow C04 · Estrus window",
    subtitle: "Farmer ↔ Dr. Gregory House",
    cowId: "C04",
    messages: [
      {
        author: "Dr. House",
        type: "received",
        text: "Activity monitor detected +62% nighttime step activity and restlessness for Cow C04. Estrus confidence is at 94%.",
        citation: "Estrus alert · Cow C04 (+62% mobility)",
      },
      {
        author: "You",
        type: "sent",
        text: "Confirmed standing heat in the loafing lane around 8:00 AM. Insemination scheduled for 4:00 PM today.",
      },
      {
        author: "Dr. House",
        type: "received",
        text: "Perfect timing for the AM/PM rule. Her feeding and idling shifted slightly during standing heat, which is normal. Let me know when AI is completed.",
      },
    ],
  },
  daisy: {
    title: "Cow C02 · Post-calving transition",
    subtitle: "Farmer ↔ Dr. Gregory House",
    cowId: "C02",
    messages: [
      {
        author: "You",
        type: "sent",
        text: "Cow C02 is day 5 post-calving. Morning yield in Stall 2 was 34.6 L, resting pattern steady at 480 min/day.",
      },
      {
        author: "Dr. House",
        type: "received",
        text: "Great transition. Fresh cow ketone strip test was negative (0.4 mmol/L BHB). Keep her on the fresh group transition ration.",
        citation: "Fresh cow health log · Day 5 check",
      },
      {
        author: "You",
        type: "sent",
        text: "Will do. She's resting primarily in Zone A cubicles with no signs of metritis or hypocalcemia.",
      },
    ],
  },
  poppy: {
    title: "Cow C06 · Stall 6 check",
    subtitle: "Farmer ↔ Dr. Gregory House",
    cowId: "C06",
    messages: [
      {
        author: "Dr. House",
        type: "received",
        text: "Cow C06 milked in Stall 6 immediately after the alert. Sensor recorded minor electrical conductivity deviation (6.4 mS/cm). Any sign of cluster cross-contamination?",
        citation: "Milking parlor alert · Stall 6 conductivity",
      },
      {
        author: "You",
        type: "sent",
        text: "Cluster #6 was automatically flushed and sanitized before the next cow entered. Cow C06's milk filters came back clean.",
      },
      {
        author: "Dr. House",
        type: "received",
        text: "Excellent preventative hygiene. Let's monitor her next two milking sessions to ensure conductivity normalizes below 5.8.",
      },
    ],
  },
  mabel: {
    title: "Cow C05 · Rest anomaly check",
    subtitle: "Farmer ↔ Dr. Gregory House",
    cowId: "C05",
    messages: [
      {
        author: "You",
        type: "sent",
        text: "Cow C05 spent 4.2 hrs resting away from herd in Zone A outer cubicles. Locomotion score looks normal (score 1), but she was slow to rise.",
      },
      {
        author: "Dr. House",
        type: "received",
        text: "Check her right front hoof for any solar ulcer or bruising before turn-out tomorrow. Vitality score is 74/100.",
        citation: "Herd vitality report · Cow C05",
      },
      {
        author: "You",
        type: "sent",
        text: "Inspected hoof and trimmed slight overgrowth. Bedding fluffed. Locomotion and resting balance are recovering well.",
      },
    ],
  },
};

function renderMessageThread(threadKey) {
  state.activeMessageThread = threadKey;
  const threadData = cowMessageThreads[threadKey] || cowMessageThreads.fern;
  const titleEl = document.querySelector("#conversation-title");
  if (titleEl) titleEl.textContent = threadData.title;

  const msgList = document.querySelector("#message-list");
  if (!msgList) return;
  msgList.innerHTML = "";

  threadData.messages.forEach((msg) => {
    const article = document.createElement("article");
    article.className = `message ${msg.type}`;
    const authorSpan = document.createElement("span");
    authorSpan.className = "message-author";
    authorSpan.textContent = msg.author;
    const bodyP = document.createElement("p");
    bodyP.textContent = msg.text;
    article.append(authorSpan, bodyP);

    if (msg.citation) {
      const citeBtn = document.createElement("button");
      citeBtn.className = "citation";
      citeBtn.dataset.citation = msg.citation;
      citeBtn.textContent = "Cite this";
      citeBtn.addEventListener("click", () => {
        const selected = document.querySelector("#selected-citation");
        if (selected) {
          selected.textContent = `Selected reference: ${msg.citation}`;
          selected.hidden = false;
        }
      });
      article.append(citeBtn);
    }
    msgList.append(article);
  });
}

document.querySelectorAll(".message-thread").forEach((thread) => {
  thread.addEventListener("click", () => {
    document.querySelectorAll(".message-thread").forEach((item) => item.classList.toggle("active", item === thread));
    renderMessageThread(thread.dataset.thread);
  });
});

document.querySelector("#message-citation")?.addEventListener("click", () => {
  const selected = document.querySelector("#selected-citation");
  if (!selected) return;
  const currentKey = state.activeMessageThread || "fern";
  const threadData = cowMessageThreads[currentKey];
  const firstCitation = threadData?.messages.find((m) => m.citation)?.citation || "Cow C03 · elevated risk model alert";
  selected.textContent = `Selected reference: ${firstCitation}`;
  selected.hidden = false;
});

document.querySelector("#message-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.querySelector("#message-input");
  const value = input?.value.trim();
  if (!value) return;

  const currentKey = state.activeMessageThread || "fern";
  if (!cowMessageThreads[currentKey]) {
    cowMessageThreads[currentKey] = { title: "Custom conversation", messages: [] };
  }
  const newMsg = { author: "You", type: "sent", text: value };
  cowMessageThreads[currentKey].messages.push(newMsg);

  const message = document.createElement("article");
  message.className = "message sent";
  const author = document.createElement("span");
  author.className = "message-author";
  author.textContent = "You";
  const body = document.createElement("p");
  body.textContent = value;
  message.append(author, body);
  document.querySelector("#message-list")?.append(message);
  input.value = "";
});

function handleAdvisorQuery(rawQuery) {
  const q = (rawQuery || "").toLowerCase();
  if (q.includes("first") || q.includes("morning") || q.includes("today") || q.includes("priority") || q.includes("priorities") || q.includes("action")) {
    return "<strong>Top Priority Action (Aug 4):</strong><br>" +
      "• <strong>Check Cow C03's udder before milking:</strong> Feel her rear udder for heat or swelling, and milk her last.<br>" +
      "• <em>Why:</em> Cow C03 logged 42 minutes of continuous idling in Rest Zone B with prolonged stall contact. Stripping her quarters first prevents milk contamination.";
  }
  if (q.includes("fern") || q.includes("c03") || q.includes("udder") || q.includes("alert")) {
    return "<strong>Cow C03 Status:</strong><br>" +
      "• <strong>What was seen:</strong> Cow C03 rested for 42 minutes in a damp stall in Rest Zone B with an extended idling bout.<br>" +
      "• <strong>What to do:</strong> Feel her rear udder before milking. Strip a couple squirts into a cup to check for watery milk or clots.<br>" +
      "• <strong>Milking order:</strong> Milk Cow C03 last so other cows stay clean.";
  }
  if (q.includes("bedding") || q.includes("zone b") || q.includes("sanitize") || q.includes("clean")) {
    return "<strong>Cleaning Rest Zone B Stalls:</strong><br>" +
      "• Scrape out wet bedding and manure from cubicles B1 through B8.<br>" +
      "• Sprinkle barn lime to dry out the floor, then lay at least 3 inches of clean, dry sawdust.<br>" +
      "• <em>Why it matters:</em> Keeps teats dry and clean while cows rest to prevent mastitis.";
  }
  if (q.includes("stall") || q.includes("parlor") || q.includes("milking") || q.includes("service")) {
    return "<strong>Milking Parlor Tasks:</strong><br>" +
      "• <strong>Stall 6:</strong> Milk conductivity was slightly elevated on the last cow. Run a quick wash cycle on cluster #6 before the next group enters.<br>" +
      "• <strong>Milking order:</strong> Milk healthy cows first, and milk watch cows (Cow C03, Cow C01) last.<br>" +
      "• <strong>Teat dip:</strong> Maintain 0.5% post-milking teat dip across all stalls.";
  }
  if (q.includes("luna") || q.includes("c04") || q.includes("heat") || q.includes("estrus") || q.includes("breed")) {
    return "<strong>Cow C04 Heat Check:</strong><br>" +
      "• <strong>Activity:</strong> Nighttime walking activity is up +62% and she spent 42 minutes pacing.<br>" +
      "• <strong>Breeding window:</strong> She is in standing heat. Optimal breeding / AI window is around 4:00 PM today (12 hours after first standing activity).";
  }
  if (q.includes("bessie") || q.includes("c01") || q.includes("contact") || q.includes("index")) {
    return "<strong>Cow C01 Check:</strong><br>" +
      "• <strong>Why she's tracked:</strong> Cow C01 shared cubicle B4 with Cow C03 before Cow C03 showed elevated risk.<br>" +
      "• <strong>Status:</strong> Morning yield was normal, but keep a close eye on her udder for the next 48 hours.";
  }
  if (q.includes("daisy") || q.includes("c02") || q.includes("calv")) {
    return "<strong>Cow C02 Fresh Cow Check:</strong><br>" +
      "• <strong>Day 5 post-calving:</strong> Morning yield in Stall 2 was strong at 34.6 L, resting pattern steady at 480 min/day.<br>" +
      "• <strong>Status:</strong> Doing great. Continue fresh cow transition ration and keep her bedding dry in Zone A.";
  }
  if (q.includes("poppy") || q.includes("c06")) {
    return "<strong>Cow C06 Status:</strong><br>" +
      "• Milked in Stall 6 right after the sensor flag. Filter came back clean, but watch her conductivity during the next milking.";
  }
  if (q.includes("mabel") || q.includes("c05")) {
    return "<strong>Cow C05 Status:</strong><br>" +
      "• Spent 4+ hours resting quietly in Zone A. She was a bit slow to get up—check her front right hoof for any stone or bruise.";
  }
  if (q.includes("differential") || q.includes("diagnosis") || q.includes("pathogen") || q.includes("cause")) {
    return "<strong>What is causing the risk?</strong><br>" +
      "• <strong>Most likely (84%):</strong> Dirty or wet bedding in Rest Zone B. Bacteria in damp bedding can enter teats when cows lie down.<br>" +
      "• <strong>Less likely (16%):</strong> Transfer from a milking cluster in the parlor. Washing milking units between cows prevents this.<br>" +
      "• <strong>Action:</strong> Check Cow C03's udder before milking and milk Cow C03 last.";
  }
  return "<strong>Bovial AI Advisor:</strong> For North Barn (16 cows, 10 tracked), your top focus right now is checking Cow C03's udder before milking.";
}

// Inline farmer advisor form
const farmerInlineForm = document.querySelector("#farmer-inline-chat-form");
if (farmerInlineForm) {
  farmerInlineForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = document.querySelector("#farmer-inline-chat-input");
    const replyEl = document.querySelector("#farmer-inline-chat-reply");
    if (!input || !input.value.trim() || !replyEl) return;
    replyEl.innerHTML = handleAdvisorQuery(input.value.trim());
    replyEl.hidden = false;
  });
}

// Quick chip prompts
document.querySelectorAll(".quick-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const query = chip.dataset.query || chip.textContent;
    const input = document.querySelector("#farmer-inline-chat-input");
    const replyEl = document.querySelector("#farmer-inline-chat-reply");
    if (input) input.value = query;
    if (replyEl) {
      replyEl.innerHTML = handleAdvisorQuery(query);
      replyEl.hidden = false;
    }
  });
});

// Farmer Action buttons
const farmerBtn1 = document.querySelector("#farmer-action-btn-1");
if (farmerBtn1) {
  farmerBtn1.addEventListener("click", () => {
    showView("barn");
    const c03Dot = findCowDot("C03") || findCowDot("Cow C03");
    if (c03Dot) c03Dot.click();
  });
}

const farmerBtn2 = document.querySelector("#farmer-action-btn-2");
if (farmerBtn2) {
  farmerBtn2.addEventListener("click", () => {
    showView("barn");
    const overlayBtn = document.querySelector("#problem-overlay");
    if (overlayBtn && !state.overlay) overlayBtn.click();
  });
}

const farmerBtn3 = document.querySelector("#farmer-action-btn-3");
if (farmerBtn3) {
  farmerBtn3.addEventListener("click", () => {
    showView("milking");
    const stall6 = document.querySelector('.stall[data-stall="6"]');
    if (stall6) stall6.click();
  });
}

// Clinical summary export
const exportClinicalBtn = document.querySelector("#export-clinical-report-btn");
if (exportClinicalBtn) {
  exportClinicalBtn.addEventListener("click", () => {
    const reportText = `BOVIAL CLINICAL CASE SUMMARY\nFarm: North Barn Dairy (Mike Johnson)\nDate: ${state.currentTsUtc || "Aug 4, 11:59 AM UTC"}\nPrimary Veterinarian: Dr. Gregory House\n\nDIFFERENTIAL ATTRIBUTION:\n- Most Supported Route: Environmental Bedding Transmission (Likelihood 84%)\n- Resting Route Permutation p-value: 0.024 (Statistically Significant)\n- Milking Machine Permutation p-value: 0.412 (Non-significant)\n- Suspected Pathogens: E. coli, Streptococcus uberis, S. dysgalactiae\n\nPATIENT INVENTORY:\n- Primary Index Case: Cow C01\n- Acute Clinical Suspect: Cow C03 - Mastitis Risk 85%\n- Rest Zone Contacts: Cow C01, Cow C03, Cow C04\n\nRECOMMENDED INTERVENTIONS:\n1. Complete California Mastitis Test (CMT) on Cow C03 and Cow C01.\n2. Initiate intramammary antimicrobial therapy if CMT score >= 2.\n3. Sanitize and renew organic bedding in Rest Zone B cubicles 1-8.\n4. Milk suspect cows last in milking sequence.`;
    navigator.clipboard?.writeText?.(reportText);
    exportClinicalBtn.textContent = "Copied to clipboard ✓";
    setTimeout(() => { exportClinicalBtn.textContent = "Export clinical summary ↗"; }, 2500);
  });
}

// Partner farm selector for vet view
const partnerFarmSelect = document.querySelector("#partner-farm-select");
if (partnerFarmSelect) {
  partnerFarmSelect.addEventListener("change", (e) => {
    const selected = e.target.value;
    const eyebrow = document.querySelector("#barn-cohort-eyebrow");
    if (selected === "north-barn") {
      loadS12Data();
    } else if (selected === "sunrise-coop") {
      if (eyebrow) eyebrow.textContent = "Sunrise Cooperative (Farmer John Doe) · 120 cows (Demo client)";
    } else if (selected === "green-pastures") {
      if (eyebrow) eyebrow.textContent = "Green Pastures (Farmer Sarah Smith) · 85 cows (Demo client)";
    } else if (selected === "highland-cattle") {
      if (eyebrow) eyebrow.textContent = "Highland Cattle Co. (Farmer David Miller) · 64 cows (Demo client)";
    }
  });
}

// Mark all routine read
const markRoutineBtn = document.querySelector("#mark-all-routine-read");
if (markRoutineBtn) {
  markRoutineBtn.addEventListener("click", () => {
    document.querySelectorAll(".stacked-card").forEach((card) => {
      card.removeAttribute("open");
    });
    markRoutineBtn.textContent = "All routine read ✓";
    setTimeout(() => { markRoutineBtn.textContent = "Mark routine as read"; }, 2000);
  });
}

// Vet contact button
const vetContactBtn = document.querySelector("#vet-contact-btn");
if (vetContactBtn) {
  vetContactBtn.addEventListener("click", () => {
    showView("messages");
  });
}

document.querySelector("#assistant-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.querySelector("#assistant-input");
  const response = document.querySelector("#assistant-response");
  if (!input.value.trim()) return;
  response.innerHTML = handleAdvisorQuery(input.value.trim());
  response.hidden = false;
  input.value = "";
});

document.querySelectorAll(".role-button").forEach((button) => {
  button.addEventListener("click", () => {
    state.role = button.dataset.role;
    document.querySelectorAll(".role-button").forEach((item) => item.classList.toggle("active", item === button));
    applyRolePresentation();
  });
});

// Import Management System Modal Handlers
const importModal = document.querySelector("#import-system-modal");
const openImportBtn = document.querySelector("#open-import-system-btn");
const milkingImportBtn = document.querySelector("#milking-import-btn");
const closeImportBtn = document.querySelector("#close-import-modal-btn");
const cancelImportBtn = document.querySelector("#close-import-modal-cancel");
const importForm = document.querySelector("#import-system-form");
const importProviderSelect = document.querySelector("#import-provider-select");
const importEndpointInput = document.querySelector("#import-endpoint-url");
const importTestBtn = document.querySelector("#import-test-btn");
const importStatusBanner = document.querySelector("#import-status-banner");

const vendorEndpoints = {
  sensehub: "https://api.merck-animal-health.com/sensehub/v2",
  lely: "https://api.lely.com/horizon/v1",
  cowmanager: "https://api.cowmanager.com/v1/telemetry",
  nedap: "https://api.nedap-livestockmanagement.com/v1",
  delaval: "https://delpro.delaval.com/api/v2",
  afimilk: "https://cloud.afimilk.com/farm/api/v1",
};

function openImportModal() {
  if (!importModal) return;
  importModal.hidden = false;
  if (openImportBtn) openImportBtn.setAttribute("aria-expanded", "true");
  if (importStatusBanner) {
    importStatusBanner.className = "modal-status-banner";
    importStatusBanner.style.display = "none";
  }
}

function closeImportModal() {
  if (!importModal) return;
  importModal.hidden = true;
  if (openImportBtn) openImportBtn.setAttribute("aria-expanded", "false");
}

if (openImportBtn) openImportBtn.addEventListener("click", openImportModal);
if (milkingImportBtn) milkingImportBtn.addEventListener("click", openImportModal);
if (closeImportBtn) closeImportBtn.addEventListener("click", closeImportModal);
if (cancelImportBtn) cancelImportBtn.addEventListener("click", closeImportModal);

if (importModal) {
  importModal.addEventListener("click", (e) => {
    if (e.target === importModal) closeImportModal();
  });
  if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !importModal.hidden) closeImportModal();
    });
  }
}

if (importProviderSelect && importEndpointInput) {
  importProviderSelect.addEventListener("change", () => {
    const val = importProviderSelect.value;
    if (vendorEndpoints[val]) {
      importEndpointInput.value = vendorEndpoints[val];
    }
  });
}

if (importTestBtn && importStatusBanner) {
  importTestBtn.addEventListener("click", () => {
    const providerName = importProviderSelect && importProviderSelect.selectedIndex >= 0 ? importProviderSelect.options[importProviderSelect.selectedIndex].text.split(" (")[0] : "Hardware Gateway";
    importStatusBanner.className = "modal-status-banner info";
    importStatusBanner.style.display = "block";
    importStatusBanner.innerHTML = `Testing connection to <strong>${providerName}</strong>...`;
    setTimeout(() => {
      importStatusBanner.className = "modal-status-banner success";
      importStatusBanner.innerHTML = `✓ Connection verified (HTTP 200 OK, latency 38ms). Ready to ingest 16 cow telemetry channels via apis.vendors normalizer.`;
    }, 400);
  });
}

if (importForm && importStatusBanner) {
  importForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const providerName = importProviderSelect && importProviderSelect.selectedIndex >= 0 ? importProviderSelect.options[importProviderSelect.selectedIndex].text.split(" (")[0] : "Hardware Gateway";
    importStatusBanner.className = "modal-status-banner success";
    importStatusBanner.style.display = "block";
    importStatusBanner.innerHTML = `✓ Configuration saved! Ingestion from <strong>${providerName}</strong> scheduled.`;
    setTimeout(() => {
      closeImportModal();
    }, 1200);
  });
}

if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("resize", () => {
    if (state.mode === "heatmap" && state.currentHeatmapData) {
      renderHeatmap(state.currentHeatmapData);
    }
  });
}

applyRolePresentation();
updateColorScaleGuides();
renderWatchListSidebar();
renderMessageThread("fern");
showView("barn");
if (timeLabel) timeLabel.textContent = formatDisplayTime(state.currentTsUtc);
loadS12Data(state.currentTsUtc);

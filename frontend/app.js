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
  modelWatchList: new Set(["Fern 221"]),
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
const configuredApiBase = window.HERDWISE_API_BASE || queryParams.get("api");
const apiBase = (configuredApiBase || "http://127.0.0.1:8000").replace(/\/$/, "");
const interactiveApiBase = (
  window.HERDWISE_INTERACTIVE_API_BASE
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
  if (!status) return;
  status.textContent = message;
  status.className = `data-status ${tone}`.trim();
}

function cowLabel(record) {
  return record.display_name || record.cow_id;
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
}

function renderHeatmap(heatmapData) {
  const canvas = document.querySelector("#heatmap-canvas");
  if (!canvas) return;

  if (state.mode !== "heatmap" || !heatmapData || !Array.isArray(heatmapData) || !heatmapData.length) {
    canvas.hidden = true;
    return;
  }

  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const rows = heatmapData.length;
  const cols = heatmapData[0].length;
  canvas.width = cols * 24;
  canvas.height = rows * 24;
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const cellW = canvas.width / cols;
  const cellH = canvas.height / rows;

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
        ctx.arc(c * cellW + cellW / 2, r * cellH + cellH / 2, cellW * 0.8, 0, Math.PI * 2);
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
    const cutoff = area.until_bedding_change_utc ? ` · until bedding change ${area.until_bedding_change_utc}` : "";
    circle.title = `${area.zone_id || area.cell_id || `Resting area ${index + 1}`} · ${radius} m radius · Model-estimated mastitis exposure area (not a diagnosis)${cutoff}`;
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

  stalls.forEach((stall) => {
    const stallBtn = document.querySelector(`.stall[data-stall="${stall.stall_number}"]`);
    if (!stallBtn) return;

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
    loadMilkingData();
    updateDataBadge([penMap, herdHealth, attribution, impact]);
    setDataStatus("API connected", "connected");
  } catch (error) {
    setDataStatus("Demo fallback · API unavailable", "fallback");
    document.querySelector("#backtrace-status").textContent = "The visualization service is unavailable; demo panels remain visible.";
    if (!state.s12.penMap) {
      document.querySelectorAll(".cow-dot:not(.api-cow)").forEach((dot) => {
        dot.hidden = false;
      });
    }
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
  if (view === "milking") {
    loadMilkingData();
  }
}

function applyRolePresentation() {
  document.body.classList.toggle("farmer-mode", state.role === "farmer");
  document.body.classList.toggle("vet-mode", state.role === "vet");
  document.querySelector(".welcome-row h1").textContent = state.role === "vet"
    ? "Herd detail for clinical review"
    : "Today’s farm priorities";
  document.querySelector(".section-heading h2").textContent = state.role === "vet"
    ? "Barn overview and risk context"
    : "Where should I look first?";
  const toggle = document.querySelector("#role-details-toggle");
  if (toggle) toggle.textContent = state.role === "vet" ? "Hide model details ↑" : "View model details →";
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
    document.querySelector(".map-legend").innerHTML = state.mode === "heatmap"
      ? "Gradient shows time spent idling"
      : '<i class="legend-dot healthy"></i> Cow location';
    renderHeatmap(state.s12.penMap?.grid?.heatmap);
  });
});

document.querySelector("#problem-overlay").addEventListener("click", (event) => {
  state.overlay = !state.overlay;
  event.currentTarget.classList.toggle("on", state.overlay);
  document.querySelector(".barn-polygon").classList.toggle("risk-overlay", state.overlay);
  const target = document.querySelector("#resting-overlays");
  if (target) target.classList.toggle("active-overlay", state.overlay);
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

function isOnWatchList(cow) {
    return state.modelWatchList.has(cow) || state.manualWatchList.has(cow);
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
  title.textContent = state.selectedCow;
  empty.hidden = true;
  content.hidden = false;
  document.querySelector("#flag-illness").textContent = isOnWatchList(state.selectedCow) ? "Remove from watch list" : "Add to watch list";

  if (rec && !rec.is_instrumented && rec.factors?.includes("Uninstrumented cohort animal")) {
    document.querySelector("#resting-spots").innerHTML = '<span class="resting-spot">Uninstrumented cohort animal · No active sensor telemetry</span>';
    document.querySelector("#co-resters").innerHTML = '<strong>Cohort animal</strong><p class="muted">Part of the uninstrumented 16-cow pen cohort.</p>';
  } else if (rec?.out_of_pen) {
    document.querySelector("#resting-spots").innerHTML = '<span class="resting-spot">Out of pen · Milking / handling activity</span>';
    document.querySelector("#co-resters").innerHTML = '<strong>Out of pen</strong><p class="muted">Currently outside the pen grid.</p>';
  } else {
    document.querySelector("#resting-spots").innerHTML = state.restingFilter
      ? `<span class="resting-spot">${zoneLabel} · 10:42 AM</span><span class="resting-spot">${zoneLabel} · 7:18 AM</span><span class="resting-spot">Rest zone A · yesterday</span>`
      : `<span class="resting-spot">Last seen: ${zoneLabel}</span><span class="resting-spot">3 recorded spots</span>`;
    document.querySelector("#co-resters").innerHTML = `<strong>${coResters.length} other cows shared this resting area</strong><ul>${coResters.map((name) => `<li>${name} <span class="shared-label">shared resting area</span></li>`).join("")}</ul>`;
  }

  document.querySelectorAll(".cow-dot").forEach((dot) => {
    dot.classList.toggle("shared-resting", state.restingFilter && dot.dataset.restZone === zone && dot.dataset.cow !== state.selectedCow);
  });
  document.querySelector("#flag-count").textContent = `${state.modelWatchList.size + state.manualWatchList.size} on watch list`;
}

document.querySelector("#flag-illness").addEventListener("click", () => {
  if (!state.selectedCow) return;
  if (state.manualWatchList.has(state.selectedCow)) state.manualWatchList.delete(state.selectedCow);
  else state.manualWatchList.add(state.selectedCow);
  const selected = document.querySelector(`[data-cow="${state.selectedCow}"]`);
  selected.classList.toggle("manual-watch", state.manualWatchList.has(state.selectedCow));
  renderRestingFilter();
});

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
    detailEl.innerHTML = `<strong>Stall ${stall.dataset.stall}</strong> · ${highRisk ? "Model-flagged exposure risk" : "Within baseline"}<br><span>${highRisk ? "2 cows flagged in recent cycles: Fern 221, Poppy 164." : "Last cow: Daisy 108 · 34.6 L · 10:21 AM."}</span>`;
  });
});

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector("#assistant-input").value = button.textContent;
    document.querySelector("#assistant-form").requestSubmit();
  });
});

document.querySelectorAll(".citation").forEach((button) => {
  button.addEventListener("click", () => {
    const target = document.querySelector("#selected-citation");
    target.textContent = `Selected reference: ${button.dataset.citation}`;
    target.hidden = false;
  });
});

document.querySelectorAll(".message-thread").forEach((thread) => {
  thread.addEventListener("click", () => {
    document.querySelectorAll(".message-thread").forEach((item) => item.classList.toggle("active", item === thread));
    document.querySelector("#conversation-title").textContent = thread.dataset.thread === "herd" ? "Herd report · July 28" : "Fern 221 · follow-up";
  });
});

document.querySelector("#message-citation").addEventListener("click", () => {
  const selected = document.querySelector("#selected-citation");
  selected.textContent = selected.hidden ? "Select a report, cow alert, or resting area to cite it here." : selected.textContent;
  selected.hidden = false;
});

document.querySelector("#message-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.querySelector("#message-input");
  const value = input.value.trim();
  if (!value) return;
  const message = document.createElement("article");
  message.className = "message sent";
  const author = document.createElement("span");
  author.className = "message-author";
  author.textContent = "You";
  const body = document.createElement("p");
  body.textContent = value;
  message.append(author, body);
  document.querySelector("#message-list").append(message);
  input.value = "";
});

document.querySelector("#assistant-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.querySelector("#assistant-input");
  const response = document.querySelector("#assistant-response");
  if (!input.value.trim()) return;
  response.textContent = "Based on the latest synced data, I recommend checking Fern 221 before the next milking. This is a model suggestion, not a diagnosis.";
  response.hidden = false;
  input.value = "";
});

document.querySelectorAll(".role-button").forEach((button) => {
  button.addEventListener("click", () => {
    state.role = button.dataset.role;
    document.querySelectorAll(".role-button").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelector(".partner-summary .field-label").textContent = state.role === "vet" ? "Partner farms" : "Care team";
    applyRolePresentation();
  });
});

applyRolePresentation();
updateColorScaleGuides();
showView("barn");
if (timeLabel) timeLabel.textContent = formatDisplayTime(state.currentTsUtc);
loadS12Data(state.currentTsUtc);

const state = {
  view: "barn",
  mode: "location",
  role: "farmer",
  overlay: false,
  selectedCow: null,
  restingFilter: false,
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
};

const timeLabel = document.querySelector("#time-label");
const slider = document.querySelector("#time-slider");
const views = ["barn", "milking", "alerts"];
const apiBase = (window.HERDWISE_API_BASE || new URLSearchParams(window.location.search).get("api") || "http://127.0.0.1:8000").replace(/\/$/, "");

async function fetchApi(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
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
    detail.textContent = `${dot.dataset.cow} · ${state.modelWatchList.has(dot.dataset.cow) ? "Elevated risk · model" : state.manualWatchList.has(dot.dataset.cow) ? "Vet watch list" : "Within baseline"}`;
    detail.hidden = false;
    renderRestingFilter();
  });
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
  dot.dataset.cow = cowLabel(record);
  dot.dataset.restZone = record.zone || "zone-a";
  dot.title = `${cowLabel(record)} · ${record.flag_status === "flagged" ? "Flagged for review" : "Observed by model"}`;
  const width = state.s12.penMap?.grid?.width_m || 30;
  const height = state.s12.penMap?.grid?.height_m || 15;
  const x = Number(record.uwb_x_m ?? record.x_coord ?? ((index + 1) * width) / 10);
  const y = Number(record.uwb_y_m ?? record.y_coord ?? ((index + 1) * height) / 10);
  dot.style.left = `${Math.max(3, Math.min(95, (x / width) * 100))}%`;
  dot.style.top = `${Math.max(8, Math.min(90, (y / height) * 100))}%`;
  dot.hidden = false;
  dot.classList.toggle("api-flagged", record.flag_status === "flagged");
  dot.classList.toggle("api-exposed", Number(record.exposure_score || 0) > 0.35);
  dot.classList.toggle("api-source", Boolean(record.is_source_candidate));
  state.cowRecords.set(dot.dataset.cow, record);
  return dot;
}

function renderPenMap(payload) {
  state.s12.penMap = payload;
  const records = payload?.cows || [];
  document.querySelectorAll(".cow-dot.api-cow").forEach((dot) => { dot.hidden = true; });
  records.forEach((record, index) => ensureCowDot(record, index));
  const polygon = document.querySelector(".barn-polygon");
  polygon.classList.toggle("api-risk-overlay", records.some((record) => record.flag_status === "flagged" || Number(record.exposure_score || 0) > 0.35));
  renderRestingOverlays(payload);
}

function renderRestingOverlays(payload) {
  const target = document.querySelector("#resting-overlays");
  if (!target) return;
  const hasOverlayData = Object.prototype.hasOwnProperty.call(payload || {}, "resting_areas")
    || Object.prototype.hasOwnProperty.call(payload?.implicated_elements || {}, "resting_areas");
  if (!hasOverlayData) return;
  target.replaceChildren();
  document.querySelectorAll(".cow-dot.resting-contact").forEach((dot) => dot.classList.remove("resting-contact"));
  const areas = payload?.resting_areas || payload?.implicated_elements?.resting_areas || [];
  const width = Number(payload?.grid?.width_m || state.s12.penMap?.grid?.width_m || 30);
  const height = Number(payload?.grid?.height_m || state.s12.penMap?.grid?.height_m || 15);
  areas.forEach((area, index) => {
    const x = Number(area.center_x_m ?? area.x_m ?? area.x ?? 0);
    const y = Number(area.center_y_m ?? area.y_m ?? area.y ?? 0);
    const radius = Number(area.radius_m ?? area.radius ?? 1.5);
    const circle = document.createElement("div");
    circle.className = "resting-circle";
    circle.style.left = `${Math.max(0, ((x - radius) / width) * 100)}%`;
    circle.style.top = `${Math.max(0, ((y - radius) / height) * 100)}%`;
    circle.style.width = `${(radius * 2 / width) * 100}%`;
    circle.style.height = `${(radius * 2 / height) * 100}%`;
    circle.title = `${area.zone_id || area.cell_id || `Resting area ${index + 1}`} · ${radius} m radius`;
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
    milking_equipment: "Milking equipment",
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

function renderAttribution(payload) {
  state.s12.attribution = payload;
  renderRestingOverlays(payload);
  const source = payload?.transmission_source || {};
  const pValues = payload?.p_values || {};
  const actions = payload?.recommended_actions || [];
  const restingAreas = payload?.resting_areas || payload?.transmission_source?.resting_areas || [];
  const restingSummary = restingAreas.length
    ? `<div class="source-note"><strong>Real resting areas:</strong> ${restingAreas.map((area) => area.zone_id || area.cell_id || "area").join(", ")} · 1.5 m contact radius, bounded by bedding changes.</div>`
    : "";
  const sourceSummary = restingAreas.length
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

async function loadS12Data() {
  try {
    const [penMap, herdHealth, attribution, impact] = await Promise.all([
      fetchApi("/api/pen-map"),
      fetchApi("/api/herd-health"),
      fetchApi("/api/attribution"),
      fetchApi("/api/impact"),
    ]);
    renderPenMap(penMap);
    renderHerdHealth(herdHealth);
    renderAttribution(attribution);
    renderImpact(impact);
    updateDataBadge([penMap, herdHealth, attribution, impact]);
    setDataStatus("API connected", "connected");
  } catch (error) {
    setDataStatus("Demo fallback · API unavailable", "fallback");
    document.querySelector("#backtrace-status").textContent = "The visualization service is unavailable; demo panels remain visible.";
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
  });
});

document.querySelector("#problem-overlay").addEventListener("click", (event) => {
  state.overlay = !state.overlay;
  event.currentTarget.classList.toggle("on", state.overlay);
  document.querySelector(".barn-polygon").classList.toggle("risk-overlay", state.overlay);
});

document.querySelectorAll(".cow-dot").forEach(attachCowDot);

document.querySelectorAll('input[name="color-by"]').forEach((input) => {
  input.addEventListener("change", () => {
    const mode = input.value;
    const colors = {
      status: ["#4fbe89", "#6f96e8", "#d75f51", "#a971cc", "#e6a23c"],
      health: ["#4fbe89", "#4fbe89", "#d75f51", "#e6a23c", "#4fbe89"],
      behavior: ["#4fbe89", "#e6a23c", "#d75f51", "#d75f51", "#4fbe89"],
    }[mode];
    document.querySelectorAll(".cow-dot").forEach((dot, index) => {
      dot.style.background = colors[index % colors.length];
    });
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
    const zone = cow.dataset.restZone;
    const zoneLabel = zone === "zone-a" ? "Rest zone A" : "Rest zone B";
    const coResters = [...document.querySelectorAll(`.cow-dot[data-rest-zone="${zone}"]`)]
      .map((dot) => dot.dataset.cow)
      .filter((name) => name !== state.selectedCow);
    title.textContent = state.selectedCow;
    empty.hidden = true;
    content.hidden = false;
    document.querySelector("#flag-illness").textContent = isOnWatchList(state.selectedCow) ? "Remove from watch list" : "Add to watch list";
    document.querySelector("#resting-spots").innerHTML = state.restingFilter
      ? `<span class="resting-spot">${zoneLabel} · 10:42 AM</span><span class="resting-spot">${zoneLabel} · 7:18 AM</span><span class="resting-spot">Rest zone A · yesterday</span>`
      : `<span class="resting-spot">Last seen: ${zoneLabel}</span><span class="resting-spot">3 recorded spots</span>`;
    document.querySelector("#co-resters").innerHTML = `<strong>${coResters.length} other cows shared this resting area</strong><ul>${coResters.map((name) => `<li>${name} <span class="shared-label">shared resting area</span></li>`).join("")}</ul>`;
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
    const result = await fetchApi("/backtrace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        flags: [...state.groupFlags].map(([cowId]) => ({ cow_id: cowId, timestamp: new Date().toISOString(), source: "manual" })),
        lookback_hours: 72,
      }),
    });
    renderAttribution(result);
    renderRestingOverlays(result);
    if (result.impact) renderImpact(result.impact);
    status.textContent = `Backtrace complete · ${routeLabel(result.likely_route)} most supported.`;
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

slider.addEventListener("input", () => {
  const hour = Number(slider.value);
  const suffix = hour >= 12 ? "PM" : "AM";
  const displayHour = hour % 12 || 12;
  timeLabel.textContent = `Today, ${displayHour}:00 ${suffix}`;
});

document.querySelectorAll(".stall").forEach((stall) => {
  stall.addEventListener("click", () => {
    const highRisk = stall.classList.contains("risk-high");
    document.querySelector("#stall-detail").innerHTML = `<strong>Stall ${stall.dataset.stall}</strong> · ${highRisk ? "High mastitis risk" : "Within baseline"}<br><span>${highRisk ? "2 cows flagged in the last cycle: Fern 221, Poppy 164." : "Last cow: Daisy 108 · 34.6 L · 10:21 AM."}</span>`;
  });
});

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector("#assistant-input").value = button.textContent;
    document.querySelector("#assistant-form").requestSubmit();
  });
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
  });
});

showView("barn");
loadS12Data();

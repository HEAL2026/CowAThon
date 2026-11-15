const state = {
  view: "barn",
  mode: "location",
  role: "farmer",
  overlay: false,
  selectedCow: null,
  restingFilter: false,
  flaggedCows: new Set(["Fern 221"]),
};

const timeLabel = document.querySelector("#time-label");
const slider = document.querySelector("#time-slider");
const views = ["barn", "milking", "alerts"];

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

document.querySelectorAll(".cow-dot").forEach((cow) => {
  cow.addEventListener("click", () => {
    state.selectedCow = cow.dataset.cow;
    const detail = document.querySelector("#cow-detail");
    document.querySelectorAll(".cow-dot").forEach((dot) => dot.classList.toggle("selected", dot === cow));
    detail.innerHTML = `${cow.dataset.cow} · ${state.flaggedCows.has(cow.dataset.cow) ? "Flagged for review" : "Within baseline"}`;
    detail.hidden = false;
    renderRestingFilter();
  });
});

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
    document.querySelector("#flag-illness").textContent = state.flaggedCows.has(state.selectedCow) ? "Remove illness flag" : "Flag as ill";
    document.querySelector("#resting-spots").innerHTML = state.restingFilter
      ? `<span class="resting-spot">${zoneLabel} · 10:42 AM</span><span class="resting-spot">${zoneLabel} · 7:18 AM</span><span class="resting-spot">Rest zone A · yesterday</span>`
      : `<span class="resting-spot">Last seen: ${zoneLabel}</span><span class="resting-spot">3 recorded spots</span>`;
    document.querySelector("#co-resters").innerHTML = `<strong>${coResters.length} other cows rested here</strong><ul>${coResters.map((name) => `<li>${name} <span class="flagged-label">flagged for exposure</span></li>`).join("")}</ul>`;
    document.querySelectorAll(".cow-dot").forEach((dot) => {
      dot.classList.toggle("co-resting", state.restingFilter && dot.dataset.restZone === zone && dot.dataset.cow !== state.selectedCow);
    });
    document.querySelector("#flag-count").textContent = `${state.flaggedCows.size + (state.restingFilter ? coResters.length : 0)} flagged`;
  }

  document.querySelector("#flag-illness").addEventListener("click", () => {
    if (!state.selectedCow) return;
    if (state.flaggedCows.has(state.selectedCow)) state.flaggedCows.delete(state.selectedCow);
    else state.flaggedCows.add(state.selectedCow);
    const selected = document.querySelector(`[data-cow="${state.selectedCow}"]`);
    selected.classList.toggle("manual-flagged", state.flaggedCows.has(state.selectedCow) && !selected.classList.contains("auto-flagged"));
    renderRestingFilter();
  });

  document.querySelector("#filter-resting").addEventListener("click", () => {
    state.restingFilter = !state.restingFilter;
    document.querySelector("#filter-resting").textContent = state.restingFilter ? "Clear resting filter" : "Show resting spots";
    renderRestingFilter();
  });
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

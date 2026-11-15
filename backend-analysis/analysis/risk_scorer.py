"""Multimodal watch-list risk scoring engine with graceful missing-modality degradation.

Combines four physiological and behavioral signal components:
1. Thermal Strain (0 - 40 pts): CBT elevation & ambient THI exposure
2. Behavioral Anomaly (0 - 30 pts): Rumination depression & activity abnormalities
3. Production Deficit (0 - 20 pts): Daily milk yield drop relative to rolling baseline
4. Movement & Spatial Strain (0 - 10 pts): Idling/crowding latency (aware of out_of_pen state)

Strictly non-diagnostic: outputs risk category (baseline / moderate_watch / priority_watch)
and actionable management suggestions.
"""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd

from .env_thermal import calculate_thi, categorize_thi_strain
from .cbt_strain import calculate_cbt_strain_score
from .behavior import (
    calculate_activity_index,
    calculate_rumination_proxy,
    calculate_behavior_anomaly_score,
)


class MultimodalRiskScorer:
    """Computes transparent, auditable multimodal watch-list risk scores."""

    def __init__(
        self,
        cbt_weight: float = 40.0,
        behavior_weight: float = 30.0,
        production_weight: float = 20.0,
        movement_weight: float = 10.0,
    ):
        self.cbt_weight = cbt_weight
        self.behavior_weight = behavior_weight
        self.production_weight = production_weight
        self.movement_weight = movement_weight

    def score_record(self, row: dict[str, Any] | pd.Series) -> dict[str, Any]:
        """Score a single observation or summary row."""
        modalities_present: list[str] = []
        missing_modalities: list[str] = []
        contributing_factors: list[str] = []
        recommended_actions: list[str] = []

        total_score = 0.0
        confidence = 1.0

        # 1. Thermal strain component (0 - 40)
        cbt_val = row.get("cbt_c") if row.get("cbt_c") is not None else row.get("cbt")
        thi_val = row.get("indoor_thi") if row.get("indoor_thi") is not None else row.get("thi")

        if thi_val is None:
            temp = row.get("indoor_temp_c") if row.get("indoor_temp_c") is not None else row.get("temp_c")
            rh = row.get("indoor_rh_pct") if row.get("indoor_rh_pct") is not None else row.get("rh_pct")
            if temp is not None and rh is not None:
                thi_val = calculate_thi(temp, rh)

        thermal_score = 0.0
        if cbt_val is not None and not pd.isna(cbt_val):
            modalities_present.append("cbt")
            cbt_strain = calculate_cbt_strain_score(float(cbt_val), max_points=self.cbt_weight)
            thermal_score += cbt_strain
            if cbt_val >= 39.5:
                contributing_factors.append(f"CBT elevated ({cbt_val:.2f}°C)")
        else:
            missing_modalities.append("cbt")
            confidence -= 0.35

        if thi_val is not None and not pd.isna(thi_val):
            modalities_present.append("indoor_env")
            if thi_val >= 72.0:
                thi_boost = min(10.0, (thi_val - 72.0) * 1.5)
                thermal_score = min(self.cbt_weight, thermal_score + thi_boost)
                contributing_factors.append(f"THI indicates heat stress ({thi_val:.1f})")
        else:
            missing_modalities.append("indoor_env")
            confidence -= 0.15

        total_score += min(self.cbt_weight, thermal_score)

        # 2. Behavioral anomaly component (0 - 30)
        act_val = row.get("neck_imu_magnitude_std") if row.get("neck_imu_magnitude_std") is not None else row.get("activity_index")
        rum_val = row.get("rumination_proxy")

        if act_val is None and "acc_x_std" in row:
            act_val = float(np.sqrt(row["acc_x_std"]**2 + row["acc_y_std"]**2 + row["acc_z_std"]**2))

        if act_val is not None and not pd.isna(act_val):
            modalities_present.append("neck_imu")
            if rum_val is None or pd.isna(rum_val):
                rum_val = 100.0 * np.exp(-((act_val - 0.12) ** 2) / (2 * (0.04**2)))

            behavior_score = 0.0
            if rum_val < 40.0:
                deficit = (40.0 - rum_val) / 40.0
                behavior_score += deficit * 20.0
                contributing_factors.append(f"Rumination proxy depressed ({rum_val:.1f} / 100)")
            # In live cattle, sustained movement < 0.10 m/s² indicates extreme lethargy
            if act_val < 0.10:
                behavior_score += 10.0
                contributing_factors.append("Prolonged lethargy / immobility")

            total_score += min(self.behavior_weight, behavior_score)
        else:
            missing_modalities.append("neck_imu")
            confidence -= 0.25

        # 3. Production deficit component (0 - 20)
        milk_drop_pct = row.get("milk_drop_pct")
        milk_val = row.get("milk_yield_kg") if row.get("milk_yield_kg") is not None else row.get("milk_yield")
        if (milk_drop_pct is not None and not pd.isna(milk_drop_pct)) or (milk_val is not None and not pd.isna(milk_val)):
            modalities_present.append("milk_yield")
            if milk_drop_pct is not None and milk_drop_pct > 5.0:
                drop_score = min(self.production_weight, (milk_drop_pct - 5.0) * 1.0)
                total_score += drop_score
                contributing_factors.append(f"Milk yield depressed {milk_drop_pct:.1f}% below rolling baseline")
        else:
            missing_modalities.append("milk_yield")
            confidence -= 0.15

        # 4. Movement / Spatial strain component (0 - 10)
        out_of_pen = bool(row.get("out_of_pen", False))
        idling_fraction = row.get("idling_fraction")
        uwb_present = (row.get("uwb_x_m") is not None and not pd.isna(row.get("uwb_x_m"))) or idling_fraction is not None

        if out_of_pen:
            modalities_present.append("uwb")
        elif uwb_present:
            modalities_present.append("uwb")
            if idling_fraction is not None and idling_fraction > 0.6:
                total_score += min(self.movement_weight, (idling_fraction - 0.6) * 20.0)
                contributing_factors.append("Extended idling in high-density barn zone")
        else:
            missing_modalities.append("uwb")
            confidence -= 0.10

        # Adjust score if key modalities are missing (re-weight available)
        available_weight = sum([
            self.cbt_weight if "cbt" in modalities_present else 0.0,
            self.behavior_weight if "neck_imu" in modalities_present else 0.0,
            self.production_weight if "milk_yield" in modalities_present else 0.0,
            self.movement_weight if "uwb" in modalities_present else 0.0,
        ])

        if available_weight > 0 and available_weight < 100.0:
            scale_factor = 100.0 / available_weight
            final_score = min(100.0, total_score * scale_factor)
        else:
            final_score = min(100.0, total_score)

        # Categorize
        if final_score >= 70.0:
            category = "priority_watch"
            recommended_actions.append("Inspect animal closely for heat stress, respiratory rate, and feed access")
            recommended_actions.append("Verify cooling fans and misters in resting stalls")
        elif final_score >= 40.0:
            category = "moderate_watch"
            recommended_actions.append("Monitor animal at upcoming milking and check water intake")
        else:
            category = "baseline"
            recommended_actions.append("Maintain standard herd management schedule")

        confidence = max(0.2, min(1.0, confidence))

        return {
            "cow_id": row.get("cow_id", "unknown"),
            "latest_ts_utc": str(row.get("ts_utc", "")),
            "watch_risk_score": round(float(final_score), 1),
            "risk_category": category,
            "confidence_score": round(float(confidence), 2),
            "modalities_present": modalities_present,
            "missing_modalities": missing_modalities,
            "contributing_factors": contributing_factors,
            "recommended_actions": recommended_actions,
            "is_model_suggestion": True,
        }

    def score_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Score an entire DataFrame of joined sensor observations."""
        results = [self.score_record(row) for _, row in df.iterrows()]
        res_df = pd.DataFrame(results)
        return res_df

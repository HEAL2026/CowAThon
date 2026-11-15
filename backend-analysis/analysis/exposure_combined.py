"""S10: Combined exposure integration.

Synthesizes environmental resting-route and contagious milking-route exposure:
- Blends multi-channel exposure scores per animal.
- Flags uninfected in-contact animals with high cumulative exposure.
- Provides actionable preventative monitoring guidance prior to clinical symptom onset.
"""

from __future__ import annotations
from typing import Any


def calculate_combined_exposure(
    resting_exposure: dict[str, float],
    milking_exposure: dict[str, float],
    base_risk_scores: dict[str, float] | None = None,
    flagged_cows: set[str] | list[str] | None = None,
) -> dict[str, Any]:
    """Combine resting-route and milking-route exposure into unified herd contact scores.

    Args:
        resting_exposure: Dictionary mapping cow_id to resting exposure score [0.0, 1.0].
        milking_exposure: Dictionary mapping cow_id to milking exposure score [0.0, 1.0].
        base_risk_scores: Optional dictionary mapping cow_id to pre-existing mastitis risk [0.0, 100.0].
        flagged_cows: Optional set of already-flagged index cases.

    Returns:
        Dictionary with combined_exposure (dict) and exposed_cows (list of detailed records).
    """
    flag_set = set(flagged_cows) if flagged_cows else set()
    all_cows = sorted(set(resting_exposure.keys()) | set(milking_exposure.keys()))

    combined_scores: dict[str, float] = {}
    exposed_cows: list[dict[str, Any]] = []

    for cid in all_cows:
        e_rest = float(resting_exposure.get(cid, 0.0))
        e_milk = float(milking_exposure.get(cid, 0.0))

        if cid in flag_set:
            combined_scores[cid] = 1.0
            continue

        # Probability of at least one exposure event
        e_comb = float(round(1.0 - (1.0 - e_rest) * (1.0 - e_milk), 3))
        combined_scores[cid] = e_comb

        if e_comb >= 0.20:
            # Primary route
            if e_rest > e_milk:
                primary_route = "resting_environment"
                rec_action = "Inspect resting cubicle cleanliness; apply dry disinfectant bedding powder"
            elif e_milk > e_rest:
                primary_route = "milking_equipment"
                rec_action = "Sanitize teat cluster before attaching; inspect teat end condition"
            else:
                primary_route = "dual_contact"
                rec_action = "Execute comprehensive parlor and bedding disinfection protocol"

            base_risk = float(base_risk_scores.get(cid, 0.0)) if base_risk_scores else 0.0
            contact_adjusted_risk = round(max(base_risk, e_comb * 65.0), 1)

            exposed_cows.append({
                "cow_id": cid,
                "combined_exposure_score": e_comb,
                "resting_exposure_score": e_rest,
                "milking_exposure_score": e_milk,
                "primary_route": primary_route,
                "contact_adjusted_risk": contact_adjusted_risk,
                "recommended_preventative_action": rec_action,
            })

    # Sort exposed cows by combined exposure descending
    exposed_cows.sort(key=lambda x: x["combined_exposure_score"], reverse=True)

    return {
        "combined_exposure": combined_scores,
        "exposed_cows": exposed_cows,
    }

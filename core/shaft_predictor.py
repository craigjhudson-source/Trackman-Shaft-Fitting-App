# core/shaft_predictor.py

import pandas as pd


def predict_shaft_winners(df_shafts: pd.DataFrame, carry_6i: float):
    """
    Phase 1 shaft prediction engine.
    Frozen logic — do not modify without version bump.
    """

    # Carry → target flex / weight mapping
    if carry_6i >= 195:
        f_tf, ideal_w = 8.5, 130
    elif carry_6i >= 180:
        f_tf, ideal_w = 7.0, 125
    elif carry_6i >= 165:
        f_tf, ideal_w = 6.0, 110
    else:
        f_tf, ideal_w = 5.0, 95

    df_all = df_shafts.copy()

    for col in ["FlexScore", "Weight (g)", "StabilityIndex", "LaunchScore", "EI_Mid"]:
        df_all[col] = pd.to_numeric(df_all[col], errors="coerce").fillna(0)

    def get_top_3(mode):
        df_t = df_all.copy()

        df_t["Penalty"] = (
            abs(df_t["FlexScore"] - f_tf) * 200 +
            abs(df_t["Weight (g)"] - ideal_w) * 15
        )

        if carry_6i >= 180:
            df_t.loc[df_t["FlexScore"] < 6.5, "Penalty"] += 4000

        if mode == "Maximum Stability":
            df_t["Penalty"] -= (df_t["StabilityIndex"] * 600)
        elif mode == "Launch & Height":
            df_t["Penalty"] -= (df_t["LaunchScore"] * 500)
        elif mode == "Feel & Smoothness":
            df_t["Penalty"] += (df_t["EI_Mid"] * 400)

        return df_t.sort_values("Penalty").head(3)[
            ["Brand", "Model", "Flex", "Weight (g)"]
        ]

    winners = {
        k: get_top_3(k)
        for k in ["Balanced", "Maximum Stability", "Launch & Height", "Feel & Smoothness"]
    }

    return winners

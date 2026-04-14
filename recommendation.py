"""
Legacy simple filter-based recommender.
This module is superseded by model/recommender.py (hybrid ML system).
Kept only as a fallback utility.

FIX: Removed module-level pd.read_csv() call which would crash on import
     if the working directory is wrong. CSV is now loaded inside the function.
"""

import pandas as pd


def get_recommendations(destination, budget, season, interest, csv_path="maharashtra_destinations.csv"):
    """
    Simple rule-based filter recommender (legacy, non-ML).
    Use hybrid_recommendation from model/recommender.py for the full ML system.
    """
    df = pd.read_csv(csv_path)  # FIX: moved inside function — safe on import
    df.columns = df.columns.str.strip()

    df["Type"]     = df["Type"].astype(str).str.strip().str.lower()
    df["Budget"]   = df["Budget"].astype(str).str.strip().str.lower()
    df["Season"]   = df["Season"].astype(str).str.strip().str.lower()
    df["Interest"] = df["Interest"].astype(str).str.strip().str.lower()

    destination = destination.strip().lower()
    budget      = budget.strip().lower()
    season      = season.strip().lower()
    interest    = interest.strip().lower()

    df_filtered = df.copy()

    if destination != "select":
        df_filtered = df_filtered[df_filtered["Type"] == destination]
    if budget != "select":
        df_filtered = df_filtered[df_filtered["Budget"] == budget]
    if season != "select":
        df_filtered = df_filtered[
            (df_filtered["Season"] == season) | (df_filtered["Season"] == "all")
        ]
    if interest != "select":
        df_filtered = df_filtered[df_filtered["Interest"] == interest]

    # Fallback: if nothing matches, return all places of the requested type
    if df_filtered.empty and destination != "select":
        df_filtered = df[df["Type"] == destination]

    recommendations = []
    for _, row in df_filtered.iterrows():
        explanation_parts = []
        if destination != "select" and row["Type"] == destination:
            explanation_parts.append("Matches your selected destination type")
        if budget != "select" and row["Budget"] == budget:
            explanation_parts.append("Fits your selected budget")
        if interest != "select" and row["Interest"] == interest:
            explanation_parts.append("Aligned with your travel interest")
        if season != "select" and row["Season"] in (season, "all"):
            explanation_parts.append("Suitable for selected season")

        recommendations.append({
            "place":       row["Place"],
            "rating":      row["Rating"],
            "cost":        row["Approx_Cost"],
            "Image_URL":   row["Image_URL"],
            "explanation": ", ".join(explanation_parts),
        })

    return recommendations

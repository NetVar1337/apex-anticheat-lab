"""Score a player population against a fitted baseline and emit a review queue.

Usage:
    python detectors.py --samples ../data/match_samples.csv \
                        --baseline ../data/baseline.json \
                        --out ../data/scores.csv

Output is a **review queue**, not a verdict. Every row carries the per-feature z-scores
that produced it so an analyst can see exactly which behaviour drove the score and argue
with a specific number.

Directionality matters: for some metrics (fire latency, recoil residual, jerk) *low* is
suspicious; for others (snap ratio, recoil regularity, headshot rate) *high* is suspicious.
Each metric therefore carries a ``tail`` in FEATURE_WEIGHTS.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from aim_metrics import load_samples, population_metrics

# (weight, tail) — tail=+1 means high values are suspicious, -1 means low, 0 = two-sided
FEATURE_WEIGHTS: dict[str, tuple[float, int]] = {
    "fitts_slope":        (1.0, -1),   # flat acquisition-vs-distance = snap aiming
    "snap_ratio":         (1.2, +1),   # spike-then-stop acquisitions
    "reaction_med_ms":    (1.1, -1),   # faster than human floor
    "fire_latency_med_ms":(1.3, -1),   # triggerbot signature
    "recoil_regularity":  (1.3, +1),   # deterministic compensation
    "recoil_residual":    (1.1, -1),   # nothing left after subtracting the pattern
    "hs_rate":            (0.8, +1),
    "accuracy":           (0.6, +1),
    "track_smoothness":   (0.7, +1),   # unnaturally smooth tracking
    "jerk_p95":           (0.5, 0),    # both hyper-jitter and hyper-smooth are odd
}


def z_scores(metrics: pd.DataFrame, baselines: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=metrics.index)
    for feature, (weight, tail) in FEATURE_WEIGHTS.items():
        col = np.full(len(metrics), np.nan)
        for i, (cohort, val) in enumerate(zip(metrics["cohort"], metrics[feature])):
            b = baselines.get(str(cohort), {}).get(feature)
            if not b or not b.get("usable"):
                continue
            x = float(val)
            if not np.isfinite(x):
                continue
            sigma = b.get("sigma")
            if sigma is not None and np.isfinite(sigma) and sigma > 0:
                z = (x - b["median"]) / sigma
            else:
                # fall back to percentile rank mapped to a z-like scale
                lo, hi = b["p01"], b["p99"]
                if not (np.isfinite(lo) and np.isfinite(hi) and hi > lo):
                    continue
                z = 4.0 * ((x - lo) / (hi - lo) - 0.5)
            col[i] = z * tail if tail else abs(z)
        out[f"z_{feature}"] = col
        out[f"w_{feature}"] = weight
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-matches", type=int, default=2,
                    help="require this many distinct matches before scoring (cross-match consistency)")
    args = ap.parse_args()

    df = load_samples(args.samples)
    metrics = population_metrics(df)
    baselines = json.loads(Path(args.baseline).read_text(encoding="utf-8"))["baselines"]

    z = z_scores(metrics, baselines)
    feats = [f for f in FEATURE_WEIGHTS if f"z_{f}" in z.columns]

    # weighted mean over available features; require at least 3 to score at all
    num = pd.DataFrame({f: z[f"z_{f}"] * z[f"w_{f}"] for f in feats})
    den = pd.DataFrame({f: z[f"w_{f}"] * z[f"z_{f}"].notna() for f in feats})
    n_avail = den.sum(axis=1)
    score = num.sum(axis=1) / den.sum(axis=1).replace(0, np.nan)
    score[n_avail < 3] = np.nan

    result = metrics.copy()
    result["score"] = score
    result["features_used"] = n_avail
    result["n_matches"] = metrics.get("n_matches", 1.0)

    def top_features(row) -> str:
        pairs = []
        for f in feats:
            v = row.get(f"z_{f}")
            if pd.notna(v):
                pairs.append((f, float(v)))
        pairs.sort(key=lambda kv: abs(kv[1]), reverse=True)
        return "; ".join(f"{k}={v:+.2f}" for k, v in pairs[:5])

    result["top_features"] = [top_features(r) for _, r in z.iterrows()]
    result = result.sort_values("score", ascending=False)

    # cross-match consistency: an outlier in one match is weak evidence
    result["eligible"] = result["n_matches"] >= args.min_matches

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.out, index_label="player_id")

    flagged = result[result["eligible"] & result["score"].notna()]
    print(f"scored {len(result)} players -> {args.out}")
    print(f"eligible for review (>= {args.min_matches} matches): {len(flagged)}")
    if not flagged.empty:
        print("\ntop of review queue:")
        cols = [c for c in ("score", "n_matches", "top_features") if c in flagged.columns]
        print(flagged[cols].head(15).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

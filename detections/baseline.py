"""Fit per-cohort metric baselines from a clean population.

Usage:
    python baseline.py --samples ../data/clean_samples.csv --out ../data/baseline.json

The baseline stores robust statistics (median, MAD, and percentiles) per (cohort, metric).
Robust statistics are deliberate: skill distributions have heavy tails and a single genuine
outlier player must not move the baseline.

A metric is only recorded when at least --min-players players in the cohort produced a
finite value. Otherwise it is marked unusable and downstream scoring will report NaN
rather than silently defaulting.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from aim_metrics import METRIC_NAMES, load_samples, population_metrics

MIN_MAD = 1e-9


def robust_stats(values: np.ndarray) -> dict:
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    return {
        "n": int(values.size),
        "median": med,
        "mad": mad,
        # 1.4826 scales MAD to be comparable to a standard deviation for normal data
        "sigma": float(1.4826 * mad) if mad > MIN_MAD else float("nan"),
        "p01": float(np.percentile(values, 1)),
        "p05": float(np.percentile(values, 5)),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
        "mean": float(values.mean()),
        "std": float(values.std(ddof=1)) if values.size > 1 else float("nan"),
    }


def fit(metrics, min_players: int) -> dict:
    baselines: dict[str, dict] = {}
    for cohort, sub in metrics.groupby("cohort"):
        entry: dict[str, dict] = {"players": int(len(sub))}
        for name in METRIC_NAMES:
            if name not in sub.columns:
                continue
            vals = sub[name].to_numpy(dtype=float)
            vals = vals[np.isfinite(vals)]
            if vals.size < min_players:
                entry[name] = {"usable": False, "n": int(vals.size)}
                continue
            entry[name] = {"usable": True, **robust_stats(vals)}
        baselines[str(cohort)] = entry
    return baselines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", required=True, help="clean-population samples CSV")
    ap.add_argument("--out", required=True, help="output baseline JSON")
    ap.add_argument("--min-players", type=int, default=10,
                    help="minimum finite values per (cohort, metric) to record a baseline")
    args = ap.parse_args()

    df = load_samples(args.samples)
    metrics = population_metrics(df)
    baselines = fit(metrics, min_players=args.min_players)

    payload = {
        "source": str(Path(args.samples)),
        "players": int(len(metrics)),
        "cohorts": sorted(baselines.keys()),
        "min_players": args.min_players,
        "baselines": baselines,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, allow_nan=True), encoding="utf-8")

    for cohort, entry in baselines.items():
        usable = [k for k, v in entry.items() if isinstance(v, dict) and v.get("usable")]
        print(f"{cohort:<24} players={entry['players']:<5} usable_metrics={len(usable)}/{len(METRIC_NAMES)}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

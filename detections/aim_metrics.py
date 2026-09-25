"""Aim kinematics and behavioral metrics for FPS anti-cheat telemetry.

Pure functions over a per-input-event sample stream. No game-specific dependencies.

Schema (one CSV row per input event, sorted by player_id, t_ms):

    player_id,t_ms,match_id,yaw,pitch,mouse_dx,mouse_dy,event,weapon_id,cohort
    p_001,0,m_8801,101.231,4.913,0.000,0.000,move,weapon_r301,mouse_gold

Optional columns: ``hit_bone`` (``head``/``neck``/``body``) on ``hit`` events.

Every metric answers one question and returns a scalar (or NaN when the stream is too
sparse to answer it). Sparse-in -> NaN-out is intentional: callers must not silently
substitute a default.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

# --- tuning constants -------------------------------------------------------
MIN_ACQUIRE_DEG = 15.0     # an "acquisition" must move at least this far
ACQUIRE_WINDOW_MS = 900.0  # ... within this window
STOP_EPS_DEG_S = 25.0      # angular velocity below this counts as "stopped"
STOP_HOLD_MS = 120.0       # ... for at least this long
SNAP_PEAK_RATIO = 6.0      # peak/median velocity ratio that indicates a snap
SNAP_MAX_MS = 220.0        # a snap also completes quickly
HUMAN_REACTION_FLOOR_MS = 90.0   # below this, a human did not do it
HUMAN_FIRE_FLOOR_MS = 110.0
RECOIL_WIN_MS = 80.0       # per-shot compensation window

METRIC_NAMES = (
    "acq_per_min",
    "ttt_med_ms",
    "fitts_slope",
    "snap_ratio",
    "reaction_med_ms",
    "fire_latency_med_ms",
    "recoil_regularity",
    "recoil_residual",
    "jerk_p95",
    "track_smoothness",
    "accuracy",
    "hs_rate",
)


# --- loading ---------------------------------------------------------------

def load_samples(path: str) -> pd.DataFrame:
    """Load a sample CSV and normalise dtypes. Raises on an unusable file."""
    df = pd.read_csv(path)
    required = {"player_id", "t_ms", "yaw", "pitch", "event"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"sample file missing columns: {sorted(missing)}")
    df["t_ms"] = pd.to_numeric(df["t_ms"])
    for col in ("yaw", "pitch", "mouse_dx", "mouse_dy"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col])
        else:
            df[col] = 0.0
    df["cohort"] = df["cohort"].astype(str) if "cohort" in df.columns else "default"
    df["weapon_id"] = df["weapon_id"].astype(str) if "weapon_id" in df.columns else "default"
    df = df.sort_values(["player_id", "t_ms"], kind="mergesort").reset_index(drop=True)
    return df


def _player_streams(df: pd.DataFrame) -> Iterable[tuple[str, pd.DataFrame]]:
    for pid, sub in df.groupby("player_id", sort=False):
        yield str(pid), sub


def _safe(x: float) -> float:
    return float(x) if x is not None and math.isfinite(float(x)) else float("nan")


# --- core kinematics -------------------------------------------------------

def angular_velocity(sub: pd.DataFrame) -> pd.Series:
    """Instantaneous angular speed in deg/s, aligned to ``sub``'s index."""
    t = sub["t_ms"].to_numpy(dtype=float) / 1000.0
    dyaw = np.abs(np.diff(sub["yaw"].to_numpy(dtype=float), prepend=sub["yaw"].iloc[0]))
    dpitch = np.abs(np.diff(sub["pitch"].to_numpy(dtype=float), prepend=sub["pitch"].iloc[0]))
    dt = np.diff(t, prepend=t[0])
    dt = np.where(dt <= 0, np.nan, dt)
    speed = np.sqrt(dyaw**2 + dpitch**2) / dt
    return pd.Series(speed, index=sub.index, dtype=float)


@dataclass
class Acquisition:
    distance_deg: float
    duration_ms: float
    peak_vel_deg_s: float
    median_vel_deg_s: float
    end_ms: float


def find_acquisitions(sub: pd.DataFrame) -> list[Acquisition]:
    """Segment the stream into aim acquisitions.

    An acquisition is a burst of motion travelling >= MIN_ACQUIRE_DEG within
    ACQUIRE_WINDOW_MS and terminating in a held stop (velocity below STOP_EPS_DEG_S for
    STOP_HOLD_MS).
    """
    speed = angular_velocity(sub).to_numpy()
    t = sub["t_ms"].to_numpy(dtype=float)
    yaw = sub["yaw"].to_numpy(dtype=float)
    pitch = sub["pitch"].to_numpy(dtype=float)

    acqs: list[Acquisition] = []
    i, n = 0, len(sub)
    while i < n:
        # skip idle
        if not (speed[i] > STOP_EPS_DEG_S):
            i += 1
            continue
        start = i
        # extend while moving and inside the window
        while i + 1 < n and (t[i + 1] - t[start]) <= ACQUIRE_WINDOW_MS:
            if speed[i + 1] > STOP_EPS_DEG_S or (t[i + 1] - t[i]) <= STOP_HOLD_MS:
                i += 1
            else:
                break
        end = i
        dist = math.hypot(yaw[end] - yaw[start], pitch[end] - pitch[start])
        dur = float(t[end] - t[start])
        if dist >= MIN_ACQUIRE_DEG and dur > 0:
            seg_speed = speed[start : end + 1]
            seg_speed = seg_speed[np.isfinite(seg_speed)]
            if seg_speed.size:
                acqs.append(
                    Acquisition(
                        distance_deg=float(dist),
                        duration_ms=dur,
                        peak_vel_deg_s=float(seg_speed.max()),
                        median_vel_deg_s=float(np.median(seg_speed)),
                        end_ms=float(t[end]),
                    )
                )
        i = end + 1
    return acqs


def fitts_fit(acqs: list[Acquisition], width_deg: float = 1.0) -> tuple[float, float]:
    """Fit movement time (ms) = a + b * log2(1 + distance/width).

    Returns (slope_b, r_squared). A human slope is clearly positive; a snap-based aimbot
    shows a near-flat slope because acquisition time barely depends on distance.
    """
    if len(acqs) < 5:
        return float("nan"), float("nan")
    x = np.log2(1.0 + np.array([a.distance_deg for a in acqs]) / width_deg)
    y = np.array([a.duration_ms for a in acqs], dtype=float)
    if np.allclose(x, x[0]):
        return float("nan"), float("nan")
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return _safe(slope), _safe(r2)


def snap_ratio(acqs: list[Acquisition]) -> float:
    """Fraction of acquisitions that are spike-then-stop (peak >> median, and fast)."""
    if not acqs:
        return float("nan")
    hits = 0
    for a in acqs:
        if a.median_vel_deg_s <= 0:
            continue
        if (a.peak_vel_deg_s / a.median_vel_deg_s) >= SNAP_PEAK_RATIO and a.duration_ms <= SNAP_MAX_MS:
            hits += 1
    return _safe(hits / len(acqs))


def reaction_times(sub: pd.DataFrame) -> np.ndarray:
    """target_enter -> first aim movement (ms). Empty when no target_enter events."""
    enters = sub.index[sub["event"] == "target_enter"].tolist()
    out = []
    for idx in enters:
        t0 = float(sub.at[idx, "t_ms"])
        after = sub.loc[idx + 1 :]
        if after.empty:
            continue
        moved = after[(after["yaw"].diff().abs() + after["pitch"].diff().abs()) > 0.5]
        if moved.empty:
            continue
        out.append(float(moved["t_ms"].iloc[0]) - t0)
    return np.asarray(out, dtype=float)


def fire_latencies(sub: pd.DataFrame) -> np.ndarray:
    """target_enter -> fire (ms)."""
    enters = sub.index[sub["event"] == "target_enter"].tolist()
    out = []
    for idx in enters:
        t0 = float(sub.at[idx, "t_ms"])
        after = sub.loc[idx + 1 :]
        fires = after[after["event"] == "fire"]
        if fires.empty:
            continue
        out.append(float(fires["t_ms"].iloc[0]) - t0)
    return np.asarray(out, dtype=float)


def recoil_profile(sub: pd.DataFrame) -> tuple[float, float]:
    """(regularity, residual) of the per-shot input compensation.

    ``regularity`` is the mean pairwise cosine similarity between per-shot compensation
    vectors. A scripted anti-recoil produces near-identical vectors (regularity -> 1.0);
    a human's compensation varies (typically well below 0.9).

    ``residual`` is the mean L2 norm left after subtracting the learned (mean) pattern,
    normalised by the pattern magnitude. Low residual + high regularity = scripted.
    """
    fires = sub[sub["event"] == "fire"]
    if len(fires) < 6:
        return float("nan"), float("nan")
    t = sub["t_ms"].to_numpy(dtype=float)
    dx = sub["mouse_dx"].to_numpy(dtype=float)
    dy = sub["mouse_dy"].to_numpy(dtype=float)

    vecs = []
    for t_fire in fires["t_ms"].to_numpy(dtype=float):
        m = (t >= t_fire) & (t <= t_fire + RECOIL_WIN_MS)
        if not m.any():
            continue
        # subtract the pre-shot baseline so steady aim does not count as compensation
        pre = (t >= t_fire - RECOIL_WIN_MS) & (t < t_fire)
        bx = float(np.mean(dx[pre])) if pre.any() else 0.0
        by = float(np.mean(dy[pre])) if pre.any() else 0.0
        vecs.append([float(np.sum(dx[m]) - bx), float(np.sum(dy[m]) - by)])
    V = np.asarray(vecs, dtype=float)
    if V.shape[0] < 6:
        return float("nan"), float("nan")

    norms = np.linalg.norm(V, axis=1, keepdims=True)
    valid = norms[:, 0] > 1e-6
    if valid.sum() < 6:
        return float("nan"), float("nan")
    U = V[valid] / norms[valid]

    # mean pairwise cosine similarity (upper triangle, without diagonal)
    sim = U @ U.T
    n = sim.shape[0]
    iu = np.triu_indices(n, k=1)
    regularity = float(sim[iu].mean())

    mean_vec = V[valid].mean(axis=0)
    residual = float(np.linalg.norm(V[valid] - mean_vec, axis=1).mean())
    scale = float(np.linalg.norm(mean_vec))
    residual_norm = residual / scale if scale > 1e-6 else float("nan")
    return _safe(regularity), _safe(residual_norm)


def jerk_p95(sub: pd.DataFrame) -> float:
    """95th percentile of |d^3 angle / dt^3| in deg/s^3. Smooths under jitter."""
    if len(sub) < 8:
        return float("nan")
    t = sub["t_ms"].to_numpy(dtype=float) / 1000.0
    ang = np.unwrap(np.radians(np.hypot(sub["yaw"].to_numpy(dtype=float),
                                        sub["pitch"].to_numpy(dtype=float))))
    dt = np.diff(t)
    good = dt > 1e-4
    if good.sum() < 4:
        return float("nan")
    v = np.diff(ang)[good] / dt[good]
    t2 = t[1:][good]
    dt2 = np.diff(t2)
    good2 = dt2 > 1e-4
    if good2.sum() < 3:
        return float("nan")
    a = np.diff(v)[good2] / dt2[good2]
    t3 = t2[1:][good2]
    dt3 = np.diff(t3)
    good3 = dt3 > 1e-4
    if good3.sum() < 2:
        return float("nan")
    j = np.diff(a)[good3] / dt3[good3]
    return _safe(np.percentile(np.abs(np.degrees(j)), 95))


def track_smoothness(sub: pd.DataFrame) -> float:
    """Lag-1 autocorrelation of angular velocity. High = unnaturally smooth tracking."""
    speed = angular_velocity(sub).to_numpy()
    speed = speed[np.isfinite(speed)]
    if speed.size < 20 or np.std(speed) < 1e-9:
        return float("nan")
    return _safe(np.corrcoef(speed[:-1], speed[1:])[0, 1])


def accuracy(sub: pd.DataFrame) -> float:
    fires = int((sub["event"] == "fire").sum())
    hits = int((sub["event"] == "hit").sum())
    return _safe(hits / fires) if fires else float("nan")


def hs_rate(sub: pd.DataFrame) -> float:
    hits = sub[sub["event"] == "hit"]
    if hits.empty or "hit_bone" not in hits.columns:
        return float("nan")
    head = hits["hit_bone"].astype(str).str.lower().isin(["head", "neck"]).sum()
    return _safe(head / len(hits))


# --- aggregation -----------------------------------------------------------

def player_metrics(sub: pd.DataFrame) -> dict[str, float]:
    """Compute every metric for one player's sample stream."""
    acqs = find_acquisitions(sub)
    slope, _r2 = fitts_fit(acqs)
    react = reaction_times(sub)
    lat = fire_latencies(sub)
    reg, resid = recoil_profile(sub)

    span_min = max((float(sub["t_ms"].max()) - float(sub["t_ms"].min())) / 60000.0, 1e-6)

    out = {
        "acq_per_min": _safe(len(acqs) / span_min),
        "ttt_med_ms": _safe(np.median([a.duration_ms for a in acqs])) if acqs else float("nan"),
        "fitts_slope": slope,
        "snap_ratio": snap_ratio(acqs),
        "reaction_med_ms": _safe(np.median(react)) if react.size else float("nan"),
        "fire_latency_med_ms": _safe(np.median(lat)) if lat.size else float("nan"),
        "recoil_regularity": reg,
        "recoil_residual": resid,
        "jerk_p95": jerk_p95(sub),
        "track_smoothness": track_smoothness(sub),
        "accuracy": accuracy(sub),
        "hs_rate": hs_rate(sub),
        "n_samples": float(len(sub)),
        "n_matches": float(sub["match_id"].nunique()) if "match_id" in sub.columns else 1.0,
    }
    return out


def population_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute metrics for every player. Returns a DataFrame indexed by player_id."""
    rows = {}
    for pid, sub in _player_streams(df):
        m = player_metrics(sub)
        m["cohort"] = str(sub["cohort"].iloc[0]) if "cohort" in sub.columns else "default"
        rows[pid] = m
    return pd.DataFrame.from_dict(rows, orient="index")

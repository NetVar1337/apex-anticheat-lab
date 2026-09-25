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
from scipy.signal import savgol_filter

# --- tuning constants -------------------------------------------------------
MIN_ACQUIRE_DEG = 15.0     # an "acquisition" must move at least this far
ACQUIRE_WINDOW_MS = 900.0  # ... within this window
STOP_EPS_DEG_S = 25.0      # angular velocity below this counts as "stopped"
STOP_HOLD_MS = 120.0       # ... for at least this long
SNAP_EFFECTIVE_DEG_S = 500.0  # sustained distance/duration that a human does not hold
SNAP_MAX_MS = 220.0           # ... or a large acquisition completed implausibly fast
HUMAN_REACTION_FLOOR_MS = 90.0   # below this, a human did not do it
HUMAN_FIRE_FLOOR_MS = 110.0
RECOIL_WIN_MS = 80.0       # per-shot compensation window
RECOIL_SETTLE_DEG_S = 60.0 # ignore shots taken mid-flick: aim and recoil cannot be separated

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
    effective_vel_deg_s: float
    end_ms: float


def find_acquisitions(sub: pd.DataFrame) -> list[Acquisition]:
    """Segment the stream into aim acquisitions.

    Algorithm: find runs where angular speed exceeds STOP_EPS_DEG_S, merge runs separated by
    less than STOP_HOLD_MS (a pause that short is one continuous move), then keep merges whose
    angular distance is >= MIN_ACQUIRE_DEG and whose duration fits ACQUIRE_WINDOW_MS.

    An earlier revision extended segments by sample-gap rather than by motion, which inflated
    durations by ~10x and made every metric downstream unreliable. Durations here are
    measured start-of-motion to end-of-motion.
    """
    speed = angular_velocity(sub).to_numpy()
    t = sub["t_ms"].to_numpy(dtype=float)
    yaw = sub["yaw"].to_numpy(dtype=float)
    pitch = sub["pitch"].to_numpy(dtype=float)

    moving = np.nan_to_num(speed, nan=0.0) > STOP_EPS_DEG_S
    n = len(sub)

    # runs of consecutive moving samples
    runs: list[list[int]] = []
    i = 0
    while i < n:
        if not moving[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and moving[j + 1]:
            j += 1
        runs.append([i, j])
        i = j + 1

    # merge runs separated by a pause shorter than STOP_HOLD_MS
    merged: list[list[int]] = []
    for r in runs:
        if merged and (t[r[0]] - t[merged[-1][1]]) < STOP_HOLD_MS:
            merged[-1][1] = r[1]
        else:
            merged.append(list(r))

    acqs: list[Acquisition] = []
    for start, end in merged:
        dur = float(t[end] - t[start])
        if dur <= 0 or dur > ACQUIRE_WINDOW_MS:
            continue
        dist = float(math.hypot(yaw[end] - yaw[start], pitch[end] - pitch[start]))
        if dist < MIN_ACQUIRE_DEG:
            continue
        seg = speed[start : end + 1]
        seg = seg[np.isfinite(seg)]
        if seg.size == 0:
            continue
        acqs.append(
            Acquisition(
                distance_deg=dist,
                duration_ms=dur,
                peak_vel_deg_s=float(seg.max()),
                median_vel_deg_s=float(np.median(seg)),
                effective_vel_deg_s=dist / (dur / 1000.0),
                end_ms=float(t[end]),
            )
        )
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
    """Fraction of acquisitions that are snaps rather than guided moves.

    A snap is judged on **effective velocity** — distance covered divided by time taken,
    including the deceleration phase — not on peak instantaneous velocity. A human flick
    peaks fast but averages far lower because it overshoots and corrects; an aimbot moves at
    a single high rate and stops dead.

    The threshold is cohort-dependent: calibrate against a labelled clean population rather
    than treating 500 deg/s as a constant of nature. ``fitts_slope`` is the principled,
    threshold-free version of the same question, and separates better.
    """
    if not acqs:
        return float("nan")
    hits = sum(1 for a in acqs if a.effective_vel_deg_s >= SNAP_EFFECTIVE_DEG_S)
    return _safe(hits / len(acqs))


def reaction_times(sub: pd.DataFrame) -> np.ndarray:
    """target_enter -> first aim movement (ms). Empty when no target_enter events.

    Movement is measured as displacement from the pose at the moment of target entry,
    not as frame-to-frame delta: the first sample after entry has no predecessor to diff
    against, and a frame-to-frame diff would miss a slow creep entirely.
    """
    enters = sub.index[sub["event"] == "target_enter"].tolist()
    out = []
    for idx in enters:
        t0 = float(sub.at[idx, "t_ms"])
        y0 = float(sub.at[idx, "yaw"])
        p0 = float(sub.at[idx, "pitch"])
        after = sub.loc[idx + 1 :]
        if after.empty:
            continue
        disp = (after["yaw"] - y0).abs() + (after["pitch"] - p0).abs()
        moved = after[disp > 0.5]
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

    ``regularity`` measures how tightly the per-shot compensation vectors cluster in both
    direction and magnitude:

        regularity = 1 - mean_pairwise_L2_distance / (2 * mean_norm)

    A scripted anti-recoil sends the same vector every shot (distance 0, regularity 1.0).
    Human compensation varies in magnitude *and* direction, so it sits well below 1.0.

    An earlier revision used mean pairwise **cosine** similarity, which is scale-invariant and
    therefore scored a human compensating straight down every shot as perfectly regular. The
    magnitude term is what makes the metric able to tell a script from a consistent human.

    ``residual`` is the mean L2 norm left after subtracting the learned (mean) pattern,
    normalised by the pattern magnitude. Low residual + high regularity = scripted.
    """
    fires = sub[sub["event"] == "fire"]
    if len(fires) < 6:
        return float("nan"), float("nan")
    t = sub["t_ms"].to_numpy(dtype=float)
    dx = sub["mouse_dx"].to_numpy(dtype=float)
    dy = sub["mouse_dy"].to_numpy(dtype=float)
    speed = angular_velocity(sub).to_numpy()

    vecs = []
    for t_fire in fires["t_ms"].to_numpy(dtype=float):
        m = (t >= t_fire) & (t <= t_fire + RECOIL_WIN_MS)
        if not m.any():
            continue
        pre = (t >= t_fire - RECOIL_WIN_MS) & (t < t_fire)
        # Skip shots taken mid-flick: in that window the input is aiming, not recoil
        # compensation, and the two cannot be separated from this signal alone.
        if pre.any():
            pre_speed = speed[pre]
            pre_speed = pre_speed[np.isfinite(pre_speed)]
            if pre_speed.size and float(np.median(pre_speed)) > RECOIL_SETTLE_DEG_S:
                continue
        bx = float(np.mean(dx[pre])) if pre.any() else 0.0
        by = float(np.mean(dy[pre])) if pre.any() else 0.0
        vecs.append([float(np.sum(dx[m]) - bx), float(np.sum(dy[m]) - by)])
    V = np.asarray(vecs, dtype=float)
    if V.shape[0] < 6:
        return float("nan"), float("nan")

    norms = np.linalg.norm(V, axis=1)
    valid = norms > 1e-6
    if int(valid.sum()) < 6:
        return float("nan"), float("nan")
    V = V[valid]
    norms = norms[valid]

    mean_norm = float(norms.mean())
    # mean pairwise L2 distance (upper triangle, without diagonal)
    diff = V[:, None, :] - V[None, :, :]
    dist = np.linalg.norm(diff, axis=2)
    n = dist.shape[0]
    iu = np.triu_indices(n, k=1)
    mean_dist = float(dist[iu].mean())
    regularity = 1.0 - mean_dist / (2.0 * mean_norm)
    regularity = float(np.clip(regularity, 0.0, 1.0))

    mean_vec = V.mean(axis=0)
    residual = float(np.linalg.norm(V - mean_vec, axis=1).mean())
    scale = float(np.linalg.norm(mean_vec))
    residual_norm = residual / scale if scale > 1e-6 else float("nan")
    return _safe(regularity), _safe(residual_norm)


def jerk_p95(sub: pd.DataFrame) -> float:
    """95th percentile of *dimensionless normalised jerk* over acquisitions.

    Raw jerk (deg/s^3) is not usable as a detector: it scales with the third power of the
    sampling rate and is dominated by telemetry noise, so it mostly measures your exporter
    rather than the player. The motor-control literature uses the **Flash & Hogan normalised
    jerk**, which is invariant to movement duration and amplitude:

        J = (T^5 / L^2) * integral of |d^3x/dt^3|^2 dt

    where T is movement duration and L is path length. Low J = smooth, speed-independent of
    how big or fast the move was.

    Both tails are interesting: a bot's interpolated aim is far smoother than a human
    (very low J) and mechanical high-frequency correction is far rougher (very high J).
    """
    acqs = find_acquisitions(sub)
    if not acqs:
        return float("nan")

    t = sub["t_ms"].to_numpy(dtype=float) / 1000.0
    yaw = np.radians(sub["yaw"].to_numpy(dtype=float))
    pitch = np.radians(sub["pitch"].to_numpy(dtype=float))
    tt = sub["t_ms"].to_numpy(dtype=float)

    vals = []
    for a in acqs:
        # restrict to the sample span that produced this acquisition
        idx = np.flatnonzero(tt <= a.end_ms)
        if idx.size < 6:
            continue
        start = int(np.searchsorted(tt, a.end_ms - a.duration_ms, side="left"))
        seg = slice(max(start, 0), int(idx[-1]) + 1)
        ts = t[seg]
        if ts.size < 6:
            continue
        T = float(ts[-1] - ts[0])
        if T <= 0:
            continue

        # Smooth before differentiating. Sampled telemetry is piecewise-constant and the
        # third derivative of a staircase is a train of impulses, not a signal. Savitzky-Golay
        # (polyorder 3) is the standard treatment for sampled kinematic data.
        wy = yaw[seg]
        wp = pitch[seg]
        n = wy.size
        if n < 7:
            continue
        win = 7 if n >= 7 else n
        if win % 2 == 0:
            win -= 1
        wy = savgol_filter(wy, win, 3)
        wp = savgol_filter(wp, win, 3)

        dt = np.diff(ts)
        v_ok = dt > 1e-4
        if int(v_ok.sum()) < 3:
            continue
        t_v = (ts[:-1] + dt / 2.0)[v_ok]
        vy = np.diff(wy)[v_ok] / dt[v_ok]
        vp = np.diff(wp)[v_ok] / dt[v_ok]

        dt2 = np.diff(t_v)
        a_ok = dt2 > 1e-4
        if int(a_ok.sum()) < 2:
            continue
        t_a = (t_v[:-1] + dt2 / 2.0)[a_ok]
        ay = np.diff(vy)[a_ok] / dt2[a_ok]
        ap = np.diff(vp)[a_ok] / dt2[a_ok]

        dt3 = np.diff(t_a)
        j_ok = dt3 > 1e-4
        if int(j_ok.sum()) < 1:
            continue
        jy = np.diff(ay)[j_ok] / dt3[j_ok]
        jp = np.diff(ap)[j_ok] / dt3[j_ok]
        jerk2 = jy**2 + jp**2

        # path length in radians
        L = float(np.sum(np.hypot(np.diff(yaw[seg]), np.diff(pitch[seg]))))
        if L <= 1e-9:
            continue
        integral = float(np.sum(jerk2 * dt3[j_ok]))
        vals.append((T**5 / L**2) * integral)

    return _safe(np.percentile(vals, 95)) if vals else float("nan")


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

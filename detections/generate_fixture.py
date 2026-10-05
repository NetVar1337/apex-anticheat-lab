"""Synthetic per-input-event telemetry for the aim scorer.

This is not game data and not a cheat. Each class is a timing shape the
existing scorer can see. A high-skill human is intentionally close to the
clean cohort.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 7
DISTANCES = (18.0, 24.0, 32.0, 40.0, 52.0, 64.0, 28.0, 46.0)
COLUMNS = (
    "player_id",
    "t_ms",
    "match_id",
    "yaw",
    "pitch",
    "mouse_dx",
    "mouse_dy",
    "event",
    "weapon_id",
    "cohort",
    "hit_bone",
)


def _row(pid, t, match, yaw, pitch, event, cohort, dx=0.0, dy=0.0, bone=""):
    return {
        "player_id": pid,
        "t_ms": int(round(t)),
        "match_id": match,
        "yaw": round(float(yaw), 4),
        "pitch": round(float(pitch), 4),
        "mouse_dx": round(float(dx), 4),
        "mouse_dy": round(float(dy), 4),
        "event": event,
        "weapon_id": "w_ar",
        "cohort": cohort,
        "hit_bone": bone,
    }


def _hold(rows, pid, t, match, yaw, cohort, ms, step=20.0):
    n = max(int(ms / step), 1)
    for i in range(n + 1):
        rows.append(_row(pid, t + i * step, match, yaw, 0.0, "move", cohort))
    return t + n * step


def _flick(rows, pid, t, match, yaw0, distance, duration_ms, cohort):
    """The first sample stays put so the moving-run distance is almost the full flick."""
    n = max(int(duration_ms / 8.0), 3)
    rows.append(_row(pid, t, match, yaw0, 0.0, "move", cohort))
    for i in range(1, n + 1):
        yaw = yaw0 + distance * (i / n)
        rows.append(_row(pid, t + i * (duration_ms / n), match, yaw, 0.0, "move", cohort))
    return t + duration_ms, yaw0 + distance


def _recoil(rows, pid, t, match, yaw, cohort, dy, dx=0.0):
    """Compensation inside the 80 ms post-fire window. Aim stays still."""
    for frac in (0.15, 0.35, 0.55, 0.75):
        rows.append(_row(pid, t + frac * 64.0, match, yaw, 0.0, "move", cohort, dx=dx * frac, dy=dy * frac))
    return t + 64.0


def _hit(rows, rng, pid, t, match, yaw, cohort, spec):
    if rng.random() >= spec["hit_p"]:
        return
    bone = "head" if rng.random() < spec["hs_p"] else "body"
    rows.append(_row(pid, t + 8, match, yaw, 0.0, "hit", cohort, bone=bone))


def _human_duration(distance, rng, scale=42.0, base=170.0):
    dur = base + scale * math.log2(1.0 + distance) + float(rng.uniform(-12.0, 12.0))
    return int(np.clip(dur, 180, 700))


def _engagement(rows, rng, pid, t, match, cohort, spec):
    yaw = float(rng.uniform(10.0, 80.0))
    distance = float(rng.choice(DISTANCES))
    t = _hold(rows, pid, t, match, yaw, cohort, 160)
    rows.append(_row(pid, t, match, yaw, 0.0, "target_enter", cohort))
    t_enter = t
    timing = spec["timing"]

    if timing == "early_fire":
        latency = int(spec["fire_latency_ms"])
        rows.append(_row(pid, t_enter + latency, match, yaw, 0.0, "fire", cohort))
        _hit(rows, rng, pid, t_enter + latency, match, yaw, cohort, spec)

    t = _hold(rows, pid, t + 8, match, yaw, cohort, spec["reaction_ms"])
    duration = spec["duration_ms"](distance, rng)
    t, yaw = _flick(rows, pid, t, match, yaw, distance, duration, cohort)
    t = _hold(rows, pid, t + 8, match, yaw, cohort, 140)

    if timing == "settled_fire":
        rows.append(_row(pid, t, match, yaw, 0.0, "fire", cohort))
        _hit(rows, rng, pid, t, match, yaw, cohort, spec)
        if spec["recoil"] == "script":
            _recoil(rows, pid, t, match, yaw, cohort, dy=-12.0, dx=0.0)
        elif spec["recoil"] == "human":
            _recoil(
                rows, pid, t, match, yaw, cohort,
                dy=float(rng.normal(-9.0, 2.4)),
                dx=float(rng.normal(0.0, 1.1)),
            )
        t += 80.0
    elif timing == "snap":
        rows.append(_row(pid, t, match, yaw, 0.0, "fire", cohort))
        _hit(rows, rng, pid, t, match, yaw, cohort, spec)
        t += 16.0

    return t + 220.0


def _specs(rng):
    return {
        "clean": {
            "reaction_ms": int(rng.integers(190, 280)),
            "duration_ms": _human_duration,
            "fire_latency_ms": 0,
            "hit_p": 0.32,
            "hs_p": 0.22,
            "recoil": "human",
            "timing": "settled_fire",
        },
        "controller": {
            "reaction_ms": int(rng.integers(230, 340)),
            "duration_ms": lambda d, r: _human_duration(d, r, scale=55.0, base=220.0),
            "fire_latency_ms": 0,
            "hit_p": 0.28,
            "hs_p": 0.18,
            "recoil": "none",
            "timing": "settled_fire",
        },
        "snap": {
            "reaction_ms": 24,
            "duration_ms": lambda d, r: 36,
            "fire_latency_ms": 0,
            "hit_p": 0.84,
            "hs_p": 0.78,
            "recoil": "none",
            "timing": "snap",
        },
        "trigger": {
            "reaction_ms": int(rng.integers(200, 260)),
            "duration_ms": _human_duration,
            "fire_latency_ms": 42,
            "hit_p": 0.55,
            "hs_p": 0.30,
            "recoil": "none",
            "timing": "early_fire",
        },
        "recoil_script": {
            "reaction_ms": int(rng.integers(200, 270)),
            "duration_ms": _human_duration,
            "fire_latency_ms": 0,
            "hit_p": 0.40,
            "hs_p": 0.26,
            "recoil": "script",
            "timing": "settled_fire",
        },
        "high_skill": {
            "reaction_ms": int(rng.integers(150, 185)),
            "duration_ms": lambda d, r: _human_duration(d, r, scale=36.0, base=160.0),
            "fire_latency_ms": 0,
            "hit_p": 0.46,
            "hs_p": 0.34,
            "recoil": "human",
            "timing": "settled_fire",
        },
    }


def _player(rng, pid, cohort, kind, n_engagements=16):
    spec = _specs(rng)[kind]
    rows = []
    t = 1_000.0
    for i in range(n_engagements):
        match = "m1" if i < n_engagements // 2 else "m2"
        t = _engagement(rows, rng, pid, t, match, cohort, spec)
    return rows


def build(seed: int = SEED):
    rng = np.random.default_rng(seed)
    clean_rows = []
    score_rows = []
    labels = []

    for i in range(16):
        pid = f"base_mouse_{i:02d}"
        clean_rows.extend(_player(rng, pid, "mouse_gold", "clean"))
        labels.append((pid, "baseline_clean", "mouse_gold"))
    for i in range(12):
        pid = f"base_pad_{i:02d}"
        clean_rows.extend(_player(rng, pid, "controller_gold", "controller"))
        labels.append((pid, "baseline_controller", "controller_gold"))

    for i in range(6):
        pid = f"holdout_mouse_{i:02d}"
        score_rows.extend(_player(rng, pid, "mouse_gold", "clean"))
        labels.append((pid, "holdout_clean", "mouse_gold"))
    for i in range(4):
        pid = f"snap_{i:02d}"
        score_rows.extend(_player(rng, pid, "mouse_gold", "snap"))
        labels.append((pid, "snap_aim", "mouse_gold"))
    for i in range(3):
        pid = f"trigger_{i:02d}"
        score_rows.extend(_player(rng, pid, "mouse_gold", "trigger"))
        labels.append((pid, "triggerbot", "mouse_gold"))
    for i in range(3):
        pid = f"script_{i:02d}"
        score_rows.extend(_player(rng, pid, "mouse_gold", "recoil_script"))
        labels.append((pid, "recoil_script", "mouse_gold"))
    for i in range(2):
        pid = f"skilled_{i:02d}"
        score_rows.extend(_player(rng, pid, "mouse_gold", "high_skill"))
        labels.append((pid, "high_skill_human", "mouse_gold"))

    clean = pd.DataFrame(clean_rows, columns=COLUMNS)
    scored = pd.DataFrame(score_rows, columns=COLUMNS)
    label_df = pd.DataFrame(labels, columns=["player_id", "label", "cohort"])
    return clean, scored, label_df


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    out = root / "data"
    out.mkdir(parents=True, exist_ok=True)
    clean, scored, labels = build()
    clean.to_csv(out / "clean_samples.csv", index=False)
    scored.to_csv(out / "match_samples.csv", index=False)
    labels.to_csv(out / "labels.csv", index=False)
    print(f"clean players={clean['player_id'].nunique()} rows={len(clean)}")
    print(f"score players={scored['player_id'].nunique()} rows={len(scored)}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Behavioral detections

Python, numpy + scipy + pandas. No game-specific dependencies.

## Input format

One CSV row per **input event** (a mouse sample, a shot, or a frame tick), sorted by
`player_id, t_ms`:

```csv
player_id,t_ms,match_id,yaw,pitch,mouse_dx,mouse_dy,event,weapon_id,cohort
p_001,0,m_8801,101.231,4.913,0.000,0.000,move,weapon_r301,mouse_gold
p_001,8,m_8801,101.402,4.913,0.171,0.000,move,weapon_r301,mouse_gold
p_001,412,m_8801,102.900,4.700,-0.210,0.101,fire,weapon_r301,mouse_gold
```

| Column | Meaning |
|:---|:---|
| `player_id` | stable player identifier |
| `t_ms` | monotonic timestamp within the match, milliseconds |
| `match_id` | match identifier — used for cross-match consistency |
| `yaw`, `pitch` | view angles in degrees |
| `mouse_dx`, `mouse_dy` | raw input delta for this event (0 for non-input events) |
| `event` | `move`, `fire`, `hit`, `target_enter`, `target_exit` |
| `weapon_id` | weapon class (recoil metrics are per-weapon) |
| `cohort` | input-device + skill-tier label, used for baseline lookup |
| `hit_bone` | *(optional)* `head` / `neck` / `body` on `hit` events |

`event=target_enter` / `target_exit` mark the frames where an opponent becomes / stops being
under the crosshair. They make reaction-time and triggerbot metrics possible. If your pipeline
cannot emit them, those metrics return NaN — the code never invents a substitute.

## Files

| File | Purpose |
|:---|:---|
| `aim_metrics.py` | pure metric extraction from a player's sample stream |
| `baseline.py` | fit per-cohort metric distributions from a clean population |
| `detectors.py` | score a population against a baseline, emit ranked review queue |
| `requirements.txt` | `numpy`, `scipy`, `pandas` |

## Metrics extracted

| Metric | Question it answers | Cheat class | Suspicious tail |
|:---|:---|:---|:---|
| `acq_per_min` | how often does this player acquire a new target? | context | — |
| `ttt_med_ms` | time-to-target vs. angular distance travelled | aimbot | low |
| `fitts_slope` | is acquisition speed consistent with human motor control? | aimbot | low |
| `snap_ratio` | fraction of acquisitions that are spike-then-stop | aimbot | high |
| `reaction_med_ms` | target-visible → first-aim latency | aimbot | low |
| `fire_latency_med_ms` | crosshair-on-target → fire latency | triggerbot | low |
| `recoil_regularity` | similarity of per-shot compensation vectors | no-recoil script | high |
| `recoil_residual` | variance left after removing the learned pattern | no-recoil script | low |
| `jerk_p95` | smoothness of the aim path (d³angle/dt³) | aimbot smoothing | two-sided |
| `track_smoothness` | lag-1 autocorrelation of angular velocity | CV / external aim | high |
| `accuracy` | hits / fires | aimbot | high |
| `hs_rate` | headshot share of hits | aimbot | high |

See `aim_metrics.py` for the exact definitions — every one is documented at the function.

## Why cross-match consistency is enforced

A single match can legitimately produce extreme values: a lucky flick, a lobby of new players,
a 200 ms reaction to a predictable peek. `detectors.py` therefore marks players with fewer
than `--min-matches` distinct matches as **ineligible** for review. Repeated outliers across
independent matches are the evidence; a single outlier is noise.

## Known limits

- `fitts_slope` and `snap_ratio` need at least ~5 acquisitions per player to be meaningful;
  below that they return NaN and are excluded from the score.
- `recoil_*` is computed per player, not per weapon. If a player mixes weapons the pattern
  blurs; split the stream by `weapon_id` first for higher precision.
- `jerk_p95` is sample-rate dependent. Do not compare cohorts with different input poll rates.
- Metrics assume `t_ms` is monotonic per player. Non-monotonic telemetry is silently
  re-sorted, which can hide pipeline bugs — validate your exporter before trusting results.

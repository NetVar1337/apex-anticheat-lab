<div align="center">

# apex-anticheat-lab

**FPS anti-cheat research lab — cheat taxonomy, behavioral detections, match-integrity SQL, and host-level signals.**

`game security` · `anti-cheat` · `detection engineering` · `telemetry` · `Apex Legends`

</div>

---

## Why this exists

Anti-cheat work is not "find the file and delete it." Modern FPS cheats ship as subscriptions,
live in hardware (DMA cards, controller emulators), or never touch the target process at all
(computer-vision aim, external input injection). The durable counter is a **defense-in-depth
stack**:

1. **Host signals** — what is loaded, what is plugged in, what is signed, what is a known-vulnerable driver.
2. **Static signals** — YARA / packing / import traits on loaders and user-mode components.
3. **Behavioral signals** — server-side telemetry: aim kinematics, recoil regularity, reaction times.
4. **Economic / account signals** — boosting, deranking, smurfing, HWID ban evasion, account sharing.
5. **Intelligence** — what the cheat market is shipping this week ([cheat-intel](https://github.com/NetVar1337/cheat-intel)).

This repo is the *detection* half of that stack. It is written from the defender's side:
everything here is a way to **observe, score, and explain** anomalous behavior.

## Contents

| Path | What it is |
|:---|:---|
| [`docs/cheat-taxonomy.md`](docs/cheat-taxonomy.md) | FPS cheat taxonomy — how each class works and how each is detected |
| [`docs/methodology.md`](docs/methodology.md) | How to build a labelled dataset, pick thresholds, measure detector quality |
| [`detections/`](detections/) | Python: aim kinematics metrics, anomaly scoring, baseline fitting |
| [`sql/`](sql/) | Telemetry schema + analyst KPI / match-integrity queries |
| [`yara/`](yara/) | Heuristic YARA for cheat loaders and HWID spoofers |
| [`host/`](host/) | PowerShell host survey: driver inventory, vulnerable-driver blocklist, PCIe devices |

## Quick start

```bash
cd detections
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. fit a clean baseline
python baseline.py --samples ../data/clean_samples.csv --out ../data/baseline.json

# 2. score a population
python detectors.py --samples ../data/match_samples.csv \
                    --baseline ../data/baseline.json \
                    --out ../data/scores.csv
```

Input format is a flat CSV of **per-input-event samples** (see
[`detections/README.md`](detections/README.md)). Any replay/telemetry pipeline that can emit
`player_id, t_ms, yaw, pitch, ...` can feed it — the code does not depend on any particular game.

## Design notes

- **Every detector is a named, single-purpose feature.** Scores are explainable: an analyst
  should be able to tell a player *why* they were flagged, and a reviewer should be able to
  argue with a specific number.
- **Baselines are per-cohort.** Mouse and controller players do not produce the same
  kinematics; neither do Bronze and Predator. Scoring against a pooled baseline produces
  mostly false positives.
- **Nothing here auto-bans.** Output is a prioritised review queue with per-feature evidence.

## Related work

- [`Kevlar-Ultimate`](https://github.com/NetVar1337/Kevlar-Ultimate) — kernel-driver emulation for behavioral analysis of anti-cheat and driver-class threats.
- [`cheat-intel`](https://github.com/NetVar1337/cheat-intel) — cheat-community monitoring and trend reports.
- [`account-security`](https://github.com/NetVar1337/account-security) — account takeover and session abuse detection.

## Scope

Defensive research. All analysis is against data the operator owns or synthetic fixtures shipped
in this repo. No game files, no bypasses, no operational cheat code.

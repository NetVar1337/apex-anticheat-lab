# Investigation packet — synthetic

**Status:** exercise. Not a player, not a live game, not a ban recommendation.
**Source:** `detections/run_fixture.py` on seed 7. Numbers below are that run.
**Question:** a report says `script_00` is "aiming weird." What do you do, and what do you not do?

## What I pulled

Cohort is `mouse_gold`. Both matches are present, so the row is eligible. The composite score is **1.729**. That is above the holdout-clean maximum in this run (**0.527**) and below every snap and trigger row.

Top features for `script_00`:

- `recoil_regularity` +5.56
- `recoil_residual` +5.32
- jerk, headshot rate, and tracking are near the cohort

The same two recoil features lead `script_01` and `script_02`. Fitts slope, snap ratio, and fire latency are not the signal. This is not an aimbot report. It is a compensation-regularity report.

## What I ruled out

- Not a one-match spike. `n_matches` is 2, which is the floor, not a career sample. On a live queue I would want more matches before any enforcement. Here it is enough to see the feature repeat.
- Not a cohort error. The baseline is other mouse players, not a pooled mouse-plus-controller population.
- Not "high score, therefore cheat." `skilled_00` scores **2.151**, above `script_00`. Their top features are jerk, Fitts slope, and fire latency, not recoil regularity. Sorting the composite and cutting a line would queue the human first.

## Decision

| Player | Score | Call | Why |
|:---|---:|:---|:---|
| `snap_00` | 7.595 | Escalate | Fire latency, Fitts slope, and reaction all move together. Still not an auto-ban. Send the feature list. |
| `trigger_01` | 4.583 | Escalate as trigger, not aim | Fire latency +22.62. Fitts and reaction are not the story. |
| `script_00` | 1.729 | Escalate as recoil-script review | Regularity and residual repeat across the class. Do not write "aimbot" in the ticket. |
| `skilled_00` | 2.151 | Close | Elevated, but the features are the skilled tail of the human cohort. No single feature is a script signature. |
| `holdout_mouse_01` | 0.527 | Close | Inside the clean range for this fixture. |

Nothing in this packet is a ban. A ban needs a second source, a larger sample than two matches, and a reviewer who can argue with the number.

## What I would watch after action

Not the ban count. Match infection rate for the two weeks before and after, and whether the same hardware or payment instrument shows up on a new account within days. A wave that only moves the ban counter, while infection rate and replacement rate stay flat, did not change the game.

## What this does not prove

- That these thresholds work on live telemetry. The fixture was built so the scorer could see the classes.
- That a YARA hit would have changed the call. The rules in `yara/` are heuristics. They are not evidence in this packet.
- That I have access to Apex data. I do not.

# Detection methodology

How this repo's detectors are built, calibrated and evaluated.

## 1. Start from a question, not a feature

"Is this player cheating" is not a question a detector can answer. Good questions are
measurable:

- Does this player's time-to-target distribution differ from their input cohort?
- Is the per-shot recoil compensation more regular than a human can produce?
- Are fires occurring faster than human reaction time allows?

Each detector in [`detections/`](../detections/) answers exactly one such question and emits one
number plus the evidence behind it.

## 2. Build a labelled set

Labels come from enforcement outcomes, not from gut feel:

| Label source | Bias to watch for |
|:---|:---|
| Confirmed bans (appeal-upheld) | Only catches what is already caught — circular |
| Manual analyst review | Inter-rater disagreement; measure it |
| Admitted / known-cheat accounts | Good positive anchor |
| Verified-clean cohort (pro players, staff, trusted) | Small and unrepresentative |
| Synthetic injection (scripted inputs, replayed patterns) | Fast but unrealistically clean |

Use several sources and report which you used. A detector validated only on synthetic cheats
over-fits to synthetic cheats.

## 3. Cohort before score

Pooling populations destroys signal. Fit baselines **per cohort**:

- input device (mouse vs. controller vs. emulator)
- skill / rank tier
- weapon class (recoil patterns differ)
- input sample rate (poll-rate dependent metrics)

`baseline.py` fits one distribution per (cohort, metric) pair and stores mean, std and robust
percentiles. Robust statistics (median/MAD, percentiles) matter: skill distributions have heavy
tails and a single genuine outlier should not move the baseline.

## 4. Score, don't decide

`detectors.py` emits a **review score**, not a verdict:

- each metric produces a z-score against the cohort baseline (or a percentile rank)
- metrics are combined with a configurable weighted sum
- the top contributing features are written alongside the score

Never auto-ban on a single feature. The output is a queue ordered by suspicion, with the
evidence a human needs to decide.

## 5. Measure before deploying

For any threshold you intend to act on, report:

- **TPR at a fixed FPR** — recall at, say, 0.1% false-positive rate. In a game with millions of
  players, 0.1% FPR is still thousands of false accusations, so pick the FPR target from the
  player population, not from convention.
- **Precision in the actioned band** — of the accounts you would ban, how many are right?
- **Population lift** — how much does the flagged band enrich for true positives over random?
- **Stability over time** — metrics drift (new weapons, patches, input devices). Re-fit on a
  schedule and track baseline drift.

Report confidence intervals. With a small labelled set, a detector that looks 95% accurate is
usually a coin flip with error bars.

## 6. Explainability is a requirement

For every flag an analyst should be able to answer:

1. What behaviour was measured?
2. What is the normal range for this player's cohort?
3. How far outside it is this player, and in how many independent matches?
4. Is there a benign explanation (smurf, pro, unusual hardware, accessibility input)?

Benign explanations are common. A genuinely excellent mouse player is a legitimate outlier —
which is why **cross-match consistency** (repeated outliers across independent matches) is a far
stronger signal than any single-match score.

## 7. Keep the loop closed

Intel → detector → enforcement → measurement → intel. Every enforcement wave is an experiment:
measure infection rate before and after, watch for evasion adaptation, and feed the adaptation
back into the taxonomy ([cheat-intel](https://github.com/NetVar1337/cheat-intel)).

# FPS cheat taxonomy

A working taxonomy for FPS titles (Apex-shaped: hero shooter, high TTK, movement-heavy,
server-authoritative with client prediction). Each class lists **how it works** and **how a
defender detects it** — the detection is the part that matters.

---

## 1. Aim automation

### 1.1 Aimbot (memory-assisted)

Reads entity state (position, bone/head index, visibility) from game or driver memory, computes
the angle delta to the target, and writes view angles or synthesises mouse input.

- **Sub-variants:** on-key (human-triggered) vs. always-on; smoothing (interpolated angles to
  look human); FOV-limited (only aims inside a cone); bone-priority (head > neck > chest);
  target-switching policy; prediction for moving targets.
- **Detection:** aim kinematics — angular velocity spikes that terminate exactly on target,
  time-to-target inconsistent with Fitts' law for the distance travelled, reaction times below
  the human floor (~100-120 ms visual), repeated identical acquisition trajectories, and a
  headshot-rate tail far outside the cohort distribution.

### 1.2 Triggerbot

Does not move the crosshair; fires the instant a target is under it. Sometimes with a randomised
delay and an "only when visible" check.

- **Detection:** time-from-crosshair-entry-to-fire distribution; a mass at 0-40 ms with a
  suspiciously narrow spread; fire events on frames where the target is occluded for a human
  but visible to the client.

### 1.3 Silent aim / server-side angle manipulation

Sends legitimate-looking mouse input for the visible aim but a different angle to the server
(hit registration).

- **Detection:** divergence between client-reported view angles and server-observed hit vectors;
  hits whose implied shot direction is not reproducible from the recorded input stream.

### 1.4 No-recoil / no-spread / recoil scripts

Replaces or cancels the weapon's recoil pattern. Two forms:

- *Memory:* zeroes the recoil accumulator or patches the spread function.
- *Input:* sends a pre-computed compensating mouse delta per shot (works on console too).

- **Detection:** the compensating deltas are **deterministic**. Autocorrelation of the per-shot
  mouse-dy sequence shows near-identical periodicity; residual variance after subtracting the
  learned pattern collapses to ~0 for scripts and stays high for humans. Also: accuracy at range
  with high-recoil weapons far outside cohort norms.

### 1.5 Computer-vision / external aim

A second machine or capture card reads frames, runs detection (classical CV or a small model),
and drives a mouse/keyboard emulator (USB HID) or a controller emulator. **Never touches game
memory.**

- **Detection:** why behavioral analysis is not optional. Look for input-device-level anomalies
  (HID report timing jitter characteristic of emulators, constant inter-event intervals),
  perfect tracking smoothness, and hardware descriptors of known emulator devices.

## 2. Information cheats (ESP / wallhack)

Reveals opponents through geometry: boxes, skeletons, health bars, distance, loot, or a radar.

- **How:** reads entity list + transforms from memory; or hooks the render path (D3D11/12
  present/resize hooks); or — external case — a second screen showing an extracted game-state feed.
- **Sub-variants:** glow/outline injection (modifies material/shader state), chams, skeleton ESP,
  radar via map overlay, loot ESP.
- **Detection:** pure ESP does not change aim, so aim metrics alone miss it. Signals instead:
  pre-aim/pre-fire through walls (crosshair tracks an occluded player), pathing that consistently
  avoids hidden opponents, movement decisions carrying too much information, and server-side
  "knowledge" tests (place a decoy entity visible only server-side and see who reacts).

## 3. Movement & physics manipulation

- **Speed hack / teleport:** alters client time-step or position before replication.
- **Bunny-hop / auto-strafe scripts, wall-climb, no-clip, fly.**
- **Packet manipulation:** replayed or dropped position packets to desync hit registration.
- **Detection:** server-side movement validation — displacement-vs-time sanity envelopes,
  acceleration limits, impossible ground-trace results, reconciliation-error telemetry.

## 4. Hardware-assisted cheats

### 4.1 DMA (Direct Memory Access)

A second machine reads physical memory over PCIe from an FPGA/PCIe card, computes ESP/aim on the
second machine, and returns input over USB/serial. The game host is untouched.

- **Detection:** PCIe device enumeration and vendor/device-ID allowlisting; configuration-space
  and link characteristics that do not match a genuine device class; unexpected DMA-remapping
  (IOMMU / Vt-d) state; timing fingerprints of the FPGA firmware; driver presence of known DMA
  toolkit drivers; behavioral detection at the game layer as a backstop.

### 4.2 Controller emulation / macro devices

Cronus-class and Titan-class devices that plug in as a controller and run scripted recoil,
rapid-fire, or auto-aim macros; also input-bridging to use mouse aim on console.

- **Detection:** device descriptor and firmware revision fingerprinting, HID report timing,
  report-rate characteristics, anti-recoil signature at the input layer.

### 4.3 Firmware / hypervisor level

Hypervisor-based memory virtualisation to hide state from a kernel anti-cheat; firmware-level
HWID masking; bootkit-class persistence.

- **Detection:** hypervisor presence indicators, timing side channels (CPUID/RDTSC
  irregularities), unexpected EPT/SLAT state, secure-boot and measured-boot attestation gaps,
  TPM quote mismatches.

## 5. Integrity & identity abuse

- **HWID spoofing:** fakes motherboard/BIOS/disk/MAC/TPM identifiers to evade hardware bans.
  *Detection:* cross-field consistency (a "new" machine whose SMBIOS, disk serials, registry
  GUIDs and MAC vendor disagree), reuse of known-banned components, fingerprint churn rate.
- **Account sharing / piloting:** a high-skill player plays on someone else's account.
  *Detection:* impossible travel, input-behaviour drift (a fundamentally different aim signature
  on the same account), hardware/locale mismatch, session overlap.
- **Boosting / deranking:** deliberate losing to drop rank, then queueing with a paying customer.
  *Detection:* asymmetric duo performance, serial throw patterns, rank-trajectory anomalies.
- **Smurfing / bot accounts:** fresh accounts played at high skill, or accounts levelled by bots.
  *Detection:* skill-vs-account-age curves, bot-lobby clustering, input entropy of levelling matches.
- **Matchmaking manipulation:** stack manipulation, region abuse, queue dodging.

## 6. Cheat delivery / economics

- **Cheat-as-a-Service:** subscription distribution, private loaders, per-build encryption,
  automated update pipelines, Discord-based support. Signature work expires in days.
- **Private vs. public:** private cheats trade margin for undetectability. Behavioral signals
  close the gap because they do not depend on knowing the binary.
- **Resellers and account markets:** banning the account is not enough when replacement accounts
  cost cents — which is why identity/economic signals belong in the same loop
  ([`account-security`](https://github.com/NetVar1337/account-security)).

---

## Mapping: class → detection layer

| Cheat class | Host | Static | Behavioral | Account/Economic |
|:---|:---:|:---:|:---:|:---:|
| Aimbot (memory) | ◐ | ● | **●** | ○ |
| Triggerbot | ○ | ○ | **●** | ○ |
| Silent aim | ○ | ○ | **●** | ○ |
| No-recoil script | ○ | ○ | **●** | ○ |
| CV / external aim | ○ | ○ | **●** | ○ |
| ESP / wallhack | ◐ | ● | ◐ | ○ |
| Movement hacks | ○ | ◐ | **●** | ○ |
| DMA hardware | **●** | ◐ | ◐ | ○ |
| Controller emulator | **●** | ○ | ● | ○ |
| Hypervisor / firmware | ● | ◐ | ○ | ○ |
| HWID spoofing | ● | ○ | ○ | **●** |
| Account sharing | ○ | ○ | ● | **●** |
| Boosting / deranking | ○ | ○ | ◐ | **●** |

**●** primary layer · ◐ useful · ○ weak

Takeaway: **behavioral + economic layers carry most of the load**, because they survive cheat
rewrites, hardware changes and account churn. Host/static layers are high-precision but narrow.

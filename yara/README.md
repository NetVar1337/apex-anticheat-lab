# YARA rules — cheat loaders & HWID spoofers

Heuristic indicators only. These are **triage aids**, not verdicts: every rule here will
eventually produce false positives, so they are written to be narrow and to name the trait
they key on.

## What these rules are for

Cheat loaders are a poor signature target long-term — they are per-build encrypted and
re-rolled weekly. What *does* persist is the loader's functional shape: it has to decrypt a
payload, drop or map a driver, resolve a hardware fingerprint to evade a hardware ban, and
talk to a licensing backend. Those functional traits leave stable strings, imports and
resource shapes.

## Tuning before use

1. **Run against a clean corpus first.** Measure the false-positive rate on legitimate
   software you actually deploy (overlay tools, RGB software, benchmarking tools, capture
   software — all of which legitimately use the same APIs).
2. **Split rules by trait, not by product.** One rule per functional capability keeps a
   single rule's FP blast radius small.
3. **Never act on a single YARA hit.** Feed it into the same review queue as the behavioral
   signals. A hit is one more piece of evidence, not a ban.
4. **Expect 30-90 day lifespans.** Track which rules have gone quiet and retire them.

## Rules in this directory

| File | Trait family |
|:---|:---|
| `loader_traits.yar` | decrypt-and-execute, driver-drop, licensing/heartbeat strings |
| `hwid_spoofer_traits.yar` | SMBIOS/disk-serial/MAC spoofing, fingerprint patching |
| `input_emulator_traits.yar` | HID/controller emulation, macro/recoil scripting |

## Deliberate omissions

No per-product signatures, no hashes of specific cheat builds, and no strings harvested from
paywalled cheat binaries. Hashes go stale in days and belong in a private IOC feed, not a
public repo; publishing product-specific strings mostly helps cheat authors know what to
strip.

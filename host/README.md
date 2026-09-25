# Host survey

PowerShell 5.1+ / 7+. **Read-only**: enumerates and reports, never modifies system state.

## What it collects

| Section | Why it matters for anti-cheat |
|:---|:---|
| Loaded drivers + signer | Unsigned or unexpected-signer drivers are the classic BYOVD / DMA toolkit surface |
| Vulnerable-driver blocklist match | Known-abusable signed drivers that legitimate software should not be loading |
| PCIe device inventory | DMA cards present as PCI devices; vendor/device IDs and class are the primary tell |
| DMA-remapping (IOMMU/Vt-d) state | A disabled or unexpected remapping state removes the main hardware defence |
| Secure Boot / HVCI / TPM | The trust root the rest of the stack depends on; gaps here invalidate other signals |
| Device descriptors | Controller emulator and HID bridge fingerprints |

## Usage

```powershell
# full survey to the console
.\driver_survey.ps1

# write a JSON artifact for the detection pipeline
.\driver_survey.ps1 -OutFile .\host-survey.json

# cross-reference a vulnerable-driver blocklist CSV (columns: sha256, name, vendor)
.\driver_survey.ps1 -BlocklistCsv .\vulnerable-drivers.csv -OutFile .\host-survey.json
```

## The blocklist input

Microsoft publishes the **vulnerable and dangerous driver blocklist** as part of its
configuration CI / HVCI policy. Export the hashes you want to match against to a CSV and pass
it in. It is deliberately not vendored here: it changes, and a stale copy in a public repo is
worse than none.

Community mirrors exist and are regularly refreshed; validate any mirror against the official
Microsoft documentation before trusting it in a detection pipeline.

## Interpreting results

- **An unrecognised PCIe device is not proof of a DMA card.** Capture cards, NVMe add-in
  cards, network adapters and sound cards all appear here. The signal is a device whose
  vendor/device ID is not in your known-good inventory, or whose class and link characteristics
  disagree (e.g. a device claiming a simple storage class but presenting an FPGA-like
  configuration space).
- **Driver signer mismatches are common in the wild.** Some legitimate vendor software ships
  expired or cross-signed drivers. Baseline your fleet before alerting.
- **HVCI off is not a cheat signal.** Plenty of legitimate machines run without it. It changes
  the *threat model*, and belongs in the risk assessment, not in the alert.

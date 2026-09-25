<#
.SYNOPSIS
    Read-only host survey for anti-cheat / game-security telemetry.

.DESCRIPTION
    Enumerates loaded drivers and their signers, matches driver hashes against a
    vulnerable-driver blocklist, inventories PCIe devices (DMA detection surface),
    and reports the Secure Boot / HVCI / TPM posture.

    This script is strictly read-only. It does not install, unload, patch or modify
    anything.

.PARAMETER BlocklistCsv
    Optional CSV with columns: sha256, name, vendor. Driver images are hashed and
    compared against this list. See host/README.md for how to source it.

.PARAMETER OutFile
    Optional path to write the survey as JSON.

.PARAMETER HashDrivers
    Switch. Hash each driver image on disk (slower, but required for blocklist matching).

.EXAMPLE
    .\driver_survey.ps1 -OutFile .\host-survey.json

.EXAMPLE
    .\driver_survey.ps1 -BlocklistCsv .\vulnerable-drivers.csv -HashDrivers -OutFile .\host-survey.json
#>
[CmdletBinding()]
param(
    [string]$BlocklistCsv,
    [string]$OutFile,
    [switch]$HashDrivers
)

$ErrorActionPreference = 'Stop'
$survey = [ordered]@{
    generated_utc = (Get-Date).ToUniversalTime().ToString('o')
    computer      = $env:COMPUTERNAME
}

# --- 1. loaded drivers + signer -------------------------------------------
Write-Host '[1/5] enumerating loaded drivers...' -ForegroundColor Cyan
$drivers = Get-CimInstance -ClassName Win32_SystemDriver | ForEach-Object {
    $path = $_.PathName
    $full = if ($path) { $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath(($path -replace '^\\\?\?', '') -replace '^\\SystemRoot', "$env:SystemRoot") } else { $null }
    $sig  = $null
    if ($full -and (Test-Path -LiteralPath $full)) {
        try { $sig = (Get-AuthenticodeSignature -LiteralPath $full).SignerCertificate.Subject } catch { }
    }
    [pscustomobject]@{
        name      = $_.Name
        state     = $_.State
        status    = $_.Status
        startMode = $_.StartMode
        path      = $full
        signer    = $sig
    }
}
$survey.drivers = @($drivers)
Write-Host ("      {0} drivers, {1} without a verified signer" -f @($drivers).Count, @($drivers | Where-Object { -not $_.signer }).Count)

# --- 2. optional blocklist match ------------------------------------------
if ($BlocklistCsv -and $HashDrivers) {
    Write-Host '[2/5] matching driver images against blocklist...' -ForegroundColor Cyan
    $block = @{}
    Import-Csv -LiteralPath $BlocklistCsv | ForEach-Object {
        $block[$_.sha256.ToLowerInvariant()] = $_
    }
    $hits = foreach ($d in $drivers) {
        if ($d.path -and (Test-Path -LiteralPath $d.path)) {
            try {
                $h = (Get-FileHash -LiteralPath $d.path -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($block.ContainsKey($h)) {
                    [pscustomobject]@{
                        driver = $d.name
                        path   = $d.path
                        sha256 = $h
                        entry  = $block[$h].name
                        vendor = $block[$h].vendor
                    }
                }
            } catch { }
        }
    }
    $survey.blocklist_matches = @($hits)
    Write-Host ("      {0} blocklist matches" -f @($hits).Count)
} else {
    $survey.blocklist_matches = @()
    Write-Host '[2/5] skipping blocklist match (needs -BlocklistCsv and -HashDrivers)' -ForegroundColor DarkGray
}

# --- 3. PCIe device inventory (DMA surface) -------------------------------
Write-Host '[3/5] enumerating PCI devices...' -ForegroundColor Cyan
$pci = Get-CimInstance -ClassName Win32_PnPEntity |
    Where-Object { $_.DeviceID -like 'PCI\*' } |
    ForEach-Object {
        $ven = $null; $dev = $null; $sub = $null
        if ($_.DeviceID -match 'PCI\\VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})&SUBSYS_([0-9A-F]{8})') {
            $ven = $Matches[1]; $dev = $Matches[2]; $sub = $Matches[3]
        }
        [pscustomobject]@{
            name        = $_.Name
            device_id   = $_.DeviceID
            vendor_id   = $ven
            device_num  = $dev
            subsystem   = $sub
            class       = $_.PNPClass
            service     = $_.Service
            status      = $_.Status
            present     = $_.Present
        }
    }
$survey.pci_devices = @($pci)
Write-Host ("      {0} PCI devices" -f @($pci).Count)

# --- 4. DMA-remapping / Device Guard posture ------------------------------
Write-Host '[4/5] reading device-guard / HVCI posture...' -ForegroundColor Cyan
$posture = [ordered]@{}
try {
    $dg = Get-CimInstance -Namespace 'root\Microsoft\Windows\DeviceGuard' -ClassName Win32_DeviceGuard
    $posture.vbs_status                 = @($dg.VirtualizationBasedSecurityStatus)
    $posture.available_security_props   = @($dg.AvailableSecurityProperties)
    $posture.required_security_props    = @($dg.RequiredSecurityProperties)
    $posture.security_services_configured = @($dg.SecurityServicesConfigured)
    $posture.security_services_running  = @($dg.SecurityServicesRunning)
} catch {
    $posture.device_guard_error = $_.Exception.Message
}
try {
    $hvci = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity' -ErrorAction Stop
    $posture.hvci_enabled = [bool]$hvci.Enabled
    $posture.hvci_was_enabled_by = $hvci.WasEnabledBy
} catch {
    $posture.hvci_enabled = $null   # key absent = not configured; NOT the same as disabled
}
$survey.device_guard = $posture

# --- 5. Secure Boot + TPM -------------------------------------------------
Write-Host '[5/5] reading Secure Boot / TPM...' -ForegroundColor Cyan
$trust = [ordered]@{}
try { $trust.secure_boot = [bool](Confirm-SecureBootUEFI) }
catch { $trust.secure_boot = $null; $trust.secure_boot_error = $_.Exception.Message }
try {
    $tpm = Get-Tpm
    $trust.tpm_present        = [bool]$tpm.TpmPresent
    $trust.tpm_ready          = [bool]$tpm.TpmReady
    $trust.tpm_owned          = [bool]$tpm.TpmOwned
    $trust.tpm_activated      = [bool]$tpm.TpmActivated
    $trust.tpm_enabled        = [bool]$tpm.TpmEnabled
    $trust.tpm_manufacturer   = $tpm.ManufacturerIdTxt
} catch {
    $trust.tpm_error = $_.Exception.Message
}
$survey.trust = $trust

# --- output ---------------------------------------------------------------
$json = $survey | ConvertTo-Json -Depth 6
if ($OutFile) {
    $json | Set-Content -LiteralPath $OutFile -Encoding UTF8
    Write-Host "wrote $OutFile" -ForegroundColor Green
} else {
    Write-Host ''
    $json
}

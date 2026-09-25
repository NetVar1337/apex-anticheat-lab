/*
    Cheat loader functional traits — heuristic.

    One rule per capability, not per product. See README.md for tuning guidance and the
    false-positive warning. Do not action on a single hit.

    Tested against: YARA 4.x
*/

import "pe"

rule CheatLoader_CryptorShell
{
    meta:
        description = "Decrypt-and-execute shell: standard crypter/loader capability shape"
        rationale   = "Legitimate installers unpack; they rarely loop-decrypt into RWX and jump"
        confidence  = "medium"
        false_positive_rate = "medium — commercial protectors, some DRM"

    strings:
        $api_virtalloc = "VirtualAlloc" ascii wide nocase
        $api_vprotect  = "VirtualProtect" ascii wide nocase
        $api_thread    = "CreateThread" ascii wide nocase
        $api_section   = "NtCreateSection" ascii wide nocase
        $api_mapview   = "NtMapViewOfSection" ascii wide nocase

        // classic XOR/RC4 loop-decrypt stub constants
        $c_xor_key     = { 81 F1 ?? ?? ?? ?? 88 ?? ?? 40 3D ?? ?? ?? ?? 72 F1 }
        $c_rc4_ksa     = { 30 04 0F 41 81 F9 00 01 00 00 75 F2 }

    condition:
        uint16(0) == 0x5A4D and
        filesize < 8MB and
        (2 of ($api_*)) and
        (1 of ($c_*))
}

rule CheatLoader_DriverDrop
{
    meta:
        description = "User-mode component that writes and loads a kernel driver"
        rationale   = "Normal apps rarely drop a .sys and call the SCM to load it"
        confidence  = "high"
        false_positive_rate = "low — some legitimate vendor updaters"

    strings:
        $sys_ext      = ".sys" ascii wide nocase
        $svc_create   = "CreateService" ascii wide nocase
        $svc_start    = "StartService" ascii wide nocase
        $scm_open     = "OpenSCManager" ascii wide nocase
        $nt_load_drv  = "NtLoadDriver" ascii wide
        $reg_drvpath  = "\\Registry\\Machine\\System\\CurrentControlSet\\Services" ascii wide nocase
        $dev_ioctl    = "DeviceIoControl" ascii wide nocase

    condition:
        uint16(0) == 0x5A4D and
        $sys_ext and
        (2 of ($svc_create, $svc_start, $scm_open, $nt_load_drv)) and
        (1 of ($reg_drvpath, $dev_ioctl))
}

rule CheatLoader_LicensingHeartbeat
{
    meta:
        description = "Subscription licensing + heartbeat: cheat-as-a-service delivery shape"
        rationale   = "Per-user tokens, HWID binding and expiry strings are stable across builds"
        confidence  = "medium"
        false_positive_rate = "medium — SaaS applications generally"

    strings:
        $l_hwid      = "hwid" ascii wide nocase
        $l_sub       = "subscription" ascii wide nocase
        $l_expires   = "expires_at" ascii wide nocase
        $l_license   = "license_key" ascii wide nocase
        $l_token     = "Bearer " ascii wide
        $l_discord   = "discord.com/api" ascii wide nocase
        $l_webhook   = "discord.com/api/webhooks" ascii wide nocase
        $l_gate      = "gate" ascii wide nocase

    condition:
        uint16(0) == 0x5A4D and
        3 of ($l_*)
}

rule CheatLoader_ManualMap
{
    meta:
        description = "Manual mapping: reflective load without a standard loader"
        rationale   = "Legitimate plugins use LoadLibrary; manual mapping is deliberate stealth"
        confidence  = "medium-high"
        false_positive_rate = "medium — game mod loaders, some overlays"

    strings:
        $m_exportdir = { 48 63 ?? ?? 48 03 ?? 48 8B ?? ?? 48 85 C0 74 ?? }
        $m_reloc     = "IMAGE_DIRECTORY_ENTRY_BASERELOC" ascii
        $m_import    = "IMAGE_DIRECTORY_ENTRY_IMPORT" ascii
        $m_ntunmap   = "NtUnmapViewOfSection" ascii wide
        $m_ldrload   = "LdrLoadDll" ascii wide

    condition:
        uint16(0) == 0x5A4D and
        (2 of ($m_*))
}

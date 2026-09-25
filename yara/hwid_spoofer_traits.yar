/*
    HWID spoofer functional traits — heuristic.

    A spoofer has to fake identifiers consistently enough to pass a fingerprint check. That
    means it must reach the same APIs the fingerprint uses: SMBIOS enumeration, disk serial
    queries, MAC/adapter enumeration, registry GUIDs, and TPM state.

    See README.md for tuning guidance. Do not action on a single hit.
*/

rule HwidSpoofer_SmbiosAndDiskSerial
{
    meta:
        description = "Fakes SMBIOS / disk serial identity fields"
        rationale   = "Legitimate inventory tools read these; they do not patch them"
        confidence  = "medium"
        false_positive_rate = "medium — inventory/asset-management agents, benchmark tools"

    strings:
        $a_getsystemfirmware = "GetSystemFirmwareTable" ascii wide nocase
        $a_smbios            = "RSMB" ascii wide
        $a_smart             = "SMART_SEND_DRIVE_COMMAND" ascii wide nocase
        $a_storageprop       = "StorageDeviceProperty" ascii wide nocase
        $a_ioctl_storage     = "IOCTL_STORAGE_QUERY_PROPERTY" ascii wide nocase
        $a_ioctl_disk        = "IOCTL_DISK_GET_DRIVE_LAYOUT_EX" ascii wide nocase

        // fake-value constants commonly substituted
        $f_to_be_filled      = "To Be Filled By O.E.M." ascii wide nocase
        $f_defaultstring     = "Default string" ascii wide nocase
        $f_systemserial      = "System Serial Number" ascii wide nocase

    condition:
        uint16(0) == 0x5A4D and
        2 of ($a_*) and
        1 of ($f_*)
}

rule HwidSpoofer_RegistryGuidChurn
{
    meta:
        description = "Patches machine identity registry GUIDs"
        rationale   = "MachineGuid / HwProfileGuid churn is the cheapest evasion and the easiest to see"
        confidence  = "medium-high"
        false_positive_rate = "low"

    strings:
        $r_machineguid = "MachineGuid" ascii wide
        $r_hwprofile   = "HwProfileGuid" ascii wide
        $r_productid   = "ProductId" ascii wide
        $r_editionid   = "EditionID" ascii wide
        $r_installid   = "InstallationID" ascii wide
        $api_regset    = "RegSetValueEx" ascii wide
        $api_regsetnt  = "NtSetValueKey" ascii wide

    condition:
        uint16(0) == 0x5A4D and
        2 of ($r_*) and
        1 of ($api_*)
}

rule HwidSpoofer_TpmFingerprint
{
    meta:
        description = "Reads or fakes TPM-backed machine identity"
        rationale   = "TPM attestation is the strongest fingerprint; tools that touch it are rare"
        confidence  = "high"
        false_positive_rate = "low"

    strings:
        $t_tbs        = "tbs.dll" ascii wide nocase
        $t_getcap     = "Tbsi_Get_TCG_Log" ascii wide nocase
        $t_pcrcap     = "Tbsi_Physical_Presence_Command" ascii wide nocase
        $t_nvread     = "TPM2_NV_Read" ascii wide nocase
        $t_ekcert     = "EK certificate" ascii wide nocase
        $t_quote      = "TPM Quote" ascii wide nocase

    condition:
        uint16(0) == 0x5A4D and
        2 of ($t_*)
}

rule HwidSpoofer_NicMacSpoof
{
    meta:
        description = "Rewrites network adapter MAC / configuration"
        rationale   = "MAC is part of most HWID bundles"
        confidence  = "low-medium"
        false_positive_rate = "high — VPN/proxy/NIC management tools"

    strings:
        $n_macreg    = "NetworkAddress" ascii wide
        $n_adaptset  = "SetIfEntry" ascii wide nocase
        $n_adaptcfg  = "SNMP_oid" ascii wide nocase
        $n_registry  = "\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4D36E972" ascii wide nocase

    condition:
        uint16(0) == 0x5A4D and
        2 of ($n_*)
}

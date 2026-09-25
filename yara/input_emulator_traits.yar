/*
    Input emulation / macro traits — heuristic.

    Covers the two shapes that matter for FPS: devices that present as a HID controller but
    are scripted, and user-mode software that synthesises input to control recoil or fire
    timing.

    See README.md for tuning guidance. Do not action on a single hit.
*/

rule InputEmulator_HidBridge
{
    meta:
        description = "Bridges one input class into a HID controller report stream"
        rationale   = "Cross-device input bridging is the core of console aim/recoil devices"
        confidence  = "medium"
        false_positive_rate = "high — accessibility tools, legitimate adapters"

    strings:
        $h_sendinput     = "SendInput" ascii wide
        $h_mouse_event   = "mouse_event" ascii wide
        $h_writefile_hid = { 48 8B ?? 48 8D ?? ?? ?? ?? ?? 48 8B ?? FF 15 ?? ?? ?? ?? 85 C0 }
        $h_vjoy          = "vJoy" ascii wide nocase
        $h_vigem         = "ViGEm" ascii wide nocase
        $h_x360          = "Xbox 360 Controller" ascii wide nocase
        $h_ds4           = "DualShock" ascii wide nocase
        $h_reportdesc    = { 05 01 09 04 A1 01 15 00 26 FF 00 }

    condition:
        uint16(0) == 0x5A4D and
        (1 of ($h_vjoy, $h_vigem, $h_x360, $h_ds4, $h_reportdesc)) and
        (1 of ($h_sendinput, $h_mouse_event, $h_writefile_hid))
}

rule Macro_RecoilScriptEngine
{
    meta:
        description = "Deterministic per-shot input scripting engine"
        rationale   = "Table-driven compensation with timing is the anti-recoil script shape"
        confidence  = "medium"
        false_positive_rate = "medium — macro peripherals' own software"

    strings:
        $m_profile    = "recoil_profile" ascii wide nocase
        $m_pattern    = "recoil_pattern" ascii wide nocase
        $m_compensate = "compensate" ascii wide nocase
        $m_per_shot   = "per_shot" ascii wide nocase
        $m_smoothing  = "smoothing" ascii wide nocase
        $m_randdelay  = "random_delay" ascii wide nocase
        $m_triggerbot = "triggerbot" ascii wide nocase
        $m_fov        = "aim_fov" ascii wide nocase

    condition:
        uint16(0) == 0x5A4D and
        3 of ($m_*)
}

rule TimingFixedInputLoop
{
    meta:
        description = "Input loop with a fixed inter-event interval"
        rationale   = "Human input timing is log-normal; a constant interval is mechanical"
        confidence  = "low"
        false_positive_rate = "high — any polling loop; use only with corroborating evidence"

    strings:
        $t_qpc       = "QueryPerformanceCounter" ascii wide
        $t_sleep     = "Sleep" ascii wide
        $t_ntdelay   = "NtDelayExecution" ascii wide
        $t_sendinput = "SendInput" ascii wide

    condition:
        uint16(0) == 0x5A4D and
        2 of ($t_qpc, $t_sleep, $t_ntdelay) and
        $t_sendinput
}

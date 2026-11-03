# Offline only: parse the helpers and mock every Windows device/network query.
$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
foreach ($name in @("run-usb-nbd-fastboot.ps1", "run-usb-debug-fastboot.ps1", "usb-gadget-identity.ps1")) {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $project "tools\$name"), [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count -ne 0) { throw ($parseErrors | Out-String) }
}
. (Join-Path $project "tools\usb-gadget-identity.ps1")

function Expect-Refusal([scriptblock]$Action) {
    $refused = $false
    try { & $Action | Out-Null } catch { $refused = $true }
    if (-not $refused) { throw "Expected refusal did not occur." }
}
function Get-PnpDevice {
    param([switch]$PresentOnly, $ErrorAction)
    return $script:devices
}
function Get-PnpDeviceProperty {
    param($InstanceId, $KeyName, $ErrorAction)
    if ($script:queryFailure) { throw "Simulated PnP provider failure" }
    return [pscustomobject]@{Data = $script:locations[$InstanceId]}
}
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    return [pscustomobject]@{PNPDeviceID = "USB\VID_18D1&PID_4EE7&MI_00\GADGET"}
}
function Find-NetRoute {
    param($RemoteIPAddress, $ErrorAction)
    return @([pscustomobject]@{InterfaceIndex = $script:routeIndex})
}
$script:devices = @([pscustomobject]@{InstanceId = "USB\VID_18D1&PID_D00D\TEST.123"})
$script:locations = @{
    "USB\VID_18D1&PID_D00D\TEST.123" = @("PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(3)")
    "USB\VID_18D1&PID_4EE7&MI_00\GADGET" = @("PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(3)#USBMI(0)")
}
$script:queryFailure = $false
$ports = @(Get-TargetUsbPorts "TEST.123")
$adapter = [pscustomobject]@{ifIndex = 17}
Assert-GadgetUsbPort $adapter $ports
Expect-Refusal { Get-TargetUsbPorts "TESTx123" }
Expect-Refusal { Assert-GadgetUsbPort $adapter @("PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(4)") }
$script:queryFailure = $true
Expect-Refusal { Get-TargetUsbPorts "TEST.123" }
$script:queryFailure = $false
$script:devices += $script:devices[0]
Expect-Refusal { Get-TargetUsbPorts "TEST.123" }
$script:routeIndex = 17
Assert-GadgetRoute $adapter "192.168.42.2"
$script:routeIndex = 18
Expect-Refusal { Assert-GadgetRoute $adapter "192.168.42.2" }
Write-Output "PowerShell parsing and six USB identity/route cases passed; no device queries ran."

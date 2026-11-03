# Shared by both fastboot helpers. Match the physical USB port across modes.
function Get-UsbPortPaths([string]$InstanceId) {
    $paths = @((Get-PnpDeviceProperty -InstanceId $InstanceId `
        -KeyName "DEVPKEY_Device_LocationPaths" -ErrorAction Stop).Data |
        ForEach-Object { "$_" -replace "#USBMI\(\d+\)$", "" } |
        Where-Object { $_ -match "#USB\(\d+\)$" } | Sort-Object -Unique)
    if ($paths.Count -eq 0) {
        throw "Cannot establish the physical USB port; do not move the cable or retry boot."
    }
    return $paths
}

function Get-TargetUsbPorts([string]$Serial) {
    $devices = @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object {
        $_.InstanceId -match ("^USB\\[^\\]+\\" + [regex]::Escape($Serial) + "$")
    })
    if ($devices.Count -ne 1) {
        throw "Cannot uniquely locate the serial-scoped fastboot USB device."
    }
    return @(Get-UsbPortPaths $devices[0].InstanceId)
}

function Assert-GadgetUsbPort($NetworkAdapter, [string[]]$ExpectedPorts) {
    $pnp = Get-CimInstance Win32_NetworkAdapter `
        -Filter "InterfaceIndex = $($NetworkAdapter.ifIndex)" -ErrorAction Stop
    if ($null -eq $pnp -or $pnp.PNPDeviceID -notmatch "^USB\\VID_18D1&PID_4EE7") {
        throw "Matching MAC is not the expected USB gadget."
    }
    $ports = @(Get-UsbPortPaths $pnp.PNPDeviceID)
    if (@($ports | Where-Object { $ExpectedPorts -contains $_ }).Count -eq 0) {
        throw "The gadget is on a different USB port from the target fastboot device."
    }
}

function Assert-GadgetRoute($NetworkAdapter, [string]$DeviceAddress) {
    $routes = @(Find-NetRoute -RemoteIPAddress $DeviceAddress -ErrorAction Stop)
    if ($routes.Count -eq 0 -or
        @($routes | Where-Object { $_.InterfaceIndex -ne $NetworkAdapter.ifIndex }).Count -ne 0) {
        throw "The device address routes through another interface; leaving routing unchanged."
    }
}

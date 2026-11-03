#requires -Version 5.1
#requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BootImage,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedBootSHA256,
    [string]$FastbootPath = "fastboot.exe",
    [Parameter(Mandatory = $true)]
    [string]$FastbootSerial,
    [Parameter(Mandatory = $true)]
    [string]$LogDirectory,
    [ValidateSet("a", "b")]
    [string]$ExpectedSlot = "a"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "usb-gadget-identity.ps1")
$bindAddress = "192.168.42.1"
$adapter = $null
$addedAddress = $false
$addressAttempted = $false
$originalDhcp = $null
New-Item -ItemType Directory -Path $LogDirectory -ErrorAction Stop | Out-Null
Start-Transcript -Path (Join-Path $LogDirectory "host-transcript.txt") | Out-Null

function Invoke-TargetFastboot([string]$Label, [string[]]$Arguments) {
    $nativeArguments = @("-s", $FastbootSerial) + $Arguments
    $quoted = foreach ($value in $nativeArguments) {
        if ($value.Contains('"') -or $value.EndsWith("\")) {
            throw "Unsupported quote or trailing backslash in a native argument."
        }
        '"' + $value + '"'
    }
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $fastboot.Source
    $process.StartInfo.Arguments = $quoted -join " "
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    $null = $process.Start()
    $outputTask = $process.StandardOutput.ReadToEndAsync()
    $errorTask = $process.StandardError.ReadToEndAsync()
    $deadline = (Get-Date).AddSeconds(120)
    while (-not $process.HasExited -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
        $process.Refresh()
    }
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        throw "Fastboot timed out; inspect device state before any retry."
    }
    $process.WaitForExit()
    $outputTask.Result | Set-Content -LiteralPath (Join-Path $LogDirectory "$Label.stdout.txt")
    $errorTask.Result | Set-Content -LiteralPath (Join-Path $LogDirectory "$Label.stderr.txt")
    $text = $outputTask.Result + $errorTask.Result
    Write-Host $text
    if ($process.ExitCode -ne 0 -or $text -match "FAILED|< waiting for") {
        throw "Fastboot $Label failed; inspect the private logs."
    }
    return $text
}

try {
    if ((Get-FileHash -LiteralPath $BootImage -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedBootSHA256) {
        throw "Boot image hash mismatch."
    }
    $fastboot = Get-Command $FastbootPath -ErrorAction Stop
    if (Get-NetIPAddress -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop |
        Where-Object { $_.IPAddress -eq $bindAddress }) {
        throw "The temporary host address already exists; leaving it untouched."
    }
    if (Get-NetTCPConnection -State Listen -LocalPort 10809 -ErrorAction SilentlyContinue) {
        throw "An NBD listener still exists; finish maintenance cleanup first."
    }
    $existing = @(Get-NetAdapter -IncludeHidden | Where-Object {
        $_.Status -eq "Up" -and
        ($_.MacAddress -replace "[:-]", "") -eq "020000000002"
    })
    if ($existing.Count -ne 0) {
        throw "A matching gadget is already online; refusing ambiguous device ownership."
    }
    foreach ($query in @(
        @("product", "elden_prc_wifi"),
        @("hwboardid", "TB322FC_SM8750P_16\+512"),
        @("unlocked", "yes"),
        @("is-userspace", "no"),
        @("current-slot", $ExpectedSlot)
    )) {
        $reply = Invoke-TargetFastboot "preflight-$($query[0])" @("getvar", $query[0])
        if ($reply -notmatch "(?m)^(?:\(bootloader\)\s*)?$($query[0]):\s*$($query[1])\s*$") {
            throw "Unexpected fastboot $($query[0]); stopping before boot."
        }
    }
    $targetPorts = @(Get-TargetUsbPorts $FastbootSerial)
    $reply = Invoke-TargetFastboot "boot" @("boot", $BootImage)
    if ($reply -notmatch "Booting\s+OKAY") {
        throw "No explicit Booting OKAY; inspect state before retrying."
    }

    $deadline = (Get-Date).AddSeconds(120)
    while ($null -eq $adapter -and (Get-Date) -lt $deadline) {
        $matches = @(Get-NetAdapter -IncludeHidden | Where-Object {
            $_.Status -eq "Up" -and
            ($_.MacAddress -replace "[:-]", "") -eq "020000000002"
        })
        if ($matches.Count -gt 1) {
            throw "Multiple adapters match the USB gadget."
        }
        if ($matches.Count -eq 1) {
            $candidate = $matches[0]
            Assert-GadgetUsbPort $candidate $targetPorts
            $adapter = $candidate
        } else {
            Start-Sleep -Seconds 1
        }
    }
    if ($null -eq $adapter) {
        throw "USB debug gadget did not appear; no boot retry was issued."
    }
    $originalDhcp = (Get-NetIPInterface -InterfaceIndex $adapter.ifIndex `
        -AddressFamily IPv4 -PolicyStore ActiveStore).Dhcp
    $addressAttempted = $true
    New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $bindAddress `
        -PrefixLength 24 -AddressFamily IPv4 -PolicyStore ActiveStore | Out-Null
    $addedAddress = $true
    Assert-GadgetRoute $adapter "192.168.42.2"
    @{
        interface_guid = $adapter.InterfaceGuid.ToString()
        host_address = $bindAddress
        original_dhcp = "$originalDhcp"
        usb_port_verified = $true
        nbd_started = $false
        firewall_rule_added = $false
        boot_sha256 = $ExpectedBootSHA256
        ready = (Get-Date).ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogDirectory "ready.json")
    Write-Host "USB SSH ready at 192.168.42.2. Rootfs comes from internal storage."
    Write-Host "The temporary host address is removed when the gadget disconnects."
    while ($true) {
        $current = @(Get-NetAdapter -IncludeHidden | Where-Object {
            $_.InterfaceGuid -eq $adapter.InterfaceGuid -and $_.Status -eq "Up"
        })
        if ($current.Count -eq 0) { break }
        Start-Sleep -Seconds 1
    }
}
finally {
    $cleanup = @{
        complete = $true
        address_added = $addedAddress
        address_attempted = $addressAttempted
    }
    if ($null -ne $adapter) {
        $cleanup.interface_guid = $adapter.InterfaceGuid.ToString()
        $cleanup.original_dhcp = "$originalDhcp"
        try {
            # Match the recorded GUID as interface indices may be reused.
            $current = @(Get-NetAdapter -IncludeHidden | Where-Object {
                $_.InterfaceGuid -eq $adapter.InterfaceGuid
            })
            if ($current.Count -ne 1) {
                throw "Recorded gadget cannot be enumerated; cleanup is unverified."
            }
            $index = $current[0].ifIndex
            if ($addressAttempted) {
                $addresses = @(Get-NetIPAddress -AddressFamily IPv4 `
                    -PolicyStore ActiveStore -ErrorAction Stop |
                    Where-Object { $_.InterfaceIndex -eq $index -and $_.IPAddress -eq $bindAddress })
                $addresses | Remove-NetIPAddress -Confirm:$false -ErrorAction Stop
                if (Get-NetIPAddress -AddressFamily IPv4 -PolicyStore ActiveStore `
                    -ErrorAction Stop | Where-Object {
                        $_.InterfaceIndex -eq $index -and $_.IPAddress -eq $bindAddress
                    }) {
                    throw "Temporary USB address remains."
                }
            }
            if ($null -ne $originalDhcp) {
                Set-NetIPInterface -InterfaceIndex $index `
                    -AddressFamily IPv4 -Dhcp $originalDhcp `
                    -PolicyStore ActiveStore -ErrorAction Stop
                $restored = (Get-NetIPInterface -InterfaceIndex $index `
                    -AddressFamily IPv4 -PolicyStore ActiveStore).Dhcp
                if ($restored -ne $originalDhcp) {
                    throw "Original DHCP state has not been restored."
                }
            }
        } catch {
            $cleanup.complete = $false
            $cleanup.error = "$_"
        }
    }
    $cleanup | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogDirectory "cleanup.json")
    Stop-Transcript | Out-Null
    if (-not $cleanup.complete) {
        throw "USB cleanup remains pending for the recorded GUID; see cleanup.json."
    }
}

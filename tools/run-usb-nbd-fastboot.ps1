#requires -Version 5.1
#requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [Alias("Image")]
    [string]$BootImage,
    [Parameter(Mandatory = $true)]
    [string]$RootfsImage,
    [string]$FastbootPath = "fastboot.exe",
    [Parameter(Mandatory = $true)]
    [string]$FastbootSerial,
    [string]$BindAddress = "192.168.42.1",
    [string]$DeviceAddress = "192.168.42.2",
    [ValidateSet("a", "b")]
    [string]$ExpectedSlot = "a",
    [Parameter(Mandatory = $true)]
    [string]$LogDirectory,
    [int]$Port = 10809,
    [int]$ServeSeconds = 300
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "usb-gadget-identity.ps1")

# Private logs must be supplied explicitly, outside the public project.
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
Start-Transcript -Path (Join-Path $LogDirectory "host-transcript.txt") | Out-Null

function Quote-NativeArgument([string]$Value) {
    if ($Value.Contains('"') -or $Value.EndsWith("\")) {
        throw "Unsupported quote or trailing backslash in a native argument."
    }
    return '"' + $Value + '"'
}

function Invoke-TargetFastboot([string]$Label, [string[]]$Arguments) {
    $stdout = Join-Path $LogDirectory "$Label.stdout.txt"
    $stderr = Join-Path $LogDirectory "$Label.stderr.txt"
    $commandArguments = @("-s", $FastbootSerial) + $Arguments
    $argumentString = ($commandArguments | ForEach-Object {
        Quote-NativeArgument $_
    }) -join " "
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = $fastboot.Source
    $process.StartInfo.Arguments = $argumentString
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
        throw "fastboot $Label timed out; device state needs inspection."
    }
    $process.WaitForExit()
    $outputTask.Result | Set-Content -LiteralPath $stdout
    $errorTask.Result | Set-Content -LiteralPath $stderr
    $text = $outputTask.Result + $errorTask.Result
    Write-Host $text
    if ($process.ExitCode -ne 0 -or $text -match "FAILED|< waiting for") {
        throw "fastboot $Label failed; see private logs."
    }
    return $text
}

if (-not (Test-Path -LiteralPath $BootImage -PathType Leaf)) {
    throw "Boot image does not exist: $BootImage"
}
if (-not (Test-Path -LiteralPath $RootfsImage -PathType Leaf)) {
    throw "Rootfs image does not exist: $RootfsImage"
}

$serverScript = Join-Path $PSScriptRoot "serve-rootfs-nbd.py"
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if ($null -eq $python) {
    $python = Get-Command py.exe -ErrorAction SilentlyContinue
}
if ($null -eq $python) {
    throw "Python 3 is required to serve the NBD rootfs."
}

$fastboot = Get-Command $FastbootPath -ErrorAction SilentlyContinue
if ($null -eq $fastboot) {
    throw "fastboot.exe was not found: $FastbootPath"
}

$serverArguments = @(
    "-u",
    $serverScript,
    "--image", $RootfsImage,
    "--bind", "0.0.0.0",
    "--port", "$Port",
    "--allow-client", $DeviceAddress
)
$serverArgumentString = ($serverArguments | ForEach-Object {
    Quote-NativeArgument $_
}) -join " "
if ($python.Name -eq "py.exe") {
    # The launcher parses its selector before Windows argv quote processing.
    $serverArgumentString = "-3 " + $serverArgumentString
}

$serverProcess = $null
$adapter = $null
$addedAddress = $false
$addressAttempted = $false
$originalDhcp = $null
$firewallRuleName = "Codex TB322FC USB-NBD $PID-$Port"
$firewallRule = $null
$bootRequested = $false
$disconnectVerified = $false
try {
    $beforeAdapters = @(Get-NetAdapter -IncludeHidden -ErrorAction Stop)
    $beforeAdapters |
        Select-Object ifIndex, Name, InterfaceGuid, MacAddress, Status, InterfaceDescription |
        ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath (Join-Path $LogDirectory "adapters-before.json")
    if (@($beforeAdapters | Where-Object {
        $_.Status -eq "Up" -and ($_.MacAddress -replace "[:-]", "") -eq "020000000002"
    }).Count -ne 0) {
        throw "A matching gadget is already online; refusing ambiguous device ownership."
    }
    if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
        throw "TCP port $Port is already in use."
    }
    if (Get-NetIPAddress -IPAddress $BindAddress -ErrorAction SilentlyContinue) {
        throw "Host test address $BindAddress already exists; leaving it untouched."
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
    $serverProcess = Start-Process -FilePath $python.Source `
        -ArgumentList $serverArgumentString -PassThru -NoNewWindow `
        -RedirectStandardOutput (Join-Path $LogDirectory "nbd.stdout.txt") `
        -RedirectStandardError (Join-Path $LogDirectory "nbd.stderr.txt")
    Start-Sleep -Milliseconds 500
    if ($serverProcess.HasExited) {
        throw "NBD server exited before fastboot boot."
    }

    $bootRequested = $true
    $bootReply = Invoke-TargetFastboot "boot" @("boot", $BootImage)
    if ($bootReply -notmatch "Booting\s+OKAY") {
        throw "No explicit fastboot Booting OKAY; inspect state before retrying."
    }

    $adapterDeadline = (Get-Date).AddSeconds(90)
    while ($null -eq $adapter -and (Get-Date) -lt $adapterDeadline) {
        $candidateAdapters = @(
            Get-NetAdapter -IncludeHidden |
                Where-Object {
                    $_.Status -eq "Up" -and
                    ($_.MacAddress -replace "[:-]", "") -eq "020000000002"
                }
        )
        if ($candidateAdapters.Count -gt 1) {
            throw "Multiple adapters match the test gadget; refusing ambiguous configuration."
        }
        if ($candidateAdapters.Count -eq 1) {
            $candidate = $candidateAdapters[0]
            Assert-GadgetUsbPort $candidate $targetPorts
            $adapter = $candidate
        }
        if ($null -eq $adapter) {
            Start-Sleep -Seconds 1
        }
    }
    if ($null -eq $adapter) {
        Get-PnpDevice -PresentOnly |
            Where-Object { $_.InstanceId -match "^USB\\" } |
            Select-Object Status, Class, FriendlyName, InstanceId |
            ConvertTo-Json -Depth 4 |
            Set-Content -LiteralPath (Join-Path $LogDirectory "usb-after-timeout.json")
        throw "The USB RNDIS adapter did not appear after fastboot boot."
    }

    $originalDhcp = (Get-NetIPInterface -InterfaceIndex $adapter.ifIndex `
        -AddressFamily IPv4 -PolicyStore ActiveStore).Dhcp
    $addressAttempted = $true
    New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $BindAddress `
        -PrefixLength 24 -AddressFamily IPv4 -PolicyStore ActiveStore | Out-Null
    $addedAddress = $true
    Assert-GadgetRoute $adapter $DeviceAddress
    $firewallRule = New-NetFirewallRule -DisplayName $firewallRuleName `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
        -LocalAddress $BindAddress -RemoteAddress $DeviceAddress `
        -InterfaceAlias $adapter.Name -Profile Any -PolicyStore PersistentStore

    @{
        interface_guid = $adapter.InterfaceGuid.ToString()
        host_address = $BindAddress
        original_dhcp = "$originalDhcp"
        usb_port_verified = $true
        firewall_rule = $firewallRuleName
        nbd_started = $true
        ready = (Get-Date).ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogDirectory "ready.json")

    Write-Host "Using USB adapter '$($adapter.Name)' at $BindAddress."
    Write-Host "fastboot boot returned. Observing for at least $ServeSeconds seconds."
    Write-Host "The tablet should connect to $BindAddress`:$Port after RNDIS enumerates."
    $deadline = (Get-Date).AddSeconds($ServeSeconds)
    while ($true) {
        if ($serverProcess.HasExited) {
            throw "NBD server exited while the tablet was booting."
        }
        try {
            # Enumerate before filtering: a CIM failure is not a disconnect.
            $connections = @(Get-NetTCPConnection -ErrorAction Stop | Where-Object {
                $_.LocalPort -eq $Port -and $_.RemoteAddress -eq $DeviceAddress -and
                $_.State -eq "Established"
            })
            $online = @(Get-NetAdapter -IncludeHidden -ErrorAction Stop | Where-Object {
                $_.InterfaceGuid -eq $adapter.InterfaceGuid -and $_.Status -eq "Up"
            })
            if ((Get-Date) -ge $deadline -and $connections.Count -eq 0 -and $online.Count -eq 0) {
                $disconnectVerified = $true
                break
            }
        } catch {
            Write-Warning "Cannot verify USB/NBD disconnect; keeping the rootfs server alive: $_"
        }
        Start-Sleep -Seconds 1
    }
}
finally {
    if ($bootRequested -and -not $disconnectVerified -and
        $null -ne $serverProcess -and -not $serverProcess.HasExited) {
        @{
            complete = $false
            rootfs_server_preserved = $true
            server_pid = $serverProcess.Id
            error = "Boot was requested but disconnect is unverified; network and NBD retained."
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogDirectory "cleanup.json")
        Stop-Transcript | Out-Null
        throw "NBD may still back the tablet rootfs; preserved the server and networking. Inspect private logs."
    }
    $cleanup = @{
        complete = $true
        address_added = $addedAddress
        address_attempted = $addressAttempted
    }
    if ($null -ne $serverProcess -and -not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force
    }
    if ($null -ne $adapter) {
        $cleanup.interface_guid = $adapter.InterfaceGuid.ToString()
        $cleanup.original_dhcp = "$originalDhcp"
        try {
            $current = @(Get-NetAdapter -IncludeHidden | Where-Object {
                $_.InterfaceGuid -eq $adapter.InterfaceGuid
            })
            if ($current.Count -ne 1) {
                throw "Recorded gadget cannot be enumerated; cleanup is unverified."
            }
            $index = $current[0].ifIndex
            if ($addressAttempted) {
                Get-NetIPAddress -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop |
                    Where-Object { $_.InterfaceIndex -eq $index -and $_.IPAddress -eq $BindAddress } |
                    Remove-NetIPAddress -Confirm:$false -ErrorAction Stop
                if (Get-NetIPAddress -AddressFamily IPv4 -PolicyStore ActiveStore -ErrorAction Stop |
                    Where-Object { $_.InterfaceIndex -eq $index -and $_.IPAddress -eq $BindAddress }) {
                    throw "Temporary USB address remains."
                }
            }
            if ($null -ne $originalDhcp) {
                Set-NetIPInterface -InterfaceIndex $index -AddressFamily IPv4 `
                    -Dhcp $originalDhcp -PolicyStore ActiveStore -ErrorAction Stop
                if ((Get-NetIPInterface -InterfaceIndex $index -AddressFamily IPv4 `
                    -PolicyStore ActiveStore).Dhcp -ne $originalDhcp) {
                    throw "Original DHCP state has not been restored."
                }
            }
        } catch {
            $cleanup.complete = $false
            $cleanup.error = "$_"
        }
    }
    if ($null -ne $firewallRule) {
        try {
            Remove-NetFirewallRule -InputObject $firewallRule -ErrorAction Stop
        } catch {
            $cleanup.complete = $false
            $cleanup.firewall_error = "$_"
        }
    }
    $cleanup | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogDirectory "cleanup.json")
    Stop-Transcript | Out-Null
    if (-not $cleanup.complete) {
        throw "USB cleanup remains unverified for the recorded GUID; see cleanup.json."
    }
}

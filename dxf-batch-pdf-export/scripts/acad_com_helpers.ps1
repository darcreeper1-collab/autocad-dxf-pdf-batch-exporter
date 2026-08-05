<#
Shared, testable helpers for AutoCAD COM automation.

They retry only known transient server-busy HRESULTs, wait for
AcadState.IsQuiescent when AutoCAD exposes it, and retain structured retry
telemetry for the caller. They never create, hide, quit, or alter AutoCAD by
themselves.
#>

$script:AcadComLogSink = $null

function Set-AcadComLogSink {
    param([object]$Sink)
    $script:AcadComLogSink = $Sink
}

function Add-AcadComEvent {
    param(
        [string]$Operation,
        [string]$Event,
        [int]$Attempt = 0,
        [string]$Message = ""
    )
    $record = [ordered]@{
        timestamp = (Get-Date).ToString("o")
        operation = $Operation
        event = $Event
        attempt = $Attempt
        message = $Message
    }
    if ($null -ne $script:AcadComLogSink) {
        try { [void]$script:AcadComLogSink.Add([pscustomobject]$record) } catch {}
    }
    Write-Verbose ("AutoCAD COM [{0}] {1} attempt={2}: {3}" -f $Event, $Operation, $Attempt, $Message)
}

function Get-ExceptionChain {
    param([Parameter(Mandatory = $true)][System.Exception]$Exception)
    $items = @()
    $current = $Exception
    while ($null -ne $current) {
        $items += $current
        $current = $current.InnerException
    }
    return $items
}

function Test-AcadTransientComError {
    param([Parameter(Mandatory = $true)][System.Exception]$Exception)

    # RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER and the server-side
    # rejected-call variant normally occur while AutoCAD starts, loads, plots,
    # or is waiting on a modal operation.
    $busyHresults = @(
        [Convert]::ToUInt32("80010001", 16),
        [Convert]::ToUInt32("8001010A", 16),
        [Convert]::ToUInt32("8001010B", 16)
    )
    foreach ($item in Get-ExceptionChain -Exception $Exception) {
        $hresult = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int]$item.HResult), 0)
        if ($busyHresults -contains $hresult) {
            return $true
        }
        $message = [string]$item.Message
        if ($message -match "RPC_E_CALL_REJECTED|RPC_E_SERVERCALL_RETRYLATER|server call retry later|call was rejected by callee") {
            return $true
        }
    }
    return $false
}

function Get-AcadProgIdCandidates {
    param([string[]]$CandidateProgIds = @())

    if ($CandidateProgIds.Count -gt 0) {
        return @($CandidateProgIds | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    }

    $candidates = New-Object System.Collections.Generic.List[string]
    try {
        $curVer = (Get-ItemProperty -LiteralPath "Registry::HKEY_CLASSES_ROOT\AutoCAD.Application" -Name "CurVer" -ErrorAction Stop).CurVer
        if (-not [string]::IsNullOrWhiteSpace($curVer)) { $candidates.Add([string]$curVer) }
    } catch {}
    foreach ($root in @("Registry::HKEY_CLASSES_ROOT", "Registry::HKEY_CLASSES_ROOT\Wow6432Node")) {
        try {
            Get-ChildItem -LiteralPath $root -ErrorAction Stop |
                Where-Object { $_.PSChildName -match "^AutoCAD\.Application\.\d+(\.\d+)?$" } |
                ForEach-Object { $candidates.Add([string]$_.PSChildName) }
        } catch {}
    }
    return @($candidates | Select-Object -Unique)
}

function Get-AcadProgIdRank {
    param([string]$ProgId)
    if ($ProgId -match "^AutoCAD\.Application\.(\d+)(?:\.(\d+))?$") {
        $minor = [decimal]0
        if ($matches.Count -gt 2 -and -not [string]::IsNullOrWhiteSpace($matches[2])) {
            $minor = [decimal]$matches[2] / 100
        }
        return ([decimal]$matches[1]) + $minor
    }
    return [decimal]0
}

function Resolve-AcadProgId {
    param(
        [string]$AutoCadProgId = "",
        [string[]]$CandidateProgIds = @()
    )
    if (-not [string]::IsNullOrWhiteSpace($AutoCadProgId) -and $AutoCadProgId -ne "auto") {
        return $AutoCadProgId
    }
    $candidates = Get-AcadProgIdCandidates -CandidateProgIds $CandidateProgIds
    $valid = @($candidates | Where-Object { $_ -match "^AutoCAD\.Application\.\d+(\.\d+)?$" })
    if ($valid.Count -eq 0) {
        throw "Could not discover an installed AutoCAD COM ProgID. Pass -AutoCadProgId explicitly, for example AutoCAD.Application.24."
    }
    return @($valid | Sort-Object @{ Expression = { Get-AcadProgIdRank $_ }; Descending = $true }, @{ Expression = { $_ }; Descending = $true } | Select-Object -First 1)[0]
}

function Wait-AcadReady {
    param(
        [Parameter(Mandatory = $true)][object]$Acad,
        [string]$Operation = "Wait for AutoCAD idle",
        [int]$TimeoutSeconds = 120,
        [int]$PollMilliseconds = 250
    )

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    $attempt = 0
    $sawState = $false
    while ((Get-Date) -lt $deadline) {
        $attempt++
        try {
            $state = $Acad.GetAcadState()
            $sawState = $true
            $isQuiescent = [bool]$state.IsQuiescent
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($state) } catch {}
            if ($isQuiescent) {
                if ($attempt -gt 1) { Add-AcadComEvent -Operation $Operation -Event "ready" -Attempt $attempt -Message "AcadState.IsQuiescent=true" }
                return
            }
            Add-AcadComEvent -Operation $Operation -Event "busy" -Attempt $attempt -Message "AcadState.IsQuiescent=false"
        } catch {
            if (Test-AcadTransientComError -Exception $_.Exception) {
                Add-AcadComEvent -Operation $Operation -Event "busy" -Attempt $attempt -Message $_.Exception.Message
            } elseif (-not $sawState) {
                # Some older AutoCAD COM APIs omit this optional probe. The
                # operation itself remains protected by Invoke-AcadComRetry.
                Add-AcadComEvent -Operation $Operation -Event "state-unavailable" -Attempt $attempt -Message $_.Exception.Message
                return
            } else {
                throw
            }
        }
        Start-Sleep -Milliseconds ([Math]::Max(25, $PollMilliseconds))
    }
    throw [TimeoutException]::new("Timed out after $TimeoutSeconds second(s) waiting for AutoCAD to become idle before $Operation.")
}

function Invoke-AcadComRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Operation,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [object]$Acad = $null,
        [int]$TimeoutSeconds = 120,
        [int]$InitialDelayMilliseconds = 250,
        [int]$MaxDelayMilliseconds = 3000,
        [switch]$SkipIdleWait
    )

    $timeout = [Math]::Max(1, $TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($timeout)
    $delay = [Math]::Max(25, $InitialDelayMilliseconds)
    $attempt = 0
    while ($true) {
        $attempt++
        try {
            if ($null -ne $Acad -and -not $SkipIdleWait) {
                $remaining = [Math]::Max(1, [int][Math]::Ceiling(($deadline - (Get-Date)).TotalSeconds))
                Wait-AcadReady -Acad $Acad -Operation $Operation -TimeoutSeconds $remaining -PollMilliseconds ([Math]::Min(250, $delay))
            }
            return (& $Action)
        } catch {
            $exception = $_.Exception
            if (-not (Test-AcadTransientComError -Exception $exception)) {
                Add-AcadComEvent -Operation $Operation -Event "failed" -Attempt $attempt -Message $exception.Message
                throw
            }
            if ((Get-Date) -ge $deadline) {
                $message = "Timed out after $timeout second(s) during $Operation after $attempt COM attempt(s): $($exception.Message)"
                Add-AcadComEvent -Operation $Operation -Event "timeout" -Attempt $attempt -Message $message
                throw [TimeoutException]::new($message, $exception)
            }
            Add-AcadComEvent -Operation $Operation -Event "retry" -Attempt $attempt -Message ("{0}; retrying in {1} ms" -f $exception.Message, $delay)
            Start-Sleep -Milliseconds $delay
            $delay = [Math]::Min([Math]::Max($delay * 2, 25), [Math]::Max(25, $MaxDelayMilliseconds))
        }
    }
}

function Resolve-DrawingInputRoute {
    param(
        [Parameter(Mandatory = $true)][string]$InputPath,
        [Parameter(Mandatory = $true)][string]$WorkDir
    )
    $source = [IO.Path]::GetFullPath($InputPath)
    $extension = [IO.Path]::GetExtension($source).ToLowerInvariant()
    if ($extension -notin @(".dxf", ".dwg")) {
        throw "Input must be a DXF or DWG file: $source"
    }
    if ($extension -eq ".dxf") {
        return [ordered]@{
            sourceInput = $source
            sourceFormat = "DXF"
            workingDxfCopy = $null
            detectionInput = $source
            preflightInput = $source
            plotInput = $source
            requiresDxfMirror = $false
            sourceModified = $false
        }
    }
    $mirrorDir = Join-Path ([IO.Path]::GetFullPath($WorkDir)) "input_mirror"
    $mirrorName = "{0}_diagnostic.dxf" -f [IO.Path]::GetFileNameWithoutExtension($source)
    $mirror = Join-Path $mirrorDir $mirrorName
    return [ordered]@{
        sourceInput = $source
        sourceFormat = "DWG"
        workingDxfCopy = $mirror
        detectionInput = $mirror
        preflightInput = $mirror
        plotInput = $source
        requiresDxfMirror = $true
        sourceModified = $false
    }
}

function Release-AcadComObject {
    param([object]$ComObject)
    if ($null -ne $ComObject) {
        try {
            if ([Runtime.InteropServices.Marshal]::IsComObject($ComObject)) {
                [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($ComObject)
            }
        } catch {}
    }
}
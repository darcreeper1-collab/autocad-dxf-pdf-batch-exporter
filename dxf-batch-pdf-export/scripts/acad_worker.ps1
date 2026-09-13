<# A process boundary is required: a synchronous COM call cannot time itself out. #>

function Write-AcadWorkerProgress {
    param([string]$Operation)
    if ($script:AcadWorkerStatePath) {
        [IO.File]::WriteAllText($script:AcadWorkerStatePath, $Operation, [Text.Encoding]::UTF8)
    }
}

function Initialize-AcadRecoveryApi {
    if ('AcadRecovery.Native' -as [type]) { return }
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace AcadRecovery {
  public static class Native {
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hwnd, int command);
  }
}
"@
}

function Register-OwnedAcadWindow {
    param([long]$Handle)
    if (-not $script:AcadWorkerStatePath) { return }
    Initialize-AcadRecoveryApi
    [uint32]$ownerId = 0
    [void][AcadRecovery.Native]::GetWindowThreadProcessId([IntPtr]$Handle, [ref]$ownerId)
    if (-not $ownerId) { throw 'Cannot identify owned AutoCAD window; refusing to hide it.' }
    $owner = Get-Process -Id $ownerId -ErrorAction Stop
    @{ handle = $Handle; pid = $ownerId; startTicks = $owner.StartTime.ToUniversalTime().Ticks } |
        ConvertTo-Json | Set-Content -LiteralPath ($script:AcadWorkerStatePath + '.owner.json') -Encoding UTF8
}

function Restore-OwnedAcadWindow {
    param([string]$StatePath)
    $ownerPath = $StatePath + '.owner.json'
    if (-not (Test-Path -LiteralPath $ownerPath)) { return }
    try {
        $identity = Get-Content -LiteralPath $ownerPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $owner = Get-Process -Id $identity.pid -ErrorAction Stop
        if ($owner.StartTime.ToUniversalTime().Ticks -ne $identity.startTicks) { return }
        Initialize-AcadRecoveryApi
        [uint32]$windowOwner = 0
        [void][AcadRecovery.Native]::GetWindowThreadProcessId([IntPtr][long]$identity.handle, [ref]$windowOwner)
        if ($windowOwner -ne $identity.pid) { return }
        [void][AcadRecovery.Native]::ShowWindowAsync([IntPtr][long]$identity.handle, 5)
        Write-Warning "Owned AutoCAD process $($identity.pid) remains open; its window was requested visible for manual recovery."
    } catch { Write-Verbose "Recovery window unavailable: $($_.Exception.Message)" }
}

function Invoke-AcadSupervisedScript {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Parameters,
        [Parameter(Mandatory = $true)][string]$LogRoot,
        [ValidateRange(1, 86400)][int]$TimeoutSeconds = 300
    )
    $runDir = Join-Path ([IO.Path]::GetFullPath($LogRoot)) ('.acad-worker/' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null
    $statePath = Join-Path $runDir 'operation.txt'
    $paramsPath = Join-Path $runDir 'parameters.clixml'
    $stdout = Join-Path $runDir 'stdout.log'
    $stderr = Join-Path $runDir 'stderr.log'
    $copy = @{}
    foreach ($key in $Parameters.Keys) { $copy[$key] = $Parameters[$key] }
    $copy.WorkerMode = $true
    $copy.WorkerStatePath = $statePath
    $copy | Export-Clixml -LiteralPath $paramsPath
    $quotedScript = $ScriptPath.Replace("'", "''")
    $quotedParams = $paramsPath.Replace("'", "''")
    $command = @"
`$ErrorActionPreference = 'Stop'
`$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new(`$false)
try {
    `$arguments = Import-Clixml -LiteralPath '$quotedParams'
    & '$quotedScript' @arguments
    exit 0
} catch {
    [Console]::Error.WriteLine(`$_.ToString() + [Environment]::NewLine + `$_.ScriptStackTrace)
    exit 1
}
"@
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $hostExe = Join-Path $PSHOME 'powershell.exe'
    if (-not (Test-Path -LiteralPath $hostExe)) { $hostExe = Join-Path $PSHOME 'pwsh.exe' }
    $worker = $null
    try {
        $worker = Start-Process -FilePath $hostExe -ArgumentList @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded) `
            -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        # Retain the native handle before exit; PS 5.1 may otherwise lose ExitCode.
        $null = $worker.Handle
        $lastProgress = [DateTime]::UtcNow
        $operation = 'Worker startup / COM activation'
        while (-not $worker.WaitForExit(200)) {
            if (Test-Path -LiteralPath $statePath) {
                try {
                    $stamp = (Get-Item -LiteralPath $statePath).LastWriteTimeUtc
                    if ($stamp -gt $lastProgress) { $lastProgress = $stamp }
                    $operation = [IO.File]::ReadAllText($statePath)
                } catch { }
            }
            if (([DateTime]::UtcNow - $lastProgress).TotalSeconds -gt $TimeoutSeconds) {
                $message = "AutoCAD worker timeout after $TimeoutSeconds seconds without progress during: $operation. Logs: $runDir. Only the owned PowerShell worker is stopped; AutoCAD is NOT killed. Inspect modal dialogs and residual AutoCAD instances before retrying."
                $message | Set-Content -LiteralPath (Join-Path $runDir 'timeout.txt') -Encoding UTF8
                throw [TimeoutException]::new($message)
            }
        }
        $worker.WaitForExit()
        if ($worker.ExitCode -ne 0) {
            throw "AutoCAD worker failed (exit $($worker.ExitCode)). Logs: $runDir`n$([IO.File]::ReadAllText($stderr))"
        }
        [IO.File]::ReadAllText($stdout)
    } finally {
        if ($null -ne $worker) {
            if (-not $worker.HasExited) {
                $worker.Kill()
                [void]$worker.WaitForExit(5000)
            }
            Restore-OwnedAcadWindow -StatePath $statePath
            $worker.Dispose()
        }
    }
}

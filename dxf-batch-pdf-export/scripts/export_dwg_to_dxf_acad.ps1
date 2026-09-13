<#
Create a diagnostic DXF mirror of a source DWG without modifying the DWG.

The mirror is for text preflight and frame-window detection only. The controller
continues to plot the original DWG, preserving the source drawing's fidelity.
#>

param(
    [Parameter(Mandatory = $true)][string]$InputDwg,
    [Parameter(Mandatory = $true)][string]$OutputDxf,
    [string]$AutoCadProgId = "",
    [int]$ReuseExistingAutoCAD = 0,
    [int]$ComTimeoutSeconds = 120,
    [ValidateRange(1, 86400)][int]$ComCallTimeoutSeconds = 300,
    [switch]$WorkerMode,
    [string]$WorkerStatePath = '',
    [int]$ComInitialDelayMilliseconds = 250,
    [int]$ComMaxDelayMilliseconds = 3000,
    [int]$DxfSaveAsFormat = -1
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptRoot "acad_com_helpers.ps1")
if (-not $WorkerMode) {
    Invoke-AcadSupervisedScript -ScriptPath $PSCommandPath -Parameters $PSBoundParameters -LogRoot (Split-Path -Parent ([IO.Path]::GetFullPath($OutputDxf))) -TimeoutSeconds $ComCallTimeoutSeconds
    return
}
$script:AcadWorkerStatePath = $WorkerStatePath
$events = New-Object System.Collections.Generic.List[object]
Set-AcadComLogSink -Sink $events

function Invoke-ConversionCom {
    param([string]$Operation, [scriptblock]$Action, [object]$Acad = $null, [switch]$SkipIdleWait, [int]$TimeoutSeconds = 0)
    if ($TimeoutSeconds -le 0) { $TimeoutSeconds = $ComTimeoutSeconds }
    return Invoke-AcadComRetry -Operation $Operation -Action $Action -Acad $Acad -TimeoutSeconds $TimeoutSeconds `
        -InitialDelayMilliseconds $ComInitialDelayMilliseconds -MaxDelayMilliseconds $ComMaxDelayMilliseconds -SkipIdleWait:$SkipIdleWait
}

$source = (Resolve-Path -LiteralPath $InputDwg).Path
if ([IO.Path]::GetExtension($source).ToLowerInvariant() -ne ".dwg") { throw "InputDwg must have a .dwg extension: $source" }
$output = [IO.Path]::GetFullPath($OutputDxf)
if ([IO.Path]::GetExtension($output).ToLowerInvariant() -ne ".dxf") { throw "OutputDxf must have a .dxf extension: $output" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $output) | Out-Null
if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Force }

$acad = $null
$doc = $null
$created = $false
$resolvedProgId = ""
$reportedVersion = ""
try {
    $resolvedProgId = Resolve-AcadProgId -AutoCadProgId $AutoCadProgId
    if ($ReuseExistingAutoCAD) {
        $acad = Invoke-ConversionCom -Operation "GetActiveObject $resolvedProgId" -SkipIdleWait -Action { [Runtime.InteropServices.Marshal]::GetActiveObject($resolvedProgId) }
        Add-AcadComEvent -Operation "AutoCAD instance" -Event "reused-explicitly" -Message $resolvedProgId
    } else {
        $acad = Invoke-ConversionCom -Operation "Create AutoCAD instance $resolvedProgId" -SkipIdleWait -Action { New-Object -ComObject $resolvedProgId }
        $created = $true
        Add-AcadComEvent -Operation "AutoCAD instance" -Event "created-owned" -Message $resolvedProgId
        $ownedHandle = Invoke-ConversionCom -Operation 'Identify owned AutoCAD window' -Acad $acad -Action { $acad.HWND }
        Register-OwnedAcadWindow -Handle $ownedHandle
        [void](Invoke-ConversionCom -Operation "Hide owned AutoCAD instance" -Acad $acad -Action { $acad.Visible = $false })
        [void](Invoke-ConversionCom -Operation "Disable alerts on owned AutoCAD instance" -Acad $acad -Action { $acad.DisplayAlerts = $false })
    }
    try { $reportedVersion = [string](Invoke-ConversionCom -Operation "Read AutoCAD version" -Acad $acad -Action { $acad.Version }) } catch { $reportedVersion = "unavailable" }
    $doc = Invoke-ConversionCom -Operation "Documents.Open $source" -Acad $acad -Action { $acad.Documents.Open($source) }
    if ($DxfSaveAsFormat -ge 0) {
        [void](Invoke-ConversionCom -Operation "Save diagnostic DXF mirror" -Acad $acad -Action { $doc.SaveAs($output, $DxfSaveAsFormat) })
    } else {
        # AutoCAD selects the drawing type from the .dxf target extension.
        [void](Invoke-ConversionCom -Operation "Save diagnostic DXF mirror" -Acad $acad -Action { $doc.SaveAs($output) })
    }
    if (-not (Test-Path -LiteralPath $output) -or (Get-Item -LiteralPath $output).Length -le 0) { throw "AutoCAD did not create the diagnostic DXF mirror: $output" }
    $prefix = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($output), 0, [Math]::Min(4096, (Get-Item -LiteralPath $output).Length))
    if ($prefix.IndexOf("SECTION", [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "AutoCAD created a non-text DXF mirror. Use -DxfSaveAsFormat with a supported DXF AcSaveAsType for this AutoCAD release."
    }
} finally {
    if ($null -ne $doc) {
        try { [void](Invoke-ConversionCom -Operation "Close DWG conversion document" -Acad $acad -TimeoutSeconds 30 -Action { $doc.Close($false) }) } catch { Add-AcadComEvent -Operation "Close DWG conversion document" -Event "cleanup-failed" -Message $_.Exception.Message }
    }
    Release-AcadComObject $doc
    if ($created -and $null -ne $acad) {
        try { [void](Invoke-ConversionCom -Operation "Quit owned AutoCAD instance" -Acad $acad -TimeoutSeconds 30 -Action { $acad.Quit() }) } catch { Add-AcadComEvent -Operation "Quit owned AutoCAD instance" -Event "cleanup-failed" -Message $_.Exception.Message }
    }
    Release-AcadComObject $acad
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

[ordered]@{
    schemaVersion = 1
    sourceDwg = $source
    diagnosticDxf = $output
    sourceModified = $false
    autoCad = [ordered]@{ requestedProgId = $AutoCadProgId; resolvedProgId = $resolvedProgId; reportedVersion = $reportedVersion; reuseExistingExplicitly = [bool]$ReuseExistingAutoCAD; instanceOwnership = $(if ($created) { "created-owned" } else { "reused-user-instance" }); cleanupFailed = [bool](@($events | Where-Object { $_.event -eq 'cleanup-failed' }).Count) }
    comEvents = @($events)
    status = "ok"
} | ConvertTo-Json -Depth 10

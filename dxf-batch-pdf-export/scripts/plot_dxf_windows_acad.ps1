<#
AutoCAD COM plotter for one-window-per-page PDF export.

By default this script creates an independent hidden AutoCAD instance. It never
attaches to, hides, closes, or changes a user's existing AutoCAD session unless
-ReuseExistingAutoCAD 1 is explicitly supplied. All COM operations that can be
busy are routed through bounded retry and idle-wait helpers.
#>

param(
    [Parameter(Mandatory = $true)]
    [Alias("InputDrawing")]
    [string]$InputDxf,

    [Parameter(Mandatory = $true)]
    [string]$WindowsJson,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [string]$AutoCadProgId = "",
    [int]$ReuseExistingAutoCAD = 0,
    [int]$ComTimeoutSeconds = 120,
    [int]$ComInitialDelayMilliseconds = 250,
    [int]$ComMaxDelayMilliseconds = 3000,

    [string]$DeviceName = "DWG To PDF.pc3",
    [string]$MediaName = "ISO_full_bleed_A1_(841.00_x_594.00_MM)",
    [int]$PlotRotation = 0,
    [int]$MaxPages = 0,
    [int]$SuppressViewerWindows = 1,
    [int]$ViewerSuppressSeconds = 3,
    [string]$IntermediateExtension = ".codexplot"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptRoot "acad_com_helpers.ps1")

$comEvents = New-Object System.Collections.Generic.List[object]
$layoutWarnings = New-Object System.Collections.Generic.List[string]
Set-AcadComLogSink -Sink $comEvents

function Invoke-PlotCom {
    param(
        [Parameter(Mandatory = $true)][string]$Operation,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [object]$Acad = $null,
        [switch]$SkipIdleWait,
        [int]$TimeoutSeconds = 0
    )
    if ($TimeoutSeconds -le 0) { $TimeoutSeconds = $ComTimeoutSeconds }
    return Invoke-AcadComRetry -Operation $Operation -Action $Action -Acad $Acad `
        -TimeoutSeconds $TimeoutSeconds -InitialDelayMilliseconds $ComInitialDelayMilliseconds `
        -MaxDelayMilliseconds $ComMaxDelayMilliseconds -SkipIdleWait:$SkipIdleWait
}

function Set-SysVarSafe {
    param([object]$Document, [string]$Name, [object]$Value, [object]$Acad)
    foreach ($attemptValue in @($Value, [int16]$Value, [int32]$Value, [double]$Value)) {
        try {
            [void](Invoke-PlotCom -Operation "SetVariable $Name" -Acad $Acad -Action { $Document.SetVariable($Name, $attemptValue) })
            return $true
        } catch {}
    }
    $layoutWarnings.Add("Could not set drawing variable $Name.")
    return $false
}

function Set-PropSafe {
    param([object]$Object, [string]$Name, [object]$Value, [object]$Acad)
    try {
        [void](Invoke-PlotCom -Operation "Set property $Name" -Acad $Acad -Action { $Object.$Name = $Value })
        return $true
    } catch {
        $layoutWarnings.Add("Could not set ${Name}: $($_.Exception.Message)")
        return $false
    }
}

function Wait-ForFile {
    param([string]$Path, [int]$TimeoutSeconds = 180)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $Path) {
            try {
                if ((Get-Item -LiteralPath $Path).Length -gt 0) { return $true }
            } catch {}
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Initialize-WindowApi {
    if ("CodexWindowApi.NativeMethods" -as [type]) { return }
    Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
namespace CodexWindowApi {
  public static class NativeMethods {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
    [DllImport("user32.dll", SetLastError=true)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll", SetLastError=true)] public static extern int GetWindowTextLength(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int command);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, int message, IntPtr wParam, IntPtr lParam);
  }
}
"@
}

function Close-GeneratedPdfViewerWindows {
    param([string[]]$PdfPaths, [int]$Seconds = 3)
    if (-not $SuppressViewerWindows) { return @() }
    Initialize-WindowApi
    $names = @($PdfPaths | ForEach-Object { [IO.Path]::GetFileName($_); [IO.Path]::GetFileNameWithoutExtension($_) } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    $closed = @()
    $deadline = (Get-Date).AddSeconds([Math]::Max(0, $Seconds))
    $callback = [CodexWindowApi.NativeMethods+EnumWindowsProc]{
        param([IntPtr]$hWnd, [IntPtr]$lParam)
        if (-not [CodexWindowApi.NativeMethods]::IsWindowVisible($hWnd)) { return $true }
        $length = [CodexWindowApi.NativeMethods]::GetWindowTextLength($hWnd)
        if ($length -le 0) { return $true }
        $builder = New-Object System.Text.StringBuilder ($length + 1)
        [void][CodexWindowApi.NativeMethods]::GetWindowText($hWnd, $builder, $builder.Capacity)
        $title = $builder.ToString()
        foreach ($name in $script:viewerNames) {
            if ($title.IndexOf($name, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                [void][CodexWindowApi.NativeMethods]::ShowWindow($hWnd, 6)
                [void][CodexWindowApi.NativeMethods]::SendMessage($hWnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
                $script:viewerClosed.Add([ordered]@{ title = $title; matchedByTitle = $true })
                break
            }
        }
        return $true
    }
    do {
        $script:viewerNames = $names
        $script:viewerClosed = New-Object System.Collections.Generic.List[object]
        [void][CodexWindowApi.NativeMethods]::EnumWindows($callback, [IntPtr]::Zero)
        $closed += @($script:viewerClosed)
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    return @($closed)
}

$resolvedInput = (Resolve-Path -LiteralPath $InputDxf).Path
$resolvedJson = (Resolve-Path -LiteralPath $WindowsJson).Path
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$config = Get-Content -LiteralPath $resolvedJson -Encoding UTF8 | ConvertFrom-Json
$frames = @($config.frames)
if ($frames.Count -eq 0) { throw "No frame windows found in $resolvedJson" }
if ($MaxPages -gt 0) { $frames = @($frames | Sort-Object { [int]$_.page } | Select-Object -First $MaxPages) }

$acad = $null
$doc = $null
$layout = $null
$plot = $null
$createdAcad = $false
$resolvedProgId = ""
$reportedVersion = ""
$results = @()

try {
    $resolvedProgId = Resolve-AcadProgId -AutoCadProgId $AutoCadProgId
    if ($ReuseExistingAutoCAD) {
        $acad = Invoke-PlotCom -Operation "GetActiveObject $resolvedProgId" -SkipIdleWait -Action {
            [Runtime.InteropServices.Marshal]::GetActiveObject($resolvedProgId)
        }
        Add-AcadComEvent -Operation "AutoCAD instance" -Event "reused-explicitly" -Message $resolvedProgId
    } else {
        $acad = Invoke-PlotCom -Operation "Create AutoCAD instance $resolvedProgId" -SkipIdleWait -Action {
            New-Object -ComObject $resolvedProgId
        }
        $createdAcad = $true
        Add-AcadComEvent -Operation "AutoCAD instance" -Event "created-owned" -Message $resolvedProgId
        [void](Invoke-PlotCom -Operation "Hide owned AutoCAD instance" -Acad $acad -Action { $acad.Visible = $false })
        [void](Invoke-PlotCom -Operation "Disable alerts on owned AutoCAD instance" -Acad $acad -Action { $acad.DisplayAlerts = $false })
    }
    try { $reportedVersion = [string](Invoke-PlotCom -Operation "Read AutoCAD version" -Acad $acad -Action { $acad.Version }) } catch { $reportedVersion = "unavailable" }

    $doc = Invoke-PlotCom -Operation "Documents.Open $resolvedInput" -Acad $acad -Action { $acad.Documents.Open($resolvedInput) }
    $null = Set-SysVarSafe -Document $doc -Name "BACKGROUNDPLOT" -Value 0 -Acad $acad
    $null = Set-SysVarSafe -Document $doc -Name "FILEDIA" -Value 0 -Acad $acad
    $null = Set-SysVarSafe -Document $doc -Name "CMDDIA" -Value 0 -Acad $acad
    $null = Set-SysVarSafe -Document $doc -Name "EXPERT" -Value 5 -Acad $acad
    $null = Set-SysVarSafe -Document $doc -Name "PUBLISHCOLLATE" -Value 0 -Acad $acad
    $null = Set-SysVarSafe -Document $doc -Name "PDFSHX" -Value 0 -Acad $acad
    $null = Set-SysVarSafe -Document $doc -Name "EPDFSHX" -Value 0 -Acad $acad
    $null = Set-SysVarSafe -Document $doc -Name "PDFSHXTEXT" -Value 0 -Acad $acad
    $null = Set-SysVarSafe -Document $doc -Name "PUBLISHOPEN" -Value 0 -Acad $acad
    $null = Set-SysVarSafe -Document $doc -Name "PUBLISHVIEW" -Value 0 -Acad $acad
    $null = Set-SysVarSafe -Document $doc -Name "PLOTNOTIFY" -Value 0 -Acad $acad
    $null = Set-SysVarSafe -Document $doc -Name "VIEWPLOTDETAILS" -Value 0 -Acad $acad

    $plot = Invoke-PlotCom -Operation "Access Plot object" -Acad $acad -Action { $doc.Plot }
    [void](Set-PropSafe -Object $plot -Name "QuietErrorMode" -Value $true -Acad $acad)
    $layout = Invoke-PlotCom -Operation "Access Model layout" -Acad $acad -Action { $doc.Layouts.Item("Model") }
    [void](Invoke-PlotCom -Operation "Activate Model layout" -Acad $acad -Action { $doc.ActiveLayout = $layout })
    try { [void](Invoke-PlotCom -Operation "Set model space" -Acad $acad -Action { $doc.ActiveSpace = 1 }) } catch { $layoutWarnings.Add("Could not activate model space: $($_.Exception.Message)") }
    [void](Set-PropSafe -Object $layout -Name "ConfigName" -Value $DeviceName -Acad $acad)
    try { [void](Invoke-PlotCom -Operation "Refresh plot device info" -Acad $acad -Action { $layout.RefreshPlotDeviceInfo() }) } catch { $layoutWarnings.Add("Could not refresh plot device: $($_.Exception.Message)") }
    [void](Set-PropSafe -Object $layout -Name "PaperUnits" -Value 1 -Acad $acad)
    [void](Set-PropSafe -Object $layout -Name "CanonicalMediaName" -Value $MediaName -Acad $acad)
    [void](Set-PropSafe -Object $layout -Name "PlotType" -Value 4 -Acad $acad)
    [void](Set-PropSafe -Object $layout -Name "CenterPlot" -Value $true -Acad $acad)
    [void](Set-PropSafe -Object $layout -Name "UseStandardScale" -Value $true -Acad $acad)
    [void](Set-PropSafe -Object $layout -Name "StandardScale" -Value 0 -Acad $acad)
    [void](Set-PropSafe -Object $layout -Name "PlotRotation" -Value $PlotRotation -Acad $acad)
    [void](Set-PropSafe -Object $layout -Name "PlotWithPlotStyles" -Value $false -Acad $acad)
    [void](Set-PropSafe -Object $layout -Name "PlotWithLineweights" -Value $true -Acad $acad)
    [void](Set-PropSafe -Object $layout -Name "ScaleLineweights" -Value $false -Acad $acad)
    [void](Set-PropSafe -Object $layout -Name "ShowPlotStyles" -Value $false -Acad $acad)
    [void](Set-PropSafe -Object $layout -Name "PlotHidden" -Value $false -Acad $acad)

    foreach ($frame in $frames) {
        $page = [int]$frame.page
        $window = @($frame.window)
        $lowerLeft = [double[]]@([double]$window[0], [double]$window[1])
        $upperRight = [double[]]@([double]$window[2], [double]$window[3])
        $pdfPath = Join-Path $OutputDir ("page_{0:D3}.pdf" -f $page)
        $extension = if ([string]::IsNullOrWhiteSpace($IntermediateExtension)) { ".pdf" } else { $IntermediateExtension }
        if (-not $extension.StartsWith(".")) { $extension = "." + $extension }
        $plotPath = if ($extension.Equals(".pdf", [StringComparison]::OrdinalIgnoreCase)) { $pdfPath } else { Join-Path $OutputDir ("page_{0:D3}{1}" -f $page, $extension) }
        $candidatePaths = @($pdfPath, $plotPath, ($plotPath + ".pdf")) | Select-Object -Unique
        foreach ($candidatePath in $candidatePaths) {
            if (Test-Path -LiteralPath $candidatePath) {
                [void](Close-GeneratedPdfViewerWindows -PdfPaths @($candidatePath) -Seconds $ViewerSuppressSeconds)
                Remove-Item -LiteralPath $candidatePath -Force
            }
        }

        $item = [ordered]@{ page = $page; output = $pdfPath; plotOutput = $plotPath; window = @($lowerLeft[0], $lowerLeft[1], $upperRight[0], $upperRight[1]); status = "pending"; message = ""; actualDevice = ""; actualMedia = ""; actualRotation = $null }
        try {
            [void](Invoke-PlotCom -Operation "SetWindowToPlot page $page" -Acad $acad -Action { $layout.SetWindowToPlot($lowerLeft, $upperRight) })
            [void](Set-PropSafe -Object $layout -Name "PlotType" -Value 4 -Acad $acad)
            $item.actualDevice = [string](Invoke-PlotCom -Operation "Read plot device page $page" -Acad $acad -Action { $layout.ConfigName })
            $item.actualMedia = [string](Invoke-PlotCom -Operation "Read plot media page $page" -Acad $acad -Action { $layout.CanonicalMediaName })
            $item.actualRotation = Invoke-PlotCom -Operation "Read plot rotation page $page" -Acad $acad -Action { $layout.PlotRotation }
            try { [void](Invoke-PlotCom -Operation "Regen page $page" -Acad $acad -Action { $doc.Regen(1) }) } catch { $layoutWarnings.Add("Regen failed on page ${page}: $($_.Exception.Message)") }
            $ok = Invoke-PlotCom -Operation "PlotToFile page $page" -Acad $acad -Action { $plot.PlotToFile($plotPath) }
            if (-not $ok) { throw "AutoCAD PlotToFile returned false" }
            $createdPlotPath = $plotPath
            if (-not (Wait-ForFile -Path $createdPlotPath -TimeoutSeconds 5)) {
                $alternatePlotPath = $plotPath + ".pdf"
                if (Wait-ForFile -Path $alternatePlotPath -TimeoutSeconds 180) { $createdPlotPath = $alternatePlotPath } else { throw "PDF was not created before timeout" }
            }
            if (-not $createdPlotPath.Equals($pdfPath, [StringComparison]::OrdinalIgnoreCase)) {
                if (Test-Path -LiteralPath $pdfPath) { Remove-Item -LiteralPath $pdfPath -Force }
                Move-Item -LiteralPath $createdPlotPath -Destination $pdfPath -Force
            }
            $item.status = "ok"
            $item["createdPlotPath"] = $createdPlotPath
            $item["suppressedViewerWindows"] = @(Close-GeneratedPdfViewerWindows -PdfPaths @($pdfPath, $plotPath, $createdPlotPath) -Seconds $ViewerSuppressSeconds)
        } catch {
            $item.status = "error"
            $item.message = $_.Exception.Message
            $item.stack = $_.ScriptStackTrace
        }
        $results += [pscustomobject]$item
    }
} finally {
    if ($null -ne $doc) {
        try { [void](Invoke-PlotCom -Operation "Close conversion document" -Acad $acad -TimeoutSeconds 30 -Action { $doc.Close($false) }) } catch { Add-AcadComEvent -Operation "Close conversion document" -Event "cleanup-failed" -Message $_.Exception.Message }
    }
    Release-AcadComObject $plot
    Release-AcadComObject $layout
    Release-AcadComObject $doc
    if ($createdAcad -and $null -ne $acad) {
        try { [void](Invoke-PlotCom -Operation "Quit owned AutoCAD instance" -Acad $acad -TimeoutSeconds 30 -Action { $acad.Quit() }) } catch { Add-AcadComEvent -Operation "Quit owned AutoCAD instance" -Event "cleanup-failed" -Message $_.Exception.Message }
    }
    Release-AcadComObject $acad
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

[ordered]@{
    schemaVersion = 2
    input = $resolvedInput
    autoCad = [ordered]@{ requestedProgId = $AutoCadProgId; resolvedProgId = $resolvedProgId; reportedVersion = $reportedVersion; reuseExistingExplicitly = [bool]$ReuseExistingAutoCAD; instanceOwnership = $(if ($createdAcad) { "created-and-closed-by-workflow" } else { "reused-user-instance" }) }
    layoutWarnings = @($layoutWarnings)
    comEvents = @($comEvents)
    pages = @($results)
} | ConvertTo-Json -Depth 10
<#
AutoCAD COM plotter. Uses native AutoCAD PlotToFile for fidelity, then writes temporary .codexplot files to avoid triggering PDF viewers per page.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$InputDxf,

    [Parameter(Mandatory = $true)]
    [string]$WindowsJson,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [string]$AutoCadProgId = "AutoCAD.Application.25",

    [string]$DeviceName = "DWG To PDF.pc3",

    [string]$MediaName = "ISO_full_bleed_A1_(841.00_x_594.00_MM)",

    [int]$PlotRotation = 0,

    [int]$MaxPages = 0,

    [int]$SuppressViewerWindows = 1,

    [int]$ViewerSuppressSeconds = 3,

    [string]$IntermediateExtension = ".codexplot"
)

$ErrorActionPreference = "Stop"

function Set-SysVarSafe {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Document,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [object]$Value
    )
    foreach ($attempt in @($Value, [int16]$Value, [int32]$Value, [double]$Value)) {
        try {
            $Document.SetVariable($Name, $attempt)
            return $true
        } catch {
        }
    }
    return $false
}

function Set-PropSafe {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [object]$Value
    )
    try {
        $Object.$Name = $Value
        return $true
    } catch {
        return $false
    }
}

function Wait-ForFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [int]$TimeoutSeconds = 120
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $Path) {
            $item = Get-Item -LiteralPath $Path
            if ($item.Length -gt 0) {
                return $true
            }
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Initialize-WindowApi {
    if ("CodexWindowApi.NativeMethods" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;

namespace CodexWindowApi {
    public static class NativeMethods {
        public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
        [DllImport("user32.dll")]
        public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
        [DllImport("user32.dll", SetLastError=true)]
        public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
        [DllImport("user32.dll", SetLastError=true)]
        public static extern int GetWindowTextLength(IntPtr hWnd);
        [DllImport("user32.dll")]
        public static extern bool IsWindowVisible(IntPtr hWnd);
        [DllImport("user32.dll")]
        public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
        [DllImport("user32.dll")]
        public static extern IntPtr SendMessage(IntPtr hWnd, int Msg, IntPtr wParam, IntPtr lParam);
        [DllImport("user32.dll")]
        public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    }
}
"@
}

function Get-WindowSnapshot {
    Initialize-WindowApi
    $windows = New-Object System.Collections.Generic.List[object]
    $callback = [CodexWindowApi.NativeMethods+EnumWindowsProc]{
        param([IntPtr]$hWnd, [IntPtr]$lParam)
        if (-not [CodexWindowApi.NativeMethods]::IsWindowVisible($hWnd)) {
            return $true
        }
        $length = [CodexWindowApi.NativeMethods]::GetWindowTextLength($hWnd)
        if ($length -le 0) {
            return $true
        }
        $builder = New-Object System.Text.StringBuilder ($length + 1)
        [void][CodexWindowApi.NativeMethods]::GetWindowText($hWnd, $builder, $builder.Capacity)
        [uint32]$windowProcessId = 0
        [void][CodexWindowApi.NativeMethods]::GetWindowThreadProcessId($hWnd, [ref]$windowProcessId)
        $title = $builder.ToString()
        if (-not [string]::IsNullOrWhiteSpace($title)) {
            $script:windowSnapshotCollector.Add([pscustomobject]@{
                Hwnd = $hWnd
                ProcessId = [int]$windowProcessId
                Title = $title
            })
        }
        return $true
    }
    $script:windowSnapshotCollector = $windows
    [void][CodexWindowApi.NativeMethods]::EnumWindows($callback, [IntPtr]::Zero)
    $script:windowSnapshotCollector = $null
    return $windows
}

function Close-GeneratedPdfViewerWindows {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$PdfPaths,
        [Parameter(Mandatory = $true)]
        [datetime]$QuietStart,
        [int]$Seconds = 3
    )
    if (-not $SuppressViewerWindows) {
        return @()
    }

    $pdfNames = @()
    foreach ($path in $PdfPaths) {
        $pdfNames += [IO.Path]::GetFileName($path)
        $pdfNames += [IO.Path]::GetFileNameWithoutExtension($path)
    }
    $pdfNames = @($pdfNames | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    $wpsLike = @("wps", "wpspdf", "wpsoffice", "wpp", "et")
    $closed = @()
    $deadline = (Get-Date).AddSeconds([math]::Max(0, $Seconds))

    do {
        foreach ($window in Get-WindowSnapshot) {
            $title = [string]$window.Title
            $titleMatched = $false
            foreach ($name in $pdfNames) {
                if ($title.IndexOf($name, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                    $titleMatched = $true
                    break
                }
            }

            $newWpsViewer = $false
            try {
                $process = Get-Process -Id $window.ProcessId -ErrorAction Stop
                if ($process.StartTime -ge $QuietStart) {
                    $processName = $process.ProcessName.ToLowerInvariant()
                    if ($wpsLike -contains $processName) {
                        $newWpsViewer = $true
                    }
                }
            } catch {
            }

            if ($titleMatched -or $newWpsViewer) {
                [void][CodexWindowApi.NativeMethods]::ShowWindow($window.Hwnd, 6)
                if ($titleMatched) {
                    [void][CodexWindowApi.NativeMethods]::SendMessage($window.Hwnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
                }
                $closed += [ordered]@{
                    title = $title
                    processId = $window.ProcessId
                    matchedByTitle = $titleMatched
                    matchedAsNewWpsViewer = $newWpsViewer
                }
            }
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)

    return @($closed)
}
$resolvedInput = (Resolve-Path -LiteralPath $InputDxf).Path

$resolvedJson = (Resolve-Path -LiteralPath $WindowsJson).Path
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$config = Get-Content -LiteralPath $resolvedJson -Encoding UTF8 | ConvertFrom-Json
$frames = @($config.frames)
if ($frames.Count -eq 0) {
    throw "No frame windows found in $resolvedJson"
}
if ($MaxPages -gt 0) {
    $frames = @($frames | Sort-Object {[int]$_.page} | Select-Object -First $MaxPages)
}

$acad = $null
$doc = $null
$createdAcad = $false
$results = @()
$quietStart = Get-Date

try {
    try {
        $acad = [Runtime.InteropServices.Marshal]::GetActiveObject($AutoCadProgId)
    } catch {
        $acad = New-Object -ComObject $AutoCadProgId
        $createdAcad = $true
    }
    try { $acad.Visible = $false } catch {}
    try { $acad.DisplayAlerts = $false } catch {}

    $doc = $acad.Documents.Open($resolvedInput)
    Start-Sleep -Milliseconds 500

    $null = Set-SysVarSafe -Document $doc -Name "BACKGROUNDPLOT" -Value 0
    $null = Set-SysVarSafe -Document $doc -Name "FILEDIA" -Value 0
    $null = Set-SysVarSafe -Document $doc -Name "CMDDIA" -Value 0
    $null = Set-SysVarSafe -Document $doc -Name "EXPERT" -Value 5
    $null = Set-SysVarSafe -Document $doc -Name "PUBLISHCOLLATE" -Value 0
    $null = Set-SysVarSafe -Document $doc -Name "PDFSHX" -Value 0
    $null = Set-SysVarSafe -Document $doc -Name "EPDFSHX" -Value 0
    $null = Set-SysVarSafe -Document $doc -Name "PDFSHXTEXT" -Value 0
    $null = Set-SysVarSafe -Document $doc -Name "PUBLISHOPEN" -Value 0
    $null = Set-SysVarSafe -Document $doc -Name "PUBLISHVIEW" -Value 0
    $null = Set-SysVarSafe -Document $doc -Name "PLOTNOTIFY" -Value 0
    $null = Set-SysVarSafe -Document $doc -Name "VIEWPLOTDETAILS" -Value 0
    try { $doc.Plot.QuietErrorMode = $true } catch {}

    $layout = $doc.Layouts.Item("Model")
    $doc.ActiveLayout = $layout
    try { $doc.ActiveSpace = 1 } catch {}

    [void](Set-PropSafe -Object $layout -Name "ConfigName" -Value $DeviceName)
    try { $layout.RefreshPlotDeviceInfo() } catch {}
    [void](Set-PropSafe -Object $layout -Name "PaperUnits" -Value 1)
    [void](Set-PropSafe -Object $layout -Name "CanonicalMediaName" -Value $MediaName)
    [void](Set-PropSafe -Object $layout -Name "PlotType" -Value 4)
    [void](Set-PropSafe -Object $layout -Name "CenterPlot" -Value $true)
    [void](Set-PropSafe -Object $layout -Name "UseStandardScale" -Value $true)
    [void](Set-PropSafe -Object $layout -Name "StandardScale" -Value 0)
    [void](Set-PropSafe -Object $layout -Name "PlotRotation" -Value $PlotRotation)
    [void](Set-PropSafe -Object $layout -Name "PlotWithPlotStyles" -Value $false)
    [void](Set-PropSafe -Object $layout -Name "PlotWithLineweights" -Value $true)
    [void](Set-PropSafe -Object $layout -Name "ScaleLineweights" -Value $false)
    [void](Set-PropSafe -Object $layout -Name "ShowPlotStyles" -Value $false)
    [void](Set-PropSafe -Object $layout -Name "PlotHidden" -Value $false)

    foreach ($frame in $frames) {
        $page = [int]$frame.page
        $window = @($frame.window)
        $lowerLeft = [double[]]@([double]$window[0], [double]$window[1])
        $upperRight = [double[]]@([double]$window[2], [double]$window[3])
        $pdfPath = Join-Path $OutputDir ("page_{0:D3}.pdf" -f $page)
        $plotExtension = $IntermediateExtension
        if ([string]::IsNullOrWhiteSpace($plotExtension)) {
            $plotExtension = ".pdf"
        }
        if (-not $plotExtension.StartsWith(".")) {
            $plotExtension = "." + $plotExtension
        }
        # Avoid writing directly to .pdf by default; some Windows setups open every created PDF in WPS or another viewer.
        if ($plotExtension.Equals(".pdf", [StringComparison]::OrdinalIgnoreCase)) {
            $plotPath = $pdfPath
        } else {
            $plotPath = Join-Path $OutputDir ("page_{0:D3}{1}" -f $page, $plotExtension)
        }
        $candidatePaths = @($pdfPath, $plotPath, ($plotPath + ".pdf")) | Select-Object -Unique
        foreach ($candidatePath in $candidatePaths) {
            if (Test-Path -LiteralPath $candidatePath) {
                [void](Close-GeneratedPdfViewerWindows -PdfPaths @($candidatePath) -QuietStart $quietStart -Seconds $ViewerSuppressSeconds)
                Remove-Item -LiteralPath $candidatePath -Force
            }
        }

        $item = [ordered]@{
            page = $page
            output = $pdfPath
            plotOutput = $plotPath
            window = @($lowerLeft[0], $lowerLeft[1], $upperRight[0], $upperRight[1])
            status = "pending"
            message = ""
            actualDevice = ""
            actualMedia = ""
            actualRotation = $null
        }
        try {
            $layout.SetWindowToPlot($lowerLeft, $upperRight)
            [void](Set-PropSafe -Object $layout -Name "PlotType" -Value 4)
            $item.actualDevice = [string]$layout.ConfigName
            $item.actualMedia = [string]$layout.CanonicalMediaName
            $item.actualRotation = $layout.PlotRotation
            try { $doc.Regen(1) } catch {}
            $ok = $doc.Plot.PlotToFile($plotPath)
            if (-not $ok) {
                throw "AutoCAD PlotToFile returned false"
            }
            $createdPlotPath = $plotPath
            if (-not (Wait-ForFile -Path $createdPlotPath -TimeoutSeconds 5)) {
                $alternatePlotPath = $plotPath + ".pdf"
                if (Wait-ForFile -Path $alternatePlotPath -TimeoutSeconds 180) {
                    $createdPlotPath = $alternatePlotPath
                } else {
                    throw "PDF was not created before timeout"
                }
            }
            if (-not $createdPlotPath.Equals($pdfPath, [StringComparison]::OrdinalIgnoreCase)) {
                if (Test-Path -LiteralPath $pdfPath) {
                    [void](Close-GeneratedPdfViewerWindows -PdfPaths @($pdfPath) -QuietStart $quietStart -Seconds $ViewerSuppressSeconds)
                    Remove-Item -LiteralPath $pdfPath -Force
                }
                Move-Item -LiteralPath $createdPlotPath -Destination $pdfPath -Force
            }
            $suppressed = Close-GeneratedPdfViewerWindows -PdfPaths @($pdfPath, $plotPath, $createdPlotPath) -QuietStart $quietStart -Seconds $ViewerSuppressSeconds
            $item.status = "ok"
            $item["createdPlotPath"] = $createdPlotPath
            $item["suppressedViewerWindows"] = @($suppressed)
        } catch {
            $item.status = "error"
            $item.message = $_.Exception.Message
            $item.stack = $_.ScriptStackTrace
        }
        $results += $item
    }
} finally {
    if ($doc -ne $null) {
        try { $doc.Close($false) } catch {}
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($doc)
    }
    if ($acad -ne $null) {
        if ($createdAcad) {
            try { $acad.Quit() } catch {}
        }
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($acad)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$results | ConvertTo-Json -Depth 8


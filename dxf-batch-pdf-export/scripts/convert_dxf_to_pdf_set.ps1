<#
One-command controller for preflight, frame detection, AutoCAD plotting, PDF merge, and PDF verification.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$InputDxf,

    [Parameter(Mandatory = $true)]
    [string]$OutputPdf,

    [string]$WorkDir = "",
    [string]$PythonExe = "python",

    [double]$FrameWidth = 841.0,
    [double]$FrameHeight = 594.0,
    [double]$FrameTolerance = 5.0,
    [double]$Padding = 0.01,
    [int]$MinCount = 1,
    [string]$FrameBlock = "",
    [ValidateSet("auto", "block", "color", "cluster")]
    [string]$DetectionStrategy = "auto",
    [string]$FrameColor = "6",
    [string]$FrameLayer = "",
    [double]$ColorClusterGap = 2.0,
    [double]$ClusterGap = 30.0,
    [int]$MinClusterEntities = 20,
    [double]$MinClusterWidth = 0.0,
    [double]$MinClusterHeight = 0.0,
    [double]$MinEntitySize = 0.0,
    [ValidateSet("top-left", "bottom-left", "left-bottom", "input")]
    [string]$Sort = "top-left",

    [string]$AutoCadProgId = "AutoCAD.Application.25",
    [string]$DeviceName = "DWG To PDF.pc3",
    [string]$MediaName = "ISO_full_bleed_A1_(841.00_x_594.00_MM)",
    [int]$PlotRotation = 0,
    [int]$MaxPages = 0,
    [int]$SuppressViewerWindows = 1,
    [int]$ViewerSuppressSeconds = 3,
    [string]$IntermediateExtension = ".codexplot",

    [int]$SkipMerge = 0,
    [int]$SkipVerification = 0,
    [int]$RenderSamples = 1,
    [int]$RunPreflight = 1,
    [int]$Dpi = 120,
    [double]$MaxMarginFraction = 0.0
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$detectScript = Join-Path $scriptRoot "detect_dxf_frames.py"
$preflightScript = Join-Path $scriptRoot "analyze_dxf_features.py"
$plotScript = Join-Path $scriptRoot "plot_dxf_windows_acad.ps1"
$mergeScript = Join-Path $scriptRoot "merge_pdf_pages.py"
$verifyScript = Join-Path $scriptRoot "verify_pdf_pages.py"

$resolvedInput = (Resolve-Path -LiteralPath $InputDxf).Path
$outputFull = [IO.Path]::GetFullPath($OutputPdf)
$outputDir = Split-Path -Parent $outputFull
if ([string]::IsNullOrWhiteSpace($outputDir)) {
    $outputDir = (Get-Location).Path
    $outputFull = Join-Path $outputDir $OutputPdf
}
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($WorkDir)) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stem = [IO.Path]::GetFileNameWithoutExtension($outputFull)
    $WorkDir = Join-Path $outputDir ("{0}_dxf_work_{1}" -f $stem, $stamp)
}
$WorkDir = [IO.Path]::GetFullPath($WorkDir)
$pagesDir = Join-Path $WorkDir "pages"
$renderDir = Join-Path $WorkDir "render_samples"
New-Item -ItemType Directory -Force -Path $pagesDir | Out-Null

$preflightJson = Join-Path $WorkDir "preflight_report.json"
$framesJson = Join-Path $WorkDir "frames.json"
$plotJson = Join-Path $WorkDir "plot_results.json"
$mergeJson = Join-Path $WorkDir "merge_summary.json"
$verifyJson = Join-Path $WorkDir "verify_summary.json"

$sharedDetectArgs = @(
    "--input", $resolvedInput,
    "--frame-width", ([string]$FrameWidth),
    "--frame-height", ([string]$FrameHeight),
    "--tolerance", ([string]$FrameTolerance),
    "--padding", ([string]$Padding),
    "--min-count", ([string]$MinCount),
    "--color-cluster-gap", ([string]$ColorClusterGap),
    "--cluster-gap", ([string]$ClusterGap),
    "--min-cluster-entities", ([string]$MinClusterEntities),
    "--min-cluster-width", ([string]$MinClusterWidth),
    "--min-cluster-height", ([string]$MinClusterHeight),
    "--min-entity-size", ([string]$MinEntitySize)
)
if (-not [string]::IsNullOrWhiteSpace($FrameBlock)) {
    $sharedDetectArgs += @("--frame-block", $FrameBlock)
}
if (-not [string]::IsNullOrWhiteSpace($FrameColor)) {
    $sharedDetectArgs += @("--frame-color", $FrameColor)
}
if (-not [string]::IsNullOrWhiteSpace($FrameLayer)) {
    $sharedDetectArgs += @("--frame-layer", $FrameLayer)
}

if ($RunPreflight) {
    $preflightArgs = @($preflightScript, "--output", $preflightJson) + $sharedDetectArgs
    & $PythonExe @preflightArgs
    if ($LASTEXITCODE -ne 0) { throw "DXF preflight failed with exit code $LASTEXITCODE" }
}

$detectArgs = @(
    $detectScript,
    "--output", $framesJson,
    "--strategy", $DetectionStrategy,
    "--sort", $Sort
) + $sharedDetectArgs
& $PythonExe @detectArgs
if ($LASTEXITCODE -ne 0) { throw "Frame detection failed with exit code $LASTEXITCODE" }

$config = Get-Content -LiteralPath $framesJson -Encoding UTF8 | ConvertFrom-Json
$expectedCount = [int]$config.pageCount
if ($MaxPages -gt 0 -and $MaxPages -lt $expectedCount) {
    $expectedCount = $MaxPages
}

$plotOutput = & $plotScript `
    -InputDxf $resolvedInput `
    -WindowsJson $framesJson `
    -OutputDir $pagesDir `
    -AutoCadProgId $AutoCadProgId `
    -DeviceName $DeviceName `
    -MediaName $MediaName `
    -PlotRotation $PlotRotation `
    -MaxPages $MaxPages `
    -SuppressViewerWindows $SuppressViewerWindows `
    -ViewerSuppressSeconds $ViewerSuppressSeconds `
    -IntermediateExtension $IntermediateExtension
$plotOutput | Set-Content -LiteralPath $plotJson -Encoding UTF8
$plotResults = Get-Content -LiteralPath $plotJson -Raw -Encoding UTF8 | ConvertFrom-Json
$plotErrors = @($plotResults | Where-Object { $_.status -ne "ok" })
if ($plotErrors.Count -gt 0) {
    throw ("AutoCAD plotting failed for {0} page(s); see {1}" -f $plotErrors.Count, $plotJson)
}

if (-not $SkipMerge) {
    $mergeOutput = & $PythonExe $mergeScript --input-dir $pagesDir --output $outputFull --expected-count $expectedCount
    if ($LASTEXITCODE -ne 0) { throw "PDF merge failed with exit code $LASTEXITCODE" }
    $mergeOutput | Set-Content -LiteralPath $mergeJson -Encoding UTF8
}

if (-not $SkipVerification -and -not $SkipMerge) {
    $verifyArgs = @($verifyScript, "--pdf", $outputFull, "--expected-pages", ([string]$expectedCount))
    if ($RenderSamples) {
        $verifyArgs += @("--render-dir", $renderDir, "--dpi", ([string]$Dpi))
    }
    if ($MaxMarginFraction -gt 0) {
        $verifyArgs += @("--max-margin-fraction", ([string]$MaxMarginFraction))
    }
    $verifyOutput = & $PythonExe @verifyArgs
    if ($LASTEXITCODE -ne 0) { throw "PDF verification failed with exit code $LASTEXITCODE" }
    $verifyOutput | Set-Content -LiteralPath $verifyJson -Encoding UTF8
}

[ordered]@{
    input = $resolvedInput
    outputPdf = $(if ($SkipMerge) { $null } else { $outputFull })
    workDir = $WorkDir
    pagesDir = $pagesDir
    preflightReportJson = $(if ($RunPreflight) { $preflightJson } else { $null })
    framesJson = $framesJson
    plotResultsJson = $plotJson
    mergeSummaryJson = $(if ($SkipMerge) { $null } else { $mergeJson })
    verifySummaryJson = $(if ($SkipVerification -or $SkipMerge) { $null } else { $verifyJson })
    pageCount = $expectedCount
    status = "ok"
} | ConvertTo-Json -Depth 6

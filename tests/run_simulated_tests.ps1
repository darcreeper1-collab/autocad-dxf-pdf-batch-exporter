param([string]$PythonExe = "python")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
& $PythonExe (Join-Path $root "test_issue2_regressions.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "test_acad_worker.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $PythonExe (Join-Path $root "test_dwg_controller.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $PythonExe (Join-Path $root "test_frame_detection.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "test_acad_helpers.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "All simulated tests passed."

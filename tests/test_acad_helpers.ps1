$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path (Split-Path -Parent $scriptRoot) "dxf-batch-pdf-export\scripts\acad_com_helpers.ps1")

function Assert-That {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Assertion failed: $Message" }
}

$busyHresult = [Convert]::ToInt32("80010001", 16)
$attempts = 0
$result = Invoke-AcadComRetry -Operation "simulated busy call" -SkipIdleWait -TimeoutSeconds 2 -InitialDelayMilliseconds 1 -MaxDelayMilliseconds 2 -Action {
    $script:attempts++
    if ($script:attempts -lt 3) { throw [Runtime.InteropServices.COMException]::new("RPC_E_CALL_REJECTED", $busyHresult) }
    "ok"
}
Assert-That ($result -eq "ok") "Busy COM call should eventually return."
Assert-That ($attempts -eq 3) "Busy COM call should retry exactly twice."

$nonTransientAttempts = 0
try {
    Invoke-AcadComRetry -Operation "simulated invalid argument" -SkipIdleWait -TimeoutSeconds 2 -Action {
        $script:nonTransientAttempts++
        throw [InvalidOperationException]::new("invalid input")
    } | Out-Null
    throw "Non-transient failure was unexpectedly retried."
} catch [InvalidOperationException] {}
Assert-That ($nonTransientAttempts -eq 1) "Non-transient error must not retry."

$timedOut = $false
try {
    Invoke-AcadComRetry -Operation "simulated timeout" -SkipIdleWait -TimeoutSeconds 1 -InitialDelayMilliseconds 1 -MaxDelayMilliseconds 2 -Action {
        throw [Runtime.InteropServices.COMException]::new("RPC_E_CALL_REJECTED", $busyHresult)
    } | Out-Null
} catch [TimeoutException] { $timedOut = $true }
Assert-That $timedOut "Busy COM retries must stop at their timeout."

Assert-That ((Resolve-AcadProgId -CandidateProgIds @("AutoCAD.Application.24", "AutoCAD.Application.25", "AutoCAD.Application.23")) -eq "AutoCAD.Application.25") "Highest candidate should win."
Assert-That ((Resolve-AcadProgId -AutoCadProgId "AutoCAD.Application.24" -CandidateProgIds @("AutoCAD.Application.25")) -eq "AutoCAD.Application.24") "Explicit ProgID should win."

$dwgRoute = Resolve-DrawingInputRoute -InputPath "C:\drawings\test.dwg" -WorkDir "C:\work"
Assert-That ($dwgRoute.requiresDxfMirror -and $dwgRoute.plotInput.EndsWith("test.dwg") -and $dwgRoute.detectionInput.EndsWith("test_diagnostic.dxf")) "DWG route should detect from a temporary DXF and plot the source DWG."
$dxfRoute = Resolve-DrawingInputRoute -InputPath "C:\drawings\test.dxf" -WorkDir "C:\work"
Assert-That ((-not $dxfRoute.requiresDxfMirror) -and $dxfRoute.plotInput.EndsWith("test.dxf")) "DXF route should not create a mirror."

Write-Output "PowerShell simulated tests passed."
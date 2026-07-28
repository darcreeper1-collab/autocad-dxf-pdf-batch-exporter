<#
Conservative cleanup helper. It only quits AutoCAD when the COM instance is hidden and has no open documents.
#>

param(
    [string]$AutoCadProgId = "AutoCAD.Application.25"
)

$ErrorActionPreference = "Stop"
try {
    $acad = [Runtime.InteropServices.Marshal]::GetActiveObject($AutoCadProgId)
    $docCount = 0
    try { $docCount = [int]$acad.Documents.Count } catch {}
    $visible = $true
    try { $visible = [bool]$acad.Visible } catch {}
    Write-Output ("documents=" + $docCount)
    Write-Output ("visible=" + $visible)
    if ($docCount -eq 0 -and -not $visible) {
        try { $acad.Quit() } catch {}
        Write-Output "quit-idle-hidden-acad"
    } else {
        Write-Output "left-running"
    }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($acad)
} catch {
    Write-Output ("cleanup-skip: " + $_.Exception.Message)
}

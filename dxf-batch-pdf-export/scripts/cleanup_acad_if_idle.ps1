<#
Inspect an explicitly selected active AutoCAD instance.

The normal plotting workflow closes the instance it created in its own finally
block. This helper intentionally does not quit active AutoCAD by default,
because COM cannot prove that an idle hidden instance belongs to this skill.
#>

param(
    [string]$AutoCadProgId = "",
    [int]$AllowQuitIdleHidden = 0
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptRoot "acad_com_helpers.ps1")
try {
    $progId = Resolve-AcadProgId -AutoCadProgId $AutoCadProgId
    $acad = Invoke-AcadComRetry -Operation "GetActiveObject $progId" -SkipIdleWait -Action { [Runtime.InteropServices.Marshal]::GetActiveObject($progId) }
    $docCount, $visible = 0, $true
    try { $docCount = [int]$acad.Documents.Count } catch {}
    try { $visible = [bool]$acad.Visible } catch {}
    [ordered]@{ progId = $progId; documents = $docCount; visible = $visible; action = "left-running"; warning = "No active AutoCAD instance is closed unless -AllowQuitIdleHidden 1 is explicitly supplied." } | ConvertTo-Json
    if ($AllowQuitIdleHidden -and $docCount -eq 0 -and -not $visible) {
        $acad.Quit()
        Write-Output "quit-idle-hidden-acad-explicitly-requested"
    }
    Release-AcadComObject $acad
} catch {
    Write-Output ("cleanup-skip: " + $_.Exception.Message)
}
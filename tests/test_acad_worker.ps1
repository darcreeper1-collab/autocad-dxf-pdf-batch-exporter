$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../dxf-batch-pdf-export/scripts/acad_com_helpers.ps1')
$fixture = Join-Path $PSScriptRoot 'fixtures/acad_worker_stub.ps1'
$logs = Join-Path $PSScriptRoot '../.test-output/watchdog'
$result = Invoke-AcadSupervisedScript -ScriptPath $fixture -Parameters @{Mode='success'} -LogRoot $logs -TimeoutSeconds 4
if (($result | ConvertFrom-Json).status -ne 'ok') { throw 'Worker output was not preserved.' }
$failed = $false
try { Invoke-AcadSupervisedScript -ScriptPath $fixture -Parameters @{Mode='failure'} -LogRoot $logs -TimeoutSeconds 4 } catch {
    $failed = $_.Exception.Message -match 'simulated worker failure'
}
if (-not $failed) { throw 'Worker error did not propagate.' }
$timer = [Diagnostics.Stopwatch]::StartNew()
$timedOut = $false
try { Invoke-AcadSupervisedScript -ScriptPath $fixture -Parameters @{Mode='hang'} -LogRoot $logs -TimeoutSeconds 4 } catch [TimeoutException] {
    $timedOut = $_.Exception.Message -match 'simulated blocking COM call'
}
if (-not $timedOut -or $timer.Elapsed.TotalSeconds -gt 15) { throw 'Blocking call was not bounded.' }
$result = Invoke-AcadSupervisedScript -ScriptPath $fixture -Parameters @{Mode='progress'} -LogRoot $logs -TimeoutSeconds 4
if (($result | ConvertFrom-Json).status -ne 'ok') { throw 'Progress should extend the watchdog.' }

# Load only the setter definition, not the entry point that starts AutoCAD.
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../dxf-batch-pdf-export/scripts/plot_dxf_windows_acad.ps1'), [ref]$tokens, [ref]$errors)
$setter = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Set-PropSafe' }, $true)
. ([scriptblock]::Create($setter.Extent.Text))
function Invoke-PlotCom { param($Operation, $Action, $Acad) & $Action }
$layoutWarnings = New-Object 'System.Collections.Generic.List[string]'
$layout = [pscustomobject]@{ConfigName='old.pc3'}
if (-not (Set-PropSafe -Object $layout -Name ConfigName -Value 'DWG To PDF.pc3')) { throw 'Valid required property failed.' }
$layout | Add-Member -MemberType ScriptProperty -Name CanonicalMediaName -Value { 'wrong-media' } -SecondValue { param($value) }
$rejected = $false
try { Set-PropSafe -Object $layout -Name CanonicalMediaName -Value 'A1' } catch { $rejected = $_.Exception.Message -match 'Required plot setting' }
if (-not $rejected) { throw 'Silent property coercion was not rejected.' }
$rejected = $false
try { Set-PropSafe -Object $layout -Name PlotType -Value 4 } catch { $rejected = $true }
if (-not $rejected) { throw 'Missing required property was not rejected.' }
if (Set-PropSafe -Object $layout -Name OptionalUnsupported -Value 1) { throw 'Optional failure should warn.' }
if ($layoutWarnings.Count -ne 1) { throw 'Optional warning missing.' }
Write-Output 'Watchdog (success/failure/hang/progress) and required-property tests passed.'

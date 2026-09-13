param([switch]$WorkerMode, [string]$WorkerStatePath, [string]$Mode)
$ErrorActionPreference = 'Stop'
if (-not $WorkerMode) { throw 'WorkerMode must be set by supervisor.' }
switch ($Mode) {
    'success' { '{"status":"ok"}' }
    'failure' { throw 'simulated worker failure' }
    'hang' {
        'simulated blocking COM call' | Set-Content -LiteralPath $WorkerStatePath
        Start-Sleep -Seconds 40
        throw 'A blocked worker must not reach here.'
    }
    'progress' {
        1..7 | ForEach-Object {
            "operation $_" | Set-Content -LiteralPath $WorkerStatePath
            Start-Sleep -Seconds 1
        }
        '{"status":"ok"}'
    }
}

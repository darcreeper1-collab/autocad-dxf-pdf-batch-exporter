"""Run the real DWG controller with simulated AutoCAD mirror/plot boundaries."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_frame_detection import ROOT, make_dxf


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_case(root, mode, prior_exit):
    case = root / f"{mode}-{prior_exit}"
    scripts = case / "scripts"
    shutil.copytree(ROOT / "dxf-batch-pdf-export" / "scripts", scripts,
                    ignore=shutil.ignore_patterns("__pycache__"))
    source = case / "source.dwg"
    source.write_bytes(b"synthetic source: must remain unchanged")
    fixture = scripts / "fixture.dxf"
    make_dxf(fixture)
    mirror = '''param([string]$InputDwg, [string]$OutputDxf)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputDxf) | Out-Null
'''
    if mode == "throw":
        mirror += "throw 'simulated mirror failure'\n"
    elif mode != "missing":
        mirror += "Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'fixture.dxf') -Destination $OutputDxf\n"
    if mode == "invalid-json":
        mirror += "Write-Output 'not json'\n"
    elif mode == "error-status":
        mirror += "Write-Output '{\"status\":\"error\"}'\n"
    else:
        mirror += "Write-Output '{\"status\":\"ok\"}'\n"
    (scripts / "export_dwg_to_dxf_acad.ps1").write_text(mirror, encoding="utf-8")
    (scripts / "plot_dxf_windows_acad.ps1").write_text('''param([string]$InputDxf, [string]$WindowsJson, [string]$OutputDir)
$config = Get-Content -LiteralPath $WindowsJson -Raw -Encoding UTF8 | ConvertFrom-Json
[ordered]@{input=$InputDxf; pages=@($config.frames | ForEach-Object { @{page=$_.page; status='ok'} })} | ConvertTo-Json -Depth 6
''', encoding="utf-8")
    work = case / "work"
    result = case / "result.json"
    wrapper = case / "run.ps1"
    prior = "$global:LASTEXITCODE = $null" if prior_exit is None else f"cmd /c exit {prior_exit}"
    wrapper.write_text(f'''$ErrorActionPreference = 'Stop'
{prior}
try {{
    $output = & {ps_quote(scripts / 'convert_dxf_to_pdf_set.ps1')} -InputDxf {ps_quote(source)} -WorkDir {ps_quote(work)} -OutputPdf {ps_quote(case / 'output.pdf')} -PythonExe {ps_quote(sys.executable)} -FrameLayerToken 'unused' -FrameColor 6 -SkipMerge 1 -SkipVerification 1
    $output | Set-Content -LiteralPath {ps_quote(result)} -Encoding UTF8
    exit 0
}} catch {{
    [Console]::Error.WriteLine($_.FullyQualifiedErrorId)
    Write-Error $_ -ErrorAction Continue
    exit 1
}}
''', encoding="utf-8")
    # Use explicit frame-layer filtering for the fixture across PS 5.1 encodings.
    fixture_text = fixture.read_text(encoding="utf-8").replace("\u56fe\u6846-A1", "unused-A1")
    fixture.write_text(fixture_text, encoding="utf-8")
    completed = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                "-File", str(wrapper)], capture_output=True, timeout=60)
    assert source.read_bytes() == b"synthetic source: must remain unchanged"
    if mode == "success":
        assert completed.returncode == 0, completed.stderr.decode(errors="replace")
        route = json.loads((work / "input_route.json").read_text(encoding="utf-8-sig"))
        plotted = json.loads((work / "plot_results.json").read_text(encoding="utf-8-sig"))
        assert route["plotInput"] == str(source)
        assert route["detectionInput"] != str(source)
        assert Path(route["detectionInput"]).is_file()
        assert plotted["input"] == str(source) and len(plotted["pages"]) == 8
        assert (work / "preflight_report.json").is_file()
    else:
        assert completed.returncode != 0, f"{mode} unexpectedly succeeded"
        expected_error = {
            "throw": b"simulated mirror failure",
            "missing": b"no DXF mirror exists",
            "invalid-json": b"ConvertFromJsonCommand",
            "error-status": b"did not report a successful conversion",
        }[mode]
        assert expected_error in completed.stderr, completed.stderr.decode(errors="replace")
        assert not (work / "plot_results.json").exists(), f"{mode} reached plotting"
    print(f"PASS DWG controller: mode={mode}, prior native exit={prior_exit}")


def main():
    scratch = ROOT / ".test-output"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as directory:
        root = Path(directory)
        for prior_exit in (None, 0, 17):
            run_case(root, "success", prior_exit)
        for mode in ("throw", "missing", "invalid-json", "error-status"):
            run_case(root, mode, None)


if __name__ == "__main__":
    main()

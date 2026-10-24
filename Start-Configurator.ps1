$ErrorActionPreference = 'Stop'
$LocalPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path $LocalPython) {
    & $LocalPython (Join-Path $PSScriptRoot 'configurator.py')
} elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
    & py.exe -3 (Join-Path $PSScriptRoot 'configurator.py')
} else {
    $Python = (Get-Command python.exe -ErrorAction Stop).Source
    & $Python (Join-Path $PSScriptRoot 'configurator.py')
}
exit $LASTEXITCODE

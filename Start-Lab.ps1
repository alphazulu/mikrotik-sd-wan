param([Parameter(ValueFromRemainingArguments=$true)][string[]]$LabArgs)
$ErrorActionPreference = 'Stop'
if (-not $LabArgs) { $LabArgs = @('up') }
$WindowsRoot = $PSScriptRoot.Replace('\', '/')
$Resolved = & wsl.exe -d Ubuntu-24.04 -- wslpath -u $WindowsRoot
if ($LASTEXITCODE -ne 0 -or -not $Resolved) { throw 'Cannot resolve project path in WSL' }
$LinuxRoot = $Resolved.Trim()
& wsl.exe -d Ubuntu-24.04 -- python3 "$LinuxRoot/lab.py" @LabArgs
exit $LASTEXITCODE

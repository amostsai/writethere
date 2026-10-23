$ErrorActionPreference = 'Stop'
$executables = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter 'phone-pad-*-windows-x64.exe' -File)
$namedExe = Join-Path $PSScriptRoot 'writethere.exe'
$exe = if (Test-Path -LiteralPath $namedExe) { $namedExe } elseif ($executables.Count -eq 1) { $executables[0].FullName } else { '' }
$base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { $env:TEMP }
$reportDir = Join-Path $base 'phone-pad'
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
$report = Join-Path $reportDir 'windows-diagnostic.txt'
$lines = [System.Collections.Generic.List[string]]::new()
function Report([string]$text) {
    Write-Host $text
    $lines.Add($text)
}
try {
    Report ('Time: ' + [DateTime]::UtcNow.ToString('o'))
    Report ('Windows: ' + [Environment]::OSVersion.VersionString)
    Report ('64-bit OS: ' + [Environment]::Is64BitOperatingSystem)
    Report ('CPU architecture: ' + $env:PROCESSOR_ARCHITECTURE)
    Report ('Native architecture: ' + $env:PROCESSOR_ARCHITEW6432)
    Report ('Session: ' + $env:SESSIONNAME)
    if (-not $exe -or -not (Test-Path -LiteralPath $exe)) {
        throw 'Executable not found. Extract the entire ZIP before running this script.'
    }
    Report ('EXE SHA256: ' + (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash)
    try {
        Get-CimInstance Win32_VideoController | ForEach-Object {
            Report ('Display: ' + $_.Name + '; driver=' + $_.DriverVersion)
        }
    } catch { Report ('Display information unavailable: ' + $_.Exception.Message) }
    $started = [DateTime]::UtcNow
    $process = Start-Process -FilePath $exe -WorkingDirectory $PSScriptRoot -PassThru
    $null = $process.Handle
    if ($process.WaitForExit(10000)) {
        $process.Refresh()
        $code = [int]$process.ExitCode
        $hex = [BitConverter]::ToUInt32([BitConverter]::GetBytes($code), 0).ToString('X8')
        Report ('Process exited: ' + $code + ' (0x' + $hex + ')')
    } else {
        Report 'Process is still running after 10 seconds. Check for an application or error window.'
    }
    $startup = Join-Path $reportDir 'startup.log'
    if ((Test-Path -LiteralPath $startup) -and (Get-Item -LiteralPath $startup).LastWriteTimeUtc -ge $started.AddSeconds(-1)) {
        Report '--- Startup log from this launch ---'
        foreach ($line in (Get-Content -LiteralPath $startup -Encoding UTF8)) { Report $line }
    } else {
        if ($process.HasExited -and $process.ExitCode -eq 0) {
            Report 'No new startup log: WriteThere may already be running; duplicate launches exit normally.'
        } else {
            Report 'No fresh startup log: the program may have failed before entering Rust main().'
        }
        $fallback = Join-Path $env:TEMP 'phone-pad/startup.log'
        if ((Test-Path -LiteralPath $fallback) -and (Get-Item -LiteralPath $fallback).LastWriteTimeUtc -ge $started.AddSeconds(-1)) {
            Report '--- Temporary startup log ---'
            foreach ($line in (Get-Content -LiteralPath $fallback -Encoding UTF8)) { Report $line }
        }
    }
} catch {
    Report ('Launch/diagnostic error: ' + $_.Exception.Message)
} finally {
    [System.IO.File]::WriteAllLines($report, $lines, [System.Text.UTF8Encoding]::new($false))
    Write-Host ('Report saved: ' + $report)
    Write-Host 'Please send the contents of windows-diagnostic.txt back for diagnosis.'
}

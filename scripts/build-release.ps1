param(
    [string]$Target = "x86_64-pc-windows-msvc",
    [string]$OutputDirectory = ""
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if ($Target -ne "x86_64-pc-windows-msvc") {
    throw "This native Windows release script supports x86_64-pc-windows-msvc."
}
$env:CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS = "$env:CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS -C target-feature=+crt-static".Trim()
if (-not $OutputDirectory) { $OutputDirectory = Join-Path (Get-Location) "dist" }
$metadata = cargo metadata --locked --no-deps --format-version 1 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "cargo metadata failed" }
$version = ($metadata.packages | Where-Object { $_.name -eq "phone-pad" }).version
cargo test --locked --target $Target
if ($LASTEXITCODE -ne 0) { throw "cargo test failed" }
cargo build --locked --release --target $Target --bin phone-pad
if ($LASTEXITCODE -ne 0) { throw "cargo build failed" }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$name = "phone-pad-$version-windows-x64"
$exe = Join-Path $OutputDirectory "$name.exe"
$zip = Join-Path $OutputDirectory "$name.zip"
Copy-Item (Join-Path $metadata.target_directory "$Target/release/phone-pad.exe") $exe -Force
$license = Join-Path $OutputDirectory "NotoSansCJK-LICENSE.txt"
Copy-Item (Join-Path $PSScriptRoot "../assets/NotoSansCJK-LICENSE.txt") $license -Force
$diagnosticCmd = Join-Path $OutputDirectory "diagnose-windows.cmd"
$diagnosticPs = Join-Path $OutputDirectory "diagnose-windows.ps1"
$diagnosticReadme = Join-Path $OutputDirectory "README-WINDOWS.txt"
Copy-Item (Join-Path $PSScriptRoot "windows/diagnose-windows.cmd") $diagnosticCmd -Force
Copy-Item (Join-Path $PSScriptRoot "windows/diagnose-windows.ps1") $diagnosticPs -Force
Copy-Item (Join-Path $PSScriptRoot "windows/README-WINDOWS.txt") $diagnosticReadme -Force
Compress-Archive -LiteralPath @($exe, $license, $diagnosticCmd, $diagnosticPs, $diagnosticReadme) -DestinationPath $zip -Force
$lines = @($exe, $zip, $license, $diagnosticCmd, $diagnosticPs, $diagnosticReadme) | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash -Algorithm SHA256 -LiteralPath $_).Hash.ToLowerInvariant(), (Split-Path $_ -Leaf)
}
[System.IO.File]::WriteAllLines((Join-Path $OutputDirectory "$name.sha256"), $lines, [System.Text.UTF8Encoding]::new($false))

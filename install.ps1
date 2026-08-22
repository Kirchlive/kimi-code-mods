# One-line installer for kimi-code-mods on Windows.
#
#   iwr -useb https://raw.githubusercontent.com/Kirchlive/kimi-code-mods/main/install.ps1 | iex
#
# WHAT THIS CAN AND CANNOT DO
# The patcher is macOS code: it reads the Mach-O header of Kimi's binary to
# find the embedded payload, and re-signs the result with `codesign`. Neither
# exists on Windows, so there is nothing here to install natively — and an
# installer that put the files down anyway would only move the disappointment
# to the first time you pressed Apply.
#
# What this script does instead is install into WSL, where the tooling is the
# same as on Linux, and say so plainly when there is no WSL to install into.
#
# Set KIMICODEMODS_REPO to install from a fork.

$ErrorActionPreference = 'Stop'

$Repo   = if ($env:KIMICODEMODS_REPO)   { $env:KIMICODEMODS_REPO }   else { 'Kirchlive/kimi-code-mods' }
$Branch = if ($env:KIMICODEMODS_BRANCH) { $env:KIMICODEMODS_BRANCH } else { 'main' }

function Say  ($m) { Write-Host $m }
function Step ($m) { Write-Host '==> ' -ForegroundColor Red -NoNewline; Write-Host $m }
function Warn ($m) { Write-Host '!   ' -ForegroundColor Red -NoNewline; Write-Host $m }
function Die  ($m) { Write-Host 'x   ' -ForegroundColor Red -NoNewline; Write-Host $m; exit 1 }

Say ''
Step 'kimi-code-mods'

# --- is there a WSL to install into? ----------------------------------------
$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wsl) {
  Warn 'Windows itself cannot be a target: patching Kimi means rewriting a'
  Warn 'Mach-O binary and re-signing it with codesign, both macOS only.'
  Say  ''
  Say  'Install WSL and run this again, or run the menu on macOS:'
  Say  '    wsl --install'
  Say  ''
  Say  'Note that even under WSL the menu runs but Apply does not — WSL is'
  Say  'Linux, and the same two reasons apply there.'
  exit 1
}

# `wsl -l -q` lists installed distributions; empty output means WSL is present
# as a command but has nothing behind it, which fails later in a less obvious
# place than here.
$distros = (& wsl.exe --list --quiet) 2>$null | Where-Object { $_ -and $_.Trim() }
if (-not $distros) {
  Die 'WSL is installed but has no distribution. Run: wsl --install -d Ubuntu'
}

Step "installing into WSL ($($distros[0].Trim()))"
Warn 'the menu will run there; Apply will not — patching is macOS only.'
Say ''

$url = "https://raw.githubusercontent.com/$Repo/$Branch/install.sh"
$cmd = "curl -fsSL '$url' | KIMICODEMODS_REPO='$Repo' KIMICODEMODS_BRANCH='$Branch' bash"

& wsl.exe -- bash -lc $cmd
if ($LASTEXITCODE -ne 0) { Die "the WSL installer exited with $LASTEXITCODE" }

Say ''
Step 'installed'
Say  '    open it with:  wsl kimi-code-mods'
Say  ''

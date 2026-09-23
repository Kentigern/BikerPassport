# Fix for "Could not locate the Claude CLI" / "claude is not recognised" on Windows.
# Run via fix_claude_path.bat (double-click). Finds the installed claude.exe and
# adds its folder to your user PATH. Changes nothing else.

$candidates = @(
    "$env:USERPROFILE\.local\bin\claude.exe",                  # official installer (irm ... | iex)
    "$env:LOCALAPPDATA\Microsoft\WinGet\Links\claude.exe"      # winget
)
$exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $exe) {
    Write-Host 'Not in the usual places - searching your user folder (can take a minute)...'
    # Skip the copy bundled inside the VS Code extension: its folder name changes
    # with every extension update, so putting it on PATH would break later.
    $exe = Get-ChildItem $env:USERPROFILE -Filter claude.exe -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notlike '*\.vscode\extensions\*' } |
        Select-Object -First 1 -ExpandProperty FullName
}

Write-Host ''
if (-not $exe) {
    Write-Host 'NOT FOUND - Claude Code is not installed yet (or the install did not finish).'
    Write-Host 'Open PowerShell and run:   winget install Anthropic.ClaudeCode'
    Write-Host 'then double-click this file again.'
    exit 1
}

$dir = Split-Path $exe
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $userPath) { $userPath = '' }

if (($userPath -split ';') -contains $dir) {
    Write-Host "FOUND: $exe"
    Write-Host 'That folder is already on your PATH.'
} else {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $dir).TrimStart(';'), 'User')
    Write-Host "FOUND: $exe"
    Write-Host "Added $dir to your PATH."
}
Write-Host ''
Write-Host 'Now close ALL PowerShell and VS Code windows, reopen VS Code, and click the Claude icon.'

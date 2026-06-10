$ErrorActionPreference = "Stop"

$checks = @(
    @{ Name = "Node npx"; Command = "npx" },
    @{ Name = "uvx"; Command = "uvx" },
    @{ Name = "Copilot CLI"; Command = "copilot" }
)

foreach ($check in $checks) {
    $cmd = Get-Command $check.Command -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        Write-Host "[missing] $($check.Name)" -ForegroundColor Red
    }
    else {
        Write-Host "[ok] $($check.Name): $($cmd.Source)" -ForegroundColor Green
    }
}
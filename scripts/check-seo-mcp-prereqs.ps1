$ErrorActionPreference = "Stop"

$checks = @(
    @{ Name = "Node npx"; Command = "npx" },
    @{ Name = "uvx"; Command = "uvx" },
    @{ Name = "Python launcher"; Command = "py" }
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

Write-Host "" 
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Run .\\scripts\\setup-search-console-mcp.ps1 for GSC login" -ForegroundColor White
Write-Host "2. Run .\\scripts\\setup-search-console-mcp.ps1 -Engine ga4 for GA4 account setup in the suite server" -ForegroundColor White
Write-Host "3. Restart MCP servers in VS Code with 'MCP: List Servers'" -ForegroundColor White
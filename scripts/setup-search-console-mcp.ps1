param(
    [ValidateSet("google", "ga4")]
    [string]$Engine = "google"
)

$ErrorActionPreference = "Stop"

$npx = (Get-Command npx -ErrorAction Stop).Source

if ($Engine -eq "ga4") {
    & $npx "search-console-mcp" "setup" "--engine=ga4"
    exit $LASTEXITCODE
}

& $npx "search-console-mcp" "setup"
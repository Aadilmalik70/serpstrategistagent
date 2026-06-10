$ErrorActionPreference = "Stop"

$status = [ordered]@{
    searchConsoleSuite = [ordered]@{
        state = "unknown"
        detail = "not checked"
    }
    ga4Official = [ordered]@{
        state = "unknown"
        detail = "not checked"
    }
    serpapi = [ordered]@{
        state = "unknown"
        detail = "not checked"
    }
}

try {
    $npx = (Get-Command npx -ErrorAction Stop).Source
    $accountsRaw = & $npx "-y" "search-console-mcp" "accounts" "list" 2>$null | Out-String
    if ($accountsRaw -match '"accounts"') {
        $status.searchConsoleSuite.state = "ready"
        $status.searchConsoleSuite.detail = "Search Console accounts are available."
    }
    else {
        $status.searchConsoleSuite.state = "auth-needed"
        $status.searchConsoleSuite.detail = "Search Console CLI responded without saved accounts."
    }
}
catch {
    $status.searchConsoleSuite.state = "error"
    $status.searchConsoleSuite.detail = $_.Exception.Message
}

$ga4Creds = $env:GOOGLE_APPLICATION_CREDENTIALS
$ga4Project = if ([string]::IsNullOrWhiteSpace($env:GOOGLE_PROJECT_ID)) { $env:GOOGLE_CLOUD_PROJECT } else { $env:GOOGLE_PROJECT_ID }

if ([string]::IsNullOrWhiteSpace($ga4Creds)) {
    $status.ga4Official.state = "blocked"
    $status.ga4Official.detail = "GOOGLE_APPLICATION_CREDENTIALS is not set."
}
elseif (-not (Test-Path $ga4Creds)) {
    $status.ga4Official.state = "blocked"
    $status.ga4Official.detail = "Credential file path does not exist."
}
elseif ([string]::IsNullOrWhiteSpace($ga4Project)) {
    $status.ga4Official.state = "blocked"
    $status.ga4Official.detail = "GOOGLE_PROJECT_ID is not set."
}
else {
    $status.ga4Official.state = "configured"
    $status.ga4Official.detail = "Credential path and project env are present. API enablement still needs runtime confirmation."
}

if ([string]::IsNullOrWhiteSpace($env:SERPAPI_API_KEY)) {
    $status.serpapi.state = "blocked"
    $status.serpapi.detail = "SERPAPI_API_KEY is not set."
}
else {
    $status.serpapi.state = "configured"
    $status.serpapi.detail = "SERPAPI_API_KEY is present."
}

$status | ConvertTo-Json -Depth 5
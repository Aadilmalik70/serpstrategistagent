$payload = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($payload)) {
    "{}"
    exit 0
}

$inputJson = $payload | ConvertFrom-Json
$toolName = $inputJson.toolName
$toolArgs = $inputJson.toolArgs | ConvertTo-Json -Compress

$dangerousPatterns = @("git push", "Remove-Item", "rm -rf")

if ($toolName -eq "powershell") {
    foreach ($pattern in $dangerousPatterns) {
        if ($toolArgs -like "*$pattern*") {
            @{ permissionDecision = "deny"; permissionDecisionReason = "Denied by SEO Operator safe-fix policy." } | ConvertTo-Json -Compress
            exit 0
        }
    }
}

"{}"
$ErrorActionPreference = "Stop"

$uvx = (Get-Command uvx -ErrorAction Stop).Source
& $uvx "--from" "analytics-mcp" "analytics-mcp"
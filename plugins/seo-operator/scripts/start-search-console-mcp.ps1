$ErrorActionPreference = "Stop"

$npx = (Get-Command npx -ErrorAction Stop).Source
& $npx "-y" "search-console-mcp"
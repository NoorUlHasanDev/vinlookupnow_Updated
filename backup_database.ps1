$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $PSScriptRoot "backups"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
Copy-Item (Join-Path $PSScriptRoot "database.db") (Join-Path $backupDir "database-$stamp.db") -ErrorAction Stop
Write-Host "Database backup created: $backupDir\database-$stamp.db"

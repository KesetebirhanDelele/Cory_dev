param(
  [Parameter(Mandatory = $true)] [string]$SourceDsn,   # Use key/value DSN (recommended)
  [string]$OutDir = "backups",
  [string[]]$Schemas = @("public","dev_nexus")
)

$ErrorActionPreference = "Stop"

# Ensure pg_dump exists
Get-Command pg_dump | Out-Null

# Ensure output folder
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }

# Timestamped filename
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$dumpPath = Join-Path $OutDir ("cory_backup_{0}.dump" -f $ts)

# Build --schema flags
$schemaFlags = @()
$Schemas | ForEach-Object { $schemaFlags += @("--schema", $_) }

# If using Supabase and key/value DSN, ensure sslmode=require (no URL-encoding needed)
function Ensure-SslMode([string]$dsn) {
  if ($dsn -match '^\s*host=.*supabase\.(co|com).*' -and ($dsn -notmatch 'sslmode\s*=')) {
    return ($dsn.Trim() + " sslmode=require")
  }
  return $dsn
}

# Detect key/value vs URI
$isKeyValue = ($SourceDsn -match '(^\s*host=)|(\sdbname=)')

if ($isKeyValue) {
  $SourceDsn = Ensure-SslMode $SourceDsn
  Write-Host "Dumping schemas [$($Schemas -join ', ')] to $dumpPath"
  & pg_dump `
    --format=custom `
    --no-owner --no-privileges `
    @schemaFlags `
    --file "$dumpPath" `
    --dbname "$SourceDsn"
} else {
  # URI branch (only if you *really* pass a postgresql:// URI)
  if ($SourceDsn -match '^postgresql://.*supabase\.(co|com)' -and $SourceDsn -notmatch 'sslmode=') {
    if ($SourceDsn -like '*?*') {
      $SourceDsn = $SourceDsn + '&sslmode=require'
    } else {
      $SourceDsn = $SourceDsn + '?sslmode=require'
    }
  }
  Write-Host "Dumping schemas [$($Schemas -join ', ')] to $dumpPath"
  & pg_dump `
    --format=custom `
    --no-owner --no-privileges `
    @schemaFlags `
    --file "$dumpPath" `
    "$SourceDsn"
}

Write-Host "Backup complete: $dumpPath"

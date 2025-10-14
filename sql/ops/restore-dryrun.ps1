param(
  [Parameter(Mandatory=$true)] [string]$TargetAdminDsn,  # server-level DSN with rights to CREATE DATABASE
  [Parameter(Mandatory=$true)] [string]$DumpPath,
  [string]$TempDbPrefix = "cory_restore_test_"
)

$ErrorActionPreference = "Stop"
# Derive server-level parts: strip database from $TargetAdminDsn if present
# We rely on psql/createdb/pg_restore supporting "postgresql://.../postgres" for admin ops.
function New-TempDbName { return "$TempDbPrefix$(Get-Random)" }

$tempDb = New-TempDbName
Write-Host "🧪 Creating temp DB: $tempDb"

# Create database
& psql "$TargetAdminDsn" -v ON_ERROR_STOP=1 -c "CREATE DATABASE $tempDb;"

# Restore into temp DB
$targetDbDsn = "$TargetAdminDsn".TrimEnd('/') -replace "/[^/]*$","/postgres"  # normalize
$targetDbDsn = "$TargetAdminDsn"  # if your DSN already points to the server, keep as-is
$restoreDsn = "$TargetAdminDsn" -replace "/([^/]*)$", "/$tempDb"

Write-Host "📥 Restoring $DumpPath into $restoreDsn"
& pg_restore `
  --no-owner --no-privileges `
  --exit-on-error `
  --verbose `
  --dbname "$restoreDsn" `
  "$DumpPath"

Write-Host "✅ Restore finished into temp DB: $tempDb"
Write-Host "Temp DB DSN: $restoreDsn"
Write-Host "ℹ️  Run scripts/ops/verify.ps1 with -SourceDsn and -TargetDsn to compare."

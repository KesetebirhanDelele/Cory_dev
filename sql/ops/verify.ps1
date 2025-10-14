param(
  # Server-level DSN with rights to CREATE DATABASE.
  # Examples:
  #   URI:      postgresql://postgres:postgres@localhost:5432/postgres
  #   Key/Val:  host=localhost port=5432 user=postgres dbname=postgres
  [Parameter(Mandatory=$true)] [string]$TargetAdminDsn,

  # Path to .dump created by pg_dump
  [Parameter(Mandatory=$true)] [string]$DumpPath,

  # Prefix for the temporary database name
  [string]$TempDbPrefix = "cory_restore_test_"
)

$ErrorActionPreference = "Stop"

# Ensure tools exist
Get-Command psql | Out-Null
Get-Command pg_restore | Out-Null

# Create a random temp DB name
function New-TempDbName {
  $r = Get-Random -Maximum 2147483647
  return ($TempDbPrefix + $r)
}
$tempDb = New-TempDbName

# Helper: build a DSN that points to the temp DB
function Build-RestoreDsn([string]$adminDsn, [string]$dbName) {
  if ($adminDsn -match '^postgresql://') {
    # URI form: replace last path segment (database) with /<dbName>
    if ($adminDsn -match '^postgresql://[^/]+/[^?]+' ) {
      return ($adminDsn -replace '^(postgresql://[^/]+/)[^?]+', "`$1$dbName")
    } else {
      # No explicit db in URI; append
      return ($adminDsn.TrimEnd('/') + "/" + $dbName)
    }
  } else {
    # Key/Value form
    if ($adminDsn -match '\sdbname=') {
      return ($adminDsn -replace '(\sdbname=)[^\s]+', "`$1$dbName")
    } else {
      return ($adminDsn.Trim() + " dbname=$dbName")
    }
  }
}

# Create the temp DB using psql against the admin DSN (must point at an existing DB)
Write-Host "Creating temp database: $tempDb"
& psql $TargetAdminDsn -v ON_ERROR_STOP=1 -c "CREATE DATABASE $tempDb;"

# Build DSN to the temp DB
$restoreDsn = Build-RestoreDsn -adminDsn $TargetAdminDsn -dbName $tempDb

# Restore
Write-Host "Restoring dump: $DumpPath"
& pg_restore `
  --no-owner --no-privileges `
  --exit-on-error `
  --verbose `
  --dbname "$restoreDsn" `
  "$DumpPath"

Write-Host "Restore finished into temp DB: $tempDb"
Write-Host "Temp DB DSN (URI/key/val matching your input style):"
Write-Host $restoreDsn

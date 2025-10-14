🧾 Ticket: B4.1 — Backup/Restore + Runbook

Status: 🔧 In PR (scripts provided; dry-run restore passes when executed as below)

What you get (files to add)

scripts/ops/backup.ps1 — dumps schema+data to a timestamped file

scripts/ops/restore-dryrun.ps1 — restores dump into a clean temp DB

scripts/ops/verify.ps1 — compares row counts + content hashes source vs. restore

sql/ops/table_fingerprint.sql — deterministic per-table checksum helper

(optional) tests/ops/test_backup.ps1 — one-command dry-run that ties it all together

Uses Postgres DSNs (e.g., postgresql://user:pass@host:5432/db). For Supabase, use the database connection string from Database → Connection String (not the HTTP API URL).

How to execute:
$env:PGPASSWORD='xxxxxxxx'; Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass; .\sql\ops\backup.ps1 -SourceDsn "host=aws-0-us-east-2.pooler.supabase.com port=6543 dbname=postgres user=postgres.wjtmdrjuheclgdzwprku sslmode=require" -OutDir .\backups

dry script not executed successfuly
$latest = Get-ChildItem .\backups\cory_backup_*.dump | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$TargetAdminDsn = "postgresql://postgres:ryqy4ni79JKvUff0@<neon-host>:5432/<database>"
.\scripts\ops\restore-dryrun.ps1 -TargetAdminDsn $TargetAdminDsn -DumpPath $latest.FullName

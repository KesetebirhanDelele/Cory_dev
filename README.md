# Run below command in Powershell to get latest folder/file structure of working repo
## Run this first if not in Cory_dev directory: 
### PS C:\Users\keset\OneDrive\Documents\Internship\Cory_dev>
$Exclude=@('.git','.testenv','node_modules','dist','build','.venv','.idea','.vscode','__pycache__');$root=(Get-Location).Path;$paths=Get-ChildItem -Recurse -Force | Where-Object{ $segs=$_.FullName.Substring($root.Length).Trim('\').Split('\'); ($segs|Where-Object{ $Exclude -contains $_ }).Count -eq 0 } | ForEach-Object{ $_.FullName.Substring($root.Length+1) } | Sort-Object;$paths | Out-File _repo_files_all.txt -Encoding utf8;"Paths written: $($paths.Count)"

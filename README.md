# Run below command in Powershell to get latest folder/file structure of working repo
## Run this first if not in Cory_dev directory: 
### PS C:\Users\keset\OneDrive\Documents\Internship\Cory_dev>
$Exclude=@('.git','.testenv','node_modules','dist','build','.venv','.idea','.vscode','__pycache__');$root=(Get-Location).Path;$paths=Get-ChildItem -Recurse -Force | Where-Object{ $segs=$_.FullName.Substring($root.Length).Trim('\').Split('\'); ($segs|Where-Object{ $Exclude -contains $_ }).Count -eq 0 } | ForEach-Object{ $_.FullName.Substring($root.Length+1) } | Sort-Object;$paths | Out-File _repo_files_all.txt -Encoding utf8;"Paths written: $($paths.Count)"


# Connecting to Supabase
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
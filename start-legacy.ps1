$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502

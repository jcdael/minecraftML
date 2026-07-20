$ErrorActionPreference = "Stop"
$env:BRAIN_DATA_DIR='C:\Users\noahj\Downloads\Minecraft ML\data\manual-launch-data'
$env:BRAIN_PORT='8776'
$env:PYTHONPATH='C:\Users\noahj\Downloads\Minecraft ML\brain\.venv\Lib\site-packages;' + $env:PYTHONPATH
Set-Location 'C:\Users\noahj\Downloads\Minecraft ML\brain'
& 'C:\Users\noahj\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' main.py

$ErrorActionPreference = "Stop"
$env:ADAPTER_LIFECYCLE_LOG='C:\Users\noahj\Downloads\Minecraft ML\data\smoke-12001\eval-12001-adapter-lifecycle.jsonl'
$env:MINECRAFT_PORT='25660'
$env:DIRECT_GOAL='bootstrap 1 iron_ingot'
$env:BRAIN_DATA_DIR='C:\Users\noahj\Downloads\Minecraft ML\data\smoke-12001'
$env:PYTHON_EXE='C:\Users\noahj\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH='C:\Users\noahj\Downloads\Minecraft ML\brain\.venv\Lib\site-packages;C:\Users\noahj\Downloads\Minecraft ML\brain\.venv\Lib\site-packages;'
Set-Location 'C:\Users\noahj\Downloads\Minecraft ML\adapter'
& 'C:\Users\noahj\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' index.js

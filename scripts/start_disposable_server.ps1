param(
    [string]$WorldName = "ai-disposable-world",
    [int]$Seed = 12001,
    [string]$ServerIp = "127.0.0.1",
    [int]$ServerPort = 25565,
    [string]$WorldTemplatePath = "",
    [switch]$Peaceful,
    [switch]$ResetWorld
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ServerDir = Join-Path $Root "server"
$ServerJar = Join-Path $ServerDir "server.jar"
$Properties = Join-Path $ServerDir "server.properties"
$ExampleProperties = Join-Path $ServerDir "server.properties.example"
$Eula = Join-Path $ServerDir "eula.txt"
$Java = Get-ChildItem -Path (Join-Path $ServerDir "java21") -Recurse -Filter java.exe -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not (Test-Path $ServerJar)) {
    throw "Missing $ServerJar. Download the official Minecraft Java 1.21.4 server jar first."
}
if (-not $Java) {
    throw "Missing project-local Java 21 under server\java21."
}
if (-not (Test-Path $Properties)) {
    Copy-Item -LiteralPath $ExampleProperties -Destination $Properties
}
if (-not (Test-Path $Eula) -or -not (Select-String -LiteralPath $Eula -Pattern '^eula=true$' -Quiet)) {
    throw "Minecraft EULA is not accepted. Read server\eula.txt and set eula=true only if you personally accept Mojang's EULA."
}

$WorldPath = Join-Path $ServerDir $WorldName
$ResolvedServer = (Resolve-Path -LiteralPath $ServerDir).Path
$DestinationParent = Split-Path -Parent $WorldPath
if (-not (Test-Path $DestinationParent)) {
    New-Item -ItemType Directory -Force -Path $DestinationParent | Out-Null
}
$ResolvedDestinationParent = (Resolve-Path -LiteralPath $DestinationParent).Path
if (-not $ResolvedDestinationParent.StartsWith($ResolvedServer, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use world path outside server directory: $WorldPath"
}
if ($ResetWorld -and (Test-Path $WorldPath)) {
    $ResolvedWorld = (Resolve-Path -LiteralPath $WorldPath).Path
    if (-not $ResolvedWorld.StartsWith($ResolvedServer, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove unexpected world path: $ResolvedWorld"
    }
    Remove-Item -LiteralPath $ResolvedWorld -Recurse -Force
}
if ($WorldTemplatePath) {
    if (-not (Test-Path $WorldTemplatePath)) {
        throw "World template path does not exist: $WorldTemplatePath"
    }
    $ResolvedTemplate = (Resolve-Path -LiteralPath $WorldTemplatePath).Path
    if (-not (Test-Path (Join-Path $ResolvedTemplate "level.dat"))) {
        throw "World template is missing level.dat: $ResolvedTemplate"
    }
    if (Test-Path $WorldPath) {
        throw "World path already exists; pass -ResetWorld before copying a template: $WorldPath"
    }
    Copy-Item -LiteralPath $ResolvedTemplate -Destination $WorldPath -Recurse -Force
}

$content = Get-Content -LiteralPath $Properties
$content = $content | ForEach-Object {
    if ($_ -match '^level-name=') { "level-name=$WorldName" }
    elseif ($_ -match '^level-seed=') { "level-seed=$Seed" }
    elseif ($_ -match '^server-ip=') { "server-ip=$ServerIp" }
    elseif ($_ -match '^server-port=') { "server-port=$ServerPort" }
    elseif ($_ -match '^online-mode=') { "online-mode=false" }
    elseif ($_ -match '^enforce-secure-profile=') { "enforce-secure-profile=false" }
    elseif ($_ -match '^use-native-transport=') { "use-native-transport=false" }
    elseif ($Peaceful -and $_ -match '^difficulty=') { "difficulty=peaceful" }
    elseif ($Peaceful -and $_ -match '^spawn-monsters=') { "spawn-monsters=false" }
    else { $_ }
}
Set-Content -LiteralPath $Properties -Value $content -Encoding ASCII

Push-Location $ServerDir
try {
    & $Java.FullName "-Djava.net.preferIPv4Stack=true" -Xmx1G -Xms512M -jar $ServerJar nogui
}
finally {
    Pop-Location
}

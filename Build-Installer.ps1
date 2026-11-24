param(
    [string]$Version = '1.1.0',
    [string]$Python = 'python.exe',
    [string]$InnoCompiler,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist')
)

$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Use a numeric version such as 1.1.0.' }
$output = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
if (-not $InnoCompiler) {
    $programFilesX86 = [Environment]::GetFolderPath('ProgramFilesX86')
    $perUser = Join-Path $env:LOCALAPPDATA 'Programs'
    $candidates = foreach ($base in @($programFilesX86, $perUser, $env:ProgramFiles)) {
        foreach ($edition in @('Inno Setup 7', 'Inno Setup 6')) {
            Join-Path $base "$edition\ISCC.exe"
        }
    }
    $InnoCompiler = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $InnoCompiler -or -not (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
    throw 'Install Inno Setup or specify the full path with -InnoCompiler.'
}

$payloadRoot = Join-Path $project '.build\installer-payload'
$payload = Join-Path $payloadRoot 'TunnelGuard'
$source = Join-Path $project 'installer\TunnelGuard.iss'
New-Item -ItemType Directory -Path $output -Force | Out-Null
& (Join-Path $project 'Build-TunnelGuard.ps1') -OutputDirectory $payloadRoot -Python $Python -OneDirectory | Out-Host

$previousPythonPath = $env:PYTHONPATH
try {
    $runtime = Join-Path $project '.build\translation-runtime'
    if (Test-Path -LiteralPath $runtime -PathType Container) {
        $env:PYTHONPATH = ($runtime, $previousPythonPath | Where-Object { $_ }) -join ';'
    }
    & $Python -B (Join-Path $project 'scripts\collect_notices.py') (Join-Path $payload 'licenses')
    if ($LASTEXITCODE -ne 0) { throw 'Could not collect dependency licenses.' }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

& $InnoCompiler "/DProjectDir=$project" "/DPayloadDir=$payload" "/DReleaseDir=$output" "/DReleaseVersion=$Version" $source
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }

$installer = Get-Item -LiteralPath (Join-Path $output "TunnelGuard-Setup-$Version-x64.exe")
$hash = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $($installer.Name)" | Set-Content -LiteralPath (Join-Path $output 'SHA256SUMS.txt') -Encoding ASCII
$installer

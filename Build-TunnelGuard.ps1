param(
    [string]$OutputDirectory = $PSScriptRoot,
    [string]$Python = 'python.exe',
    [switch]$OneDirectory
)

$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$output = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
$build = Join-Path $project '.build'
$icon = Join-Path $project 'TunnelGuard.ico'
$model = Join-Path $project 'translation_model'
if (-not (Test-Path -LiteralPath (Join-Path $model 'model/model.bin') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $model 'source.spm') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $model 'target.spm') -PathType Leaf)) {
    throw 'The offline model is missing. Run python scripts/prepare_translation_model.py first.'
}
New-Item -ItemType Directory -Path $build -Force | Out-Null
$previousCache = $env:PYINSTALLER_CONFIG_DIR
$previousTcl = $env:TCL_LIBRARY
$previousTk = $env:TK_LIBRARY
$previousPythonPath = $env:PYTHONPATH
$previousPath = $env:Path

Push-Location -LiteralPath $project
try {
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $build 'cache'
    $runtime = Join-Path $build 'translation-runtime'
    if (Test-Path -LiteralPath $runtime -PathType Container) {
        $env:PYTHONPATH = ($runtime, $previousPythonPath | Where-Object { $_ }) -join ';'
    }
    $pythonBase = & $Python -B -c 'import sys; print(sys.base_prefix)'
    if ($LASTEXITCODE -ne 0) { throw 'Python could not report its installation directory.' }
    $tcl = Join-Path $pythonBase 'tcl/tcl8.6'
    $tk = Join-Path $pythonBase 'tcl/tk8.6'
    if ((Test-Path -LiteralPath $tcl -PathType Container) -and (Test-Path -LiteralPath $tk -PathType Container)) {
        $env:TCL_LIBRARY = $tcl
        $env:TK_LIBRARY = $tk
    }

    $system = Join-Path $env:SystemRoot 'System32'
    $pythonDirectory = Split-Path -Parent (Get-Command $Python -CommandType Application | Select-Object -First 1 -ExpandProperty Source)
    $env:Path = "$system;$($env:SystemRoot);$pythonDirectory"
    # Keep the C++ runtime consistent. Other tools on PATH may include older copies.
    $runtimeBinaries = @()
    foreach ($name in @('msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll','vcruntime140.dll','vcruntime140_1.dll')) {
        $library = Join-Path $system $name
        if (-not (Test-Path -LiteralPath $library -PathType Leaf)) {
            throw "The Microsoft Visual C++ x64 runtime is missing $name."
        }
        $runtimeBinaries += '--add-binary', "$library;."
    }

    & $Python -B -m unittest -q
    if ($LASTEXITCODE -ne 0) { throw 'TunnelGuard tests failed.' }

    $layout = if ($OneDirectory) { '--onedir' } else { '--onefile' }
    & $Python -B -m PyInstaller --clean --noconfirm $layout --windowed --noupx --name TunnelGuard `
        --exclude-module torch --exclude-module tensorflow --exclude-module transformers `
        --exclude-module pandas --exclude-module scipy --exclude-module pytest `
        --exclude-module matplotlib --exclude-module IPython --exclude-module jupyter_client `
        --exclude-module pydantic --exclude-module requests --exclude-module huggingface_hub `
        --exclude-module keras --exclude-module onnxruntime --exclude-module sklearn --exclude-module cv2 `
        --collect-binaries ctranslate2 @runtimeBinaries --icon $icon --add-data "$icon;." --add-data "$model;translation_model" `
        --workpath (Join-Path $build 'work') `
        --specpath $build --distpath $output 'tunnelguard.py'
    if ($LASTEXITCODE -ne 0) { throw 'TunnelGuard build failed.' }

    $executable = if ($OneDirectory) { 'TunnelGuard/TunnelGuard.exe' } else { 'TunnelGuard.exe' }
    Get-Item -LiteralPath (Join-Path $output $executable)
} finally {
    $env:PYINSTALLER_CONFIG_DIR = $previousCache
    $env:TCL_LIBRARY = $previousTcl
    $env:TK_LIBRARY = $previousTk
    $env:PYTHONPATH = $previousPythonPath
    $env:Path = $previousPath
    Pop-Location
}

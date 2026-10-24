# build_exe.ps1 —— 打包 PasteBoard.exe（开发期脚本，不入库的产物在 dist/）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1            # 默认文件夹版（推荐）
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Install   # 允许联网安装 PyInstaller
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1 -SkipTests # 快速重打包
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Onefile   # 单文件版（解压到 %TEMP%，不推荐）
#
# 产物：
#   默认（文件夹）dist\PasteBoard\PasteBoard.exe  —— 拷贝整个 PasteBoard 文件夹使用
#   -Onefile       dist\PasteBoard.exe             —— 单文件，启动时解压到系统临时目录
#
# 为什么默认文件夹版：单文件 exe 启动时要把自身解压到 %TEMP%，在受限账户或
# 杀软环境下可能失败（报 Could not create temporary directory!）。文件夹版没有
# 解压过程，普通用户双击即可运行，历史数据存放在程序目录的 data/ 下。

param(
    [switch]$Install,
    [switch]$SkipTests,
    [switch]$Onefile
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# ---- 1. 找 Python ---------------------------------------------------
# 顺序：环境变量 PASTEBOARD_PYTHON → PATH 里的 python（须带 tkinter 与 Pillow）
$Py = $env:PASTEBOARD_PYTHON
if (-not $Py) {
    $candidate = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($candidate) {
        & $candidate -c "import tkinter, PIL" 2>$null
        if ($LASTEXITCODE -eq 0) { $Py = $candidate }
    }
}
if (-not $Py) {
    Write-Error '找不到可用的 Python。请安装 Python 3.10+（需含 tkinter 与 Pillow）并加入 PATH，或用环境变量 PASTEBOARD_PYTHON 指定解释器完整路径。'
    exit 1
}
Write-Host "[1/6] Python: $Py"

# ---- 2. 图标与版本信息 ----------------------------------------------
$Icon = Join-Path $Root 'assets\app.ico'
if (-not (Test-Path $Icon)) {
    Write-Host '[2/6] 生成图标 assets/app.ico'
    & $Py (Join-Path $Root 'make_icon.py')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "[2/6] 图标已存在: $Icon"
}

Write-Host '[2/6] 生成版本资源 build/version_info.txt'
& $Py (Join-Path $Root 'make_version_info.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$VersionFile = Join-Path $Root 'build\version_info.txt'

# ---- 3. PyInstaller -------------------------------------------------
$null = & $Py -m PyInstaller --version 2>&1
if ($LASTEXITCODE -ne 0) {
    if (-not $Install) {
        Write-Host '[3/6] 未安装 PyInstaller。'
        Write-Host '      首次打包需要联网安装一次，请重试并加 -Install：'
        Write-Host '      powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Install'
        exit 1
    }
    Write-Host '[3/6] 安装 PyInstaller（需联网，仅开发期使用）'
    & $Py -m pip install --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$PyInstallerVersion = (& $Py -m PyInstaller --version) | Select-Object -Last 1
Write-Host "[3/6] PyInstaller $PyInstallerVersion"

# ---- 4. 单元测试 ----------------------------------------------------
if ($SkipTests) {
    Write-Host '[4/6] 跳过单元测试（-SkipTests）'
} else {
    Write-Host '[4/6] 运行单元测试'
    & $Py -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) {
        Write-Error '单元测试未通过，已中止打包。'
        exit 1
    }
}

# ---- 5. 打包 --------------------------------------------------------
# 默认 --onedir（文件夹绿色版），只有显式 -Onefile 才打单文件。
$Mode = if ($Onefile) { '--onefile' } else { '--onedir' }
Write-Host "[5/6] 打包中（$Mode）..."
& $Py -m PyInstaller `
    --noconfirm --clean --windowed $Mode `
    --name PasteBoard `
    --icon 'assets\app.ico' `
    --version-file $VersionFile `
    --add-data 'assets;assets' `
    app/main.py
if ($LASTEXITCODE -ne 0) {
    Write-Error '打包失败。可改用 -Onefile 回退（见 docs/07-release.md 第 5 节）。'
    exit $LASTEXITCODE
}

# ---- 6. 校验产物 ----------------------------------------------------
$Exe = if ($Onefile) { Join-Path $Root 'dist\PasteBoard.exe' } else { Join-Path $Root 'dist\PasteBoard\PasteBoard.exe' }
if (-not (Test-Path $Exe)) {
    Write-Error "未找到产物: $Exe"
    exit 1
}
$SizeMb = [math]::Round((Get-Item $Exe).Length / 1MB, 1)
Write-Host ''
Write-Host "[6/6] ✅ 打包完成：$Exe（exe $SizeMb MB）"
if (-not $Onefile) {
    $FolderMb = [math]::Round(((Get-ChildItem (Split-Path $Exe) -Recurse | Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
    Write-Host "   整个文件夹约 $FolderMb MB，把整个 PasteBoard 文件夹拷给别人双击 PasteBoard.exe 即可。"
}
Write-Host '   冒烟步骤见 docs/07-release.md 第 4 节。'

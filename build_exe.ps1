# build_exe.ps1 —— 打包 PasteBoard.exe（开发期脚本，不入库的产物在 dist/）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1            # 首次会提示安装 PyInstaller
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Install   # 允许联网安装 PyInstaller
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1 -SkipTests # 快速重打包
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Onedir    # 回退为文件夹版（启动更快）
#
# 产物：
#   默认（单文件）dist\PasteBoard.exe
#   -Onedir（文件夹）dist\PasteBoard\PasteBoard.exe

param(
    [switch]$Install,
    [switch]$SkipTests,
    [switch]$Onedir
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# ---- 1. 找 Python ---------------------------------------------------
$Py = 'C:\Users\lenovo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path $Py)) {
    $Py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $Py) {
        Write-Error '找不到 Python，请先安装或修改本脚本里的 $Py 路径。'
        exit 1
    }
}
Write-Host "[1/5] Python: $Py"

# ---- 2. 图标 --------------------------------------------------------
$Icon = Join-Path $Root 'assets\app.ico'
if (-not (Test-Path $Icon)) {
    Write-Host '[2/5] 生成图标 assets/app.ico'
    & $Py (Join-Path $Root 'make_icon.py')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "[2/5] 图标已存在: $Icon"
}

# ---- 3. PyInstaller -------------------------------------------------
$null = & $Py -m PyInstaller --version 2>&1
if ($LASTEXITCODE -ne 0) {
    if (-not $Install) {
        Write-Host '[3/5] 未安装 PyInstaller。'
        Write-Host '      首次打包需要联网安装一次，请重试并加 -Install：'
        Write-Host '      powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Install'
        exit 1
    }
    Write-Host '[3/5] 安装 PyInstaller（需联网，仅开发期使用）'
    & $Py -m pip install --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$PyInstallerVersion = (& $Py -m PyInstaller --version) | Select-Object -Last 1
Write-Host "[3/5] PyInstaller $PyInstallerVersion"

# ---- 4. 单元测试 ----------------------------------------------------
if ($SkipTests) {
    Write-Host '[4/5] 跳过单元测试（-SkipTests）'
} else {
    Write-Host '[4/5] 运行单元测试'
    & $Py -m unittest discover -s tests
    if ($LASTEXITCODE -ne 0) {
        Write-Error '单元测试未通过，已中止打包。'
        exit 1
    }
}

# ---- 5. 打包 --------------------------------------------------------
$Mode = if ($Onedir) { '--onedir' } else { '--onefile' }
Write-Host "[5/5] 打包中（$Mode）..."
& $Py -m PyInstaller `
    --noconfirm --clean --windowed $Mode `
    --name PasteBoard `
    --icon 'assets\app.ico' `
    --add-data 'assets;assets' `
    app/main.py
if ($LASTEXITCODE -ne 0) {
    Write-Error '打包失败。可改用 -Onedir 回退（见 docs/07-release.md 第 5 节）。'
    exit $LASTEXITCODE
}

$Exe = if ($Onedir) { Join-Path $Root 'dist\PasteBoard\PasteBoard.exe' } else { Join-Path $Root 'dist\PasteBoard.exe' }
if (-not (Test-Path $Exe)) {
    Write-Error "未找到产物: $Exe"
    exit 1
}
$SizeMb = [math]::Round((Get-Item $Exe).Length / 1MB, 1)
Write-Host ''
Write-Host "✅ 打包完成：$Exe（exe $SizeMb MB）"
if ($Onedir) {
    $FolderMb = [math]::Round(((Get-ChildItem (Split-Path $Exe) -Recurse | Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
    Write-Host "   整个文件夹约 $FolderMb MB，拷贝整个 PasteBoard 文件夹使用。"
}
Write-Host '   冒烟步骤见 docs/07-release.md 第 4 节；把产物拷到空目录双击即可运行。'

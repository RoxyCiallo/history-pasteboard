# 07 打包与发布

- 版本：v1.1（2026-10-21，随 0.2.0 更新）
- 产物：`dist/PasteBoard/`（文件夹绿色版，双击 `PasteBoard.exe` 运行）

## 1. 前置条件

| 项 | 说明 |
|---|---|
| 网络 | 首次打包需联网安装 PyInstaller（唯一一次联网） |
| 磁盘 | `dist/` + `build/` 约 150–250MB 临时占用 |
| 权限 | 打包机无需管理员；**运行方也不需要管理员** |

安装打包工具（只装到本机已用 Python 中）：

```powershell
$py = 'python'   # 换成你自己的解释器完整路径也可以
& $py -m pip install --upgrade pyinstaller
```

> 在本项目的沙箱开发环境里，PyInstaller 装在系统 site-packages 会被文件沙箱拒绝，
> 实际做法是装到项目内目录并在**同一条命令**里完成打包，例如：
> `pip install --target build/pylibs-v5 pyinstaller` 然后立刻
> `python -m PyInstaller ...`（详见 devlog 2026-10-21 的打包记录）。
> 正常机器上不需要这么绕。

## 2. 打包步骤

```powershell
# 0) 更新版本号：app/config.py 的 APP_VERSION，并在 CHANGELOG.md 增加条目
#    1) 生成图标与版本资源（脚本会自动做，手工执行也可以）
& $py make_icon.py
& $py make_version_info.py

# 2) 全量测试必须先过
& $py -m unittest discover -s tests -v

# 3) 打包（推荐用脚本）
powershell -ExecutionPolicy Bypass -File build_exe.ps1
```

`build_exe.ps1` 的参数：

| 参数 | 作用 |
|---|---|
| 无 | 默认打**文件夹版**（onedir），推荐 |
| `-Onefile` | 打单文件版，启动解压到 `%TEMP%`，不推荐（见 §8） |
| `-Install` | 首次联网安装 PyInstaller |
| `-SkipTests` | 跳过单元测试，快速重打包 |

等价的 PyInstaller 命令（文件夹版）：

```powershell
& $py -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name PasteBoard `
    --icon "$PWD\assets\app.ico" `
    --version-file "$PWD\build\version_info.txt" `
    --specpath build --workpath build\pyi-work --distpath dist `
    --add-data "$PWD\assets;assets" `
    "$PWD\app\main.py"
```

参数说明：

| 参数 | 作用 |
|---|---|
| `--windowed` | 不弹黑框控制台 |
| `--onedir` | 文件夹版：无解压过程，受限账户也能运行 |
| `--version-file` | 把版本/产品名写进 exe 属性（由 `make_version_info.py` 生成） |
| `--specpath build` | 把 `.spec` 放进 build/，不污染根目录 |
| `--add-data "…assets;assets"` | 资源打进包（Windows 用分号）；**用了 `--specpath` 后必须写绝对路径**，否则会按 spec 所在目录解析而找不到 |
| `--clean --noconfirm` | 清除缓存、覆盖旧产物 |

## 3. 产物与分发

```
dist/
└─ PasteBoard/
   ├─ PasteBoard.exe        # 5.1 MB，双击运行
   └─ _internal/            # 运行时依赖（74.2 MB 合计）
```

0.2.0 实测（2026-10-21，PyInstaller 6.22.3）：exe **5.1 MB**，整个文件夹 **74.2 MB**，
exe 属性显示 `FileVersion 0.2.0`、`ProductName 历史粘贴板`。

分发方式：**把整个 `PasteBoard` 文件夹拷贝给对方**，双击里面的 `PasteBoard.exe`。
首次运行后在同目录生成：

```
PasteBoard/
├─ PasteBoard.exe
├─ _internal/
└─ data/
   ├─ history.db
   ├─ history.db-wal / -shm
   ├─ images/     # 原图
   ├─ thumbs/     # 缩略图
   └─ app.log
```

连 `data/` 一起拷走就是「带历史的迁移」；卸载 = 删除整个文件夹。
`data/` 不随程序退出删除，只由保留期规则清理过期记录。

> **为什么默认文件夹版**：单文件 exe 每次启动要先把自己解压到 `%TEMP%`，
> 在受限账户或杀软策略下会失败（用户实测报 `Could not create temporary directory!`，
> 必须管理员运行）。文件夹版没有解压过程，普通用户双击即可。

## 4. 冒烟验证（每次打包必做）

| ID | 步骤 | 预期 |
|---|---|---|
| R1 | 把 `PasteBoard` 文件夹拷到全新目录双击 exe | 3s 内出窗口，无控制台黑框，无报错弹窗 |
| R2 | 复制文字 → 查看列表 | 出现卡片 |
| R3 | 截图复制 → 查看 | 出现图片卡 |
| R4 | 关闭窗口 → `Ctrl+Shift+V` | 唤出（首次关闭会弹「仍在后台记录」提示） |
| R5 | 点历史卡片 → 切到记事本粘贴 | 内容正确；**窗口保持打开**，状态栏提示已复制 |
| R6 | 复制后再看列表 | **不新增重复卡片**（不回灌） |
| R7 | 长文本卡片点「查看全文」 | 弹窗显示完整内容，可一键复制 |
| R8 | 检查 `data/` | 数据库与图片文件齐全 |
| R9 | 彻底退出 → 任务管理器 | 无残留进程 |

0.2.0 已在开发环境验证：文件夹版从空目录启动，0.9 秒内写出三条日志
（数据目录 `…\PasteBoard\data`、剪贴板监听已启动、全局热键已注册 `Ctrl+Shift+V`），
并创建 `data/history.db`；跨进程复制两条文字被记录（id=1、id=2）；
关闭窗口后主窗口隐藏、进程存活（对应 R1 的启动部分、R2、R8、关闭到后台）。
R4 的唤回、R5–R7 的交互需在真实桌面手动确认。

## 5. 回退方案

若文件夹版产物无法运行：

1. **单文件版**：`powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Onefile`，
   生成 `dist/PasteBoard.exe`（约 30.5 MB）。仅在目标机器 `%TEMP%` 可写时可用。
2. **脚本启动**：新建 `启动.vbs`：
   ```vbs
   CreateObject("WScript.Shell").Run """<Python 目录>\pythonw.exe"" ""<项目目录>\app\main.py""", 0, False
   ```
   交付「文件夹 + 快捷方式」，功能一致，但依赖本机 Python。

两种回退都需在交付说明里写清楚差异。

## 6. 版本号与更新日志

- 规则：`主.次.修订`，功能或行为变化升次版本，缺陷修复升修订号。当前 `0.2.0`。
- 唯一来源：`app/config.py` 的 `APP_VERSION`；设置面板底部显示 `历史粘贴板 v{APP_VERSION}`。
- exe 属性版本由 `make_version_info.py` 从同一常量生成，避免两处不一致。
- **每次发版必须**在 `CHANGELOG.md` 增加一节（新增/变更/修复/已知限制四类）。
- 打包前跑一次 `python make_version_info.py --check` 确认格式。

## 7. 发布说明模板

```markdown
# 历史粘贴板 v0.2.0

## 新增
- 长文本「查看全文」弹窗
- CHANGELOG.md 与 exe 版本属性

## 变更
- 改为文件夹绿色版，普通用户双击即可运行
- 复制后窗口保持打开，状态栏提示
- 从历史复制不再回灌历史

## 已知限制
- 私密内容明文存于本地数据库，密码仅作界面门禁
- 热键与关闭后唤回需在真实桌面确认

## 使用
双击 PasteBoard.exe，Ctrl+Shift+V 唤出。
```

## 8. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 报 `Could not create temporary directory!` | 单文件版解压 `%TEMP%` 失败 | 改用文件夹版（默认产物）；不要用管理员权限绕过 |
| 杀软报毒/拦截 | PyInstaller 产物常见误报 | 加信任；exe 名保持 ASCII |
| 双击无反应 | 之前实例已在运行 | 按 `Ctrl+Shift+V`；或任务管理器结束 `PasteBoard.exe` |
| 热键无反应 | 被其他软件占用 | 状态栏会提示改用备选键；本期不支持自定义热键 |
| 中文路径下启动失败 | 旧版 PyInstaller 兼容问题 | 升级 PyInstaller；或换英文路径 |
| 记录不全 | 剪贴板被占用或超上限 | 查 `data/app.log` |
| 数据目录跑到 AppData | exe 所在目录不可写 | 正常回退；设置面板可查看真实路径 |
| 复制后列表多出一条 | 旧版（0.1）行为 | 0.2.0 已修复，升级即可 |

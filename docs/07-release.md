# 07 打包与发布

- 版本：v1.0
- 日期：2026-10-21
- 产物：`dist/PasteBoard.exe`（单文件、无控制台、绿色免安装）

## 1. 前置条件

| 项 | 说明 |
|---|---|
| 网络 | 首次打包需联网安装 PyInstaller（唯一一次联网） |
| 磁盘 | `dist/` + `build/` 约 100–200MB 临时占用 |
| 权限 | 无需管理员 |

安装打包工具（只装到本机已用 Python 中）：

```powershell
$py = 'C:\Users\lenovo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m pip install --upgrade pyinstaller
```

## 2. 打包步骤

```powershell
# 0) 生成图标（首次或改图标时）
& $py make_icon.py

# 1) 全量测试必须先过
& $py -m unittest discover -s tests -v

# 2) 打包（推荐用脚本，内含回退逻辑）
powershell -ExecutionPolicy Bypass -File build_exe.ps1
```

等价的 PyInstaller 命令：

```powershell
& $py -m PyInstaller --noconfirm --clean --windowed --onefile `
    --name PasteBoard `
    --icon assets/app.ico `
    --add-data "assets;assets" `
    app/main.py
```

参数说明：

| 参数 | 作用 |
|---|---|
| `--windowed` | 不弹黑框控制台 |
| `--onefile` | 单个 exe，便于分发 |
| `--add-data "assets;assets"` | 图标等资源打进包里（Windows 用分号） |
| `--clean --noconfirm` | 清除缓存、覆盖旧产物 |

## 3. 产物与分发

```
dist/
└─ PasteBoard.exe          # 唯一需要分发的文件（约 20–40MB）
```

M7 实测（2026-10-21，PyInstaller 6.22.3）：`dist/PasteBoard.exe` **30.5 MB**。
回退版 `-Onedir` 产物位于 `dist/PasteBoard/PasteBoard.exe` + 依赖文件夹。

首次运行后在 exe 同目录生成：

```
PasteBoard.exe
data/
├─ history.db
├─ history.db-wal / -shm
├─ images/     # 原图
├─ thumbs/     # 缩略图
└─ app.log
```

分发方式：把 `PasteBoard.exe` 拷给对方即可；连 `data/` 一起打包就是「带历史的迁移」。卸载 = 删除该文件夹。

> `--onefile` 每次启动会把自身解压到 `%TEMP%\_MEIxxxx`，因此**启动略慢（约 2–4 秒）**，且要求 `%TEMP%` 可写；
> 若对方机器的临时目录被安全策略锁定，改用 `-Onedir` 版（启动约 0.3 秒，免解压）。

## 4. 冒烟验证（每次打包必做）

| ID | 步骤 | 预期 |
|---|---|---|
| R1 | 把 exe 拷到全新目录（如 `D:\test\`）双击 | 3s 内出窗口，无控制台黑框，无报错弹窗 |
| R2 | 复制文字 → 查看列表 | 出现卡片 |
| R3 | 截图复制 → 查看 | 出现图片卡 |
| R4 | 关闭窗口 → `Ctrl+Shift+V` | 唤出 |
| R5 | 剪切板内容点回剪贴板 → 粘到记事本 | 内容正确 |
| R6 | 置顶一条 → 彻底退出 → 重开 | 仍置顶 |
| R7 | 检查 `data/` | 数据库与图片文件齐全 |
| R8 | 任务管理器 | 退出后无残留进程/CPU 占用 |

M7 已在开发环境验证的部分：`-Onedir` 产物从空目录启动，0.3 秒内写出
「程序启动：数据目录 …」「全局热键已注册：Ctrl+Shift+V」「剪贴板监听已启动」三条日志，
并创建 `data/history.db`、`images/`、`thumbs/`、`app.log`（对应 R1 的目录/日志部分、R7）。
R2–R6、R8 需在真实桌面手动确认（见 `docs/06-test-plan.md` 的待实机项）。

## 5. 回退方案

若 PyInstaller 安装失败或产物无法运行：

1. **降级 onedir**：`powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Onedir`，
   生成 `dist/PasteBoard/PasteBoard.exe` + 依赖目录（启动更快，分发时拷整个 `PasteBoard` 文件夹）。
2. **脚本启动**：新建 `启动.vbs`：
   ```vbs
   CreateObject("WScript.Shell").Run """C:\path\to\pythonw.exe"" ""C:\path\to\app\main.py""", 0, False
   ```
   交付「文件夹 + 快捷方式」，功能一致，但依赖本机 Python。

两种回退都需在交付说明里写清楚差异。

## 6. 版本号

- 规则：`主.次.修订`，如 `1.0.0`。
- 显示位置：设置面板「关于」；同时写入 `app/__init__.py` 的 `__version__`。
- 每次打包前确认版本号与 `devlog` 一致。

## 7. 发布说明模板

```markdown
# 历史粘贴板 v1.0.0

## 新增
- 剪贴板文字/图片自动记录
- 置顶、删除、搜索
- 保留期清理（1/3/5/7 天或自定义）
- 敏感内容二级密码

## 已知限制
- 私密内容以明文存于本地数据库，密码仅作界面门禁
- 无托盘图标，靠 Ctrl+Shift+V 唤出，主界面内退出
- 首次启动约 1–3 秒（单文件解压）

## 使用
双击 PasteBoard.exe，Ctrl+Shift+V 唤出。
```

## 8. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 杀软报毒/拦截 | `--onefile` 自解压行为易被误判 | 加信任；或改用 `--onedir`；exe 名保持 ASCII |
| 双击无反应 | 之前实例已在运行 | 按 `Ctrl+Shift+V`；或任务管理器结束 `PasteBoard.exe` |
| 热键无反应 | 被其他软件占用 | 设置面板换热键 |
| 中文路径下启动失败 | 旧版 PyInstaller 兼容问题 | 升级 PyInstaller；或换英文路径 |
| 记录不全 | 剪贴板被占用或超上限 | 查 `data/app.log` |
| 数据目录跑到 AppData | exe 所在目录不可写 | 正常回退；设置面板可查看真实路径 |

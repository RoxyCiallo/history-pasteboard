# 历史粘贴板 0.2.0

> Windows 本地剪贴板历史工具：复制过的文字和图片不丢，按 `Ctrl+Shift+V` 随时找回、搜索、再粘一次。

- 绿色免安装**文件夹版**，普通用户双击即可运行（无需管理员权限）
- 完全离线，数据只存在本机 `data/` 目录
- 淡蓝色简洁卡片界面

## 功能

| 功能 | 说明 |
|---|---|
| 自动记录 | 后台监听剪贴板，文字与图片都会保存（窗口关闭后仍记录） |
| 时间倒序 | 最近复制的在最上面 |
| 置顶 | 常用内容固定在最前，且永不过期 |
| 搜索 | 输入关键字即时过滤历史 |
| 再次粘贴 | 点一下卡片，内容回到剪贴板并提示；切到目标窗口 `Ctrl+V` 即可（不会重复记入历史） |
| 查看全文 | 超过 3 行的文字可点「查看全文 ›」弹窗阅读并一键复制 |
| 保留期 | 1/3/5/7 天或自定义 1–365 天，过期自动清理 |
| 敏感内容 | 密码类内容自动打码并加锁，输入二级密码才能查看 |
| 热键唤出 | `Ctrl+Shift+V` 随时叫出主界面 |
| 彻底退出 | 主界面底部「彻底退出」才真正结束进程 |

## 快速开始

**使用打包好的文件夹版**

1. 打开 `dist\PasteBoard\`，双击 `PasteBoard.exe`，主界面出现。
2. 正常复制文字、截图，历史自动累积。
3. 关闭窗口只是隐藏；按 `Ctrl+Shift+V` 唤回。
4. 要结束程序，点底部「彻底退出」。

> 整个 `PasteBoard` 文件夹可以拷到任意位置使用；历史数据在文件夹内的 `data\`，随文件夹一起走。

**从源码运行**

```powershell
# 带控制台（便于看日志）
python app/main.py

# 无控制台
pythonw app/main.py
```

> 需要 Python 3.10+，并带 tkinter 与 Pillow；若 `python` 不在 PATH，请换成你自己的解释器完整路径。

**打包**

```powershell
# 默认 onedir 文件夹版（推荐，普通用户可直接运行）
powershell -ExecutionPolicy Bypass -File build_exe.ps1

# 首次需要联网安装 PyInstaller
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Install

# 回退成单文件（会解压到 %TEMP%，权限受限时可能失败）
powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Onefile
```

详见 [docs/07-release.md](docs/07-release.md)。

## 数据与隐私

数据目录：`exe 所在目录\data\`（不可写时回退到 `%LOCALAPPDATA%\PasteBoard\data\`）

```
data/
├─ history.db   记录本体（SQLite）
├─ images/      原图
├─ thumbs/      缩略图
└─ app.log      运行日志
```

- 不联网、不上传、无统计。
- **已知限制**：私密卡片（密码保护的）正文在数据库中以明文保存，二级密码只控制界面显示与复制；能直接读取 `data/history.db` 的人不受密码保护。详见 [docs/08-decisions.md](docs/08-decisions.md) 的 ADR-003。

## 文档索引

| 文档 | 内容 |
|---|---|
| [AGENTS.md](AGENTS.md) | 给开发者/AI 的入口说明：目录地图、约束、工作流程 |
| [CHANGELOG.md](CHANGELOG.md) | 版本更新日志 |
| [docs/01-requirements.md](docs/01-requirements.md) | 需求规格与验收标准 |
| [docs/02-architecture.md](docs/02-architecture.md) | 技术方案、模块、线程、数据库 |
| [docs/03-design-spec.md](docs/03-design-spec.md) | 视觉与交互规范 |
| [docs/04-dev-guide.md](docs/04-dev-guide.md) | 编码规范 |
| [docs/05-roadmap.md](docs/05-roadmap.md) | 里程碑与执行步骤 |
| [docs/06-test-plan.md](docs/06-test-plan.md) | 测试用例与验收清单 |
| [docs/07-release.md](docs/07-release.md) | 打包发布 |
| [docs/08-decisions.md](docs/08-decisions.md) | 技术决策记录 |
| [devlog/](devlog/) | 每日开发日志 |

## 当前状态

- 版本：**0.2.0**（2026-10-21）。完整版本历史见 [CHANGELOG.md](CHANGELOG.md)。
- 阶段：M0–M7 交付完成 + 用户实测反馈修复。
- 已能：后台自动记录文字与图片（重复内容只刷新时间）、圆角卡片列表、搜索过滤、点击卡片复制回剪贴板（**窗口保持打开**且不会回灌历史）、查看全文弹窗、置顶/取消置顶、删除、关闭后继续记录、`Ctrl+Shift+V` 唤回（被占用时自动回退备选键）、重复启动只唤出已有窗口、保留期自动清理、设置面板（保留期/清空历史/数据目录/版本/重置密码）、敏感内容打码与二级密码（错误 5 次冷却 30 秒、空闲 5 分钟自动上锁）、彻底退出。
- 打包产物：`dist\PasteBoard\PasteBoard.exe`（5.1 MB，文件夹共 74.2 MB），exe 版本资源为 0.2.0。
- 进度见 [docs/05-roadmap.md](docs/05-roadmap.md)，已知限制见 [docs/07-release.md](docs/07-release.md) 与 [docs/06-test-plan.md](docs/06-test-plan.md) 的待实机项。

## 系统要求

- Windows 10 / 11 x64
- 无需安装 Python（使用 exe 时）

# 历史粘贴板

> Windows 本地剪贴板历史工具：复制过的文字和图片不丢，按 `Ctrl+Shift+V` 随时找回、搜索、再粘一次。

- 绿色免安装，单个 `PasteBoard.exe`
- 完全离线，数据只存在本机 `data/` 目录
- 淡蓝色简洁卡片界面

## 功能

| 功能 | 说明 |
|---|---|
| 自动记录 | 后台监听剪贴板，文字与图片都会保存（窗口关闭后仍记录） |
| 时间倒序 | 最近复制的在最上面 |
| 置顶 | 常用内容固定在最前，且永不过期 |
| 搜索 | 输入关键字即时过滤历史 |
| 再次粘贴 | 点一下卡片，内容回到剪贴板，切到目标窗口 `Ctrl+V` 即可 |
| 保留期 | 1/3/5/7 天或自定义 1–365 天，过期自动清理 |
| 敏感内容 | 密码类内容自动打码并加锁，输入二级密码才能查看 |
| 热键唤出 | `Ctrl+Shift+V` 随时叫出主界面 |
| 彻底退出 | 主界面底部「彻底退出」才真正结束进程 |

## 快速开始

**使用安装包 / exe**

1. 双击 `PasteBoard.exe`，主界面出现。
2. 正常复制文字、截图，历史自动累积。
3. 关闭窗口只是隐藏；按 `Ctrl+Shift+V` 唤回。
4. 要结束程序，点底部「彻底退出」。

**从源码运行**

```powershell
# 带控制台（便于看日志）
& 'C:\Users\lenovo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe' app/main.py

# 无控制台
& 'C:\Users\lenovo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe' app/main.py
```

**打包成 exe**

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1
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

- 阶段：**M2 系统能力层**已完成（M0 工程底座、M1 数据层、M2 剪贴板监听）。
- 已能后台自动记录文字与图片（含「文件形式复制的图片」），重复内容只刷新时间。
- 界面从 M3 开始做；Ctrl+Shift+V 热键与单实例在 M5。
- 进度见 [docs/05-roadmap.md](docs/05-roadmap.md)。

## 系统要求

- Windows 10 / 11 x64
- 无需安装 Python（使用 exe 时）

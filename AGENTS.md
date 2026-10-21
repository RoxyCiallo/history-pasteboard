# AGENTS.md — 历史粘贴板 项目工作指引

> 本文件是本仓库**唯一的入口说明书**。任何 AI 助手、协作者接手前必须读完本文再动手。
> 本项目没有 CLAUDE.md；若使用 Claude Code，请让它读本文件（规则等价）。

## 1. 项目是什么

Windows 本地剪贴板历史工具：后台常驻记录文字与图片，`Ctrl+Shift+V` 唤出卡片式界面，支持置顶、删除、搜索、保留期自动清理、敏感内容二级密码。交付形态为免安装绿色版 `PasteBoard.exe`。不联网、不上传、单机单用户。

## 2. 目录地图（标准路径）

| 路径 | 作用 | 何时必须更新 |
|---|---|---|
| `AGENTS.md` | 本文件，入口说明书 | 目录结构、命令、约束变更时 |
| `README.md` | 面向使用者的简介与快速开始 | 功能或启动方式变化时 |
| `docs/01-requirements.md` | 需求规格（FR/NFR、验收标准） | 需求变更时（需用户确认） |
| `docs/02-architecture.md` | 技术方案、模块职责、线程模型、数据库 schema | 架构或表结构变更时 |
| `docs/03-design-spec.md` | 视觉与交互规范（色值、字体、尺寸、组件） | UI 改动前先改规范 |
| `docs/04-dev-guide.md` | 编码与协作规范 | 规范本身变化时 |
| `docs/05-roadmap.md` | 里程碑与执行步骤、状态表 | 每完成一个任务后 |
| `docs/06-test-plan.md` | 自动化用例与手动验收清单 | 新增功能/新用例时 |
| `docs/07-release.md` | 打包发布流程与回退方案 | 打包参数或产物变化时 |
| `docs/08-decisions.md` | 技术决策记录 ADR | 每次做重大取舍时追加 |
| `devlog/` | 每日开发日志，文件名 `YYYY-MM-DD.md` | **每天收尾必须写** |
| `devlog/README.md` | 日志规范与写入方法 | 规范变化时 |
| `tools/devlog.py` | 日志自动记录脚本 | 日志格式变化时 |
| `app/` | 程序源码（见 `docs/02`） | 开发时 |
| `assets/` | 图标等静态资源 | 换图标时 |
| `tests/` | 单元测试（纯逻辑，不依赖桌面） | 同步于功能开发 |
| `build_exe.ps1` | 打包脚本 | 打包流程变化时 |
| `data/` | **运行时**数据（`history.db`、`images/`、`thumbs/`、`app.log`），不进版本库 | 不需要手改 |

## 3. 开工前的必读顺序

1. `docs/01-requirements.md` — 要做什么，什么不做。
2. `docs/05-roadmap.md` — 当前处于哪个里程碑，该做什么。
3. `devlog/{今天}.md` — 上次留下的待办与风险（不存在就先创建）。
4. 涉及界面：`docs/03-design-spec.md`；涉及数据结构：`docs/02-architecture.md`。

## 4. 每次会话的工作流程

**开始**
- 读第 3 节四份文档，确认本轮只推进**一个**里程碑内的工作。
- 用 `todo_write` 列出本轮任务，粒度不超过半天。

**开发中**
- 一次只改一个子系统；改完立刻跑对应测试。
- 新文件落地后，登记到第 2 节目录地图。
- 遇到需要用户拍板的取舍：停下来记录到 `docs/08-decisions.md` 的「待决」并询问，不擅自决定。

**收尾（每次都要做）**
```powershell
python tools/devlog.py done "本轮完成的事项"
python tools/devlog.py todo "没做完的、下一步要做的"
python -m unittest discover -s tests -v
```
- 更新 `docs/05-roadmap.md` 状态表。
- 日志不写流水账：写「做了什么 / 为什么 / 结果 / 遗留」。

## 5. 硬性约束（不可违反）

1. **技术栈锁定**：Python 3 + `tkinter` + `sqlite3` + `Pillow` + `ctypes`。运行期**不得**引入第三方包。
2. **打包工具例外**：`PyInstaller` 仅开发期使用，不得成为运行依赖。
3. **全中文界面**：所有用户可见文案中文，代码标识符英文。
4. **配色统一**：只允许使用 `docs/03-design-spec.md` 定义的设计令牌，禁止随手写色值。
5. **不联网**：程序运行期间不得发起任何网络请求。
6. **数据库变更必须写迁移**：在 `docs/02-architecture.md` 记录 schema 版本与迁移步骤。
7. **不擅自扩大范围**：托盘图标、开机自启、云同步、深色主题均不在本期范围，除非用户在 `docs/08-decisions.md` 中确认。
8. **工作区限制**：所有文件写入限定在项目目录内；`data/`、`dist/`、`build/`、`__pycache__/` 不进版本库。

## 6. 常用命令

```powershell
# 开发运行（带控制台，便于看日志）
& 'C:\Users\lenovo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe' app/main.py

# 静默运行（无控制台）
& '...\python\pythonw.exe' app/main.py

# 单元测试
python -m unittest discover -s tests -v

# 记录日志（自动写入 devlog/当天日期.md）
python tools/devlog.py done "完成剪贴板监听线程"
python tools/devlog.py todo "补图片上限测试"
python tools/devlog.py status          # 查看当天日志

# 打包（需联网装 PyInstaller，见 docs/07）
powershell -ExecutionPolicy Bypass -File build_exe.ps1
```
> 说明：`python` 指本机 Python；若未进 PATH，用第 6 节第一条的绝对路径。

## 7. 开发日志规则

- 文件：`devlog/YYYY-MM-DD.md`，一天一个，跨天另起。
- 必须包含小节：`今日目标`、`完成`、`待办`、`问题与风险`、`明日计划`。
- 由 `tools/devlog.py` 自动追加，格式：`- HH:MM 内容`；不用脚本时手工按同格式补。
- 语气：只记事实、原因、结论，不写情绪。

## 8. 完成定义（DoD）

一个任务算「完成」，必须同时满足：
1. 功能按 `docs/01-requirements.md` 对应条目可用；
2. `python -m unittest discover -s tests` 全绿；
3. 头部 `docs/05-roadmap.md` 状态改为 ✅ 并注明日期；
4. `devlog` 当天有记录；
5. 无新增第三方运行依赖、无硬编码色值、无 TODO 残留（或已登记为待办）。

## 9. 当前状态

- 阶段：**M2 系统能力层已完成**（M0 工程底座 → M1 数据层 → M2 剪贴板监听），当前 64 个单元测试全绿。
- 下一步：`docs/05-roadmap.md` 的 M3（界面骨架）。
- 已有代码：`app/config.py`、`app/db.py`、`app/storage.py`、`app/win32.py`、`app/clipboard.py`；工具 `tools/devlog.py`、`tools/dev_smoke.py`、`tools/clipboard_watch.py`。

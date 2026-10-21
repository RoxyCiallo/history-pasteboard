# 02 技术方案与架构

- 版本：v1.0
- 日期：2026-10-21
- 基准环境：Python 3.12.14 (MSC v.1944 64bit)、Tk 8.6、Pillow 12.3.0、SQLite 3.53.1、Windows 10/11 x64

## 1. 选型

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| Electron + SQLite | UI 表现力强 | 需下载 ~100MB 运行时、原生模块编译、包体大、内存高 | 否决 |
| C# WPF / WinUI | 原生体验好 | 需 .NET SDK 与编译链，本机无 | 否决 |
| **Python 3 + tkinter + sqlite3 + Pillow + ctypes** | 本机零安装、零第三方依赖、可直接打包 | UI 需手绘、无原生控件美化 | **采用** |

理由：本机 Python、tkinter、Pillow、sqlite3 全部就绪（已核实），全程离线可开发；tkinter 足够画卡片式列表；Win32 能力通过 `ctypes` 直调，不需要 `pywin32`。

## 2. 模块划分

```
app/
├─ main.py          入口：DPI、单实例、日志、装配、主循环、退出清理
├─ config.py        设置读写（settings 表 + 默认值 + 类型转换）
├─ db.py            SQLite：schema、迁移、CRUD、搜索、清理、分页
├─ storage.py       数据目录解析、图片保存、缩略图、去重、文件删除
├─ clipboard.py     监听线程：序列号轮询、读取文本/图片、排除标记检测
├─ win32.py         ctypes 封装：剪贴板读写、热键、互斥体、置前、DPI
├─ security.py      二级密码：PBKDF2、会话解锁、错误冷却
└─ ui/
   ├─ theme.py      设计令牌（唯一色值来源）
   ├─ main_window.py 主窗口布局、搜索、列表容器、滚动、状态刷新
   ├─ card.py       单卡片绘制与命中区域
   └─ dialogs.py    设置面板（后续补密码对话框）
```

> 已落地：`main.py`、`theme.py`、`main_window.py`（M3）、`card.py`（M4）、`dialogs.py`（M5 设置面板）；
> `security.py` 与密码对话框待 M6。

### 模块职责与依赖

| 模块 | 职责 | 允许依赖 |
|---|---|---|
| `win32.py` | 所有 Win32 调用集中于此，其他模块不直接 `ctypes` | 标准库 |
| `storage.py` | 路径与文件，不碰 UI、不碰剪贴板 | `config` |
| `db.py` | 纯数据，输入输出为 dict/基础类型 | `storage`（删图片文件时回调） |
| `config.py` | 键值读写，含默认值与校验 | `db` |
| `security.py` | 哈希、校验、冷却状态 | `db`/`config`、`hashlib` |
| `clipboard.py` | 读剪贴板 → 规范化 → 交 `db` | `win32`、`storage`、`db` |
| `ui/*` | 只做展示与交互，业务通过 `db`/`config`/`security` | 以上全部 except `clipboard` 内部 |

## 3. 线程模型

```
主线程 (tkinter mainloop)
 ├─ UI 事件、after() 定时器
 ├─ queue.get() 消费：新增记录、热键、唤出请求、热键注册结果、清理完成事件
 └─ 不与任何线程共享 tkinter 对象

监听线程 (clipboard.ListenerThread, daemon)
 └─ 每 500ms 轮询 GetClipboardSequenceNumber → 变化则读取 → db.upsert → queue.put(("new", id))

热键线程 (hotkey, daemon)
 └─ 依次尝试候选热键注册 → GetMessage 循环 → WM_HOTKEY → queue.put(("hotkey", None))

唤起等待线程 (win32.ActivateWatcher, daemon，M5)
 └─ WaitForSingleObject(命名事件, 250ms) → 收到 → queue.put(("activate", None))

清理定时器 (主线程：启动后 2 秒一次，之后 after(600_000) = 10 分钟)
 └─ db.purge_expired() → 删图片文件 → 通知 UI 刷新 → 写 last_purge_at
```

规则：
1. **任何线程都不得直接调用 tkinter**；跨线程只通过 `queue.Queue`，主线程用 `after(200, poll_queue)` 消费。
2. `db.py` 内部单个连接 + `threading.RLock`，监听线程与 UI 线程可并发调用。
3. 退出顺序：置停止标志 → join 监听线程(≤2s) → 热键 `UnregisterHotKey` + `PostThreadMessage(WM_QUIT)` → 唤起线程 stop → 关连接 → 关互斥体/事件句柄 → `destroy()`。

## 4. 数据流

**文字**
```
复制 → 序列号 +1 → 读 CF_UNICODETEXT → strip() 判空 → 长度 >1MB? 跳过
     → sha256(text) → SELECT id FROM items WHERE content_hash=?
        有 → UPDATE updated_at（并清 pinned_at? 不清，仅时间）
        无 → INSERT → queue("new")
```

**图片**
```
复制 → 序列号 +1 → ImageGrab.grabclipboard()
     → 是 Image：尺寸/字节校验 → 原图 PNG 存 data/images/<sha256>.png
                → 缩略图 320px 宽存 data/thumbs/<sha256>.png
                → sha256(原图字节) 去重 → INSERT
     → 是文件列表：取第一个图片文件读取，同上
     → 都不是：忽略
```

**点击卡片复制**
```
点击 → 私密且未解锁? → 弹密码框 → 校验 → 失败计数
     → 文本：win32.set_clipboard_text()
     → 图片：win32.set_clipboard_image(PIL.Image)
     → 更新 updated_at → withdraw() 主窗口 → 状态栏提示"已复制"
```

## 5. 数据库 schema

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT    NOT NULL CHECK (kind IN ('text','image')),
    text_content TEXT,                       -- 文本正文；图片为 NULL
    image_path   TEXT,                       -- 相对 data/ 的路径
    thumb_path   TEXT,
    width        INTEGER,
    height       INTEGER,
    byte_size    INTEGER,
    content_hash TEXT    NOT NULL UNIQUE,    -- sha256
    is_private   INTEGER NOT NULL DEFAULT 0,
    pinned       INTEGER NOT NULL DEFAULT 0,
    pinned_at    TEXT,
    created_at   TEXT    NOT NULL,           -- ISO8601 本地时间
    updated_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_order ON items(pinned DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_hash  ON items(content_hash);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
```

- 当前 schema 版本：**1**
- 迁移策略：`schema_meta.version` 落后时按版本号顺序执行 `_migrate_v1_to_v2()` 之类的函数，迁移前自动备份 `history.db` 为 `history.db.bak-<时间戳>`。
- 约定：所有时间存本地时间 ISO8601（`YYYY-MM-DDTHH:MM:SS`），比较用字符串即可（同格式可字典序比较）。

### settings 键

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `retention_days` | int | 3 | 1–365 |
| `pwd_salt` | hex | 空 | 16B 随机盐 |
| `pwd_hash` | hex | 空 | PBKDF2-HMAC-SHA256 结果 |
| `pwd_iterations` | int | 200000 | 便于日后提高 |
| `pwd_set_at` | iso | 空 | 设置时间 |
| `hotkey` | str | `ctrl+shift+v` | 取值见 `win32.HOTKEY_PRESETS` |
| `hide_hint_shown` | bool | false | 首次隐藏提示是否已显示 |
| `window_geometry` | str | 空 | `WxH+X+Y` |
| `last_purge_at` | iso | 空 | 上次清理时间 |

## 6. 数据目录解析（storage.py）

优先级：
0. 环境变量 `PASTEBOARD_DATA_DIR` —— 测试与冒烟脚本用，指定后**完全不碰**真实数据目录。
1. `exe 同目录/data/` —— 若存在或可创建（绿色便携）。
2. `%LOCALAPPDATA%\PasteBoard\data\` —— 上面不可写（如放在 Program Files）时回退。

判定方法：尝试 `os.makedirs(..., exist_ok=True)` + 写入探针文件 `os.access`/实际写一个临时文件，失败则回退。结果写入日志，便于排查。

> 测试约定：单元测试**不要**用 `tempfile.TemporaryDirectory`。它在 Windows 沙箱下会把目录 ACL 改成当前受限令牌无法访问，导致 SQLite 报 `unable to open database file`、清理时报 `PermissionError`。统一用 `tests/tmpdir.py`（在 `build/test-tmp/` 下普通 `mkdir`，继承父目录权限，`shutil.rmtree(ignore_errors=True)` 清理）。

## 7. Win32 API 清单（win32.py）

状态：✅ 已实现（M2） · ⏳ 待实现（标注里程碑）

| API | 用途 | 注意 | 状态 |
|---|---|---|---|
| `GetClipboardSequenceNumber` | 轮询判断变化 | 无锁、极轻 | ✅ |
| `OpenClipboard/CloseClipboard` | 访问剪贴板 | 必须成对；失败重试 3 次 × 20ms | ✅ |
| `GetClipboardData(CF_UNICODETEXT)` | 读文本 | `ctypes.wstring_at` | ✅ |
| `RegisterClipboardFormatW` | 检测 `ExcludeClipboardContentFromMonitorProcessing` 等标记 | 存在即视为私密 | ✅ |
| `EmptyClipboard/SetClipboardData` + `GlobalAlloc/GlobalLock/GlobalUnlock` | 写文本（`CF_UNICODETEXT`）、写图片（`CF_DIB`） | `GMEM_MOVEABLE`；CF_DIB = BMP 去掉 14 字节文件头 | ✅ |
| `GetClipboardData(CF_HDROP)` 等图片文件列表 | 复制「图片文件」时识别为图片 | 由 Pillow `ImageGrab.grabclipboard()` 处理 | ✅ |
| `RegisterHotKey/UnregisterHotKey` | 全局热键 | 候选：`Ctrl+Shift+V` → `Ctrl+Alt+V` → `Ctrl+Shift+H`，独立线程 + `GetMessage` 循环；`PostThreadMessage(WM_QUIT)` 退出 | ✅（M3 主键，M5 补备选键） |
| `CreateMutexW` | 单实例 | `Local\PasteBoard.SingleInstance`，见 ADR-010 | ✅（M5） |
| `CreateEventW/OpenEventW/SetEvent` + `WaitForSingleObject` | 唤起已有实例 | 命名事件 `Local\PasteBoard.Activate` + 后台等待线程（ADR-010，替代最初的窗口广播方案） | ✅（M5） |
| `SetForegroundWindow/ShowWindow` | 唤出置前 | 目前用 tkinter `deiconify + lift + topmost` 实现 | ✅（M3，tkinter 方案） |
| `SetProcessDpiAwareness` (`shcore`) | 高清缩放 | 失败回退 `user32.SetProcessDPIAware` | ✅（M3） |

## 8. 剪贴板监听：为什么用轮询

`AddClipboardFormatListener` 需要一个隐藏窗口和消息循环，还要与 tkinter 争线程；`GetClipboardSequenceNumber` 轮询开销近乎为零（一次系统调用），500ms 延迟在体验上不可感知。若将来要更低延迟，可降到 200ms 或迁到消息钩子（见 `docs/08-decisions.md` ADR-006）。

## 9. 二级密码设计

```
设置密码：salt = os.urandom(16)
          hash = pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations=200000)
          存 settings：pwd_salt(hex) / pwd_hash(hex) / pwd_iterations / pwd_set_at

校验：    重算比对 hmac.compare_digest；失败 attempts += 1
          连续 5 次失败 → locked_until = now + 30s

会话：    unlocked = True，last_action 时间戳；空闲 5 分钟或窗口隐藏 → 重新上锁
重置：    二次确认 → 删除所有 is_private=1 卡片 → 清空 pwd_* 设置
```

已知限制（必须写进 README）：数据库未加密，密码只作界面门禁；能直接读 `data/history.db` 的人不受密码保护。

## 10. 错误处理与日志

- `logging` 写入 `data/app.log`，`RotatingFileHandler(maxBytes=1MB, backupCount=2)`，级别 INFO；未捕获异常用 `sys.excepthook` 与 `threading.excepthook` 记录堆栈。
- 剪贴板读取失败（其他程序占用）：捕获并静默重试，不弹窗、不刷屏。
- 数据库异常：单次操作失败记录日志并提示「操作失败，请查看日志」，不让 UI 崩溃。
- 图片文件缺失（被手动删除）：卡片显示占位图，点击提示「原图已丢失」。

## 11. 性能设计

| 点 | 做法 |
|---|---|
| 列表渲染 | 分页 200 条，滚动到底再加载；卡片控件复用 `PhotoImage` 引用缓存 |
| 缩略图 | 落盘 320px 宽，显示时再缩到 260px，避免每次解码原图 |
| 去重 | `content_hash` 唯一索引，O(1) 判断 |
| 搜索 | `text_content LIKE` + 索引；数据量大时再考虑 FTS5（记为待优化） |
| 清理 | 每 10 分钟一次，单条 SQL + 批量删文件 |

## 12. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 热键被其他软件占用 | 唤不出 | 注册失败给告警，允许在 3 个预设键之间切换 |
| 剪贴板被独占 | 漏记一次 | 重试 3 次；序列号下次变化会补记 |
| PyInstaller 无法安装 | 打包失败 | 回退 `--onedir` + `启动.vbs`（`docs/07`） |
| 中文 exe 名被杀软误报 | 无法运行 | exe 用 ASCII 名 `PasteBoard.exe`（ADR-007） |
| 图片量大占磁盘 | 磁盘满 | 20MB 单条上限 + 保留期清理 + 设置内显示数据目录 |
| tkinter 高 DPI 模糊 | 观感差 | `SetProcessDpiAwareness(2)` + `tk scaling` |

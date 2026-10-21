# 06 测试与验收

- 版本：v1.0
- 日期：2026-10-21
- 原则：**纯逻辑自动化，系统交互手动验**；每个里程碑结束必须跑一次全量。

## 1. 测试策略

| 层 | 方式 | 覆盖 |
|---|---|---|
| 数据/安全/规范化 | `unittest` 自动化 | `db`、`storage`、`security`、`clipboard` 纯函数 |
| Win32 调用 | 不写自动化，做手动冒烟 | 剪贴板、热键、单实例 |
| 界面 | 手动清单 | 卡片、搜索、置顶、删除、密码 |
| 打包产物 | 手动冒烟（干净目录） | exe 启动、记录、退出、持久化 |

运行命令：

```powershell
python -m unittest discover -s tests -v
```

## 2. 自动化用例

### 2.1 `tests/test_db.py`

| ID | 场景 | 预期 |
|---|---|---|
| DB-01 | 插入文字记录 | 返回 id，`count()` +1 |
| DB-02 | 相同 hash 再插入 | 不新增；`updated_at` 更新；时间变新 |
| DB-03 | 列表排序 | 置顶在前，其余按 `updated_at` 倒序 |
| DB-04 | 置顶/取消置顶 | `pinned` 翻转，`pinned_at` 有值/清空 |
| DB-05 | 搜索关键字 | 仅返回匹配项；`%`/`_` 被转义不误匹配 |
| DB-06 | 搜索无条件 | 返回全部（分页） |
| DB-07 | 分页 limit/offset | 不重不漏 |
| DB-08 | 删除图片记录 | 记录消失且图片、缩略图文件被删 |
| DB-09 | 清理过期 | 超期非置顶删除，未超期保留 |
| DB-10 | 清理过期（置顶） | 置顶记录即使超期也保留 |
| DB-11 | 边界天数 | days=1 与 days=365 均正常 |
| DB-12 | 空库操作 | 不抛异常，count=0 |

### 2.2 `tests/test_storage.py`

| ID | 场景 | 预期 |
|---|---|---|
| ST-01 | 保存图片 | 原图与缩略图文件存在，路径为相对路径 |
| ST-02 | 缩略图尺寸 | 宽 ≤ 320，保持纵横比 |
| ST-03 | 相同图片两次 | 文件只有一份（按 hash 命名） |
| ST-04 | 删除文件 | 不存在时也不抛异常 |
| ST-05 | 目录不可写 | 回退到备用目录（用假路径模拟） |

M1 实际覆盖补充：sha256 文本/字节一致性、文本与图片大小上限、`image_abs_path` 路径穿越、`PASTEBOARD_DATA_DIR` 覆盖优先、`ensure_layout` 建目录、`db_path`/`log_path` 拼接。

### 2.2.1 `tests/test_config.py`（M1 新增）

| ID | 场景 | 预期 |
|---|---|---|
| CF-01 | 空库读默认值 | `retention_days=3`，布尔/字符串取默认 |
| CF-02 | 写入后读回 | 类型还原（int/bool/str） |
| CF-03 | 越界天数 | `ValueError`（0、366） |
| CF-04 | 非数字/非布尔文本 | `ValueError` |
| CF-05 | 未知键 | `KeyError` |
| CF-06 | 库里存了脏数据 | `get` 回退默认值，不抛异常 |
| CF-07 | `retention_days` 属性 | 可读可写，与 `set/get` 等价 |

### 2.2.2 临时目录约定

所有涉及 SQLite 或文件系统的用例继承 `tests/tmpdir.py` 的 `new_dir()` / `remove_dir()`；禁止 `tempfile.TemporaryDirectory`（沙箱 ACL 问题，见 `docs/02` 第 6 节）。

### 2.3 `tests/test_security.py`（M6 已实现）

| 编号 | 用例 | 覆盖点 |
|---|---|---|
| SE-01 | `test_no_password_means_locked` | 未设置密码时不可解锁 |
| SE-02 | `test_set_password_stores_salt_and_hash` | 盐 32 hex、哈希 64 hex 且不等于明文 |
| SE-03 | `test_salt_is_random` | 两次设置相同密码，盐与哈希都不同 |
| SE-04 | `test_rejects_short_password` / `test_rejects_blank_password` | 少于 4 位、全空白被拒绝 |
| SE-05 | `test_correct_password_unlocks` | 正确密码解锁 |
| SE-06 | `test_wrong_password_stays_locked` | 错误密码不解锁且失败计数 +1 |
| SE-07 | `test_five_failures_lock_temporarily` | 连续 5 次失败锁 30 秒，冷却内正确密码也拒绝 |
| SE-08 | `test_lock_expires_after_cooldown` | 冷却到期后可再次尝试 |
| SE-09 | `test_success_resets_failure_counter` | 成功一次清零失败计数 |
| SE-10 | `test_lock_clears_unlocked` | `lock()` 清掉会话解锁状态 |
| SE-11 | `test_touch_extends_session` | `touch()` 延长空闲计时 |
| SE-12 | `test_idle_session_locks` | 空闲超过 5 分钟 `lock_if_idle()` 自动上锁 |
| SE-13 | `test_lock_if_idle_is_noop_when_locked` | 本来就锁着时返回 False |
| SE-14 | `test_reset_clears_password` | 重置清空 `pwd_*` 并上锁 |
| SE-15 | `test_delete_private_items` | 只删私密记录，普通记录保留 |
| SE-16 | `test_delete_private_items_when_none` | 无私密记录时返回空列表 |

### 2.4 `tests/test_clipboard.py`

| ID | 场景 | 预期 |
|---|---|---|
| CB-01 | `normalize_text` 去首尾空白、统一换行 | `"  a\r\nb\rc  "` → `"a\nb\nc"` |
| CB-02 | 纯空白文本 / None | 返回 None（不记录） |
| CB-03 | 超长文本（>1MB） | 返回 None |
| CB-04 | hash 稳定 | 同文本两次 hash 相同，不同文本不同 |
| CB-05 | 图片尺寸超限 / 零尺寸 | `is_acceptable_image` 返回 False |
| CB-06 | 非图片对象 | `is_acceptable_image` 返回 False（字节上限由 `storage.save_image` 返回 None 拒绝） |
| CB-07 | 正常图片、边界尺寸 8000px | 返回 True |
| CT-01 | 捕获文本 | 入库 kind=text，内容已去空白 |
| CT-02 | 捕获私密文本 | `is_private=True` |
| CT-03 | 重复内容 | 不新增，`created=False`，id 不变 |
| CT-04 | 空剪贴板 | 返回 None，不入库 |
| CT-05 | 捕获图片 | kind=image，原图与缩略图落盘，宽高正确 |
| CT-06 | 尺寸超限图片 | 返回 None，不入库 |
| CT-07 | 同时有文本与图片 | 优先记文本 |
| CT-08 | 文本超长但有图片 | 回退记图片 |
| CB-08 | `suppress_once` 后消费一次 | `_consume_suppress()` 第一次 True、第二次 False |
| CB-09 | 未请求抑制时消费 | 返回 False |
| CB-10 | 抑制标记过期（`seconds=0`） | 立即失效，返回 False |
| CB-11 | 抑制过期后的真实复制 | 仍正常记录，不被吞掉 |

> 真实剪贴板的读写不走单元测试（依赖桌面会话），用 `tools/clipboard_watch.py` 手动验证。

### 2.5 `tests/test_ui_helpers.py`（M4 新增）

| 编号 | 用例 | 覆盖点 |
|---|---|---|
| UI-01 | `RoundedPointsTests.test_four_corners_are_sampled` | 圆角多边形四个角各采样 `steps+1` 个点，坐标不越界 |
| UI-02 | `test_radius_clamped_to_half_size` | 半径超过短边一半时被夹紧 |
| UI-03 | `test_zero_radius_is_plain_rectangle` | 半径为 0 退化为直角矩形 |
| UI-04 | `FormatTimeTests.test_today/yesterday/older` | 时间显示三档：今天、昨天、日期 |
| UI-05 | `test_invalid_text_returned_as_is` | 非法时间字符串原样返回 |
| UI-06 | `HumanSizeTests.test_bytes/kilobytes/megabytes/none` | 文件大小格式与 `None` 兜底 |
| UI-07 | `ClipLinesTests.test_short_text_kept/empty_text` | 短文本与空文本不改动 |
| UI-08 | `test_hard_line_break_respected` | 文本内的硬换行保留 |
| UI-09 | `test_long_line_is_wrapped_and_truncated` | 长行按像素宽度断行、末行加省略号 |
| UI-10 | `test_line_count_limited` | 超过 3 行只保留 3 行 |

> `ClipLinesTests` 需要 Tk 显示；在无桌面环境自动 `SkipTest`。

### 2.6 `tests/test_win32_instance.py`（M5 新增）

| 编号 | 用例 | 覆盖点 |
|---|---|---|
| SI-01 | `test_first_instance_acquires` | 首个实例拿到命名互斥体 |
| SI-02 | `test_second_instance_is_rejected` | 第二个实例被拒绝并通知首个实例 |
| SI-03 | `test_activate_event_wakes_waiter` | 唤起线程 `WaitForSingleObject` 收到事件并投递队列 |
| SI-04 | `test_wait_times_out_without_signal` | 无信号时等待超时返回 False |
| SI-05 | `test_close_is_idempotent` | 重复关闭句柄不抛异常 |
| SI-06 | `test_names_are_isolated` | 不同名字的实例互不影响 |

> 用例使用 `uuid` 生成一次性名字，不干扰真实运行中的程序；无 Windows 时整组跳过。

### 2.7 `tests/test_dialogs.py`（M5 新增）

| 编号 | 用例 | 覆盖点 |
|---|---|---|
| DL-01 | `test_preset_selected_when_value_is_preset` | 保留期为 3 时选中预设，自定义框禁用 |
| DL-02 | `test_custom_selected_when_value_not_preset` | 保留期为 10 时选中「自定义」并填入数值 |
| DL-03 | `test_save_preset_writes_config` | 选 7 天保存后写入配置并触发刷新回调 |
| DL-04 | `test_save_custom_value` | 自定义值去除空格后保存 |
| DL-05 | `test_invalid_custom_value_is_rejected` | 非法值弹提示、原值不变、面板不关闭 |
| DL-06 | `test_clear_history_calls_callback_and_reports_count` | 确认后调用清空回调并提示删除条数 |
| DL-07 | `test_clear_history_cancelled_does_nothing` | 取消时不调用回调 |
| DL-08 | `test_hotkey_label_is_shown` | 面板展示传入的当前热键 |

> 需要 Tk 显示；无桌面环境整组 `SkipTest`。

## 3. 手动验收清单

前置：`data/` 为空目录，程序首次启动。

| ID | 步骤 | 预期 |
|---|---|---|
| A1 | 复制一段中文文字，切回列表 | ≤1s 出现卡片，位于最上 |
| A2 | 复制第二段文字 | 新卡片在最上，旧的下移 |
| A3 | 再复制 A1 的内容 | 不新增卡片，A1 卡片回到最上 |
| A4 | 截图（Win+Shift+S）后复制 | 出现图片卡，带缩略图与尺寸信息 |
| A5 | 点击文字卡片 | 窗口**保持打开**，状态栏提示已复制；在记事本 `Ctrl+V` 得到该文本 |
| A6 | 点击图片卡片 | 窗口保持打开；在画图 `Ctrl+V` 得到原图 |
| A7 | 点击图钉 | 卡片移到最上，左侧出现主色条，显示「已置顶」 |
| A8 | 点击删除 → 确认 | 卡片消失；`data/images` 中对应文件被删除 |
| A9 | 搜索框输入关键字 | 列表即时过滤；清空后恢复 |
| A10 | 点关闭按钮 | 窗口消失；首次出现「仍在后台运行」提示；再次点击不再提示 |
| A11 | 按 `Ctrl+Shift+V` | 窗口再次出现并置前 |
| A12 | 再次双击 exe | 不新开进程，唤出已有窗口 |
| A13 | 设置保留期为 1 天，插入 2 天前的假数据 | 10 分钟内该数据被清理，置顶的不被清理 |
| A14 | 复制 KeePass 类内容（带排除标记） | 卡片打码显示锁；点击要求密码；错误密码有提示；正确后显示并可复制 |
| A15 | 密码错误 5 次 | 冷却 30 秒提示 |
| A16 | 点「彻底退出」 | 进程结束，热键不再响应，数据仍在 |
| A17 | 重新启动 | 历史、置顶、保留期、密码全部保留 |
| A18 | 把窗口放到 150% 缩放屏幕 | 字不模糊、布局不溢出 |
| A19 | 点击卡片复制后查看列表 | 不多出重复卡片，旧卡片不会被顶到最前（0.2.0 不回灌） |
| A20 | 复制一段超过 3 行的长文本 | 卡片显示「查看全文 ›」；点开可滚动看全文；「复制全文」可粘贴 |
| A21 | 普通用户（非管理员）双击文件夹版 exe | 正常启动出窗口，无「Could not create temporary directory!」 |

### 截至 0.2.0 的验收进度（2026-10-21）

- 已通过：**A1 / A2 / A3**（真实进程 `Set-Clipboard` 验证，重复内容只刷新时间）、**A4**（图片卡缩略图与尺寸渲染）、**A5**（`build/v02_probe.py`：点击文字卡片写回剪贴板，窗口 `winfo_viewable()` 保持 True，状态栏提示已复制）、**A7**（置顶后目标卡排到首位、卡片显示主色条与「已置顶」）、**A8**（删除确认后库与卡片同步减少、图片文件交给 `storage.delete_files`）、**A9**（搜索「SELECT」过滤、无结果空状态、清空恢复）、**A10**（`WM_CLOSE` 后窗口隐藏、进程存活、记录继续）、**A12**（首个实例隐藏窗口后再次启动，第二个进程 exit 0 并唤回首个窗口）、**A13**（`build/purge_probe.py`：过期非置顶记录与图片文件被删、置顶过期保留、`last_purge_at` 写入）、**A14 / A15**（`build/security_probe.py`：私密卡打码 → 首次点击设置密码 → 解锁后显示明文与缩略图 → 错误密码提示剩余次数 → 连续失败进入冷却）、**A18 部分**（150% 缩放屏幕下界面清晰、布局不溢出）、**A19 部分**（`build/v02_probe.py` 验证 `suppress_once()` 写入 1 次且不产生回灌；CB-08…CB-11 单测覆盖抑制窗口）、**A20**（长文本卡出现「查看全文 ›」，弹窗 620×480 可滚动查看全文，底部字数与「复制全文」可用；`VIEW-01…07` 单测覆盖显示条件）。
- 设置面板（A12/A13 的配套）由 `build/settings_probe.py` 验证：预设与自定义保留期写入、非法值拦截、清空历史连带删图片；M6 新增 `build/m6_settings_probe.py` 验证「重置密码」：密码清除、私密记录与图片文件一并删除、按钮转禁用。
- 打包（0.2.0）已通过：`dist/PasteBoard/PasteBoard.exe`（5.1 MB，文件夹共 74.2 MB）从 `Start-Process` 启动，0.9 秒内完成初始化并创建 `dist/PasteBoard/data/`；跨进程复制被记录；`WM_CLOSE` 后首次隐藏提示弹出，确认后窗口隐藏且进程存活；exe 属性 `FileVersion 0.2.0`、`ProductName 历史粘贴板`。
- 待实机验证：**A6**（点击图片卡片写回剪贴板，需要真实粘贴到画图确认）、**A11**（`Ctrl+Shift+V` 唤回；沙箱内无法注入按键，热键注册成功日志已确认）、**A16**（点「彻底退出」按钮）、**A17**（重启后数据保留；`security_probe` 已用重建 `Config/Security` 间接验证密码持久化）、**A19 实进程部分**（真实双击复制后确认列表不多出新卡片）、**A21**（普通用户非管理员双击文件夹版 exe，需用户在真实桌面确认），以及 `docs/07` 的 R2–R6、R8。
- 开发期自检脚本（均不入库）：`build/ui_probe.py`（窗口渲染/搜索/置顶/复制/删除/截图）、`build/purge_probe.py`（保留期清理）、`build/settings_probe.py`（设置面板）、`build/security_probe.py`（二级密码全流程）、`build/m6_settings_probe.py`（设置面板里的重置密码）、`build/v02_probe.py`（查看全文、复制不回灌与窗口保留）。

## 4. 回归清单（每次改代码必过）

- [ ] 启动 → 复制文字 → 列表出现
- [ ] 置顶 → 重启 → 仍置顶
- [ ] 搜索 → 清空 → 列表恢复
- [ ] 关闭 → 热键唤出
- [ ] 彻底退出 → 进程消失
- [ ] `unittest` 全绿

## 5. 缺陷分级

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 数据丢失、崩溃、无法启动 | 立即修，停止新功能 |
| P1 严重 | 核心功能不可用（记录/唤出/粘贴） | 当前轮次内修 |
| P2 一般 | 展示错误、次要交互失效 | 记入待办，下轮修 |
| P3 轻微 | 文案、间距、图标 | 记入待办 |

## 6. 测试数据

- 文字：中文长段、英文、含 `%_\` 的字符串、超长 1MB、纯空白。
- 图片：1080p 截图、10MB 大图、8000px+ 超大图、损坏文件。
- 时间：手工把 `updated_at` 改成 2 天前/2 年前，验证清理。

## 7. 记录

每次验收在 `devlog` 当天写一行结论：`验收 A1–A18 通过 17 项，A14 待 M6`。

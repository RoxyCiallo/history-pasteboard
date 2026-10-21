# 04 开发规范

- 版本：v1.0
- 日期：2026-10-21
- 适用：本项目所有 Python 代码、脚本与文档

## 1. 环境

| 项 | 值 |
|---|---|
| Python | 3.12.14（本机运行时） |
| 解释器路径 | `C:\Users\lenovo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe` |
| 无控制台解释器 | 同目录 `pythonw.exe` |
| GUI 库 | tkinter 8.6（标准库） |
| 图像 | Pillow 12.3.0 |
| 数据库 | sqlite3（SQLite 3.53.1） |
| 打包 | PyInstaller（仅开发期，需联网安装一次） |

不新建虚拟环境（本机解释器已备齐依赖）；若将来必须隔离，用 `python -m venv .venv` 并登记到本文。

## 2. 目录与命名

```
app/            源码，模块名小写下划线
app/ui/         界面层
tests/          test_<模块>.py
tools/          辅助脚本（devlog.py 等）
assets/         ico 等静态文件
data/           运行时生成，不手工编辑、不进版本库
```

| 对象 | 规则 | 例 |
|---|---|---|
| 模块/文件 | 小写 + 下划线 | `main_window.py` |
| 函数/变量 | 小写 + 下划线 | `purge_expired` |
| 类 | PascalCase | `ClipboardListener` |
| 常量 | 全大写下划线 | `MAX_TEXT_BYTES` |
| 私有 | 前缀单下划线 | `_migrate_v1_to_v2` |
| 回调 | `on_<事件>` | `on_pin_click` |

## 3. 代码风格

- 遵循 PEP 8；行宽上限 **100**（tkinter 布局代码可放宽到 120）。
- 所有公开函数/类写 docstring（中文，说明「做什么、参数、返回、异常」）。
- 关键函数加类型注解；本项目不使用 `typing.Protocol` 等高级抽象，保持直白。
- 导入顺序：标准库 → 第三方 → 本项目；按字母排序；禁止通配符导入。
- 不使用 `from tkinter import *`；统一 `import tkinter as tk` + `from tkinter import ttk, messagebox`。

```python
def purge_expired(self, days: int) -> int:
    """删除超过保留期的非置顶记录及其图片文件。

    Args:
        days: 保留天数，取值 1-365。
    Returns:
        被删除的记录条数。
    """
```

## 4. 分层与调用约束

1. `ui/` 之下**不得**直接 `import ctypes`、`sqlite3`、`threading`；一律走 `win32`、`db`、`clipboard` 等模块。
2. `db.py` 不得 `import tkinter`；不得弹窗；错误以异常或返回值表达。
3. `win32.py` 不得包含业务逻辑，只做系统调用封装。
4. 颜色/字体/尺寸**只能**引用 `theme.py` 的常量（对应 `docs/03` 设计令牌）。
5. 任何用户可见文案必须中文；不允许把英文提示直接抛给用户。

## 5. tkinter 专项规则

- **禁止跨线程操作控件**：子线程结果一律 `queue.put()`，主线程 `after(120, ...)` 消费。
- `PhotoImage` 必须持有引用（存到卡片对象属性），否则会被 GC 变空白。
- 长列表不要一次 `grid` 上千个控件：分页 200 条。
- 定时器统一用 `widget.after()`，退出前 `after_cancel` 并用 `_closing` 标志防止回调访问已销毁控件。
- 主窗口用 `withdraw()/deiconify()` 隐藏与唤出，不用 `destroy()` 关闭（会丢状态）。
- 所有 `Toplevel` 设置 `transient(master)` + `grab_set()`，并处理 `WM_DELETE_WINDOW`。

## 5.1 线程规则

- 继承 `threading.Thread` 时，**不要**把自己的停止标志命名为 `_stop`：`Thread` 内部已有 `_stop()` 方法，赋值会把它覆盖掉（M2 踩过，报 `AttributeError: 'function' object has no attribute 'clear'`）。统一用 `self._stop_event = threading.Event()`。
- 等待用 `event.wait(timeout)` 而不是 `time.sleep()`，这样 `stop()` 能立刻生效。
- 线程 `run()` 里必须 `try/except` 包住单轮循环体：一次读取失败不能终止整个监听（只记日志）。


## 6. 错误处理

| 场景 | 做法 |
|---|---|
| 剪贴板被占用 | 捕获异常 → 20ms 后重试，最多 3 次 → 仍失败则记日志静默跳过 |
| 图片解码失败 | 跳过该条，日志记录格式与字节数 |
| 数据库异常 | 记日志 + 界面上中文提示；不崩溃、不退出 |
| 文件删除失败 | 记 warning，继续删数据库记录（避免僵尸条目） |
| 未捕获异常 | `sys.excepthook` / `threading.excepthook` 写日志，界面提示 |

禁止：裸 `except:`、`except Exception: pass`（必须至少记日志）。

## 7. 测试规范

- 框架：标准库 `unittest`；命令 `python -m unittest discover -s tests -v`。
- 纯逻辑必须可测：`db`、`security`、`storage` 的路径拼接与哈希、`clipboard` 的内容规范化函数。
- 每个测试用独立临时目录（`tempfile.TemporaryDirectory`），不碰真实 `data/`。
- 涉及 Win32/剪贴板的逻辑拆成两层：**纯函数**（可测）+ **薄封装**（不测）。
- 新增功能必须同时新增或更新测试；失败用例优先于成功用例覆盖边界。

## 8. 提交与版本（可选启用 git)

- 建议每完成一个里程碑 `git init` + 一次提交；提交信息格式：`<类型>: <简述>`，类型 `feat/fix/docs/test/chore/build`。
- 例：`feat: 剪贴板轮询监听与文字入库`
- 不提交 `data/`、`dist/`、`build/`、`__pycache__/`、`*.spec` 中间产物（除非需要定制 spec）。

## 9. 审查清单（每个任务收尾自查）

- [ ] 只用第 5 节允许的技术栈，未新增第三方运行依赖
- [ ] 无色值硬编码，全部来自 `theme.py`
- [ ] 无跨线程 UI 调用
- [ ] 异常都被记录，无静默吞掉
- [ ] 新文件已登记到 `AGENTS.md` 目录地图
- [ ] 测试通过，且新增了对应用例
- [ ] `docs/05-roadmap.md` 状态已更新，`devlog` 已写

## 10. 禁止事项

1. 在程序运行期联网、发请求、埋点。
2. 引入 `pywin32`、`pynput`、`keyboard` 等第三方库替代 `ctypes`。
3. 把密码明文写入数据库、配置或日志。
4. 在 `ui/` 里写 SQL。
5. 用 `time.sleep` 阻塞主线程。
6. 修改用户 `data/` 目录之外的文件（除打包产物 `dist/`）。

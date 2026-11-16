# 参与开发

本项目是 Windows 库存候选诊断工具的 Alpha，不是官方接口 SDK。适配器只依据真实、普通账号正常收到的响应维护；不能猜测端点或将字段名当作库存语义。

使用 CPython 3.12 x64，执行 install-windows.cmd 后运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/release.py verify
```

提交解析改动时说明实际结构来源和适用范围，但只加入明确标注的合成/脱敏 fixture。离线测试成功不能代替真实账号采样证明；不要提交管理端缓存、真实会话、原始响应或 secrets/data/exports 内容。

涉及进程管理的改动须验证外置 Python、路径含空格/中文、界面重启后的进程核对，以及拒绝停止无关进程。涉及数量的改动须区分未知、null、0、错误、剩余/总量/销量口径，并保留失败后的历史与过期标志。

发布前按 docs/release.md 操作。CI 不登录微信、不发起平台业务请求、不发布 GitHub Release；只验证本地软件行为并生成来源包。

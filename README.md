# 拼团呀普通账号商品与库存候选诊断

**v0.1.0-alpha.1 · Windows 源代码实验版 · MIT**

在你自己的普通参团账号正常浏览时，检查本机实际收到的商品/SKU 响应，并提供本地诊断表、历史和 CSV。不会从分享短码猜团单 ID，不会主动轮询、重放请求、下单或占库存。

**这是库存候选诊断工具，不保证能取得确定口径的剩余库存。** 原始 `stock`、`sale` 只是候选；未确认语义时剩余库存列为空，不做 `stock-sale` 推算。无字段、无权限、失败和零库存分别处理。

## 安装与打开

目标环境：**Windows 10/11、CPython 3.12 x64**。本机验证范围和未验证项见 [兼容性](docs/compatibility.md)。这不是独立 EXE，不包含 Python 或依赖。

1. 下载并完整解压源代码 ZIP，或克隆仓库到当前用户可写目录。不要直接在 ZIP 内运行。
2. 安装 [CPython 3.12 64-bit](https://www.python.org/downloads/windows/)。不要使用 32-bit、ARM64 原生解释器或其他 Python 主版本。
3. 双击 **install-windows.cmd**。它会在当前目录创建 `.venv`，按实际验证的 `requirements.lock` 安装依赖并检查环境。首次安装需要网络。
4. 安装完成后双击 **start-self-service.cmd**，保持启动窗口打开；浏览器访问 **http://127.0.0.1:8502**。

安装器不改全局 PATH、系统代理、Clash、防火墙或证书存储；不会下载/安装 Python 本身。[详细安装与排错](docs/setup_windows.md)

## 采一个新团

1. 用没有该团管理权限的普通微信账号打开分享入口，完成你自己的登录，核对团单完整名称。
2. 自助页面选择“新建团单”，填写名称和链接。上游 HTTP(S) 代理按你实际设置填写；没有则留空，软件没有固定代理软件或端口假设。
3. 启动观察后，由你手动将测试代理设为页面显示的 **127.0.0.1:8082**（默认端口），并按标准流程配置测试证书。
4. 在微信正常重新进入、浏览列表、滚动到底、查看商品/规格；回页面读取观察结果，核对实际团名和商品，再确认绑定。
5. 日常浏览后点“同步本地记录并生成 CSV”，查看或下载结果。每团独立保存，界面刷新不发起平台查询。

**8502 是操作网页，8082 是代理端口。** 结束时先恢复你记录的原系统代理，再停止本工具服务；测试证书不再需要时由你手动移除。[完整自助步骤](docs/self_service_windows.md)

## 支持范围与限制

- 只适配此前实际观察过的拼团呀主机、端点和 JSON 结构；新团仍需由真实响应验证。结构变更、普通角色不符、TLS 不兼容或响应不透明时给出诊断，不伪造结果。
- 只对当前目标团单与商品端点提取白名单字段；不保存用户、订单、地址或请求凭据。角色检查是保守的采样校验，不是对平台权限模型的完整审计。
- 页面隐藏库存不等于服务端没有返回字段；反过来，字段名像库存也不能证明是剩余可售数量。
- 依赖用户正常浏览触发被动更新。无无人值守实时查询；主动请求命令当前明确未实现。
- 分页、下架/隐藏商品、复杂多规格和跨端点关联不保证完整。覆盖默认为 partial/unknown；没有服务端库存时间时不宣称实时。
- 本项目为独立诊断工具，不是平台官方 SDK。

[字段与状态定义](docs/field_mapping.md) · [验证范围](docs/validation.md) · [数据边界](SECURITY.md)

## 离线演示与开发

安装后，以下命令不需要微信或网络。示例全部标记为 DEMO，不能作为线上成功证明。

```powershell
.\.venv\Scripts\python.exe -m pintuanya_inventory doctor
.\.venv\Scripts\python.exe -m pintuanya_inventory demo
.\.venv\Scripts\python.exe -m pintuanya_inventory status --mode demo
.\.venv\Scripts\python.exe -m pintuanya_inventory export --mode demo --output exports/demo_inventory.csv
.\.venv\Scripts\python.exe -m pytest -q
```

另有只读库存表入口 `scripts/start-ui.ps1`，默认 http://127.0.0.1:8501，可选择各团的独立数据库。高级命令见 `python -m pintuanya_inventory --help` 中的 profile-*。

## 发布与贡献

这是源代码 Alpha，不声称适用于所有 Windows/微信版本。GitHub CI 在 Windows runner 上检查安装、离线契约和本地代理生命周期，不登录微信，不将测试 fixture 当作真实采样证明。

发布包来自固定的 [release-files.json](release-files.json)，排除运行数据、秘密目录和本机笔记，并带文件与 ZIP 哈希。[发布流程](docs/release.md) · [贡献指南](CONTRIBUTING.md) · [变更记录](CHANGELOG.md)

项目代码采用 [MIT License](LICENSE)。依赖软件由安装器另行下载，各自适用其许可证。

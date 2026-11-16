# Windows 安装与环境检查

## 支持目标

源代码 Alpha 当前限定 CPython 3.12 x64，目标 Windows 10/11。Windows ARM64 原生 Python、32-bit、其他 Python 版本及早于 Windows 10 的系统不在安装器支持范围。目标范围与实际验证范围不同，详见 compatibility.md。

## 新电脑安装

1. 从 Python 官方 Windows 下载页安装 CPython 3.12 的 64-bit 版本。不要下载 embeddable 精简包；安装器需要标准库 venv/ensurepip。
2. 将项目完整解压到可写目录；路径可包含空格或中文。不要直接从 ZIP 内启动，也不要把个人采样数据放入公开仓库。
3. 双击根目录 install-windows.cmd。它优先使用已有项目 `.venv`，否则尝试 `py -3.12`、再尝试 PATH 中符合条件的 `python`。
4. 安装器创建项目内 `.venv`，安装精确锁定的依赖，安装本项目并执行 pip check/版本检查；失败会保留错误，不用模拟数据填充采集结果。
5. 双击 start-self-service.cmd，打开 http://127.0.0.1:8502。

首次安装需要访问 Python 包索引；之后 demo、离线导入、SQLite、界面和 CSV 可以离线运行。真实被动采样仍需要微信正常联网。

高级安装（已选好 CPython 3.12 x64 后）：

```powershell
py -3.12 scripts/install_windows.py
.\.venv\Scripts\python.exe scripts/install_windows.py --check
.\.venv\Scripts\python.exe scripts/launch.py --check
```

如果使用 uv 管理 Python，可先按 uv 官方方式准备 3.12 x64，再用该解释器执行 scripts/install_windows.py。项目不要求 Python 安装在仓库里，也不会自动安装系统 Python。

## 端口和代理

| 默认端口 | 用途 |
|---|---|
| 8502 | 新团自助操作网页 |
| 8501 | 可选的只读库存表 |
| 8082 | 自助采样的本机 HTTP 代理，可在新建团单时更改 |

上游代理填写你原先实际使用的 HTTP(S) 代理地址和端口，没有则留空。软件不假定安装了 Clash，不复制或修改其配置；不接受把用户名/密码写入上游 URL。

先记录测试前的手动代理/PAC/企业代理设置。启动本工具后，由你手动将测试代理指向页面显示的地址。企业策略或 PAC 不明确时，先在可控测试环境核对链路，不直接覆盖原设置。

访问 http://mitm.it，按对应 Windows 说明手动安装/信任本次测试 CA；先用测试浏览器验证 HTTPS，再检查微信。浏览器成功不证明微信成功。客户端拒绝标准代理/证书时停止这条路径，不关闭 TLS 校验，不注入或修改微信。

官方参考：[mitmproxy 起步](https://docs.mitmproxy.org/stable/overview/getting-started/) · [证书说明](https://docs.mitmproxy.org/stable/concepts/certificates/)。这些资料说明工具配置，不证明平台会返回库存。

## 排错与恢复

| 问题 | 处理 |
|---|---|
| 找不到 Python | 安装 CPython 3.12 x64 后重新打开启动窗口 |
| 已有 .venv 版本不符 | 先保留备份，再用正确解释器重建；安装器不会擅自删除环境 |
| 依赖版本不符或安装中断 | 再运行 install-windows.cmd；不要把复制来的 .venv 当成可移植安装包 |
| 包索引/上游不可达 | 核对实际网络与原代理配置；不通过关闭证书校验解决 |
| 界面端口占用 | 使用已打开的实例，或执行 scripts/launch.py --port 其他空闲端口；不会结束未知进程 |
| 看不到采样 | 核对系统代理端口、证书、完整团名、普通账号以及5分钟窗口；正常重新进入再观察 |

结束测试时，先恢复自己记录的原系统代理，再在页面停止该团服务；测试证书不再需要时手动移除本次 CA。不要删除其他软件或企业证书。

安装和启动器不修改全局 PATH、代理、证书、防火墙，也不要求管理员权限；项目目录须对当前用户可写。

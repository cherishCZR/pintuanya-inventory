# Alpha 源代码发布

当前发布形式是经审查的 Windows 源代码 ZIP，不是独立 EXE、不包含 Python、虚拟环境或依赖 wheel。首次安装需要网络，受支持解释器由用户先安装。

## 本地检查与构建

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/release.py verify
.\.venv\Scripts\python.exe scripts/release.py build
```

build 只读取 release-files.json 中的固定文件列表；不递归打包整个工作区。它排除运行目录、本地配置、私钥、HAR、本机笔记及旧专用脚本，检查高置信凭据/私人路径模式，并逐文件生成 FILE_MANIFEST.sha256，再复核 ZIP 内容。

dist 中生成源代码 ZIP 和 SHA256SUMS.txt。可再次检查：

```powershell
.\.venv\Scripts\python.exe scripts/release.py verify-archive --archive dist/pintuanya-inventory-0.1.0-alpha.1-windows-source.zip
```

扫描规则不能识别所有自由文本隐私；维护者仍需审查清单和实际公开内容。添加公开文件时必须明确更新 release-files.json，不能改回按目录递归收集。

## 准备 GitHub 仓库

本机工作区可能含采样和秘密文件。建议把上述已审核 ZIP 解压到新的空目录，再从那份干净源代码创建 Git 仓库；不要上传整个开发工作目录。

初始化后可运行 `scripts/release.py verify --git-index`，确保已跟踪文件均属于固定公开清单。工作区的 .gitignore 只是辅助措施，不能代替实际文件和历史审查。

本地整理和打包不会创建远程仓库、推送提交或发布 GitHub Release。这些需要维护者在审查源包后另行操作。

## CI 与发布说明

.github/workflows/windows.yml 在 Windows runner 上配置安装、离线测试、本地代理生命周期和源包构建，只上传 dist 中的源包及哈希为 CI artifact。它不会登录微信或自动创建 Release。

在实际 GitHub 运行通过前，记录状态为“已配置，未运行”。Windows Server runner 通过也不能替代消费者 Windows/微信的端到端采样验证。发布说明应标注 Alpha、解释器/架构范围、候选数量口径和已知限制，不宣传实时剩余库存。

项目代码 MIT；外部依赖由安装器另行获取，各自适用其许可。原始现场采样和本机诊断笔记保留在被忽略的本地目录中，不进入公共发布。

# 贡献指南

感谢参与 SatelliteTool。本项目是一个 **Windows 本地工具**，通过 Python 标准库
HTTP 服务调用已编译的 BlueSpace、APS 和 SGP4 exe，不包含 C++ 实现源码。

## 1. 开发环境

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Windows | 10/11 x64 | 运行 exe 功能所必需 |
| Python | 3.9+ | 仅使用标准库 |
| Node.js | 18+ | 可选，仅用于 `node --check static/app.js` |
| Git | 2.x | 版本管理 |

开发工具（可选，Ruff/Black 当前要求 Python 3.10+）：

```powershell
python -m pip install -r requirements-dev.txt
```

## 2. 本地运行

```powershell
python app.py --open
```

默认地址为 <http://127.0.0.1:8765/>。也可以双击 `start.bat`。

## 3. 测试与检查

提交 PR 前请至少运行：

```powershell
python -m py_compile app.py test_app.py
python -m unittest discover -v
python -m ruff check .
python -m black --check .
node --check static/app.js
```

如果修改了安全边界、任务生命周期或 CSV 预览逻辑，请补充对应测试。

## 4. 代码风格

- Python 使用 Black 格式化，Ruff 做静态检查；
- 前端保持原生 HTML/CSS/JavaScript，不引入构建链；
- 遵循 `.editorconfig`：UTF-8、LF、Python 4 空格、其他文件 2 空格；
- `.bat` 使用 CRLF；
- 不要在运行时代码中引入第三方 Python 包；
- 新增/修改配置字段时，同步更新 README 和 `docs/`；
- 新增错误信息时，优先使用稳定、可读的中文提示，不直接暴露 Python 异常。

## 5. 前端约定

- 所有写入 `innerHTML` 的外部数据必须经过 `escapeHtml`；
- 新按钮/表单需要可键盘操作，并考虑 `:focus-visible` 样式；
- 页面切换依赖 URL hash，修改路由时同步验证浏览器前进/后退；
- 不要提交 `runs/`、`__pycache__/`、日志或截图临时文件。

## 6. 配置、数据和二进制

- 修改 `config/tool.json` 后，更新 README 的配置说明；
- 修改 CSV 配置字段后，更新 `docs/API.md` 或 README；
- 替换 `bin/` 中的 exe/DLL 时，必须：
  1. 记录上游仓库和 commit/tag；
  2. 重新生成 `bin/SHA256SUMS`；
  3. 更新 `bin/README.md`；
  4. 在干净 Windows 环境验证三个工具；
- 不要提交密钥、令牌、个人路径或真实账号。

## 7. 提交 PR

1. 从 `main` 切出功能分支；
2. 提交信息使用祈使语气，首行不超过 72 字符；
3. PR 描述包含：动机、改动、验证命令、风险；
4. 至少通过 CI 和一次人工 Review；
5. 涉及安全问题时，不要公开细节，先阅读 [SECURITY.md](SECURITY.md)。

## 8. 许可

贡献代码即表示同意以 Apache License 2.0 授权。第三方组件和数据归属见
[NOTICE](NOTICE)、[third_party/README.md](third_party/README.md) 和
[docs/DATA.md](docs/DATA.md)。

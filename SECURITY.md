# 安全策略

## 支持版本

| 版本 | 状态 |
| --- | --- |
| 0.2.x | 接收安全修复 |
| < 0.2 | 不再维护 |

## 报告漏洞

**不要通过公开 Issue 报告安全问题。** 请使用 GitHub 仓库的
“Security → Report a vulnerability” 私密安全公告功能。

报告中请尽量包含：

- 受影响版本、Windows 版本和 Python 版本；
- 复现步骤或最小示例；
- 影响评估（信息泄露、拒绝服务、路径穿越、命令执行等）；
- 如果可能，附上修复建议。

我们会在收到报告后 5 个工作日内确认，并在修复发布后致谢（如您同意）。

## 安全模型

- 默认只监听 `127.0.0.1`，**没有登录鉴权**；
- 非本机监听必须显式使用 `--allow-remote`，且当前版本仍无鉴权；
- 只允许执行 `config/tool.json` 中配置的 exe；
- 场景名、NORAD ID、CSV 配置名、任务 ID 和下载路径均做白名单/越界校验；
- POST/DELETE 请求校验 `Host`、`Origin`、`Sec-Fetch-Site` 和
  `Content-Type: application/json`；
- 响应包含 CSP、`X-Frame-Options`、`X-Content-Type-Options` 等安全头。

## 适用范围

- 本地 HTTP 服务的 CSRF、DNS rebinding、路径穿越、命令注入；
- TLE、场景、CSV 配置和下载文件解析；
- 前端 XSS、剪贴板和下载行为；
- 资源耗尽（超长仿真、超大 TLE 采样、超大 CSV 预览/下载）；
- 第三方二进制和依赖的已知漏洞；
- 仓库中的密钥/凭据泄露。

## 安全实践

- 不要把服务直接暴露到公网；
- 不要在配置、日志或 issue 中粘贴真实账号、令牌、私钥；
- 使用来源可信的 `bin/` 和 `runtime/` 资产；
- 发现异常行为时，先停止服务并保留 `runs/<job>/job.log` 以便排查。

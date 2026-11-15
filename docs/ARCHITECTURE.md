# 架构

## 目标与约束

SatelliteTool 是 Windows 本地工具，目标是把 BlueSpace 仿真、APS 轨道转换和
SGP4 TLE 递推集中到一个浏览器界面中。

约束：

- 不包含 C++ 实现源码；
- Python 只使用标准库，不引入运行时第三方包；
- 通过外部 exe 完成计算；
- 默认只监听本机，不默认暴露到网络；
- 前端为原生 HTML/CSS/JavaScript，无构建链。

## 组件

```text
浏览器
  │ HTTP
  ▼
app.py（标准库 ThreadingHTTPServer）
  ├── 静态页面 static/
  ├── 配置 config/ + runtime/cfg/
  ├── 作业管理 runs/
  ├── Celestrak 查询
  └── 子进程
        ├── bin/BlueSpace.exe
        ├── bin/ApsOrbitTool.exe
        └── bin/Sgp4EcefTool.exe
```

## 请求流

1. 浏览器加载 `static/index.html`、`styles.css`、`app.js`；
2. `GET /api/info` 返回版本、exe 状态、场景、CSV 配置、资源限制和 EOP 状态；
3. 仿真：`POST /api/run` 创建 `runs/<job_id>/`，启动 `BlueSpace.exe`；
4. 前端每秒轮询 `GET /api/jobs/<id>?limit=20`，并通过
   `GET /api/jobs/<id>/log?tail=65536` 读取日志尾部；
5. 仿真结束后，后端把 `output/sim_data.csv` 按 CSV 配置导出为
   `telemetry.csv`，并写入 `job.json`；
6. APS/SGP4：同步调用对应 exe，读取 stdout JSON 返回浏览器；
7. TLE 查询：并发访问 Celestrak，结果按 NORAD ID 缓存。

## 任务生命周期

- 同一时间只允许一个仿真任务；
- 任务状态：`running`、`completed`、`failed`、`stopped`；
- 停止使用 Windows `taskkill /T /F`；
- CSV 导出先写 `.tmp`，成功后 `os.replace`；
- 历史任务默认保留 50 个，可通过 `config/tool.json` 的 `history.keep_jobs` 调整；
- 支持清理全部历史任务和删除单个任务。

## 安全边界

- 默认绑定 `127.0.0.1`；
- 校验 `Host`、`Origin`、`Sec-Fetch-Site`；
- POST 要求 `Content-Type: application/json`；
- 响应带 CSP、`X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`；
- 任务 ID、下载路径、场景名、CSV 配置名和 NORAD ID 均做白名单/越界校验；
- 非本机监听必须显式 `--allow-remote`，当前版本没有鉴权，不建议公网使用。

## 资源限制

- 仿真时长默认上限 1,000,000 秒；
- 启动前估算 CSV 大小并检查磁盘剩余空间；
- SGP4 采样点默认上限 20,000；
- CSV 预览使用流式降采样，运行中任务只扫描前 200,000 行；
- 下载和日志读取使用分块/尾部读取。

## 目录约定

| 目录 | 作用 |
| --- | --- |
| `bin/` | 编译好的 exe 和 DLL |
| `config/` | 工具配置和 CSV 配置 |
| `runtime/cfg/` | BlueSpace 分层配置 |
| `runtime/data/` | EOP、重力场、磁场等数据 |
| `static/` | 前端页面、样式、脚本、favicon |
| `runs/` | 任务历史（git 忽略） |
| `docs/` | 架构、API、集成、数据和排错文档 |

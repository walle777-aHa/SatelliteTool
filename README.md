# SatelliteTool

SatelliteTool 是一个面向 Windows 的本地卫星仿真工具工作台，把 BlueSpace
仿真、APS 轨道转换和 SGP4 TLE 递推集中到一个浏览器界面中。计算通过
`bin/` 中的**已编译 exe** 完成，本仓库**不包含 C++ 实现源码**。

[English](README.en.md) · [贡献指南](CONTRIBUTING.md) · [安全策略](SECURITY.md) ·
[更新日志](CHANGELOG.md) · [文档](docs/)

## 1. 快速开始

要求：

- Windows 10/11 x64；
- Python 3.9+；
- `bin/` 中存在三个 exe 和依赖 DLL。

```powershell
cd SatelliteTool
python app.py --open
```

也可以双击 `start.bat`。默认地址：<http://127.0.0.1:8765/>。

首次启动前确认：

```text
bin/BlueSpace.exe
bin/ApsOrbitTool.exe
bin/Sgp4EcefTool.exe
bin/*.dll
```

exe 不在默认位置时，修改 `config/tool.json` 的 `executables`。
Python 依赖只有标准库；Node.js 仅用于可选的 `node --check static/app.js`。

## 截图

| 首页 | 仿真 |
| --- | --- |
| ![首页](docs/screenshots/home.png) | ![仿真](docs/screenshots/simulation.png) |

| 轨道转换 | TLE 递推 | TLE 查询 |
| --- | --- | --- |
| ![轨道转换](docs/screenshots/aps.png) | ![TLE 递推](docs/screenshots/tle.png) | ![TLE 查询](docs/screenshots/query.png) |

| F10.7 空间环境 |
| --- |
| ![F10.7 空间环境](docs/screenshots/f107.png) |

## 2. 功能

- **首页**：纯黑背景、七个可拖动排序的快捷入口和 WALL-E 风格机器人；
  拖动后的入口顺序保存在浏览器 localStorage；机器人从上下左右任一边完全
  离开后都会从对侧进入，并支持方向键控制；
- **仿真**：选择场景、仿真时长和 CSV 配置，运行 `BlueSpace.exe`；
  预览表显示前 20 行，曲线对完整数据流式降采样；
- **轨道转换**：调用 `ApsOrbitTool.exe`，结果表随输入方向显示“输入/输出”
  两列（输出列高亮），一键复制方向对应的输出参数；页面下方另有 J2000 RV
  与六根数（`a/e/i/Ω/ω/M`）的双向转换；
- **惯性系 RVT ↔ 18Eph**：按 `**` 模型定义进行 60 组、每分钟采样的
  J2000 惯性系 RVT 与 18Eph 互转；支持 km/km·s⁻¹ 或 m/m·s⁻¹ 输入、
  起始 UTC/BDT 历元、拟合误差显示与结果复制；
- **TLE 递推**：调用 `Sgp4EcefTool.exe`，输出地固系位置/速度，结果表支持
  一键复制 CSV 数据；
- **TLE 查询**：Celestrak 查询最多 10 个 NORAD ID，结果按行展示，支持单行/全部
  复制；左侧保存列表支持保存、添加和删除本地 NORAD ID，并按 GCAT 国家代码
  分为中国/国外两列；左侧同时显示最近 30 天内最新一个发射日的载荷；
- **F10.7 空间环境**：NASA OMNI2 最新日值、81 天均值和近 183 天曲线，
  支持复制曲线 CSV；
- **三维显示**：Starlink V3 概念外观，按右手系展示双长展太阳翼、相控阵面、
  六个光学星间链路端口、四个 RF 回传天线及推进组件；支持鼠标拖动旋转、
  滚轮缩放、自动旋转和太阳翼展开/收拢，右侧展示公开参数与资料来源；
  首页提供快捷入口。通信能力和双阵列特征来自 SpaceX 公开资料；V3 的
  完整机械图、整翼尺寸、外形和部件位置未公开，画面比例/布局为概念示意。
- RVT 转换的输入可以是 60 行 `Rx,Ry,Rz,Vx,Vy,Vz`，也可附加首列时间；反向
  使用按 GNC 顺序排列的 18 个参数和独立 BDT 周值，输出 60 行 CSV。
- **拖动布局**：轨道转换、TLE 递推、TLE 查询、三维显示和 F10.7 页面支持
  按住面板标题拖动调整面板位置与顺序，布局保存在浏览器 localStorage；
- **CSV 定制**：按 JSON 配置选择列、重命名、缩放、偏移和精度；
- **历史任务**：日志、原始 CSV、定制 CSV、调度统计；支持清理历史；
- **安全/资源边界**：本机监听、Host/Origin 校验、统一错误、仿真/SGP4/预览上限。

## 3. 目录结构

```text
SatelliteTool/
├── app.py                     # Python 标准库 HTTP 服务与作业管理
├── start.bat                  # Windows 启动脚本
├── config/
│   ├── tool.json              # exe 路径、运行目录、限制、历史策略
│   ├── telemetry/             # CSV 输出配置
│   └── user/                  # 本地 NORAD ID 与国家分类缓存（git 忽略）
├── bin/                       # BlueSpace/APS/SGP4 exe、DLL、SHA256SUMS
├── runtime/
│   ├── cfg/                   # BlueSpace 分层配置
│   ├── data/                  # EOP、重力场、磁场等数据
│   └── modules/log/conf/       # glog 配置
├── static/                    # 前端页面、样式、脚本、favicon
├── runs/                      # 运行历史（git 忽略）
├── docs/                      # 架构、API、集成、数据、排错
├── test_app.py                # 单元测试
├── pyproject.toml             # Ruff/Black 配置
├── requirements-dev.txt       # 开发工具
├── LICENSE
├── NOTICE
└── README.md
```

`runtime/` 是 BlueSpace 的运行资产，不是 C++ 源码。升级 BlueSpace 时同步新的
`cfg/`、`data/`、`log/conf/` 和 exe/DLL 即可。

## 4. 配置

### 4.1 `config/tool.json`

```json
{
  "name": "SatelliteTool",
  "version": "0.2.0",
  "server": { "host": "127.0.0.1", "port": 8765 },
  "executables": {
    "simulation": "bin/BlueSpace.exe",
    "aps": "bin/ApsOrbitTool.exe",
    "sgp4": "bin/Sgp4EcefTool.exe"
  },
  "runtime": {
    "working_directory": "runtime",
    "config_root": "cfg",
    "data_root": "data",
    "log_config_dir": "modules/log/conf",
    "default_scenario": "baseline",
    "default_csv_profile": "default"
  },
  "telemetry": { "profiles_dir": "config/telemetry" },
  "celestrak": { "timeout_s": 20, "cache_ttl_s": 300, "recent_launches_cache_ttl_s": 1800 },
  "f107": { "timeout_s": 20, "cache_ttl_s": 1800, "window_days": 183 },
  "limits": {
    "max_simulation_time_s": 1000000,
    "max_sgp4_samples": 20000,
    "preview_scan_rows_running": 200000,
    "preview_scan_rows_finished": 2000000
  },
  "history": { "keep_jobs": 50 }
}
```

相对路径相对于 `SatelliteTool/` 解析。

### 4.2 CSV 输出配置

在 `config/telemetry/` 新建 JSON：

```json
{
  "name": "my_profile",
  "description": "我的遥测列",
  "delimiter": ",",
  "columns": [
    { "name": "time_s", "source": "time_s", "precision": 3 },
    { "name": "roll", "source": "roll_deg", "precision": 6 },
    { "name": "roll_scaled", "source": "roll_deg", "scale": 0.1, "offset": 0.0, "precision": 6 },
    { "name": "task_flow", "source": "task_flow" }
  ]
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 输出 CSV 列名，不能重复 |
| `source` | 是 | 原始 `sim_data.csv` 列名 |
| `scale` | 否 | 数值乘数，默认 1 |
| `offset` | 否 | 数值偏移，默认 0 |
| `precision` | 否 | 小数位数 0–15；不填则保留原始字符串 |
| `delimiter` | 否 | 逗号/分号/制表符/竖线之一 |

配置在仿真结束后应用；原始 `sim_data.csv` 保留。源字段不存在时任务失败并提示。

## 5. 页面使用

### 仿真

1. 选择场景；
2. 可选填写仿真时长（秒）；留空使用场景默认值；
3. 选择 CSV 输出配置；
4. 点击“运行仿真”，查看日志、遥测预览和曲线；
5. 完成后下载 `telemetry.csv` 或 `output/sim_data.csv`。

运行中任务只扫描前若干行以降低开销，完成后按完整文件重新预览。历史任务可
在页面底部查看，支持“清理历史”。

### 轨道转换

输入方向、UTC 历元、`a/e/i/Ω/ω/M`，调用 `ApsOrbitTool.exe`。结果表根据方向
自适应：瞬根 → 平根时显示“瞬根（输入）/ 平根（输出）”，平根 → 瞬根时显示
“平根（输入）/ 瞬根（输出）”，输出列高亮；复制按钮同步变为“复制平根”或
“复制瞬根”，内容为对应的输出六项参数。

页面下方“J2000 RV ↔ 六根数”支持双向转换：输入 J2000 位置速度
（km、km/s）得到 `a/e/i/Ω/ω/M`、真近点角、周期与模长；输入六根数得到
J2000 位置速度。引力常数 μ 默认 398600.4418 km³/s²，可修改；仅支持椭圆
轨道（`e < 1`），结果可一键复制。

### 惯性系 RVT ↔ 18Eph

页面按 `**` 的 18Eph 模型转换 60 组、间隔 60 秒的 J2000 惯性系
RVT。RVT → 18Eph 使用首组 RV 初始化，按 60 个位置残差作最小二乘拟合；
速度用于初始化轨道根数。18Eph → RVT 按解析模型从起始历元递推 60 个样本。
转换和拟合均由 `app.py` 中的 Python 实现完成，不调用 MATLAB、MATLAB Runtime
或目录中的 `.m` 脚本；该目录仅作为算法定义与字段约定的参考。

RVT 输入支持每行 `Rx,Ry,Rz,Vx,Vy,Vz` 六列，或首列加时间的七列；
时间列如提供必须间隔 60 秒。可选 `km/km/s`（Excel 常见）或 `m/m/s`
（GNC 算法内部单位）。起始时间按 UTC 输入，转换 BDT 周时使用 GNC 代码约定
`BDT = UTC + 4 s`。反向需另填 BDT 周和 18 个数值。

18Eph 字段顺序与拟合向量一致：
`a, e, i0, Ω0, ω, M0, Δn0, Ωdot, idot, Cus, Cuc, Cis, Cic, Crs, Crc, Adot, Δndot, toe`。
角度及角度改正为 rad，时间导数为 rad/s 或 rad/s²，长度为 m，`toe` 为 BDT
周内秒；BDT 周单独填写。此转换面向椭圆轨道，输出拟合 RMS（m）与 60 行 RVT CSV。

### TLE 递推

输入两行 TLE、递推天数、步长和输出间隔，调用 `Sgp4EcefTool.exe`。采样点数量
受 `limits.max_sgp4_samples` 限制。结果表默认显示 15 行数据，可点击
“复制数据”把全部采样点（含表头）复制为 CSV。

### TLE 查询

输入 1–10 个 NORAD ID（逗号、空格或换行分隔）。结果按行展示名称、NORAD、
入轨日期、TLE 历元与两行 TLE；每行可单独复制，也可复制全部成功结果。
离线时按 ID 返回错误，不影响其他卫星。

左侧“最新一天发射的航天器”从 CelesTrak SATCAT 的最近 30 天记录中选取最新
发射日，仅列出载荷（`PAY`），显示名称、NORAD ID、国际编号、国家/发射场和在轨
状态；数据缓存 30 分钟，可点击“刷新”强制更新。5 位 NORAD ID 可直接“添加”到
查询栏；6 位 NORAD ID 因 TLE 格式限制暂不可添加。

左侧“已保存 NORAD ID”读取 `config/user/norad_ids.txt`；保存按钮把当前查询栏
中的 ID 追加到本地文件，列表中的“添加”写入查询栏，“删除”同时从列表和文件移除。

保存列表按 GCAT `satcat.tsv` 的 `State` 字段分为“中国”和“国外”两列：
`CN` 为中国，其他已识别国家显示国家代码，未匹配的 ID 归入国外列并标注
“未分类”。分类结果缓存在 `config/user/norad_countries.json`，只有遇到新 ID
时才批量下载 GCAT 目录；数据源不可用时列表仍正常显示。

### 三维显示

三维显示页使用 Starlink V3 概念模型（右手系），不更改仿真使用的
`star_001.json`。模型以箱体表示总线平台，双长展太阳翼沿 ±Y 展开，表面以
网格表示太阳能阵列；平台上展示相控阵面、四个四频段 RF 回传天线、六个光学
星间链路端口及推进组件。拖动旋转、滚轮缩放，支持自动旋转和太阳翼展开/
收拢，右侧列出公开特征与模型说明。

**尺寸免责声明**：SpaceX 尚未公开 V3 的完整机械图、准确质量、外形尺寸、
太阳翼总翼展或部件精确布局。模型仅依据公开的功能特征制作；太阳翼采用约
19 m 级太阳毯段作为比例参考，整翼长度、平台大小、天线/链路位置均为视觉
示意，不能用于工程、仿真或制造。通信能力数字（下行 >1 Tbps、上行 >200 Gbps、
2048 个上下行波束、6 个 400 Gbps 光学链路、4 个四频段回传天线、太阳能发电
约为 V2 的 2 倍）为 SpaceX 公布的设计目标/特征。

资料来源：[Starlink Version 3 Satellites](https://starlink.com/updates/starlink-version-3-satellites)
 · [Starlink Progress 2025](https://starlink.com/public-files/starlinkProgressReport%5F2025.pdf)

### F10.7 空间环境

展示 NASA OMNI2 的最新日 F10.7（1 AU 调整值）、81 天均值和近 183 天变化曲线；
数据缓存 30 分钟，“刷新数据”强制重新拉取。曲线数据可一键复制为 CSV。

## 6. HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/info` | 版本、exe 状态、场景、CSV 配置、限制、EOP |
| GET | `/api/scenarios` | 场景列表 |
| GET | `/api/profiles` | CSV 配置列表 |
| GET | `/api/jobs` | 历史任务 |
| GET | `/api/jobs/<id>?limit=N` | 任务详情与 CSV 预览 |
| GET | `/api/jobs/<id>/log?tail=N` | 日志尾部 |
| GET | `/api/jobs/<id>/file?name=...` | 下载产物 |
| GET | `/api/norad/saved` | 读取已保存的 NORAD ID 及中国/国外分组 |
| GET | `/api/celestrak/recent-launches` | 最新一天发射的载荷 |
| GET | `/api/spacecraft/model?name=star_001` | 从配置文件推导的航天器模型 |
| GET | `/api/spacecraft/model?model=starlink-v3&expand=1` | Starlink V3 概念外观模型 |
| GET | `/api/f107?refresh=1` | F10.7 最新值与近半年序列 |
| POST | `/api/run` | `{scenario, simulation_time?, csv_profile}` |
| POST | `/api/norad/saved` | 保存 `{norad_ids}`（追加去重） |
| POST | `/api/norad/saved/delete` | 删除 `{norad_id}` |
| POST | `/api/jobs/<id>/stop` | 停止当前任务 |
| DELETE | `/api/jobs/<id>` | 删除任务 |
| DELETE | `/api/jobs` | 清理所有非运行中任务 |
| POST | `/api/aps` | APS 转换 |
| POST | `/api/orbit/convert` | J2000 RV 与六根数互转 |
| POST | `/api/rv18/convert` | 惯性系 RVT 与 18Eph 互转 |
| POST | `/api/sgp4` | SGP4 递推 |
| POST | `/api/celestrak` | TLE 查询 |

详细请求/响应见 [docs/API.md](docs/API.md)。所有 POST 必须使用
`Content-Type: application/json`。

## 7. 安全与资源限制

- 默认只监听 `127.0.0.1`，没有登录鉴权，不要直接暴露公网；
- 校验 `Host`、`Origin`、`Sec-Fetch-Site`，POST/DELETE 拒绝跨站请求；
- 响应包含 CSP、`X-Frame-Options`、`X-Content-Type-Options` 等安全头；
- 非本机监听必须显式 `--allow-remote`，且当前版本仍无鉴权；
- 只能运行 `config/tool.json` 中配置的 exe；
- 场景名、NORAD ID、CSV 配置名、任务 ID 和下载路径均做白名单/越界校验；
- 同一时间只允许一个仿真任务；停止使用 Windows `taskkill /T /F`；
- 仿真时长、SGP4 采样点、CSV 预览扫描行数和历史保留数量均可配置；
- 下载采用流式输出，日志只读尾部。

安全问题请阅读 [SECURITY.md](SECURITY.md)，不要公开提交漏洞细节。

## 8. 开发与测试

```powershell
python -m pip install -r requirements-dev.txt
python -m py_compile app.py test_app.py
python -m unittest discover -v
python -m ruff check .
python -m black --check .
node --check static/app.js
```

当前测试 46 项，覆盖 CSV 导出、预览降采样、路径校验、配置校验、APS/SGP4 参数、
Host/Origin、Content-Type、任务清理、NORAD 保存/删除、国家分组、最新发射解析、
J2000 RV 六根数互转、航天器模型推导和 F10.7 解析。

`app.py` 运行时只使用 Python 标准库，支持 Python 3.9+。Ruff/Black 开发工具
当前要求 Python 3.10+；CI 在 Python 3.12 上执行 lint，在 3.9–3.13 上执行测试。
Node.js 仅用于前端语法检查。

## 9. 数据与许可

本项目采用 **Apache License 2.0**，见 [LICENSE](LICENSE)。

- `bin/` 中的二进制来自 BlueSpace 项目（Apache-2.0），来源和 SHA256 见
  [bin/README.md](bin/README.md)；
- 第三方组件、SGP4 署名和数据来源见 [NOTICE](NOTICE)、
  [third_party/README.md](third_party/README.md)；
- EGM2008、IGRF、EOP、Celestrak、NASA OMNI2 的版本和更新方式见
  [docs/DATA.md](docs/DATA.md)；
- 首页已改为纯黑背景，仓库不再包含背景图片；
- 维护者当前主要面向研究与教学用途，第三方数据/二进制遵循原始许可。

> EOP 数据当前截止 2025-12-27；运行 2026 年及之后场景时，页面顶部会显示过期提示。

## 10. 贡献、支持与文档

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- [SUPPORT.md](SUPPORT.md)
- [ROADMAP.md](ROADMAP.md)
- [CHANGELOG.md](CHANGELOG.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/API.md](docs/API.md)
- [docs/INTEGRATION.md](docs/INTEGRATION.md)
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- [docs/DATA.md](docs/DATA.md)

# HTTP API

默认地址：`http://127.0.0.1:8765/`。

## 通用约定

- 请求和响应均为 JSON；POST 必须携带
  `Content-Type: application/json`。
- 成功响应：`{"ok": true, ...}`。
- 失败响应：`{"ok": false, "error": "..."}`，HTTP 状态码表示错误类别。
- 默认只允许 `127.0.0.1` / `localhost` 的 `Host` 和同源 `Origin`。
- 响应包含 CSP、`X-Frame-Options`、`X-Content-Type-Options` 等安全头。

## 状态码

| 状态码 | 说明 |
| --- | --- |
| 200 | 成功 |
| 400 | 参数错误、路径非法 |
| 403 | Host/Origin/跨站请求被拒绝 |
| 404 | 资源不存在 |
| 409 | 任务冲突或已结束 |
| 415 | Content-Type 不是 JSON |
| 500 | 内部错误（不返回异常细节） |

## 端点

### `GET /api/health`

```json
{"ok": true, "name": "SatelliteTool", "version": "0.2.0"}
```

### `GET /api/info`

返回版本、exe 状态、运行目录、场景、CSV 配置、限制、历史策略和 EOP 状态。
`eop.stale_days` 大于 30 时前端会显示过期提示。

### `GET /api/scenarios`

```json
{"ok": true, "scenarios": [{"name": "baseline", "simulation_time": 1000}]}
```

### `GET /api/profiles`

```json
{"ok": true, "profiles": [{"name": "default", "description": "...", "columns": 8}]}
```

### `GET /api/jobs`

返回按创建时间倒序的任务摘要数组。

### `GET /api/jobs/<id>?limit=20`

返回任务详情、文件列表和 CSV 预览。`limit` 为 1–200，默认 20。
`preview.truncated` 为 true 时表示只扫描了前若干行。

### `GET /api/jobs/<id>/log?tail=65536`

返回日志尾部文本，`tail` 最大 1 MiB。

### `GET /api/jobs/<id>/file?name=...`

下载任务目录内的文件。`name` 必须在任务目录内，禁止路径穿越。

### `POST /api/run`

```json
{
  "scenario": "baseline",
  "csv_profile": "default",
  "simulation_time": 30
}
```

`simulation_time` 可省略，使用场景默认值；上限见 `/api/info` 的
`limits.max_simulation_time_s`。

### `POST /api/jobs/<id>/stop`

停止当前运行的仿真任务。

### `DELETE /api/jobs/<id>`

删除一个非运行中的任务。

### `DELETE /api/jobs`

清理所有非运行中的历史任务。

### `POST /api/aps`

```json
{
  "mode": "o2m",
  "epoch": "20260101T000000.0000",
  "a_km": 7000,
  "e": 0.001,
  "i_deg": 98,
  "raan_deg": 30,
  "argp_deg": 40,
  "m_deg": 50
}
```

`mode` 为 `o2m`（瞬根→平根）或 `m2o`（平根→瞬根）。返回 `result` 对象，
包含 `input`、`osculating`、`mean`、`epoch` 和 `end_of_life`。

### `POST /api/orbit/convert`

J2000 位置速度与六根数（`a/e/i/Ω/ω/M`）双向转换，纯 Python 二体计算，
`mu` 可选，默认 398600.4418 km³/s²。

RV → 六根数：

```json
{
  "mode": "rv2el",
  "mu": 398600.4418,
  "r_km": [477.5, -848.5, 6927.4],
  "v_km_s": [-6.5397, -3.7748, -0.0057]
}
```

返回 `result.mode = "rv2el"`，`result.elements` 包含 `a_km`、`e`、`i_deg`、
`raan_deg`、`argp_deg`、`m_deg`、`nu_deg`、`period_min`、`r_norm_km`、
`v_norm_km_s`。

六根数 → RV：

```json
{
  "mode": "el2rv",
  "mu": 398600.4418,
  "a_km": 7000,
  "e": 0.001,
  "i_deg": 98,
  "raan_deg": 30,
  "argp_deg": 40,
  "m_deg": 50
}
```

返回 `result.mode = "el2rv"`，包含 `r_km`、`v_km_s`、`r_norm_km`、
`v_norm_km_s`。仅支持椭圆轨道（`e < 1`、能量为负），否则返回 400。

### `POST /api/rv18/convert`

将 `**` 格式的 18 参数与 60 组 J2000 惯性系 RVT 相互转换。
状态递推、拟合与线性方程求解均由 Python 进程内实现；不调用 MATLAB、
MATLAB Runtime 或 `.m` 脚本。

RVT → 18 参数：

```json
{
  "mode": "rvt2eph",
  "units": "km",
  "start_utc": "2024-09-01T03:00:00Z",
  "rvt": [
    [6913.809933, -1192.067359, 421.023692, 0.47815, 4.838418, 5.750788]
  ]
}
```

`rvt` 实际必须提供 60 行，每行依次是 `Rx,Ry,Rz,Vx,Vy,Vz`。也可在前端粘贴
带首列时间的 7 列数据；时间列需每行间隔 60 秒。`units` 可为 `km`（位置 km、
速度 km/s）或 `m`（位置 m、速度 m/s）。RVT → 18 参数用位置残差最小二乘拟合，
速度仅用于初始轨道根数；响应包含 `parameters`（18 项）、`bdt_week`、
`fit_error_rms_m`、`iterations` 和 `converged`。UTC 转 BDT 按 GNC 代码中的
`BDT = UTC + 4 s`，BDT 周内秒为第 18 参数 `toe`。

18 参数 → RVT：

```json
{
  "mode": "eph2rvt",
  "units": "km",
  "bdt_week": 974,
  "parameters": [
    7000000, 0.01, 0.9, 1, 0.5, 0.3,
    1e-8, -1e-7, 1e-9, 1e-6, -2e-6, 3e-7, -4e-7,
    100, 50, 0.01, 1e-12, 10804
  ]
}
```

`parameters` 顺序为 `a,e,i0,Ω0,ω,M0,Δn0,Ωdot,idot,Cus,Cuc,Cis,Cic,Crs,Crc,Adot,Δndot,toe`。
单位依次为 m、无量纲、rad、rad、rad、rad、rad/s、rad/s、rad/s、rad、rad、rad、
rad、m、m、m/s、rad/s²、BDT 周内秒。`bdt_week` 单独给出。响应 `samples`
含 60 项，每项为 `{t_s, r:[x,y,z], v:[vx,vy,vz]}`，时间从 0 到 3540 秒，
间隔 60 秒；位置/速度单位由 `units` 决定。只支持椭圆轨道。

### `POST /api/sgp4`

```json
{
  "line1": "1 ...",
  "line2": "2 ...",
  "duration_days": 2,
  "step_minutes": 2,
  "sample_minutes": 120
}
```

返回 `result.samples` 数组，每项包含 `t_min`、`utc`、`r_km`、`v_km_s`。
采样点数量受 `limits.max_sgp4_samples` 限制。

### `GET /api/norad/saved`

返回 `config/user/norad_ids.txt` 中的 ID 及国家分组：

```json
{
  "ok": true,
  "norad_ids": [65106, 25544, 99999],
  "count": 3,
  "groups": {
    "china": [65106],
    "foreign": [25544],
    "unknown": [99999]
  },
  "states": {"65106": "CN", "25544": "US"},
  "classification": {
    "source": "GCAT satcat.tsv",
    "source_url": "https://planet4589.org/space/gcat/tsv/cat/satcat.tsv",
    "updated_at": "2026-11-21 08:05:22"
  }
}
```

`groups.china` 为 `State=CN` 的 ID；`groups.foreign` 为其他已识别国家；
`groups.unknown` 为 GCAT 未匹配的 ID，页面将其归入国外列并标注“未分类”。
分类缓存在 `config/user/norad_countries.json`，数据源失败时
`classification.warning` 会说明原因。

### `POST /api/norad/saved`

```json
{"norad_ids": "25544, 48274"}
```

校验并追加去重，最多保存 200 个；返回 `norad_ids`、`added`、`count`，
以及上述 `groups`、`states`、`classification` 字段。

### `POST /api/norad/saved/delete`

```json
{"norad_id": 48274}
```

从本地文件删除单个 ID；返回 `norad_ids`、`removed`、`count`，以及上述分组字段。

### `GET /api/celestrak/recent-launches?refresh=1`

从 CelesTrak SATCAT 的 `GROUP=last-30-days` 记录中选取最新发射日，仅返回
`OBJECT_TYPE=PAY` 的载荷：

```json
{
  "ok": true,
  "launch_date": "2026-11-18",
  "count": 1,
  "objects": [
    {
      "name": "SHIJIAN-24 (SJ-24)",
      "norad_id": 101415,
      "object_id": "2026-259A",
      "owner": "PRC",
      "launch_date": "2026-11-18",
      "launch_site": "TAISC",
      "decay_date": "",
      "in_orbit": true,
      "tle_available": false
    }
  ],
  "source": "CelesTrak SATCAT (last 30 days)",
  "source_url": "https://celestrak.org/satcat/records.php?GROUP=last-30-days&FORMAT=JSON",
  "fetched_at": "2026-11-21 08:05:22",
  "cached": false,
  "stale": false
}
```

`tle_available` 表示该 NORAD ID 能否用 TLE 格式查询（6 位 ID 为 `false`）。
缓存时间由 `celestrak.recent_launches_cache_ttl_s` 控制，默认 1800 秒；
`refresh=1` 强制刷新；数据源失败时返回上次缓存并设置 `stale=true`、`warning`。

### `GET /api/spacecraft/model?name=star_001&expand=1`

读取 `runtime/cfg/spacecraft/<name>.json` 并推导三维示意模型：

```json
{
  "ok": true,
  "name": "star_001",
  "sate_name": "star_001",
  "series": "StarHalo",
  "mass_kg": 664.36,
  "expand_flags": [{"index": 0, "name": "+YSADA", "expanded": true}],
  "nodes": [
    {
      "id": 3,
      "name": "+Y太阳翼",
      "parent": 2,
      "kind": "sunwing",
      "position": [2.216, 0, 0.016],
      "dcm": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
      "size": [4.3, 2.1, 0.06],
      "color": "#2f6fb0",
      "mass_kg": 34.228,
      "connect_point": [1.7749, 0, -0.01344]
    }
  ],
  "info": [{"label": "卫星名称", "value": "star_001"}]
}
```

`name` 必须为字母、数字、点、下划线或连字符；文件不存在返回 404。
`expand=1/0` 覆盖 `ModuleExpandFlag` 的前两项（太阳翼）展开状态，
省略时按配置文件原值。`nodes` 中 `kind` 为 `body`、`link`、`sunwing`、
`star-base`、`star-cone`、`engine`、`wheel`，`shape` 为 `box`、
`cylinder`（动量轮，星内扁圆柱）或 `cone`（星敏遮光罩）；连杆从本体
`ConnectPoint` 延伸到翼面连接点并再深入帆板 0.15 m；星敏指向由
`PosQbs` 四元数推导并投影到星表，电推按推力方向安装在星表。配置没有
显式几何时按质量特性给出示意尺寸，`info` 为页面参数表。

### `GET /api/spacecraft/model?model=starlink-v3&expand=1`

返回 Starlink V3 外观概念模型，不读取或修改仿真用的 `star_001.json`。
`expand=1/0` 控制双太阳翼展开/收拢。返回 `nodes` 包含 `solar-array`、
`phased-array`、`rf-backhaul`、`optical-terminal` 和 `thruster` 等示意部件；
`info` 将公开能力目标与未公开机械尺寸分别标注。

可核实的 SpaceX 公开特征包括：V3 下行目标超过 1 Tbps、2025 年资料中的
上行目标超过 200 Gbps、2048 个上下行波束、6 个 400 Gbps 光学星间链路、
4 个四频段 RF 回传天线，以及太阳翼发电量约为 V2 的两倍。V3 完整机械图、
准确外形尺寸、整翼翼展和部件布局没有公开；模型中约 19 m 的太阳毯段比例、
外形尺寸和设备布置仅作可视化示意，不应作为工程尺寸使用。

来源：[Starlink Version 3 Satellites](https://starlink.com/updates/starlink-version-3-satellites)、
[Starlink Progress 2025](https://starlink.com/public-files/starlinkProgressReport%5F2025.pdf)。

### `GET /api/f107?refresh=1`

返回 NASA OMNI2 最新日 F10.7（1 AU）、81 天均值和近 183 天序列：

```json
{
  "ok": true,
  "source": "NASA OMNI2 (F10.7, 1 AU)",
  "unit": "sfu",
  "latest": {"date": "2026-11-15", "flux": 119.3, "last81": 110.0},
  "series": [{"date": "2026-05-16", "flux": 111.5, "last81": 125.5}],
  "range": {"start": "2026-05-16", "end": "2026-11-15", "count": 184}
}
```

`refresh=1` 跳过 30 分钟缓存并重新拉取；数据源失败时使用上次缓存并返回
`stale=true` 和 `warning`。

### `POST /api/celestrak`

```json
{"norad_ids": "25544, 48274"}
```

最多 10 个 NORAD ID；单个 ID 失败不会影响其他结果。

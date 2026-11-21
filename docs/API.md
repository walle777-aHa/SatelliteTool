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

# 外部 exe 集成

SatelliteTool 不包含 C++ 源码，计算由 `bin/` 中的三个 Windows exe 完成。
本文记录当前调用契约，替换二进制时必须重新验证。

## 1. BlueSpace.exe

工作目录：`runtime/`

命令行：

```text
BlueSpace.exe
  --config-root   runtime/cfg
  --scenario      <scenario>
  --data-root     runtime/data
  --output-dir    runs/<job>/output
  --log-config-dir runtime/modules/log/conf
  [--simulation-time <seconds>]
```

输出：

- 标准输出/错误重定向到 `runs/<job>/job.log`；
- 成功时生成 `runs/<job>/output/sim_data.csv`；
- 退出码 0 表示成功。

## 2. ApsOrbitTool.exe

工作目录：项目根目录。

```text
ApsOrbitTool.exe
  --mode o2m|m2o
  --epoch YYYYMMDDTHHMMSS.SSSS
  --a <km>
  --e <eccentricity>
  --i <deg>
  --raan <deg>
  --argp <deg>
  --m <deg>
```

stdout 为 JSON：

```json
{
  "ok": true,
  "mode": "o2m",
  "epoch": "20260101T000000.0000",
  "input": {"a_km": 7000, "e": 0.001, "i_deg": 98, "raan_deg": 30, "argp_deg": 40, "m_deg": 50},
  "osculating": {"a_km": 7000, "e": 0.001, "i_deg": 98, "raan_deg": 30, "argp_deg": 40, "m_deg": 50},
  "mean": {"a_km": 7009.286, "e": 0.0025, "i_deg": 97.995, "raan_deg": 30.0008, "argp_deg": 72.1, "m_deg": 17.895},
  "end_of_life": false
}
```

## 3. Sgp4EcefTool.exe

工作目录：项目根目录。

```text
Sgp4EcefTool.exe
  --line1 "<TLE line 1>"
  --line2 "<TLE line 2>"
  --duration-days <days>
  --step-minutes <minutes>
  --sample-minutes <minutes>
```

stdout 为 JSON，至少包含：

```json
{
  "ok": true,
  "tle_epoch": "2000-06-27T18:50:19.000000",
  "sample_count": 25,
  "samples": [
    {"t_min": 0.0, "utc": "...", "r_km": [x, y, z], "v_km_s": [vx, vy, vz]}
  ]
}
```

## 4. 版本与兼容性

| SatelliteTool | BlueSpace 工作区 | 说明 |
| --- | --- | --- |
| 0.2.0 | `3a2b286` 对应工作区（二进制需重新构建验证） | 当前发布基线 |

发布前应在干净 Windows 10/11 x64 环境重新构建 exe，记录：

- 上游仓库 URL 和 commit/tag；
- 编译器、CMake 和 Release/Debug 配置；
- 构建日期；
- `bin/SHA256SUMS`；
- 三个工具的冒烟结果。

## 5. 替换步骤

1. 备份旧 `bin/`；
2. 替换 exe/DLL；
3. 运行 `GET /api/info` 确认路径和存在状态；
4. 运行一次 5 秒仿真、一次 APS 转换、一次 SGP4 递推；
5. 重新生成 `bin/SHA256SUMS`；
6. 更新 `bin/README.md` 和本文件的版本矩阵。

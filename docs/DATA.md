# 数据与第三方组件

本项目按 Apache License 2.0 发布，维护者当前主要面向研究与教学用途。
第三方数据、二进制和依赖仍遵循其原始许可；本文用于记录来源和版本。

## 运行数据

| 数据 | 文件 | 来源 | 当前版本/范围 |
| --- | --- | --- | --- |
| EGM2008 重力场 | `runtime/data/gravity/EGM2008.gfc` | NGA / EGM2008 | 文件头注明 EGM2008 |
| IGRF13 | `runtime/data/magnetic/IGRF13.COF` | IAGA / IGRF | 1900–2025 |
| IGRF14 | `runtime/data/magnetic/IGRF14.COF` | IAGA / IGRF | 1900–2030 |
| IERS EOP C04 | `runtime/data/EOP/eopFile.txt` | IERS | 2025-01-01 – 2025-12-27 |
| 卫星 TLE | 在线查询 | Celestrak | 实时数据，受网络和 Celestrak 服务影响 |
| F10.7 日值 | 在线查询 | NASA OMNI2 | 1 AU 调整值，当前年份/上一年文件，通常滞后数天 |
| NORAD 国家分类 | `config/user/norad_countries.json` | GCAT | 按 `satcat.tsv` 的 `State` 缓存已保存 ID，首次遇到新 ID 时更新 |

> EOP 文件当前最后日期为 2025-12-27。运行 2026 年及之后的场景时，页面顶部
> 会显示过期提示；请更新 EOP 数据或在结果中注意 UT1-UTC/极移外推误差。

## 二进制

| 组件 | 来源 | 许可 |
| --- | --- | --- |
| BlueSpace.exe | BlueSpace 项目 | Apache-2.0 |
| ApsOrbitTool.exe | BlueSpace 项目 | Apache-2.0 |
| Sgp4EcefTool.exe | BlueSpace 项目 / Vallado SGP4 | Apache-2.0 + Vallado 署名 |
| glog / gflags / protobuf / ERFA / Eigen / yaml-cpp / nlohmann-json | 见 NOTICE | BSD / MPL-2.0 / MIT |

`bin/README.md` 记录二进制来源和 SHA256；`third_party/README.md` 汇总第三方
组件和许可链接。

## SGP4 署名

SGP4 实现来自 David Vallado 的 `sgp4unit.cpp` 系列代码，源码头包含作者和
版本变更记录。再分发时请保留该署名，并遵循上游代码的许可要求。

## 更新 EOP

1. 从 IERS 获取最新 C04 数据；
2. 保持 `MJD Xpole Ypole UT1-UTC LOD dX dY` 列格式；
3. 替换 `runtime/data/EOP/eopFile.txt`；
4. 访问 `/api/info`，确认 `eop.last_date` 已更新；
5. 运行一次 5–30 秒仿真，确认结果正常。

## 更新 IGRF/EGM

替换 `runtime/data/magnetic/` 或 `runtime/data/gravity/` 文件后，必须运行
BlueSpace 的现有测试或至少完成一次仿真冒烟；不同阶数/格式可能导致读取失败。

## 图片

首页已改为纯黑背景，仓库不再包含 `mars-globe.png`，因此没有背景图授权问题。

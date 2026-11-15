# 第三方组件与数据

本项目不包含 C++ 源码，但 `bin/` 中的二进制和 `runtime/data/` 中的数据来自
第三方项目。以下为来源和许可索引；发布或再分发时请保留对应署名。

## 二进制依赖

| 组件 | 许可 | 链接 |
| --- | --- | --- |
| Google glog | BSD-3-Clause | <https://github.com/google/glog> |
| gflags | BSD-3-Clause | <https://github.com/gflags/gflags> |
| Protocol Buffers | BSD-3-Clause | <https://github.com/protocolbuffers/protobuf> |
| ERFA | BSD-3-Clause | <https://github.com/liberfa/erfa> |
| Eigen | MPL-2.0 | <https://eigen.tuxfamily.org> |
| yaml-cpp | MIT | <https://github.com/jbeder/yaml-cpp> |
| JSON for Modern C++ | MIT | <https://github.com/nlohmann/json> |
| Vallado SGP4 | 见上游代码署名 | <https://github.com/davidvallado/sgp4> |

## 数据

| 数据 | 来源 | 链接 |
| --- | --- | --- |
| EGM2008 | NGA | <https://earth-info.nga.mil/index.php?dir=wgs84&action=wgs84> |
| IGRF13 / IGRF14 | IAGA | <https://www.ngdc.noaa.gov/IAGA/vmod/igrf.html> |
| IERS EOP C04 | IERS | <https://www.iers.org/IERS/EN/DataProducts/EarthOrientationData/eop.html> |
| TLE | Celestrak | <https://celestrak.org/> |

## 说明

- 本项目按 Apache-2.0 发布，维护者当前主要面向研究与教学用途；
- 第三方二进制和数据的许可不因本项目而改变；
- 正式发布前建议把各许可证全文放入 `third_party/licenses/`，并在
  `docs/DATA.md` 中记录数据版本；
- 首页已改为纯黑背景，不再包含第三方背景图片。

# Changelog

## Unreleased

### Added

- F10.7 空间环境页：NASA OMNI2 最新日值、81 天均值和近半年曲线，
  支持复制曲线 CSV；
- TLE 查询页 NORAD ID 本地保存：`config/user/norad_ids.txt`，
  左侧列表支持添加和删除；
- 已保存 NORAD ID 按 GCAT 国家代码分为中国/国外两列，分类缓存到
  `config/user/norad_countries.json`，未匹配项标注“未分类”；
- TLE 查询页左侧新增“最新一天发射的航天器”：从 CelesTrak SATCAT 最近
  30 天记录中提取最新发射日的载荷，显示名称、NORAD ID、国家/发射场和在轨
  状态，支持一键加入查询栏；
- 新增 API：`GET /api/f107`、`GET/POST /api/norad/saved`、
  `POST /api/norad/saved/delete`、`GET /api/celestrak/recent-launches`；
  保存接口同时返回国家分组；
- 单元测试扩展到 28 项，覆盖 NORAD 保存/删除、国家分组、最新发射解析和
  F10.7 解析。

## 0.2.0 - 2026-11-15

### Changed

- 首页改为纯黑背景，移除 `mars-globe.png` 背景图；
- 首页增加 WALL-E 风格机器人、履带和眨眼动画；
- 机器人从上下左右任一边完全离开后都会从对侧进入，支持方向键控制；
  手动操作暂停自动行走，松开后自动恢复；
- 版本号统一为 `0.2.0`，运行期从 `config/tool.json` 读取。

### Security

- 校验 `Host`、`Origin`、`Sec-Fetch-Site`，阻止跨站 POST/DELETE；
- POST 强制要求 `Content-Type: application/json`；
- 增加 CSP、`X-Frame-Options`、`X-Content-Type-Options` 等安全响应头；
- 非本机监听必须显式使用 `--allow-remote`；
- 错误响应不再直接暴露 Python 异常文本；
- 下载改为流式输出，限制内部日志读取大小。

### Added

- 仿真时长上限、磁盘空间检查和历史任务保留策略；
- SGP4 采样点上限；
- CSV 预览流式降采样、扫描上限和缓存；
- 日志 tail 接口与前端增量读取；
- 历史任务清理 API/UI；
- 任务删除 API；
- EOP 数据日期和过期警告条；
- 浏览器前进/后退 hash 路由；
- 页面刷新后恢复运行中任务的轮询；
- fetch 超时、轮询重试、提交按钮禁用和复制回退检查；
- 无障碍标签、`aria-live`、favicon、`prefers-reduced-motion` 样式；
- `docs/`、`bin/README.md`、`THIRD_PARTY` 说明、CI、issue/PR 模板；
- 测试扩展到 17 项，覆盖预览、路径、配置、APS/SGP4 校验和任务清理。

### Removed

- `static/assets/mars-globe.png` 及其 CSS 引用。

## 0.1.0 - 2026-11-14

- 初始版本：仿真、APS 轨道转换、SGP4 TLE 递推、TLE 查询、CSV 定制和历史任务。

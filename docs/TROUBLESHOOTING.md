# 排错

## 启动失败

### `python` 找不到

安装 Python 3.9+，并确保加入 PATH；或在 `start.bat` 所在目录使用
`py -3 app.py --open`。

### 端口被占用

```powershell
python app.py --port 8785 --open
```

服务会给出“无法监听”的错误，而不是直接抛出 traceback。

### 非 Windows 系统

运行 exe 需要 Windows。仅调试 Web 层时可使用：

```powershell
python app.py --allow-non-windows
```

### 非本机监听被拒绝

默认只允许 `127.0.0.1`/`localhost`。如确需在可信网络使用：

```powershell
python app.py --host 0.0.0.0 --allow-remote
```

当前版本没有登录鉴权，不要暴露到公网。

## 页面空白或请求被拒绝

- 确认浏览器访问的是 `http://127.0.0.1:<port>`，不要用其他域名；
- 403 通常表示 `Host` 或 `Origin` 不在允许列表；
- 415 表示 POST 没有使用 `Content-Type: application/json`；
- 浏览器控制台出现 CSP 错误时，请提交 issue 并附上完整错误。

## 缺少 exe 或 DLL

打开首页查看“运行环境”中的缺失项，或访问 `/api/info`。确认：

```text
bin/BlueSpace.exe
bin/ApsOrbitTool.exe
bin/Sgp4EcefTool.exe
bin/*.dll
```

若 DLL 缺失，Windows 事件查看器或 `job.log` 通常会显示加载失败信息。

## 仿真任务一直 running

- 查看 `runs/<job>/job.log` 最后 100 行；
- 确认 BlueSpace 进程是否仍在运行；
- 若服务异常退出，`job.json` 可能保留 running 状态，可删除该任务目录；
- 使用页面“停止”或 API `POST /api/jobs/<id>/stop` 终止任务。

## 预览只显示前若干行

运行中的任务默认只扫描前 200,000 行；完成后会按完整文件重新生成预览。
如果文件非常大，`preview.truncated` 会为 true，页面显示“预览范围”。

## 磁盘空间不足

仿真启动前会按仿真时长估算 CSV 大小。清理 `runs/` 历史任务，或降低
`simulation_time`。

## TLE 查询失败

- 需要能访问 `celestrak.org`；
- 检查代理、防火墙和 DNS；
- 单个 NORAD ID 失败不会影响其他结果；
- 离线时可使用“TLE 递推”手动粘贴两行 TLE。

## EOP 数据过期

页面顶部的数据警告条会显示 EOP 最后日期；超过 30 天会标记为过期。更新方法见
[DATA.md](DATA.md)。

## 清理历史

页面“历史任务 → 清理历史”会删除所有非运行中任务。也可以直接删除
`runs/` 下对应目录。

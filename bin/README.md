# bin 目录说明

本目录包含 SatelliteTool 依赖的 Windows 可执行文件和 DLL。项目不包含 C++ 源码，
这些文件由 BlueSpace 项目构建。

## 来源

- 上游项目：<https://github.com/walle777-aHa/bluespace>
- 打包时记录的上游工作区 revision：`3a2b286e47202abfd4d3f8fda634c6d2b05e1d37`
- 构建目标：Windows x64 Release
- 构建方式：见上游 `docs/BUILD.md` 和 CMake presets

> `3a2b286` 是打包时记录的工作区 revision，不保证与每个二进制逐字节可复现。
> 正式发布前建议在干净环境重新构建，并更新本文件和 `SHA256SUMS`。

## 文件

| 文件 | 用途 |
| --- | --- |
| `BlueSpace.exe` | 卫星仿真主程序 |
| `ApsOrbitTool.exe` | APS 瞬根/平根转换 |
| `Sgp4EcefTool.exe` | SGP4 TLE → ECEF 递推 |
| `erfa.dll` | ERFA 天文库 |
| `gflags.dll` / `gflags_nothreads.dll` | gflags |
| `glog.dll` | glog |
| `libprotobuf.dll` / `libprotobuf-lite.dll` | Protocol Buffers |
| `libprotoc.dll` | Protocol Buffers 编译器库；如确认运行期不需要可删除 |

## 校验

```powershell
Get-FileHash bin\*.exe,bin\*.dll -Algorithm SHA256
```

或对照 [SHA256SUMS](SHA256SUMS)。

## 替换二进制

1. 备份当前 `bin/`；
2. 替换 exe/DLL；
3. 在干净 Windows 环境运行仿真、APS、SGP4 冒烟；
4. 重新生成 `SHA256SUMS`；
5. 更新本文件的 revision 和构建信息；
6. 更新 `docs/INTEGRATION.md` 的版本矩阵。

## 许可

BlueSpace 及本目录中的 BlueSpace 构建产物按 Apache-2.0 发布；第三方组件
（glog、gflags、protobuf、ERFA、Eigen、yaml-cpp、nlohmann-json、Vallado SGP4）
的归属见根目录 [NOTICE](../NOTICE) 和 [third_party/README.md](../third_party/README.md)。

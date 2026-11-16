#!/usr/bin/env python3
"""SatelliteTool: a small Windows desktop web tool around BlueSpace executables.

The tool intentionally contains no C++ source. It invokes the compiled
BlueSpace.exe, ApsOrbitTool.exe and Sgp4EcefTool.exe, and can rewrite the
simulation CSV according to a JSON telemetry profile.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "tool.json"
STATIC_DIR = BASE_DIR / "static"
RUNS_DIR = BASE_DIR / "runs"
MAX_NORAD_IDS = 10
NORAD_RE = re.compile(r"^\d{1,6}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
EPOCH_RE = re.compile(r"^\d{8}T\d{6}\.\d{4}$")

CELESTRAK_GP_TLE = "https://celestrak.org/NORAD/elements/gp.php?CATNR={id}&FORMAT=TLE"
CELESTRAK_GP_JSON = "https://celestrak.org/NORAD/elements/gp.php?CATNR={id}&FORMAT=JSON"
CELESTRAK_SATCAT = "https://celestrak.org/satcat/records.php?CATNR={id}&FORMAT=JSON"
CELESTRAK_CACHE: Dict[int, Tuple[float, Dict[str, Any]]] = {}
CELESTRAK_CACHE_LOCK = threading.Lock()
PREVIEW_CACHE: Dict[Tuple[str, int, int, int, int, Optional[int]], Dict[str, Any]] = {}
PREVIEW_CACHE_LOCK = threading.Lock()
PREVIEW_CACHE_MAX = 8
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
STATIC_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = int(status)
        self.message = message


def config_limit(name: str, default: int) -> int:
    try:
        return int(CONFIG.get("limits", {}).get(name, default))
    except (TypeError, ValueError):
        return int(default)


def parse_limit(query: Dict[str, List[str]], default: int = 20) -> int:
    raw = query.get("limit", [str(default)])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError(400, "limit 必须是整数")
    return max(1, min(value, 200))


def host_allowed(host_header: Optional[str], allowed: Optional[set]) -> bool:
    if allowed is None:
        return True
    if not host_header:
        return False
    try:
        host = urllib.parse.urlsplit("//" + host_header).hostname
    except ValueError:
        return False
    return bool(host and host.lower() in allowed)


def origin_allowed(origin: Optional[str], allowed: Optional[set]) -> bool:
    if not origin:
        return True
    if allowed is None:
        return True
    if origin == "null":
        return False
    try:
        parsed = urllib.parse.urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return bool(parsed.hostname and parsed.hostname.lower() in allowed)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as error:
        raise SystemExit("无法读取 %s: %s" % (CONFIG_PATH, error))
    if not isinstance(config, dict):
        raise SystemExit("config/tool.json 必须是 JSON 对象")
    return config


CONFIG = load_config()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


def runtime_dir() -> Path:
    return resolve_path(CONFIG["runtime"]["working_directory"])


def config_root() -> Path:
    return runtime_dir() / CONFIG["runtime"]["config_root"]


def data_root() -> Path:
    return runtime_dir() / CONFIG["runtime"]["data_root"]


def log_config_dir() -> Path:
    return runtime_dir() / CONFIG["runtime"]["log_config_dir"]


def profiles_dir() -> Path:
    return resolve_path(CONFIG["telemetry"]["profiles_dir"])


def executable(key: str) -> Path:
    try:
        value = CONFIG["executables"][key]
    except KeyError:
        raise ApiError(500, "tool.json 缺少 executables.%s" % key)
    return resolve_path(value)


def require_executable(key: str) -> Path:
    path = executable(key)
    if not path.is_file():
        raise ApiError(
            500,
            "找不到 %s：%s。请把对应 exe 放入 bin/，或修改 config/tool.json" % (key, path),
        )
    return path


def read_json_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ApiError(415, "Content-Type 必须是 application/json")
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise ApiError(400, "Content-Length 无效")
    if length <= 0 or length > 2 * 1024 * 1024:
        raise ApiError(400, "请求体为空或过大")
    raw = handler.rfile.read(length)
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ApiError(400, "请求体不是有效 JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "请求体必须是 JSON 对象")
    return body


def eop_status() -> Dict[str, Any]:
    path = data_root() / "EOP" / "eopFile.txt"
    if not path.is_file():
        return {"available": False}
    last_mjd = None
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                try:
                    last_mjd = int(float(text.split()[0]))
                except (IndexError, ValueError):
                    continue
    except OSError:
        return {"available": False}
    if last_mjd is None:
        return {"available": False}
    last_date = (datetime(1858, 11, 17) + timedelta(days=last_mjd)).date()
    stale_days = (datetime.now().date() - last_date).days
    return {
        "available": True,
        "last_mjd": last_mjd,
        "last_date": last_date.isoformat(),
        "stale_days": stale_days,
    }


def list_scenarios() -> List[Dict[str, Any]]:
    scenarios_dir = config_root() / "scenarios"
    default_time = None
    default_path = config_root() / "sim" / "default.yaml"
    if default_path.is_file():
        text = default_path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^\s*simulation_time:\s*(-?\d+)", text, re.M)
        if match:
            default_time = int(match.group(1))
    items = []
    if scenarios_dir.is_dir():
        for path in sorted(scenarios_dir.glob("*.yaml")):
            if not NAME_RE.fullmatch(path.stem):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"^\s*simulation_time:\s*(-?\d+)", text, re.M)
            items.append(
                {
                    "name": path.stem,
                    "simulation_time": int(match.group(1)) if match else default_time,
                }
            )
    return items


def list_profiles() -> List[Dict[str, Any]]:
    items = []
    directory = profiles_dir()
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            if not NAME_RE.fullmatch(path.stem):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                description = str(data.get("description", ""))
                columns = data.get("columns") or []
                items.append(
                    {
                        "name": path.stem,
                        "description": description,
                        "columns": len(columns),
                    }
                )
            except (OSError, ValueError) as error:
                items.append(
                    {"name": path.stem, "description": "配置错误: %s" % error, "columns": 0}
                )
    return items


def load_profile(name: str) -> Dict[str, Any]:
    if not NAME_RE.fullmatch(name or ""):
        raise ApiError(400, "非法 CSV 配置名")
    path = profiles_dir() / (name + ".json")
    if not path.is_file():
        raise ApiError(400, "CSV 配置不存在: %s" % name)
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ApiError(400, "CSV 配置读取失败: %s" % error)
    if not isinstance(profile, dict):
        raise ApiError(400, "CSV 配置必须是 JSON 对象")
    profile["name"] = name
    columns = profile.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ApiError(400, "CSV 配置 columns 不能为空")
    if len(columns) > 200:
        raise ApiError(400, "CSV 配置列数不能超过 200")
    output_names = set()
    for index, column in enumerate(columns):
        if not isinstance(column, dict):
            raise ApiError(400, "columns[%d] 必须是对象" % index)
        for key in ("name", "source"):
            value = column.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ApiError(400, "columns[%d] 必须包含 name/source" % index)
            if "\n" in value or "\r" in value:
                raise ApiError(400, "columns[%d] 的 name/source 不能包含换行" % index)
        if column["name"] in output_names:
            raise ApiError(400, "CSV 输出列名重复: %s" % column["name"])
        output_names.add(column["name"])
        for key in ("scale", "offset"):
            if key not in column:
                continue
            try:
                number = float(column[key])
            except (TypeError, ValueError):
                raise ApiError(400, "columns[%d] 的 %s 必须是数字" % (index, key))
            if not math.isfinite(number):
                raise ApiError(400, "columns[%d] 的 %s 必须是有限数字" % (index, key))
        if "precision" in column:
            try:
                precision = int(column["precision"])
            except (TypeError, ValueError):
                raise ApiError(400, "columns[%d] 的 precision 必须是整数" % index)
            if not 0 <= precision <= 15:
                raise ApiError(400, "columns[%d] 的 precision 必须在 0-15 之间" % index)
    delimiter = profile.get("delimiter", ",")
    if delimiter not in (",", ";", "\t", "|"):
        raise ApiError(400, "delimiter 必须是逗号、分号、制表符或竖线之一")
    return profile


def export_csv(raw_path: Path, profile: Dict[str, Any], out_path: Path) -> Dict[str, Any]:
    delimiter = profile.get("delimiter", ",")
    columns = profile["columns"]
    temporary = out_path.with_name(out_path.name + ".tmp")
    try:
        with open(raw_path, newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            source_fields = reader.fieldnames or []
            missing = [
                column["source"] for column in columns if column["source"] not in source_fields
            ]
            if missing:
                raise ValueError("源 CSV 缺少字段: %s" % ", ".join(sorted(set(missing))))
            count = 0
            with open(temporary, "w", newline="", encoding="utf-8") as target:
                writer = csv.writer(target, delimiter=delimiter)
                writer.writerow([column["name"] for column in columns])
                for row in reader:
                    output = []
                    for column in columns:
                        value = row.get(column["source"], "")
                        scale = column.get("scale")
                        offset = column.get("offset")
                        precision = column.get("precision")
                        if scale is not None or offset is not None or precision is not None:
                            try:
                                number = float(value)
                                number = number * float(scale if scale is not None else 1.0)
                                number += float(offset if offset is not None else 0.0)
                                if precision is not None:
                                    value = format(number, ".%df" % max(0, int(precision)))
                                else:
                                    value = str(number)
                            except (TypeError, ValueError):
                                pass
                        output.append(value)
                    writer.writerow(output)
                    count += 1
        os.replace(temporary, out_path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return {
        "profile": profile["name"],
        "columns": [column["name"] for column in columns],
        "row_count": count,
    }


def preview_csv(
    path: Path,
    table_limit: int = 20,
    chart_limit: int = 800,
    scan_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Return table rows plus a bounded, downsampled series over the full scan.

    The chart sample is kept in memory with an online decimation strategy, so
    large CSV files do not require loading every row at once. ``scan_limit``
    is used for jobs that are still being written.
    """
    table_limit = max(1, min(int(table_limit), 200))
    chart_limit = max(2, min(int(chart_limit), 2000))
    scan_limit = None if scan_limit is None else max(1, int(scan_limit))
    stat = path.stat()
    cache_key = (
        str(path.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
        table_limit,
        chart_limit,
        scan_limit,
    )
    with PREVIEW_CACHE_LOCK:
        cached = PREVIEW_CACHE.get(cache_key)
        if cached is not None:
            return cached

    columns: List[str] = []
    table_rows: List[List[str]] = []
    chart_rows: List[List[str]] = []
    row_count = 0
    stride = 1
    last_row: Optional[List[str]] = None
    truncated = False
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        for index, row in enumerate(reader):
            if index == 0:
                columns = row
                continue
            if scan_limit is not None and row_count >= scan_limit:
                truncated = True
                break
            last_row = row
            if len(table_rows) < table_limit:
                table_rows.append(row)
            if len(chart_rows) < chart_limit:
                chart_rows.append(row)
            elif row_count % stride == 0:
                chart_rows.append(row)
            if len(chart_rows) >= chart_limit * 2:
                chart_rows = chart_rows[::2]
                stride *= 2
            row_count += 1

    if last_row is not None and (not chart_rows or chart_rows[-1] != last_row):
        chart_rows.append(last_row)
        if len(chart_rows) > chart_limit * 2:
            chart_rows = chart_rows[::2]

    result = {
        "columns": columns,
        "rows": table_rows,
        "chart_rows": chart_rows,
        "row_count": row_count,
        "limit": table_limit,
        "truncated": truncated,
    }
    with PREVIEW_CACHE_LOCK:
        PREVIEW_CACHE[cache_key] = result
        while len(PREVIEW_CACHE) > PREVIEW_CACHE_MAX:
            PREVIEW_CACHE.pop(next(iter(PREVIEW_CACHE)))
    return result


def list_files(directory: Path) -> List[Dict[str, Any]]:
    files = []
    if directory.is_dir():
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                files.append(
                    {
                        "name": path.relative_to(directory).as_posix(),
                        "size": path.stat().st_size,
                    }
                )
    return files


def safe_job_dir(job_id: str) -> Path:
    if not NAME_RE.fullmatch(job_id or ""):
        raise ApiError(400, "非法任务 ID")
    directory = (RUNS_DIR / job_id).resolve()
    if RUNS_DIR.resolve() not in directory.parents and directory != RUNS_DIR.resolve():
        raise ApiError(400, "非法任务路径")
    return directory


def safe_download(job_id: str, name: str) -> Path:
    directory = safe_job_dir(job_id)
    target = (directory / name).resolve()
    if directory not in target.parents and target != directory:
        raise ApiError(400, "非法文件路径")
    if not target.is_file():
        raise ApiError(404, "文件不存在")
    return target


def job_summary(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: job.get(key)
        for key in (
            "id",
            "kind",
            "status",
            "created_at",
            "started_at",
            "completed_at",
            "scenario",
            "csv_profile",
            "exit_code",
            "error",
        )
    }


class JobManager:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active_id: Optional[str] = None
        self.active_job: Optional[Dict[str, Any]] = None
        self.process: Optional[subprocess.Popen] = None
        self.log_handle: Optional[Any] = None
        self.stop_requested = False
        RUNS_DIR.mkdir(parents=True, exist_ok=True)

    def _running_locked(self) -> bool:
        return bool(
            self.process is not None
            and self.process.poll() is None
            and self.active_job
            and self.active_job.get("status") == "running"
        )

    def running(self) -> bool:
        with self.lock:
            return self._running_locked()

    def start_simulation(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if self.running():
            raise ApiError(409, "已有仿真任务在运行，请等待完成或先停止")
        with self.lock:
            if self._running_locked():
                raise ApiError(409, "已有仿真任务在运行，请等待完成或先停止")

        scenario = str(body.get("scenario") or CONFIG["runtime"]["default_scenario"])
        if not NAME_RE.fullmatch(scenario):
            raise ApiError(400, "非法场景名")
        scenario_path = config_root() / "scenarios" / (scenario + ".yaml")
        if not scenario_path.is_file():
            raise ApiError(400, "场景不存在: %s" % scenario)

        profile_name = str(body.get("csv_profile") or CONFIG["runtime"]["default_csv_profile"])
        profile = load_profile(profile_name)

        max_simulation_time = config_limit("max_simulation_time_s", 1_000_000)
        simulation_time = body.get("simulation_time")
        if simulation_time not in (None, ""):
            try:
                simulation_time = int(simulation_time)
            except (TypeError, ValueError):
                raise ApiError(400, "simulation_time 必须是整数秒")
            if simulation_time < 0 or simulation_time > max_simulation_time:
                raise ApiError(
                    400,
                    "simulation_time 必须在 0-%d 秒之间" % max_simulation_time,
                )

        effective_time = simulation_time
        if effective_time is None:
            match = re.search(
                r"^\s*simulation_time:\s*(-?\d+)",
                scenario_path.read_text(encoding="utf-8", errors="replace"),
                re.M,
            )
            if match:
                effective_time = int(match.group(1))
        if effective_time is None:
            default_path = config_root() / "sim" / "default.yaml"
            if default_path.is_file():
                match = re.search(
                    r"^\s*simulation_time:\s*(-?\d+)",
                    default_path.read_text(encoding="utf-8", errors="replace"),
                    re.M,
                )
                if match:
                    effective_time = int(match.group(1))
        if effective_time is not None and (
            effective_time < 0 or effective_time > max_simulation_time
        ):
            raise ApiError(
                400,
                "场景默认仿真时长必须在 0-%d 秒之间" % max_simulation_time,
            )

        exe = require_executable("simulation")
        run_dir = RUNS_DIR
        run_dir.mkdir(parents=True, exist_ok=True)
        if effective_time is not None:
            estimated_rows = int(effective_time / 0.05) + 1
            estimated_bytes = estimated_rows * 256
            free_bytes = shutil.disk_usage(run_dir).free
            if free_bytes < estimated_bytes + 200 * 1024 * 1024:
                raise ApiError(
                    400,
                    "磁盘空间不足：预计需要约 %.1f MB，当前可用 %.1f MB"
                    % (estimated_bytes / 1024.0 / 1024.0, free_bytes / 1024.0 / 1024.0),
                )
        self.prune_history()
        job_id = time.strftime("%Y%m%d-%H%M%S")
        base = job_id
        counter = 2
        while (RUNS_DIR / job_id).exists():
            job_id = "%s-%d" % (base, counter)
            counter += 1

        job_dir = RUNS_DIR / job_id
        output_dir = job_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = job_dir / "job.log"
        log_handle = open(log_path, "w", encoding="utf-8", errors="replace", newline="\n")

        command = [
            str(exe),
            "--config-root",
            str(config_root()),
            "--scenario",
            scenario,
            "--data-root",
            str(data_root()),
            "--output-dir",
            str(output_dir),
            "--log-config-dir",
            str(log_config_dir()),
        ]
        if simulation_time is not None:
            command.extend(["--simulation-time", str(simulation_time)])

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            process = subprocess.Popen(
                command,
                cwd=str(runtime_dir()),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        except OSError as error:
            log_handle.close()
            raise ApiError(500, "启动仿真失败: %s" % error)

        job = {
            "id": job_id,
            "kind": "simulation",
            "status": "running",
            "created_at": time.time(),
            "started_at": now_text(),
            "completed_at": None,
            "scenario": scenario,
            "simulation_time": simulation_time,
            "csv_profile": profile_name,
            "exit_code": None,
            "error": None,
            "command": command,
            "job_dir": str(job_dir),
            "output_dir": str(output_dir),
            "log_file": str(log_path),
            "files": [],
            "telemetry": None,
        }
        with self.lock:
            self.active_id = job_id
            self.active_job = job
            self.process = process
            self.log_handle = log_handle
            self.stop_requested = False
        self._write_job(job)
        thread = threading.Thread(
            target=self._wait_for_process, args=(job, process, profile), daemon=True
        )
        thread.start()
        return job_summary(job)

    def _wait_for_process(
        self, job: Dict[str, Any], process: subprocess.Popen, profile: Dict[str, Any]
    ) -> None:
        exit_code = process.wait()
        with self.lock:
            log_handle = self.log_handle
            self.log_handle = None
            self.process = None
            was_stopped = self.stop_requested
            self.stop_requested = False
        if log_handle is not None:
            log_handle.close()

        job["exit_code"] = int(exit_code)
        job["completed_at"] = now_text()
        job_dir = Path(job["job_dir"])
        output_dir = Path(job["output_dir"])
        raw_csv = output_dir / "sim_data.csv"
        if was_stopped:
            job["status"] = "stopped"
            job["error"] = "用户停止"
        elif exit_code == 0 and raw_csv.is_file():
            try:
                telemetry = export_csv(raw_csv, profile, job_dir / "telemetry.csv")
                job["telemetry"] = telemetry
            except Exception as error:
                traceback.print_exc()
                job["status"] = "failed"
                job["error"] = "CSV 导出失败: %s" % error
            else:
                job["status"] = "completed"
        else:
            job["status"] = "failed"
            job["error"] = (
                "仿真进程退出码 %d" % exit_code if exit_code != 0 else "未生成 sim_data.csv"
            )
        job["files"] = list_files(job_dir)
        self._write_job(job)
        with self.lock:
            if self.active_job and self.active_job.get("id") == job["id"]:
                self.active_job = job
        self.prune_history()
        with self.lock:
            if self.active_id == job["id"]:
                self.active_id = None

    def _write_job(self, job: Dict[str, Any]) -> None:
        path = Path(job["job_dir"]) / "job.json"
        temporary = path.with_suffix(".json.tmp")
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(job, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)

    def get_job(self, job_id: str, limit: int = 20) -> Dict[str, Any]:
        directory = safe_job_dir(job_id)
        path = directory / "job.json"
        if not path.is_file():
            raise ApiError(404, "任务不存在")
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ApiError(500, "任务记录读取失败: %s" % error)
        job["files"] = list_files(directory)
        preview_path = directory / "telemetry.csv"
        if not preview_path.is_file():
            preview_path = directory / "output" / "sim_data.csv"
        if preview_path.is_file():
            scan_limit = config_limit(
                (
                    "preview_scan_rows_running"
                    if job.get("status") == "running"
                    else "preview_scan_rows_finished"
                ),
                200_000 if job.get("status") == "running" else 2_000_000,
            )
            try:
                job["preview"] = preview_csv(preview_path, limit, 800, scan_limit)
            except Exception as error:
                job["preview_error"] = str(error)
        return job

    def list_jobs(self) -> List[Dict[str, Any]]:
        jobs = []
        if RUNS_DIR.is_dir():
            for path in RUNS_DIR.glob("*/job.json"):
                try:
                    job = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                jobs.append(job_summary(job))
        jobs.sort(key=lambda item: item.get("created_at") or 0, reverse=True)
        return jobs

    def prune_history(self) -> None:
        try:
            keep = max(0, int(CONFIG.get("history", {}).get("keep_jobs", 50)))
        except (TypeError, ValueError):
            keep = 50
        jobs = self.list_jobs()
        with self.lock:
            active = self.active_id
        for job in jobs[keep:]:
            job_id = job.get("id")
            if not job_id or job_id == active:
                continue
            try:
                shutil.rmtree(RUNS_DIR / job_id)
            except OSError:
                pass

    def delete_job(self, job_id: str) -> Dict[str, Any]:
        directory = safe_job_dir(job_id)
        with self.lock:
            if self.active_id == job_id and self._running_locked():
                raise ApiError(409, "不能删除正在运行的任务")
        if not (directory / "job.json").is_file():
            raise ApiError(404, "任务不存在")
        shutil.rmtree(directory)
        return {"removed": 1, "id": job_id}

    def clear_jobs(self) -> Dict[str, Any]:
        with self.lock:
            active = self.active_id
        removed = 0
        if RUNS_DIR.is_dir():
            for directory in RUNS_DIR.iterdir():
                if not directory.is_dir() or not (directory / "job.json").is_file():
                    continue
                if active and directory.name == active:
                    continue
                try:
                    shutil.rmtree(directory)
                    removed += 1
                except OSError:
                    pass
        return {"removed": removed}

    def stop(self, job_id: str) -> Dict[str, Any]:
        with self.lock:
            if not self.active_job or self.active_job.get("id") != job_id:
                raise ApiError(404, "该任务不是当前运行任务")
            process = self.process
            if process is None or process.poll() is not None:
                raise ApiError(409, "任务已经结束")
            self.stop_requested = True
            pid = process.pid
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
            )
        else:
            process.terminate()
        return {"ok": True, "message": "已请求停止任务"}

    def shutdown(self) -> None:
        with self.lock:
            process = self.process
        if process is not None and process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                )
            else:
                process.terminate()


def normalize_norad_ids(value: Any) -> List[int]:
    if isinstance(value, str):
        parts = re.split(r"[\s,;]+", value.strip())
    elif isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            parts.extend(re.split(r"[\s,;]+", str(item).strip()))
    else:
        parts = []
    ids: List[int] = []
    for part in parts:
        if not part:
            continue
        if not NORAD_RE.fullmatch(part):
            raise ApiError(400, "NORAD ID 必须是 1-6 位数字: %s" % part)
        number = int(part)
        if number < 1:
            raise ApiError(400, "NORAD ID 超出范围")
        if number not in ids:
            ids.append(number)
    if not ids:
        raise ApiError(400, "请输入至少一个 NORAD ID")
    if len(ids) > MAX_NORAD_IDS:
        raise ApiError(400, "最多同时查询 %d 颗卫星" % MAX_NORAD_IDS)
    return ids


def celestrak_get(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SatelliteTool/%s" % CONFIG.get("version", "0.1.0"),
            "Accept": "application/json, text/plain, */*",
        },
    )
    timeout = float(CONFIG.get("celestrak", {}).get("timeout_s", 20))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(2 * 1024 * 1024).decode("utf-8", "replace")


def fetch_celestrak_tle(norad_id: int) -> Dict[str, Any]:
    now = time.time()
    ttl = float(CONFIG.get("celestrak", {}).get("cache_ttl_s", 300))
    with CELESTRAK_CACHE_LOCK:
        cached = CELESTRAK_CACHE.get(norad_id)
        if cached is not None and now - cached[0] < ttl:
            return dict(cached[1])

    try:
        tle_text = celestrak_get(CELESTRAK_GP_TLE.format(id=norad_id))
        lines = [line.rstrip() for line in tle_text.splitlines() if line.strip()]
        if len(lines) < 3 or not lines[-2].startswith("1 ") or not lines[-1].startswith("2 "):
            raise ApiError(404, "Celestrak 没有该 NORAD ID 的 TLE 数据")
        name = lines[-3].strip()
        line1 = lines[-2].strip()
        line2 = lines[-1].strip()

        epoch = ""
        object_id = ""
        try:
            gp_data = json.loads(celestrak_get(CELESTRAK_GP_JSON.format(id=norad_id)))
            if isinstance(gp_data, list) and gp_data:
                entry = gp_data[0]
                epoch = str(entry.get("EPOCH", ""))
                object_id = str(entry.get("OBJECT_ID", ""))
                if not name:
                    name = str(entry.get("OBJECT_NAME", ""))
        except (ValueError, OSError, urllib.error.URLError):
            pass

        launch_date = ""
        warning = ""
        try:
            satcat_data = json.loads(celestrak_get(CELESTRAK_SATCAT.format(id=norad_id)))
            if isinstance(satcat_data, list) and satcat_data:
                entry = satcat_data[0]
                launch_date = str(entry.get("LAUNCH_DATE", ""))
                if not object_id:
                    object_id = str(entry.get("OBJECT_ID", ""))
                if not name:
                    name = str(entry.get("OBJECT_NAME", ""))
        except (ValueError, OSError, urllib.error.URLError):
            warning = "未获取到入轨日期（SATCAT 查询失败）"

        result = {
            "norad_id": norad_id,
            "ok": True,
            "name": name or ("NORAD %d" % norad_id),
            "object_id": object_id,
            "launch_date": launch_date,
            "tle_epoch": epoch,
            "tle_line1": line1,
            "tle_line2": line2,
            "warning": warning,
        }
        with CELESTRAK_CACHE_LOCK:
            CELESTRAK_CACHE[norad_id] = (now, dict(result))
        return result
    except urllib.error.HTTPError as error:
        return {"norad_id": norad_id, "ok": False, "error": "Celestrak HTTP %d" % error.code}
    except urllib.error.URLError as error:
        return {
            "norad_id": norad_id,
            "ok": False,
            "error": "Celestrak 连接失败: %s" % error.reason,
        }
    except ApiError as error:
        return {"norad_id": norad_id, "ok": False, "error": error.message}
    except Exception as error:  # noqa: BLE001
        return {"norad_id": norad_id, "ok": False, "error": str(error)}


def fetch_celestrak_batch(body: Dict[str, Any]) -> Dict[str, Any]:
    ids = normalize_norad_ids(body.get("norad_ids", body.get("query", "")))
    workers = min(3, len(ids))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(fetch_celestrak_tle, ids))
    return {"ok": True, "count": len(results), "results": results}


def run_aps(body: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(body.get("mode", ""))
    if mode not in ("o2m", "m2o"):
        raise ApiError(400, "mode 必须是 o2m 或 m2o")
    epoch = str(body.get("epoch", "")).strip()
    if not EPOCH_RE.fullmatch(epoch):
        raise ApiError(400, "epoch 格式应为 YYYYMMDDTHHMMSS.SSSS")
    try:
        datetime.strptime(epoch, "%Y%m%dT%H%M%S.%f")
    except ValueError:
        raise ApiError(400, "epoch 不是有效的 UTC 日期时间")

    fields = [
        ("a_km", "a"),
        ("e", "e"),
        ("i_deg", "i"),
        ("raan_deg", "raan"),
        ("argp_deg", "argp"),
        ("m_deg", "m"),
    ]
    values = {}
    for body_key, cli_key in fields:
        try:
            values[cli_key] = float(body.get(body_key))
        except (TypeError, ValueError):
            raise ApiError(400, "%s 必须是数字" % body_key)
        if not math.isfinite(values[cli_key]):
            raise ApiError(400, "%s 必须是有限数字" % body_key)
    if values["a"] <= 6378.137:
        raise ApiError(400, "a_km 必须大于地球半径 6378.137 km")
    if not 0 <= values["e"] < 1:
        raise ApiError(400, "e 必须在 [0, 1) 范围内")
    if not 0 <= values["i"] <= 180:
        raise ApiError(400, "i_deg 必须在 [0, 180] 范围内")
    for key, label in (("raan", "raan_deg"), ("argp", "argp_deg"), ("m", "m_deg")):
        if not 0 <= values[key] <= 360:
            raise ApiError(400, "%s 必须在 [0, 360] 范围内" % label)

    command = [
        str(require_executable("aps")),
        "--mode",
        mode,
        "--epoch",
        epoch,
        "--a",
        format(values["a"], ".15g"),
        "--e",
        format(values["e"], ".15g"),
        "--i",
        format(values["i"], ".15g"),
        "--raan",
        format(values["raan"], ".15g"),
        "--argp",
        format(values["argp"], ".15g"),
        "--m",
        format(values["m"], ".15g"),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ApiError(500, "轨道转换启动失败: %s" % error)
    if completed.returncode != 0:
        raise ApiError(500, (completed.stderr or completed.stdout or "轨道转换失败").strip())
    try:
        result = json.loads(completed.stdout)
    except ValueError:
        raise ApiError(500, "轨道转换输出不是 JSON")
    return {"ok": True, "result": result}


def run_sgp4(body: Dict[str, Any]) -> Dict[str, Any]:
    line1 = str(body.get("line1", "")).strip()
    line2 = str(body.get("line2", "")).strip()
    if not line1.startswith("1 ") or not line2.startswith("2 "):
        raise ApiError(400, "TLE 第一行必须以 '1 ' 开头，第二行以 '2 ' 开头")

    def number(key: str, default: float, low: float, high: float) -> float:
        value = body.get(key, default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ApiError(400, "%s 必须是数字" % key)
        if not math.isfinite(value) or value < low or value > high:
            raise ApiError(400, "%s 超出范围" % key)
        return value

    duration = number("duration_days", 2.0, 0.001, 3650.0)
    step = number("step_minutes", 2.0, 0.1, 1440.0)
    sample = number("sample_minutes", 120.0, 0.1, 100000.0)
    max_samples = config_limit("max_sgp4_samples", 20_000)
    estimated_samples = int(math.floor(duration * 1440.0 / sample)) + 1
    if estimated_samples > max_samples:
        raise ApiError(
            400,
            "采样点过多：预计 %d 个，上限为 %d 个；请增大输出间隔或缩短递推天数"
            % (estimated_samples, max_samples),
        )

    command = [
        str(require_executable("sgp4")),
        "--line1",
        line1,
        "--line2",
        line2,
        "--duration-days",
        format(duration, ".15g"),
        "--step-minutes",
        format(step, ".15g"),
        "--sample-minutes",
        format(sample, ".15g"),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ApiError(500, "TLE 递推启动失败: %s" % error)
    if completed.returncode != 0:
        raise ApiError(500, (completed.stderr or completed.stdout or "TLE 递推失败").strip())
    try:
        result = json.loads(completed.stdout)
    except ValueError:
        raise ApiError(500, "TLE 递推输出不是 JSON")
    return {"ok": True, "result": result}


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"


class Handler(BaseHTTPRequestHandler):
    server_version = "SatelliteTool/" + str(CONFIG.get("version", "0.1.0"))
    protocol_version = "HTTP/1.1"

    @property
    def manager(self) -> JobManager:
        return self.server.manager  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[web] %s - %s\n" % (self.address_string(), format % args))

    def send_security_headers(self) -> None:
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)

    def send_json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, error: ApiError) -> None:
        if self.command in ("POST", "DELETE"):
            self.close_connection = True
        try:
            self.send_json(error.status, {"ok": False, "error": error.message})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def enforce_safety(self) -> None:
        allowed = getattr(self.server, "allowed_hosts", LOOPBACK_HOSTS)
        if not host_allowed(self.headers.get("Host"), allowed):
            raise ApiError(403, "Host 不被允许")
        if self.command in ("POST", "DELETE"):
            site = (self.headers.get("Sec-Fetch-Site") or "").lower()
            if site and site not in ("same-origin", "none"):
                raise ApiError(403, "跨站请求被拒绝")
            if not origin_allowed(self.headers.get("Origin"), allowed):
                raise ApiError(403, "Origin 不被允许")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            self.enforce_safety()
            if path == "/api/health":
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "name": CONFIG["name"],
                        "version": CONFIG.get("version", ""),
                    },
                )
                return
            if path == "/api/info":
                self.handle_info()
                return
            if path == "/api/jobs":
                self.send_json(200, {"ok": True, "jobs": self.manager.list_jobs()})
                return
            match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_.-]+)", path)
            if match:
                query = urllib.parse.parse_qs(parsed.query)
                limit = parse_limit(query)
                self.send_json(
                    200,
                    {"ok": True, "job": self.manager.get_job(match.group(1), limit)},
                )
                return
            match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_.-]+)/log", path)
            if match:
                query = urllib.parse.parse_qs(parsed.query)
                self.handle_log_tail(match.group(1), query)
                return
            if path == "/api/profiles":
                self.send_json(200, {"ok": True, "profiles": list_profiles()})
                return
            if path == "/api/scenarios":
                self.send_json(200, {"ok": True, "scenarios": list_scenarios()})
                return
            match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_.-]+)/file", path)
            if match:
                query = urllib.parse.parse_qs(parsed.query)
                name = query.get("name", [""])[0]
                target = safe_download(match.group(1), name)
                self.send_download(target, name)
                return
            self.send_static(path)
        except (BrokenPipeError, ConnectionResetError):
            return
        except ApiError as error:
            self.send_error_json(error)
        except Exception:
            traceback.print_exc()
            self.send_error_json(ApiError(500, "服务器内部错误"))

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            self.enforce_safety()
            body = read_json_body(self)
            if path == "/api/run":
                job = self.manager.start_simulation(body)
                self.send_json(200, {"ok": True, "job": job})
                return
            if path == "/api/aps":
                self.send_json(200, run_aps(body))
                return
            if path == "/api/sgp4":
                self.send_json(200, run_sgp4(body))
                return
            if path == "/api/celestrak":
                self.send_json(200, fetch_celestrak_batch(body))
                return
            match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_.-]+)/stop", path)
            if match:
                self.send_json(200, self.manager.stop(match.group(1)))
                return
            raise ApiError(404, "接口不存在")
        except (BrokenPipeError, ConnectionResetError):
            return
        except ApiError as error:
            self.send_error_json(error)
        except Exception:
            traceback.print_exc()
            self.send_error_json(ApiError(500, "服务器内部错误"))

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            self.enforce_safety()
            if path == "/api/jobs":
                self.send_json(200, {"ok": True, **self.manager.clear_jobs()})
                return
            match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_.-]+)", path)
            if match:
                self.send_json(200, {"ok": True, **self.manager.delete_job(match.group(1))})
                return
            raise ApiError(404, "接口不存在")
        except (BrokenPipeError, ConnectionResetError):
            return
        except ApiError as error:
            self.send_error_json(error)
        except Exception:
            traceback.print_exc()
            self.send_error_json(ApiError(500, "服务器内部错误"))

    def handle_info(self) -> None:
        executables = {}
        for key in ("simulation", "aps", "sgp4"):
            path = executable(key)
            executables[key] = {"path": str(path), "exists": path.is_file()}
        self.send_json(
            200,
            {
                "ok": True,
                "name": CONFIG.get("name", "SatelliteTool"),
                "version": CONFIG.get("version", ""),
                "executables": executables,
                "runtime": {
                    "working_directory": str(runtime_dir()),
                    "config_root": str(config_root()),
                    "data_root": str(data_root()),
                    "log_config_dir": str(log_config_dir()),
                },
                "scenarios": list_scenarios(),
                "profiles": list_profiles(),
                "default_scenario": CONFIG["runtime"]["default_scenario"],
                "default_csv_profile": CONFIG["runtime"]["default_csv_profile"],
                "limits": CONFIG.get("limits", {}),
                "history": CONFIG.get("history", {}),
                "eop": eop_status(),
                "running": self.manager.running(),
            },
        )

    def handle_log_tail(self, job_id: str, query: Dict[str, List[str]]) -> None:
        directory = safe_job_dir(job_id)
        path = directory / "job.log"
        if not path.is_file():
            raise ApiError(404, "日志不存在")
        raw = query.get("tail", ["65536"])[0]
        try:
            tail = int(raw)
        except (TypeError, ValueError):
            raise ApiError(400, "tail 必须是整数")
        tail = max(1, min(tail, 1024 * 1024))
        size = path.stat().st_size
        with open(path, "rb") as handle:
            handle.seek(max(0, size - tail))
            data = handle.read(tail)
        self.send_json(200, {"ok": True, "text": data.decode("utf-8", "replace")})

    def send_static(self, path: str) -> None:
        if path in ("", "/"):
            target = STATIC_DIR / "index.html"
        elif path.startswith("/assets/"):
            target = STATIC_DIR / "assets" / path[len("/assets/") :]
        else:
            target = STATIC_DIR / path.lstrip("/")
        target = target.resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            raise ApiError(404, "文件不存在")
        if not target.is_file():
            raise ApiError(404, "文件不存在")
        content_type = STATIC_MIME_TYPES.get(target.suffix.lower())
        if not content_type:
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if content_type.startswith("text/"):
                content_type += "; charset=utf-8"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def send_download(self, target: Path, name: str) -> None:
        safe_name = name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        size = target.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header(
            "Content-Disposition",
            'attachment; filename="%s"' % safe_name,
        )
        self.send_header("Content-Length", str(size))
        self.send_security_headers()
        self.end_headers()
        try:
            with open(target, "rb") as handle:
                while True:
                    chunk = handle.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> None:
    if sys.version_info < (3, 9):
        raise SystemExit("SatelliteTool 需要 Python 3.9 或更高版本")
    parser = argparse.ArgumentParser(description="SatelliteTool local web console")
    parser.add_argument("--host", default=CONFIG.get("server", {}).get("host", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(CONFIG.get("server", {}).get("port", 8765)),
    )
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="允许非本机监听；当前版本没有登录鉴权，请仅在可信网络使用",
    )
    parser.add_argument(
        "--allow-non-windows",
        action="store_true",
        help="允许在非 Windows 系统启动服务（exe 功能不可用）",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="SatelliteTool " + str(CONFIG.get("version", "")),
    )
    args = parser.parse_args()

    if os.name != "nt" and not args.allow_non_windows:
        raise SystemExit("SatelliteTool 需要 Windows；开发调试可加 --allow-non-windows")
    if not 0 <= args.port <= 65535:
        parser.error("--port 必须在 0-65535 之间")
    if args.host not in LOOPBACK_HOSTS and not args.allow_remote:
        parser.error(
            "非本机监听需要显式加 --allow-remote；当前版本没有登录鉴权，" "请仅在本机或可信网络使用"
        )

    for directory in (RUNS_DIR, profiles_dir()):
        directory.mkdir(parents=True, exist_ok=True)
    try:
        server = LocalThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as error:
        raise SystemExit("无法监听 %s:%d：%s" % (args.host, args.port, error))
    server.manager = JobManager()  # type: ignore[attr-defined]
    server.allowed_hosts = None if args.allow_remote else set(LOOPBACK_HOSTS)  # type: ignore[attr-defined]
    if args.allow_remote:
        print("警告：已允许远程监听，当前版本没有登录鉴权。")
    host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = "http://%s:%d/" % (host, args.port)
    print("SatelliteTool %s: %s" % (CONFIG.get("version", ""), url))
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.manager.shutdown()  # type: ignore[attr-defined]
        server.server_close()


if __name__ == "__main__":
    main()

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
import http.client
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
SAVED_NORAD_FILE = BASE_DIR / "config" / "user" / "norad_ids.txt"
MAX_NORAD_IDS = 10
MAX_SAVED_NORAD_IDS = 200
SAVED_NORAD_LOCK = threading.Lock()
NORAD_RE = re.compile(r"^\d{1,6}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
EPOCH_RE = re.compile(r"^\d{8}T\d{6}\.\d{4}$")

CELESTRAK_GP_TLE = "https://celestrak.org/NORAD/elements/gp.php?CATNR={id}&FORMAT=TLE"
CELESTRAK_GP_JSON = "https://celestrak.org/NORAD/elements/gp.php?CATNR={id}&FORMAT=JSON"
CELESTRAK_SATCAT = "https://celestrak.org/satcat/records.php?CATNR={id}&FORMAT=JSON"
CELESTRAK_RECENT_LAUNCHES = (
    "https://celestrak.org/satcat/records.php?GROUP=last-30-days&FORMAT=JSON"
)
CELESTRAK_CACHE: Dict[int, Tuple[float, Dict[str, Any]]] = {}
CELESTRAK_CACHE_LOCK = threading.Lock()
RECENT_LAUNCH_CACHE: Dict[str, Any] = {"time": 0.0, "data": None}
RECENT_LAUNCH_CACHE_LOCK = threading.Lock()
F107_SOURCE_URL = "https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/omni2_{year}.dat"
F107_SOURCE_NAME = "NASA OMNI2 (F10.7, 1 AU)"
F107_CACHE: Dict[str, Any] = {"time": 0.0, "data": None}
F107_CACHE_LOCK = threading.Lock()
GCAT_SATCAT_URL = "https://planet4589.org/space/gcat/tsv/cat/satcat.tsv"
GCAT_CACHE_FILE = BASE_DIR / "config" / "user" / "norad_countries.json"
GCAT_TIMEOUT = 30
GCAT_MAX_BYTES = 32 * 1024 * 1024
GCAT_RETRY_SECONDS = 300
GCAT_UNKNOWN_TTL = 7 * 24 * 3600
GCAT_LOCK = threading.Lock()
GCAT_LAST_FAILURE = {"time": 0.0}
PREVIEW_CACHE: Dict[Tuple[str, int, int, int, int, Optional[int]], Dict[str, Any]] = {}
PREVIEW_CACHE_LOCK = threading.Lock()
PREVIEW_CACHE_MAX = 8
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
QUIET_CONNECTION_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
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
    elif isinstance(value, int):
        parts = [str(value)]
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


def read_saved_norad_ids() -> List[int]:
    if not SAVED_NORAD_FILE.is_file():
        return []
    try:
        text = SAVED_NORAD_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ApiError(500, "读取保存的 NORAD ID 失败: %s" % error)
    ids: List[int] = []
    for token in re.split(r"[\s,;]+", text):
        if not token or not NORAD_RE.fullmatch(token):
            continue
        number = int(token)
        if 1 <= number <= 999999 and number not in ids:
            ids.append(number)
        if len(ids) >= MAX_SAVED_NORAD_IDS:
            break
    return ids


def write_saved_norad_ids(ids: List[int]) -> None:
    SAVED_NORAD_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SAVED_NORAD_FILE.with_name(SAVED_NORAD_FILE.name + ".tmp")
    try:
        temporary.write_text(
            "".join("%d\n" % number for number in ids),
            encoding="utf-8",
        )
        os.replace(temporary, SAVED_NORAD_FILE)
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ApiError(500, "保存 NORAD ID 失败: %s" % error)


def save_norad_ids(value: Any) -> Dict[str, Any]:
    incoming = normalize_norad_ids(value)
    with SAVED_NORAD_LOCK:
        current = read_saved_norad_ids()
        added = [number for number in incoming if number not in current]
        if len(current) + len(added) > MAX_SAVED_NORAD_IDS:
            raise ApiError(400, "保存的 NORAD ID 最多 %d 个" % MAX_SAVED_NORAD_IDS)
        combined = current + added
        write_saved_norad_ids(combined)
    return {"norad_ids": combined, "added": len(added), "count": len(combined)}


def delete_saved_norad_id(value: Any) -> Dict[str, Any]:
    ids = normalize_norad_ids(value)
    if len(ids) != 1:
        raise ApiError(400, "一次只能删除一个 NORAD ID")
    target = ids[0]
    with SAVED_NORAD_LOCK:
        current = read_saved_norad_ids()
        if target not in current:
            return {"norad_ids": current, "removed": 0, "count": len(current)}
        combined = [number for number in current if number != target]
        write_saved_norad_ids(combined)
    return {"norad_ids": combined, "removed": 1, "count": len(combined)}


def parse_gcat_states(text: str, wanted: Optional[List[int]] = None) -> Dict[str, str]:
    """Extract Satcat -> State pairs from the GCAT satcat.tsv catalog."""
    wanted_keys = None if wanted is None else {str(number) for number in wanted}
    states: Dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) <= 15:
            continue
        satcat = parts[1].strip()
        state = parts[15].strip().upper()
        if not satcat.isdigit() or not state or state == "-":
            continue
        if wanted_keys is not None and satcat not in wanted_keys:
            continue
        states[satcat] = state
    return states


def read_norad_country_cache() -> Dict[str, Any]:
    cache: Dict[str, Any] = {
        "states": {},
        "unknown": [],
        "updated_at": None,
        "checked_at": 0.0,
    }
    if not GCAT_CACHE_FILE.is_file():
        return cache
    try:
        raw = json.loads(GCAT_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cache
    if not isinstance(raw, dict):
        return cache
    states = raw.get("states")
    if isinstance(states, dict):
        for key, value in states.items():
            key = str(key)
            if key.isdigit() and isinstance(value, str) and value.strip():
                cache["states"][key] = value.strip().upper()
    unknown = raw.get("unknown")
    if isinstance(unknown, list):
        for item in unknown:
            item = str(item)
            if item.isdigit() and item not in cache["unknown"]:
                cache["unknown"].append(item)
    updated_at = raw.get("updated_at")
    if isinstance(updated_at, str):
        cache["updated_at"] = updated_at
    checked_at = raw.get("checked_at")
    if isinstance(checked_at, (int, float)) and math.isfinite(checked_at) and checked_at > 0:
        cache["checked_at"] = float(checked_at)
    return cache


def write_norad_country_cache(states: Dict[str, str], unknown: set) -> Dict[str, Any]:
    GCAT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = GCAT_CACHE_FILE.with_name(GCAT_CACHE_FILE.name + ".tmp")
    payload: Dict[str, Any] = {
        "source": GCAT_SATCAT_URL,
        "updated_at": now_text(),
        "checked_at": time.time(),
        "states": states,
        "unknown": sorted(unknown, key=int),
    }
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, GCAT_CACHE_FILE)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return payload


def fetch_gcat_states(wanted: List[str]) -> Dict[str, str]:
    request = urllib.request.Request(
        GCAT_SATCAT_URL,
        headers={
            "User-Agent": "SatelliteTool/%s" % CONFIG.get("version", "0.2.0"),
            "Accept": "text/tab-separated-values, text/plain, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=GCAT_TIMEOUT) as response:
        raw = response.read(GCAT_MAX_BYTES + 1)
    if len(raw) > GCAT_MAX_BYTES:
        raise ValueError("GCAT 目录超过大小限制")
    return parse_gcat_states(raw.decode("utf-8", "replace"), wanted)


def resolve_norad_countries(
    ids: List[int],
) -> Tuple[Dict[str, str], set, Optional[str], Optional[str]]:
    cache = read_norad_country_cache()
    states = dict(cache["states"])
    unknown = set(cache["unknown"])
    checked_at = cache["checked_at"]
    updated_at = cache["updated_at"]
    now = time.time()
    pending: List[str] = []
    for number in ids:
        key = str(number)
        if key in states:
            continue
        if key in unknown and now - checked_at < GCAT_UNKNOWN_TTL:
            continue
        pending.append(key)

    warning = None
    if pending:
        with GCAT_LOCK:
            cache = read_norad_country_cache()
            states = dict(cache["states"])
            unknown = set(cache["unknown"])
            checked_at = cache["checked_at"]
            updated_at = cache["updated_at"]
            now = time.time()
            pending = []
            for number in ids:
                key = str(number)
                if key in states:
                    continue
                if key in unknown and now - checked_at < GCAT_UNKNOWN_TTL:
                    continue
                pending.append(key)

            if pending and now - GCAT_LAST_FAILURE["time"] >= GCAT_RETRY_SECONDS:
                try:
                    fetched = fetch_gcat_states(pending)
                except (
                    urllib.error.URLError,
                    http.client.HTTPException,
                    OSError,
                    ValueError,
                ) as error:
                    GCAT_LAST_FAILURE["time"] = time.time()
                    warning = "国家分类数据暂不可用：%s" % error
                else:
                    for key in pending:
                        state = fetched.get(key)
                        if state:
                            states[key] = state
                            unknown.discard(key)
                        else:
                            unknown.add(key)
                    try:
                        payload = write_norad_country_cache(states, unknown)
                        updated_at = payload["updated_at"]
                    except OSError as error:
                        warning = "国家分类缓存写入失败：%s" % error
                    GCAT_LAST_FAILURE["time"] = 0.0
            elif pending:
                warning = "国家分类数据暂不可用，未匹配的 ID 暂归入国外列"

    return states, unknown, updated_at, warning


def group_norad_ids_by_country(ids: List[int], states: Dict[str, str]) -> Dict[str, List[int]]:
    groups: Dict[str, List[int]] = {"china": [], "foreign": [], "unknown": []}
    for number in ids:
        state = states.get(str(number))
        if state == "CN":
            groups["china"].append(number)
        elif state:
            groups["foreign"].append(number)
        else:
            groups["unknown"].append(number)
    return groups


def norad_group_payload(ids: List[int]) -> Dict[str, Any]:
    states, _unknown, updated_at, warning = resolve_norad_countries(ids)
    payload: Dict[str, Any] = {
        "groups": group_norad_ids_by_country(ids, states),
        "states": {str(number): states[str(number)] for number in ids if str(number) in states},
        "classification": {
            "source": "GCAT satcat.tsv",
            "source_url": GCAT_SATCAT_URL,
            "updated_at": updated_at,
        },
    }
    if warning:
        payload["classification"]["warning"] = warning
    return payload


def saved_norad_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(payload)
    result.update(norad_group_payload(payload.get("norad_ids", [])))
    return result


def parse_omni2_text(text: str) -> List[Dict[str, Any]]:
    """Parse daily F10.7 values from a NASA OMNI2 yearly file."""
    by_date: Dict[str, float] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 51:
            continue
        try:
            year = int(parts[0])
            day_of_year = int(parts[1])
            hour = int(parts[2])
            flux = float(parts[50])
        except ValueError:
            continue
        if hour != 0 or not 0 < flux < 999:
            continue
        try:
            date = (datetime(year, 1, 1) + timedelta(days=day_of_year - 1)).date()
        except ValueError:
            continue
        by_date[date.isoformat()] = flux
    return [{"date": date, "flux": by_date[date]} for date in sorted(by_date)]


def build_f107_payload(
    observations: List[Dict[str, Any]], window_days: int = 183
) -> Dict[str, Any]:
    if not observations:
        raise ApiError(502, "F10.7 数据为空或格式不匹配")
    dated = [
        {
            "date": item["date"],
            "flux": item["flux"],
            "date_obj": datetime.strptime(item["date"], "%Y-%m-%d"),
        }
        for item in sorted(observations, key=lambda item: item["date"])
    ]
    latest = dated[-1]
    latest_date = latest["date_obj"]
    cutoff = latest_date - timedelta(days=window_days)
    series_rows = []
    latest_last81 = None
    for item in dated:
        item_date = item["date_obj"]
        window = [
            entry
            for entry in dated
            if item_date - timedelta(days=80) <= entry["date_obj"] <= item_date
        ]
        last81 = sum(entry["flux"] for entry in window) / len(window)
        if item_date >= cutoff:
            series_rows.append(
                {
                    "date": item["date"],
                    "flux": item["flux"],
                    "last81": last81,
                }
            )
        latest_last81 = last81
    return {
        "source": F107_SOURCE_NAME,
        "source_url": F107_SOURCE_URL.format(year=latest_date.year),
        "unit": "sfu",
        "window_days": window_days,
        "fetched_at": now_text(),
        "latest": {
            "date": latest["date"],
            "flux": latest["flux"],
            "last81": latest_last81,
        },
        "series": series_rows,
        "range": {
            "start": series_rows[0]["date"],
            "end": latest["date"],
            "count": len(series_rows),
        },
    }


def fetch_f107(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    cache_ttl = float(CONFIG.get("f107", {}).get("cache_ttl_s", 1800))
    window_days = int(CONFIG.get("f107", {}).get("window_days", 183))
    with F107_CACHE_LOCK:
        cached = F107_CACHE["data"]
        cached_at = F107_CACHE["time"]
    if not force and cached is not None and now - cached_at < cache_ttl:
        return cached

    observations: List[Dict[str, Any]] = []
    errors = []
    timeout = float(CONFIG.get("f107", {}).get("timeout_s", 20))
    current_year = datetime.now().year
    for year in (current_year - 1, current_year):
        try:
            request = urllib.request.Request(
                F107_SOURCE_URL.format(year=year),
                headers={
                    "User-Agent": "SatelliteTool/%s" % CONFIG.get("version", "0.2.0"),
                    "Accept": "text/plain, */*",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(8 * 1024 * 1024)
            observations.extend(parse_omni2_text(raw.decode("ascii", "replace")))
        except (urllib.error.URLError, OSError, ValueError) as error:
            errors.append("%d: %s" % (year, error))

    if observations:
        data = build_f107_payload(observations, window_days)
        with F107_CACHE_LOCK:
            F107_CACHE["time"] = time.time()
            F107_CACHE["data"] = data
        return data

    message = "; ".join(errors) or "没有可用的观测数据"
    with F107_CACHE_LOCK:
        cached = F107_CACHE["data"]
    if cached is not None:
        result = dict(cached)
        result["stale"] = True
        result["warning"] = "F10.7 数据源暂不可用，显示上次缓存结果: " + message
        return result
    raise ApiError(502, "无法获取 F10.7 数据: " + message)


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


def parse_recent_launches(records: Any) -> Dict[str, Any]:
    """Select payloads launched on the most recent launch day."""
    if not isinstance(records, list):
        raise ValueError("最新发射数据格式无效")

    payloads: List[Dict[str, Any]] = []
    for entry in records:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("OBJECT_TYPE", "")).strip().upper() != "PAY":
            continue
        launch_date = str(entry.get("LAUNCH_DATE", "")).strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", launch_date):
            continue
        try:
            norad_id = int(entry.get("NORAD_CAT_ID"))
        except (TypeError, ValueError):
            continue
        if norad_id <= 0:
            continue

        object_id = str(entry.get("OBJECT_ID", "")).strip()
        decay_date = str(entry.get("DECAY_DATE", "")).strip()
        payloads.append(
            {
                "name": str(entry.get("OBJECT_NAME", "")).strip() or ("NORAD %d" % norad_id),
                "norad_id": norad_id,
                "object_id": object_id,
                "owner": str(entry.get("OWNER", "")).strip(),
                "launch_date": launch_date,
                "launch_site": str(entry.get("LAUNCH_SITE", "")).strip(),
                "decay_date": decay_date,
                "in_orbit": not decay_date,
                "tle_available": norad_id <= 99999,
            }
        )

    if not payloads:
        return {"launch_date": "", "count": 0, "objects": []}

    latest_date = max(item["launch_date"] for item in payloads)
    objects = [item for item in payloads if item["launch_date"] == latest_date]
    objects.sort(key=lambda item: (item["object_id"], item["norad_id"]))
    return {"launch_date": latest_date, "count": len(objects), "objects": objects}


def fetch_recent_launches(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    ttl = float(CONFIG.get("celestrak", {}).get("recent_launches_cache_ttl_s", 1800))
    with RECENT_LAUNCH_CACHE_LOCK:
        cached = RECENT_LAUNCH_CACHE["data"]
        cached_at = RECENT_LAUNCH_CACHE["time"]
    if not force and cached is not None and now - cached_at < ttl:
        result = dict(cached)
        result["cached"] = True
        return result

    try:
        raw = celestrak_get(CELESTRAK_RECENT_LAUNCHES)
        data = parse_recent_launches(json.loads(raw))
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as error:
        with RECENT_LAUNCH_CACHE_LOCK:
            cached = RECENT_LAUNCH_CACHE["data"]
        if cached is not None:
            result = dict(cached)
            result["cached"] = True
            result["stale"] = True
            result["warning"] = "最新发射数据暂不可用，显示上次缓存结果: %s" % error
            return result
        raise ApiError(502, "无法获取最新发射数据: %s" % error)

    data.update(
        {
            "source": "CelesTrak SATCAT (last 30 days)",
            "source_url": CELESTRAK_RECENT_LAUNCHES,
            "fetched_at": now_text(),
            "cached": False,
            "stale": False,
        }
    )
    with RECENT_LAUNCH_CACHE_LOCK:
        RECENT_LAUNCH_CACHE["time"] = time.time()
        RECENT_LAUNCH_CACHE["data"] = dict(data)
    return data


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


def _vec_cross(a: List[float], b: List[float]) -> List[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _vec_dot(a: List[float], b: List[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_norm(a: List[float]) -> float:
    return math.sqrt(_vec_dot(a, a))


def _atan2_deg(y: float, x: float) -> float:
    return math.degrees(math.atan2(y, x)) % 360.0


def _clamp_one(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _orbit_number(
    body: Dict[str, Any],
    key: str,
    label: str,
    low: float,
    high: float,
    default: Optional[float] = None,
) -> float:
    raw = body.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ApiError(400, "%s 必须是数字" % label)
    if not math.isfinite(value):
        raise ApiError(400, "%s 必须是有限数字" % label)
    if value < low or value > high:
        raise ApiError(400, "%s 超出范围" % label)
    return value


def _orbit_vector(body: Dict[str, Any], key: str) -> List[float]:
    raw = body.get(key)
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        raise ApiError(400, "%s 必须是 3 个数字组成的数组" % key)
    try:
        return [float(component) for component in raw]
    except (TypeError, ValueError):
        raise ApiError(400, "%s 必须是数字" % key)


def rv_to_j2000_elements(body: Dict[str, Any]) -> Dict[str, Any]:
    """Convert J2000 position/velocity (km, km/s) to classical elements."""
    mu = _orbit_number(body, "mu", "μ", 1e-6, 1e18, 398600.4418)
    r_vec = _orbit_vector(body, "r_km")
    v_vec = _orbit_vector(body, "v_km_s")
    r = _vec_norm(r_vec)
    v = _vec_norm(v_vec)
    if r < 1e-9:
        raise ApiError(400, "位置矢量模长不能为 0")
    if v < 1e-9:
        raise ApiError(400, "速度矢量模长不能为 0")

    h_vec = _vec_cross(r_vec, v_vec)
    h = _vec_norm(h_vec)
    if h < 1e-9:
        raise ApiError(400, "角动量为 0，不构成轨道运动")

    n_vec = _vec_cross([0.0, 0.0, 1.0], h_vec)
    n = _vec_norm(n_vec)
    rv = _vec_dot(r_vec, v_vec)

    energy = v * v / 2.0 - mu / r
    a = -mu / (2.0 * energy)
    if not math.isfinite(a) or a <= 0:
        raise ApiError(400, "轨道能量非负（a <= 0），仅支持椭圆轨道")

    e_vec = [((v * v - mu / r) * r_vec[k] - rv * v_vec[k]) / mu for k in range(3)]
    e = _vec_norm(e_vec)
    if e >= 1.0:
        raise ApiError(400, "偏心率 e >= 1，仅支持椭圆轨道")

    i_deg = math.degrees(math.acos(_clamp_one(h_vec[2] / h)))
    raan_deg = _atan2_deg(n_vec[1], n_vec[0]) if n > 1e-9 else 0.0

    if n > 1e-9 and e > 1e-9:
        cos_argp = _vec_dot(n_vec, e_vec) / (n * e)
        sin_argp = _vec_dot(_vec_cross(n_vec, e_vec), h_vec) / (n * e * h)
        argp_deg = _atan2_deg(sin_argp, cos_argp)
    elif n <= 1e-9 and e > 1e-9:
        argp_deg = _atan2_deg(e_vec[1], e_vec[0])
    else:
        argp_deg = 0.0

    if e > 1e-9:
        cos_nu = _vec_dot(e_vec, r_vec) / (e * r)
        sin_nu = _vec_dot(_vec_cross(e_vec, r_vec), h_vec) / (e * r * h)
        nu_deg = _atan2_deg(sin_nu, cos_nu)
    elif n > 1e-9:
        cos_nu = _vec_dot(n_vec, r_vec) / (n * r)
        sin_nu = _vec_dot(_vec_cross(n_vec, r_vec), h_vec) / (n * r * h)
        nu_deg = _atan2_deg(sin_nu, cos_nu)
    else:
        nu_deg = _atan2_deg(r_vec[1], r_vec[0])

    nu = math.radians(nu_deg)
    ecc_anomaly = 2.0 * math.atan2(
        math.sqrt(1.0 - e) * math.sin(nu / 2.0),
        math.sqrt(1.0 + e) * math.cos(nu / 2.0),
    )
    mean_anomaly = (ecc_anomaly - e * math.sin(ecc_anomaly)) % (2.0 * math.pi)
    period_min = 2.0 * math.pi * math.sqrt(a * a * a / mu) / 60.0

    return {
        "a_km": a,
        "e": e,
        "i_deg": i_deg,
        "raan_deg": raan_deg,
        "argp_deg": argp_deg,
        "m_deg": math.degrees(mean_anomaly),
        "nu_deg": nu_deg,
        "period_min": period_min,
        "r_norm_km": r,
        "v_norm_km_s": v,
    }


def elements_to_j2000_rv(body: Dict[str, Any]) -> Dict[str, Any]:
    """Convert classical elements to J2000 position/velocity (km, km/s)."""
    mu = _orbit_number(body, "mu", "μ", 1e-6, 1e18, 398600.4418)
    a = _orbit_number(body, "a_km", "a_km", 1e-6, 1e12)
    e = _orbit_number(body, "e", "e", 0.0, 0.999999999)
    i_deg = _orbit_number(body, "i_deg", "i_deg", 0.0, 180.0)
    raan_deg = _orbit_number(body, "raan_deg", "raan_deg", 0.0, 360.0)
    argp_deg = _orbit_number(body, "argp_deg", "argp_deg", 0.0, 360.0)
    m_deg = _orbit_number(body, "m_deg", "m_deg", 0.0, 360.0)

    mean_anomaly = math.radians(m_deg)
    ecc_anomaly = mean_anomaly
    for _ in range(100):
        residual = ecc_anomaly - e * math.sin(ecc_anomaly) - mean_anomaly
        ecc_anomaly -= residual / (1.0 - e * math.cos(ecc_anomaly))
        if abs(residual) < 1e-12:
            break

    cos_e = math.cos(ecc_anomaly)
    sin_e = math.sin(ecc_anomaly)
    r_pf_norm = a * (1.0 - e * cos_e)
    r_pf = [a * (cos_e - e), a * math.sqrt(1.0 - e * e) * sin_e, 0.0]
    factor = math.sqrt(mu * a) / r_pf_norm
    v_pf = [
        -factor * sin_e,
        factor * math.sqrt(1.0 - e * e) * cos_e,
        0.0,
    ]

    cos_w, sin_w = math.cos(math.radians(argp_deg)), math.sin(math.radians(argp_deg))
    cos_o, sin_o = math.cos(math.radians(raan_deg)), math.sin(math.radians(raan_deg))
    cos_i, sin_i = math.cos(math.radians(i_deg)), math.sin(math.radians(i_deg))
    rotation = [
        [
            cos_o * cos_w - sin_o * sin_w * cos_i,
            -cos_o * sin_w - sin_o * cos_w * cos_i,
            sin_o * sin_i,
        ],
        [
            sin_o * cos_w + cos_o * sin_w * cos_i,
            -sin_o * sin_w + cos_o * cos_w * cos_i,
            -cos_o * sin_i,
        ],
        [sin_w * sin_i, cos_w * sin_i, cos_i],
    ]
    r_vec = [sum(rotation[row][col] * r_pf[col] for col in range(3)) for row in range(3)]
    v_vec = [sum(rotation[row][col] * v_pf[col] for col in range(3)) for row in range(3)]

    return {
        "r_km": r_vec,
        "v_km_s": v_vec,
        "r_norm_km": _vec_norm(r_vec),
        "v_norm_km_s": _vec_norm(v_vec),
    }


def orbit_convert(body: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(body.get("mode", ""))
    if mode == "rv2el":
        return {"mode": "rv2el", "elements": rv_to_j2000_elements(body)}
    if mode == "el2rv":
        return {"mode": "el2rv", **elements_to_j2000_rv(body)}
    raise ApiError(400, "mode 必须是 rv2el 或 el2rv")


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

    def handle_error(self, request, client_address) -> None:  # type: ignore[no-untyped-def]
        exc_type, _exc_value, _exc_tb = sys.exc_info()
        if exc_type is not None and issubclass(exc_type, QUIET_CONNECTION_ERRORS):
            return
        super().handle_error(request, client_address)


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
        except QUIET_CONNECTION_ERRORS:
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
            if path == "/api/norad/saved":
                ids = read_saved_norad_ids()
                self.send_json(
                    200,
                    {
                        "ok": True,
                        **saved_norad_response({"norad_ids": ids, "count": len(ids)}),
                    },
                )
                return
            if path == "/api/f107":
                query = urllib.parse.parse_qs(parsed.query)
                force = query.get("refresh", ["0"])[0].lower() in ("1", "true", "yes")
                data = fetch_f107(force=force)
                self.send_json(200, {"ok": True, **data})
                return
            if path == "/api/celestrak/recent-launches":
                query = urllib.parse.parse_qs(parsed.query)
                force = query.get("refresh", ["0"])[0].lower() in ("1", "true", "yes")
                self.send_json(200, {"ok": True, **fetch_recent_launches(force=force)})
                return
            match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_.-]+)/file", path)
            if match:
                query = urllib.parse.parse_qs(parsed.query)
                name = query.get("name", [""])[0]
                target = safe_download(match.group(1), name)
                self.send_download(target, name)
                return
            self.send_static(path)
        except QUIET_CONNECTION_ERRORS:
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
            if path == "/api/orbit/convert":
                self.send_json(200, {"ok": True, "result": orbit_convert(body)})
                return
            if path == "/api/sgp4":
                self.send_json(200, run_sgp4(body))
                return
            if path == "/api/celestrak":
                self.send_json(200, fetch_celestrak_batch(body))
                return
            if path == "/api/norad/saved":
                self.send_json(
                    200,
                    {
                        "ok": True,
                        **saved_norad_response(save_norad_ids(body.get("norad_ids", ""))),
                    },
                )
                return
            if path == "/api/norad/saved/delete":
                self.send_json(
                    200,
                    {
                        "ok": True,
                        **saved_norad_response(delete_saved_norad_id(body.get("norad_id", ""))),
                    },
                )
                return
            match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_.-]+)/stop", path)
            if match:
                self.send_json(200, self.manager.stop(match.group(1)))
                return
            raise ApiError(404, "接口不存在")
        except QUIET_CONNECTION_ERRORS:
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
        except QUIET_CONNECTION_ERRORS:
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
        except QUIET_CONNECTION_ERRORS:
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

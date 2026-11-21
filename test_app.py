import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class CsvExportTest(unittest.TestCase):
    def test_export_columns_scale_and_precision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "sim_data.csv"
            raw.write_text(
                "time_s,roll_deg,pitch_deg,yaw_deg,task_flow\n"
                "0.5,-10.0,2.0,3.0,6\n"
                "1.0,-9.5,2.5,3.5,7\n",
                encoding="utf-8",
            )
            profile = {
                "name": "test",
                "delimiter": ";",
                "columns": [
                    {"name": "t", "source": "time_s", "precision": 1},
                    {"name": "roll_x10", "source": "roll_deg", "scale": 10, "precision": 0},
                    {"name": "flow", "source": "task_flow"},
                ],
            }
            output = root / "telemetry.csv"
            result = app.export_csv(raw, profile, output)
            self.assertEqual(result["row_count"], 2)
            self.assertEqual(result["columns"], ["t", "roll_x10", "flow"])
            with open(output, newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle, delimiter=";"))
            self.assertEqual(rows[0], ["t", "roll_x10", "flow"])
            self.assertEqual(rows[1], ["0.5", "-100", "6"])
            self.assertEqual(rows[2], ["1.0", "-95", "7"])
            self.assertFalse((root / "telemetry.csv.tmp").exists())

    def test_missing_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "sim_data.csv"
            raw.write_text("time_s,roll_deg\n0.1,1.0\n", encoding="utf-8")
            profile = {
                "name": "bad",
                "columns": [{"name": "x", "source": "missing"}],
            }
            with self.assertRaises(ValueError):
                app.export_csv(raw, profile, root / "out.csv")


class PreviewCsvTest(unittest.TestCase):
    def test_preview_is_downsampled_and_keeps_full_range(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "data.csv"
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["time_s", "value"])
                for index in range(1001):
                    writer.writerow([index, index * 2])
            preview = app.preview_csv(path, table_limit=5, chart_limit=100)
            self.assertEqual(preview["columns"], ["time_s", "value"])
            self.assertEqual(len(preview["rows"]), 5)
            self.assertEqual(preview["row_count"], 1001)
            self.assertEqual(preview["chart_rows"][0][0], "0")
            self.assertEqual(preview["chart_rows"][-1][0], "1000")
            self.assertLessEqual(len(preview["chart_rows"]), 200)
            self.assertFalse(preview["truncated"])

    def test_preview_scan_limit_marks_truncated(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "data.csv"
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["time_s", "value"])
                for index in range(100):
                    writer.writerow([index, index])
            preview = app.preview_csv(path, table_limit=5, chart_limit=20, scan_limit=10)
            self.assertEqual(preview["row_count"], 10)
            self.assertTrue(preview["truncated"])
            self.assertEqual(preview["chart_rows"][-1][0], "9")


class ValidationTest(unittest.TestCase):
    def test_norad_ids(self):
        self.assertEqual(app.normalize_norad_ids("25544, 48274"), [25544, 48274])
        self.assertEqual(app.normalize_norad_ids(["25544", "48274"]), [25544, 48274])
        ten = ",".join(str(index) for index in range(1, 11))
        self.assertEqual(len(app.normalize_norad_ids(ten)), 10)
        with self.assertRaises(app.ApiError):
            app.normalize_norad_ids("not-a-number")
        with self.assertRaises(app.ApiError):
            app.normalize_norad_ids(",".join(str(index) for index in range(1, 12)))

    def test_profiles_exist(self):
        names = {profile["name"] for profile in app.list_profiles()}
        self.assertIn("default", names)
        self.assertIn("attitude_only", names)

    def test_eop_status_is_available(self):
        status = app.eop_status()
        self.assertTrue(status["available"])
        self.assertRegex(status["last_date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_safe_job_id(self):
        self.assertRaises(app.ApiError, app.safe_job_dir, "../escape")

    def test_parse_limit(self):
        self.assertEqual(app.parse_limit({}), 20)
        self.assertEqual(app.parse_limit({"limit": ["500"]}), 200)
        self.assertEqual(app.parse_limit({"limit": ["0"]}), 1)
        with self.assertRaises(app.ApiError):
            app.parse_limit({"limit": ["abc"]})

    def test_host_and_origin_checks(self):
        allowed = {"127.0.0.1", "localhost"}
        self.assertTrue(app.host_allowed("127.0.0.1:8765", allowed))
        self.assertTrue(app.host_allowed("localhost:8765", allowed))
        self.assertFalse(app.host_allowed("evil.example", allowed))
        self.assertTrue(app.origin_allowed("http://127.0.0.1:8765", allowed))
        self.assertFalse(app.origin_allowed("https://evil.example", allowed))
        self.assertFalse(app.origin_allowed("null", allowed))

    def test_json_content_type_is_required(self):
        body = b'{"ok": true}'

        class FakeHandler:
            headers = {
                "Content-Type": "text/plain",
                "Content-Length": str(len(body)),
            }
            rfile = io.BytesIO(body)

        with self.assertRaises(app.ApiError):
            app.read_json_body(FakeHandler())

        class JsonHandler(FakeHandler):
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(body)),
            }
            rfile = io.BytesIO(body)

        self.assertEqual(app.read_json_body(JsonHandler()), {"ok": True})


class StaticMimeTypeTest(unittest.TestCase):
    def test_script_and_style_types_are_executable(self):
        self.assertTrue(app.STATIC_MIME_TYPES[".js"].startswith("text/javascript"))
        self.assertTrue(app.STATIC_MIME_TYPES[".css"].startswith("text/css"))
        self.assertEqual(app.STATIC_MIME_TYPES[".html"], "text/html; charset=utf-8")
        self.assertEqual(app.STATIC_MIME_TYPES[".svg"], "image/svg+xml")


class ProfileValidationTest(unittest.TestCase):
    def test_rejects_duplicate_names_and_bad_precision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = {
                "duplicate": {
                    "columns": [
                        {"name": "x", "source": "time_s"},
                        {"name": "x", "source": "roll_deg"},
                    ]
                },
                "precision": {"columns": [{"name": "x", "source": "time_s", "precision": 99}]},
                "delimiter": {
                    "delimiter": '"',
                    "columns": [{"name": "x", "source": "time_s"}],
                },
            }
            for name, payload in cases.items():
                (root / (name + ".json")).write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(app, "profiles_dir", return_value=root):
                for name in cases:
                    with self.assertRaises(app.ApiError):
                        app.load_profile(name)


class ApsSgp4ValidationTest(unittest.TestCase):
    def test_aps_rejects_invalid_calendar_date(self):
        with self.assertRaises(app.ApiError):
            app.run_aps(
                {
                    "mode": "o2m",
                    "epoch": "20261301T000000.0000",
                    "a_km": 7000,
                    "e": 0.001,
                    "i_deg": 98,
                    "raan_deg": 30,
                    "argp_deg": 40,
                    "m_deg": 50,
                }
            )

    def test_aps_rejects_out_of_range_angles(self):
        with self.assertRaises(app.ApiError):
            app.run_aps(
                {
                    "mode": "o2m",
                    "epoch": "20260101T000000.0000",
                    "a_km": 7000,
                    "e": 0.001,
                    "i_deg": 98,
                    "raan_deg": 400,
                    "argp_deg": 40,
                    "m_deg": 50,
                }
            )

    def test_sgp4_rejects_too_many_samples(self):
        with self.assertRaises(app.ApiError):
            app.run_sgp4(
                {
                    "line1": "1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753",
                    "line2": "2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667",
                    "duration_days": 3650,
                    "step_minutes": 2,
                    "sample_minutes": 0.1,
                }
            )


class SavedNoradTest(unittest.TestCase):
    def test_save_and_delete_saved_norad_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "norad_ids.txt"
            with mock.patch.object(app, "SAVED_NORAD_FILE", path):
                first = app.save_norad_ids("25544, 48274, 43013")
                self.assertEqual(first["norad_ids"], [25544, 48274, 43013])
                self.assertEqual(first["added"], 3)
                second = app.save_norad_ids("48274, 43013")
                self.assertEqual(second["added"], 0)
                removed = app.delete_saved_norad_id(48274)
                self.assertEqual(removed["removed"], 1)
                self.assertEqual(removed["norad_ids"], [25544, 43013])
                self.assertEqual(
                    path.read_text(encoding="utf-8").splitlines(),
                    ["25544", "43013"],
                )


class NoradCountryTest(unittest.TestCase):
    @staticmethod
    def gcat_line(satcat, state):
        parts = ["-"] * 40
        parts[0] = "S" + satcat
        parts[1] = satcat
        parts[15] = state
        return "\t".join(parts)

    def setUp(self):
        app.GCAT_LAST_FAILURE["time"] = 0.0

    def test_parse_gcat_states(self):
        text = "\n".join(
            [
                "#JCAT\tSatcat\tName\tState",
                self.gcat_line("65106", "CN"),
                self.gcat_line("25544", "US"),
                self.gcat_line("99999", "-"),
            ]
        )
        self.assertEqual(
            app.parse_gcat_states(text, [65106, 25544, 99999]),
            {"65106": "CN", "25544": "US"},
        )
        self.assertEqual(
            app.parse_gcat_states(text),
            {"65106": "CN", "25544": "US"},
        )

    def test_group_norad_ids_by_country(self):
        groups = app.group_norad_ids_by_country(
            [65106, 25544, 99999, 43013],
            {"65106": "CN", "25544": "US", "43013": "RU"},
        )
        self.assertEqual(groups["china"], [65106])
        self.assertEqual(groups["foreign"], [25544, 43013])
        self.assertEqual(groups["unknown"], [99999])

    def test_saved_norad_response_uses_cached_gcat_states(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "norad_countries.json"
            with (
                mock.patch.object(app, "GCAT_CACHE_FILE", cache),
                mock.patch.object(
                    app,
                    "fetch_gcat_states",
                    return_value={"65106": "CN", "25544": "US"},
                ) as fetch,
            ):
                first = app.saved_norad_response({"norad_ids": [65106, 25544, 99999], "count": 3})
                self.assertEqual(first["groups"]["china"], [65106])
                self.assertEqual(first["groups"]["foreign"], [25544])
                self.assertEqual(first["groups"]["unknown"], [99999])
                self.assertEqual(first["states"], {"65106": "CN", "25544": "US"})
                self.assertEqual(fetch.call_count, 1)
                self.assertTrue(cache.is_file())

                second = app.saved_norad_response({"norad_ids": [65106, 25544, 99999], "count": 3})
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(second["groups"]["unknown"], [99999])

    def test_saved_norad_response_marks_unknown_when_gcat_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "norad_countries.json"
            with (
                mock.patch.object(app, "GCAT_CACHE_FILE", cache),
                mock.patch.object(
                    app,
                    "fetch_gcat_states",
                    side_effect=OSError("offline"),
                ),
            ):
                payload = app.saved_norad_response({"norad_ids": [25544], "count": 1})
                self.assertEqual(payload["groups"]["unknown"], [25544])
                self.assertIn("warning", payload["classification"])
                self.assertFalse(cache.exists())


class F107ParseTest(unittest.TestCase):
    @staticmethod
    def omni_line(year, day_of_year, hour, flux):
        parts = ["0"] * 55
        parts[0] = str(year)
        parts[1] = str(day_of_year)
        parts[2] = str(hour)
        parts[50] = str(flux)
        return " ".join(parts)

    def test_parse_latest_and_half_year_series(self):
        text = "\n".join(
            [
                self.omni_line(2025, 1, 0, 90.0),
                self.omni_line(2026, 152, 0, 120.0),
                self.omni_line(2026, 152, 1, 999.9),
                self.omni_line(2026, 153, 0, 121.5),
                self.omni_line(2026, 154, 0, 999.9),
            ]
        )
        observations = app.parse_omni2_text(text)
        self.assertEqual(len(observations), 3)
        result = app.build_f107_payload(observations)
        self.assertEqual(result["unit"], "sfu")
        self.assertEqual(result["latest"]["date"], "2026-06-02")
        self.assertEqual(result["latest"]["flux"], 121.5)
        self.assertEqual(result["latest"]["last81"], 120.75)
        self.assertEqual(result["range"]["start"], "2026-06-01")
        self.assertEqual(len(result["series"]), 2)

    def test_parse_rejects_empty_observations(self):
        with self.assertRaises(app.ApiError):
            app.build_f107_payload([])


class SafeDownloadTest(unittest.TestCase):
    def test_download_stays_inside_job_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = root / "job1"
            job.mkdir()
            (job / "ok.txt").write_text("ok", encoding="utf-8")
            (root / "secret.txt").write_text("secret", encoding="utf-8")
            with mock.patch.object(app, "RUNS_DIR", root):
                self.assertTrue(app.safe_download("job1", "ok.txt").is_file())
                with self.assertRaises(app.ApiError):
                    app.safe_download("job1", "../secret.txt")


class JobCleanupTest(unittest.TestCase):
    def test_clear_jobs_removes_completed_jobs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("a", "b"):
                job = root / name
                job.mkdir()
                (job / "job.json").write_text(
                    json.dumps({"id": name, "status": "completed"}),
                    encoding="utf-8",
                )
            with mock.patch.object(app, "RUNS_DIR", root):
                manager = app.JobManager()
                result = manager.clear_jobs()
            self.assertEqual(result["removed"], 2)
            self.assertFalse((root / "a").exists())
            self.assertFalse((root / "b").exists())


if __name__ == "__main__":
    unittest.main()

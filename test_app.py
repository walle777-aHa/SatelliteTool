import csv
import io
import json
import math
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


class OrbitConvertTest(unittest.TestCase):
    def test_elements_rv_roundtrip(self):
        body = {
            "mode": "el2rv",
            "a_km": 7000,
            "e": 0.1,
            "i_deg": 98,
            "raan_deg": 30,
            "argp_deg": 40,
            "m_deg": 50,
        }
        rv = app.elements_to_j2000_rv(body)
        back = app.rv_to_j2000_elements(
            {"mode": "rv2el", "r_km": rv["r_km"], "v_km_s": rv["v_km_s"]}
        )
        self.assertAlmostEqual(back["a_km"], 7000, places=6)
        self.assertAlmostEqual(back["e"], 0.1, places=9)
        self.assertAlmostEqual(back["i_deg"], 98, places=6)
        self.assertAlmostEqual(back["raan_deg"], 30, places=6)
        self.assertAlmostEqual(back["argp_deg"], 40, places=6)
        self.assertAlmostEqual(back["m_deg"], 50, places=6)

    def test_circular_equatorial_orbit(self):
        mu = 398600.4418
        speed = math.sqrt(mu / 7000.0)
        elements = app.rv_to_j2000_elements(
            {"mode": "rv2el", "r_km": [7000.0, 0.0, 0.0], "v_km_s": [0.0, speed, 0.0]}
        )
        self.assertAlmostEqual(elements["a_km"], 7000, places=6)
        self.assertLess(elements["e"], 1e-6)
        self.assertLess(elements["i_deg"], 1e-6)

    def test_rv_rejects_hyperbolic(self):
        with self.assertRaises(app.ApiError):
            app.rv_to_j2000_elements({"mode": "rv2el", "r_km": [7000, 0, 0], "v_km_s": [0, 20, 0]})

    def test_elements_reject_escape_eccentricity(self):
        with self.assertRaises(app.ApiError):
            app.elements_to_j2000_rv(
                {
                    "mode": "el2rv",
                    "a_km": 7000,
                    "e": 1.5,
                    "i_deg": 98,
                    "raan_deg": 30,
                    "argp_deg": 40,
                    "m_deg": 50,
                }
            )

    def test_elements_reject_bad_vector(self):
        with self.assertRaises(app.ApiError):
            app.rv_to_j2000_elements({"mode": "rv2el", "r_km": [7000, 0], "v_km_s": [0, 1, 0]})


class Rvt18ConvertTest(unittest.TestCase):
    PARAMETERS = [
        7_000_000.0,
        0.01,
        0.9,
        1.0,
        0.5,
        0.3,
        1e-8,
        -1e-7,
        1e-9,
        1e-6,
        -2e-6,
        3e-7,
        -4e-7,
        100.0,
        50.0,
        0.01,
        1e-12,
        100000.0,
    ]

    def test_18_parameters_generate_60_one_minute_rvt_samples(self):
        result = app.convert_rvt18(
            {
                "mode": "eph2rvt",
                "parameters": self.PARAMETERS,
                "bdt_week": 974,
                "units": "km",
            }
        )
        self.assertEqual(result["count"], 60)
        self.assertEqual(result["samples"][0]["t_s"], 0)
        self.assertEqual(result["samples"][-1]["t_s"], 3540)
        self.assertAlmostEqual(
            result["samples"][0]["r"][0] * 1000,
            -22823.7168795,
            places=4,
        )
        self.assertEqual(result["units"], "km")

    def test_rvt_to_18_roundtrip_fit(self):
        generated = app.convert_rvt18(
            {
                "mode": "eph2rvt",
                "parameters": self.PARAMETERS,
                "bdt_week": 974,
                "units": "m",
            }
        )
        fit = app.convert_rvt18(
            {
                "mode": "rvt2eph",
                "rvt": [[*sample["r"], *sample["v"]] for sample in generated["samples"]],
                "start_utc": "2024-09-01T03:00:00Z",
                "units": "m",
            }
        )
        self.assertEqual(fit["bdt_week"], 974)
        self.assertTrue(fit["converged"])
        self.assertLess(fit["fit_error_rms_m"], 1e-4)
        for index in range(17):
            self.assertAlmostEqual(fit["parameters"][index], self.PARAMETERS[index], places=7)
        self.assertAlmostEqual(fit["parameters"][17], 10804.0, places=6)

    def test_rejects_not_60_rvt_groups(self):
        with self.assertRaises(app.ApiError) as error:
            app.convert_rvt18(
                {
                    "mode": "rvt2eph",
                    "rvt": [[1, 2, 3, 4, 5, 6]] * 59,
                    "start_utc": "2024-09-01T03:00:00Z",
                    "units": "m",
                }
            )
        self.assertEqual(error.exception.status, 400)

    def test_rejects_non_minute_time_column(self):
        with self.assertRaises(app.ApiError) as error:
            app.convert_rvt18(
                {
                    "mode": "rvt2eph",
                    "rvt": [[7_000_000, 0, 0, 0, 7_500, 0]] * 60,
                    "rvt_times_s": [index * 30 for index in range(60)],
                    "start_utc": "2024-09-01T03:00:00Z",
                    "units": "m",
                }
            )
        self.assertEqual(error.exception.status, 400)

    def test_rejects_invalid_18_parameter_toe(self):
        values = self.PARAMETERS[:]
        values[17] = 604800
        with self.assertRaises(app.ApiError):
            app.convert_rvt18({"mode": "eph2rvt", "parameters": values, "bdt_week": 974})


class SpacecraftModelTest(unittest.TestCase):
    @staticmethod
    def minimal_config():
        return {
            "DynInfo": {"SateName": "test_sat", "SeriesName": "T", "SateMessage": ""},
            "SatModule": {
                "Mass": 100.0,
                "ModuleExpandFlag": [True, False],
                "ModuleExpandFlagName": ["+YSADA", "-YSADA"],
                "MassPro": {
                    "SatBody": {
                        "NodeName": "卫星本体",
                        "ID": 1,
                        "ExpandMass": 90.0,
                        "ExpandMassCenter": [0, 0, 0],
                    },
                    "ChildPartLst": [
                        {
                            "NodeName": "+Y太阳翼",
                            "ID": 3,
                            "ParentID": 1,
                            "ModuleFlagIdx": 0,
                            "Expand": {
                                "Mass": 5.0,
                                "MassCenter": [2.0, 0, 0],
                                "ConnectPoint": [1.5, 0, 0],
                                "RotateDcm": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                            },
                            "Collapse": {
                                "Mass": 0,
                                "MassCenter": [0, 0, 0],
                                "ConnectPoint": [0, 0, 0],
                                "RotateDcm": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                            },
                        },
                        {
                            "NodeName": "-Y太阳翼",
                            "ID": 5,
                            "ParentID": 1,
                            "ModuleFlagIdx": 1,
                            "Expand": {
                                "Mass": 5.0,
                                "MassCenter": [2.0, 0, 0],
                                "ConnectPoint": [1.5, 0, 0],
                                "RotateDcm": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                            },
                            "Collapse": {
                                "Mass": 0,
                                "MassCenter": [0, 0, 0],
                                "ConnectPoint": [0, 0, 0],
                                "RotateDcm": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                            },
                        },
                    ],
                },
            },
            "Engine": [{"InstallPointM": [-1.5, 0, 0.4], "EngineDirectionM": [1, 0, 0]}],
            "Gnss": [{"PosVetB": [0, 0, -1]}],
            "Wheel": [{"PosVetB": [0.6, 0.3, -0.6]}],
            "Star": [{"PosQbs": [1, 0, 0, 0]}],
        }

    def test_derive_respects_expand_flags(self):
        model = app.derive_spacecraft_model(self.minimal_config(), "test_sat")
        kinds = [node["kind"] for node in model["nodes"]]
        self.assertEqual(kinds, ["body", "sunwing", "star-base", "star-cone", "engine", "wheel"])
        wing = model["nodes"][1]
        self.assertEqual(wing["name"], "+Y太阳翼")
        self.assertEqual(wing["size"], [4.3, 2.1, 0.06])
        self.assertEqual(wing["color"], "#2f6fb0")
        self.assertEqual(wing["position"], [3.65, 0.0, 0.0])
        self.assertEqual(wing["mass_center"], [2.0, 0.0, 0.0])

    def test_derive_gizmo_shapes(self):
        model = app.derive_spacecraft_model(self.minimal_config(), "test_sat")
        by_kind = {node["kind"]: node for node in model["nodes"]}
        engine = by_kind["engine"]
        self.assertEqual(engine["size"], [0.35, 0.35, 0.35])
        self.assertAlmostEqual(engine["position"][0], -1.025, places=9)
        self.assertEqual(engine["position"][1:], [0.0, 0.4])
        wheel = by_kind["wheel"]
        self.assertEqual(wheel["shape"], "cylinder")
        self.assertEqual(wheel["radius"], 0.16)
        self.assertEqual(wheel["position"][2], -0.54)
        star = by_kind["star-base"]
        self.assertEqual(star["position"], [0.0, 0.0, 0.6])
        cone = by_kind["star-cone"]
        self.assertEqual(cone["shape"], "cone")
        self.assertEqual(cone["parent"], star["id"])
        body = by_kind["body"]
        self.assertEqual(body["opacity"], 0.55)

    def test_derive_expand_override(self):
        config = self.minimal_config()
        expanded = app.derive_spacecraft_model(config, "test_sat", expand=True)
        self.assertEqual(sum(1 for node in expanded["nodes"] if node["kind"] == "sunwing"), 2)
        collapsed = app.derive_spacecraft_model(config, "test_sat", expand=False)
        self.assertEqual(sum(1 for node in collapsed["nodes"] if node["kind"] == "sunwing"), 0)

    def test_derive_link_connects_wing(self):
        config = {
            "SatModule": {
                "MassPro": {
                    "SatBody": {"NodeName": "卫星本体", "ID": 1, "ExpandMass": 100.0},
                    "ChildPartLst": [
                        {
                            "NodeName": "+Y连杆",
                            "ID": 2,
                            "ParentID": 1,
                            "ModuleFlagIdx": -1,
                            "Expand": {
                                "Mass": 4.8,
                                "MassCenter": [1.25, 0, 0],
                                "ConnectPoint": [-0.141, 0.479105, 0.408081],
                                "RotateDcm": [[0, 1, 0], [1, 0, 0], [0, 0, -1]],
                            },
                        },
                        {
                            "NodeName": "+Y太阳翼",
                            "ID": 3,
                            "ParentID": 2,
                            "ModuleFlagIdx": -1,
                            "Expand": {
                                "Mass": 34.0,
                                "MassCenter": [2.216, 0, 0.016],
                                "ConnectPoint": [1.7749, 0, -0.01344],
                                "RotateDcm": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                            },
                        },
                    ],
                }
            }
        }
        model = app.derive_spacecraft_model(config, "link_test")
        link = next(node for node in model["nodes"] if node["kind"] == "link")
        wing = next(node for node in model["nodes"] if node["kind"] == "sunwing")
        self.assertAlmostEqual(link["size"][0], 1.924947, places=6)
        self.assertEqual(link["color"], "#5c6670")
        self.assertAlmostEqual(link["position"][1], 1.441555, places=9)
        self.assertEqual(wing["parent"], 2)
        self.assertAlmostEqual(wing["position"][0], 3.9249, places=9)

    def test_derive_empty_config_is_graceful(self):
        model = app.derive_spacecraft_model({}, "empty")
        self.assertEqual(len(model["nodes"]), 1)
        self.assertEqual(model["nodes"][0]["kind"], "body")
        self.assertEqual(model["info"][0], {"label": "卫星名称", "value": "-"})

    def test_spacecraft_config_path_validation(self):
        path = app.spacecraft_config_path("star_001")
        self.assertEqual(path.name, "star_001.json")
        with self.assertRaises(app.ApiError) as bad:
            app.spacecraft_config_path("../secret")
        self.assertEqual(bad.exception.status, 400)
        with self.assertRaises(app.ApiError) as missing:
            app.spacecraft_config_path("no_such_satellite")
        self.assertEqual(missing.exception.status, 404)

    def test_starlink_v3_concept_has_dual_wings_and_disclosure(self):
        model = app.derive_starlink_v3_model()
        wings = [node for node in model["nodes"] if node["kind"] == "solar-array"]
        self.assertEqual(len(wings), 2)
        self.assertEqual({node["name"] for node in wings}, {"+Y 太阳翼", "-Y 太阳翼"})
        self.assertAlmostEqual(wings[0]["size"][1], 19.0)
        self.assertAlmostEqual(wings[1]["size"][1], 19.0)
        self.assertIsNone(model["mass_kg"])
        self.assertIn("未公开", " ".join(item["value"] for item in model["info"]))
        self.assertTrue(any(node["kind"] == "phased-array" for node in model["nodes"]))
        self.assertEqual(sum(node["kind"] == "optical-terminal" for node in model["nodes"]), 6)
        self.assertEqual(sum(node["kind"] == "rf-backhaul" for node in model["nodes"]), 4)
        self.assertIn("starlink.com", model["source"])

    def test_starlink_v3_expand_override_only_changes_wings(self):
        expanded = app.derive_starlink_v3_model(True)
        folded = app.derive_starlink_v3_model(False)
        expanded_wings = [n for n in expanded["nodes"] if n["kind"] == "solar-array"]
        folded_wings = [n for n in folded["nodes"] if n["kind"] == "solar-array"]
        self.assertEqual([n["size"][1] for n in expanded_wings], [19.0, 19.0])
        self.assertEqual([n["size"][1] for n in folded_wings], [2.8, 2.8])
        self.assertEqual(
            [n["kind"] for n in expanded["nodes"]],
            [n["kind"] for n in folded["nodes"]],
        )


class RecentLaunchParseTest(unittest.TestCase):
    @staticmethod
    def record(name, norad_id, object_id, launch_date, object_type="PAY", decay_date=""):
        return {
            "OBJECT_NAME": name,
            "NORAD_CAT_ID": norad_id,
            "OBJECT_ID": object_id,
            "OBJECT_TYPE": object_type,
            "OWNER": "PRC",
            "LAUNCH_DATE": launch_date,
            "LAUNCH_SITE": "TAISC",
            "DECAY_DATE": decay_date,
        }

    def test_selects_payloads_from_latest_launch_day(self):
        records = [
            self.record("OLD SAT", 10001, "2026-250A", "2026-11-10"),
            self.record("ROCKET BODY", 101416, "2026-259B", "2026-11-18", "R/B"),
            self.record("NEW SAT B", 101416, "2026-259B", "2026-11-18"),
            self.record("NEW SAT A", 62609, "2026-259A", "2026-11-18"),
            self.record("DEBRIS", 101417, "2026-259C", "2026-11-18", "DEB"),
        ]
        result = app.parse_recent_launches(records)
        self.assertEqual(result["launch_date"], "2026-11-18")
        self.assertEqual(result["count"], 2)
        self.assertEqual(
            [item["object_id"] for item in result["objects"]],
            ["2026-259A", "2026-259B"],
        )
        self.assertTrue(result["objects"][0]["tle_available"])
        self.assertFalse(result["objects"][1]["tle_available"])
        self.assertTrue(result["objects"][0]["in_orbit"])

    def test_ignores_non_payloads_and_invalid_dates(self):
        result = app.parse_recent_launches(
            [
                self.record("ROCKET BODY", 10001, "2026-259B", "2026-11-18", "R/B"),
                self.record("BAD DATE", 10002, "2026-259C", "2026/11/18"),
                {"OBJECT_TYPE": "PAY", "LAUNCH_DATE": "2026-11-18"},
            ]
        )
        self.assertEqual(result, {"launch_date": "", "count": 0, "objects": []})

    def test_rejects_non_list_payload(self):
        with self.assertRaises(ValueError):
            app.parse_recent_launches({"results": []})


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

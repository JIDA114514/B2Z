import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiment_tools.manage import legacy_plan
from experiment_tools.manage import rebuild_reports
from experiment_tools.reporting import PROJECT, rebuild_index, ratio_text, receiver_markdown, write_receiver_reports


class ReportingTests(unittest.TestCase):
    def test_parallel_receiver_reports_keep_index_and_history(self):
        import experiment_tools.reporting as reporting

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root / "old_run"
            current = root / "new_run"
            for directory in (old, current):
                directory.mkdir()
                (directory / "experiment.config.json").write_text("{}")
            (old / "report.md").write_text("preserve this report\n")

            def receive(role):
                prefix = current / "captures" / role / "rx"
                paths = {key: Path(str(prefix) + suffix) for key, suffix in (
                    ("summary", ".summary.json"), ("report", ".report.md"),
                    ("text", ".summary.txt"))}
                summary = {"schema": "exadv_rx_v3" if role == "ble" else "zigbee_rx_v1",
                           "status": "complete", "config": {"run_id": 8},
                           "counts": {"packets": 1, "fcs_valid_packets": 1}}
                write_receiver_reports(summary, paths, current)

            with patch.object(reporting, "EXPERIMENTS", root):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(receive, ("ble", "zigbee")))
            self.assertEqual((old / "report.md").read_text(), "preserve this report\n")
            with (root / "index.csv").open() as handle:
                rows = {row["experiment_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual(rows["new_run"]["receiver_records"], "2")
            self.assertEqual(rows["new_run"]["live_records"], "2")

    def test_explicit_output_outside_archive_does_not_create_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / "custom" / "rx"
            paths = {key: Path(str(prefix) + suffix) for key, suffix in (
                ("summary", ".summary.json"), ("report", ".report.md"),
                ("text", ".summary.txt"))}
            write_receiver_reports({"schema": "exadv_rx_v3", "status": "complete",
                                    "config": {"run_id": 9}, "counts": {"packets": 0}}, paths)
            self.assertTrue(paths["report"].exists())
            self.assertFalse((Path(temporary) / "index.csv").exists())

    def test_index_is_read_only_for_every_registered_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "old_run"
            session.mkdir()
            (session / "experiment.config.json").write_text("{}")
            (session / "notes.md").write_text("human notes\n")
            (session / "report.md").write_text("original report\n")
            (session / "rx.summary.json").write_text(json.dumps({
                "schema": "zigbee_rx_v1", "status": "complete", "config": {"run_id": 5},
                "counts": {"fcs_valid_packets": 2}}))
            before = {str(p.relative_to(session)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in session.rglob("*") if p.is_file()}
            self.assertEqual(rebuild_index(root), (1, 1))
            after = {str(p.relative_to(session)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in session.rglob("*") if p.is_file()}
            self.assertEqual(after, before)
            self.assertTrue((root / "index.csv").exists())

    def test_explicit_rebuild_previews_and_only_writes_named_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("first", "second"):
                session = root / name
                session.mkdir()
                (session / "experiment.config.json").write_text("{}")
                (session / "report.md").write_text("old report\n")
            with self.assertRaisesRegex(ValueError, "requires at least one"):
                rebuild_reports([], root=root)
            with self.assertRaisesRegex(ValueError, "one experiment directory"):
                rebuild_reports(["../first"], root=root)
            self.assertIsNone(rebuild_reports(["first"], root=root))
            self.assertEqual((root / "first/report.md").read_text(), "old report\n")
            self.assertFalse((root / "report_rebuilds").exists())
            log = rebuild_reports(["first"], apply=True, root=root)
            self.assertTrue(log.exists())
            self.assertEqual((root / "second/report.md").read_text(), "old report\n")
            self.assertIn("# 实验：first", (root / "first/report.md").read_text())
            record = json.loads(log.read_text())
            self.assertEqual(record["sessions"], ["first"])
            self.assertNotEqual(record["before_sha256"]["first/report.md"],
                                record["after_sha256"]["first/report.md"])

    def test_new_receiver_does_not_modify_historical_session(self):
        """A real receiver report call may update only its session and root indexes."""
        import experiment_tools.reporting as reporting

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            historical = root / "old_run"
            current = root / "new_run"
            historical.mkdir()
            current.mkdir()
            (historical / "experiment.config.json").write_text("{}")
            (current / "experiment.config.json").write_text("{}")
            (historical / "report.md").write_text("Historical report preserved\n")
            (historical / "notes.md").write_text("Manual observations\n")
            (historical / "captures").mkdir()
            (historical / "captures" / "rx.summary.json").write_text(json.dumps({
                "schema": "exadv_rx_v3", "status": "complete", "config": {"run_id": 7},
                "counts": {"packets": 1}}))

            def inventory():
                return {str(path.relative_to(historical)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in historical.rglob("*") if path.is_file()}

            before = inventory()
            prefix = current / "captures" / "ble" / "rx"
            paths = {key: Path(str(prefix) + suffix) for key, suffix in (
                ("summary", ".summary.json"), ("report", ".report.md"), ("text", ".summary.txt"))}
            summary = {"schema": "exadv_rx_v3", "status": "complete",
                       "config": {"run_id": 8}, "counts": {"packets": 1}}
            with patch.object(reporting, "EXPERIMENTS", root):
                write_receiver_reports(summary, paths, current)
            self.assertEqual(inventory(), before)
            self.assertTrue((root / "index.csv").exists())
            self.assertTrue((current / "report.md").exists())

    def test_control_receiver_markdown_renders_after_capture(self):
        summary = {"schema": "zigbee_control_rx_v1", "status": "complete",
                   "config": {"run_id": 1007, "command_id": 43},
                   "counts": {"fcs_valid_packets": 43, "control_candidates": 43,
                              "valid_control_records": 43},
                   "receiver": {"unique": 43, "duplicate": 0, "out_of_order": 0}}
        report = receiver_markdown(summary, Path("rx.summary.json"))
        self.assertIn("有效唯一时隙：43", report)
        self.assertIn("当前报告描述解码与负载校验", report)

    def test_short_live_commands_use_distinct_devices_and_keep_every_attempt(self):
        # Exercise the actual receiver CLIs/capture processes with a fake SDR
        # executable. No connected radio or central experiment data is touched.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "hackrf_transfer"
            executable.write_text("#!/usr/bin/env python3\nimport sys\nsys.stdout.buffer.write(bytes(16384))\n")
            executable.chmod(0o755)
            environment = dict(os.environ, PATH=str(root) + os.pathsep + os.environ.get("PATH", ""))
            archive = root / "experiments"
            bootstrap = (
                "import sys,runpy;from pathlib import Path;"
                f"sys.path.insert(0,{str(PROJECT / 'python')!r});"
                "import experiment_tools.reporting as r;"
                f"r.EXPERIMENTS=Path({str(archive)!r});"
                "script=sys.argv.pop(1);sys.path.insert(0,str(Path(script).parent));"
                "runpy.run_path(script,run_name='__main__')"
            )
            for family in ("exadv_rx", "zigbee_rx", "exadv_rx"):
                command = [sys.executable, "-c", bootstrap, str(PROJECT / "python" / family / "receive.py"), "--run-id", "71", "--duration", "0"]
                result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
            sessions = list(archive.glob("????????_run71"))
            self.assertEqual(len(sessions), 1)
            session = sessions[0]
            records = list(session.rglob("*.summary.json"))
            self.assertEqual(len(records), 3)
            self.assertEqual(len(list((session / "captures/ble").glob("*/rx.ci8"))), 2)
            self.assertEqual(len(list((session / "captures/zigbee").glob("*/rx.ci8"))), 1)
            serials = {}
            for path in records:
                value = json.loads(path.read_text())
                config = value["config"]
                role = "ble" if value["schema"].startswith("exadv") else "zigbee"
                serials[role] = config["serial"]
                self.assertEqual(config["run_id"], 71)
                self.assertEqual(config["duration"], 0)
                self.assertEqual(config["sample_rate"], 8000000)
                self.assertTrue(config["save_iq"])
                self.assertTrue(config["quiet"])
                if role == "zigbee":
                    self.assertEqual((config["demod"], config["symbol_order"], config["cutoff_hz"]), ("phase", "project", 700000))
                    self.assertIsNone(config["payload_len"])
                    self.assertIsNone(config["expected_packets"])
            self.assertNotEqual(serials["ble"], serials["zigbee"])
            with (archive / "index.csv").open() as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["run_ids"], "71")
            self.assertEqual(row["live_records"], "3")

    def test_independent_cli_replays_share_session_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            iq = root / "noise.ci8"
            iq.write_bytes(bytes(16384))
            session = root / "experiments" / "shared"
            processes = []
            for receiver in ("exadv_rx", "zigbee_rx"):
                command = [sys.executable, str(PROJECT / "python" / receiver / "receive.py"),
                           "--iq-file", str(iq), "--duration", "0", "--quiet",
                           "--experiment-dir", str(session), "--analysis-id", "comparison"]
                processes.append((command, subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))
            for command, process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, (stdout, stderr))
                self.assertNotIn("0/None", stdout)
                # A repeated invocation must refuse to overwrite its original record.
                repeated = subprocess.run(command, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(repeated.returncode, 0)
            originals = {}
            for role in ("ble", "zigbee"):
                path = session / "analyses/comparison" / role / "rx.summary.json"
                originals[path] = hashlib.sha256(path.read_bytes()).hexdigest()
                value = json.loads(path.read_text())
                self.assertFalse(value["config"]["save_iq"])
                self.assertIsNone(value["config"]["serial"])
                self.assertFalse(path.with_name("rx.ci8").exists())
            self.assertIn("replay", (session / "report.md").read_text())
            self.assertEqual(rebuild_index(session.parent), (1, 2))
            for path, digest in originals.items():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            with (session.parent / "index.csv").open() as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["live_records"], "0")
            self.assertEqual(row["replay_records"], "2")
            with (session.parent / "runs.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual({r["valid_packets"] for r in rows}, {"0"})
            self.assertTrue(all(r["wireless_prr"].startswith("N/A") for r in rows))

    def test_migration_groups_only_explicit_iq_ancestry(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            ble = project / "python/exadv_rx/results"
            zigbee = project / "python/zigbee_rx/results"
            ble.mkdir(parents=True)
            zigbee.mkdir(parents=True)
            (ble / "capture.summary.json").write_text(json.dumps({"schema": "exadv_rx_v3", "config": {}}))
            (ble / "capture.ci8").write_bytes(bytes(4))
            (zigbee / "replay.summary.json").write_text(json.dumps({"schema": "zigbee_rx_v1", "run_id": 7,
                "config": {"iq_file": "python/exadv_rx/results/capture.ci8"}}))
            (zigbee / "other_capture.summary.json").write_text(json.dumps({"schema": "zigbee_rx_v1", "run_id": 7, "config": {}}))
            paths, groups = legacy_plan(project)
            self.assertEqual(len(groups), 2)
            replay = paths["python/zigbee_rx/results/replay.summary.json"]["destination"]
            self.assertIn("history_ble_capture/analyses/", replay)
            self.assertNotEqual(replay.split("/analyses")[0], paths["python/zigbee_rx/results/other_capture.summary.json"]["destination"].split("/captures")[0])

    def test_unavailable_and_zero_denominators_are_not_percentages(self):
        for ratio in ({"numerator": 0, "denominator": None, "value": None},
                      {"numerator": 0, "denominator": 0, "value": None}):
            self.assertTrue(ratio_text(ratio).startswith("N/A"))
        self.assertEqual(ratio_text({"numerator": 0, "denominator": 150, "value": 0}), "0/150 = 0.00%")


if __name__ == "__main__":
    unittest.main()

"""Unit tests for UC1 board serial sender and direct-to-disk log capture."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from python.control_match.tests.test_uc1_receive import make_synthetic_uc1_board_log
from python.control_match.uc1_board_send import (
    DEFAULT_BAUDRATE,
    DEFAULT_BYTESIZE,
    DEFAULT_PARITY,
    DEFAULT_PORT,
    DEFAULT_STOPBITS,
    build_parser,
    execute_serial_run,
    resolve_job,
)
from python.control_match.uc1_config import export_commands, generate as generate_uc1_config


class FakeSerial:
    def __init__(self, chunks: list[bytes], *, advance_per_read: float = 0.2):
        self.port = "/dev/ttyUSB1"
        self._chunks = list(chunks)
        self.written = bytearray()
        self.now = 0.0
        self.advance_per_read = advance_per_read
        self.flushed = 0

    @property
    def in_waiting(self) -> int:
        if not self.written:
            return 0
        return len(self._chunks[0]) if self._chunks else 0

    def reset_input_buffer(self) -> None:
        pass

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        self.flushed += 1

    def read(self, size: int = 256) -> bytes:
        self.now += self.advance_per_read
        if not self.written or not self._chunks:
            return b""
        return self._chunks.pop(0)


class UC1BoardSendTests(unittest.TestCase):
    def test_parser_defaults_match_bench_serial_spec(self):
        args = build_parser().parse_args(["--run-id", "2703"])
        self.assertEqual(args.port, DEFAULT_PORT)
        self.assertEqual(args.port, "/dev/ttyUSB1")
        self.assertEqual(args.baudrate, DEFAULT_BAUDRATE)
        self.assertEqual(args.baudrate, 115200)
        self.assertEqual(args.bytesize, DEFAULT_BYTESIZE)
        self.assertEqual(args.bytesize, 8)
        self.assertEqual(args.stopbits, DEFAULT_STOPBITS)
        self.assertEqual(args.stopbits, 1.0)
        self.assertEqual(args.parity, DEFAULT_PARITY)
        self.assertEqual(args.parity, "N")

    def test_resolve_job_from_config_board_txt_and_host_sh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_dir = root / "configs"
            exp_root = root / "experiments"
            cfg_dir.mkdir()
            exp_root.mkdir()

            cfg = generate_uc1_config(
                2719, mode="JC", profile="core", ble_extra=26, ieee_extra=0,
                tasks=30, policy="k", value=1, phase="P3", stage="pilot",
                rf_condition="R1", block=1, provenance=False,
            )
            cfg_path = cfg_dir / "uc1_2719.json"
            board_txt = cfg_dir / "uc1_2719.board.txt"
            host_sh = cfg_dir / "uc1_2719.host.sh"
            exp_dir = exp_root / "20261120_run2719"
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
            cmds = export_commands(cfg, cfg_path, experiment_dir=exp_dir)
            board_txt.write_text(cmds["board_text"])
            host_sh.write_text(
                "\n".join([
                    cmds["ble_rx"],
                    cmds["zigbee_rx"],
                    cmds["board_serial"],
                    cmds["analyze"],
                ]) + "\n"
            )
            self.assertIn("uc1_board_send.py", cmds["board_serial"])

            # 1. Resolve via --run-id alone (finds uc1_2719.json and reads experiment_dir from uc1_2719.host.sh)
            j1 = resolve_job(run_id=2719, configs_dir=cfg_dir, experiments_root=exp_root)
            self.assertEqual(j1["run_id"], 2719)
            self.assertEqual(j1["command"], "b2z_uc1_start? 2719 500 30 26 0 1 0 1 0")
            self.assertEqual(j1["board_duration_s"], 95)
            self.assertEqual(j1["output_path"], exp_dir / "board.board.log")

            # 2. Resolve via --board-commands (.board.txt) when .host.sh is absent but experiment dir exists
            host_sh.unlink()
            exp_dir.mkdir(parents=True)
            j2 = resolve_job(board_commands_path=board_txt, configs_dir=cfg_dir, experiments_root=exp_root)
            self.assertEqual(j2["run_id"], 2719)
            self.assertEqual(j2["command"], "b2z_uc1_start? 2719 500 30 26 0 1 0 1 0")
            self.assertEqual(j2["output_path"], exp_dir / "board.board.log")

    def test_execute_serial_run_streams_verifies_and_protects_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = generate_uc1_config(
                2720, mode="LC", profile="core", ble_extra=26, ieee_extra=0,
                tasks=2, policy="budget", value=6000, provenance=False,
            )
            full_log = (
                "\x00\x00CONTROL_PLAN_START state=armed run_id=2720 period_ms=500 tasks=2 slots=22 duration_s=11\r\r\n"
                + make_synthetic_uc1_board_log(cfg)
                + "\r\r\nCOMPACT_TIME_END run_id=2720 trace=burst_brackets_only\r\r\n"
            )
            raw_bytes = full_log.encode("utf-8")
            # Split into irregular chunks to test line reassembly across UART reads
            chunks = [raw_bytes[i:i + 97] for i in range(0, len(raw_bytes), 97)] + [b"", b"", b""]
            ser = FakeSerial(chunks, advance_per_read=0.2)
            out_log = root / "exp_2720" / "board.board.log"
            job = {
                "run_id": 2720,
                "command": cfg["board_command"],
                "board_duration_s": cfg["board_duration_s"],
                "experiment_dir": out_log.parent,
                "output_path": out_log,
            }
            res = execute_serial_run(
                ser,
                job,
                char_delay_ms=0.5,
                post_end_drain_s=0.3,
                quiet=True,
                clock=lambda: ser.now,
                sleep=lambda dt: setattr(ser, "now", ser.now + dt),
            )
            self.assertEqual(ser.written.decode("ascii"), cfg["board_command"] + "\n")
            self.assertTrue(res["started_armed"])
            self.assertTrue(res["rf_final_seen"])
            self.assertTrue(res["cost_stats_seen"])
            self.assertTrue(res["terminal_end_seen"])
            self.assertEqual(res["verified"]["completed_attempts"], "4")
            self.assertEqual(res["verified"]["ble_tx_completed"], 4)
            self.assertEqual(res["verified"]["ieee_tx_completed"], 4)
            self.assertEqual(res["verified"]["burst_completed"], 24)
            self.assertEqual(out_log.read_bytes(), raw_bytes.replace(b"\x00", b""))

            # Refuses to overwrite existing non-empty board.board.log without overwrite=True
            with self.assertRaises(FileExistsError):
                execute_serial_run(FakeSerial([]), job, quiet=True)

            # Detects board command rejection immediately
            bad_job = dict(job, output_path=root / "exp_bad" / "board.board.log")
            bad_ser = FakeSerial([b"CONTROL_PLAN_ERROR busy\r\n"])
            with self.assertRaisesRegex(RuntimeError, "board rejected command"):
                execute_serial_run(
                    bad_ser,
                    bad_job,
                    quiet=True,
                    clock=lambda: bad_ser.now,
                    sleep=lambda dt: None,
                )

            # Detects start timeout when board never prints CONTROL_PLAN_START
            to_job = dict(job, output_path=root / "exp_to" / "board.board.log")
            to_ser = FakeSerial([b""] * 20, advance_per_read=1.0)
            with self.assertRaisesRegex(TimeoutError, "waiting for CONTROL_PLAN_START"):
                execute_serial_run(
                    to_ser,
                    to_job,
                    start_timeout_s=3.0,
                    quiet=True,
                    clock=lambda: to_ser.now,
                    sleep=lambda dt: None,
                )


if __name__ == "__main__":
    unittest.main()

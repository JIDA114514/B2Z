#!/usr/bin/env python3
"""Send pre-generated UC1 board command over UART and stream board.board.log to disk.

Default serial settings match the ANTSDR/Zynq bench UART:
  port=/dev/ttyUSB1, baudrate=115200, bytesize=8, stopbits=1, parity=N (8N1)

Safety & audit features:
- Resolves command, run_id, expected duration, and <experiment-dir>/board.board.log
  automatically from --run-id, --config (uc1_<id>.json), or --board-commands (uc1_<id>.board.txt).
- Refuses to overwrite an existing non-empty board.board.log unless --overwrite is set.
- Paces UART TX characters (default 1 ms/char, single LF) so Zynq's 64-byte XUartPs
  FIFO and FreeRTOS console polling loop never drop characters or trigger double commands.
- Verifies CONTROL_PLAN_START within --start-timeout-s (default 10 s) and detects
  UC1_ERROR / CONTROL_PLAN_ERROR / Invalid command! immediately.
- Streams every received chunk directly to disk with flush() (zero scrollback truncation),
  waits until the final trace marker (CONTROL_TIME_END or COMPACT_TIME_END) arrives
  after the 115200-baud statistics dump, and validates the saved log with read_plan().
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from plan_analyze import read_plan  # noqa: E402
from uc1_config import load as load_uc1_config  # noqa: E402

DEFAULT_PORT = "/dev/ttyUSB1"
DEFAULT_BAUDRATE = 115200
DEFAULT_BYTESIZE = 8
DEFAULT_STOPBITS = 1.0
DEFAULT_PARITY = "N"

ERROR_PREFIXES = (
    "UC1_ERROR ",
    "CONTROL_PLAN_ERROR ",
    "CAPACITY_ERROR ",
    "Usage: b2z_",
    "Invalid command!",
)


def _parse_board_txt(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    cmd_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(cmd_lines) != 1:
        raise ValueError(f"expected exactly 1 command line in {path}, found {len(cmd_lines)}")
    cmd = cmd_lines[0]
    m_run = re.search(r"\bb2z_uc1_start\?\s+(\d+)\s+(\d+)\s+(\d+)\b", cmd)
    run_id = int(m_run.group(1)) if m_run else None
    m_dur = re.search(r"board_duration_s=(\d+)", text)
    board_duration_s = int(m_dur.group(1)) if m_dur else None
    if board_duration_s is None and m_run:
        period_ms = int(m_run.group(2))
        tasks = int(m_run.group(3))
        parts = cmd.split()
        profile = int(parts[9]) if len(parts) >= 10 else 0
        slots = 300 if profile == 1 else (10 + 6 * tasks)
        board_duration_s = (slots * period_ms + 999) // 1000
    return {
        "run_id": run_id,
        "command": cmd,
        "board_duration_s": board_duration_s or 305,
        "source_path": str(path),
    }


def _extract_exp_dir_from_host_sh(host_sh: Path) -> Path | None:
    if not host_sh.is_file():
        return None
    text = host_sh.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        m = re.search(r"--experiment-dir\s+([^\s]+)", line)
        if m:
            raw = m.group(1).strip("'\"")
            if "<" not in raw and ">" not in raw:
                return Path(raw)
    return None


def resolve_job(
    *,
    run_id: int | None = None,
    config_path: Path | None = None,
    board_commands_path: Path | None = None,
    command: str | None = None,
    experiment_dir: Path | None = None,
    output_path: Path | None = None,
    configs_dir: Path | None = None,
    experiments_root: Path | None = None,
) -> dict[str, Any]:
    """Resolve command, run_id, expected duration, and output board.board.log path."""
    cfg_dir = configs_dir or (HERE / "configs")
    exp_root = experiments_root or (REPO_ROOT / "python" / "experiments")

    resolved_run_id = run_id
    resolved_cmd = command.strip() if command else None
    board_duration_s: int | None = None
    host_sh_candidate: Path | None = None
    source_desc = "cli_command"

    if config_path is None and board_commands_path is None and resolved_cmd is None:
        if resolved_run_id is None:
            raise ValueError("specify one of --run-id, --config, --board-commands, or --command")
        cand_json = cfg_dir / f"uc1_{resolved_run_id}.json"
        cand_txt = cfg_dir / f"uc1_{resolved_run_id}.board.txt"
        if cand_json.is_file():
            config_path = cand_json
        elif cand_txt.is_file():
            board_commands_path = cand_txt
        else:
            raise FileNotFoundError(
                f"neither {cand_json} nor {cand_txt} found for run_id={resolved_run_id}"
            )

    if config_path is not None:
        cfg = load_uc1_config(config_path, run_id=resolved_run_id)
        resolved_run_id = int(cfg["run_id"])
        resolved_cmd = str(cfg["board_command"]).strip()
        board_duration_s = int(cfg["board_duration_s"])
        source_desc = str(config_path)
        host_sh_candidate = config_path.with_suffix(".host.sh")
    elif board_commands_path is not None:
        info = _parse_board_txt(board_commands_path)
        if resolved_run_id is not None and info["run_id"] is not None and resolved_run_id != info["run_id"]:
            raise ValueError(f"--run-id {resolved_run_id} does not match {board_commands_path} ({info['run_id']})")
        resolved_run_id = resolved_run_id or info["run_id"]
        resolved_cmd = info["command"]
        board_duration_s = info["board_duration_s"]
        source_desc = str(board_commands_path)
        name = board_commands_path.name
        if name.endswith(".board.txt"):
            host_sh_candidate = board_commands_path.with_name(name[:-10] + ".host.sh")
    elif resolved_cmd is not None:
        m = re.search(r"\bb2z_\w+_start\?\s+(\d+)\b", resolved_cmd)
        if m:
            cmd_run = int(m.group(1))
            if resolved_run_id is not None and resolved_run_id != cmd_run:
                raise ValueError(f"--run-id {resolved_run_id} does not match command run_id {cmd_run}")
            resolved_run_id = cmd_run
        if resolved_run_id is not None:
            host_sh_candidate = cfg_dir / f"uc1_{resolved_run_id}.host.sh"

    if not resolved_cmd:
        raise ValueError("empty board command")
    if resolved_run_id is None:
        raise ValueError("could not determine run_id from inputs; pass --run-id explicitly")
    if board_duration_s is None:
        board_duration_s = 305

    if output_path is not None:
        final_output = output_path
        final_exp_dir = output_path.parent
    else:
        final_exp_dir = experiment_dir
        if final_exp_dir is None and host_sh_candidate is not None:
            final_exp_dir = _extract_exp_dir_from_host_sh(host_sh_candidate)
        if final_exp_dir is None and exp_root.is_dir():
            matches = sorted(exp_root.glob(f"*_run{resolved_run_id}"))
            if len(matches) == 1:
                final_exp_dir = matches[0]
            elif len(matches) > 1:
                raise ValueError(
                    f"multiple experiment directories match *_run{resolved_run_id}: {matches}; specify --experiment-dir"
                )
        if final_exp_dir is None:
            today = datetime.now().strftime("%Y%m%d")
            final_exp_dir = exp_root / f"{today}_run{resolved_run_id}"
        final_output = final_exp_dir / "board.board.log"

    return {
        "run_id": resolved_run_id,
        "command": resolved_cmd,
        "board_duration_s": board_duration_s,
        "experiment_dir": final_exp_dir,
        "output_path": final_output,
        "source": source_desc,
    }


def open_serial_port(
    port: str = DEFAULT_PORT,
    baudrate: int = DEFAULT_BAUDRATE,
    bytesize: int = DEFAULT_BYTESIZE,
    stopbits: float = DEFAULT_STOPBITS,
    parity: str = DEFAULT_PARITY,
    timeout: float = 0.2,
):
    """Open pyserial port with 8N1 defaults and no hardware/software flow control."""
    import serial

    parity_map = {
        "N": serial.PARITY_NONE,
        "NONE": serial.PARITY_NONE,
        "E": serial.PARITY_EVEN,
        "EVEN": serial.PARITY_EVEN,
        "O": serial.PARITY_ODD,
        "ODD": serial.PARITY_ODD,
        "M": serial.PARITY_MARK,
        "S": serial.PARITY_SPACE,
    }
    bytesize_map = {
        5: serial.FIVEBITS,
        6: serial.SIXBITS,
        7: serial.SEVENBITS,
        8: serial.EIGHTBITS,
    }
    stopbits_map = {
        1: serial.STOPBITS_ONE,
        1.0: serial.STOPBITS_ONE,
        1.5: serial.STOPBITS_ONE_POINT_FIVE,
        2: serial.STOPBITS_TWO,
        2.0: serial.STOPBITS_TWO,
    }
    p_key = parity.strip().upper()
    if p_key not in parity_map:
        raise ValueError(f"unsupported parity: {parity}")
    if bytesize not in bytesize_map:
        raise ValueError(f"unsupported bytesize: {bytesize}")
    if stopbits not in stopbits_map:
        raise ValueError(f"unsupported stopbits: {stopbits}")

    return serial.Serial(
        port=port,
        baudrate=baudrate,
        bytesize=bytesize_map[bytesize],
        parity=parity_map[p_key],
        stopbits=stopbits_map[stopbits],
        timeout=timeout,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )


def execute_serial_run(
    ser: Any,
    job: dict[str, Any],
    *,
    overwrite: bool = False,
    char_delay_ms: float = 1.0,
    eol: str = "lf",
    start_timeout_s: float = 10.0,
    dump_timeout_margin_s: float = 300.0,
    post_end_drain_s: float = 0.5,
    verify_log: bool = True,
    quiet: bool = False,
    clock=time.monotonic,
    sleep=time.sleep,
) -> dict[str, Any]:
    """Send command over an open serial-like object, stream log to disk, and validate."""
    output_path: Path = job["output_path"]
    run_id: int = job["run_id"]
    command: str = job["command"]
    board_duration_s: int = job["board_duration_s"]

    if output_path.exists() and output_path.stat().st_size > 0 and not overwrite:
        raise FileExistsError(
            f"refusing to overwrite existing non-empty board log: {output_path} (use --overwrite if intended)"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    eol_bytes = {"lf": b"\n", "cr": b"\r", "crlf": b"\r\n"}[eol]

    # Drain any stale bytes sitting in the UART RX buffer before sending
    if hasattr(ser, "reset_input_buffer"):
        ser.reset_input_buffer()
    while True:
        waiting = getattr(ser, "in_waiting", 0)
        if not waiting:
            break
        ser.read(waiting)

    if not quiet:
        print(
            f"[uc1_board_send] run_id={run_id} sending command to {getattr(ser, 'port', 'serial')}: {command}",
            file=sys.stderr,
        )
        print(
            f"[uc1_board_send] logging directly to {output_path} (expected RF duration ~{board_duration_s}s + UART dump)",
            file=sys.stderr,
        )

    t0 = clock()
    max_deadline = t0 + board_duration_s + dump_timeout_margin_s
    start_deadline = t0 + start_timeout_s

    started_armed = False
    rf_final_seen = False
    cost_stats_seen = False
    terminal_end_seen = False
    terminal_end_time: float | None = None
    pending_line = ""
    bytes_written = 0
    lines_seen = 0

    start_pattern = re.compile(rf"\b(?:CONTROL_PLAN_START|UC1_CONFIG)\b.*\brun_id={run_id}\b")
    final_uc1_pattern = re.compile(rf"\bUC1_STATS\b.*\bfinal=1\b.*\brun_id={run_id}\b")
    final_plan_pattern = re.compile(rf"\bCONTROL_PLAN_STATS\b.*\bfinal=1\b.*\brun_id={run_id}\b")
    cost_pattern = re.compile(rf"\b(?:UC1_COST_STATS|COMPACT_COST_STATS|CONTROL_COST_STATS)\b.*\brun_id={run_id}\b")
    end_pattern = re.compile(rf"\b(?:CONTROL_TIME_END|COMPACT_TIME_END)\b.*\brun_id={run_id}\b")

    with output_path.open("wb") as log_file:
        # Pace command characters so Zynq's 64B hardware FIFO never overflows during FreeRTOS tick sleep
        payload = command.encode("ascii") + eol_bytes
        delay_s = max(0.0, char_delay_ms / 1000.0)
        if delay_s > 0:
            for b in payload:
                ser.write(bytes([b]))
                if hasattr(ser, "flush"):
                    ser.flush()
                sleep(delay_s)
        else:
            ser.write(payload)
            if hasattr(ser, "flush"):
                ser.flush()

        while True:
            now = clock()
            waiting = getattr(ser, "in_waiting", 0)
            chunk = ser.read(waiting if waiting and waiting > 0 else 256)
            if chunk:
                # Strip stray NUL bytes produced by USB-UART bridges on port open
                clean_chunk = chunk.replace(b"\x00", b"")
                if clean_chunk:
                    log_file.write(clean_chunk)
                    log_file.flush()
                    bytes_written += len(clean_chunk)
                    text = pending_line + clean_chunk.decode("utf-8", errors="replace")
                    parts = text.splitlines(keepends=True)
                    if parts and not (parts[-1].endswith("\n") or parts[-1].endswith("\r")):
                        pending_line = parts.pop()
                    else:
                        pending_line = ""

                    for raw_line in parts:
                        line = raw_line.strip()
                        if not line:
                            continue
                        lines_seen += 1
                        if any(line.startswith(prefix) for prefix in ERROR_PREFIXES):
                            raise RuntimeError(f"board rejected command: {line}")
                        if not started_armed and start_pattern.search(line):
                            started_armed = True
                            if not quiet:
                                print(f"[uc1_board_send] board armed & running: {line}", file=sys.stderr)
                        if not rf_final_seen and (final_uc1_pattern.search(line) or final_plan_pattern.search(line)):
                            rf_final_seen = True
                            if not quiet:
                                print(
                                    f"[uc1_board_send] RF schedule complete ({line.split()[0]} final=1); streaming UART burst/slot dump...",
                                    file=sys.stderr,
                                )
                        if not cost_stats_seen and cost_pattern.search(line):
                            cost_stats_seen = True
                        if not terminal_end_seen and end_pattern.search(line):
                            terminal_end_seen = True
                            terminal_end_time = clock()
                            if not quiet:
                                print(f"[uc1_board_send] received terminal marker: {line}", file=sys.stderr)

            now = clock()
            if terminal_end_seen and terminal_end_time is not None:
                if (now - terminal_end_time) >= post_end_drain_s and not getattr(ser, "in_waiting", 0):
                    break
            if not started_armed and now > start_deadline:
                raise TimeoutError(
                    f"timed out after {start_timeout_s:.1f}s waiting for CONTROL_PLAN_START run_id={run_id} "
                    f"(received {bytes_written} bytes; check serial port, baudrate, and board state)"
                )
            if now > max_deadline:
                raise TimeoutError(
                    f"timed out after {now - t0:.1f}s waiting for CONTROL_TIME_END/COMPACT_TIME_END run_id={run_id} "
                    f"(started={started_armed}, final_stats={rf_final_seen}, bytes={bytes_written})"
                )

    plan_summary = None
    if verify_log:
        plan = read_plan(output_path, run_id)
        uc1_stats = plan.get("uc1_stats") or {}
        burst_counts = (plan.get("bursts") or {}).get("counts") or {}
        plan_summary = {
            "planned_slots": plan["stats"].get("planned_slots"),
            "reached_slots": plan["stats"].get("reached_slots"),
            "planned_attempts": uc1_stats.get("planned_attempts"),
            "completed_attempts": uc1_stats.get("completed_attempts"),
            "failed_attempts": uc1_stats.get("failed_attempts"),
            "ble_tx_completed": burst_counts.get("ble_tx_completed"),
            "ieee_tx_completed": burst_counts.get("ieee_tx_completed"),
            "burst_completed": burst_counts.get("burst_completed"),
            "burst_attempted": burst_counts.get("burst_attempted"),
        }
        if not quiet:
            print(
                f"[uc1_board_send] verified {output_path} ({bytes_written} B, {lines_seen} lines): "
                f"attempts={plan_summary['completed_attempts']}/{plan_summary['planned_attempts']} "
                f"(failed={plan_summary['failed_attempts']}), "
                f"ble_tx={plan_summary['ble_tx_completed']}, ieee_tx={plan_summary['ieee_tx_completed']}, "
                f"bursts={plan_summary['burst_completed']}/{plan_summary['burst_attempted']}",
                file=sys.stderr,
            )

    return {
        "run_id": run_id,
        "command": command,
        "output_path": str(output_path),
        "bytes_written": bytes_written,
        "lines_seen": lines_seen,
        "started_armed": started_armed,
        "rf_final_seen": rf_final_seen,
        "cost_stats_seen": cost_stats_seen,
        "terminal_end_seen": terminal_end_seen,
        "verified": plan_summary,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Send pre-generated UC1 board command over serial and save board.board.log."
    )
    ap.add_argument("--run-id", type=int, help="UC1 run_id (auto-locates configs/uc1_<run_id>.json)")
    ap.add_argument("--config", type=Path, help="Path to frozen uc1_<run_id>.json manifest")
    ap.add_argument("--board-commands", type=Path, help="Path to uc1_<run_id>.board.txt")
    ap.add_argument("--command", help="Explicit board command string (overrides file command)")
    ap.add_argument("--experiment-dir", type=Path, help="Experiment directory to save board.board.log")
    ap.add_argument("--output", type=Path, help="Explicit output file path (default: <experiment-dir>/board.board.log)")
    ap.add_argument("--port", default=DEFAULT_PORT, help=f"Serial port (default: {DEFAULT_PORT})")
    ap.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE, help=f"Baud rate (default: {DEFAULT_BAUDRATE})")
    ap.add_argument("--bytesize", type=int, default=DEFAULT_BYTESIZE, choices=(5, 6, 7, 8), help="Data bits (default: 8)")
    ap.add_argument("--stopbits", type=float, default=DEFAULT_STOPBITS, choices=(1, 1.5, 2), help="Stop bits (default: 1)")
    ap.add_argument("--parity", default=DEFAULT_PARITY, help="Parity: N/None, E, O, M, S (default: N)")
    ap.add_argument("--char-delay-ms", type=float, default=1.0, help="Inter-character TX pacing in ms (default: 1.0)")
    ap.add_argument("--eol", choices=("lf", "cr", "crlf"), default="lf", help="Command line ending (default: lf)")
    ap.add_argument("--start-timeout-s", type=float, default=10.0, help="Seconds to wait for CONTROL_PLAN_START (default: 10)")
    ap.add_argument(
        "--dump-timeout-margin-s",
        type=float,
        default=300.0,
        help="Extra seconds beyond board_duration_s to allow 115200-baud UART stats dump (default: 300)",
    )
    ap.add_argument("--post-end-drain-s", type=float, default=0.5, help="Idle drain seconds after terminal marker (default: 0.5)")
    ap.add_argument("--overwrite", action="store_true", help="Allow overwriting an existing non-empty board.board.log")
    ap.add_argument("--no-verify", action="store_true", help="Skip plan_analyze.read_plan verification after capture")
    ap.add_argument("--dry-run", action="store_true", help="Print resolved command and output log path without opening serial")
    ap.add_argument("--quiet", action="store_true", help="Suppress progress messages on stderr")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    job = resolve_job(
        run_id=args.run_id,
        config_path=args.config,
        board_commands_path=args.board_commands,
        command=args.command,
        experiment_dir=args.experiment_dir,
        output_path=args.output,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "run_id": job["run_id"],
                    "command": job["command"],
                    "board_duration_s": job["board_duration_s"],
                    "experiment_dir": str(job["experiment_dir"]),
                    "output_path": str(job["output_path"]),
                    "port": args.port,
                    "baudrate": args.baudrate,
                    "bytesize": args.bytesize,
                    "stopbits": args.stopbits,
                    "parity": args.parity,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    with open_serial_port(
        port=args.port,
        baudrate=args.baudrate,
        bytesize=args.bytesize,
        stopbits=args.stopbits,
        parity=args.parity,
    ) as ser:
        result = execute_serial_run(
            ser,
            job,
            overwrite=args.overwrite,
            char_delay_ms=args.char_delay_ms,
            eol=args.eol,
            start_timeout_s=args.start_timeout_s,
            dump_timeout_margin_s=args.dump_timeout_margin_s,
            post_end_drain_s=args.post_end_drain_s,
            verify_log=not args.no_verify,
            quiet=args.quiet,
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

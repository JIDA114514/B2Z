#!/usr/bin/env python3
"""Verify the board's v1 primary/AuxPtr/secondary BLE path.

Live mode follows AuxPtr with one HackRF. File mode checks independently
decoded fixed-frequency packet logs; it cannot demonstrate RF retuning.
Neither mode treats host timestamps as a calibrated air-time measurement.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import re
import sys
import time
from uuid import uuid4

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from ble_exadv_hackrf_sniffer import (  # noqa: E402
    ble_channel_freq_hz, build_hop_top_block, parse_ad_structures,
    parse_ext_adv_payload,
)
from bsp_algorithm import bsp_algorithm  # noqa: E402
from control_match.protocol import control_record, ble_manufacturer_record  # noqa: E402
from experiment_tools.reporting import EXPERIMENTS, refresh_session, session_for  # noqa: E402


def _adi(packet: dict) -> tuple[int, int]:
    value = packet["ext"].get("adi")
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("missing_or_malformed_adi")
    return int(value[0]), int(value[1])


def _pdu_no_crc(packet: dict) -> bytes:
    data = bytes(packet["pdu"])
    if len(data) >= 2 and len(data) == 2 + data[1] + 3:
        return data[:-3]  # std_ble stream parser includes CRC in its packet buffer.
    return data  # exadv_rx packet files keep CRC in a separate field.


def validate_primary(packet: dict, args) -> dict:
    """Check the exact board v1 ADV_EXT_IND shape, independent of expectations."""
    pdu = _pdu_no_crc(packet)
    ext = packet["ext"]
    if not packet["crc_ok"] or packet["channel"] != args.primary_channel:
        raise ValueError("primary_crc_or_rf_channel")
    if (len(pdu) != 9 or pdu[0] & 0x0f != 7 or pdu[1] != 7 or
            packet["kind"] != "primary" or ext.get("adv_mode") != 0 or
            ext.get("ext_hdr_len") != 6 or ext.get("flags") != 0x18 or
            ext.get("adva") is not None or ext.get("adv_data")):
        raise ValueError("primary_pdu_shape")
    sid, did = _adi(packet)
    aux = ext.get("aux_ptr")
    if sid != 0 or not aux or (aux["channel"], aux["offset_us"], aux["phy"]) != (
            args.secondary_channel, args.aux_offset_us, 0):
        raise ValueError("primary_adi_or_auxptr")
    if did >= args.expected_attempts:
        raise ValueError("primary_did_out_of_range")
    return {"sid": sid, "did": did, "aux_ptr": aux, "pdu_hex": pdu.hex()}


def validate_secondary(packet: dict, args) -> dict:
    """Check BLE CRC, extended fields, AD envelope and B2Z application CRC."""
    pdu = _pdu_no_crc(packet)
    ext = packet["ext"]
    if not packet["crc_ok"] or packet["channel"] != args.secondary_channel:
        raise ValueError("secondary_crc_or_rf_channel")
    payload_len = pdu[1]
    if (len(pdu) != payload_len + 2 or pdu[0] != 0x47 or pdu[1] != payload_len or
            packet["kind"] != "secondary" or ext.get("adv_mode") != 0 or
            ext.get("ext_hdr_len") != 9 or ext.get("flags") != 0x09 or
            ext.get("aux_ptr") is not None or
            (ext.get("adva") or "").upper() != args.expected_adva.upper()):
        raise ValueError("secondary_pdu_shape")
    sid, did = _adi(packet)
    ad = parse_ad_structures(bytes(ext["adv_data"]))
    if (len(ad) != 2 or ad[0][0] != 0x01 or bytes(ad[0][1]) != b"\x06" or
            ad[1][0] != 0xff):
        raise ValueError("secondary_ad_structure")
    manufacturer = bytes(ad[1][1])
    raw = ble_manufacturer_record(manufacturer, payload_len)
    if (getattr(args,"payload_mode","joint")=="ble-only") != (payload_len==52):
        raise ValueError("secondary_pdu_shape")
    record = control_record(raw, "ble")
    if (sid != 0 or did != (record["slot_index"] & 0x0fff) or
            record["slot_index"] >= args.expected_attempts or
            record["run_id"] != args.run_id or
            record["period_ms"] != args.period_ms or
            (args.command_id is not None and record["command_id"] != args.command_id)):
        raise ValueError("secondary_identity_or_control_fields")
    return {"sid": sid, "did": did, "control": record,
            "encoded_ieee_bytes": len(manufacturer)-2-len(raw), "pdu_hex": pdu.hex()}


def file_packet(row: dict) -> dict:
    """Reparse an exadv_rx record with the std_ble extended-header parser."""
    pdu = bytes.fromhex(row["pdu_hex"])
    if len(pdu) < 2:
        raise ValueError("packet_short")
    if not row.get("crc_ok") or bytes.fromhex(row["crc_hex"]) != bytes(
            bsp_algorithm.bt_crc(list(pdu), len(pdu))):
        raise ValueError("packet_crc")
    if len(pdu) != 2 + (pdu[1] if pdu[0] & 0x0f == 7 else pdu[1] & 0x3f):
        raise ValueError("packet_length")
    ext = parse_ext_adv_payload(list(pdu[2:]))
    return {"channel": row["channel"], "pdu": pdu, "ext": ext,
            "kind": "primary" if row["channel"] >= 37 else "secondary",
            "crc_ok": True, "sample_time_s": row.get("sample_time_s")}


def _run_from_path(path: Path) -> int | None:
    for part in path.parts:
        match = re.fullmatch(r"\d{8}_run(\d+)", part)
        if match:
            return int(match.group(1))
    return None


def _load_file(path: Path) -> tuple[list[dict], dict]:
    packets = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    summary_path = path.with_name("rx.summary.json")
    if not summary_path.is_file():
        raise ValueError(f"receiver summary missing: {summary_path}")
    summary = json.loads(summary_path.read_text())
    if summary.get("status") != "complete":
        raise ValueError(f"receiver did not complete: {summary_path}")
    return packets, summary


def _board_stats(path: Path | None, run_id: int) -> dict | None:
    if path is None:
        return None
    for line in path.read_text().splitlines():
        if not line.startswith("CONTROL_STATS final=1 "):
            continue
        fields = dict(item.split("=", 1) for item in line.split()[1:] if "=" in item)
        if fields.get("run_id") == str(run_id):
            return fields
    raise ValueError("matching final CONTROL_STATS not found")


def _record_packet(events: list[dict], kind: str, packet: dict, detail: dict) -> None:
    events.append({"event": kind, "channel": packet["channel"],
                   "did": detail["did"], "pdu_hex": detail["pdu_hex"],
                   "crc_ok": packet["crc_ok"],
                   **({"host_callback_monotonic_s": packet["monotonic"]} if "monotonic" in packet else {}),
                   **({"stream_generation": packet["stream_generation"], "demodulated_byte_start": packet.get("abs_start")}
                      if "stream_generation" in packet else {}),
                   **({"crc_hex": bytes(packet["pdu"][-3:]).hex()}
                      if len(packet["pdu"]) == len(bytes.fromhex(detail["pdu_hex"])) + 3 else {}),
                   **({"preamble_errors": packet["preamble_errors"]}
                      if "preamble_errors" in packet else {}),
                   **({"bit_alignment": packet["bit_alignment"]}
                      if "bit_alignment" in packet else {}),
                   **({"control": detail["control"]} if "control" in detail else {}),
                   **({"sample_time_s": packet["sample_time_s"]}
                      if packet.get("sample_time_s") is not None else {})})


def verify_files(args) -> dict:
    primary_run = _run_from_path(args.primary_packets)
    secondary_run = _run_from_path(args.secondary_packets)
    if primary_run is None or secondary_run is None:
        raise ValueError("both packet files must reside under YYYYMMDD_run<id>")
    separate_runs = primary_run != secondary_run
    if separate_runs and not args.allow_cross_run_structure_only:
        raise ValueError("files are from different runs; use --allow-cross-run-structure-only")
    if not separate_runs and primary_run != args.run_id:
        raise ValueError("file run ID differs from --run-id")
    primaries, primary_summary = _load_file(args.primary_packets)
    secondaries, secondary_summary = _load_file(args.secondary_packets)
    if not separate_runs:
        start = max(datetime.fromisoformat(primary_summary["start_utc"]),
                    datetime.fromisoformat(secondary_summary["start_utc"]))
        end = min(datetime.fromisoformat(primary_summary["end_utc"]),
                  datetime.fromisoformat(secondary_summary["end_utc"]))
        if start >= end:
            raise ValueError("same-run primary and secondary captures do not overlap")
    events: list[dict] = []
    counts: Counter = Counter()
    primary_dids: set[int] = set()
    secondary_dids: set[int] = set()
    for line_no, row in enumerate(primaries, 1):
        counts["primary_observed"] += 1
        try:
            packet = file_packet(row)
            detail = validate_primary(packet, args)
        except (ValueError, KeyError, TypeError) as exc:
            counts["primary_invalid"] += 1
            events.append({"event": "primary_invalid", "line_no": line_no,
                           "reason": str(exc),
                           "pdu_hex": row.get("pdu_hex") if isinstance(row, dict) else None})
            continue
        if detail["did"] in primary_dids:
            counts["primary_duplicate_did"] += 1
        primary_dids.add(detail["did"])
        _record_packet(events, "primary_valid", packet, detail)
    for line_no, row in enumerate(secondaries, 1):
        counts["secondary_observed"] += 1
        try:
            packet = file_packet(row)
            detail = validate_secondary(packet, args)
        except (ValueError, KeyError, TypeError) as exc:
            counts["secondary_invalid"] += 1
            events.append({"event": "secondary_invalid", "line_no": line_no,
                           "reason": str(exc),
                           "pdu_hex": row.get("pdu_hex") if isinstance(row, dict) else None})
            continue
        if detail["did"] in secondary_dids:
            counts["secondary_duplicate_did"] += 1
        secondary_dids.add(detail["did"])
        _record_packet(events, "secondary_valid", packet, detail)
    paired = sorted(primary_dids & secondary_dids) if not separate_runs else []
    counts["identity_correlated"] = len(paired)
    for did in paired:
        events.append({"event": "identity_correlated", "did": did,
                       "timing_status": "not_calibrated_independent_iq"})
    complete_primary = primary_dids == set(range(args.expected_attempts))
    complete_secondary = secondary_dids == set(range(args.expected_attempts))
    return {"mode": "files", "counts": dict(counts), "events": events,
            "primary_dids": sorted(primary_dids), "secondary_dids": sorted(secondary_dids),
            "paired_dids": paired, "separate_runs": separate_runs,
            "primary_source_run_id": primary_run, "secondary_source_run_id": secondary_run,
            "primary_correct": (complete_primary and counts["primary_invalid"] == 0 and
                                counts["primary_duplicate_did"] == 0),
            "secondary_correct": (complete_secondary and counts["secondary_invalid"] == 0 and
                                  counts["secondary_duplicate_did"] == 0),
            "follow_observed": False,
            "assessment": ("cross_run_structure_only" if separate_runs else
                           "same_run_content_correlated_timing_unverified" if
                           complete_primary and complete_secondary and len(paired) == args.expected_attempts and
                           counts["primary_invalid"] == 0 and counts["secondary_invalid"] == 0 else
                           "incomplete_same_run_content_observation")}


def verify_live(args) -> dict:
    """Follow each valid primary immediately, then wait through its AuxPtr."""
    start_utc = datetime.now(timezone.utc).isoformat()
    packet_queue: queue.Queue = queue.Queue()
    args.center_freq = ble_channel_freq_hz(args.primary_channel)
    args.keep_crc_errors = False
    tb = build_hop_top_block(args, packet_queue)
    counts: Counter = Counter()
    events: list[dict] = []
    primary_dids: set[int] = set()
    secondary_dids: set[int] = set()
    paired: set[int] = set()
    active: tuple[dict, dict] | None = None
    deadline = 0.0
    window_crc_start = 0
    stopped = False
    def stage(event, **detail):
        events.append({"event": event, "host_monotonic_s": time.monotonic(),
                       "timing_scope": "host_software_only", **tb.diagnostic_state(), **detail})

    def tune(channel, did=None):
        stage("tune_request", channel=channel, did=did)
        try:
            result = tb.tune_channel(channel, args.settle_us)
        except Exception as exc:
            stage("tune_error", channel=channel, did=did, reason=str(exc))
            raise
        stage("tune_return", channel=channel, did=did, **result)

    tb.start()
    try:
        tune(args.primary_channel)
        end = time.monotonic() + args.duration
        while time.monotonic() < end:
            if active and time.monotonic() >= deadline:
                counts["follow_window_miss"] += 1
                events.append({"event": "follow_window_miss", "did": active[1]["did"],
                               "crc_errors_in_window": tb.packet_sink.parser.crc_errors - window_crc_start})
                stage("secondary_window_exit", did=active[1]["did"], outcome="miss")
                tune(args.primary_channel, active[1]["did"])
                active = None
            try:
                packet = packet_queue.get(timeout=0.01)
            except queue.Empty:
                continue
            stage("packet_dequeued", channel=packet["channel"], active_did=active[1]["did"] if active else None,
                  packet_generation=packet.get("stream_generation"),
                  queue_delay_ms=(time.monotonic()-packet["monotonic"])*1000)
            if packet.get("stream_generation") != tb.diagnostic_state()["stream_generation"]:
                counts["stale_generation_discard"] += 1
                stage("packet_discard", reason="stale_generation", channel=packet["channel"])
                continue
            if active is None:
                if packet["channel"] != args.primary_channel:
                    continue
                counts["primary_observed"] += 1
                try:
                    detail = validate_primary(packet, args)
                except ValueError as exc:
                    counts["primary_invalid"] += 1
                    stage("primary_invalid", reason=str(exc), pdu_hex=_pdu_no_crc(packet).hex())
                    continue
                primary_dids.add(detail["did"])
                _record_packet(events, "primary_valid", packet, detail)
                active = (packet, detail)
                retune_started = time.monotonic()
                tune(args.secondary_channel, detail["did"])
                events.append({"event": "tune_secondary", "did": detail["did"],
                               "host_retune_ms": (time.monotonic() - retune_started) * 1000,
                               "channel": args.secondary_channel})
                window_crc_start = tb.packet_sink.parser.crc_errors
                # This is a host observation window, not a measured RF offset.
                deadline = packet["monotonic"] + args.follow_window_ms / 1000
                stage("secondary_window_enter", did=detail["did"], host_deadline_s=deadline)
                continue
            if packet["channel"] != args.secondary_channel:
                continue
            counts["secondary_observed"] += 1
            try:
                detail = validate_secondary(packet, args)
            except ValueError as exc:
                counts["secondary_invalid"] += 1
                stage("secondary_invalid", did=active[1]["did"], reason=str(exc), pdu_hex=_pdu_no_crc(packet).hex())
                continue
            secondary_dids.add(detail["did"])
            _record_packet(events, "secondary_valid", packet, detail)
            if detail["did"] != active[1]["did"] or detail["sid"] != active[1]["sid"]:
                counts["identity_mismatch"] += 1
                stage("identity_mismatch", did=active[1]["did"], observed_did=detail["did"])
                continue
            paired.add(detail["did"])
            counts["followed_events"] += 1
            events.append({"event": "followed_event", "did": detail["did"],
                           "host_observation_delta_ms":
                           (packet["monotonic"] - active[0]["monotonic"]) * 1000,
                           "timing_status": "host_diagnostic_only"})
            print(f"FOLLOW did={detail['did']} run={detail['control']['run_id']} "
                  f"command={detail['control']['command_id']} BLE_CRC=OK app_CRC=OK",
                  flush=True)
            stage("secondary_window_exit", did=detail["did"], outcome="matched")
            tune(args.primary_channel, detail["did"])
            active = None
    except KeyboardInterrupt:
        stopped = True
    except Exception as exc:
        stopped = True
        stage("capture_error", reason=str(exc))
    finally:
        tb.stop()
        tb.wait()
    if active:
        stage("secondary_window_exit", did=active[1]["did"], outcome="capture_end")
        counts["follow_window_miss"] += 1
        events.append({"event": "follow_window_miss", "did": active[1]["did"],
                       "crc_errors_in_window": tb.packet_sink.parser.crc_errors - window_crc_start})
    stage("capture_end", interrupted=stopped)
    counts["demod_crc_errors"] = tb.packet_sink.parser.crc_errors
    complete = paired == set(range(args.expected_attempts))
    return {"mode": "live_hop", "counts": dict(counts), "events": events,
            "diagnostics_schema": "b2z_follow_stages_v1", "timeline_status": "timeline_unverified",
            "iq_saved": False, "stream_counter_unit": "demodulated_bytes_not_IQ_samples",
            "start_utc": start_utc, "end_utc": datetime.now(timezone.utc).isoformat(),
            "primary_dids": sorted(primary_dids), "secondary_dids": sorted(secondary_dids),
            "paired_dids": sorted(paired), "separate_runs": False,
            "primary_correct": primary_dids == set(range(args.expected_attempts)),
            "secondary_correct": secondary_dids == set(range(args.expected_attempts)),
            "follow_observed": complete and not stopped,
            "assessment": ("auxptr_driven_follow_content_verified_timing_unverified" if complete else
                           "incomplete_follow_observation"), "interrupted": stopped}


def verification_passed(result: dict) -> bool:
    passed = result["primary_correct"] and result["secondary_correct"] and not result["separate_runs"]
    return passed and (result["mode"] != "live_hop" or result["follow_observed"])


def write_results(args, result: dict) -> Path:
    board = _board_stats(args.board_log, args.run_id)
    if board and (board.get("rf_mode") != ("separate_secondary_ch3" if args.payload_mode == "ble-only" else "standard_secondary_ch3") or
                  board.get("aux_channel") != str(args.secondary_channel) or
                  board.get("aux_offset_us") != str(args.aux_offset_us) or
                  board.get("period_ms") != str(args.period_ms) or
                  board.get("attempts") != str(args.expected_attempts) or
                  (args.command_id is not None and board.get("command_id") != str(args.command_id))):
        raise ValueError("board CONTROL_STATS configuration differs from verifier")
    if args.output_dir:
        output = args.output_dir
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = HERE.parent / "experiments" / f"{datetime.now():%Y%m%d}_run{args.run_id}"
        output = root / "analyses" / f"std_ble_flow_{stamp}_{uuid4().hex[:6]}"
    output.mkdir(parents=True, exist_ok=False)
    summary = {key: value for key, value in result.items() if key != "events"}
    summary.update(schema="board_std_ble_flow_v1", status="complete", run_id=args.run_id,
                   verification_passed=verification_passed(result),
                   command_id=args.command_id, expected_attempts=args.expected_attempts,
                   expected_adva=args.expected_adva, payload_mode=args.payload_mode,
                   primary_channel=args.primary_channel,
                   secondary_channel=args.secondary_channel,
                   advertised_aux_offset_us=args.aux_offset_us,
                   period_ms=args.period_ms, board=board,
                   source_files={"primary_packets": str(args.primary_packets) if args.primary_packets else None,
                                 "secondary_packets": str(args.secondary_packets) if args.secondary_packets else None,
                                 "board_log": str(args.board_log) if args.board_log else None},
                   receiver_config={"osmosdr_args": args.osmosdr_args, "sample_rate": args.sample_rate,
                                    "gain": args.gain, "if_gain": args.if_gain, "bb_gain": args.bb_gain,
                                    "duration_s": args.duration, "settle_us": args.settle_us,
                                    "follow_window_ms": args.follow_window_ms},
                   aux_air_timing_verified=False,
                   full_standard_exadv_verified=False,
                   limitations=["host/GNU Radio callback time is not an RF timestamp",
                                "retuning may interrupt the sample stream",
                                "fixed-IQ files do not demonstrate receiver following",
                                "no calibrated primary-to-secondary air-time measurement"])
    (output / "flow.summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    (output / "flow.events.jsonl").write_text("".join(json.dumps(event, ensure_ascii=False) + "\n"
                                                     for event in result["events"]))
    board_lines = []
    if board:
        board_lines = ["- 板端 DMA 计数：primary_completed=" + board.get("primary_completed", "N/A") +
                       "，tx_completed=" + board.get("tx_completed", "N/A") +
                       "，auxptr_dma_window_miss=" + board.get("auxptr_dma_window_miss", "N/A") +
                       "，retune_failure=" + board.get("retune_failure", "N/A") + "。", ""]
    lines = ["# 板端 BLE exadv 流程验证", "",
             f"- Run ID：{args.run_id}；模式：{result['mode']}；结论：`{result['assessment']}`。",
             f"- primary 有效 DID：{result['primary_dids']}。",
             f"- secondary 有效 DID：{result['secondary_dids']}。",
             f"- 同轮关联／实际跟随 DID：{result['paired_dids']}。",
             f"- 软件跟随观察：{result['follow_observed']}；空口 AuxPtr 时间窗：未校准、未验证。",
             f"- 计数：{result['counts']}。",
             f"- 板端日志：{args.board_log if args.board_log else '未提供'}。", "",
             *board_lines,
             "CRC 正确、AuxPtr 字段正确与同一接收机跟随成功分别记录；它们不自动证明实际空口间隔满足 BLE 规范。",
             "原始逐包与原因见 `flow.events.jsonl`，结构化计数见 `flow.summary.json`。", ""]
    (output / "flow.md").write_text("\n".join(lines))
    session = session_for(output / "flow.summary.json", EXPERIMENTS)
    if session and re.fullmatch(r"\d{8}_run\d+", session.name):
        refresh_session(session)
    return output


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--command-id", type=int, default=None)
    parser.add_argument("--expected-attempts", type=int, default=10)
    parser.add_argument("--period-ms", type=int, default=500)
    parser.add_argument("--payload-mode", choices=("joint", "ble-only"), default="joint",
                        help="explicit secondary wire format; BLE-only is the N2 separate baseline")
    parser.add_argument("--primary-channel", type=int, default=39)
    parser.add_argument("--secondary-channel", type=int, default=3)
    parser.add_argument("--aux-offset-us", type=int, default=300000)
    parser.add_argument("--expected-adva", default="C1:A2:A3:A4:A5:A6")
    parser.add_argument("--board-log", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--primary-packets", type=Path, help="exadv_rx primary .packets.jsonl; enables file mode")
    parser.add_argument("--secondary-packets", type=Path, help="exadv_rx secondary .packets.jsonl")
    parser.add_argument("--allow-cross-run-structure-only", action="store_true")
    parser.add_argument("--duration", type=float, default=15.0, help="live capture seconds")
    parser.add_argument("--sample-rate", type=int, default=8000000, choices=(4000000, 8000000))
    parser.add_argument("--osmosdr-args", default="hackrf=0", help="select BLE HackRF as in std_ble sniffer")
    parser.add_argument("--gain", type=float, default=0)
    parser.add_argument("--if-gain", type=float, default=16)
    parser.add_argument("--bb-gain", type=float, default=10)
    parser.add_argument("--settle-us", type=float, default=1000)
    parser.add_argument("--follow-window-ms", type=float, default=360,
                        help="host listening window after primary; not an AuxPtr timing tolerance")
    args = parser.parse_args(argv)
    if not 1 <= args.run_id <= 65535 or args.expected_attempts < 1 or args.expected_attempts > 4096:
        parser.error("run ID or expected attempts out of range")
    if (args.period_ms <= 0 or args.aux_offset_us <= 0 or args.duration <= 0 or
            args.settle_us < 0 or not args.aux_offset_us / 1000 < args.follow_window_ms < args.period_ms):
        parser.error("invalid period, AuxPtr offset or live observation window")
    if args.primary_channel not in (37, 38, 39) or not 0 <= args.secondary_channel <= 36:
        parser.error("primary must be an advertising channel and secondary a data channel")
    if bool(args.primary_packets) != bool(args.secondary_packets):
        parser.error("provide both --primary-packets and --secondary-packets")
    for path in (args.primary_packets, args.secondary_packets, args.board_log):
        if path and not path.is_file():
            parser.error(f"file does not exist: {path}")
    if args.output_dir and args.output_dir.exists():
        parser.error("--output-dir must not already exist")
    ble_channel_freq_hz(args.primary_channel)
    ble_channel_freq_hz(args.secondary_channel)
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    result = verify_files(args) if args.primary_packets else verify_live(args)
    output = write_results(args, result)
    print(f"assessment={result['assessment']} primary={result['primary_dids']} "
          f"secondary={result['secondary_dids']} paired={result['paired_dids']} "
          f"output={output}", flush=True)
    return 0 if verification_passed(result) else 2


if __name__ == "__main__":
    raise SystemExit(main())

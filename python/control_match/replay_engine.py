#!/usr/bin/env python3
"""Replay one independently decoded receiver stream through the control engine.

The input JSONL needs available_sample, recorded when the packet was emitted
by a streaming decoder. Old packet files must be regenerated from saved IQ;
packet start is never substituted for availability.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

try:
    from .control_engine import EngineConfig, SideControlEngine
    from .immediate_engine import ImmediateControlEngine
    from .packet_adapter import control_payload
except ImportError:
    from control_engine import EngineConfig, SideControlEngine
    from immediate_engine import ImmediateControlEngine
    from packet_adapter import control_payload


def replay_records(rows: list[dict], config: EngineConfig, total_samples: int,
                   progress_step_samples: int | None = None,
                   policy: str = "scheduled") -> tuple[list[dict], dict]:
    """Run one side only, preserving decoder availability and IQ chronology."""
    if not isinstance(total_samples, int) or total_samples < 0:
        raise ValueError("total_samples must be nonnegative")
    step = (max(1, round(config.sample_rate / 100)) if progress_step_samples is None
            else progress_step_samples)
    if not isinstance(step, int) or step <= 0:
        raise ValueError("progress step must be a positive sample count")
    observations = []
    for line_no, packet in enumerate(rows, 1):
        try:
            payload = control_payload(packet, config.side)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"packet row {line_no}: {exc}") from exc
        if payload is None:
            continue
        if policy == "scheduled" and config.side == "ble" and packet.get("pdu_length") == 52:
            raise ValueError("BLE-only separate layout does not support the joint scheduled reference")
        if "available_sample" not in packet:
            raise ValueError(f"packet row {line_no}: missing available_sample; replay saved IQ")
        if packet["available_sample"] > total_samples:
            raise ValueError(f"packet row {line_no}: availability exceeds capture")
        observations.append((payload, packet["sample_start"], packet["available_sample"]))
    if policy not in ("scheduled", "immediate"):
        raise ValueError("policy must be scheduled or immediate")
    engine = SideControlEngine(config) if policy == "scheduled" else ImmediateControlEngine(config)
    events = []
    cursor = 0
    for payload, start, available in observations:
        while (cursor // step + 1) * step < available:
            cursor = (cursor // step + 1) * step
            events.extend(engine.advance(cursor))
        events.extend(engine.observe(payload, start, available))
        cursor = available
    while (cursor // step + 1) * step <= total_samples:
        cursor = (cursor // step + 1) * step
        events.extend(engine.advance(cursor))
    if cursor < total_samples:
        events.extend(engine.advance(total_samples))
    counts = Counter(event["event"] for event in events)
    reasons = Counter(event["reason"] for event in events if "reason" in event)
    foreign_runs = sorted({event["observed_run_id"] for event in events
                           if event["event"] == "foreign_run"})
    return events, {"control_observations": len(observations), "policy": policy,
                    "events": dict(counts),
                    "reasons": dict(reasons), "engine": engine.snapshot(),
                    "foreign_run_ids": foreign_runs,
                    "time_reference": "one_receiver_iq_sample_domain",
                    "progress_step_samples": step,
                    "progress_scope": "sample-domain replay; no host dispatch-time reconstruction",
                    "software_only": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packets", type=Path, required=True, help="one side's rx.packets.jsonl")
    parser.add_argument("--side", choices=("ble", "zigbee"), required=True)
    parser.add_argument("--run-id", type=int, required=True, help="must match packet contents")
    parser.add_argument("--target-id", type=int, action="append", required=True,
                        help="configured receiver node/group ID; repeat for several memberships")
    parser.add_argument("--sender-id", default="configured_board")
    parser.add_argument("--accept-broadcast", action="store_true")
    parser.add_argument("--policy", choices=("scheduled", "immediate"), default="scheduled",
                        help="immediate processes the first valid command at decoder availability")
    parser.add_argument("--assumed-reference-bound-ms", type=float,
                        help="functional replay assumption, not measured synchronization accuracy")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.packets.is_file():
        parser.error("packets file does not exist")
    summary_path = args.packets.with_name(args.packets.name.replace(".packets.jsonl", ".summary.json"))
    if args.packets.name == summary_path.name or not summary_path.is_file():
        parser.error("matching rx.summary.json is required")
    receiver = json.loads(summary_path.read_text(encoding="utf-8"))
    if receiver.get("status") != "complete":
        parser.error("receiver capture must have completed")
    if receiver.get("counts", {}).get("samples_processed") is None:
        parser.error("receiver summary has no processed sample count")
    if receiver.get("config", {}).get("control_layout") == "separate" and args.policy == "scheduled":
        parser.error("separate layout has no shared RF epoch; use immediate replay")
    sample_rate = receiver.get("config", {}).get("sample_rate")
    if not isinstance(sample_rate, int):
        parser.error("receiver summary has no integer sample rate")
    if args.assumed_reference_bound_ms is not None and (not math.isfinite(args.assumed_reference_bound_ms) or
                                                        args.assumed_reference_bound_ms < 0):
        parser.error("assumed reference bound must be finite and nonnegative")
    if args.policy == "immediate" and args.assumed_reference_bound_ms is not None:
        parser.error("immediate policy does not use a reference bound")
    try:
        config = EngineConfig(side=args.side, run_id=args.run_id, sample_rate=sample_rate,
                              target_ids=frozenset(args.target_id), sender_id=args.sender_id,
                              accept_broadcast=args.accept_broadcast,
                              external_reference_bound_ms=args.assumed_reference_bound_ms)
        rows = [json.loads(line) for line in args.packets.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        events, result = replay_records(rows, config, receiver["counts"]["samples_processed"],
                                        receiver["config"].get("block_samples"), args.policy)
        if result["events"].get("decoded", 0) == 0 and result["foreign_run_ids"]:
            raise ValueError(f"requested run {args.run_id}, packet contents have run IDs "
                             f"{result['foreign_run_ids']}")
    except (ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    output = args.output_dir
    if output.exists():
        parser.error(f"output directory already exists: {output}")
    output.mkdir(parents=True)
    events_path = output / "control.events.jsonl"
    events_path.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
                           encoding="utf-8")
    result.update(schema=("b2z_control_engine_replay_v1" if args.policy == "scheduled" else
                          "b2z_immediate_baseline_replay_v1"), side=args.side, run_id=args.run_id,
                  target_ids=sorted(config.target_ids), sample_rate=sample_rate,
                  assumed_reference_bound_ms=args.assumed_reference_bound_ms,
                  assumption_status=("no time reference used; deadline and target-time checks not evaluated"
                                     if args.policy == "immediate" else
                                     "uncalibrated; timed actions denied" if args.assumed_reference_bound_ms is None
                                     else "user-supplied functional replay assumption; not a measured bound"),
                  generated_utc=datetime.now(timezone.utc).isoformat(),
                  sources={"packets": str(args.packets.resolve()),
                           "packets_sha256": hashlib.sha256(args.packets.read_bytes()).hexdigest(),
                           "receiver_summary": str(summary_path.resolve())},
                  limitations=["one receiver only; no cross-device execution error",
                               "software state/actions are sample-domain replay, not physical actuator events",
                               "sender planned timestamp is not calibrated RF start",
                               *(["immediate baseline does not schedule against execute_at_ms or evaluate runtime expiry"]
                                  if args.policy == "immediate" else [])])
    (output / "control.summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
    print(f"side={args.side} run={args.run_id} observations={result['control_observations']} "
          f"accepted={result['events'].get('accepted', 0)} "
          f"software_processed={result['events'].get('software_processed', 0)} "
          f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

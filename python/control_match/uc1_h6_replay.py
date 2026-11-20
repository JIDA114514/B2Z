#!/usr/bin/env python3
"""Offline H6 fault-injection replay on real recorded UC1/C3 packet streams.

Reads frozen UC1 config and real recorded BLE/IEEE rx.packets.jsonl files in
read-only mode, applies explicit in-memory fault injections to copies of the
recorded packets, and writes auditable results into a new analysis directory
under <experiment-dir>/analyses/<analysis-id>/.

All injected cases are explicitly tagged as offline synthetic fault injections
on recorded packets and never overwrite raw captures or prior analyses.
"""
from __future__ import annotations

import argparse
import binascii
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from analyze import discover, extract_ble, extract_zigbee  # noqa: E402
from compact import BLEControlExtractor, uc1_record  # noqa: E402
from control_engine import EngineConfig, SideControlEngine  # noqa: E402
from protocol import control_record  # noqa: E402
from uc1_config import validate as validate_uc1_config  # noqa: E402


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _ble_ad_data(pkt: dict) -> tuple[dict, bytes]:
    for ad in pkt.get("extended", {}).get("ad_structures", []):
        if ad.get("type") == 255 and ad.get("company_id") == 0xFFFF and ad.get("data_hex"):
            return ad, bytes.fromhex(ad["data_hex"])
    raise ValueError("missing BLE 0xFFFF manufacturer AD structure")


def _flip_ble_ad_byte(pkt: dict, offset_from_start: int, xor_mask: int = 0x01) -> dict:
    out = deepcopy(pkt)
    ad, raw = _ble_ad_data(out)
    buf = bytearray(raw)
    buf[offset_from_start] ^= xor_mask
    ad["data_hex"] = bytes(buf).hex()
    return out


def _flip_zigbee_payload_byte(pkt: dict, offset: int, xor_mask: int = 0x01) -> dict:
    out = deepcopy(pkt)
    buf = bytearray(bytes.fromhex(out["payload_hex"]))
    buf[offset] ^= xor_mask
    out["payload_hex"] = bytes(buf).hex()
    return out


def _mutate_uc1_arg_valid_crc(raw_record: bytes, new_arg: int) -> bytes:
    """Mutate UC1 uint16 arg at bytes [17:19] and recompute CRC-16/CCITT."""
    buf = bytearray(raw_record)
    struct.pack_into("<H", buf, 17, new_arg & 0xFFFF)
    crc = binascii.crc_hqx(bytes(buf[:-2]), 0xFFFF)
    struct.pack_into("<H", buf, len(buf) - 2, crc)
    return bytes(buf)


def _run_c3_stream(
    packets: list[dict],
    run_id: int,
    layout: dict,
    *,
    pending_limit: int = 16,
    closed_limit: int = 256,
    timeout_s: float = 2.0,
) -> dict:
    ex = BLEControlExtractor(
        timeout=timeout_s,
        pending_limit=pending_limit,
        closed_limit=closed_limit,
        allowed_run_id=run_id,
        layout=layout,
    )
    valid_slots = []
    valid_commands = set()
    invalid_reasons: dict[str, int] = {}
    invariant_ok = True
    for pkt in packets:
        try:
            data = ex(pkt)
        except ValueError as exc:
            reason = str(exc)
            invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
            if len(ex.closed) + len(ex.pending) > closed_limit:
                invariant_ok = False
            continue
        if len(ex.closed) + len(ex.pending) > closed_limit:
            invariant_ok = False
        if data is None:
            continue
        try:
            rec = control_record(data, "ble", layout=layout)
        except ValueError as exc:
            reason = str(exc)
            invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
            continue
        if rec["run_id"] == run_id:
            valid_slots.append(rec["slot_index"])
            valid_commands.add(rec["command_id"])
    ex.finish()
    if len(ex.closed) + len(ex.pending) > closed_limit:
        invariant_ok = False
    return {
        "valid_records": len(valid_slots),
        "unique_slots": len(set(valid_slots)),
        "unique_commands": len(valid_commands),
        "valid_slots": sorted(set(valid_slots)),
        "invalid_reasons": invalid_reasons,
        "extractor_counts": dict(ex.counts),
        "closed_count": len(ex.closed),
        "pending_count": len(ex.pending),
        "closed_exhausted": ex.closed_exhausted,
        "capacity_invariant_ok": invariant_ok,
    }


def run_c3_fault_suite(cfg: dict, ble_packets: list[dict]) -> list[dict]:
    run_id = cfg["run_id"]
    layout = cfg["layout"]
    cases = []

    # 1. Baseline unmodified recorded stream
    base = _run_c3_stream(ble_packets, run_id, layout)
    expected_records = base["valid_records"]
    cases.append({
        "case_id": "c3_baseline_recorded",
        "synthetic_injection": False,
        "description": "Unmodified recorded C3 BLE fragment stream replayed through BLEControlExtractor",
        "passed": (
            expected_records > 0
            and base["invalid_reasons"] == {}
            and base["extractor_counts"].get("pending_overflow", 0) == 0
            and base["extractor_counts"].get("closed_capacity_exhausted", 0) == 0
            and base["capacity_invariant_ok"]
        ),
        "metrics": base,
    })

    # Group recorded fragment indices by slot_index from C3 header:
    # AD payload = 2B company_id + 15B C3 header (0:0xC3, 1:ver=1, 2..4:run_id, 4..8:slot_u32, ...) + chunk
    by_slot_idx: dict[int, list[int]] = {}
    for i, pkt in enumerate(ble_packets):
        _, raw = _ble_ad_data(pkt)
        slot = struct.unpack_from("<I", raw, 2 + 4)[0]
        by_slot_idx.setdefault(slot, []).append(i)
    slots_sorted = sorted(by_slot_idx)
    if len(slots_sorted) < 2:
        raise ValueError("C3 fault suite requires at least 2 recorded slots")
    s0, s1 = slots_sorted[0], slots_sorted[1]
    s0_idxs = by_slot_idx[s0]
    s1_idxs = by_slot_idx[s1]

    # 2. Bad app CRC on last fragment of first recorded slot
    pkts_bad_crc = deepcopy(ble_packets)
    last_i = s0_idxs[-1]
    _, last_raw = _ble_ad_data(pkts_bad_crc[last_i])
    pkts_bad_crc[last_i] = _flip_ble_ad_byte(pkts_bad_crc[last_i], len(last_raw) - 1, 0x01)
    r_crc = _run_c3_stream(pkts_bad_crc, run_id, layout)
    cases.append({
        "case_id": "c3_bad_app_crc",
        "synthetic_injection": True,
        "description": f"Flip 1 bit in final C3 fragment payload of recorded slot {s0} (corrupts reassembled UC1 app_crc16)",
        "passed": (
            r_crc["valid_records"] == expected_records - 1
            and s0 not in r_crc["valid_slots"]
            and s1 in r_crc["valid_slots"]
            and r_crc["invalid_reasons"].get("c3_fragment_record:app_crc16", 0) == 1
        ),
        "metrics": r_crc,
    })

    # 3. Conflicting duplicate fragment in slot s0 must isolate slot s0 without blocking slot s1
    pkts_conflict = deepcopy(ble_packets)
    # Chunk bytes start at raw[2 + 15] = raw[17]
    dup_conflict = _flip_ble_ad_byte(pkts_conflict[s0_idxs[0]], 2 + 15, 0xFF)
    pkts_conflict.insert(s0_idxs[0] + 1, dup_conflict)
    r_conf = _run_c3_stream(pkts_conflict, run_id, layout)
    cases.append({
        "case_id": "c3_slot_conflict_isolation",
        "synthetic_injection": True,
        "description": f"Insert conflicting duplicate fragment 0 in slot {s0}; verify slot {s0} closes as conflict while retry slot {s1} completes",
        "passed": (
            r_conf["valid_records"] == expected_records - 1
            and s0 not in r_conf["valid_slots"]
            and s1 in r_conf["valid_slots"]
            and r_conf["extractor_counts"].get("conflict", 0) == 1
            and r_conf["invalid_reasons"].get("c3_fragment_conflict", 0) == 1
            and r_conf["unique_commands"] == base["unique_commands"]
        ),
        "metrics": r_conf,
    })

    # 4. Replace one fragment from slot s0 with the same-index fragment from
    # slot s1. Both C3 headers retain their original slot identities.
    pkts_cross = deepcopy(ble_packets)
    original = pkts_cross[s0_idxs[1]]
    injected = deepcopy(pkts_cross[s1_idxs[1]])
    injected["sample_time_s"] = original["sample_time_s"]
    injected["sample_start"] = original["sample_start"]
    injected["available_sample"] = original["available_sample"]
    pkts_cross[s0_idxs[1]] = injected
    r_cross = _run_c3_stream(pkts_cross, run_id, layout)
    cases.append({
        "case_id": "c3_cross_slot_fragment_no_assembly",
        "synthetic_injection": True,
        "description": f"Replace slot {s0} fragment 1 with slot {s1} fragment 1 at the same IQ position; verify slot identities never merge",
        "passed": (
            r_cross["valid_records"] == expected_records - 1
            and set(r_cross["valid_slots"]) == set(base["valid_slots"]) - {s0}
            and r_cross["unique_commands"] == base["unique_commands"]
            and r_cross["capacity_invariant_ok"]
        ),
        "metrics": r_cross,
    })

    # 5. pending_overflow (pending_limit=1): interleave fragment 0 of slot s1 before slot s0 finishes
    pkts_ovf = deepcopy(ble_packets)
    f1_0 = pkts_ovf.pop(s1_idxs[0])
    f1_0["sample_time_s"] = pkts_ovf[s0_idxs[0]]["sample_time_s"] + 0.0005
    pkts_ovf.insert(s0_idxs[0] + 1, f1_0)
    r_ovf = _run_c3_stream(pkts_ovf, run_id, layout, pending_limit=1, closed_limit=64)
    cases.append({
        "case_id": "c3_pending_overflow_no_eviction",
        "synthetic_injection": True,
        "description": f"Interleave slot {s1} frag 0 while slot {s0} pending with pending_limit=1; verify slot {s0} completes without eviction and slot {s1} tombstoned",
        "passed": (
            r_ovf["valid_records"] == expected_records - 1
            and s0 in r_ovf["valid_slots"]
            and s1 not in r_ovf["valid_slots"]
            and r_ovf["extractor_counts"].get("pending_overflow", 0) >= 1
            and r_ovf["capacity_invariant_ok"]
        ),
        "metrics": r_ovf,
    })

    # 6. closed_capacity_exhausted (closed_limit=2): stop admitting after 2 identities, never evict closed
    r_closed = _run_c3_stream(ble_packets, run_id, layout, pending_limit=4, closed_limit=2)
    cases.append({
        "case_id": "c3_closed_capacity_exhausted",
        "synthetic_injection": True,
        "description": "Replay unmodified recorded C3 stream with closed_limit=2; verify hard stop at 2 identities and invariant len(closed)+len(pending)<=2",
        "passed": (
            r_closed["valid_records"] == 2
            and r_closed["closed_exhausted"] is True
            and r_closed["extractor_counts"].get("closed_capacity_exhausted", 0) > 0
            and r_closed["closed_count"] == 2
            and r_closed["capacity_invariant_ok"]
        ),
        "metrics": r_closed,
    })

    # 7. Time regression on fragment 1 of slot s0
    pkts_reg = deepcopy(ble_packets)
    pkts_reg[s0_idxs[1]]["sample_time_s"] = pkts_reg[s0_idxs[0]]["sample_time_s"] - 1.0
    r_reg = _run_c3_stream(pkts_reg, run_id, layout)
    cases.append({
        "case_id": "c3_time_regression",
        "synthetic_injection": True,
        "description": f"Inject -1.0 s sample_time_s regression on fragment 1 of recorded slot {s0}; verify fragment_time_order rejection",
        "passed": (
            r_reg["invalid_reasons"].get("fragment_time_order", 0) == 1
            and r_reg["extractor_counts"].get("time_regression", 0) == 1
            and s0 not in r_reg["valid_slots"]
            and r_reg["valid_records"] == expected_records - 1
        ),
        "metrics": r_reg,
    })

    return cases


def _feed_engine(
    packets: list[dict],
    side: str,
    cfg: dict,
    *,
    sample_rate: float = 4_000_000.0,
    ref_bound_ms: float | None = None,
    layout_override: dict | None = None,
) -> dict:
    run_id = cfg["run_id"]
    target_id = 1 if side == "ble" else 2
    use_cfg = deepcopy(cfg)
    if layout_override is not None:
        use_cfg["layout"] = layout_override
    eng = SideControlEngine(
        EngineConfig(
            side=side,
            run_id=run_id,
            sample_rate=int(sample_rate),
            target_ids=frozenset({target_id}),
            uc1_config=use_cfg,
            external_reference_bound_ms=ref_bound_ms,
        )
    )
    events: list[dict] = []
    last_avail = 0
    for pkt in packets:
        raw = extract_ble(pkt) if side == "ble" else extract_zigbee(pkt)
        if raw is None:
            continue
        s_start = float(pkt["sample_start"])
        avail = int(pkt.get("available_sample", int(s_start) + 4096))
        last_avail = max(last_avail, avail)
        events.extend(eng.observe(raw, s_start, avail))
    # Advance 10 s beyond last packet to flush any pending scheduled tasks
    events.extend(eng.advance(last_avail + int(10 * sample_rate)))

    by_event: dict[str, int] = {}
    reject_reasons: dict[str, int] = {}
    invalid_reasons: dict[str, int] = {}
    processed_cmds = []
    for ev in events:
        name = ev["event"]
        by_event[name] = by_event.get(name, 0) + 1
        if name == "rejected":
            r = ev.get("reason", "unknown")
            reject_reasons[r] = reject_reasons.get(r, 0) + 1
        elif name == "invalid_record":
            r = ev.get("reason", "unknown")
            invalid_reasons[r] = invalid_reasons.get(r, 0) + 1
        elif name == "software_processed":
            processed_cmds.append(ev.get("command_id"))
    return {
        "clock_state": eng.clock.state,
        "clock_version": eng.clock.version,
        "event_counts": by_event,
        "reject_reasons": reject_reasons,
        "invalid_reasons": invalid_reasons,
        "processed_commands": sorted(processed_cmds),
        "task_statuses": {str(cid): t.status for cid, t in sorted(eng.tasks.items())},
    }


def run_time_fault_suite(cfg: dict, ble_packets: list[dict], zig_packets: list[dict]) -> list[dict]:
    cases = []

    # 1. Baseline replay with ref_bound_ms=None (proves safety gate: tracking + probes work, 0 timed processing)
    b_base = _feed_engine(ble_packets, "ble", cfg, ref_bound_ms=None)
    z_base = _feed_engine(zig_packets, "zigbee", cfg, ref_bound_ms=None)
    cases.append({
        "case_id": "time_baseline_unknown_bound_safety_gate",
        "synthetic_injection": False,
        "description": "Replay unmodified recorded time-profile BLE/IEEE streams with unknown reference bound; verify tracking & probes succeed while timed processing stays 0",
        "passed": (
            b_base["clock_version"] > 0
            and z_base["clock_version"] > 0
            and b_base["event_counts"].get("probe_score", 0) == len(cfg["probes"])
            and z_base["event_counts"].get("probe_score", 0) == len(cfg["probes"])
            and len(b_base["processed_commands"]) == 0
            and len(z_base["processed_commands"]) == 0
        ),
        "metrics": {"ble": b_base, "zigbee": z_base},
    })

    # 2. Wrong configured layout on BLE (ble_extra=0 vs recorded b=26)
    wrong_layout = deepcopy(cfg["layout"])
    wrong_layout["ble_extra"] = 0 if cfg["layout"]["ble_extra"] != 0 else 26
    wrong_layout["ble_record_bytes"] = 26 + wrong_layout["ble_extra"]
    wrong_layout["marker_offset_us"] = 400 + 8 * wrong_layout["ble_extra"]
    b_wrong = _feed_engine(ble_packets, "ble", cfg, ref_bound_ms=1.0, layout_override=wrong_layout)
    expected_cmd_attempts = sum(int(t["attempts"]) for t in cfg["tasks"])
    cases.append({
        "case_id": "time_wrong_layout_rejection",
        "synthetic_injection": True,
        "description": f"Replay recorded BLE stream (b={cfg['layout']['ble_extra']}) under mismatched configured layout (b={wrong_layout['ble_extra']}); verify clock_skipped on all packets and timing_layout_unavailable rejection on all command attempts",
        "passed": (
            b_wrong["clock_version"] == 0
            and b_wrong["event_counts"].get("accepted", 0) == 0
            and len(b_wrong["processed_commands"]) == 0
            and b_wrong["event_counts"].get("clock_skipped", 0) == len(ble_packets)
            and b_wrong["reject_reasons"].get("timing_layout_unavailable", 0) == expected_cmd_attempts
        ),
        "metrics": b_wrong,
    })

    # Locate command 1's first and second attempt packet indices on each side
    cmd1_task = cfg["tasks"][0]
    cmd1_id = cmd1_task["command_id"]
    slot_a0 = cmd1_task["first_slot"]
    slot_a1 = slot_a0 + 1

    def _find_slot_idx(pkts: list[dict], side: str, target_slot: int) -> int:
        for i, p in enumerate(pkts):
            raw = extract_ble(p) if side == "ble" else extract_zigbee(p)
            if raw is None:
                continue
            rec = uc1_record(raw, side, layout=cfg["layout"])
            if rec["slot_index"] == target_slot and rec["command_id"] == cmd1_id:
                return i
        raise ValueError(f"slot {target_slot} for command {cmd1_id} not found on {side}")

    b_i0 = _find_slot_idx(ble_packets, "ble", slot_a0)
    b_i1 = _find_slot_idx(ble_packets, "ble", slot_a1)
    z_i0 = _find_slot_idx(zig_packets, "zigbee", slot_a0)
    z_i1 = _find_slot_idx(zig_packets, "zigbee", slot_a1)

    # 3. Bad app CRC on command 1 attempt 0 (both sides): rejected as app_crc16, retry still recovers
    b_crc_pkts = deepcopy(ble_packets)
    b_crc_pkts[b_i0] = _flip_ble_ad_byte(b_crc_pkts[b_i0], 2 + 17, 0x01)
    z_crc_pkts = deepcopy(zig_packets)
    z_crc_pkts[z_i0] = _flip_zigbee_payload_byte(z_crc_pkts[z_i0], 17, 0x01)
    b_crc = _feed_engine(b_crc_pkts, "ble", cfg, ref_bound_ms=1.0)
    z_crc = _feed_engine(z_crc_pkts, "zigbee", cfg, ref_bound_ms=1.0)
    cases.append({
        "case_id": "time_bad_app_crc_retry_recovery",
        "synthetic_injection": True,
        "description": f"Corrupt 1 bit in command {cmd1_id} attempt 0 (slot {slot_a0}) on BLE & IEEE; verify app_crc16 rejection and clean retry recovery on attempt 1 (slot {slot_a1}) under synthetic ref_bound_ms=1.0",
        "passed": (
            b_crc["invalid_reasons"].get("app_crc16", 0) == 1
            and z_crc["invalid_reasons"].get("app_crc16", 0) == 1
            and cmd1_id in b_crc["processed_commands"]
            and cmd1_id in z_crc["processed_commands"]
        ),
        "metrics": {"ble": b_crc, "zigbee": z_crc},
    })

    # 4. Conflicting task on command 1 attempt 1 (valid CRC, mutated arg): cancels pending task 1, blocks attempt 2
    b_conf_pkts = deepcopy(ble_packets)
    b_ad, b_raw = _ble_ad_data(b_conf_pkts[b_i1])
    b_rec_len = cfg["layout"]["ble_record_bytes"]
    b_rec_mut = _mutate_uc1_arg_valid_crc(b_raw[2:2 + b_rec_len], (cmd1_task["ble_arg"] + 1) & 0xFFFF)
    b_ad["data_hex"] = (b_raw[:2] + b_rec_mut + b_raw[2 + b_rec_len:]).hex()

    z_conf_pkts = deepcopy(zig_packets)
    z_raw = bytes.fromhex(z_conf_pkts[z_i1]["payload_hex"])
    z_conf_pkts[z_i1]["payload_hex"] = _mutate_uc1_arg_valid_crc(z_raw, (cmd1_task["zigbee_arg"] + 1) & 0xFFFF).hex()

    b_conf = _feed_engine(b_conf_pkts, "ble", cfg, ref_bound_ms=1.0)
    z_conf = _feed_engine(z_conf_pkts, "zigbee", cfg, ref_bound_ms=1.0)
    cases.append({
        "case_id": "time_conflicting_task_cancels_pending",
        "synthetic_injection": True,
        "description": f"Mutate arg (with valid recomputed CRC) on command {cmd1_id} attempt 1 (slot {slot_a1}); verify task {cmd1_id} is cancelled and attempt 2 cannot resurrect it (synthetic ref_bound_ms=1.0)",
        "passed": (
            b_conf["task_statuses"].get(str(cmd1_id)) == "cancelled"
            and z_conf["task_statuses"].get(str(cmd1_id)) == "cancelled"
            and cmd1_id not in b_conf["processed_commands"]
            and cmd1_id not in z_conf["processed_commands"]
            and b_conf["reject_reasons"].get("conflicting_task", 0) >= 2
            and z_conf["reject_reasons"].get("conflicting_task", 0) >= 2
            and len(b_conf["processed_commands"]) == len(cfg["tasks"]) - 1
            and len(z_conf["processed_commands"]) == len(cfg["tasks"]) - 1
        ),
        "metrics": {"ble": b_conf, "zigbee": z_conf},
    })

    return cases


def run_h6_replay(experiment_dir: Path, config_path: Path, output_dir: Path) -> dict:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty analysis directory: {output_dir}")
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    validate_uc1_config(cfg, cfg["run_id"])
    ble_path = discover(experiment_dir, "ble")
    zig_path = discover(experiment_dir, "zigbee")
    if ble_path is None or zig_path is None:
        raise FileNotFoundError(f"missing complete BLE/ZigBee packet captures under {experiment_dir}")

    ble_packets = _load_jsonl(ble_path)
    zig_packets = _load_jsonl(zig_path)

    cases: list[dict] = []
    suites_run: list[str] = []
    if cfg["mode"] == "LC" and cfg["layout"]["ble_fragments_per_attempt"] > 1:
        suites_run.append("c3_fragment_reassembly")
        cases.extend(run_c3_fault_suite(cfg, ble_packets))
    if cfg["profile"] == "time":
        suites_run.append("time_profile_engine")
        cases.extend(run_time_fault_suite(cfg, ble_packets, zig_packets))
    if not suites_run:
        raise ValueError(f"no H6 replay suite defined for mode={cfg['mode']} profile={cfg['profile']} frags={cfg['layout']['ble_fragments_per_attempt']}")

    passed_n = sum(1 for c in cases if c["passed"])
    summary = {
        "schema": "b2z_uc1_h6_fault_injection_replay_v1",
        "evidence_type": "offline_fault_injection_replay_on_recorded_packets",
        "disclaimer": (
            "Synthetic fault injections applied in memory to copies of real recorded packets; "
            "raw captures are untouched. Not live RF fault evidence."
        ),
        "run_id": cfg["run_id"],
        "mode": cfg["mode"],
        "profile": cfg["profile"],
        "point": cfg["point"],
        "suites": suites_run,
        "sources": {
            "config": {"path": str(config_path.resolve()), "sha256": _sha256(config_path)},
            "ble_packets": {"path": str(ble_path.resolve()), "sha256": _sha256(ble_path), "rows": len(ble_packets)},
            "zigbee_packets": {"path": str(zig_path.resolve()), "sha256": _sha256(zig_path), "rows": len(zig_packets)},
        },
        "overall": {"passed": passed_n, "total": len(cases), "all_passed": passed_n == len(cases)},
        "cases": cases,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "h6.summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with (output_dir / "h6.cases.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["case_id", "synthetic_injection", "passed", "description"])
        w.writeheader()
        for c in cases:
            w.writerow({
                "case_id": c["case_id"],
                "synthetic_injection": c["synthetic_injection"],
                "passed": c["passed"],
                "description": c["description"],
            })

    lines = [
        f"# UC1 H6 实录流离线故障注入回放报告（Run {cfg['run_id']}）",
        "",
        f"- **证据类型**：`offline_fault_injection_replay_on_recorded_packets`（在真实录制包副本的内存中执行确定性故障注入；未修改任何原始录制文件，不代表空口实测异常）",
        f"- **基线实录**：`run_id={cfg['run_id']}`，`mode={cfg['mode']}`，`profile={cfg['profile']}`，`point={cfg['point']}`（BLE `{len(ble_packets)}` 行，IEEE `{len(zig_packets)}` 行）",
        f"- **总计通过**：`{passed_n}/{len(cases)}`",
        "",
        "| Case ID | Synthetic Injection | Passed | Description |",
        "| --- | --- | --- | --- |",
    ]
    for c in cases:
        lines.append(f"| `{c['case_id']}` | `{c['synthetic_injection']}` | `{'PASS' if c['passed'] else 'FAIL'}` | {c['description']} |")
    lines.append("")
    (output_dir / "h6.report.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline H6 fault-injection replay on recorded UC1/C3 streams.")
    ap.add_argument("--experiment-dir", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--analysis-id", default="h6_fault_injection_replay")
    args = ap.parse_args()
    out_dir = args.experiment_dir / "analyses" / args.analysis_id
    summary = run_h6_replay(args.experiment_dir, args.config, out_dir)
    print(json.dumps({
        "run_id": summary["run_id"],
        "suites": summary["suites"],
        "overall": summary["overall"],
        "output": str(out_dir),
    }, ensure_ascii=False))
    return 0 if summary["overall"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

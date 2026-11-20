"""Comprehensive P1 tests for UC1/C3 host decoding, reassembly, online bridge, and analysis."""
from __future__ import annotations

import binascii
from copy import deepcopy
import ctypes as C
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.signal import resample_poly

import python.perf_test.tests.test_b2z_control_generator as _gen
from python.perf_test.tests.test_compact_generator import CompactMeta
from python.perf_test.tests.test_bluebee_gen_waveform import iq_complex
Packet = _gen.Packet
from python.exadv_rx.decoder import ChannelDecoder
from python.zigbee_rx.tests.test_zigbee_receiver import decode as decode_zigbee
from python.zigbee_rx.control_receive import ControlTracker
from python.control_match.compact import BLEControlExtractor, uc1_extension, uc1_record, compact_record
from python.control_match.protocol import control_record, ble_manufacturer_record
from python.control_match.control_engine import EngineConfig, SideControlEngine
from python.control_match.immediate_engine import ImmediateControlEngine
from python.control_match.uc1_config import (
    dry_run_cost_table,
    export_commands,
    generate as generate_uc1_config,
    load as load_uc1_config,
    uc1_burst_table,
    uc1_cost,
    validate as validate_uc1_config,
)
from python.control_match.plan_analyze import read_plan, summarize
from python.control_match.uc1_analyze import compare_uc1, run_analysis

REPO_ROOT = Path(__file__).resolve().parents[3]


def build_uc1_wire(
    *,
    run_id: int = 2701,
    slot: int = 10,
    period_ms: int = 500,
    command_id: int = 1,
    target_id: int = 1,
    opcode: int = 1,
    arg: int = 1,
    valid_offset_ms: int = 2500,
    execute_offset_ms: int = 3000,
    extra: bytes = b"",
    ver_type: int | None = None,
) -> bytes:
    """Independently construct a UC1 wire record (cross-checks C generator)."""
    vt = (0x11 if command_id else 0x10) if ver_type is None else ver_type
    buf = bytearray()
    buf.append(0xC1)
    buf.append(vt)
    buf += run_id.to_bytes(2, "little")
    buf += slot.to_bytes(4, "little")
    buf += period_ms.to_bytes(2, "little")
    buf += command_id.to_bytes(4, "little")
    buf += target_id.to_bytes(2, "little")
    buf.append(opcode)
    buf += arg.to_bytes(2, "little")
    buf += valid_offset_ms.to_bytes(2, "little")
    buf += execute_offset_ms.to_bytes(2, "little")
    buf.append(len(extra))
    buf += extra
    buf += binascii.crc_hqx(bytes(buf), 0xFFFF).to_bytes(2, "little")
    return bytes(buf)


def build_c3_packets(
    record: bytes,
    *,
    run_id: int,
    slot: int,
    command_id: int,
    adva: str = "aa:bb:cc:dd:ee:ff",
    t0: float = 0.1,
    dt: float = 0.005,
    sample_rate: int = 4000000,
) -> list[dict]:
    """Independently construct legacy BLE packets carrying C3 fragments of `record`."""
    total = len(record)
    count = (total + 11) // 12
    out = []
    for idx in range(count):
        chunk = record[idx * 12 : (idx + 1) * 12]
        hdr = bytearray([0xC3, 1])
        hdr += run_id.to_bytes(2, "little")
        hdr += slot.to_bytes(4, "little")
        hdr += command_id.to_bytes(4, "little")
        hdr += bytes([idx, count, total])
        payload = b"\xff\xff" + bytes(hdr) + chunk
        t = t0 + idx * dt
        sample = t * sample_rate
        out.append(
            {
                "kind": "legacy",
                "crc_ok": True,
                "pdu_length": 6 + 2 + len(payload),
                "sample_start": sample,
                "available_sample": int(sample) + 4096,
                "sample_time_s": t,
                "extended": {
                    "adva": adva,
                    "ad_structures": [
                        {"type": 255, "company_id": 0xFFFF, "data_hex": payload.hex()}
                    ],
                },
            }
        )
    return out


def make_synthetic_uc1_board_log(cfg: dict, *, failed_slots: set[int] | None = None) -> str:
    """Emit a spec-faithful board log matching bluebee_perf.c UC1 output format."""
    failed = failed_slots or set()
    run_id = cfg["run_id"]
    mode_code = cfg["mode_code"]
    profile_code = cfg["profile_code"]
    layout = cfg["layout"]
    b, z = layout["ble_extra"], layout["ieee_extra"]
    k = cfg["k"]
    period = cfg["period_ms"]
    total_slots = cfg["planned_slots"]
    cost = cfg["cost_per_attempt_us"]
    bursts_spec = uc1_burst_table(b, z, mode_code)

    slot_to_task = {}
    for idx, t in enumerate(cfg["tasks"]):
        for s in range(t["first_slot"], t["first_slot"] + t["attempts"]):
            slot_to_task[s] = (idx, t)

    active_slots = set(range(total_slots)) if profile_code == 1 else set(slot_to_task)
    generated = sum(1 for s in active_slots)
    completed_attempts = sum(1 for s in active_slots if s not in failed)
    failed_attempts = sum(1 for s in active_slots if s in failed)
    primary_completed = 0 if mode_code == 3 else completed_attempts
    tx_completed = completed_attempts
    dma_timeout = failed_attempts

    lines = [
        (
            f"UC1_CONFIG run_id={run_id} version=1 mode={mode_code} profile={profile_code} "
            f"tasks={cfg['tasks_count']} slots={total_slots} k={k} budget_us={cfg['budget_us']} "
            f"cost_per_attempt_us={cost} unused_per_task_us={cfg['unused_per_task_us']} "
            f"ble_extra={b} ieee_extra={z} period_ms={period} "
            f"marker_offset_us={layout['marker_offset_us'] if layout['marker_offset_valid'] else 0} "
            f"marker_offset_valid={1 if layout['marker_offset_valid'] else 0} "
            f"reference_epoch_offset_us={layout['reference_epoch_offset_us']} "
            f"fill=lcg_uc1_command_seed reference=planned_not_rf"
        ),
        (
            f"CONTROL_PLAN_STATS final=1 state=complete run_id={run_id} period_ms={period} "
            f"tasks={cfg['tasks_count']} planned_slots={total_slots} reached_slots={total_slots} "
            f"generated={generated} primary_started={primary_completed} primary_completed={primary_completed} "
            f"tx_started={generated} tx_completed={tx_completed} deadline_miss=0 dma_timeout={dma_timeout} "
            f"rf_mode={layout['rf_mode']}"
        ),
        (
            f"UC1_STATS run_id={run_id} planned_attempts={cfg['planned_attempts']} "
            f"processed_attempts={generated} completed_attempts={completed_attempts} "
            f"failed_attempts={failed_attempts} planned_silent_slots={cfg['planned_silent_slots']} "
            f"planned_air_us={cfg['planned_waveform_us']} completion=dma_all_bursts_and_restore"
        ),
    ]
    for idx, t in enumerate(cfg["tasks"]):
        t_slots = list(range(t["first_slot"], t["first_slot"] + t["attempts"]))
        t_ok = sum(1 for s in t_slots if s not in failed)
        t_fail = len(t_slots) - t_ok
        t_prim = 0 if mode_code == 3 else t_ok
        lines.append(
            f"CONTROL_PLAN_TASK run_id={run_id} entry={idx} command_id={t['command_id']} "
            f"first_slot={t['first_slot']} repeats={t['attempts']} reached={t['attempts']} "
            f"generated={t['attempts']} execute_at_ms={t['execute_at_ms']} valid_until_ms={t['valid_until_ms']} "
            f"ble_target={t['ble_target']} ble_opcode={t['ble_opcode']} ble_arg={t['ble_arg']} "
            f"zigbee_target={t['zigbee_target']} zigbee_opcode={t['zigbee_opcode']} zigbee_arg={t['zigbee_arg']} "
            f"primary_started={t_prim} primary_completed={t_prim} tx_started={t['attempts']} "
            f"tx_completed={t_ok} deadline_miss=0 dma_timeout={t_fail} auxptr_dma_window_miss=0"
        )
    for slot in range(total_slots):
        cmd_id = slot_to_task[slot][1]["command_id"] if slot in slot_to_task else 0
        built = 1 if slot in active_slots else 0
        lines.append(
            f"COMPACT_SLOT run_id={run_id} slot={slot} command_id={cmd_id} built={built} "
            f"ble_record_bytes={layout['ble_record_bytes'] if built else 0} "
            f"ieee_record_bytes={layout['ieee_record_bytes'] if built else 0} "
            f"mapped_bytes={layout['mapped_bytes'] if built else 0} "
            f"secondary_payload_bytes={layout['secondary_payload_bytes'] if built else 0}"
        )
    for slot in range(total_slots):
        if slot not in active_slots:
            lines.append(f"CONTROL_PLAN_SLOT run_id={run_id} slot={slot} silent=1 invalid_plan=0")
        else:
            cmd_id = slot_to_task[slot][1]["command_id"] if slot in slot_to_task else 0
            ok = 0 if slot in failed else 1
            prim = 0 if mode_code == 3 else ok
            lines.append(
                f"CONTROL_PLAN_SLOT run_id={run_id} slot={slot} entry={slot} command_id={cmd_id} "
                f"flags=31 generated=1 primary_started={prim} primary_completed={prim} "
                f"tx_started=1 tx_completed={ok} deadline_miss=0 dma_timeout={1 - ok} "
                f"secondary_dma_late_us=0 auxptr_dma_delta_us=0 retune_secondary_us=0 auxptr_dma_window_miss=0"
            )
    b_att = b_st = b_comp = ble_comp = ieee_comp = 0
    for slot in range(total_slots):
        active = slot in active_slots
        ok = active and slot not in failed
        for b_idx, (kind, air) in enumerate(bursts_spec):
            if not active:
                lines.append(
                    f"UC1_BURST run_id={run_id} slot={slot} kind={kind} generated=0 attempted=0 "
                    f"started=0 completed=0 timeout=0 iq_bytes=0 air_us=0 pad_us=0 "
                    f"prepared_us=0 submit_before_us=0 submit_after_us=0 finish_us=0"
                )
            else:
                t_us = slot * period * 1000 + 300000 + b_idx * 5000
                comp = 1 if ok else 0
                tout = 0 if ok else 1
                # If failed on first burst, don't attempt later bursts in sequential modes.
                if not ok and b_idx > 0:
                    lines.append(
                        f"UC1_BURST run_id={run_id} slot={slot} kind={kind} generated=1 attempted=0 "
                        f"started=0 completed=0 timeout=0 iq_bytes=4096 air_us={air} pad_us=10 "
                        f"prepared_us=1 submit_before_us=0 submit_after_us=0 finish_us=0"
                    )
                    continue
                b_att += 1
                b_st += 1
                b_comp += comp
                lines.append(
                    f"UC1_BURST run_id={run_id} slot={slot} kind={kind} generated=1 attempted=1 "
                    f"started=1 completed={comp} timeout={tout} iq_bytes=4096 air_us={air} pad_us=10 "
                    f"prepared_us=1 submit_before_us={t_us} submit_after_us={t_us + 1} finish_us={t_us + 2000}"
                )
        if ok:
            ble_comp += 1
            ieee_comp += 1
    lines.append(
        f"UC1_COST_STATS run_id={run_id} logical_slots={total_slots} ble_tx_completed={ble_comp} "
        f"ieee_tx_completed={ieee_comp} burst_attempted={b_att} burst_started={b_st} "
        f"burst_completed={b_comp} separate_gap_us={1000 if mode_code == 2 else 0} reference=dma_software_brackets"
    )
    return "\n".join(lines) + "\n"


class UC1ProtocolAndC3UnitTests(unittest.TestCase):
    def test_version_isolation_and_record_validation(self):
        # UC1 command (0x11) with arbitrary application payload vs test fill separation
        custom_extra = b"\x01\x02\x03\x04"
        raw = build_uc1_wire(extra=custom_extra)
        rec = control_record(raw, "ble")
        self.assertEqual(rec["wire_format"], "UC1")
        self.assertEqual(rec["wire_version"], 1)
        self.assertEqual(rec["version"], "UC1")
        self.assertEqual(rec["flags"], 1)
        self.assertEqual(rec["extra_hex"], "01020304")
        self.assertFalse(rec["test_fill_ok"])
        self.assertFalse(rec["timing_eligible"])
        self.assertIsNone(rec["ieee_marker_offset_us"])
        with self.assertRaisesRegex(ValueError, "uc1_test_fill"):
            control_record(raw, "ble", verify_test_fill=True)

        # UC1 command with frozen test fill + matching JC layout
        fill = uc1_extension(2701, 1, "ble", 26)
        raw_jc = build_uc1_wire(extra=fill)
        layout = dict(mode="JC", run_id=2701, period_ms=500, ble_extra=26, ieee_extra=0,
                      marker_offset_valid=True, marker_offset_us=400 + 8 * 26)
        rec_jc = control_record(raw_jc, "ble", layout=layout, verify_test_fill=True)
        self.assertTrue(rec_jc["test_fill_ok"])
        self.assertTrue(rec_jc["timing_eligible"])
        self.assertEqual(rec_jc["ieee_marker_offset_us"], 608)

        # Wrong layout -> still decoded, timing_eligible=False (never falls back to 472)
        wrong_layout = dict(layout, ble_extra=2, marker_offset_us=416)
        rec_wrong = control_record(raw_jc, "ble", layout=wrong_layout)
        self.assertFalse(rec_wrong["layout_match"])
        self.assertFalse(rec_wrong["timing_eligible"])
        self.assertIsNone(rec_wrong["ieee_marker_offset_us"])

        # Pure time update (0x10): valid_until_ms = execute_at_ms = 0, zero padding required
        sync_raw = build_uc1_wire(
            slot=5, command_id=0, target_id=0, opcode=0, arg=0,
            valid_offset_ms=0, execute_offset_ms=0, extra=bytes(6), ver_type=0x10,
        )
        sync_rec = control_record(sync_raw, "zigbee", layout=dict(layout, ieee_extra=6))
        self.assertEqual(sync_rec["flags"], 0)
        self.assertEqual(sync_rec["ref_tick_ms"], 2500)
        self.assertEqual(sync_rec["valid_until_ms"], 0)
        self.assertEqual(sync_rec["execute_at_ms"], 0)
        self.assertTrue(sync_rec["timing_eligible"])
        self.assertEqual(sync_rec["ieee_marker_offset_us"], 608)

        # Pure time update with non-zero padding or non-zero command field rejected
        bad_pad = build_uc1_wire(
            slot=5, command_id=0, target_id=0, opcode=0, arg=0,
            valid_offset_ms=0, execute_offset_ms=0, extra=b"\x00\x01", ver_type=0x10,
        )
        with self.assertRaisesRegex(ValueError, "uc1_sync_padding_nonzero"):
            control_record(bad_pad, "ble")

        # Command type 0x11 with all-zero fields rejected (no implicit type change)
        bad_implicit = build_uc1_wire(
            slot=5, command_id=0, target_id=0, opcode=0, arg=0,
            valid_offset_ms=0, execute_offset_ms=0, extra=b"", ver_type=0x11,
        )
        with self.assertRaisesRegex(ValueError, "uc1_command_semantics"):
            control_record(bad_implicit, "ble")

        # Unknown version_type rejected
        for vt in (0x00, 0x02, 0x12, 0x20, 0xFF):
            bad_vt = build_uc1_wire(ver_type=vt)
            with self.assertRaisesRegex(ValueError, "unknown_c1_version_type"):
                control_record(bad_vt, "ble")

        # Historical C1 01 stays isolated as version=3 (not UC1)
        from python.control_match.protocol import capacity_extension
        hist_c1 = build_uc1_wire(slot=0, command_id=1, extra=capacity_extension(2701, 0, "ble", 2), ver_type=0x01)
        hist_rec = control_record(hist_c1, "ble")
        self.assertEqual(hist_rec["version"], 3)
        self.assertEqual(hist_rec["wire_format"], "C1")

        # uint32 ref overflow and time bound overflow rejected
        overflow_ref = build_uc1_wire(slot=9_000_000, period_ms=500)
        with self.assertRaisesRegex(ValueError, "uc1_ref_overflow"):
            control_record(overflow_ref, "ble")
        overflow_exec = build_uc1_wire(slot=8_589_934, period_ms=500, valid_offset_ms=500, execute_offset_ms=1000)
        with self.assertRaisesRegex(ValueError, "uc1_time_bounds"):
            control_record(overflow_exec, "ble")

        # Bad CRC and truncation rejected
        corrupted = bytearray(raw)
        corrupted[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "app_crc16"):
            control_record(bytes(corrupted), "ble")
        with self.assertRaisesRegex(ValueError, "uc1_length"):
            control_record(raw[:-1], "ble")

    def test_ble_manufacturer_envelope_jc_and_sc(self):
        rec = build_uc1_wire(extra=uc1_extension(2701, 10, "ble", 26))
        # JC: 2 + 52 + 136 = 190 B manufacturer data -> pdu_length = 205
        jc_ad = b"\xff\xff" + rec + bytes(136)
        self.assertEqual(ble_manufacturer_record(jc_ad, 205), rec)
        # SC (BLE-only): 2 + 52 = 54 B manufacturer data -> pdu_length = 69 (43 + 26)
        sc_ad = b"\xff\xff" + rec
        self.assertEqual(ble_manufacturer_record(sc_ad, 69), rec)
        # Wrong pdu_length rejected
        with self.assertRaisesRegex(ValueError, "uc1_wire_budget"):
            ble_manufacturer_record(sc_ad, 70)

    def test_c3_cross_attempt_isolation_and_independent_pending_closed_limits(self):
        # Two retries of SAME task (command_id=1) at slot 10 and slot 11 interleaved
        extra = uc1_extension(2701, 1, "ble", 26)
        rec10 = build_uc1_wire(slot=10, command_id=1, valid_offset_ms=2500, execute_offset_ms=3000, extra=extra)
        rec11 = build_uc1_wire(slot=11, command_id=1, valid_offset_ms=2000, execute_offset_ms=2500, extra=extra)
        p10 = build_c3_packets(rec10, run_id=2701, slot=10, command_id=1, t0=0.10, dt=0.01)
        p11 = build_c3_packets(rec11, run_id=2701, slot=11, command_id=1, t0=0.105, dt=0.01)
        self.assertEqual(len(p10), 5)

        # Interleave reversed order + identical duplicate fragment
        stream = sorted(p10 + p11 + [deepcopy(p10[2])], key=lambda x: x["sample_time_s"])
        for i, pkt in enumerate(stream):
            pkt["sample_time_s"] = 0.1 + i * 0.005
        ex = BLEControlExtractor(timeout=2.0, pending_limit=4, closed_limit=10, allowed_run_id=2701)
        decoded = [out for pkt in stream if (out := ex(pkt)) is not None]
        self.assertEqual(len(decoded), 2)
        self.assertEqual({control_record(d, "ble")["slot_index"] for d in decoded}, {10, 11})
        self.assertEqual({control_record(d, "ble")["valid_until_ms"] for d in decoded}, {7500})
        self.assertEqual(ex.counts["duplicate"], 1)
        self.assertEqual(ex.counts["complete"], 2)

        # Replaying a fragment of already-closed slot 10 -> closed_duplicate, never reopens
        late_dup = deepcopy(p10[0])
        late_dup["sample_time_s"] = 0.5
        self.assertIsNone(ex(late_dup))
        self.assertEqual(ex.counts["closed_duplicate"], 1)
        self.assertEqual(len(ex.pending), 0)

        # Conflict in slot 10 closes slot 10 but DOES NOT block slot 11 of the same task
        ex2 = BLEControlExtractor(timeout=2.0, pending_limit=4, closed_limit=10, allowed_run_id=2701)
        self.assertIsNone(ex2(p10[0]))
        bad = deepcopy(p10[0])
        bad["sample_time_s"] = 0.12
        ad = bad["extended"]["ad_structures"][0]
        raw = bytearray.fromhex(ad["data_hex"])
        raw[-1] ^= 1
        ad["data_hex"] = raw.hex()
        with self.assertRaisesRegex(ValueError, "c3_fragment_conflict"):
            ex2(bad)
        self.assertEqual(ex2.counts["conflict"], 1)
        # Slot 11 still succeeds cleanly
        out11 = []
        for i, pkt in enumerate(deepcopy(p11)):
            pkt["sample_time_s"] = 0.2 + i * 0.01
            res = ex2(pkt)
            if res is not None:
                out11.append(res)
        self.assertEqual(len(out11), 1)
        self.assertEqual(control_record(out11[0], "ble")["slot_index"], 11)

        # pending_overflow: pending_limit=1, closed_limit=3 -> slot 10 admitted, slot 11 rejected & tombstoned, slot 10 NOT evicted!
        ex3 = BLEControlExtractor(timeout=2.0, pending_limit=1, closed_limit=3, allowed_run_id=2701)
        self.assertIsNone(ex3(p10[0]))
        self.assertIsNone(ex3(p11[0]))
        self.assertEqual(ex3.counts["pending_overflow"], 1)
        self.assertEqual(len(ex3.pending), 1)
        self.assertEqual(len(ex3.closed), 1)
        # Slot 10 finishes normally without eviction
        done = [ex3(pkt) for pkt in p10[1:]]
        self.assertIsNotNone(done[-1])
        self.assertEqual(len(ex3.closed), 2)
        # Slot 11 tombstone prevents resurrection even now that pending is empty!
        p11_later = deepcopy(p11[1])
        p11_later["sample_time_s"] = 0.5
        self.assertIsNone(ex3(p11_later))
        self.assertEqual(ex3.counts["closed_duplicate"], 1)

        # closed_capacity_exhausted: pending_limit=4, closed_limit=2 -> 2 admitted (reserving both closed slots), 3rd refused; existing 2 finish!
        ex4 = BLEControlExtractor(timeout=2.0, pending_limit=4, closed_limit=2, allowed_run_id=2701)
        rec12 = build_uc1_wire(slot=12, command_id=1, valid_offset_ms=1500, execute_offset_ms=2000, extra=extra)
        p12 = build_c3_packets(rec12, run_id=2701, slot=12, command_id=1, t0=0.11, dt=0.01)
        self.assertIsNone(ex4(p10[0]))
        self.assertIsNone(ex4(p11[0]))
        self.assertIsNone(ex4(p12[0]))
        self.assertTrue(ex4.closed_exhausted)
        self.assertEqual(ex4.counts["closed_capacity_exhausted"], 1)
        # Invariant len(closed) + len(pending) <= closed_limit holds strictly
        self.assertLessEqual(len(ex4.closed) + len(ex4.pending), 2)
        # Both pre-reserved pending attempts finish cleanly
        for pkt in p10[1:]:
            pkt = deepcopy(pkt)
            pkt["sample_time_s"] += 0.2
            ex4(pkt)
        for pkt in p11[1:]:
            pkt = deepcopy(pkt)
            pkt["sample_time_s"] += 0.4
            ex4(pkt)
        self.assertEqual(ex4.counts["complete"], 2)
        self.assertEqual(len(ex4.closed), 2)
        # After exhaustion, new unknown identity is STILL rejected (no tombstone eviction!)
        p12_late = deepcopy(p12[0])
        p12_late["sample_time_s"] = 1.0
        self.assertIsNone(ex4(p12_late))
        self.assertEqual(ex4.counts["closed_capacity_exhausted"], 2)

        # Foreign run fragment does not allocate or clear queues
        foreign_rec = build_uc1_wire(run_id=9999, slot=10, command_id=1, extra=extra)
        p_foreign = build_c3_packets(foreign_rec, run_id=9999, slot=10, command_id=1, t0=1.2)
        self.assertIsNone(ex4(p_foreign[0]))
        self.assertEqual(ex4.counts["foreign_run_fragment"], 1)
        self.assertEqual(len(ex4.closed), 2)

        # Time regression raises fragment_time_order
        reg = deepcopy(p10[0])
        reg["sample_time_s"] = 0.01
        with self.assertRaisesRegex(ValueError, "fragment_time_order"):
            ex4(reg)
        self.assertEqual(ex4.counts["time_regression"], 1)

        # C3 fragmentation of pure time update (command_id=0, b=26)
        sync_big = build_uc1_wire(
            slot=7, command_id=0, target_id=0, opcode=0, arg=0,
            valid_offset_ms=0, execute_offset_ms=0, extra=bytes(26), ver_type=0x10,
        )
        p_sync = build_c3_packets(sync_big, run_id=2701, slot=7, command_id=0, t0=0.1, dt=0.01)
        ex5 = BLEControlExtractor(timeout=2.0, pending_limit=4, closed_limit=10, allowed_run_id=2701)
        out_sync = [res for pkt in p_sync if (res := ex5(pkt)) is not None]
        self.assertEqual(len(out_sync), 1)
        self.assertEqual(control_record(out_sync[0], "ble")["flags"], 0)

    def test_online_engine_uc1_bridge_layout_conflict_and_holdover(self):
        cfg = generate_uc1_config(2704, mode="JC", profile="time", ble_extra=26, ieee_extra=0, tasks=6, policy="k", value=3, provenance=False)
        # Missing layout -> decoded with timing_eligible=False, clock skipped, no fallback to 472
        eng_no_layout = SideControlEngine(EngineConfig(
            side="zigbee", run_id=2704, sample_rate=4000000, target_ids=frozenset({2}),
            external_reference_bound_ms=1.0,
        ))
        raw_cmd = build_uc1_wire(run_id=2704, slot=70, period_ms=500, command_id=1, target_id=2, opcode=1, arg=2,
                                 valid_offset_ms=2000, execute_offset_ms=3000)
        evs = eng_no_layout.observe(raw_cmd, 10000.0, 20000)
        self.assertTrue(any(e["event"] == "decoded" and e["timing_eligible"] is False for e in evs))
        self.assertTrue(any(e["event"] == "clock_skipped" and e["reason"] == "layout_missing" for e in evs))
        self.assertTrue(any(e["event"] == "rejected" and e["reason"] == "timing_layout_unavailable" for e in evs))
        self.assertEqual(eng_no_layout.clock.version, 0)

        # Matching JC time profile -> ObservationClock uses 400+8*26=608 us, tracks, goes stale, reacquires
        eng = SideControlEngine(EngineConfig(
            side="zigbee", run_id=2704, sample_rate=4000000, target_ids=frozenset({2}),
            uc1_config=cfg, external_reference_bound_ms=1.0,
        ))
        self.assertEqual(eng.clock.marker_offset_us, 608)
        offset_samples = 4000000 * 608 / 1_000_000
        # Feed 8 odd training slots (1, 3, ..., 15) as pure time updates -> tracking
        for slot in range(1, 16, 2):
            sync = build_uc1_wire(run_id=2704, slot=slot, period_ms=500, command_id=0, target_id=0,
                                  opcode=0, arg=0, valid_offset_ms=0, execute_offset_ms=0, ver_type=0x10)
            s_start = slot * 2_000_000 + offset_samples
            evs = eng.observe(sync, s_start, int(s_start) + 4000)
        self.assertEqual(eng.clock.state, "tracking")

        # Command 1 at slot 70 (first attempt) accepted; slot 71 (retry, odd candidate!) updates clock WITHOUT re-processing command 1!
        for slot in range(17, 70, 2):
            if slot in cfg["probes"]:
                continue
            sync = build_uc1_wire(run_id=2704, slot=slot, period_ms=500, command_id=0, target_id=0,
                                  opcode=0, arg=0, valid_offset_ms=0, execute_offset_ms=0, ver_type=0x10)
            s_start = slot * 2_000_000 + offset_samples
            eng.observe(sync, s_start, int(s_start) + 4000)
        # Held-out probe at slot 69 scored
        probe69 = build_uc1_wire(run_id=2704, slot=69, period_ms=500, command_id=0, target_id=0,
                                 opcode=0, arg=0, valid_offset_ms=0, execute_offset_ms=0, ver_type=0x10)
        p_evs = eng.observe(probe69, 69 * 2_000_000 + offset_samples, 69 * 2_000_000 + int(offset_samples) + 4000)
        scored = [e for e in p_evs if e["event"] == "probe_score"]
        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0]["status"], "scored")
        self.assertAlmostEqual(scored[0]["residual_ms"], 0.0, places=3)

        # Command 1 attempt 1 (slot 70) -> accepted; attempt 2 (slot 71, odd candidate) -> duplicate task BUT clock_updated!
        c70 = build_uc1_wire(run_id=2704, slot=70, period_ms=500, command_id=1, target_id=2, opcode=1, arg=2,
                             valid_offset_ms=2000, execute_offset_ms=3000)
        evs70 = eng.observe(c70, 70 * 2_000_000 + offset_samples, 70 * 2_000_000 + int(offset_samples) + 4000)
        self.assertTrue(any(e["event"] == "accepted" for e in evs70))
        ver_before = eng.clock.version
        c71 = build_uc1_wire(run_id=2704, slot=71, period_ms=500, command_id=1, target_id=2, opcode=1, arg=2,
                             valid_offset_ms=1500, execute_offset_ms=2500)
        evs71 = eng.observe(c71, 71 * 2_000_000 + offset_samples, 71 * 2_000_000 + int(offset_samples) + 4000)
        self.assertTrue(any(e["event"] == "clock_updated" for e in evs71))
        self.assertTrue(any(e["event"] == "duplicate" for e in evs71))
        self.assertEqual(eng.clock.version, ver_before + 1)

        # Conflicting command 1 at slot 72 (different arg) -> rejected without updating clock
        ver_before = eng.clock.version
        c72_bad = build_uc1_wire(run_id=2704, slot=72, period_ms=500, command_id=1, target_id=2, opcode=1, arg=99,
                                 valid_offset_ms=1000, execute_offset_ms=2000)
        evs72 = eng.observe(c72_bad, 72 * 2_000_000 + offset_samples, 72 * 2_000_000 + int(offset_samples) + 4000)
        self.assertTrue(any(e["event"] == "rejected" and e["reason"] == "conflicting_task" for e in evs72))
        self.assertEqual(eng.clock.version, ver_before)

        self.assertEqual(eng.tasks[1].status, "cancelled")
        c73 = build_uc1_wire(run_id=2704, slot=73, command_id=1, target_id=2, arg=2,
                            valid_offset_ms=500, execute_offset_ms=1500)
        after = eng.observe(c73, 73 * 2_000_000 + offset_samples,
                            73 * 2_000_000 + int(offset_samples) + 4000)
        self.assertTrue(any(e.get("reason") == "conflicting_task" for e in after))
        self.assertEqual(eng.clock.version, ver_before)
        self.assertFalse(any(e["event"] == "software_processed" for e in eng.advance(80 * 2_000_000)))
        self.assertEqual(eng.state, {})

        # Immediate baseline supports UC1 (ignores flags=0, processes flags=1 once)
        imm = ImmediateControlEngine(EngineConfig(
            side="zigbee", run_id=2704, sample_rate=4000000, target_ids=frozenset({2}), uc1_config=cfg
        ))
        self.assertTrue(any(e["event"] == "time_update_ignored" for e in imm.observe(probe69, 1000.0, 2000)))
        self.assertTrue(any(e["event"] == "software_processed" for e in imm.observe(c70, 3000.0, 4000)))
        self.assertTrue(any(e["event"] == "duplicate" for e in imm.observe(c71, 5000.0, 6000)))


class UC1ReviewRegressionTests(unittest.TestCase):
    def test_status_snapshots_old_and_new_logs(self):
        cfg = generate_uc1_config(2701, mode="JC", profile="core", ble_extra=0,
                                  ieee_extra=0, tasks=2, policy="k", value=3, provenance=False)
        original = make_synthetic_uc1_board_log(cfg)
        plan_line = next(x for x in original.splitlines() if x.startswith("CONTROL_PLAN_STATS "))
        uc1_line = next(x for x in original.splitlines() if x.startswith("UC1_STATS "))
        snapshot = plan_line.replace("final=1", "final=0").replace("state=complete", "state=running")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "board.log"
            for explicit in (False, True):
                status = uc1_line.replace("UC1_STATS ", "UC1_STATS final=0 ") if explicit else uc1_line
                final = uc1_line.replace("UC1_STATS ", "UC1_STATS final=1 ") if explicit else uc1_line
                text = snapshot + "\n" + status + "\n" + original.replace(uc1_line, final)
                path.write_text(text + "\n" + snapshot + "\n" + status)
                self.assertEqual(read_plan(path, 2701)["uc1_stats"]["completed_attempts"], "6")
                # Terminal duplicates must agree; snapshots must never substitute for a final.
                if explicit:
                    path.write_text(text + "\n" + final)
                    read_plan(path, 2701)
                    path.write_text(text + "\n" + final.replace("completed_attempts=6", "completed_attempts=5"))
                    with self.assertRaisesRegex(ValueError, "conflicting final UC1_STATS"):
                        read_plan(path, 2701)
                    path.write_text(text.replace(final, status))
                    with self.assertRaisesRegex(ValueError, "final UC1_STATS"):
                        read_plan(path, 2701)

    def test_loss_counts_active_attempts_and_time_updates(self):
        cfg = generate_uc1_config(2701, mode="JC", profile="core", ble_extra=0,
                                  ieee_extra=0, tasks=2, policy="k", value=3, provenance=False)
        tracker = ControlTracker(2701, None, cfg["planned_slots"], layout=cfg["layout"], uc1_config=cfg)
        tracker.seen = {s: {"wire_format": "UC1"} for s in tracker.active_slots}
        self.assertEqual(tracker.longest_loss_burst(), 0)
        del tracker.seen[12]
        del tracker.seen[16]
        self.assertEqual(tracker.longest_loss_burst(), 2)
        tracker.seen.clear()
        self.assertEqual(tracker.longest_loss_burst(), 6)
        unknown = ControlTracker(2701, None, None)
        unknown.seen = {10: {"wire_format": "UC1"}, 16: {"wire_format": "UC1"}}
        self.assertIsNone(unknown.longest_loss_burst())
        time_cfg = generate_uc1_config(2702, mode="JC", profile="time", ble_extra=0,
                                       ieee_extra=0, tasks=6, policy="k", value=3, provenance=False)
        time_tracker = ControlTracker(2702, None, None, uc1_config=time_cfg)
        self.assertEqual(len(time_tracker.active_slots), 300)
        filtered = ControlTracker(2702, 1, None, uc1_config=time_cfg)
        self.assertEqual(len(filtered.active_slots), 3)
        updates = ControlTracker(2702, 0, None, uc1_config=time_cfg)
        self.assertEqual(len(updates.active_slots), 282)


class UC1FirmwareWaveformAndCLITests(unittest.TestCase):
    setUpClass = classmethod(_gen.ControlGeneratorTests.setUpClass.__func__)
    tearDownClass = classmethod(_gen.ControlGeneratorTests.tearDownClass.__func__)

    def _gen_iq_and_decode(self, p: Packet, b: int, z: int, mode: int):
        fn = self.lib.b2z_uc1_build
        fn.argtypes = [C.POINTER(Packet), C.c_uint32, C.c_uint32, C.c_uint8]
        self.lib.b2z_compact_get_meta.restype = C.POINTER(CompactMeta)
        self.assertEqual(fn(C.byref(p), b, z, mode), 0)
        m = self.lib.ble_exadv_secondary_gen_get_last_meta().contents
        lc = self.lib.b2z_compact_get_meta().contents
        legacy = mode == 3
        chunks = [np.zeros(4000, np.complex64)]
        buffers = [(lc.iq[i], lc.iq_bytes[i]) for i in range(lc.ble_count)] if legacy else [(m.iq_words, m.iq_byte_count)]
        for ptr, size in buffers:
            iq = iq_complex(np.ctypeslib.as_array(ptr, shape=(size // 4,))[::2])
            chunks.extend([resample_poly(iq, 25, 192).astype(np.complex64), np.zeros(8000, np.complex64)])
        ble_iq = np.concatenate(chunks)
        decoder = ChannelDecoder(4000000, 2480000000 if legacy else 2410000000, 39 if legacy else 3)
        ble_packets = decoder.feed(ble_iq, final=True)
        self.assertEqual(len(ble_packets), len(buffers))
        for pkt in ble_packets:
            pkt["available_sample"] = len(ble_iq)

        if mode == 1:
            zig_iq = ble_iq
        else:
            ieee = iq_complex(np.ctypeslib.as_array(m.ieee_iq_words, shape=(m.ieee_iq_byte_count // 4,))[::2])
            zig_iq = np.concatenate(
                (np.zeros(400, np.complex64), resample_poly(ieee, 25, 192), np.zeros(1200, np.complex64))
            ).astype(np.complex64)
        _, zig_received = decode_zigbee(zig_iq, sample_rate=4000000)
        zig_valid = [r for r in zig_received if r["fcs_ok"]]
        self.assertEqual(len(zig_valid), 1)
        zig_valid[0]["available_sample"] = len(zig_iq)
        return ble_iq, ble_packets, zig_iq, zig_valid[0]

    def test_real_c_waveforms_all_points_and_marker_offset_h1(self):
        p = Packet(2701, 10, 5000, 500, 1, 8000, 7500, 1, 1, 1, 2, 1, 2)
        for b, z in ((0, 0), (1, 0), (26, 0), (2, 6)):
            for mode, m_name in ((1, "JC"), (2, "SC"), (3, "LC")):
                ble_iq, ble_pkts, zig_iq, zig_pkt = self._gen_iq_and_decode(p, b, z, mode)
                cfg = generate_uc1_config(2701, mode=m_name, profile="core", ble_extra=b, ieee_extra=z, tasks=1, policy="k", value=1, provenance=False)
                layout = cfg["layout"]
                ex = BLEControlExtractor(allowed_run_id=2701, layout=layout)
                ble_raws = [out for pkt in ble_pkts if (out := ex(pkt)) is not None]
                self.assertEqual(len(ble_raws), 1)
                ble_rec = control_record(ble_raws[0], "ble", layout=layout, verify_test_fill=True)
                zig_rec = control_record(bytes.fromhex(zig_pkt["payload_hex"]), "zigbee", layout=layout, verify_test_fill=True)
                self.assertEqual(ble_rec["wire_format"], "UC1")
                self.assertEqual(zig_rec["wire_format"], "UC1")
                self.assertEqual(ble_rec["valid_until_ms"], 7500)
                self.assertEqual(ble_rec["execute_at_ms"], 8000)
                if mode == 3:
                    expected_frags = 1 if b <= 1 else (26 + b + 11) // 12
                    self.assertEqual(len(ble_pkts), expected_frags)
                    self.assertEqual(ex.counts["c3_fragments"], 0 if b <= 1 else expected_frags)
                if mode == 1:
                    # H1 check: measure actual BLE-to-IEEE preamble offset in same IQ vs 400 + 8*b us
                    delta_us = (zig_pkt["sample_start"] - ble_pkts[0]["sample_start"]) * 1e6 / 4000000
                    expected_us = 400 + 8 * b
                    self.assertAlmostEqual(delta_us, expected_us, delta=0.5)

    def test_end_to_end_receivers_uc1_analyze_and_cross_mode_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summaries = {}
            for run_id, mode, m_name in ((2711, 1, "JC"), (2712, 2, "SC"), (2713, 3, "LC")):
                cfg = generate_uc1_config(
                    run_id, mode=m_name, profile="core", ble_extra=26, ieee_extra=0,
                    tasks=2, policy="budget", value=6000, phase="P2", stage="verification",
                    rf_condition="R0", provenance=False,
                )
                validate_uc1_config(cfg, run_id)
                cfg_path = root / f"uc1_{run_id}.json"
                cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
                cmds = export_commands(cfg, cfg_path)
                self.assertIn(f"b2z_uc1_start? {run_id} 500 2 26 0 {mode} 1 6000 0", cmds["board_command"])

                # Build real C IQ waveforms for all planned attempts of both tasks (K=3 for JC/SC, K=2 for LC)
                ble_iqs = [np.zeros(4000, np.complex64)]
                zig_iqs = [np.zeros(4000, np.complex64)]
                for t in cfg["tasks"]:
                    for attempt_idx in range(t["attempts"]):
                        slot = t["first_slot"] + attempt_idx
                        p = Packet(
                            run_id, slot, slot * 500, 500, t["command_id"],
                            t["execute_at_ms"], t["valid_until_ms"],
                            t["ble_target"], t["ble_opcode"], t["ble_arg"],
                            t["zigbee_target"], t["zigbee_opcode"], t["zigbee_arg"],
                        )
                        b_iq, _, z_iq, _ = self._gen_iq_and_decode(p, 26, 0, mode)
                        # Drop first attempt on BLE for task 1 in JC to test retry recovery (first_attempt < within_planned)
                        if m_name == "JC" and t["command_id"] == 1 and attempt_idx == 0:
                            ble_iqs.append(np.zeros(len(b_iq), np.complex64))
                        else:
                            ble_iqs.append(b_iq)
                        zig_iqs.append(z_iq)
                exp_dir = root / f"exp_{run_id}"
                exp_dir.mkdir()
                ble_iq_file = root / f"ble_{run_id}.cf32"
                zig_iq_file = root / f"zig_{run_id}.cf32"
                np.concatenate(ble_iqs).astype("<c8").tofile(ble_iq_file)
                np.concatenate(zig_iqs).astype("<c8").tofile(zig_iq_file)
                (exp_dir / "board.board.log").write_text(make_synthetic_uc1_board_log(cfg))

                ble_layout = "joint" if m_name == "JC" else "separate"
                ble_out = exp_dir / "captures" / "ble" / "run" / "rx"
                zig_out = exp_dir / "captures" / "zigbee" / "run" / "rx"
                r_ble = subprocess.run(
                    [
                        sys.executable, str(REPO_ROOT / "python/exadv_rx/receive.py"),
                        "--iq-file", str(ble_iq_file), "--format", "cf32", "--sample-rate", "4000000",
                        "--channels", str(cfg["layout"]["ble_channel"]), "--control-layout", ble_layout,
                        "--run-id", str(run_id), "--uc1-config", str(cfg_path),
                        "--duration", "0", "--output", str(ble_out), "--quiet",
                    ],
                    capture_output=True, text=True,
                )
                self.assertEqual(r_ble.returncode, 0, r_ble.stderr)
                r_zig = subprocess.run(
                    [
                        sys.executable, str(REPO_ROOT / "python/zigbee_rx/control_receive.py"),
                        "--iq-file", str(zig_iq_file), "--format", "cf32", "--sample-rate", "4000000",
                        "--channel", "12", "--control-layout", ble_layout,
                        "--run-id", str(run_id), "--uc1-config", str(cfg_path),
                        "--duration", "0", "--output", str(zig_out), "--quiet",
                    ],
                    capture_output=True, text=True,
                )
                self.assertEqual(r_zig.returncode, 0, r_zig.stderr)

                out_dir = exp_dir / "analyses" / "uc1_check"
                res = run_analysis(exp_dir, cfg_path, out_dir)
                summaries[m_name] = res
                self.assertEqual(res["within_planned_attempts"]["joint"]["numerator"], 2)
                self.assertEqual(res["within_planned_attempts"]["joint"]["denominator"], 2)
                self.assertEqual(res["deadline_class"]["joint_unknown"]["numerator"], 2)
                self.assertEqual(res["deadline_class"]["joint_on_time"]["numerator"], 0)
                if m_name == "JC":
                    # Task 1 dropped on BLE attempt 1, recovered on attempt 2!
                    self.assertEqual(res["first_attempt"]["joint"]["numerator"], 1)
                    self.assertEqual(res["first_attempt"]["quadrants"]["zigbee_only"], 1)
                else:
                    self.assertEqual(res["first_attempt"]["joint"]["numerator"], 2)
                if m_name == "LC":
                    # 2 tasks * K=2 * 5 fragments = 20 fragments, 4 complete records
                    self.assertEqual(res["ble_fragment_reassembly"]["c3_fragments"], 20)
                    self.assertEqual(res["ble_fragment_reassembly"]["complete"], 4)
                    self.assertEqual(res["waveform_cost"]["submitted_waveform_us"], 4 * 2904)
                else:
                    self.assertEqual(res["waveform_cost"]["submitted_waveform_us"], 6 * 1856)

            comp = compare_uc1(summaries)
            self.assertIsNone(comp["comparisons"]["JC_vs_SC"]["recorded_conditions_match"])
            self.assertFalse(comp["comparisons"]["JC_vs_SC"]["reliability_protocol_effect_identifiable"])
            # Missing evidence must not certify fairness; numeric zero is valid evidence.
            complete = deepcopy(summaries)
            for summary in complete.values():
                summary["receiver_configs"] = {
                    side: dict(sample_rate=4000000, lna=16, vga=16, amp=0, duration=60, center_hz=2410000000)
                    for side in ("ble", "zigbee")
                }
            conditions = {mode: dict(topology="feeder", tx_power=0, attenuation=0, firmware_build="test")
                          for mode in complete}
            fair = compare_uc1(complete, conditions)["comparisons"]["JC_vs_SC"]
            self.assertTrue(fair["recorded_conditions_match"])
            self.assertTrue(fair["reliability_protocol_effect_identifiable"])
            complete["SC"]["receiver_configs"]["ble"]["lna"] = 99
            unfair = compare_uc1(complete, conditions)["comparisons"]["JC_vs_SC"]
            self.assertFalse(unfair["recorded_conditions_match"])
            self.assertFalse(unfair["reliability_protocol_effect_identifiable"])
            complete["SC"]["receiver_configs"]["ble"]["lna"] = 16
            del complete["SC"]["receiver_configs"]["ble"]["amp"]
            unknown = compare_uc1(complete, conditions)["comparisons"]["JC_vs_SC"]
            self.assertIsNone(unknown["recorded_conditions_match"])
            self.assertIn("receiver.ble.amp", unknown["missing_evidence"])
            complete["SC"]["receiver_configs"]["ble"]["amp"] = 0
            complete["SC"]["planned_task_semantics"][0]["ble_arg"] += 1
            mismatch = compare_uc1(complete, conditions)["comparisons"]["JC_vs_SC"]
            self.assertIn("planned_task_semantics", mismatch["differences"])
            self.assertFalse(mismatch["reliability_protocol_effect_identifiable"])
            self.assertFalse(comp["comparisons"]["JC_vs_SC"]["channel_confound"])
            self.assertTrue(comp["comparisons"]["JC_vs_LC"]["channel_confound"])
            self.assertFalse(comp["comparisons"]["JC_vs_LC"]["reliability_protocol_effect_identifiable"])

    def test_uc1_config_100_tasks_dry_run_and_validation(self):
        cfg100 = generate_uc1_config(2801, mode="LC", profile="core", ble_extra=26, ieee_extra=0,
                                     tasks=100, policy="budget", value=6000, provenance=False)
        self.assertEqual(cfg100["planned_slots"], 610)
        self.assertEqual(cfg100["k"], 2)
        self.assertEqual(cfg100["cost_per_attempt_us"], 2904)
        self.assertEqual(cfg100["unused_per_task_us"], 192)
        self.assertEqual(cfg100["planned_attempts"], 200)
        self.assertEqual(cfg100["planned_silent_slots"], 410)
        self.assertEqual(cfg100["planned_waveform_us"], 200 * 2904)
        validate_uc1_config(cfg100, 2801)

        # Reject budget that yields K=0 or K>4 (never truncate)
        with self.assertRaises(ValueError):
            generate_uc1_config(2802, mode="JC", ble_extra=0, ieee_extra=0, tasks=10, policy="budget", value=1647, provenance=False)
        with self.assertRaises(ValueError):
            generate_uc1_config(2802, mode="JC", ble_extra=0, ieee_extra=0, tasks=10, policy="budget", value=10000, provenance=False)
        # Reject time profile with wrong mode/tasks/policy
        with self.assertRaises(ValueError):
            generate_uc1_config(2803, mode="LC", profile="time", tasks=6, policy="k", value=3, provenance=False)

        table = dry_run_cost_table(6000)
        self.assertIn("| A | 0,0 | 26/26 | 1648 | 1456 | 2/3/2 | 3/3/4 | 1056/1056/176 |", table)
        self.assertIn("| B | 26,0 | 52/26 | 1856 | 2904 | 2/3/6 | 3/3/2 | 432/432/192 |", table)
        self.assertIn("| C | 2,6 | 28/32 | 1856 | 2344 | 2/3/4 | 3/3/2 | 432/432/1312 |", table)

    def test_uc1_zero_joint_success_returns_na_and_time_profile_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Zero joint success -> per_joint_decoded_task.value_us is None (N/A)
            cfg = generate_uc1_config(2720, mode="JC", profile="core", ble_extra=0, ieee_extra=0,
                                      tasks=2, policy="k", value=1, provenance=False)
            cfg_path = root / "cfg.json"
            cfg_path.write_text(json.dumps(cfg))
            exp_dir = root / "exp_zero"
            exp_dir.mkdir()
            (exp_dir / "board.board.log").write_text(make_synthetic_uc1_board_log(cfg))
            for side in ("ble", "zigbee"):
                d = exp_dir / "captures" / side / "run"
                d.mkdir(parents=True)
                (d / "rx.packets.jsonl").write_text("")
                (d / "rx.summary.json").write_text(json.dumps(dict(
                    status="complete", uc1_config_sha256=cfg["sha256"],
                    counts=dict(samples_processed=4000000),
                    config=dict(sample_rate=4000000, iq_file="synthetic.cf32"),
                )))
            res = run_analysis(exp_dir, cfg_path, exp_dir / "analyses" / "zero")
            self.assertEqual(res["within_planned_attempts"]["joint"]["numerator"], 0)
            self.assertEqual(res["within_planned_attempts"]["joint"]["denominator"], 2)
            self.assertIsNone(res["waveform_cost"]["per_joint_decoded_task"]["value_us"])
            self.assertIn("N/A", (exp_dir / "analyses" / "zero" / "uc1.report.md").read_text())

            # Time profile (300 slots, b=26 -> 608 us offset, 6 tasks K=3 + 282 time updates)
            t_cfg = generate_uc1_config(2721, mode="JC", profile="time", ble_extra=26, ieee_extra=0,
                                        tasks=6, policy="k", value=3, provenance=False)
            t_cfg_path = root / "time_cfg.json"
            t_cfg_path.write_text(json.dumps(t_cfg))
            t_exp = root / "exp_time"
            t_exp.mkdir()
            (t_exp / "board.board.log").write_text(make_synthetic_uc1_board_log(t_cfg))
            task_by_slot = {}
            for t in t_cfg["tasks"]:
                for s in range(t["first_slot"], t["first_slot"] + t["attempts"]):
                    task_by_slot[s] = t
            offset_samples = 4000000 * 608 / 1_000_000
            for side in ("ble", "zigbee"):
                d = t_exp / "captures" / side / "run"
                d.mkdir(parents=True)
                pkt_lines = []
                for slot in range(300):
                    # Simulate BLE outage during slots 120..145 (13 s > 10 s stale)
                    if side == "ble" and 120 <= slot <= 145:
                        continue
                    t = task_by_slot.get(slot)
                    if t is None:
                        extra = bytes(26 if side == "ble" else 0)
                        rec_bytes = build_uc1_wire(
                            run_id=2721, slot=slot, period_ms=500, command_id=0, target_id=0,
                            opcode=0, arg=0, valid_offset_ms=0, execute_offset_ms=0, extra=extra, ver_type=0x10,
                        )
                    else:
                        n = 26 if side == "ble" else 0
                        extra = uc1_extension(2721, t["command_id"], side, n)
                        ref = slot * 500
                        rec_bytes = build_uc1_wire(
                            run_id=2721, slot=slot, period_ms=500, command_id=t["command_id"],
                            target_id=t[side + "_target"], opcode=t[side + "_opcode"], arg=t[side + "_arg"],
                            valid_offset_ms=t["valid_until_ms"] - ref,
                            execute_offset_ms=t["execute_at_ms"] - ref, extra=extra, ver_type=0x11,
                        )
                    s_start = slot * 2_000_000 + (0.0 if side == "ble" else offset_samples)
                    avail = int(s_start) + 4096
                    if side == "ble":
                        ad = b"\xff\xff" + rec_bytes + bytes(136)
                        pkt = dict(
                            kind="auxiliary", crc_ok=True, pdu_length=15 + len(ad),
                            sample_start=s_start, available_sample=avail, sample_time_s=s_start / 4000000,
                            extended=dict(adi=dict(did=slot & 0xFFF),
                                          ad_structures=[dict(type=255, company_id=0xFFFF, data_hex=ad.hex())]),
                        )
                    else:
                        pkt = dict(
                            fcs_ok=True, payload_hex=rec_bytes.hex(),
                            sample_start=s_start, available_sample=avail, sample_time_s=s_start / 4000000,
                        )
                    pkt_lines.append(json.dumps(pkt))
                (d / "rx.packets.jsonl").write_text("\n".join(pkt_lines) + "\n")
                (d / "rx.summary.json").write_text(json.dumps(dict(
                    status="complete", uc1_config_sha256=t_cfg["sha256"],
                    counts=dict(samples_processed=305 * 4000000),
                    config=dict(sample_rate=4000000, iq_file="synthetic.cf32"),
                )))
            t_res = run_analysis(t_exp, t_cfg_path, t_exp / "analyses" / "time_check")
            self.assertEqual(t_res["within_planned_attempts"]["joint"]["numerator"], 6)
            self.assertEqual(t_res["within_planned_attempts"]["joint"]["denominator"], 6)
            self.assertEqual(t_res["time_support"]["marker_offset_us"], 608)
            self.assertEqual(t_res["waveform_cost"]["planned_time_updates"], 282)
            # Check offline replay scored with ~0 us relative error using 608 us marker offset
            self.assertTrue((t_exp / "analyses" / "time_check" / "uc1.replay_summary.csv").is_file())
            rel_rows = [r for r in t_res["time_support"]["replay_summary"] if r["metric"] == "relative_error_us" and r["policy"] == "update_1s"]
            self.assertEqual(len(rel_rows), 1)
            self.assertAlmostEqual(rel_rows[0]["median_abs"], 0.0, places=2)

    def test_cli_entrypoints_and_misconfiguration_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = root / "uc1_2799.json"
            board_cmd_path = root / "uc1_2799.board.txt"
            host_cmd_path = root / "uc1_2799.host.sh"
            r_cfg = subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "python/control_match/uc1_config.py"),
                    "--run-id", "2799", "--mode", "LC", "--profile", "core",
                    "--ble-extra", "26", "--ieee-extra", "0", "--tasks", "10",
                    "--policy", "budget", "--value", "6000", "--allow-existing-run-id",
                    "--output", str(cfg_path),
                    "--board-commands", str(board_cmd_path),
                    "--host-commands", str(host_cmd_path),
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(r_cfg.returncode, 0, r_cfg.stderr)
            self.assertIn("b2z_uc1_start? 2799 500 10 26 0 3 1 6000 0", board_cmd_path.read_text())
            self.assertIn("--uc1-config", host_cmd_path.read_text())
            self.assertIn("uc1_analyze.py", host_cmd_path.read_text())

            # Receiver CLI rejects wrong BLE channel for LC (ch3 instead of ch39)
            dummy_iq = root / "empty.cf32"
            np.zeros(4096, np.complex64).astype("<c8").tofile(dummy_iq)
            r_bad_ch = subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "python/exadv_rx/receive.py"),
                    "--iq-file", str(dummy_iq), "--format", "cf32", "--sample-rate", "4000000",
                    "--channels", "3", "--control-layout", "separate",
                    "--run-id", "2799", "--uc1-config", str(cfg_path),
                    "--duration", "0", "--output", str(root / "bad_ble"), "--quiet",
                ],
                capture_output=True, text=True,
            )
            self.assertNotEqual(r_bad_ch.returncode, 0)
            self.assertIn("BLE channel", r_bad_ch.stderr)

            # Receiver CLI rejects wrong ZigBee channel (ch26 instead of ch12)
            r_bad_z = subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "python/zigbee_rx/control_receive.py"),
                    "--iq-file", str(dummy_iq), "--format", "cf32", "--sample-rate", "4000000",
                    "--channel", "26", "--control-layout", "separate",
                    "--run-id", "2799", "--uc1-config", str(cfg_path),
                    "--duration", "0", "--output", str(root / "bad_zig"), "--quiet",
                ],
                capture_output=True, text=True,
            )
            self.assertNotEqual(r_bad_z.returncode, 0)
            self.assertIn("IEEE channel", r_bad_z.stderr)

            # Receiver CLI in time profile with ControlSession enabled (JC, b=26)
            t_cfg = generate_uc1_config(2798, mode="JC", profile="time", ble_extra=26, ieee_extra=0,
                                        tasks=6, policy="k", value=3, provenance=False)
            t_cfg_path = root / "uc1_2798.json"
            t_cfg_path.write_text(json.dumps(t_cfg))
            p0 = Packet(2798, 0, 0, 500, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            b_iq, _, z_iq, _ = self._gen_iq_and_decode(p0, 26, 0, 1)
            time_iq = root / "time_joint.cf32"
            b_iq.astype("<c8").tofile(time_iq)
            r_tb = subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "python/exadv_rx/receive.py"),
                    "--iq-file", str(time_iq), "--format", "cf32", "--sample-rate", "4000000",
                    "--channels", "3", "--control-layout", "joint",
                    "--run-id", "2798", "--uc1-config", str(t_cfg_path),
                    "--control-target-id", "1",
                    "--duration", "0", "--output", str(root / "tb_rx"), "--quiet",
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(r_tb.returncode, 0, r_tb.stderr)
            tb_ctrl = json.loads((root / "tb_rx.control.summary.json").read_text())
            self.assertEqual(tb_ctrl["event_counts"]["decoded"], 1)
            self.assertEqual(tb_ctrl["event_counts"]["candidate_accumulating"], 1)

            r_tz = subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "python/zigbee_rx/control_receive.py"),
                    "--iq-file", str(time_iq), "--format", "cf32", "--sample-rate", "4000000",
                    "--channel", "12", "--control-layout", "joint",
                    "--run-id", "2798", "--uc1-config", str(t_cfg_path),
                    "--control-target-id", "2",
                    "--duration", "0", "--output", str(root / "tz_rx"), "--quiet",
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(r_tz.returncode, 0, r_tz.stderr)
            tz_ctrl = json.loads((root / "tz_rx.control.summary.json").read_text())
            self.assertEqual(tz_ctrl["event_counts"]["decoded"], 1)
            # Slot 0 is BLE candidate (even), not ZigBee candidate (odd)
            self.assertEqual(tz_ctrl["event_counts"]["not_training_candidate"], 1)

            # uc1_analyze rejects mismatched board log layout
            exp_bad = root / "exp_bad"
            exp_bad.mkdir()
            wrong_cfg = generate_uc1_config(2799, mode="JC", profile="core", ble_extra=26, ieee_extra=0,
                                            tasks=10, policy="budget", value=6000, provenance=False)
            (exp_bad / "board.board.log").write_text(make_synthetic_uc1_board_log(wrong_cfg))
            with self.assertRaisesRegex(ValueError, "differs from manifest"):
                run_analysis(exp_bad, cfg_path, exp_bad / "analyses" / "bad")

            # uc1_analyze --compare CLI end-to-end
            s_jc = root / "jc.summary.json"
            s_lc = root / "lc.summary.json"
            for mode_name, run_id, target_file in (("JC", 2781, s_jc), ("LC", 2782, s_lc)):
                c = generate_uc1_config(run_id, mode=mode_name, profile="core", ble_extra=26, ieee_extra=0,
                                        tasks=2, policy="budget", value=6000, provenance=False)
                c_path = root / f"c_{run_id}.json"
                c_path.write_text(json.dumps(c))
                e_dir = root / f"e_{run_id}"
                e_dir.mkdir()
                (e_dir / "board.board.log").write_text(make_synthetic_uc1_board_log(c))
                for side in ("ble", "zigbee"):
                    d = e_dir / "captures" / side / "r"
                    d.mkdir(parents=True)
                    (d / "rx.packets.jsonl").write_text("")
                    (d / "rx.summary.json").write_text(json.dumps(dict(
                        status="complete", uc1_config_sha256=c["sha256"],
                        counts=dict(samples_processed=4000000),
                        config=dict(sample_rate=4000000, iq_file="syn.cf32"),
                    )))
                r_an = subprocess.run(
                    [
                        sys.executable, str(REPO_ROOT / "python/control_match/uc1_analyze.py"),
                        "--experiment-dir", str(e_dir), "--config", str(c_path), "--analysis-id", "a1",
                    ],
                    capture_output=True, text=True,
                )
                self.assertEqual(r_an.returncode, 0, r_an.stderr)
                target_file.write_text((e_dir / "analyses/a1/uc1.summary.json").read_text())
            comp_out = root / "comp_out"
            r_cmp = subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "python/control_match/uc1_analyze.py"),
                    "--compare-jc", str(s_jc), "--compare-lc", str(s_lc), "--output-dir", str(comp_out),
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(r_cmp.returncode, 0, r_cmp.stderr)
            comp_data = json.loads((comp_out / "uc1.comparison.json").read_text())
            self.assertTrue(comp_data["comparisons"]["JC_vs_LC"]["channel_confound"])
            self.assertTrue((comp_out / "uc1.comparison.md").is_file())

    def test_uc1_time_recovery_in_schedule_vs_post_run_tail_and_h6_replay(self):
        from python.control_match.uc1_h6_replay import run_h6_replay

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            t_cfg = generate_uc1_config(2722, mode="JC", profile="time", ble_extra=26, ieee_extra=0,
                                        tasks=6, policy="k", value=3, provenance=False)
            t_cfg_path = root / "time_cfg.json"
            t_cfg_path.write_text(json.dumps(t_cfg))
            task_by_slot = {}
            for t in t_cfg["tasks"]:
                for s in range(t["first_slot"], t["first_slot"] + t["attempts"]):
                    task_by_slot[s] = t
            offset_samples = 4000000 * 608 / 1_000_000

            def _build_time_exp(exp_name: str, ble_drop_fn):
                t_exp = root / exp_name
                t_exp.mkdir()
                (t_exp / "board.board.log").write_text(make_synthetic_uc1_board_log(t_cfg))
                for side in ("ble", "zigbee"):
                    d = t_exp / "captures" / side / "run"
                    d.mkdir(parents=True)
                    pkt_lines = []
                    for slot in range(300):
                        if side == "ble" and ble_drop_fn(slot):
                            continue
                        t = task_by_slot.get(slot)
                        if t is None:
                            extra = bytes(26 if side == "ble" else 0)
                            rec_bytes = build_uc1_wire(
                                run_id=2722, slot=slot, period_ms=500, command_id=0, target_id=0,
                                opcode=0, arg=0, valid_offset_ms=0, execute_offset_ms=0, extra=extra, ver_type=0x10,
                            )
                        else:
                            n = 26 if side == "ble" else 0
                            extra = uc1_extension(2722, t["command_id"], side, n)
                            ref = slot * 500
                            rec_bytes = build_uc1_wire(
                                run_id=2722, slot=slot, period_ms=500, command_id=t["command_id"],
                                target_id=t[side + "_target"], opcode=t[side + "_opcode"], arg=t[side + "_arg"],
                                valid_offset_ms=t["valid_until_ms"] - ref,
                                execute_offset_ms=t["execute_at_ms"] - ref, extra=extra, ver_type=0x11,
                            )
                        s_start = slot * 2_000_000 + (0.0 if side == "ble" else offset_samples)
                        avail = int(s_start) + 4096
                        if side == "ble":
                            ad = b"\xff\xff" + rec_bytes + bytes(136)
                            pkt = dict(
                                kind="auxiliary", crc_ok=True, pdu_length=15 + len(ad),
                                sample_start=s_start, available_sample=avail, sample_time_s=s_start / 4000000,
                                extended=dict(adi=dict(did=slot & 0xFFF),
                                              ad_structures=[dict(type=255, company_id=0xFFFF, data_hex=ad.hex())]),
                            )
                        else:
                            pkt = dict(
                                fcs_ok=True, payload_hex=rec_bytes.hex(),
                                sample_start=s_start, available_sample=avail, sample_time_s=s_start / 4000000,
                            )
                        pkt_lines.append(json.dumps(pkt))
                    (d / "rx.packets.jsonl").write_text("\n".join(pkt_lines) + "\n")
                    # Emit live-style control events through SideControlEngine up to capture end (180 s)
                    eng = SideControlEngine(EngineConfig(
                        side=side, run_id=2722, sample_rate=4000000,
                        target_ids=frozenset({1 if side == "ble" else 2}), uc1_config=t_cfg,
                    ))
                    ev_lines = [json.dumps({"event": "registration", "registration": t_cfg})]
                    cur_adv = 0
                    for line in pkt_lines:
                        p = json.loads(line)
                        avail = int(p["available_sample"])
                        while cur_adv + 4_000_000 < avail:
                            cur_adv += 4_000_000
                            for ev in eng.advance(cur_adv):
                                ev_lines.append(json.dumps(ev))
                        cur_adv = avail
                        raw_b = (
                            bytes.fromhex(p["extended"]["ad_structures"][0]["data_hex"])[2:2 + 52]
                            if side == "ble" else bytes.fromhex(p["payload_hex"])
                        )
                        for ev in eng.observe(raw_b, float(p["sample_start"]), avail):
                            ev_lines.append(json.dumps(ev))
                    # Advance through capture end in 1 s chunks so post-run tail stale triggers cleanly
                    total_samples = 180 * 4000000
                    while cur_adv < total_samples:
                        cur_adv = min(total_samples, cur_adv + 4_000_000)
                        for ev in eng.advance(cur_adv):
                            ev_lines.append(json.dumps(ev))
                    (d / "rx.control.events.jsonl").write_text("\n".join(ev_lines) + "\n")
                    # Capture continues 30 s past slot 299 (149.5 s -> 180 s), triggering post-run tail stale
                    (d / "rx.summary.json").write_text(json.dumps(dict(
                        status="complete", uc1_config_sha256=t_cfg["sha256"],
                        counts=dict(samples_processed=total_samples),
                        config=dict(sample_rate=4000000, iq_file="synthetic.cf32"),
                    )))
                return t_exp

            # Case A: mid-schedule recovered BLE outage (slots 120..145) + post-run tail stale on both sides
            exp_rec = _build_time_exp("exp_recovered", lambda s: 120 <= s <= 145)
            res_rec = run_analysis(exp_rec, t_cfg_path, exp_rec / "analyses" / "tail_audit")
            ts_rec = res_rec["time_support"]
            self.assertEqual(ts_rec["recovery_in_schedule"]["ble"], {"numerator": 1, "denominator": 1, "value": 1.0})
            self.assertEqual(ts_rec["recovery_in_schedule"]["zigbee"], {"numerator": 0, "denominator": 0, "value": None})
            self.assertEqual(ts_rec["post_run_tail_stale_events"], {"ble": 1, "zigbee": 1})
            # Backward-compatible all-recording recovery includes tail stale
            self.assertEqual(ts_rec["recovery"]["ble"]["denominator"], 2)
            self.assertEqual(ts_rec["recovery"]["zigbee"]["denominator"], 1)

            # Case B: genuine unrecovered mid-schedule BLE outage (drops from slot 180 onward, 60 s > 10 s remaining)
            exp_perm = _build_time_exp("exp_perm_drop", lambda s: s >= 180)
            res_perm = run_analysis(exp_perm, t_cfg_path, exp_perm / "analyses" / "tail_audit")
            ts_perm = res_perm["time_support"]
            # Must stay classified as in_schedule (0/1), NOT post_run_tail!
            self.assertEqual(ts_perm["recovery_in_schedule"]["ble"], {"numerator": 0, "denominator": 1, "value": 0.0})
            self.assertEqual(ts_perm["post_run_tail_stale_events"]["ble"], 0)
            self.assertEqual(ts_perm["post_run_tail_stale_events"]["zigbee"], 1)

            # Case C: H6 replay on full time-profile stream (no drops) passes all 4 cases & refuses overwrite
            exp_full = _build_time_exp("exp_full_time", lambda s: False)
            h6_out = exp_full / "analyses" / "h6_test"
            h6_res = run_h6_replay(exp_full, t_cfg_path, h6_out)
            self.assertTrue(h6_res["overall"]["all_passed"])
            self.assertEqual(h6_res["overall"]["passed"], 4)
            self.assertEqual(h6_res["evidence_type"], "offline_fault_injection_replay_on_recorded_packets")
            with self.assertRaises(FileExistsError):
                run_h6_replay(exp_full, t_cfg_path, h6_out)


if __name__ == "__main__":
    unittest.main()

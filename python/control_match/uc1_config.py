#!/usr/bin/env python3
"""Generate and validate immutable UC1 manifests, board commands, and dry-run tables."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

try:
    from .n3_holdover import default_config as n3_default_config
    from .compact import MAX_PENDING_LIMIT, MAX_CLOSED_LIMIT
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from control_match.n3_holdover import default_config as n3_default_config
    from control_match.compact import MAX_PENDING_LIMIT, MAX_CLOSED_LIMIT

SCHEMA = "b2z_uc1_config_v1"
MODE_TO_CODE = {"JC": 1, "SC": 2, "LC": 3}
CODE_TO_MODE = {1: "JC", 2: "SC", 3: "LC"}
POLICY_TO_CODE = {"k": 0, "budget": 1}
CODE_TO_POLICY = {0: "k", 1: "budget"}
PROFILE_TO_CODE = {"core": 0, "time": 1}
CODE_TO_PROFILE = {0: "core", 1: "time"}
TIME_FIRST_SLOTS = (70, 90, 150, 190, 240, 270)
POINT_MAP = {(0, 0): "A", (26, 0): "B", (2, 6): "C", (1, 0): "B1"}
RF_MODE_NAMES = {
    "JC": "standard_secondary_ch3",
    "SC": "separate_secondary_ch3",
    "LC": "legacy_separate_ch39",
}


def normalize_mode(mode: str | int) -> str:
    if isinstance(mode, int) and not isinstance(mode, bool):
        if mode not in CODE_TO_MODE:
            raise ValueError(f"unsupported UC1 mode: {mode}")
        return CODE_TO_MODE[mode]
    if isinstance(mode, str) and mode.upper() in MODE_TO_CODE:
        return mode.upper()
    raise ValueError(f"unsupported UC1 mode: {mode}")


def normalize_policy(policy: str | int) -> str:
    if isinstance(policy, int) and not isinstance(policy, bool):
        if policy not in CODE_TO_POLICY:
            raise ValueError(f"unsupported UC1 policy: {policy}")
        return CODE_TO_POLICY[policy]
    if isinstance(policy, str) and policy.lower() in POLICY_TO_CODE:
        return policy.lower()
    raise ValueError(f"unsupported UC1 policy: {policy}")


def normalize_profile(profile: str | int) -> str:
    if isinstance(profile, int) and not isinstance(profile, bool):
        if profile not in CODE_TO_PROFILE:
            raise ValueError(f"unsupported UC1 profile: {profile}")
        return CODE_TO_PROFILE[profile]
    if isinstance(profile, str) and profile.lower() in PROFILE_TO_CODE:
        return profile.lower()
    raise ValueError(f"unsupported UC1 profile: {profile}")


def uc1_burst_table(b: int, z: int, mode: str | int) -> list[tuple[str, int]]:
    """Return exact per-attempt (burst_kind, air_us) design budget matching firmware."""
    m = normalize_mode(mode)
    if (
        type(b) is not int
        or type(z) is not int
        or not 0 <= b <= 26
        or not 0 <= z <= 6
        or b + 4 * z > 26
    ):
        raise ValueError("UC1 (b, z) outside phase-1 working domain (0<=b<=26, 0<=z<=6, b+4z<=26)")
    if m == "JC":
        return [("primary", 136), ("secondary", (189 + b + 4 * z) * 8)]
    if m == "SC":
        return [("primary", 136), ("secondary", (53 + b) * 8), ("ieee", (136 + 4 * z) * 8)]
    # LC: direct legacy (b<=1) or C3 15-byte header + 12-byte chunk fragments + standalone IEEE
    length = 26 + b
    if length <= 27:
        bursts = [("fragment0", (20 + length) * 8)]
    else:
        count = (length + 11) // 12
        bursts = [
            (f"fragment{i}", (20 + 15 + min(12, length - 12 * i)) * 8)
            for i in range(count)
        ]
    bursts.append(("ieee", (136 + 4 * z) * 8))
    return bursts


def uc1_cost(b: int, z: int, mode: str | int) -> int:
    """Design effective waveform budget (µs) for one complete UC1 logical attempt."""
    return sum(air for _, air in uc1_burst_table(b, z, mode))


def digest(config: dict) -> str:
    body = {k: v for k, v in config.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def used_run_ids(repo_root: Path | None = None) -> dict[int, list[str]]:
    """Inspect experiment directories, index CSVs, and config JSONs for occupied run IDs."""
    root = repo_root or Path(__file__).resolve().parents[2]
    found: dict[int, list[str]] = {}

    def mark(run_id: int, source: str) -> None:
        found.setdefault(run_id, []).append(source)

    exp_dir = root / "python" / "experiments"
    if exp_dir.is_dir():
        for entry in exp_dir.iterdir():
            m = re.search(r"_run(\d+)$", entry.name)
            if m:
                mark(int(m.group(1)), f"dir:{entry.name}")
        for csv_name in ("index.csv", "runs.csv"):
            csv_path = exp_dir / csv_name
            if csv_path.is_file():
                try:
                    with csv_path.open(encoding="utf-8") as handle:
                        for row in csv.DictReader(handle):
                            raw = row.get("run_id") or row.get("Run ID")
                            if raw and str(raw).isdigit():
                                mark(int(raw), f"csv:{csv_name}")
                except OSError:
                    pass
    cfg_dir = root / "python" / "control_match" / "configs"
    if cfg_dir.is_dir():
        for path in cfg_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and type(data.get("run_id")) is int:
                    mark(data["run_id"], f"config:{path.name}")
            except (OSError, json.JSONDecodeError):
                pass
    return found


def generate(
    run_id: int,
    *,
    mode: str | int = "JC",
    profile: str | int = "core",
    ble_extra: int = 0,
    ieee_extra: int = 0,
    tasks: int = 100,
    period_ms: int = 500,
    policy: str | int = "k",
    value: int = 1,
    phase: str = "P2",
    stage: str = "verification",
    rf_condition: str = "R0",
    block: int | None = None,
    sample_rate: int = 4000000,
    lna: int = 16,
    vga: int = 16,
    amp: bool = False,
    save_iq: bool = True,
    firmware_build: str = "UNSET_RECORD_BEFORE_CAPTURE",
    pending_limit: int = 1024,
    closed_limit: int | None = None,
    fragment_timeout_s: float = 2.0,
    intervention_description: str = "no intentional intervention",
    intervention_windows: list[list[int]] | None = None,
    provenance: bool = True,
) -> dict:
    """Build a complete, immutable UC1 manifest matching firmware b2z_uc1_start? rules."""
    if type(run_id) is not int or not 1 <= run_id <= 65535:
        raise ValueError("run_id must be integer 1..65535")
    m = normalize_mode(mode)
    prof = normalize_profile(profile)
    pol = normalize_policy(policy)
    if type(period_ms) is not int or not 500 <= period_ms <= 10922:
        raise ValueError("period_ms must be integer 500..10922")
    if type(tasks) is not int or not 1 <= tasks <= 169:
        raise ValueError("tasks must be integer 1..169")
    if type(value) is not int or value <= 0:
        raise ValueError("policy value must be positive integer")

    bursts = uc1_burst_table(ble_extra, ieee_extra, m)
    cost_per_attempt = sum(air for _, air in bursts)
    if pol == "k":
        k = value
        budget_us = k * cost_per_attempt
    else:
        k = value // cost_per_attempt
        budget_us = value
    if not 1 <= k <= 4:
        raise ValueError(f"resolved K={k} outside 1..4 (reject, never truncate)")

    if prof == "time":
        if m != "JC" or tasks != 6 or pol != "k" or k != 3:
            raise ValueError("time profile requires mode=JC, tasks=6, policy=k, value=3")
        total_slots = 300
    else:
        total_slots = 10 + 6 * tasks

    if total_slots > 1024 or total_slots * period_ms > 600000:
        raise ValueError("schedule exceeds 1024 slots or 600 s board limit")

    unused_per_task = budget_us - k * cost_per_attempt
    if unused_per_task < 0:
        raise ValueError("negative unused budget")

    c_lim = max(4096, total_slots * 2) if closed_limit is None else closed_limit
    if type(pending_limit) is not int or not 1 <= pending_limit <= MAX_PENDING_LIMIT:
        raise ValueError("invalid pending_limit")
    if type(c_lim) is not int or not 1 <= c_lim <= MAX_CLOSED_LIMIT:
        raise ValueError("invalid closed_limit")
    if c_lim < total_slots:
        raise ValueError("closed_limit must at least cover total planned slots in this run")
    if fragment_timeout_s <= 0:
        raise ValueError("fragment_timeout_s must be positive")

    task_rows = []
    for j in range(tasks):
        first_slot = TIME_FIRST_SLOTS[j] if prof == "time" else 10 + 6 * j
        valid_until_ms = (first_slot + (4 if prof == "time" else 5)) * period_ms
        execute_at_ms = (first_slot + 6) * period_ms
        # Pre-check every attempt slot for uint16 offset and uint32 absolute bounds.
        for attempt_idx in range(k):
            slot = first_slot + attempt_idx
            ref = slot * period_ms
            if not (0 <= valid_until_ms - ref < execute_at_ms - ref <= 65535 and execute_at_ms <= 0xFFFFFFFF):
                raise ValueError(f"task {j + 1} slot {slot} exceeds UC1 16-bit offset or uint32 bounds")
        task_rows.append(
            dict(
                command_id=j + 1,
                first_slot=first_slot,
                attempts=k,
                valid_until_ms=valid_until_ms,
                execute_at_ms=execute_at_ms,
                ble_target=1,
                ble_opcode=1,
                ble_arg=j + 1,
                zigbee_target=2,
                zigbee_opcode=1,
                zigbee_arg=j + 2,
            )
        )

    planned_attempts = 300 if prof == "time" else tasks * k
    planned_time_updates = 300 - tasks * k if prof == "time" else 0
    planned_silent_slots = total_slots - planned_attempts
    planned_waveform_us = planned_attempts * cost_per_attempt
    board_duration_s = (total_slots * period_ms + 999) // 1000
    capture_duration_s = board_duration_s + (30 if prof == "time" else 25)
    marker_valid = m == "JC"
    marker_offset_us = 400 + 8 * ble_extra if marker_valid else None
    ble_fragments = 1 if (m != "LC" or ble_extra <= 1) else (26 + ble_extra + 11) // 12

    layout = dict(
        wire_format="UC1",
        wire_version=1,
        run_id=run_id,
        mode=m,
        rf_mode=RF_MODE_NAMES[m],
        period_ms=period_ms,
        ble_extra=ble_extra,
        ieee_extra=ieee_extra,
        ble_record_bytes=26 + ble_extra,
        ieee_record_bytes=26 + ieee_extra,
        mapped_bytes=136 + 4 * ieee_extra,
        secondary_payload_bytes=(
            179 + ble_extra + 4 * ieee_extra
            if m == "JC"
            else 43 + ble_extra
            if m == "SC"
            else 0
        ),
        ble_fragments_per_attempt=ble_fragments if m == "LC" else 1,
        ble_channel=39 if m == "LC" else 3,
        ieee_channel=12,
        phy="LE_1M",
        reference_point="planned_legacy_slot_start" if m == "LC" else "planned_secondary_start",
        reference_epoch_offset_us=0 if m == "LC" else 300000,
        marker_offset_us=marker_offset_us,
        marker_offset_valid=marker_valid,
        fill="lcg_uc1_command_seed",
    )

    cfg = dict(
        schema=SCHEMA,
        wire_format="UC1",
        wire_version=1,
        run_id=run_id,
        phase=phase,
        stage=stage,
        rf_condition=rf_condition,
        block=block,
        point=POINT_MAP.get((ble_extra, ieee_extra), "custom"),
        profile=prof,
        profile_code=PROFILE_TO_CODE[prof],
        mode=m,
        mode_code=MODE_TO_CODE[m],
        policy=pol,
        policy_code=POLICY_TO_CODE[pol],
        policy_value=value,
        period_ms=period_ms,
        tasks_count=tasks,
        planned_slots=total_slots,
        slots=list(range(total_slots)),
        k=k,
        budget_us=budget_us,
        cost_per_attempt_us=cost_per_attempt,
        unused_per_task_us=unused_per_task,
        bursts_per_attempt=len(bursts),
        burst_table=[dict(kind=kind, air_us=air) for kind, air in bursts],
        planned_attempts=planned_attempts,
        planned_time_updates=planned_time_updates,
        planned_silent_slots=planned_silent_slots,
        planned_waveform_us=planned_waveform_us,
        board_duration_s=board_duration_s,
        capture_duration_s=capture_duration_s,
        layout=layout,
        fragment_limits=dict(
            pending_limit=pending_limit,
            closed_limit=c_lim,
            timeout_s=float(fragment_timeout_s),
        ),
        tasks=task_rows,
        device_settings=dict(
            sample_rate=sample_rate,
            lna=lna,
            vga=vga,
            amp=bool(amp),
            save_iq=bool(save_iq),
        ),
        firmware_build=firmware_build,
        deadline_method="local_iq_uncalibrated_until_verified",
        board_command=(
            f"b2z_uc1_start? {run_id} {period_ms} {tasks} {ble_extra} {ieee_extra} "
            f"{MODE_TO_CODE[m]} {POLICY_TO_CODE[pol]} {value} {PROFILE_TO_CODE[prof]}"
        ),
    )

    if prof == "time":
        n3_base = n3_default_config(slots=300, period_ms=500) if period_ms == 500 else None
        probes = list(range(69, 300, 10))
        cfg.update(
            ieee_marker_offset_us=marker_offset_us,
            probes=probes,
            candidates={
                side: [s for s in range(300) if s % 2 == parity and s not in probes]
                for parity, side in enumerate(("ble", "zigbee"))
            },
            observation_policy=dict(
                history=8,
                span_ms=4000,
                update_interval_ms=1000,
                holdover_ms=2000,
                stale_ms=10000,
            ),
            policies=n3_base["policies"] if n3_base else [],
            thresholds_us=[10000, 50000, 100000],
            exploratory=False,
            intervention_description=intervention_description,
            intervention_windows=list(intervention_windows or []),
            missing_policy="no replacement of preregistered probes or frozen training slots",
            quality_policy="unknown_reference_strict_rejection",
        )
        for window in cfg["intervention_windows"]:
            if (
                not isinstance(window, list)
                or len(window) != 2
                or any(type(v) is not int for v in window)
                or not 0 <= window[0] <= window[1] < 300
            ):
                raise ValueError("invalid intervention window")

    if provenance:
        root = Path(__file__).resolve().parents[2]
        cfg["created_utc"] = datetime.now(timezone.utc).isoformat()
        try:
            cfg["code_version"] = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            cfg["code_version"] = "unknown"
        cfg["source_sha256"] = {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ("control_match", "exadv_rx", "zigbee_rx")
            for p in sorted((root / "python" / folder).glob("*.py"))
        }

    cfg["sha256"] = digest(cfg)
    return cfg


def validate(cfg: dict, run_id: int | None = None) -> dict:
    """Strictly verify a UC1 manifest against schema, digest, and firmware rules."""
    if not isinstance(cfg, dict) or cfg.get("schema") != SCHEMA:
        raise ValueError("invalid UC1 config schema")
    if cfg.get("wire_format") != "UC1" or cfg.get("wire_version") != 1:
        raise ValueError("invalid UC1 wire_format/wire_version")
    if cfg.get("sha256") != digest(cfg):
        raise ValueError("UC1 config sha256 mismatch")
    if run_id is not None and cfg.get("run_id") != run_id:
        raise ValueError("UC1 config run_id mismatch")
    layout = cfg.get("layout") or {}
    limits = cfg.get("fragment_limits") or {}
    dev = cfg.get("device_settings") or {}
    expected = generate(
        cfg["run_id"],
        mode=cfg["mode"],
        profile=cfg["profile"],
        ble_extra=layout["ble_extra"],
        ieee_extra=layout["ieee_extra"],
        tasks=cfg["tasks_count"],
        period_ms=cfg["period_ms"],
        policy=cfg["policy"],
        value=cfg["policy_value"],
        phase=cfg.get("phase", "P2"),
        stage=cfg.get("stage", "verification"),
        rf_condition=cfg.get("rf_condition", "R0"),
        block=cfg.get("block"),
        sample_rate=dev.get("sample_rate", 4000000),
        lna=dev.get("lna", 16),
        vga=dev.get("vga", 16),
        amp=dev.get("amp", False),
        save_iq=dev.get("save_iq", True),
        firmware_build=cfg.get("firmware_build", "UNSET_RECORD_BEFORE_CAPTURE"),
        pending_limit=limits["pending_limit"],
        closed_limit=limits["closed_limit"],
        fragment_timeout_s=limits["timeout_s"],
        intervention_description=cfg.get("intervention_description", "no intentional intervention"),
        intervention_windows=cfg.get("intervention_windows", []),
        provenance=False,
    )
    compare_keys = (
        "wire_format",
        "wire_version",
        "profile",
        "profile_code",
        "mode",
        "mode_code",
        "policy",
        "policy_code",
        "policy_value",
        "period_ms",
        "tasks_count",
        "planned_slots",
        "slots",
        "k",
        "budget_us",
        "cost_per_attempt_us",
        "unused_per_task_us",
        "bursts_per_attempt",
        "burst_table",
        "planned_attempts",
        "planned_time_updates",
        "planned_silent_slots",
        "planned_waveform_us",
        "layout",
        "fragment_limits",
        "tasks",
        "board_command",
    )
    if cfg["profile"] == "time":
        compare_keys = compare_keys + (
            "ieee_marker_offset_us",
            "probes",
            "candidates",
            "observation_policy",
            "policies",
            "thresholds_us",
            "missing_policy",
            "quality_policy",
        )
    for key in compare_keys:
        if cfg.get(key) != expected.get(key):
            raise ValueError(f"UC1 config field mismatch: {key}")
    return cfg


def load(path: Path | str, run_id: int | None = None) -> dict:
    return validate(json.loads(Path(path).read_text(encoding="utf-8")), run_id=run_id)


def export_commands(
    cfg: dict,
    config_path: Path | str,
    *,
    experiment_dir: Path | str | None = None,
    analysis_id: str | None = None,
) -> dict[str, str]:
    """Generate exact board, BLE RX, ZigBee RX, and UC1 analysis commands."""
    validate(cfg)
    cfg_str = str(config_path)
    layout = cfg["layout"]
    dev = cfg["device_settings"]
    run_id = cfg["run_id"]
    dur = cfg["capture_duration_s"]
    iq_flag = "--save-iq" if dev["save_iq"] else "--no-save-iq"
    amp_flag = " --amp" if dev["amp"] else ""
    exp_arg = f" --experiment-dir {experiment_dir}" if experiment_dir else ""
    exp_dir_display = str(experiment_dir) if experiment_dir else f"python/experiments/<YYYYMMDD>_run{run_id}"
    aid = analysis_id or f"uc1_{cfg['mode'].lower()}_{cfg['profile']}"

    control_ble = " --control-target-id 1" if cfg["profile"] == "time" else ""
    control_zig = " --control-target-id 2" if cfg["profile"] == "time" else ""
    ble_layout = "joint" if cfg["mode"] == "JC" else "separate"

    ble_cmd = (
        f"python3 python/exadv_rx/receive.py --run-id {run_id}"
        f" --uc1-config {cfg_str}"
        f" --channels {layout['ble_channel']} --control-layout {ble_layout}"
        f" --sample-rate {dev['sample_rate']} --lna {dev['lna']} --vga {dev['vga']}{amp_flag}"
        f" --duration {dur} {iq_flag}{control_ble}{exp_arg}"
    )
    zig_cmd = (
        f"python3 python/zigbee_rx/control_receive.py --run-id {run_id}"
        f" --uc1-config {cfg_str}"
        f" --channel {layout['ieee_channel']} --control-layout {ble_layout}"
        f" --sample-rate {dev['sample_rate']} --lna {dev['lna']} --vga {dev['vga']}{amp_flag}"
        f" --duration {dur} {iq_flag}{control_zig}{exp_arg}"
    )
    analyze_cmd = (
        f"python3 python/control_match/uc1_analyze.py"
        f" --experiment-dir {exp_dir_display}"
        f" --config {cfg_str}"
        f" --analysis-id {aid}"
    )
    board_text = "\n".join(
        [
            f"# UC1 board command (sha256={cfg['sha256'][:16]}...)",
            f"# run_id={run_id} mode={cfg['mode']} profile={cfg['profile']} point={cfg['point']} b={layout['ble_extra']} z={layout['ieee_extra']}",
            f"# tasks={cfg['tasks_count']} slots={cfg['planned_slots']} K={cfg['k']} planned_attempts={cfg['planned_attempts']} planned_time_updates={cfg['planned_time_updates']} silent={cfg['planned_silent_slots']}",
            f"# cost_per_attempt_us={cfg['cost_per_attempt_us']} bursts_per_attempt={cfg['bursts_per_attempt']} planned_waveform_us={cfg['planned_waveform_us']} unused_per_task_us={cfg['unused_per_task_us']}",
            f"# board_duration_s={cfg['board_duration_s']} recommended_rx_duration_s={dur}",
            cfg["board_command"],
            "",
        ]
    )
    return {
        "board_text": board_text,
        "board_command": cfg["board_command"],
        "ble_rx": ble_cmd,
        "zigbee_rx": zig_cmd,
        "analyze": analyze_cmd,
    }


def dry_run_cost_table(budget_us: int = 6000) -> str:
    """Format verified UC1 design waveform budget table for representative points."""
    lines = [
        f"# UC1 Design Waveform Budget Table (Q={budget_us} us, non-RF design proxy)",
        "",
        "| Point | b,z | Records (B/Z B) | JC/SC us | LC us | Bursts (JC/SC/LC) | K@Q (JC/SC/LC) | Unused us (JC/SC/LC) |",
        "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for label, b, z in (("A", 0, 0), ("B1", 1, 0), ("B", 26, 0), ("C", 2, 6)):
        c_jc = uc1_cost(b, z, "JC")
        c_sc = uc1_cost(b, z, "SC")
        c_lc = uc1_cost(b, z, "LC")
        assert c_jc == c_sc
        n_jc = len(uc1_burst_table(b, z, "JC"))
        n_sc = len(uc1_burst_table(b, z, "SC"))
        n_lc = len(uc1_burst_table(b, z, "LC"))
        k_jc, k_sc, k_lc = budget_us // c_jc, budget_us // c_sc, budget_us // c_lc
        u_jc, u_sc, u_lc = budget_us - k_jc * c_jc, budget_us - k_sc * c_sc, budget_us - k_lc * c_lc
        lines.append(
            f"| {label} | {b},{z} | {26+b}/{26+z} | {c_jc} | {c_lc} | {n_jc}/{n_sc}/{n_lc} | "
            f"{k_jc}/{k_sc}/{k_lc} | {u_jc}/{u_sc}/{u_lc} |"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run-table", action="store_true", help="print UC1 A/B1/B/C cost table and exit")
    p.add_argument("--budget-preview-us", type=int, default=6000)
    p.add_argument("--run-id", type=int)
    p.add_argument("--mode", choices=("JC", "SC", "LC"), default="JC")
    p.add_argument("--profile", choices=("core", "time"), default="core")
    p.add_argument("--ble-extra", type=int, default=0)
    p.add_argument("--ieee-extra", type=int, default=0)
    p.add_argument("--tasks", type=int, default=100)
    p.add_argument("--period-ms", type=int, default=500)
    p.add_argument("--policy", choices=("k", "budget"), default="k")
    p.add_argument("--value", type=int, default=1)
    p.add_argument("--phase", default="P2")
    p.add_argument("--stage", default="verification")
    p.add_argument("--rf-condition", default="R0")
    p.add_argument("--block", type=int)
    p.add_argument("--sample-rate", type=int, default=4000000)
    p.add_argument("--lna", type=int, default=16)
    p.add_argument("--vga", type=int, default=16)
    p.add_argument("--amp", action="store_true")
    p.add_argument("--save-iq", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--firmware-build", default="UNSET_RECORD_BEFORE_CAPTURE")
    p.add_argument("--pending-limit", type=int, default=1024)
    p.add_argument("--closed-limit", type=int)
    p.add_argument("--fragment-timeout-s", type=float, default=2.0)
    p.add_argument("--intervention-description", default="no intentional intervention")
    p.add_argument("--intervention-window", nargs=2, type=int, action="append", default=[])
    p.add_argument("--allow-existing-run-id", action="store_true")
    p.add_argument("--output", type=Path, help="output manifest JSON path")
    p.add_argument("--board-commands", type=Path, help="optional board command file path")
    p.add_argument("--host-commands", type=Path, help="optional host RX/analysis commands file path")
    p.add_argument("--experiment-dir", type=Path)
    p.add_argument("--analysis-id")
    a = p.parse_args(argv)

    if a.dry_run_table:
        print(dry_run_cost_table(a.budget_preview_us))
        return 0

    if a.run_id is None or a.output is None:
        p.error("--run-id and --output are required unless --dry-run-table is set")

    if not a.allow_existing_run_id:
        occupied = used_run_ids()
        if a.run_id in occupied:
            p.error(f"run_id {a.run_id} already occupied by {occupied[a.run_id]}; pass --allow-existing-run-id only for dry-run")

    try:
        cfg = generate(
            a.run_id,
            mode=a.mode,
            profile=a.profile,
            ble_extra=a.ble_extra,
            ieee_extra=a.ieee_extra,
            tasks=a.tasks,
            period_ms=a.period_ms,
            policy=a.policy,
            value=a.value,
            phase=a.phase,
            stage=a.stage,
            rf_condition=a.rf_condition,
            block=a.block,
            sample_rate=a.sample_rate,
            lna=a.lna,
            vga=a.vga,
            amp=a.amp,
            save_iq=a.save_iq,
            firmware_build=a.firmware_build,
            pending_limit=a.pending_limit,
            closed_limit=a.closed_limit,
            fragment_timeout_s=a.fragment_timeout_s,
            intervention_description=a.intervention_description,
            intervention_windows=a.intervention_window,
        )
        validate(cfg, a.run_id)
    except ValueError as exc:
        p.error(str(exc))

    outputs = [p_out for p_out in (a.output, a.board_commands, a.host_commands) if p_out is not None]
    if len(set(outputs)) != len(outputs):
        p.error("output file paths must be distinct")
    for p_out in outputs:
        if p_out.exists():
            p.error(f"refusing to overwrite {p_out}")

    cmds = export_commands(cfg, a.output, experiment_dir=a.experiment_dir, analysis_id=a.analysis_id)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("x", encoding="utf-8") as handle:
        json.dump(cfg, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    if a.board_commands is not None:
        a.board_commands.parent.mkdir(parents=True, exist_ok=True)
        with a.board_commands.open("x", encoding="utf-8") as handle:
            handle.write(cmds["board_text"])
    if a.host_commands is not None:
        a.host_commands.parent.mkdir(parents=True, exist_ok=True)
        host_text = "\n".join(
            [
                f"# UC1 host RX & analysis commands (run_id={cfg['run_id']}, sha256={cfg['sha256'][:16]}...)",
                "# Start both receivers BEFORE sending the board serial command.",
                "",
                "# BLE receiver:",
                cmds["ble_rx"],
                "",
                "# IEEE 802.15.4 receiver:",
                cmds["zigbee_rx"],
                "",
                "# Joint analysis (after both captures and board.board.log are saved):",
                cmds["analyze"],
                "",
            ]
        )
        with a.host_commands.open("x", encoding="utf-8") as handle:
            handle.write(host_text)
    print(
        f"uc1_config run_id={cfg['run_id']} mode={cfg['mode']} profile={cfg['profile']} "
        f"K={cfg['k']} slots={cfg['planned_slots']} cost_per_attempt_us={cfg['cost_per_attempt_us']} "
        f"planned_waveform_us={cfg['planned_waveform_us']} sha256={cfg['sha256'][:12]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

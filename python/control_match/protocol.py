"""B2 43 v1 control record, shared by live and offline analysis."""
from __future__ import annotations

import binascii


def control_record(data: bytes) -> dict:
    """Parse one side's independently recovered 35-byte application record."""
    if len(data) != 35:
        raise ValueError("control_length")
    if data[:2] != b"\xb2\x43":
        raise ValueError("magic")
    record = {
        "magic": "b243", "version": data[2], "flags": data[3],
        "run_id": int.from_bytes(data[4:6], "little"),
        "slot_index": int.from_bytes(data[6:10], "little"),
        "ref_tick_ms": int.from_bytes(data[10:14], "little"),
        "period_ms": int.from_bytes(data[14:16], "little"),
        "command_id": int.from_bytes(data[16:20], "little"),
        "target_id": int.from_bytes(data[20:22], "little"),
        "opcode": data[22], "arg": int.from_bytes(data[23:25], "little"),
        "execute_at_ms": int.from_bytes(data[25:29], "little"),
        "valid_until_ms": int.from_bytes(data[29:33], "little"),
        "app_crc16": int.from_bytes(data[33:35], "little"),
    }
    if binascii.crc_hqx(data[:33], 0xffff) != record["app_crc16"]:
        raise ValueError("app_crc16")
    if record["version"] != 1:
        raise ValueError("version")
    if record["flags"] not in (0, 1):
        raise ValueError("flags")
    if record["run_id"] == 0 or record["period_ms"] == 0:
        raise ValueError("run_or_period")
    if record["slot_index"] * record["period_ms"] != record["ref_tick_ms"]:
        raise ValueError("reference_tick")
    if record["flags"] == 0:
        if any(record[key] for key in ("command_id", "target_id", "opcode", "arg",
                                      "execute_at_ms", "valid_until_ms")):
            raise ValueError("sync_only_fields")
    else:
        if (record["command_id"] == 0 or record["target_id"] == 0 or
                record["opcode"] not in (0, 1, 2) or
                (record["opcode"] == 0 and record["arg"] != 0) or
                record["ref_tick_ms"] > record["valid_until_ms"] or
                record["valid_until_ms"] >= record["execute_at_ms"]):
            raise ValueError("command_semantics")
    return record

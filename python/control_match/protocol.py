"""B2 43 v1/v2 control records, shared by live and offline analysis."""
from __future__ import annotations

import binascii


def control_record(data: bytes, side: str | None = None) -> dict:
    """Parse one side's independently recovered 35-byte application record."""
    if len(data) < 35:
        raise ValueError("control_length")
    version=data[2]
    if version not in (1,2):
        raise ValueError("version")
    length=35 if version==1 else 36+data[33]
    if len(data)!=length:
        raise ValueError("control_length")
    if version==2 and side not in ("ble","zigbee"):
        raise ValueError("v2_side_required")
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
        "app_crc16": int.from_bytes(data[-2:], "little"),
    }
    if binascii.crc_hqx(data[:-2], 0xffff) != record["app_crc16"]:
        raise ValueError("app_crc16")
    if version==2:
        extra=data[33]
        if extra>(26 if side=="ble" else 6):
            raise ValueError("capacity_length")
        expected=capacity_extension(record["run_id"],record["slot_index"],side,extra)
        if data[34:-2]!=expected:
            raise ValueError("capacity_content")
        record.update(record_bytes=len(data), extra_len=extra, extra_hex=data[34:-2].hex(),
                      capacity_content_ok=True,
                      ieee_marker_offset_us=(480+8*extra if side=="ble" else None))
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


def capacity_extension(run_id: int, slot: int, side: str, length: int) -> bytes:
    if side not in ("ble","zigbee"):
        raise ValueError("side")
    state=(0xB2430200 ^ (run_id<<16) ^ slot ^ ((1 if side=="ble" else 2)*0x9E3779B9))&0xffffffff
    out=bytearray()
    for _ in range(length):
        state=(state*1664525+1013904223)&0xffffffff
        out.append(state>>24)
    return bytes(out)


def ble_manufacturer_record(data: bytes, pdu_length: int) -> bytes:
    """Validate envelope sizes without decoding or reconstructing IEEE content."""
    if len(data)<37 or data[:4]!=b"\xff\xff\xb2\x43":
        raise ValueError("control_wire_budget")
    version=data[4]
    if version==1:
        if (pdu_length,len(data)) not in ((224,209),(52,37)):
            raise ValueError("control_wire_budget")
        return data[2:37]
    if version!=2:
        raise ValueError("version")
    ble_len=36+data[35]
    mapped=len(data)-2-ble_len
    if (not 229<=pdu_length<=255 or pdu_length!=15+len(data) or
            mapped<176 or mapped>200 or mapped%4 or data[35]+mapped-176>26):
        raise ValueError("control_wire_budget")
    return data[2:2+ble_len]

"""Extract a v1 record from one side's independently CRC/FCS-valid packet."""
from __future__ import annotations

try:
    from .analyze import extract_ble, extract_zigbee
    from .protocol import control_record
except ImportError:
    from analyze import extract_ble, extract_zigbee
    from protocol import control_record


def control_payload(packet: dict, side: str) -> bytes | None:
    if side == "ble":
        payload = extract_ble(packet)
        if payload is not None:
            try:
                record = control_record(payload)
            except ValueError:
                pass  # The engine reports the application-level rejection.
            else:
                did = packet.get("extended", {}).get("adi", {}).get("did")
                if did != (record["slot_index"] & 0xfff):
                    raise ValueError("BLE ADI/slot mismatch")
        return payload
    if side == "zigbee":
        return extract_zigbee(packet)
    raise ValueError("side must be ble or zigbee")

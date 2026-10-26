"""LE 1M advertising framing. No GNU Radio or hardware imports."""
from __future__ import annotations
from functools import lru_cache


def channel_frequency(channel: int) -> int:
    if channel in (37, 38, 39):
        return {37: 2402000000, 38: 2426000000, 39: 2480000000}[channel]
    if 0 <= channel <= 36:
        return (2404 + 2 * channel + (2 if channel >= 11 else 0)) * 1000000
    raise ValueError("BLE channel must be in 0..39")


def reverse8(value: int) -> int:
    return int(f"{value & 255:08b}"[::-1], 2)


_REVERSED = bytes(reverse8(value) for value in range(256))


def _crc_table_entry(value: int) -> int:
    state = value << 16
    for _ in range(8):
        state = ((state << 1) ^ (0x65B if state & 0x800000 else 0)) & 0xFFFFFF
    return state


_CRC_TABLE = tuple(_crc_table_entry(value) for value in range(256))


def crc24(data: bytes) -> bytes:
    # Advertising CRCInit=0x555555, polynomial x^24+x^10+x^9+x^6+x^4+x^3+x+1.
    state = 0x555555
    for byte in data:
        state = ((state << 8) & 0xFFFFFF) ^ _CRC_TABLE[(state >> 16) ^ _REVERSED[byte]]
    return bytes(_REVERSED[(state >> shift) & 255] for shift in (16, 8, 0))


@lru_cache(maxsize=128)
def _whitening_mask(channel: int, length: int) -> bytes:
    channel_frequency(channel)
    state = channel | 0x40
    result = bytearray()
    for _ in range(length):
        output = 0
        for bit in range(8):
            if state & 1:
                output ^= 1 << bit
                state ^= 0x88
            state >>= 1
        result.append(output)
    return bytes(result)


def whiten(data: bytes, channel: int) -> bytes:
    mask = _whitening_mask(channel, len(data))
    return bytes(byte ^ mask[index] for index, byte in enumerate(data))


def parse_ad(data: bytes) -> list[dict]:
    items = []
    pos = 0
    while pos < len(data) and data[pos]:
        end = pos + 1 + data[pos]
        if end > len(data):
            items.append({"malformed": True, "raw_hex": data[pos:].hex()})
            break
        kind, value = data[pos + 1], data[pos + 2:end]
        item = {"type": kind, "data_hex": value.hex()}
        if kind in (8, 9):
            item["name"] = value.decode("utf-8", errors="replace")
        if kind == 255 and len(value) >= 2:
            item["company_id"] = int.from_bytes(value[:2], "little")
        items.append(item)
        pos = end
    return items


def parse_extended(payload: bytes) -> dict:
    if not payload:
        raise ValueError("empty extended payload")
    length, mode = payload[0] & 63, payload[0] >> 6
    if mode == 3 or 1 + length > len(payload):
        raise ValueError("invalid extended header length or AdvMode")
    header = payload[1:1 + length]
    result = {"adv_mode": mode, "ext_header_length": length}
    flags = header[0] if header else 0
    if flags & 128:
        raise ValueError("reserved extended header flag")
    result["flags"] = flags
    pos = 1
    for mask, name, size in ((1, "adva", 6), (2, "targeta", 6),
                             (4, "cte_info", 1), (8, "adi", 2),
                             (16, "aux_ptr", 3), (32, "sync_info", 18),
                             (64, "tx_power", 1)):
        if not flags & mask:
            continue
        if pos + size > len(header):
            raise ValueError(f"truncated {name}")
        field = header[pos:pos + size]
        pos += size
        if name in ("adva", "targeta"):
            result[name] = ":".join(f"{b:02X}" for b in reversed(field))
        elif name == "adi":
            value = int.from_bytes(field, "little")
            result[name] = {"sid": value >> 12, "did": value & 4095}
        elif name == "aux_ptr":
            value = int.from_bytes(field, "little")
            channel, phy = value & 63, value >> 21
            if channel > 36 or phy > 2:
                raise ValueError("invalid AuxPtr channel or PHY")
            unit = 300 if value & 128 else 30
            offset = (value >> 8) & 8191
            result[name] = {"channel": channel, "ca": (value >> 6) & 1,
                            "offset_unit_us": unit, "offset_us": offset * unit,
                            "phy": phy, "phy_name": ("LE_1M", "LE_2M", "LE_CODED")[phy]}
        elif name == "tx_power":
            result[name] = int.from_bytes(field, "little", signed=True)
        else:
            result[name] = field.hex()
    # Remaining extended header bytes are ACAD, not advertising data.
    result["acad_hex"] = header[pos:].hex() if header else ""
    adv_data = payload[1 + length:]
    result["adv_data_hex"] = adv_data.hex()
    result["ad_structures"] = parse_ad(adv_data)
    return result


def parse_pdu(pdu: bytes, channel: int) -> dict:
    if len(pdu) < 2 or len(pdu) != 2 + pdu[1]:
        raise ValueError("PDU length mismatch")
    kind = pdu[0] & 15
    if kind != 7:
        raise ValueError("not an extended advertising PDU")
    ext = parse_extended(pdu[2:])
    # Secondary PDU subtypes share type 7; do not guess ADV vs CHAIN from flags.
    role = "primary" if channel >= 37 else "auxiliary"
    if channel >= 37 and ext["adv_data_hex"]:
        role = "same_channel_auxiliary_diagnostic"
    return {"channel": channel, "kind": role, "pdu_type": kind,
            "pdu_length": pdu[1], "pdu_hex": pdu.hex(), "crc_ok": True,
            "extended": ext}


class EventMatcher:
    """Match only on one continuous IQ timeline; never use host arrival time."""
    def __init__(self, tolerance_us: float = 20):
        self.tolerance_us = tolerance_us
        self.pending: list[dict] = []
        self.matched = 0
        self.expired = 0

    def feed(self, packet: dict) -> list[dict]:
        now = packet["sample_time_s"] * 1e6
        keep = []
        for primary in self.pending:
            aux = primary["extended"]["aux_ptr"]
            latest = (primary["sample_time_s"] * 1e6 + aux["offset_us"]
                      + aux["offset_unit_us"] + self.tolerance_us)
            if now > latest:
                self.expired += 1
            else:
                keep.append(primary)
        self.pending = keep
        matches = []
        if packet["kind"] == "auxiliary":
            for primary in self.pending[:]:
                aux = primary["extended"]["aux_ptr"]
                delta = now - primary["sample_time_s"] * 1e6
                if aux["channel"] != packet["channel"] or aux["phy"] != 0:
                    continue
                # Require identity evidence, not merely an approximate time match.
                pri, sec = primary["extended"], packet["extended"]
                common = [key for key in ("adi", "adva") if key in pri and key in sec]
                if not common or any(pri[key] != sec[key] for key in common):
                    continue
                if (aux["offset_us"] - self.tolerance_us <= delta <=
                        aux["offset_us"] + aux["offset_unit_us"] + self.tolerance_us):
                    self.pending.remove(primary)
                    self.matched += 1
                    matches.append({"primary_packet": primary["packet_no"],
                                    "auxiliary_packet": packet["packet_no"],
                                    "delta_us": delta, "aux_ptr": aux})
        aux = packet["extended"].get("aux_ptr")
        if packet["kind"] == "primary" and aux and aux["offset_us"]:
            self.pending.append(packet)
        return matches

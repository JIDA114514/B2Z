"""Historical C1/C2 and unified UC1/C3 decoding and bounded local BLE reassembly.

All decoding and reassembly uses only this side's independently received,
outer-CRC-valid packets. No cross-side input or wall clock is used.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
import binascii
import hashlib
import math

MAX_PENDING_LIMIT = 65536
MAX_CLOSED_LIMIT = 1_000_000


def uc1_extension(run_id: int, command_id: int, side: str, length: int) -> bytes:
    """Frozen UC1 command test-fill LCG (stable across retries; independent of slot)."""
    if side not in ("ble", "zigbee"):
        raise ValueError("side")
    if length < 0:
        raise ValueError("uc1_length")
    side_code = 1 if side == "ble" else 2
    state = (
        0xB2430100
        ^ ((run_id & 0xFFFF) << 16)
        ^ (command_id & 0xFFFFFFFF)
        ^ (side_code * 0x9E3779B9)
    ) & 0xFFFFFFFF
    out = bytearray()
    for _ in range(length):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        out.append(state >> 24)
    return bytes(out)


def compact_record(data: bytes, side: str) -> dict:
    """Parse historical C1 (0xC1 0x01) records; kept isolated from UC1."""
    try:
        from .protocol import capacity_extension
    except ImportError:
        from protocol import capacity_extension
    if side not in ("ble", "zigbee") or len(data) < 26 or data[0] != 0xC1:
        raise ValueError("compact_shape")
    if data[1] != 0x01:
        raise ValueError("compact_semantics")
    n = data[23]
    if n > (26 if side == "ble" else 6) or len(data) != 26 + n:
        raise ValueError("compact_length")
    if binascii.crc_hqx(data[:-2], 0xFFFF) != int.from_bytes(data[-2:], "little"):
        raise ValueError("app_crc16")
    u = lambda a, b: int.from_bytes(data[a:b], "little")
    run, slot, period, command = u(2, 4), u(4, 8), u(8, 10), u(10, 14)
    ref = slot * period
    valid = ref + u(19, 21)
    execute = ref + u(21, 23)
    target, opcode, arg = u(14, 16), data[16], u(17, 19)
    if (
        not run
        or not period
        or not command
        or not target
        or opcode > 2
        or (opcode == 0 and arg != 0)
        or not ref <= valid < execute <= 0xFFFFFFFF
    ):
        raise ValueError("compact_semantics")
    if data[24:-2] != capacity_extension(run, slot, side, n):
        raise ValueError("capacity_content")
    return dict(
        magic="c1",
        version=3,
        wire_format="C1",
        wire_version=1,
        format="C1",
        flags=1,
        run_id=run,
        slot_index=slot,
        ref_tick_ms=ref,
        period_ms=period,
        command_id=command,
        target_id=target,
        opcode=opcode,
        arg=arg,
        execute_at_ms=execute,
        valid_until_ms=valid,
        app_crc16=u(len(data) - 2, len(data)),
        record_bytes=len(data),
        extra_len=n,
        extra_hex=data[24:-2].hex(),
        capacity_content_ok=True,
        ieee_marker_offset_us=None,
        timing_eligible=False,
    )


def uc1_record(
    data: bytes,
    side: str,
    layout: dict | None = None,
    *,
    verify_test_fill: bool = False,
) -> dict:
    """Parse UC1 (0xC1 0x10 pure time update / 0xC1 0x11 command) record.

    Protocol validity is checked separately from deterministic test-fill checks.
    Missing or mismatched layout keeps decoding valid with timing_eligible=False.
    """
    if side not in ("ble", "zigbee") or len(data) < 26 or data[0] != 0xC1:
        raise ValueError("uc1_shape")
    ver_type = data[1]
    if ver_type not in (0x10, 0x11):
        raise ValueError("unknown_c1_version_type")
    n = data[23]
    if n > (26 if side == "ble" else 6) or len(data) != 26 + n:
        raise ValueError("uc1_length")
    if binascii.crc_hqx(data[:-2], 0xFFFF) != int.from_bytes(data[-2:], "little"):
        raise ValueError("app_crc16")
    u = lambda a, b: int.from_bytes(data[a:b], "little")
    run = u(2, 4)
    slot = u(4, 8)
    period = u(8, 10)
    command = u(10, 14)
    target = u(14, 16)
    opcode = data[16]
    arg = u(17, 19)
    valid_off = u(19, 21)
    exec_off = u(21, 23)
    if run == 0 or period == 0:
        raise ValueError("uc1_run_or_period")
    ref = slot * period
    if ref > 0xFFFFFFFF:
        raise ValueError("uc1_ref_overflow")
    extra_bytes = data[24:-2]
    flags = ver_type & 0x0F
    if flags == 0:
        if any((command, target, opcode, arg, valid_off, exec_off)):
            raise ValueError("uc1_sync_only_fields")
        if extra_bytes != bytes(n):
            raise ValueError("uc1_sync_padding_nonzero")
        valid = 0
        execute = 0
        test_fill_ok = True
    else:
        if command == 0 or target == 0 or opcode > 2 or (opcode == 0 and arg != 0):
            raise ValueError("uc1_command_semantics")
        valid = ref + valid_off
        execute = ref + exec_off
        if not (ref <= valid < execute <= 0xFFFFFFFF):
            raise ValueError("uc1_time_bounds")
        test_fill_ok = extra_bytes == uc1_extension(run, command, side, n)
        if verify_test_fill and not test_fill_ok:
            raise ValueError("uc1_test_fill")

    layout_match: bool | None = None
    timing_eligible = False
    ieee_marker_offset_us: int | None = None
    if layout is not None:
        side_key = "ble_extra" if side == "ble" else "ieee_extra"
        expected_n = layout.get(side_key)
        expected_period = layout.get("period_ms")
        expected_run = layout.get("run_id")
        match = expected_n is not None and n == int(expected_n)
        if expected_period is not None:
            match = match and period == int(expected_period)
        if expected_run is not None:
            match = match and run == int(expected_run)
        layout_match = match
        if (
            match
            and layout.get("mode") == "JC"
            and layout.get("marker_offset_valid")
            and layout.get("ble_extra") is not None
        ):
            expected_offset = 400 + 8 * int(layout["ble_extra"])
            if layout.get("marker_offset_us") == expected_offset:
                ieee_marker_offset_us = expected_offset
                timing_eligible = True

    return dict(
        magic="c1",
        version="UC1",
        wire_format="UC1",
        wire_version=1,
        format="UC1",
        version_type=ver_type,
        flags=flags,
        run_id=run,
        slot_index=slot,
        ref_tick_ms=ref,
        period_ms=period,
        command_id=command,
        target_id=target,
        opcode=opcode,
        arg=arg,
        execute_at_ms=execute,
        valid_until_ms=valid,
        valid_offset_ms=valid_off,
        execute_offset_ms=exec_off,
        app_crc16=u(len(data) - 2, len(data)),
        record_bytes=len(data),
        extra_len=n,
        extra_hex=extra_bytes.hex(),
        test_fill_ok=test_fill_ok,
        layout_match=layout_match,
        timing_eligible=timing_eligible,
        ieee_marker_offset_us=ieee_marker_offset_us,
    )


class BLEControlExtractor:
    """Reassemble only outer-CRC-valid legacy frames (historical C2 and UC1 C3).

    Timeout uses local IQ sample_time_s (no wall clock).
    - Historical C2 uses (AdvA, run_id, command_id) with bounded LRU closed tombstones.
    - UC1 C3 uses (AdvA, run_id, slot_index, command_id) with independent pending_limit
      and closed_limit, reserving a closed slot upon pending admission so
      len(c3_closed) + len(c3_pending) <= closed_limit and closed entries never evict.
    """

    def __init__(
        self,
        timeout: float = 2.0,
        limit: int = 1024,
        *,
        pending_limit: int | None = None,
        closed_limit: int | None = None,
        allowed_run_id: int | None = None,
        allowed_senders: set[str] | frozenset[str] | None = None,
        layout: dict | None = None,
    ):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("fragment timeout must be finite and positive")
        if type(limit) is not int or not 1 <= limit <= MAX_PENDING_LIMIT:
            raise ValueError("invalid legacy fragment limit")
        p_lim = limit if pending_limit is None else pending_limit
        c_lim = max(limit, 4096) if closed_limit is None else closed_limit
        if type(p_lim) is not int or not 1 <= p_lim <= MAX_PENDING_LIMIT:
            raise ValueError("invalid pending_limit")
        if type(c_lim) is not int or not 1 <= c_lim <= MAX_CLOSED_LIMIT:
            raise ValueError("invalid closed_limit")
        if allowed_run_id is not None and (type(allowed_run_id) is not int or not 1 <= allowed_run_id <= 65535):
            raise ValueError("invalid allowed_run_id")
        self.timeout = float(timeout)
        self.limit = limit
        self.pending_limit = p_lim
        self.closed_limit = c_lim
        self.allowed_run_id = allowed_run_id
        self.allowed_senders = frozenset(allowed_senders) if allowed_senders is not None else None
        self.layout = layout
        self.pending: OrderedDict = OrderedDict()
        self.closed: OrderedDict = OrderedDict()
        self.counts: Counter = Counter()
        self.last_time: float | None = None
        self.closed_exhausted = False

    def reset(
        self,
        *,
        allowed_run_id: int | None = None,
        allowed_senders: set[str] | frozenset[str] | None = None,
        layout: dict | None = None,
    ) -> None:
        """Controlled run switch: explicitly clear queues and update allowed scope."""
        if allowed_run_id is not None and (type(allowed_run_id) is not int or not 1 <= allowed_run_id <= 65535):
            raise ValueError("invalid allowed_run_id")
        self.allowed_run_id = allowed_run_id
        self.allowed_senders = frozenset(allowed_senders) if allowed_senders is not None else None
        self.layout = layout
        self.pending.clear()
        self.closed.clear()
        self.counts.clear()
        self.last_time = None
        self.closed_exhausted = False

    def _update_peaks(self) -> None:
        self.counts["pending_peak"] = max(self.counts["pending_peak"], len(self.pending))
        self.counts["closed_peak"] = max(self.counts["closed_peak"], len(self.closed))

    def _c3_counts(self) -> tuple[int, int]:
        p = sum(1 for k in self.pending if len(k) == 4)
        c = sum(1 for k in self.closed if len(k) == 4)
        return p, c

    def _close_c2(self, key, value=True) -> None:
        self.closed[key] = value
        # Only evict historical C2 (3-tuple) tombstones; never evict C3 (4-tuple) entries.
        c2_keys = [k for k in self.closed if len(k) == 3]
        while len(c2_keys) > self.limit:
            oldest = c2_keys.pop(0)
            del self.closed[oldest]
        self._update_peaks()

    def _close_c3(self, key, reason: str, now: float | None, total: int, count: int,
                  part_hashes: dict[int, bytes] | None = None) -> None:
        self.closed[key] = {
            "reason": reason,
            "at": now,
            "total": total,
            "count": count,
            "part_hashes": part_hashes or {},
        }
        self._update_peaks()

    def expire(self, now: float) -> None:
        for key, state in list(self.pending.items()):
            if now - state["first"] >= self.timeout:
                del self.pending[key]
                if len(key) == 4:
                    self._close_c3(key, "timeout", now, state["total"], state["count"])
                else:
                    self._close_c2(key)
                self.counts["timeout"] += 1

    def finish(self) -> None:
        for key, state in list(self.pending.items()):
            del self.pending[key]
            if len(key) == 4:
                self._close_c3(key, "incomplete_at_end", self.last_time, state["total"], state["count"])
            self.counts["incomplete_at_end"] += 1
        self.pending.clear()
        self._update_peaks()

    def _handle_c3(self, packet: dict, data: bytes, now: float) -> bytes | None:
        self.counts["fragments"] += 1
        self.counts["c3_fragments"] += 1
        if len(data) < 16:
            raise ValueError("c3_fragment_header")
        if data[1] != 1:
            raise ValueError("c3_fragment_version")
        run = int.from_bytes(data[2:4], "little")
        slot = int.from_bytes(data[4:8], "little")
        command = int.from_bytes(data[8:12], "little")
        index, count, total = data[12], data[13], data[14]
        expected_count = (total + 11) // 12
        expected_chunk = min(12, total - index * 12)
        if (
            not run
            or not 28 <= total <= 52
            or count != expected_count
            or index >= count
            or expected_chunk <= 0
            or len(data) != 15 + expected_chunk
        ):
            raise ValueError("c3_fragment_shape")
        sender = packet["extended"].get("adva")
        if not sender:
            raise ValueError("fragment_sender")
        if self.allowed_run_id is not None and run != self.allowed_run_id:
            self.counts["foreign_run_fragment"] += 1
            return None
        if self.allowed_senders is not None and sender not in self.allowed_senders:
            self.counts["foreign_sender_fragment"] += 1
            return None
        chunk = data[15:]
        chunk_hash = hashlib.sha256(chunk).digest()[:8]
        key = (sender, run, slot, command)

        if key in self.closed:
            old = self.closed[key]
            if (old["total"], old["count"]) != (total, count) or (
                old["part_hashes"] and old["part_hashes"].get(index) != chunk_hash
            ):
                self.counts["closed_conflict"] += 1
                self.counts["conflict"] += 1
                raise ValueError("c3_closed_conflict")
            self.counts["closed_duplicate"] += 1
            return None

        if key not in self.pending:
            c3_pending, c3_closed = self._c3_counts()
            # Invariant: len(c3_closed) + len(c3_pending) <= closed_limit.
            if c3_closed + c3_pending >= self.closed_limit:
                self.closed_exhausted = True
                self.counts["closed_capacity_exhausted"] += 1
                return None
            if c3_pending >= self.pending_limit:
                self._close_c3(key, "pending_overflow", now, total, count)
                self.counts["pending_overflow"] += 1
                return None
            self.pending[key] = dict(first=now, total=total, count=count, parts={})
            self._update_peaks()

        state = self.pending[key]
        parts = state["parts"]
        if (state["total"], state["count"]) != (total, count) or (index in parts and parts[index] != chunk):
            del self.pending[key]
            self._close_c3(key, "conflict", now, state["total"], state["count"])
            self.counts["conflict"] += 1
            raise ValueError("c3_fragment_conflict")
        if index in parts:
            self.counts["duplicate"] += 1
            return None
        parts[index] = chunk
        if len(parts) != count:
            return None

        # Atomic transition from pending to closed; free raw fragment storage immediately.
        record = b"".join(parts[i] for i in range(count))
        part_hashes = {i: hashlib.sha256(parts[i]).digest()[:8] for i in range(count)}
        del self.pending[key]
        self._close_c3(key, "complete", now, total, count, part_hashes=part_hashes)
        try:
            decoded = uc1_record(record, "ble", layout=self.layout)
        except ValueError as exc:
            self.closed[key]["reason"] = "invalid_reassembled_record"
            self.counts["invalid_reassembled"] += 1
            raise ValueError(f"c3_fragment_record:{exc}") from exc
        if (decoded["run_id"], decoded["slot_index"], decoded["command_id"]) != (run, slot, command):
            self.closed[key]["reason"] = "fragment_identity_mismatch"
            self.counts["invalid_reassembled"] += 1
            raise ValueError("c3_fragment_identity")
        packet["compact_reassembly"] = {
            "protocol": "C3",
            "first_sample_time_s": state["first"],
            "last_sample_time_s": now,
            "span_s": now - state["first"],
            "fragment_count": count,
            "slot_index": slot,
            "command_id": command,
        }
        self.counts["complete"] += 1
        return record

    def _handle_c2(self, packet: dict, data: bytes, now: float) -> bytes | None:
        self.counts["fragments"] += 1
        if len(data) < 11:
            raise ValueError("fragment_header")
        run = int.from_bytes(data[1:3], "little")
        command = int.from_bytes(data[3:7], "little")
        index, count, total = data[7:10]
        if (
            not run
            or not command
            or not 28 <= total <= 52
            or count != (total + 16) // 17
            or index >= count
            or len(data) != 10 + min(17, total - index * 17)
        ):
            raise ValueError("fragment_shape")
        sender = packet["extended"].get("adva")
        if not sender:
            raise ValueError("fragment_sender")
        key = (sender, run, command)
        if key in self.closed:
            old = self.closed[key]
            if isinstance(old, dict) and (
                (old["total"], old["count"]) != (total, count) or old["parts"].get(index) != data[10:]
            ):
                self.counts["conflict"] += 1
                raise ValueError("fragment_conflict")
            self.counts["closed_duplicate"] += 1
            return None
        if key not in self.pending:
            c2_pending = [k for k in self.pending if len(k) == 3]
            if len(c2_pending) >= self.limit:
                old = c2_pending[0]
                del self.pending[old]
                self._close_c2(old)
                self.counts["evicted"] += 1
            self.pending[key] = dict(first=now, total=total, count=count, parts={})
            self._update_peaks()
        state = self.pending[key]
        parts = state["parts"]
        if (state["total"], state["count"]) != (total, count) or (index in parts and parts[index] != data[10:]):
            del self.pending[key]
            self._close_c2(key)
            self.counts["conflict"] += 1
            raise ValueError("fragment_conflict")
        if index in parts:
            self.counts["duplicate"] += 1
        parts[index] = data[10:]
        if len(parts) != count:
            return None
        del self.pending[key]
        self._close_c2(key, state)
        record = b"".join(parts[i] for i in range(count))
        decoded = compact_record(record, "ble")
        if (decoded["run_id"], decoded["command_id"]) != (run, command):
            raise ValueError("fragment_identity")
        packet["compact_reassembly"] = {
            "first_sample_time_s": state["first"],
            "last_sample_time_s": now,
            "span_s": now - state["first"],
            "fragment_count": count,
        }
        self.counts["complete"] += 1
        return record

    def __call__(self, packet: dict) -> bytes | None:
        try:
            from .analyze import extract_ble
        except ImportError:
            from analyze import extract_ble
        if packet.get("kind") != "legacy":
            return extract_ble(packet)
        if not packet.get("crc_ok"):
            return None
        ads = packet.get("extended", {}).get("ad_structures", [])
        candidates = [
            bytes.fromhex(a["data_hex"])[2:]
            for a in ads
            if a.get("type") == 255 and a.get("company_id") == 65535
        ]
        if not candidates:
            return None
        if len(candidates) != 1:
            raise ValueError("compact_legacy_ad")
        data = candidates[0]
        if not data or data[0] not in (0xC1, 0xC2, 0xC3):
            return None
        now = float(packet["sample_time_s"])
        if not math.isfinite(now) or now < 0:
            raise ValueError("fragment_time_order")
        if self.last_time is not None and now < self.last_time:
            self.counts["time_regression"] += 1
            raise ValueError("fragment_time_order")
        self.last_time = now
        self.expire(now)
        if data[0] == 0xC1:
            if len(data) > 27:
                raise ValueError("legacy_record_length")
            if len(data) < 2:
                raise ValueError("compact_shape")
            if data[1] == 0x01:
                compact_record(data, "ble")
                return data
            if data[1] in (0x10, 0x11):
                uc1_record(data, "ble", layout=self.layout)
                return data
            raise ValueError("unknown_c1_version_type")
        if data[0] == 0xC3:
            return self._handle_c3(packet, data, now)
        return self._handle_c2(packet, data, now)

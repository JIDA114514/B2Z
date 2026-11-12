"""Audit buffered DMA observations; waveform budgets are not measured RF airtime."""
from __future__ import annotations


def read_bursts(matching, stats: dict, slots: dict, capacity: dict | None = None) -> dict | None:
    rows = matching("CONTROL_BURST")
    totals = matching("CONTROL_COST_STATS")
    separate = stats.get("rf_mode") == "separate_secondary_ch3"
    if not rows and not totals and not separate:
        return None  # Historical logs cannot support measured submission costs.
    if len(totals) != 1:
        raise ValueError("one complete CONTROL_COST_STATS is required")
    kinds = {"primary": 136, "secondary": 496 if separate else 1872}
    if separate:
        kinds["ieee"] = 1376
    if capacity is not None:
        # read_plan has already checked config and actual per-slot lengths.
        # LE 1M: payload + 2-byte PDU header + preamble/AA (5) + CRC (3).
        payload=int(capacity["pdu_payload_bytes"])
        if separate or capacity.get("version")!="2" or not 229<=payload<=255:
            raise ValueError("invalid capacity waveform configuration")
        kinds["secondary"]=(payload+10)*8

    parsed = {}
    integers = ("slot", "generated", "attempted", "started", "completed", "timeout",
                "iq_bytes", "air_us", "pad_us", "prepared_us", "submit_before_us",
                "submit_after_us", "finish_us")
    for raw in rows:
        row = {k: int(raw[k]) for k in integers}
        kind, slot = raw["kind"], row["slot"]
        key = (slot, kind)
        if slot not in slots or kind not in kinds or key in parsed or any(v < 0 for v in row.values()):
            raise ValueError("duplicate, unknown or invalid burst")
        row["kind"] = kind
        g, a, s, c, t = (row[k] for k in ("generated", "attempted", "started", "completed", "timeout"))
        if any(v not in (0, 1) for v in (g, a, s, c, t)) or not c <= s <= a <= g or t != s - c:
            raise ValueError("inconsistent burst lifecycle")
        if g:
            if row["air_us"] != kinds[kind] or row["pad_us"] != 10 or row["iq_bytes"] <= 0:
                raise ValueError("burst waveform budget differs from " +
                                 ("validated v2 capacity format" if capacity is not None else "frozen N2 format"))
        elif any(row[k] for k in integers if k != "slot"):
            raise ValueError("ungenerated burst has observations")
        if a and not row["prepared_us"] <= row["submit_before_us"] <= row["submit_after_us"]:
            raise ValueError("invalid DMA submission bracket")
        if s and row["finish_us"] < row["submit_after_us"]:
            raise ValueError("invalid DMA completion observation")
        row["outcome"] = ("completed" if c else "dma_timeout" if t else
                          "submit_failed" if a else "not_attempted" if g else "not_generated")
        parsed[key] = row
    if len(parsed) != len(slots) * len(kinds):
        raise ValueError("missing CONTROL_BURST rows, including unsent bursts")
    for slot, board in slots.items():
        if any(parsed[slot, kind]["generated"] != board["board_generated"] for kind in kinds):
            raise ValueError("burst generation disagrees with plan slot")
        for kind, metric in (("primary", "primary_completed"), ("secondary", "tx_completed")):
            expected = board["board_tx_completed"] if metric == "tx_completed" else board["board_primary_completed"]
            if parsed[slot, kind]["completed"] != expected:
                raise ValueError("burst completion disagrees with plan slot")
        ordered = [parsed[slot, k] for k in kinds if parsed[slot, k]["attempted"]]
        if any(b["submit_before_us"] < a["finish_us"] for a, b in zip(ordered, ordered[1:])):
            raise ValueError("overlapping sequential DMA observations")
        if separate and parsed[slot, "ieee"]["attempted"]:
            ble = parsed[slot, "secondary"]
            if not ble["completed"] or parsed[slot, "ieee"]["submit_before_us"] - ble["finish_us"] < 1000:
                raise ValueError("separate burst lacks BLE completion or minimum software gap")
        board["board_ble_tx_completed"] = parsed[slot, "secondary"]["completed"]
        board["board_ieee_tx_completed"] = parsed[slot, "ieee" if separate else "secondary"]["completed"]
    counts = {"logical_slots": len(slots),
              "ble_tx_completed": sum(r["board_ble_tx_completed"] for r in slots.values()),
              "ieee_tx_completed": sum(r["board_ieee_tx_completed"] for r in slots.values()),
              **{f"burst_{name}": sum(r[name] for r in parsed.values()) for name in ("attempted", "started", "completed")}}
    if any(int(totals[0][k]) != v for k, v in counts.items()):
        raise ValueError("burst totals disagree with CONTROL_COST_STATS")
    return {"rows": list(parsed.values()), "counts": counts, "separate": separate,
            "planned_waveform_us": sum(kinds.values()) * len(slots)}


def cost_summary(bursts: dict, successful_tasks: int) -> dict:
    rows = bursts["rows"]
    submitted = sum(r["air_us"] for r in rows if r["started"])
    padding = sum(r["pad_us"] for r in rows if r["started"])
    attempted = sum(r["air_us"] for r in rows if r["attempted"])
    return {"schema": "b2z_waveform_cost_v1", "mode": "separate_bluebee" if bursts["separate"] else "joint",
            **bursts["counts"], "planned_waveform_us": bursts["planned_waveform_us"],
            "submitted_waveform_us": submitted, "submitted_zero_padding_us": padding,
            "attempted_waveform_budget_us": attempted,
            "uncertain_bursts": sum(r["attempted"] and not r["completed"] for r in rows),
            "per_joint_decoded_task": {"numerator_us": submitted, "denominator": successful_tasks,
                                      "value_us": submitted / successful_tasks if successful_tasks else None},
            "actual_rf_airtime_us": None,
            "scope": "All slots including sync-only, repeats and failed DMA completions; successful DMA start allocates full waveform. Failed submissions listed separately; actual emitted fraction unknown. Padding is zero IQ, not proof of zero RF energy."}

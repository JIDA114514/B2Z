import unittest

from python.control_match.holdover_analyze import VALIDATION, candidate_slots, evaluate


def side(intercept, slope):
    return {"by_slot": {slot: {"record": {"ref_tick_ms": slot * 200},
                               "sample_start": (intercept + slope * slot * .2) * 4_000_000}
                        for slot in range(300)}}


class HoldoverAnalysisTests(unittest.TestCase):
    def test_validation_slots_never_used_as_periodic_updates(self):
        for mode in ("common", "disjoint"):
            for receiver in ("ble", "zigbee"):
                for interval in (None, 5, 25, 50):
                    self.assertFalse(set(VALIDATION) & set(candidate_slots(mode, receiver, interval)))

    def test_independent_linear_clocks_recover_common_reference(self):
        summaries, rows = evaluate(side(3.0, 1.00001), side(4.0, .99999),
                                   {"ble": 4_000_000, "zigbee": 4_000_000})
        self.assertEqual(len(summaries), 32)
        self.assertTrue(all(item["conditional_count"] == 168 for item in summaries))
        self.assertTrue(all(item["max_abs_us"] < .001 for item in summaries
                            if item["packets_per_side"] >= 2))
        self.assertEqual(len(rows), 32 * 168)

    def test_validation_packet_cannot_change_training_fit(self):
        ble, zigbee = side(3.0, 1.00001), side(4.0, .99999)
        _, baseline = evaluate(ble, zigbee, {"ble": 4_000_000, "zigbee": 4_000_000})
        ble["by_slot"][22]["sample_start"] += 40_000
        _, changed = evaluate(ble, zigbee, {"ble": 4_000_000, "zigbee": 4_000_000})
        before = next(r for r in baseline if r["mode"] == "disjoint" and
                      r["policy"] == "periodic_1s" and r["packets_per_side"] == 5 and
                      r["validation_slot"] == 22)
        after = next(r for r in changed if r["mode"] == "disjoint" and
                     r["policy"] == "periodic_1s" and r["packets_per_side"] == 5 and
                     r["validation_slot"] == 22)
        self.assertEqual(before["ble_training_slots"], after["ble_training_slots"])
        self.assertEqual(before["ble_slope_ppm"], after["ble_slope_ppm"])
        self.assertAlmostEqual(after["relative_error_us"] - before["relative_error_us"],
                               10_000 / 1.00001, places=3)


if __name__ == "__main__":
    unittest.main()

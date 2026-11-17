"""Uniform-K registration must match the actual board slot plan."""
import copy
import unittest

from control_match.n5_config import board_commands, digest, generate, validate


class UniformKConfigTests(unittest.TestCase):
    def test_legacy_mixed_plan_stays_compatible(self):
        config = generate(2509)
        self.assertNotIn('uniform_k', config)
        self.assertEqual([t['attempts'] for t in config['tasks']], [1, 3, 3, 5, 3, 3])
        self.assertIs(validate(config, 2509), config)

    def test_uniform_plans_cover_300_slots_and_preserve_first_slots(self):
        expected_fill = {1: [70, 19, 59, 39, 49, 29, 29],
                         3: [70, 17, 57, 37, 47, 27, 27],
                         5: [70, 15, 55, 35, 45, 25, 25]}
        for k in (1, 3, 5):
            with self.subTest(k=k):
                config = generate(2518 + k, uniform_k=k)
                self.assertIs(validate(config, 2518 + k), config)
                self.assertEqual([t['first_slot'] for t in config['tasks']],
                                 [70, 90, 150, 190, 240, 270])
                self.assertEqual([t['attempts'] for t in config['tasks']], [k] * 6)
                lines = board_commands(config).splitlines()
                entries = [line.split() for line in lines if line.startswith('b2z_plan_add?')]
                self.assertEqual(len(entries), 13)
                self.assertEqual([int(x[2]) for x in entries[::2]], expected_fill[k])
                self.assertEqual([int(x[2]) for x in entries[1::2]], [k] * 6)
                self.assertEqual(sum(int(x[2]) for x in entries), 300)
                self.assertEqual(lines[-1], f'b2z_plan_start? {2518 + k} 500 1')

    def test_reject_invalid_or_forged_k(self):
        for k in (0, 2, 4, True):
            with self.subTest(k=k), self.assertRaises(ValueError):
                generate(2518, uniform_k=k)
        config = generate(2518, uniform_k=3)
        forged = copy.deepcopy(config)
        forged['tasks'][0]['attempts'] = 1
        forged['sha256'] = digest(forged)
        with self.assertRaisesRegex(ValueError, 'tasks'):
            validate(forged, 2518)


if __name__ == '__main__':
    unittest.main()

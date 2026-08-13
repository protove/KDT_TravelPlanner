import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts/loadtest/validate-rehearsal-config.py"
SPEC = importlib.util.spec_from_file_location("validate_rehearsal_config", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class RehearsalConfigTest(unittest.TestCase):
    def test_duration_parser_accepts_compound_units(self):
        self.assertEqual(MODULE.duration_seconds("2m30s"), 150)
        self.assertEqual(MODULE.duration_seconds("500ms"), 0.5)

    def test_warmup_must_be_whole_minutes(self):
        with self.assertRaises(ValueError):
            MODULE.validate(
                mode="recovery",
                warmup="30s",
                baseline="10m",
                recovery="6m",
                drill_at_min=2,
            )

    def test_recovery_requires_three_minutes_after_drill(self):
        with self.assertRaises(ValueError):
            MODULE.validate(
                mode="recovery",
                warmup="3m",
                baseline="10m",
                recovery="10m",
                drill_at_min=8,
            )

    def test_recovery_drill_must_start_after_warmup(self):
        with self.assertRaises(ValueError):
            MODULE.validate(
                mode="recovery",
                warmup="3m",
                baseline="10m",
                recovery="7m",
                drill_at_min=2,
            )

    def test_recovery_with_three_minute_observation_is_valid(self):
        MODULE.validate(
            mode="recovery",
            warmup="3m",
            baseline="10m",
            recovery="11m",
            drill_at_min=8,
        )

    def test_spike_does_not_require_recovery_window(self):
        MODULE.validate(
            mode="spike",
            warmup="3m",
            baseline="10m",
            recovery="1m",
            drill_at_min=8,
        )


if __name__ == "__main__":
    unittest.main()

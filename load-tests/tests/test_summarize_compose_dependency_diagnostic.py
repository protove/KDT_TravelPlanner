from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts/loadtest/summarize-compose-dependency-diagnostic.py"
SPEC = importlib.util.spec_from_file_location("summarize_compose_dependency_diagnostic", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def point(metric: str, when: datetime, value: float, tags: dict[str, str]) -> str:
    return json.dumps({"type": "Point", "metric": metric, "data": {"time": when.isoformat().replace("+00:00", "Z"), "value": value, "tags": tags}})


class SummaryDiagnosticTest(unittest.TestCase):
    def test_spearman_detects_growing_item_count(self) -> None:
        self.assertGreater(MODULE.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 0.99)

    def test_run_summary_calculates_last_quartile_degradation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "replicate-1" / "growing-cardinality-mixed"
            run.mkdir(parents=True)
            (run / "metadata.json").write_text(json.dumps({"replicate": 1, "variant": "growing-cardinality-mixed"}), encoding="utf-8")
            (run / "run-status.json").write_text(json.dumps({"k6ExitCode": 0}), encoding="utf-8")
            start = datetime(2026, 8, 20, tzinfo=timezone.utc)
            lines = []
            for index in range(8):
                value = 100 if index < 2 else 300
                lines.append(point("http_req_duration", start + timedelta(seconds=index), value, {"diagnostic_operation": "reverseAllItemsReorder", "diagnostic_phase": "measured"}))
                lines.append(point("diagnostic_reorder_item_count", start + timedelta(seconds=index), index + 1, {"diagnostic_operation": "reverseAllItemsReorder", "diagnostic_phase": "measured"}))
            (run / "raw.json").write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = MODULE.load_run(run)
            summary = result["operations"][0]
            self.assertEqual(summary["samples"], 8)
            self.assertGreater(summary["degradationRatio"], 1.0)

    def test_report_references_replicate_grafana_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "replicate-1" / "grafana").mkdir(parents=True)
            MODULE.write_report(
                root,
                {"campaignId": "fixture" , "runs": []},
                {"verdict": "inconclusive", "reason": "fixture"},
            )
            report = (root / "DIAGNOSTIC_REPORT.md").read_text(encoding="utf-8")
            self.assertIn("replicate-1/grafana/dashboard-full.png", report)
            self.assertIn("replicate-1/grafana/capture-status.json", report)


if __name__ == "__main__":
    unittest.main()

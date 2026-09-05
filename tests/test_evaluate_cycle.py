#!/usr/bin/env python3
"""Smoke tests for evaluate_cycle.py (offline gate logic + optional live run)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluate_cycle import evaluate_gate1, is_cycle_end_reached  # noqa: E402


class TestGateLogic(unittest.TestCase):
    def test_gate1_pass(self):
        markets = {
            "idx": {"portfolio_return_pct": 2.0, "winners": 4, "hit_sl": 0},
            "us": {"portfolio_return_pct": 0.5, "hit_sl": 0},
            "crypto": {"portfolio_return_pct": 1.0, "hit_sl": 0},
        }
        benchmarks = {
            "idx": {"return_pct": 1.0},
            "us": {"return_pct": 1.5},
            "crypto": {"return_pct": 3.0},
        }
        gates_cfg = json.loads(
            (ROOT / "reports/evaluation/gates.json").read_text(encoding="utf-8")
        )
        result = evaluate_gate1(markets, benchmarks, gates_cfg)
        self.assertTrue(result["pass"])
        self.assertEqual(result["summary"], "PASS")

    def test_gate1_fail_sl(self):
        markets = {
            "idx": {"portfolio_return_pct": 5.0, "winners": 5, "hit_sl": 1},
            "us": {"portfolio_return_pct": 2.0, "hit_sl": 0},
            "crypto": {"portfolio_return_pct": 2.0, "hit_sl": 0},
        }
        benchmarks = {"idx": {"return_pct": 0}, "us": {"return_pct": 0}, "crypto": {"return_pct": 0}}
        gates_cfg = json.loads(
            (ROOT / "reports/evaluation/gates.json").read_text(encoding="utf-8")
        )
        result = evaluate_gate1(markets, benchmarks, gates_cfg)
        self.assertFalse(result["pass"])

    def test_cycle_end_not_reached(self):
        cycle = {"end_date": "2099-12-31"}
        self.assertFalse(is_cycle_end_reached(cycle))


class TestLiveRun(unittest.TestCase):
    def test_live_checkpoint_dry_run(self):
        from evaluate_cycle import run_evaluation, POSITIONS_PATH

        if not POSITIONS_PATH.exists():
            self.skipTest("positions.json tidak ada")
        result = run_evaluation(eval_type="checkpoint", dry_run=True)
        self.assertIn("eval_id", result)
        self.assertEqual(result["type"], "checkpoint")
        self.assertIn("idx", result["snapshot"]["markets"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

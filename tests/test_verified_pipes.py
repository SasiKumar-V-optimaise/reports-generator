import unittest
from datetime import datetime

import pandas as pd

from reports.pipes.verified_pipes import VerifiedPipeExporter


class VerifiedPipeExporterTest(unittest.TestCase):
    def _exporter(self):
        exporter = object.__new__(VerifiedPipeExporter)
        exporter.cfg = {"verified_pipes_gate_open_max_interval_seconds": 120}
        return exporter

    def test_missing_loadcell_checkpoint_one_passes_without_gate(self):
        pipe_df = pd.DataFrame([
            {
                "pipe_uid": "checkpoint-pass",
                "pipe_checkpoint": 1,
                "t_origin": "2026-06-26 22:00:00",
                "t_loadcell_enter": "",
                "t_loadcell_exit": "",
            },
        ])
        gate_df = pd.DataFrame(columns=["gate_name", "t_open_IST"])

        verified_df, summary = self._exporter()._apply_gate_verification(
            pipe_df,
            gate_df,
            mode="loadcell",
            shift_end=datetime(2026, 6, 27, 6, 0, 0),
        )

        self.assertEqual(verified_df["pipe_uid"].tolist(), ["checkpoint-pass"])
        self.assertEqual(summary["removed_count"], 0)
        self.assertEqual(summary["confirmed_by_checkpoint_count"], 1)
        self.assertEqual(summary["gate_fallback_checked_count"], 0)

    def test_missing_checkpoint_column_defaults_to_g2_window(self):
        pipe_df = pd.DataFrame([
            {
                "pipe_uid": "legacy-schema-pass",
                "t_origin": "2026-06-26 22:00:00",
                "t_loadcell_enter": "",
                "t_loadcell_exit": "",
            },
        ])
        gate_df = pd.DataFrame([
            {
                "gate_name": "g2",
                "t_open_IST": "2026-06-26 22:01:00",
            },
        ])

        verified_df, summary = self._exporter()._apply_gate_verification(
            pipe_df,
            gate_df,
            mode="loadcell",
            shift_end=datetime(2026, 6, 27, 6, 0, 0),
        )

        self.assertEqual(verified_df["pipe_uid"].tolist(), ["legacy-schema-pass"])
        self.assertEqual(summary["pipe_checkpoint_count"], 0)
        self.assertEqual(summary["confirmed_by_gate2_count"], 1)
    def test_missing_loadcell_checkpoint_zero_uses_g2_window(self):
        pipe_df = pd.DataFrame([
            {
                "pipe_uid": "g2-pass",
                "pipe_checkpoint": 0,
                "t_origin": "2026-06-26 22:00:00",
                "t_loadcell_enter": "",
                "t_loadcell_exit": "",
            },
            {
                "pipe_uid": "gate1-only-fail",
                "pipe_checkpoint": 0,
                "t_origin": "2026-06-26 22:02:00",
                "t_loadcell_enter": "",
                "t_loadcell_exit": "",
            },
            {
                "pipe_uid": "normal-loadcell-pass",
                "pipe_checkpoint": 0,
                "t_origin": "2026-06-26 22:04:00",
                "t_loadcell_enter": "2026-06-26 22:04:10",
                "t_loadcell_exit": "2026-06-26 22:04:20",
            },
        ])
        gate_df = pd.DataFrame([
            {
                "gate_name": "g2",
                "t_open_IST": "2026-06-26 22:01:00",
            },
            {
                "gate_name": "g1",
                "t_open_IST": "2026-06-26 22:03:00",
            },
        ])

        verified_df, summary = self._exporter()._apply_gate_verification(
            pipe_df,
            gate_df,
            mode="loadcell",
            shift_end=datetime(2026, 6, 27, 6, 0, 0),
        )

        self.assertEqual(
            verified_df["pipe_uid"].tolist(),
            ["g2-pass", "normal-loadcell-pass"],
        )
        self.assertEqual(summary["removed_count"], 1)
        self.assertEqual(summary["confirmed_by_gate2_count"], 1)
        self.assertEqual(summary["gate2_unconfirmed_count"], 1)


if __name__ == "__main__":
    unittest.main()

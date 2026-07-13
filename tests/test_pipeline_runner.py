from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from daily_review.features.build_features import build_mood_inputs
from daily_review.modules_v2.sentiment.fear import _compute as compute_fear
from daily_review.modules_v2.sentiment.panorama import _compute as compute_panorama
from daily_review.pipeline.context import Context
from daily_review.pipeline.runner import Runner


class RunnerTimingLogTest(unittest.TestCase):
    def test_runner_logs_module_elapsed_time(self) -> None:
        module = SimpleNamespace(
            name="demo_module",
            requires=[],
            provides=["marketData.demo"],
            compute=lambda ctx: {"marketData.demo": 1},
        )
        runner = Runner([module])
        ctx = Context(market_data={}, features={}, raw={}, meta={})

        buf = io.StringIO()
        with redirect_stdout(buf):
            result = runner.run(ctx)

        self.assertIs(result, ctx)
        self.assertEqual(ctx.market_data.get("demo"), 1)
        self.assertIn("pipeline 模块耗时 demo_module:", buf.getvalue())


class LimitDownCountContractTest(unittest.TestCase):
    def test_build_mood_inputs_excludes_st_limit_down_from_dt_and_loss(self) -> None:
        pools = {
            "ztgc": [],
            "zbgc": [],
            "yest_ztgc": [],
            "qsgc": [],
            "dtgc": [
                {"dm": "000001", "mc": "平安银行", "zf": -10.0},
                {"dm": "600001", "mc": "*ST示例", "zf": -5.0},
            ],
        }

        result = build_mood_inputs(pools=pools)

        self.assertEqual(result["dt_count"], 1)
        self.assertEqual(result["bf_count"], 1)
        self.assertEqual(result["loss"], 2)

    def test_panorama_and_fear_share_non_st_limit_down_contract(self) -> None:
        ctx = Context(
            raw={
                "pools": {
                    "ztgc": [{"dm": "000001", "mc": "平安银行"}],
                    "zbgc": [{"dm": "000002", "mc": "万科A"}],
                    "dtgc": [
                        {"dm": "000003", "mc": "国农科技", "zf": -10.0},
                        {"dm": "600003", "mc": "ST样本", "zf": -5.0},
                    ],
                }
            },
            features={"mood_inputs": {"bf_count": 1, "zt_count": 1, "fb_rate": 50.0}},
            market_data={},
        )

        panorama_patch = compute_panorama(ctx)
        fear_patch = compute_fear(ctx)

        self.assertEqual(panorama_patch["marketData.panorama"]["limitDown"], 1)
        self.assertEqual(fear_patch["marketData.fear"]["limitDown"], "1只")
        self.assertEqual(fear_patch["marketData.fear"]["limitDownNote"], "总跌停2，剔除ST后1")


if __name__ == "__main__":
    unittest.main()

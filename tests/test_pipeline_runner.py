from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from daily_review.pipeline.context import Context
from daily_review.pipeline.runner import Runner


class RunnerTimingLogTest(unittest.TestCase):
    def test_runner_logs_module_elapsed_time(self) -> None:
        module = SimpleNamespace(
            name="demo_module",
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


if __name__ == "__main__":
    unittest.main()

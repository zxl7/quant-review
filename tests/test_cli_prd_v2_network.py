#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from contextlib import ExitStack
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from daily_review import cli


def _fake_three_quadrants(_: dict) -> dict:
    return {
        "position": {"x": 0, "y": 0, "z": 0},
        "bubble": {"size": 0},
        "interpretation": {"zone": ""},
        "history": [],
    }


class RunRebuildPrdV2NetworkTest(unittest.TestCase):
    def test_run_rebuild_disables_prd_v2_network_when_env_requests_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            bundle = SimpleNamespace(
                ctx=SimpleNamespace(market_data={"date": "2026-06-23"}),
                market_data={"date": "2026-06-23"},
                market_path=cache_dir / "market_data-20260623.json",
            )
            fake_runner = MagicMock()

            with patch.object(cli, "_workspace_root", return_value=root), patch.object(
                cli, "build_rebuild_context", return_value=bundle
            ), patch.object(cli, "_prepare_indices_from_cache"), patch.object(
                cli, "_postprocess_market_data"
            ) as mock_postprocess, patch.object(
                cli, "Runner", return_value=fake_runner
            ), patch.dict(
                cli.os.environ, {"QR_DISABLE_PRD_V2_NETWORK": "1"}, clear=False
            ):
                rc = cli.run_rebuild("2026-06-23", allow_network=True)

        self.assertEqual(rc, 0)
        self.assertTrue(mock_postprocess.called)
        self.assertTrue(mock_postprocess.call_args.kwargs["allow_network"])
        self.assertFalse(mock_postprocess.call_args.kwargs["prd_v2_allow_network"])


class RunFetchAndRebuildDailySnapshotLimitTest(unittest.TestCase):
    def test_daily_snapshot_limit_keeps_core_realtime_and_backtest_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            market_path = cache_dir / "market_data-20260623.json"
            fake_cfg = SimpleNamespace(base_url="https://example.test", token="token")
            fake_client = object()

            def fake_write_market_data(*, root: Path, market_data: dict, actual_date: str, suffix: str = "") -> Path:
                market_path.write_text(json.dumps(market_data, ensure_ascii=False, indent=2), encoding="utf-8")
                return market_path

            def fake_attach_stock_research_backtest(*, market_data: dict, sync_source: bool, query_tag: str, log_fn) -> None:
                market_data["stockResearchBacktest"] = {
                    "realtimeBuy": {
                        "trade_date": "2026-06-23",
                        "quote_time": "2026-06-23 09:25:01",
                        "diagnostics": {"source": "workflow_prefetch"},
                    }
                }

            with ExitStack() as stack:
                stack.enter_context(patch.object(cli, "_workspace_root", return_value=root))
                stack.enter_context(patch.object(cli, "load_config_from_env", return_value=fake_cfg))
                stack.enter_context(patch("daily_review.http.HttpClient", return_value=fake_client))
                stack.enter_context(patch.object(cli, "resolve_trade_date", return_value=("2026-06-23", "trade_day")))
                stack.enter_context(
                    patch.object(
                        cli,
                        "_resolve_trade_days_with_local_fallback",
                        return_value=["2026-06-19", "2026-06-22", "2026-06-23"],
                    )
                )
                stack.enter_context(patch.object(cli, "_fetch_pool_with_cache_fallback", return_value=[]))
                stack.enter_context(patch.object(cli, "update_theme_cache", return_value={}))
                stack.enter_context(patch.object(cli, "build_theme_trend_cache", return_value={}))
                mock_sample = stack.enter_context(patch.object(cli, "_save_abnormal_event_history_sample"))
                stack.enter_context(patch.object(cli, "update_index_kline_cache", return_value={}))
                stack.enter_context(patch.object(cli, "build_height_trend_cache"))
                mock_newhigh = stack.enter_context(patch.object(cli, "save_newhigh_snapshot"))
                stack.enter_context(patch.object(cli, "fetch_indices_realtime", return_value=([], "09:26:00")))
                stack.enter_context(patch.object(cli, "build_report_indices", return_value=[]))
                stack.enter_context(
                    patch.object(cli, "build_raw_pools", return_value={"ztgc": [], "qsgc": [], "zbgc": [], "dtgc": []})
                )
                stack.enter_context(
                    patch.object(cli, "build_base_market_data", return_value={"date": "2026-06-23", "features": {}, "raw": {}})
                )
                stack.enter_context(patch.object(cli, "load_latest_valid_research_snapshot", return_value={}))
                stack.enter_context(patch.object(cli, "collect_research_codes_from_snapshot", return_value=["000001"]))
                mock_quotes = stack.enter_context(
                    patch.object(cli, "_fetch_realtime_quotes_map", return_value={"000001": {"dm": "000001"}})
                )
                mock_attach_quotes = stack.enter_context(patch.object(cli, "attach_quotes_and_features"))
                stack.enter_context(patch.object(cli, "write_market_data", side_effect=fake_write_market_data))
                stack.enter_context(patch.object(cli, "run_rebuild", return_value=0))
                stack.enter_context(patch.object(cli, "append_watch_runtime_slice"))
                stack.enter_context(patch.object(cli, "inject_intraday_snapshots"))
                mock_attach_backtest = stack.enter_context(
                    patch.object(cli, "attach_stock_research_backtest", side_effect=fake_attach_stock_research_backtest)
                )
                stack.enter_context(patch.object(cli.time, "sleep"))
                stack.enter_context(patch.dict(cli.os.environ, {"QR_LIMIT_DAILY_SNAPSHOT": "1"}, clear=False))
                rc = cli.run_fetch_and_rebuild("2026-06-23")
                payload = json.loads(market_path.read_text(encoding="utf-8"))

                self.assertEqual(rc, 0)
                self.assertFalse(mock_sample.called)
                self.assertFalse(mock_newhigh.called)
                self.assertTrue(mock_quotes.called)
                self.assertTrue(mock_attach_quotes.called)
                self.assertTrue(mock_attach_backtest.called)
        realtime_buy = ((payload.get("stockResearchBacktest") or {}).get("realtimeBuy") or {})
        self.assertEqual(realtime_buy.get("trade_date"), "2026-06-23")
        self.assertEqual(realtime_buy.get("quote_time"), "2026-06-23 09:25:01")


class InjectPrdV2MetricsNetworkGuardTest(unittest.TestCase):
    def test_inject_prd_v2_metrics_skips_secondary_network_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cache").mkdir()
            market_data = {"date": "2026-06-23", "raw": {"pools": {}, "themes": {}}, "sectors": []}
            divergence_mock = MagicMock(return_value={"overallScore": 0})
            high_position_mock = MagicMock(return_value={"triggered": False})

            with patch("daily_review.metrics.sector_heatmap.build_sector_heatmap", return_value={"rows": [], "meta": {}}), patch(
                "daily_review.metrics.three_quadrants.build_three_quadrants", side_effect=_fake_three_quadrants
            ), patch(
                "daily_review.metrics.risk_diffusion.build_risk_engine", return_value={"score": 0}
            ), patch(
                "daily_review.metrics.divergence.build_divergence_engine", divergence_mock
            ), patch(
                "daily_review.metrics.high_position_risk.build_high_position_risk", high_position_mock
            ), patch(
                "daily_review.metrics.structure_v2.build_structure_v2", return_value={"cards": []}
            ), patch(
                "daily_review.metrics.action_sheet.build_action_sheet", return_value={"actions": []}
            ), patch(
                "daily_review.config.load_config_from_env"
            ) as mock_load_config, patch(
                "daily_review.http.HttpClient"
            ) as mock_http_client, patch.object(
                cli, "PlateRotateFetcher"
            ) as mock_plate_fetcher:
                cli._inject_prd_v2_metrics(root=root, date="2026-06-23", market_data=market_data, allow_network=False)

        self.assertFalse(mock_load_config.called)
        self.assertFalse(mock_http_client.called)
        self.assertFalse(mock_plate_fetcher.called)
        self.assertIsNone(divergence_mock.call_args.kwargs["client"])
        self.assertIsNone(high_position_mock.call_args.kwargs["client"])
        self.assertNotIn("plateRotateTop", market_data)

    def test_inject_prd_v2_metrics_keeps_existing_refresh_path_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cache").mkdir()
            market_data = {"date": "2026-06-23", "raw": {"pools": {}, "themes": {}}, "sectors": []}
            divergence_mock = MagicMock(return_value={"overallScore": 1})
            high_position_mock = MagicMock(return_value={"triggered": False})
            fake_client = object()
            fake_cfg = SimpleNamespace(base_url="https://example.test", token="token")
            plate_fetcher_instance = MagicMock()
            plate_fetcher_instance.fetch_kaipan_days.return_value = {
                "source": "mock",
                "by_day": {
                    "20260623": {
                        "rows": [{"code": "BK001", "name": "机器人", "strength": 95}],
                        "detailByCode": {},
                    }
                },
            }

            with patch("daily_review.metrics.sector_heatmap.build_sector_heatmap", return_value={"rows": [], "meta": {}}), patch(
                "daily_review.metrics.three_quadrants.build_three_quadrants", side_effect=_fake_three_quadrants
            ), patch(
                "daily_review.metrics.risk_diffusion.build_risk_engine", return_value={"score": 0}
            ), patch(
                "daily_review.metrics.divergence.build_divergence_engine", divergence_mock
            ), patch(
                "daily_review.metrics.high_position_risk.build_high_position_risk", high_position_mock
            ), patch(
                "daily_review.metrics.structure_v2.build_structure_v2", return_value={"cards": []}
            ), patch(
                "daily_review.metrics.action_sheet.build_action_sheet", return_value={"actions": []}
            ), patch(
                "daily_review.config.load_config_from_env", return_value=fake_cfg
            ) as mock_load_config, patch(
                "daily_review.http.HttpClient", return_value=fake_client
            ) as mock_http_client, patch.object(
                cli, "PlateRotateFetcher", return_value=plate_fetcher_instance
            ) as mock_plate_fetcher:
                cli._inject_prd_v2_metrics(root=root, date="2026-06-23", market_data=market_data, allow_network=True)

        self.assertTrue(mock_load_config.called)
        self.assertTrue(mock_http_client.called)
        self.assertTrue(mock_plate_fetcher.called)
        self.assertIs(divergence_mock.call_args.kwargs["client"], fake_client)
        self.assertIs(high_position_mock.call_args.kwargs["client"], fake_client)
        self.assertEqual((market_data.get("plateRotateTop") or [])[0]["name"], "机器人")


if __name__ == "__main__":
    unittest.main()

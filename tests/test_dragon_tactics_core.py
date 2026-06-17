#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest

from daily_review.metrics.dragon_tactics_core import (
    DragonRoleModel,
    DragonTacticsCore,
    DragonTacticsEngine,
    RelaySelector,
    WatchSelector,
    leader_role_profile,
)


class DragonTacticsCoreTest(unittest.TestCase):
    def test_leader_role_profile_marks_strong_one_to_two_as_core(self) -> None:
        profile = leader_role_profile(
            {
                "themeLadderProfile": {"followerCount": 0, "gapCount": 0, "hasCarry": True},
                "_isThemeLeader": False,
                "_leaderBonus": 0,
                "lbc": 1,
                "breakRisk": 23,
                "factorHint": "环境98 / 龙头61 / 接力82 / 强候选",
                "isBroadOnly": False,
                "hasTradeTheme": True,
                "leaderFactorScore": 61,
                "relayFactorScore": 82,
                "leaderPhilosophyScore": 79,
                "stepContextScore": 71,
                "capacityFactorScore": 94,
                "qualityScore": 87,
            }
        )

        self.assertEqual(profile["role"], "core")
        self.assertTrue(profile["isCore"])
        self.assertFalse(profile["isFollower"])

    def test_relay_one_to_two_requires_quality_and_capacity(self) -> None:
        core = DragonTacticsCore(tide_market_regime={}, max_lbc=4, cap_threshold=20.0)
        good_row = {
            "themeLadderProfile": {"followerCount": 0, "gapCount": 0, "hasCarry": True},
            "hasTradeTheme": True,
            "isBroadOnly": False,
            "isYizi": False,
            "isShrinkSeal": False,
            "lbc": 1,
            "open": 0,
            "_raw": 83,
            "stepContextScore": 71,
            "leaderFactorScore": 61,
            "relayFactorScore": 82,
            "leaderPhilosophyScore": 79,
            "capacityFactorScore": 94,
            "qualityScore": 87,
            "breakRisk": 23,
            "tideRelayGate": 0,
            "factorHint": "环境98 / 龙头61 / 接力82 / 强候选",
        }
        weak_row = {
            **good_row,
            "capacityFactorScore": 59,
            "qualityScore": 76,
        }

        self.assertTrue(core.relay_one_to_two_ok(good_row))
        self.assertFalse(core.relay_one_to_two_ok(weak_row))

    def test_engine_selects_relay_before_watch_and_assigns_ranks(self) -> None:
        core = DragonTacticsCore(tide_market_regime={}, max_lbc=3, cap_threshold=20.0)
        engine = DragonTacticsEngine(core=core, ladder=[])
        relay_row = {
            "name": "主线二板龙头",
            "themeLadderProfile": {"followerCount": 1, "gapCount": 0, "hasCarry": True, "score": 60, "frontCount": 2},
            "hasTradeTheme": True,
            "isBroadOnly": False,
            "isYizi": False,
            "isShrinkSeal": False,
            "lbc": 2,
            "open": 1,
            "_raw": 90,
            "stepContextScore": 88,
            "leaderFactorScore": 85,
            "relayFactorScore": 92,
            "leaderPhilosophyScore": 95,
            "capacityFactorScore": 80,
            "qualityScore": 90,
            "environmentScore": 90,
            "breakRisk": 18,
            "tideRelayGate": 0,
            "_isThemeLeader": True,
            "_leaderBonus": 10,
            "factorHint": "带动强",
        }
        watch_row = {
            "name": "容量中军",
            "themeLadderProfile": {"followerCount": 0, "gapCount": 0, "hasCarry": True, "score": 55, "frontCount": 1},
            "hasTradeTheme": True,
            "isBroadOnly": False,
            "isYizi": False,
            "isShrinkSeal": False,
            "lbc": 1,
            "open": 0,
            "_raw": 75,
            "stepContextScore": 60,
            "leaderFactorScore": 58,
            "relayFactorScore": 63,
            "leaderPhilosophyScore": 66,
            "capacityFactorScore": 72,
            "qualityScore": 70,
            "environmentScore": 82,
            "breakRisk": 25,
            "tideRelayGate": 0,
            "_isThemeLeader": False,
            "_leaderBonus": 0,
            "factorHint": "容量承接",
            "cjeYi": 35,
        }

        selection = engine.select([relay_row, watch_row])

        self.assertEqual([row["name"] for row in selection.relay], ["主线二板龙头"])
        self.assertEqual(selection.relay[0]["relayRank"], 1)
        self.assertEqual([row["name"] for row in selection.watch], ["容量中军"])
        self.assertEqual(selection.watch[0]["watchRank"], 1)

    def test_role_model_writes_leader_role_back_to_rows(self) -> None:
        core = DragonTacticsCore(tide_market_regime={}, max_lbc=4, cap_threshold=20.0)
        role_model = DragonRoleModel(core=core)
        rows = [
            {
                "name": "主线龙头",
                "themeLadderProfile": {"followerCount": 1, "gapCount": 0, "hasCarry": True},
                "_isThemeLeader": True,
                "_leaderBonus": 10,
                "lbc": 3,
                "breakRisk": 20,
                "factorHint": "带动强",
                "isBroadOnly": False,
                "hasTradeTheme": True,
                "leaderFactorScore": 85,
                "relayFactorScore": 90,
                "leaderPhilosophyScore": 95,
                "stepContextScore": 88,
                "capacityFactorScore": 78,
                "qualityScore": 90,
            }
        ]

        result = role_model.apply(rows)

        self.assertEqual(result[0]["leaderRole"], "driver")

    def test_selectors_can_be_used_independently(self) -> None:
        core = DragonTacticsCore(tide_market_regime={}, max_lbc=3, cap_threshold=20.0)
        relay_selector = RelaySelector(core=core)
        watch_selector = WatchSelector(core=core, ladder=[])
        rows = [
            {
                "name": "主线二板龙头",
                "themeLadderProfile": {"followerCount": 1, "gapCount": 0, "hasCarry": True, "score": 60, "frontCount": 2},
                "hasTradeTheme": True,
                "isBroadOnly": False,
                "isYizi": False,
                "isShrinkSeal": False,
                "lbc": 2,
                "open": 1,
                "_raw": 90,
                "stepContextScore": 88,
                "leaderFactorScore": 85,
                "relayFactorScore": 92,
                "leaderPhilosophyScore": 95,
                "capacityFactorScore": 80,
                "qualityScore": 90,
                "environmentScore": 90,
                "breakRisk": 18,
                "tideRelayGate": 0,
                "_isThemeLeader": True,
                "_leaderBonus": 10,
                "factorHint": "带动强",
                "leaderRole": "driver",
            },
            {
                "name": "容量中军",
                "themeLadderProfile": {"followerCount": 0, "gapCount": 0, "hasCarry": True, "score": 55, "frontCount": 1},
                "hasTradeTheme": True,
                "isBroadOnly": False,
                "isYizi": False,
                "isShrinkSeal": False,
                "lbc": 1,
                "open": 0,
                "_raw": 75,
                "stepContextScore": 60,
                "leaderFactorScore": 58,
                "relayFactorScore": 63,
                "leaderPhilosophyScore": 66,
                "capacityFactorScore": 72,
                "qualityScore": 70,
                "environmentScore": 82,
                "breakRisk": 25,
                "tideRelayGate": 0,
                "_isThemeLeader": False,
                "_leaderBonus": 0,
                "factorHint": "容量承接",
                "cjeYi": 35,
                "leaderRole": "neutral",
            },
        ]

        relay, mode, _ = relay_selector.select(rows)
        watch = watch_selector.select(rows, relay_names={row["name"] for row in relay})

        self.assertEqual(mode, "strict")
        self.assertEqual([row["name"] for row in relay], ["主线二板龙头"])
        self.assertEqual([row["name"] for row in watch], ["容量中军"])


if __name__ == "__main__":
    unittest.main()

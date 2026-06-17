#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""龙头战法核心规则层。

从 ``zt_analysis`` 中抽离纯规则判断，让“角色识别 / 接力池准入 / 观察池排序”
可以独立复用、单测和迭代。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


def _to_num(v: Any, d: float = 0.0) -> float:
    try:
        if v is None:
            return float(d)
        if isinstance(v, str):
            v = v.replace("%", "").replace("板", "").strip()
        n = float(v)
        return n if math.isfinite(n) else float(d)
    except Exception:
        return float(d)


def leader_role_profile(row: dict[str, Any]) -> dict[str, Any]:
    theme_ladder = row.get("themeLadderProfile") if isinstance(row.get("themeLadderProfile"), dict) else {}
    follower_count = _to_num(theme_ladder.get("followerCount"), 0.0)
    gap_count = _to_num(theme_ladder.get("gapCount"), 0.0)
    has_carry = bool(theme_ladder.get("hasCarry"))
    is_theme_leader = bool(row.get("_isThemeLeader"))
    leader_bonus = _to_num(row.get("_leaderBonus"), 0.0)
    lbc = _to_num(row.get("lbc"), 0.0)
    break_risk = _to_num(row.get("breakRisk"), 0.0)
    factor_hint = str(row.get("factorHint") or "")
    is_broad_only = bool(row.get("isBroadOnly"))
    has_trade_theme = bool(row.get("hasTradeTheme"))
    leader_factor = _to_num(row.get("leaderFactorScore"), 0.0)
    relay_factor = _to_num(row.get("relayFactorScore"), 0.0)
    leader_philosophy = _to_num(row.get("leaderPhilosophyScore"), 0.0)
    step_context = _to_num(row.get("stepContextScore"), 0.0)
    capacity_factor = _to_num(row.get("capacityFactorScore"), 0.0)
    quality_score = _to_num(row.get("qualityScore"), 0.0)

    is_driver = bool(
        not is_broad_only
        and (
            row.get("_superLeaderCandidate")
            or row.get("_heightBreakoutLeader")
            or row.get("_uniqueMarketLeader")
            or (is_theme_leader and (follower_count >= 1 or has_carry or "带动" in factor_hint))
            or (leader_bonus >= 10 and lbc >= 2 and break_risk < 72)
        )
    )
    is_core = bool(
        not is_driver
        and not is_broad_only
        and (
            is_theme_leader
            or leader_bonus >= 6
            or (lbc >= 2 and has_carry and gap_count <= 1)
            or (
                has_trade_theme
                and lbc == 1
                and leader_factor >= 60
                and relay_factor >= 64
                and leader_philosophy >= 66
                and step_context >= 55
                and break_risk < 68
                and capacity_factor >= 68
                and quality_score >= 80
            )
        )
    )
    is_follower = bool(
        not is_broad_only
        and not is_driver
        and (
            "跟风" in factor_hint
            or gap_count >= 1
            or (
                not is_theme_leader
                and follower_count <= 0
                and lbc <= 2
                and leader_factor < 70
                and relay_factor < 66
            )
        )
    )
    role = "driver" if is_driver else "core" if is_core else "follower" if is_follower else "neutral"
    return {
        "role": role,
        "isDriver": is_driver,
        "isCore": is_core,
        "isFollower": is_follower,
    }


@dataclass(frozen=True)
class DragonTacticsCore:
    tide_market_regime: dict[str, Any]
    max_lbc: float
    cap_threshold: float

    def tide_relay_blocked(self, row: dict[str, Any]) -> bool:
        action = str(row.get("tideAction") or "")
        status = str(row.get("tideStatus") or "")
        phase = str(row.get("tidePhase") or "")
        regime_status = str(self.tide_market_regime.get("status") or "")
        if action == "no_new_position":
            return True
        if status in {"afterglow_risk", "rebound_warning"}:
            return True
        if status in {"shrinking_rebound", "volume_rebound"} and phase == "ebbing":
            return True
        if action == "avoid" and regime_status in {"ebb", "ice", "divergence"}:
            return True
        return False

    def relay_sort_key(self, row: dict[str, Any]) -> tuple[float, ...]:
        lbc = _to_num(row.get("lbc"), 0)
        is_first_board = 1.0 if lbc <= 1 else 0.0
        broad_penalty = 1.0 if row.get("isBroadOnly") else 0.0
        theme_ladder = row.get("themeLadderProfile") if isinstance(row.get("themeLadderProfile"), dict) else {}
        leader_role = leader_role_profile(row)
        return (
            1.0 if row.get("_superLeaderCandidate") else 0.0,
            1.0 if row.get("_heightBreakoutLeader") else 0.0,
            1.0 if leader_role.get("isDriver") else 0.0,
            1.0 if 2 <= lbc <= 5 and row.get("hasTradeTheme") and not row.get("isBroadOnly") else 0.0,
            1.0 if 3 <= lbc <= 5 and (row.get("_isThemeLeader") or _to_num(row.get("_leaderBonus"), 0) >= 10) else 0.0,
            _to_num(row.get("tideRelayGate"), 0),
            _to_num(row.get("leaderPhilosophyScore"), 0),
            _to_num(row.get("_raw"), 0),
            _to_num(((row.get("themeLadderProfile") or {}).get("score")), 0),
            _to_num(row.get("leaderFactorScore"), 0),
            _to_num(row.get("relayFactorScore"), 0),
            _to_num(row.get("environmentScore"), 0),
            _to_num(row.get("capacityFactorScore"), 0),
            -_to_num(row.get("breakRisk"), 0),
            -is_first_board,
            -broad_penalty,
            -_to_num(theme_ladder.get("gapCount"), 0),
        )

    def relay_height_breakout_ok(self, row: dict[str, Any]) -> bool:
        if self.tide_relay_blocked(row):
            return False
        return bool(
            (row.get("_heightBreakoutLeader") or row.get("_superLeaderCandidate"))
            and _to_num(row.get("lbc"), 0) >= 6
            and _to_num(row.get("_raw"), 0) >= 72
            and _to_num(row.get("leaderFactorScore"), 0) >= 76
            and _to_num(row.get("relayFactorScore"), 0) >= 70
            and _to_num(row.get("breakRisk"), 0) < 68
            and _to_num(row.get("stepContextScore"), 0) >= 70
            and _to_num(row.get("open"), 0) <= 2
            and _to_num(row.get("tideRelayGate"), 0) >= -4
        )

    def relay_core_ok(self, row: dict[str, Any]) -> bool:
        if self.tide_relay_blocked(row):
            return False
        leader_role = leader_role_profile(row)
        open_cnt = _to_num(row.get("open"), 0)
        return bool(
            row.get("hasTradeTheme")
            and not row.get("isBroadOnly")
            and not row.get("isYizi")
            and not row.get("isShrinkSeal")
            and 2 <= _to_num(row.get("lbc"), 0) <= 5
            and _to_num(row.get("_raw"), 0) >= 60
            and _to_num(row.get("open"), 0) < 8
            and _to_num(row.get("breakRisk"), 0) < 76
            and _to_num(row.get("stepContextScore"), 0) >= 38
            and _to_num(row.get("tideRelayGate"), 0) >= 0
            and not leader_role.get("isFollower")
            and (leader_role.get("isDriver") or leader_role.get("isCore"))
            and not (leader_role.get("isDriver") and _to_num(row.get("lbc"), 0) >= 3 and open_cnt >= 3)
            and not (_to_num(row.get("lbc"), 0) >= 3 and _to_num(((row.get("themeLadderProfile") or {}).get("gapCount")), 0) >= 1)
        )

    def relay_high_mark_ok(self, row: dict[str, Any]) -> bool:
        if self.tide_relay_blocked(row):
            return False
        lbc = _to_num(row.get("lbc"), 0)
        leader_role = leader_role_profile(row)
        return bool(
            row.get("hasTradeTheme")
            and not row.get("isBroadOnly")
            and not row.get("isYizi")
            and not row.get("isShrinkSeal")
            and 3 <= lbc <= 5
            and _to_num(row.get("_raw"), 0) >= 74
            and _to_num(row.get("leaderFactorScore"), 0) >= 72
            and _to_num(row.get("leaderPhilosophyScore"), 0) >= 76
            and _to_num(row.get("breakRisk"), 0) < 68
            and _to_num(row.get("open"), 0) <= 2
            and leader_role.get("isDriver")
            and _to_num(((row.get("themeLadderProfile") or {}).get("gapCount")), 0) <= 0
            and (
                _to_num(row.get("stepContextScore"), 0) >= 32
                or row.get("_isThemeLeader")
                or row.get("_isNewHigh")
                or _to_num(row.get("_leaderBonus"), 0) >= 10
            )
            and _to_num(row.get("tideRelayGate"), 0) >= 0
        )

    def relay_one_to_two_ok(self, row: dict[str, Any]) -> bool:
        if self.tide_relay_blocked(row):
            return False
        leader_role = leader_role_profile(row)
        return bool(
            row.get("hasTradeTheme")
            and not row.get("isBroadOnly")
            and not row.get("isYizi")
            and not row.get("isShrinkSeal")
            and _to_num(row.get("lbc"), 0) == 1
            and _to_num(row.get("open"), 0) < 3
            and _to_num(row.get("_raw"), 0) >= 72
            and _to_num(row.get("stepContextScore"), 0) >= 55
            and _to_num(row.get("leaderFactorScore"), 0) >= 60
            and _to_num(row.get("relayFactorScore"), 0) >= 64
            and _to_num(row.get("leaderPhilosophyScore"), 0) >= 66
            and _to_num(row.get("capacityFactorScore"), 0) >= 68
            and _to_num(row.get("qualityScore"), 0) >= 80
            and _to_num(row.get("breakRisk"), 0) < 68
            and _to_num(row.get("tideRelayGate"), 0) >= 0
            and (leader_role.get("isDriver") or leader_role.get("isCore"))
        )

    def relay_relaxed_ok(self, row: dict[str, Any]) -> bool:
        if self.tide_relay_blocked(row):
            return False
        leader_role = leader_role_profile(row)
        return bool(
            row.get("hasTradeTheme")
            and not row.get("isBroadOnly")
            and not row.get("isYizi")
            and not row.get("isShrinkSeal")
            and 2 <= _to_num(row.get("lbc"), 0) <= 4
            and _to_num(row.get("open"), 0) < 8
            and _to_num(row.get("stepContextScore"), 0) >= 50
            and _to_num(row.get("breakRisk"), 0) < 90
            and _to_num(row.get("leaderFactorScore"), 0) >= 58
            and _to_num((row.get("factorBreakdown") or {}).get("sector"), 0) >= 70
            and _to_num(row.get("capacityFactorScore"), 0) >= 55
            and _to_num(row.get("tideRelayGate"), 0) >= -6
            and not leader_role.get("isFollower")
        )

    def relay_broad_ok(self, row: dict[str, Any]) -> bool:
        return bool(
            (not self.tide_relay_blocked(row))
            and not row.get("isYizi")
            and 1 <= _to_num(row.get("lbc"), 0) <= 6
            and _to_num(row.get("open"), 0) < 12
            and _to_num(row.get("breakRisk"), 0) < 95
            and _to_num(row.get("_raw"), 0) >= 55
            and not (_to_num(row.get("lbc"), 0) >= 3 and _to_num(((row.get("themeLadderProfile") or {}).get("gapCount")), 0) >= 1)
            and not (row.get("isBroadOnly") and _to_num(row.get("lbc"), 0) <= 1 and _to_num(row.get("capacityFactorScore"), 0) < 72)
        )

    def relay_emergency_ok(self, row: dict[str, Any]) -> bool:
        return bool(
            str(row.get("tideAction") or "") != "no_new_position"
            and 1 <= _to_num(row.get("lbc"), 0) <= 7
            and _to_num(row.get("open"), 0) < 15
            and _to_num(row.get("breakRisk"), 0) < 98
            and _to_num(row.get("_raw"), 0) >= 45
            and not (_to_num(row.get("lbc"), 0) >= 3 and _to_num(((row.get("themeLadderProfile") or {}).get("gapCount")), 0) >= 1)
            and not (row.get("isBroadOnly") and _to_num(row.get("lbc"), 0) <= 1)
        )

    def relay_hit_labels(self, row: dict[str, Any]) -> list[str]:
        hits: list[str] = []
        if self.relay_height_breakout_ok(row):
            hits.append("高度突破")
        if self.relay_high_mark_ok(row):
            hits.append("高标龙头")
        if self.relay_core_ok(row):
            hits.append("主线接力")
        if self.relay_one_to_two_ok(row):
            hits.append("1进2")
        if self.relay_relaxed_ok(row):
            hits.append("宽松候选")
        if self.relay_broad_ok(row):
            hits.append("兜底候选")
        if self.relay_emergency_ok(row):
            hits.append("应急兜底")
        return hits

    def relay_block_labels(self, row: dict[str, Any]) -> list[str]:
        labels: list[str] = []
        lbc = _to_num(row.get("lbc"), 0)
        if not row.get("hasTradeTheme"):
            labels.append("无主线题材")
        if row.get("isBroadOnly"):
            labels.append("题材偏泛化")
        if row.get("isYizi"):
            labels.append("一字难参与")
        if row.get("isShrinkSeal"):
            labels.append("缩量参与难")
        if _to_num(row.get("open"), 0) >= 5:
            labels.append("开板过多")
        elif _to_num(row.get("open"), 0) >= 3:
            labels.append("分歧偏大")
        if _to_num(row.get("breakRisk"), 0) >= 76:
            labels.append("断板风险高")
        if lbc == 1 and _to_num(row.get("stepContextScore"), 0) < 55:
            labels.append("首板接力链条弱")
        if 2 <= lbc <= 5 and _to_num(row.get("stepContextScore"), 0) < 38:
            labels.append("晋级承接不足")
        if 3 <= lbc <= 5 and _to_num(row.get("leaderPhilosophyScore"), 0) < 76:
            labels.append("龙头辨识度不足")
        if 3 <= lbc <= 5 and _to_num(row.get("leaderFactorScore"), 0) < 72:
            labels.append("龙头因子不够")
        theme_ladder = row.get("themeLadderProfile") if isinstance(row.get("themeLadderProfile"), dict) else {}
        if _to_num(theme_ladder.get("gapCount"), 0) >= 1 and _to_num(theme_ladder.get("leaderBoards"), 0) >= 3:
            labels.append("梯队断层")
        elif _to_num(theme_ladder.get("leaderBoards"), 0) >= 3 and not theme_ladder.get("hasCarry"):
            labels.append("中位承接不足")
        if _to_num(row.get("capacityFactorScore"), 0) < 55 and lbc <= 2:
            labels.append("容量承接偏弱")
        if _to_num(row.get("environmentScore"), 0) < 58:
            labels.append("环境不支持")
        if self.tide_relay_blocked(row):
            labels.append("潮汐不支持接力")
        elif _to_num(row.get("tideRelayGate"), 0) < 0:
            labels.append("潮汐偏弱")
        return labels

    def relay_diagnostics(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "scored": len(rows),
            "themeRows": sum(1 for row in rows if row.get("hasTradeTheme")),
            "heightBreakoutEligible": sum(1 for row in rows if self.relay_height_breakout_ok(row)),
            "coreEligible": sum(1 for row in rows if self.relay_core_ok(row)),
            "highMarkEligible": sum(1 for row in rows if self.relay_high_mark_ok(row)),
            "oneToTwoEligible": sum(1 for row in rows if self.relay_one_to_two_ok(row)),
            "relaxedEligible": sum(1 for row in rows if self.relay_relaxed_ok(row)),
            "broadEligible": sum(1 for row in rows if self.relay_broad_ok(row)),
            "emergencyEligible": sum(1 for row in rows if self.relay_emergency_ok(row)),
            "riskBlocked": sum(1 for row in rows if _to_num(row.get("breakRisk"), 0) >= 76),
            "openBlocked": sum(1 for row in rows if _to_num(row.get("open"), 0) >= 8),
            "stepWeak": sum(1 for row in rows if _to_num(row.get("stepContextScore"), 0) < 38),
            "yiziBlocked": sum(1 for row in rows if row.get("isYizi")),
            "shrinkBlocked": sum(1 for row in rows if row.get("isShrinkSeal")),
            "tideBlocked": sum(1 for row in rows if self.tide_relay_blocked(row)),
        }

    def watch_bucket(self, row: dict[str, Any]) -> int:
        cje_yi = _to_num(row.get("cjeYi"), 0.0)
        open_cnt = _to_num(row.get("open"), 0.0)
        lbc = _to_num(row.get("lbc"), 0.0)
        break_risk = _to_num(row.get("breakRisk"), 0.0)
        leader_bonus = _to_num(row.get("_leaderBonus"), 0.0)
        tide_status = str(row.get("tideStatus") or "")
        tide_action = str(row.get("tideAction") or "")
        tide_phase = str(row.get("tidePhase") or "")
        if tide_action == "no_new_position" or tide_status in {"afterglow_risk", "rebound_warning"}:
            return 3
        if lbc >= 3 and open_cnt >= 3:
            return 1
        if tide_status in {"core_mainline", "confirmed_mainline"} and tide_phase != "ebbing":
            return 0
        if tide_status in {"resonance_traverse", "traverse_candidate"}:
            return 1 if lbc >= 3 else 2
        if tide_status in {"observe_candidate", "micro_traverse"}:
            return 2
        if lbc >= max(4.0, self.max_lbc) or leader_bonus >= 10 or row.get("_isThemeLeader") or row.get("_isNewHigh"):
            return 0
        if lbc >= 3:
            return 1
        if lbc >= 2 and row.get("hasTradeTheme") and not row.get("isBroadOnly") and break_risk < 72:
            return 1
        if cje_yi >= self.cap_threshold and row.get("hasTradeTheme") and open_cnt < 3 and break_risk < 70:
            return 2
        if cje_yi >= self.cap_threshold or open_cnt >= 3 or break_risk >= 68:
            return 3
        if _to_num(row.get("stepContextScore"), 0.0) < 42 or not row.get("hasTradeTheme"):
            return 4
        return 5

    def watch_group(self, row: dict[str, Any]) -> str:
        return {
            0: "高标/题材核心",
            1: "高位分歧",
            2: "容量核心",
            3: "风险观察",
            4: "补充观察",
        }.get(self.watch_bucket(row), "补充观察")

    def watch_rank(self, row: dict[str, Any]) -> float:
        cje_yi = _to_num(row.get("cjeYi"), 0.0)
        open_cnt = _to_num(row.get("open"), 0.0)
        lbc = _to_num(row.get("lbc"), 0.0)
        bucket = self.watch_bucket(row)
        capacity = _to_num(row.get("capacityFactorScore"), 0.0) * 0.88 + min(cje_yi, 90.0) * 0.24 + (18.0 if cje_yi >= self.cap_threshold else 0.0)
        divergence = min(open_cnt, 12.0) * 5.0 + max(0.0, _to_num(row.get("breakRisk"), 0.0) - 60.0) * 0.95
        height = lbc * 18.0 + _to_num(row.get("_leaderBonus"), 0.0) * 1.7 + _to_num(row.get("leaderFactorScore"), 0.0) * 0.48 + (12.0 if row.get("_isThemeLeader") else 0.0) + (8.0 if row.get("_isNewHigh") else 0.0)
        theme_gap = 0.0 if row.get("hasTradeTheme") else 22.0 if row.get("isBroadOnly") else 16.0
        theme_core = _to_num(row.get("_themeNet"), 0.0) * 1.8 + _to_num(row.get("sectorTrendScore"), 0.0) * 0.18 + _to_num(row.get("environmentScore"), 0.0) * 0.14
        theme_ladder = row.get("themeLadderProfile") if isinstance(row.get("themeLadderProfile"), dict) else {}
        ladder_core = _to_num(theme_ladder.get("score"), 0.0) * 0.55 + _to_num(theme_ladder.get("frontCount"), 0.0) * 6.0
        ladder_gap = _to_num(theme_ladder.get("gapCount"), 0.0) * 16.0
        weak_step = max(0.0, 48.0 - _to_num(row.get("stepContextScore"), 0.0)) * 0.45
        core = _to_num(row.get("_raw"), 0.0) * 0.26 + _to_num(row.get("leaderFactorScore"), 0.0) * 0.18 + _to_num(row.get("relayFactorScore"), 0.0) * 0.14 + _to_num(row.get("qualityScore"), 0.0) * 0.10
        tide_bias = (
            _to_num(row.get("tideWatchAdjust"), 0.0) * 2.4
            + _to_num(row.get("tideCoreScore"), 0.0) * 0.18
            - _to_num(row.get("tideEbbScore"), 0.0) * 0.14
        )
        bucket_base = {0: 240.0, 1: 200.0, 2: 165.0, 3: 130.0, 4: 95.0}.get(bucket, 70.0)
        if bucket == 0:
            return bucket_base + height + theme_core * 0.55 + ladder_core * 0.22 + capacity * 0.22 + core * 0.22 + tide_bias - divergence * 0.15 - ladder_gap * 0.10
        if bucket == 1:
            return bucket_base + height * 0.78 + divergence * 0.68 + capacity * 0.34 + theme_core * 0.30 + ladder_core * 0.18 + tide_bias * 0.78 - ladder_gap * 0.18
        if bucket == 2:
            return bucket_base + capacity * 0.92 + theme_core * 0.60 + ladder_core * 0.14 + core * 0.18 + tide_bias * 0.88 - divergence * 0.25 - ladder_gap * 0.12
        if bucket == 3:
            return bucket_base + capacity * 0.78 + divergence * 0.82 + theme_core * 0.22 + theme_gap * 0.25 + tide_bias * 0.35 - ladder_gap * 0.18
        return bucket_base + core * 0.45 + capacity * 0.45 + height * 0.35 + ladder_core * 0.12 + theme_gap + weak_step + tide_bias * 0.55 - ladder_gap * 0.12

    def watch_should_include(self, row: dict[str, Any]) -> bool:
        return bool(
            self.watch_bucket(row) <= 1
            or (_to_num(row.get("cjeYi"), 0) and _to_num(row.get("cjeYi"), 0) >= self.cap_threshold)
            or _to_num(row.get("lbc"), 0) >= 5
            or _to_num(row.get("open"), 0) >= 3
            or _to_num(row.get("breakRisk"), 0) >= 68
            or _to_num(row.get("stepContextScore"), 0) < 42
            or not row.get("hasTradeTheme")
        )

    def watch_sort_key(self, row: dict[str, Any]) -> tuple[float, ...]:
        leader_role = leader_role_profile(row)
        return (
            -float(self.watch_bucket(row)),
            self.watch_rank(row),
            1.0 if leader_role.get("isDriver") else 0.0,
            1.0 if leader_role.get("isCore") else 0.0,
            -1.0 if leader_role.get("isFollower") else 0.0,
            _to_num(row.get("leaderFactorScore"), 0),
            _to_num(row.get("leaderPhilosophyScore"), 0),
            _to_num(row.get("relayFactorScore"), 0),
            _to_num(row.get("capacityFactorScore"), 0),
            _to_num(row.get("qualityScore"), 0),
            _to_num(row.get("_raw"), 0),
            _to_num(row.get("tideWatchAdjust"), 0),
        )


@dataclass
class DragonTacticsSelection:
    relay: list[dict[str, Any]]
    watch: list[dict[str, Any]]
    relay_selection_mode: str
    relay_diagnostics: dict[str, Any]


@dataclass
class DragonRoleModel:
    core: DragonTacticsCore

    def apply(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            profile = leader_role_profile(row)
            row["leaderRole"] = profile.get("role")
        return rows


@dataclass
class RelaySelector:
    core: DragonTacticsCore

    def select(self, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        relay_diagnostics = self.core.relay_diagnostics(rows)
        relay_breakout = sorted(
            [row for row in rows if self.core.relay_height_breakout_ok(row)],
            key=self.core.relay_sort_key,
            reverse=True,
        )
        relay_core = sorted(
            [row for row in rows if self.core.relay_core_ok(row)],
            key=self.core.relay_sort_key,
            reverse=True,
        )
        relay_high_mark = sorted(
            [row for row in rows if self.core.relay_high_mark_ok(row)],
            key=self.core.relay_sort_key,
            reverse=True,
        )
        relay_one_to_two = sorted(
            [row for row in rows if self.core.relay_one_to_two_ok(row)],
            key=self.core.relay_sort_key,
            reverse=True,
        )[:3]
        relay_pool: list[dict[str, Any]] = []
        relay_seen: set[str] = set()
        for item in [*relay_breakout, *relay_high_mark, *relay_core, *relay_one_to_two]:
            name = str(item.get("name") or "")
            if name in relay_seen:
                continue
            relay_seen.add(name)
            relay_pool.append(item)
        relay = sorted(relay_pool, key=self.core.relay_sort_key, reverse=True)[:8]
        relay_selection_mode = "strict" if relay else "relaxed"
        if not relay:
            relay = sorted(
                [row for row in rows if self.core.relay_relaxed_ok(row)],
                key=self.core.relay_sort_key,
                reverse=True,
            )[:3]
        if not relay:
            relay_selection_mode = "broad"
            relay = sorted(
                [row for row in rows if self.core.relay_broad_ok(row)],
                key=self.core.relay_sort_key,
                reverse=True,
            )[:3]
        if not relay:
            relay_selection_mode = "emergency"
            relay = sorted(
                [row for row in rows if self.core.relay_emergency_ok(row)],
                key=self.core.relay_sort_key,
                reverse=True,
            )[:3]
        if not relay:
            relay_selection_mode = "none"
        for idx, row in enumerate(relay, start=1):
            row["relayRank"] = idx
            row["relaySelectionMode"] = relay_selection_mode
        return relay, relay_selection_mode, relay_diagnostics


@dataclass
class WatchSelector:
    core: DragonTacticsCore
    ladder: list[dict[str, Any]]

    def select(self, rows: list[dict[str, Any]], *, relay_names: set[str]) -> list[dict[str, Any]]:
        watch_pool = [
            row
            for row in rows
            if str(row.get("name") or "") not in relay_names and self.core.watch_should_include(row)
        ]
        watch_pool = sorted(watch_pool, key=self.core.watch_sort_key, reverse=True)
        watch = watch_pool[:10]
        if not watch:
            watch = sorted(
                [row for row in rows if str(row.get("name") or "") not in relay_names],
                key=self.core.watch_sort_key,
                reverse=True,
            )[:10]

        must_set = self._ladder_must_names()
        must_rows = sorted(
            [row for row in rows if str(row.get("name") or "") in must_set and str(row.get("name") or "") not in relay_names],
            key=self.core.watch_sort_key,
            reverse=True,
        )
        merged: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for row in [*must_rows, *watch]:
            name = str(row.get("name") or "")
            if name and name not in seen_names:
                merged.append(row)
                seen_names.add(name)
        watch = sorted(merged, key=self.core.watch_sort_key, reverse=True)[:8]
        for idx, row in enumerate(watch, start=1):
            row["watchRank"] = idx
            row["watchGroup"] = self.core.watch_group(row)
        return watch

    def _ladder_must_names(self) -> set[str]:
        names: list[str] = []
        for item in self.ladder:
            if isinstance(item, dict) and _to_num(item.get("badge"), 0) >= 4:
                name = str(item.get("name") or "").replace("🐲", "").strip()
                if name:
                    names.append(name)
        return set(names)


@dataclass
class DragonTacticsEngine:
    core: DragonTacticsCore
    ladder: list[dict[str, Any]]

    def select(self, rows: list[dict[str, Any]]) -> DragonTacticsSelection:
        role_model = DragonRoleModel(core=self.core)
        relay_selector = RelaySelector(core=self.core)
        watch_selector = WatchSelector(core=self.core, ladder=self.ladder)

        prepared_rows = role_model.apply(rows)
        relay, relay_selection_mode, relay_diagnostics = relay_selector.select(prepared_rows)
        relay_names = {str(row.get("name") or "") for row in relay}
        watch = watch_selector.select(prepared_rows, relay_names=relay_names)
        return DragonTacticsSelection(
            relay=relay,
            watch=watch,
            relay_selection_mode=relay_selection_mode,
            relay_diagnostics=relay_diagnostics,
        )

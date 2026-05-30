#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from daily_review.learning.notes_loader import build_learning_notes


class LearningNotesLoaderTest(unittest.TestCase):
    def _build_notes(
        self,
        *,
        workspace: Path,
        date: str,
        cycle: str = "ICE",
        stage_type: str = "warn",
    ) -> dict:
        cache_dir = workspace / "cache"
        cache_dir.mkdir(exist_ok=True)
        return build_learning_notes(
            market_data={
                "date": date,
                "moodStage": {
                    "cycle": cycle,
                    "type": stage_type,
                },
            },
            cache_dir=cache_dir,
        )

    def test_primary_pool_no_longer_blocks_secondary_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "心法.md").write_text(
                "\n".join(
                    [
                        "## 标准调用池（日报优先）",
                        "### 语录｜ICE 冰点/退潮",
                        "- 主池语录甲甲甲甲甲甲甲甲",
                        "## 语录（Quotes）",
                        "### 退潮/防守",
                        "- 全量语录乙乙乙乙乙乙乙乙",
                    ]
                ),
                encoding="utf-8",
            )

            day1 = self._build_notes(workspace=workspace, date="2026-05-29")
            day2 = self._build_notes(workspace=workspace, date="2026-05-30")

            self.assertEqual(day1["quotes"], ["主池语录甲甲甲甲甲甲甲甲"])
            self.assertEqual(day2["quotes"], ["全量语录乙乙乙乙乙乙乙乙"])
            self.assertEqual(day2["meta"]["source"], "心法全量素材库（标准池优先）")

    def test_quote_rotation_covers_full_pool_before_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "心法.md").write_text(
                "\n".join(
                    [
                        "## 语录（Quotes）",
                        "### 分歧/中性",
                        "- 语录甲甲甲甲甲甲甲甲甲",
                        "- 语录乙乙乙乙乙乙乙乙乙",
                        "- 语录丙丙丙丙丙丙丙丙丙",
                    ]
                ),
                encoding="utf-8",
            )

            seen: list[str] = []
            for date in ["2026-05-29", "2026-05-30", "2026-05-31"]:
                notes = self._build_notes(workspace=workspace, date=date, cycle="", stage_type="warn")
                seen.append(notes["quotes"][0])

            day4 = self._build_notes(workspace=workspace, date="2026-06-01", cycle="", stage_type="warn")

            self.assertEqual(len(set(seen)), 3)
            self.assertEqual(day4["quotes"], [seen[0]])

    def test_dragon_section_is_not_treated_as_primary_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "心法.md").write_text(
                "\n".join(
                    [
                        "## 龙头战法（语义拆分）",
                        "### 语录｜通用｜龙头战法总纲",
                        "- 主动靠拢龙头，本质上就是拥抱最强大最有价值的企业",
                    ]
                ),
                encoding="utf-8",
            )

            notes = self._build_notes(workspace=workspace, date="2026-05-29", cycle="", stage_type="warn")

            self.assertEqual(notes["quotes"], ["主动靠拢龙头，本质上就是拥抱最强大最有价值的企业"])
            self.assertEqual(notes["meta"]["source"], "心法素材库")


if __name__ == "__main__":
    unittest.main()

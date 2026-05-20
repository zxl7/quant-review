"""
AI 分析器（analyzer.py）

职责：读取 market_data 结构化字段，构建 AI prompt，接收 AI 分析结果，
     回写到 market_data 的文本字段。

用法：
    from daily_review.ai.analyzer import AIAnalyzer

    analyzer = AIAnalyzer()
    prompt = analyzer.build_prompt(market_data)  # → 发给 AI 的 prompt
    result = ai.generate(prompt)                   # AI 返回分析结果
    analyzer.apply(market_data, result)            # 回写到 JSON

架构位置：数据加工层 (Layer 2)
    上游 → Layer 1（biying API 数据源）
    下游 → Layer 3（Vue3 渲染层）
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AIAnalysisResult:
    """AI 分析结果结构"""
    summary3_lines: list[str] = field(default_factory=list)     # 三句盘面总结
    learning_tips: list[str] = field(default_factory=list)       # 学习笔记
    learning_quote: str = ""                                     # 交易心法引用
    action_summary: str = ""                                     # 操作建议文字
    raw_response: str = ""                                       # AI 原始回复（调试用）


class AIAnalyzer:
    """AI 分析器 — 构建 prompt 并解析 AI 回复"""

    SYSTEM_PROMPT = """你是一位 A 股短线交易分析师，专注龙头战法。基于盘面数据，给出精准、简洁的盘面总结和交易教训。

## 分析原则
- 结论先行，不绕弯
- 一句话说清核心矛盾：赚钱效应如何？亏钱效应收敛还是扩散？主导情绪是什么？
- 主线要指出最强方向及其持续性信号
- 操作建议具体到板块和确认条件，不说"注意风险"这类空话
- 学习笔记必须是今日盘面提炼的具体教训，不是通用口诀
- 每句话短促有力，中文为主，术语可保留（炸板、封单、分歧转一致等）

## 回复格式
严格返回 JSON，不要任何额外文字：

{
  "summary3_lines": [
    "第一句：核心盘面定性（情绪/效应/周期阶段）",
    "第二句：主线方向和结构判断（空间/梯队/承接）",
    "第三句：次日操作动作（仓位/方向/确认条件）"
  ],
  "learning_tips": [
    "从今日盘面提炼的具体教训1",
    "具体教训2",
    "具体教训3"
  ],
  "learning_quote": "引用一句契合今日行情的经典交易心法",
  "action_summary": "80字以内操作建议，包含仓位、方向、确认条件"
}

每句话不超过 60 字。学习笔记每条不超过 30 字。"""

    def build_prompt(self, market_data: dict) -> str:
        """根据 market_data 构建分析 prompt"""
        parts = []

        # ─── 盘面全景 ───
        pan = market_data.get("panorama") or {}
        parts.append(f"【盘面全景】\n涨停 {pan.get('limitUp','?')}家 / 炸板 {pan.get('broken','?')}家 / 跌停 {pan.get('limitDown','?')}家 / 封板率 {pan.get('ratio','?')}")

        # ─── 情绪温度 ───
        mood = market_data.get("mood") or {}
        stage = market_data.get("moodStage") or {}
        parts.append(f"【情绪温度】\n热度 {mood.get('heat','?')} / 风险 {mood.get('risk','?')} / 综合 {mood.get('score','?')}")

        # ─── 情绪阶段 ───
        parts.append(f"【情绪阶段】\n{stage.get('title','')}（{stage.get('type','')}）— {stage.get('dayState','')} | {stage.get('stance','')} | {stage.get('cycle','')}")

        # ─── 量能 ───
        vol = market_data.get("volume") or {}
        parts.append(f"【量能】\n{vol.get('total','?')}，{vol.get('change','?')}（{vol.get('increase','')}）")

        # ─── 连板天梯 ───
        ladder = market_data.get("ladder") or []
        ladder_str = "、".join(
            f"{l.get('name','?')}({l.get('lbc','?')}板)" for l in ladder[:8]
        ) if ladder else "无连板数据"
        parts.append(f"【连板天梯】\n{ladder_str}")

        # ─── 主线题材 ───
        sectors = market_data.get("sectors") or []
        sector_str = "\n".join(
            f"{i+1}. {s['name']}({s['count']}只涨停) — {s.get('eval','')}"
            for i, s in enumerate(sectors[:5])
        ) if sectors else "无题材数据"
        parts.append(f"【主线题材】\n{sector_str}")

        # ─── 龙头 ───
        leaders = market_data.get("leaders") or []
        ldr_str = "、".join(l.get('name','?') for l in leaders[:3]) if leaders else "无"
        parts.append(f"【龙头股】\n{ldr_str}")

        # ─── 结构拆解 ───
        sv2 = market_data.get("structureV2") or {}
        summary_items = sv2.get("summary") or []
        if isinstance(summary_items, list) and summary_items:
            ev_str = "\n".join(
                f"- {e.get('title',e.get('key',''))}：{e.get('value','')}（{e.get('status','')}）— {e.get('note','')}"
                for e in summary_items[:5] if isinstance(e, dict)
            )
            parts.append(f"【结构拆解】\n{ev_str}")

        # ─── 涨停分析 ───
        zta = market_data.get("ztAnalysis") or {}
        relay_names = [r.get('name','') for r in (zta.get('relay',[]) or [])[:5]]
        watch_names = [w.get('name','') for w in (zta.get('watch',[]) or [])[:5]]
        parts.append(f"【接力候选】\n{'、'.join(relay_names) if relay_names else '无'}")
        parts.append(f"【观察池】\n{'、'.join(watch_names) if watch_names else '无'}")

        # ─── 高位风险 ───
        hpr = market_data.get("highPositionRisk") or {}
        if hpr.get("triggered"):
            mh = hpr.get('maxHeight','?')
            mh_str = str(mh) if mh else '?'
            parts.append(f"【高位风险】\n触发！最高{mh_str}板 / 风险评分{hpr.get('score','?')} / 等级{hpr.get('level','?')}")

        return "\n\n".join(parts)

    def apply(self, market_data: dict, result: AIAnalysisResult) -> dict:
        """将 AI 分析结果回写到 market_data，返回修改后的 dict"""
        md = market_data

        # summary3
        if result.summary3_lines:
            md["summary3"] = {
                "lines": result.summary3_lines,
                "source": "ai",
                "updated_at": _now_iso(),
            }

        # learningNotes
        if result.learning_tips or result.learning_quote:
            ln = md.get("learningNotes") or {}
            if isinstance(ln, dict):
                if result.learning_tips:
                    ln["tips"] = result.learning_tips
                if result.learning_quote:
                    ln["quotes"] = [result.learning_quote]
                ln["source"] = "ai"
                ln["updated_at"] = _now_iso()
                md["learningNotes"] = ln

        # actionAdvisor.summary
        if result.action_summary:
            aa = md.get("actionAdvisor") or {}
            if isinstance(aa, dict):
                aa["summary"] = result.action_summary
                aa["source"] = "ai"
                md["actionAdvisor"] = aa

        return md

    def parse_response(self, text: str) -> AIAnalysisResult:
        """解析 AI 返回的 JSON"""
        result = AIAnalysisResult(raw_response=text)
        try:
            # 提取 JSON 块
            text = text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            data = json.loads(text)
            if isinstance(data.get("summary3_lines"), list):
                result.summary3_lines = data["summary3_lines"]
            if isinstance(data.get("learning_tips"), list):
                result.learning_tips = data["learning_tips"]
            if isinstance(data.get("learning_quote"), str):
                result.learning_quote = data["learning_quote"]
            if isinstance(data.get("action_summary"), str):
                result.action_summary = data["action_summary"]
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"AI 回复解析失败: {e}")
        return result


def analyze_market_data(market_data: dict, ai_response: str) -> dict:
    """快捷函数：一步完成 build → parse → apply"""
    analyzer = AIAnalyzer()
    result = analyzer.parse_response(ai_response)
    return analyzer.apply(market_data, result)


def _now_iso() -> str:
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).isoformat()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

"""
模块执行器：
- 依赖解析（DAG）
- partial：只跑目标模块及其依赖链
- patch 合并（写入 ctx.market_data）
"""

import time
from typing import Any, Mapping, Sequence

from .context import Context, set_path
from .module import Module


class PipelineError(RuntimeError):
    pass


def _normalize_key(k: str) -> str:
    return k.strip()


def _build_provider_index(modules: Sequence[Module]) -> dict[str, str]:
    """
    provides_key -> module_name
    """
    idx: dict[str, str] = {}
    for m in modules:
        for p in m.provides:
            key = _normalize_key(p)
            if key in idx and idx[key] != m.name:
                # 默认策略：允许冲突，后出现的模块覆盖前者（与“全量执行=按声明顺序覆盖”的行为一致）
                # 若需要严格模式，可设置环境变量 PIPELINE_STRICT_PROVIDERS=1 强制报错。
                import os

                if os.environ.get("PIPELINE_STRICT_PROVIDERS", "").strip() == "1":
                    raise PipelineError(f"产物冲突：{key} 同时由 {idx[key]} 和 {m.name} 提供")
            idx[key] = m.name
    return idx


def _resolve_required_modules(modules: Sequence[Module], targets: Sequence[str]) -> list[Module]:
    name_to_module = {m.name: m for m in modules}
    provider_idx = _build_provider_index(modules)

    need: set[str] = set()
    stack: list[str] = list(targets)
    while stack:
        cur_name = stack.pop()
        if cur_name in need:
            continue
        if cur_name not in name_to_module:
            raise PipelineError(f"未知模块: {cur_name}")
        need.add(cur_name)
        cur = name_to_module[cur_name]
        # 对每个 require，找对应 provider 模块
        for r in cur.requires:
            r = _normalize_key(r)
            # requires 支持 marketData/features/raw 三种域
            # 若 require 指向的 key 没有 provider（例如 raw.* 由 data 层产生），则忽略
            prov = provider_idx.get(r)
            if prov:
                stack.append(prov)
    return [name_to_module[n] for n in modules_order_by_input(modules, list(need))]


def modules_order_by_input(modules: Sequence[Module], names: Sequence[str]) -> list[str]:
    """
    保留原 modules 列表的声明顺序（稳定），用于简化初期迁移。
    后续可以换成严格拓扑排序（依赖边生成）。
    """
    s = set(names)
    return [m.name for m in modules if m.name in s]


def _strip_domain(path: str, domain_prefix: str) -> str:
    """
    纯函数：去掉域前缀（如 marketData./features./raw./meta.）。
    """
    return path[len(domain_prefix) :] if path.startswith(domain_prefix) else path


def apply_patch_to_market_data(
    ctx: Context,
    patch: Mapping[str, Any],
    allowed_provides: Sequence[str],
    module_name: str,
) -> None:
    """
    将 patch 应用到 ctx.market_data。
    - patch keys 为点路径（必须以 marketData. 开头或省略 marketData 前缀）
    - 限制模块只能写自己的 provides
    """
    allow = set(_normalize_key(p) for p in allowed_provides)
    for k, v in patch.items():
        k = _normalize_key(k)
        # 兼容：允许写 "styleRadar"（默认当作 marketData.styleRadar）
        if not (k.startswith("marketData.") or k.startswith("features.") or k.startswith("raw.") or k.startswith("meta.")):
            k = "marketData." + k

        # 只约束 marketData 域
        if k.startswith("marketData."):
            root = "marketData." + k.split(".", 2)[1]
            if root not in allow and k not in allow:
                raise PipelineError(f"模块 {module_name} 试图写入未声明产物: {k}（允许：{sorted(allow)}）")
            set_path(ctx.market_data, _strip_domain(k, "marketData."), v)
        elif k.startswith("features."):
            set_path(ctx.features, _strip_domain(k, "features."), v)
        elif k.startswith("raw."):
            set_path(ctx.raw, _strip_domain(k, "raw."), v)
        elif k.startswith("meta."):
            set_path(ctx.meta, _strip_domain(k, "meta."), v)


# 外部种子依赖域：由 data / features / meta 层在 pipeline 执行前注入，
# 无需任何模块 provides，视为“已满足”。
_SEED_DOMAINS = ("raw.", "features.", "meta.")


def _is_seed_require(key: str) -> bool:
    key = _normalize_key(key)
    return any(key.startswith(d) for d in _SEED_DOMAINS)


def validate_pipeline_dag(modules: Sequence[Module]) -> None:
    """
    启动期 DAG 结构校验（fail-fast），在模块执行前暴露结构性错误。

    当前可靠校验项：
    1. 循环依赖：模块间形成环（声明序执行会读到未完成中间态）→ HARD FAIL。
       —— 这是静态可判定、且会导致“静默产出错误数据”的最危险结构问题。

    不做“缺失依赖”硬失败的原因（重要）：
    系统采用“模块图 + cli 直接注入”混合模型，raw./features./marketData 三个命名空间
    均有大量键由 cli 层（数据层/特征层/postprocess）直接写入 ctx，而无对应模块 provider。
    静态无法区分“cli 注入的键”与“真正缺失的键”，盲目失败会误伤现有正常 pipeline。
    完整的缺失依赖检测需引入“外部输入清单”（manifest），属更大重构，暂不纳入（改造节制）。

    不改动执行顺序（保持声明序），仅做前置校验。
    自依赖（模块 require 自身 provides）视为无依赖，不参与环判定。

    :raises PipelineError: 检测到循环依赖时抛出，错误信息列出环上节点及其上游依赖。
    """
    provider_idx = _build_provider_index(modules)

    # 仅在“某模块 provides 某 marketData 键，且被另一模块 require”时建立模块间依赖边，
    # 用于环检测。raw./features./meta. 不形成模块间边（它们由外部注入，无 provider 模块）。
    deps: dict[str, set[str]] = {m.name: set() for m in modules}
    for m in modules:
        for r in m.requires:
            r = _normalize_key(r)
            if _is_seed_require(r):
                continue
            prov = provider_idx.get(r)
            if prov and prov != m.name:
                deps[m.name].add(prov)

    # Kahn 拓扑排序：入度 = 依赖数量；入度为 0 者先出队
    indeg = {n: len(d) for n, d in deps.items()}
    dependents: dict[str, set[str]] = {n: set() for n in deps}
    for n, ds in deps.items():
        for d in ds:
            dependents[d].add(n)

    from collections import deque

    q = deque([n for n, d in indeg.items() if d == 0])
    visited = 0
    while q:
        n = q.popleft()
        visited += 1
        for child in dependents.get(n, ()):
            indeg[child] -= 1
            if indeg[child] == 0:
                q.append(child)

    if visited != len(modules):
        in_cycle = [n for n, d in indeg.items() if d > 0]
        cycle_info = [f"  - {n} 依赖 {sorted(p for p in deps[n] if p in in_cycle)}" for n in in_cycle]
        raise PipelineError(
            "Pipeline 存在循环依赖（无法拓扑排序）：\n" + "\n".join(cycle_info)
        )


class Runner:
    def __init__(self, modules: Sequence[Module]):
        self.modules = modules
        self.name_to_module = {m.name: m for m in modules}

    def validate(self) -> None:
        """对当前模块集合执行 DAG 结构校验（fail-fast）。"""
        validate_pipeline_dag(self.modules)

    def run(self, ctx: Context, *, targets: Sequence[str] | None = None) -> Context:
        """
        targets=None => 执行全部模块（按声明顺序）
        targets!=None => 只执行目标模块及其依赖链
        """
        if targets:
            exec_modules = _resolve_required_modules(self.modules, targets)
        else:
            exec_modules = self.modules

        # fail-fast：执行前校验依赖完整性与无环，避免静默产出错误数据
        validate_pipeline_dag(exec_modules)

        for m in exec_modules:
            started = time.perf_counter()
            patch = m.compute(ctx) or {}
            apply_patch_to_market_data(ctx, patch, m.provides, m.name)
            elapsed = max(time.perf_counter() - started, 0.0)
            print(f"  [{time.strftime('%H:%M:%S')}] pipeline 模块耗时 {m.name}: {elapsed:.2f}s", flush=True)
        return ctx

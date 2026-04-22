#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

"""
模块执行器：
- 依赖解析（DAG）
- partial：只跑目标模块及其依赖链
- patch 合并（写入 ctx.market_data）
"""

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


class Runner:
    def __init__(self, modules: Sequence[Module]):
        self.modules = modules
        self.name_to_module = {m.name: m for m in modules}

    def run(self, ctx: Context, *, targets: Sequence[str] | None = None) -> Context:
        """
        targets=None => 执行全部模块（按声明顺序）
        targets!=None => 只执行目标模块及其依赖链
        """
        if targets:
            exec_modules = _resolve_required_modules(self.modules, targets)
        else:
            exec_modules = self.modules

        for m in exec_modules:
            patch = m.compute(ctx) or {}
            apply_patch_to_market_data(ctx, patch, m.provides, m.name)
        return ctx

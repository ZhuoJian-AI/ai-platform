"""确定性数据生成工具——所有 mock 子系统共用，保证重启可复现。

禁止使用全局 ``random`` / ``datetime.now()`` 之类不可复现的状态：每个子系统在
``data.py`` 顶部用固定种子实例化 ``random.Random``，并通过本模块的纯函数取数。
"""

from __future__ import annotations

import random
from typing import Any, Sequence


def rng(seed: int) -> random.Random:
    """以固定种子构造一个独立 PRNG（互不污染）。"""
    return random.Random(seed)


def pick(r: random.Random, seq: Sequence[Any]) -> Any:
    """从序列随机取一个元素。"""
    return r.choice(seq)


def picks(r: random.Random, seq: Sequence[Any], k: int) -> list[Any]:
    """有放回取 k 个。"""
    return [r.choice(seq) for _ in range(k)]


def sample(r: random.Random, seq: Sequence[Any], k: int) -> list[Any]:
    """无放回取 k 个（k <= len(seq)）。"""
    return r.sample(list(seq), k)


def randint(r: random.Random, a: int, b: int) -> int:
    return r.randint(a, b)


def randfloat(r: random.Random, a: float, b: float, *, ndigits: int = 2) -> float:
    return round(r.uniform(a, b), ndigits)


def code(r: random.Random, prefix: str, width: int = 4) -> str:
    """生成形如 ``PREFIX0001`` 的顺序+随机编号。"""
    return f"{prefix}{r.randint(0, 10 ** width - 1):0{width}d}"


def pad(n: int, width: int = 4) -> str:
    return f"{n:0{width}d}"

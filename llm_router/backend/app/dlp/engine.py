"""DLP Engine — core rule evaluation pipeline."""

from __future__ import annotations

import asyncio
import re as stdlib_re
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

import regex

from app.models.dlp_rule import DlpRule


@dataclass
class DLPMatch:
    """单条规则的一个匹配结果。"""
    rule_id: UUID
    rule_name: str
    severity: str
    action: str
    start: int
    end: int
    matched_text: str
    matched_text_redacted: str = ""

    def __post_init__(self) -> None:
        if not self.matched_text_redacted:
            # 红acted版本：保留前后各1字符，中间用 *** 替代
            if len(self.matched_text) <= 3:
                self.matched_text_redacted = "***"
            else:
                self.matched_text_redacted = self.matched_text[0] + "***" + self.matched_text[-1]


@dataclass
class DLPResult:
    """DLP 扫描的最终结果。"""
    blocked: bool = False
    redacted_text: str | None = None
    violations: list[DLPMatch] = field(default_factory=list)
    warnings: list[DLPMatch] = field(default_factory=list)
    logged: list[DLPMatch] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return bool(self.violations or self.warnings or self.logged)


class RuleEvaluator(Protocol):
    """规则评估器协议。"""

    async def evaluate(self, text: str, rule: DlpRule) -> list[DLPMatch]:
        ...


class RegexEvaluator:
    """正则表达式规则评估器。"""

    async def evaluate(self, text: str, rule: DlpRule) -> list[DLPMatch]:
        try:
            # 优先使用 regex 包（支持高级特性）
            pattern = regex.compile(rule.pattern, regex.IGNORECASE)
        except regex.error:
            # fallback 到标准库 re
            try:
                pattern = stdlib_re.compile(rule.pattern, stdlib_re.IGNORECASE)
            except stdlib_re.error:
                return []

        matches = []
        for m in pattern.finditer(text):
            matches.append(
                DLPMatch(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    action=rule.action,
                    start=m.start(),
                    end=m.end(),
                    matched_text=m.group(),
                )
            )
        return matches


class KeywordEvaluator:
    """关键词规则评估器（Aho-Corasick 多模式匹配）。"""

    async def evaluate(self, text: str, rule: DlpRule) -> list[DLPMatch]:
        import json

        try:
            keywords: list[str] = json.loads(rule.pattern)
        except (json.JSONDecodeError, TypeError):
            # 如果不是 JSON 列表，按逗号分隔
            keywords = [kw.strip() for kw in rule.pattern.split(",") if kw.strip()]

        if not keywords:
            return []

        # 小规模关键词列表用简单搜索
        if len(keywords) < 20:
            matches = []
            text_lower = text.lower()
            for kw in keywords:
                kw_lower = kw.lower()
                start = 0
                while True:
                    idx = text_lower.find(kw_lower, start)
                    if idx == -1:
                        break
                    matches.append(
                        DLPMatch(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            severity=rule.severity,
                            action=rule.action,
                            start=idx,
                            end=idx + len(kw),
                            matched_text=text[idx : idx + len(kw)],
                        )
                    )
                    start = idx + 1
            return matches

        # 大规模列表使用 Aho-Corasick
        try:
            import ahocorasick

            automaton = ahocorasick.Automaton()
            for kw in keywords:
                automaton.add_word(kw.lower(), kw.lower())
            automaton.make_automaton()

            matches = []
            for end_idx, kw in automaton.iter(text.lower()):
                start_idx = end_idx - len(kw) + 1
                matches.append(
                    DLPMatch(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        severity=rule.severity,
                        action=rule.action,
                        start=start_idx,
                        end=end_idx + 1,
                        matched_text=text[start_idx : end_idx + 1],
                    )
                )
            return matches
        except ImportError:
            # 如果 ahocorasick 不可用，退回简单搜索
            return await RegexEvaluator().evaluate(text, rule)


class NEREvaluator:
    """命名实体识别规则评估器（基于内置正则模式）。"""

    # 内置实体识别模式
    ENTITY_PATTERNS: dict[str, str] = {
        "EMAIL": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "PHONE": r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|1[3-9]\d{9}",
        "IP_ADDRESS": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "PERSON_HINT": r"(?:姓名|名字|叫|name(?:\s+is)?)\s*[:：]?\s*[一-鿿]{2,4}",
        "ADDRESS_HINT": r"(?:地址|住址|address(?:\s+is)?)\s*[:：]?\s*[一-鿿\w\s,，]+(?:省|市|区|路|街|号|栋|室)",
    }

    async def evaluate(self, text: str, rule: DlpRule) -> list[DLPMatch]:
        import json

        # 获取需要检测的实体类型
        try:
            entity_types: list[str] = json.loads(rule.pattern)
        except (json.JSONDecodeError, TypeError):
            entity_types = [e.strip() for e in rule.pattern.split(",") if e.strip()]

        matches = []
        for entity_type in entity_types:
            pattern_str = self.ENTITY_PATTERNS.get(entity_type.upper())
            if not pattern_str:
                continue
            try:
                for m in regex.finditer(pattern_str, text, regex.IGNORECASE):
                    matches.append(
                        DLPMatch(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            severity=rule.severity,
                            action=rule.action,
                            start=m.start(),
                            end=m.end(),
                            matched_text=m.group(),
                        )
                    )
            except regex.error:
                continue
        return matches


class CustomEvaluator:
    """自定义规则评估器（沙箱化执行）。"""

    ALLOWED_BUILTINS = {
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "set": set,
        "tuple": tuple,
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "min": min,
        "max": max,
        "abs": abs,
        "any": any,
        "all": all,
        "sorted": sorted,
        "reversed": reversed,
        "isinstance": isinstance,
    }

    async def evaluate(self, text: str, rule: DlpRule) -> list[DLPMatch]:
        """在受限环境中执行自定义规则代码。

        自定义代码应定义 `scan(text: str) -> list[dict]` 函数，
        每个 dict 包含 {start, end, matched_text}。
        """
        code = rule.pattern
        sandbox_globals = {"__builtins__": self.ALLOWED_BUILTINS, "regex": regex}
        try:
            exec(code, sandbox_globals)  # noqa: S102
            scan_fn = sandbox_globals.get("scan")
            if not callable(scan_fn):
                return []
            results = scan_fn(text)
            return [
                DLPMatch(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    action=rule.action,
                    start=r.get("start", 0),
                    end=r.get("end", 0),
                    matched_text=r.get("matched_text", ""),
                )
                for r in results
            ]
        except Exception:
            return []


class DLPEngine:
    """DLP 评估引擎。"""

    def __init__(self, rules: list[DlpRule]) -> None:
        self.rules = sorted(rules, key=lambda r: r.priority, reverse=True)
        self._evaluators: dict[str, RuleEvaluator] = {
            "regex": RegexEvaluator(),
            "keyword": KeywordEvaluator(),
            "ner": NEREvaluator(),
            "custom": CustomEvaluator(),
        }

    async def scan(self, text: str, direction: str = "both") -> DLPResult:
        """扫描文本，评估所有适用规则。"""
        # 过滤方向匹配的规则
        applicable_rules = [
            r for r in self.rules
            if r.is_active
            and (r.direction in (direction, "both"))
        ]

        if not applicable_rules or not text:
            return DLPResult()

        # 并行评估所有规则
        tasks = [self._evaluate_rule(text, rule) for rule in applicable_rules]
        all_matches_list = await asyncio.gather(*tasks)

        # 合并所有匹配
        all_matches: list[DLPMatch] = []
        for matches in all_matches_list:
            all_matches.extend(matches)

        return self._build_result(text, all_matches)

    async def _evaluate_rule(self, text: str, rule: DlpRule) -> list[DLPMatch]:
        evaluator = self._evaluators.get(rule.rule_type)
        if evaluator is None:
            return []
        return await evaluator.evaluate(text, rule)

    def _build_result(self, text: str, matches: list[DLPMatch]) -> DLPResult:
        """根据匹配结果构建 DLPResult，应用动作。"""
        result = DLPResult()

        # 按位置排序，合并重叠区间
        matches.sort(key=lambda m: (m.start, m.end))

        # 应用动作
        for match in matches:
            if match.action == "block":
                result.blocked = True
                result.violations.append(match)
            elif match.action == "redact":
                result.violations.append(match)
            elif match.action == "warn":
                result.warnings.append(match)
            elif match.action == "log":
                result.logged.append(match)

        # 如果有任何 block 匹配，直接返回
        if result.blocked:
            return result

        # 执行 redact
        redact_matches = [m for m in matches if m.action == "redact"]
        if redact_matches:
            result.redacted_text = self._redact_text(text, redact_matches)

        return result

    @staticmethod
    def _redact_text(text: str, matches: list[DLPMatch]) -> str:
        """将匹配区间替换为 [REDACTED]。"""
        if not matches:
            return text

        # 从后往前替换，避免偏移
        sorted_matches = sorted(matches, key=lambda m: m.start, reverse=True)
        for m in sorted_matches:
            text = text[: m.start] + "[REDACTED]" + text[m.end :]
        return text

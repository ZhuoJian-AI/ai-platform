"""DLP Stream Scanner — real-time scanning for SSE streaming responses."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.dlp.engine import DLPEngine, DLPMatch, DLPResult
from app.models.dlp_rule import DlpRule


@dataclass
class StreamScanResult:
    """流式扫描单个 chunk 的结果。"""
    emit_text: str = ""  # 可以安全转发的文本
    blocked: bool = False  # 是否应终止流
    violations: list[DLPMatch] = field(default_factory=list)
    pending: bool = False  # 是否有部分匹配等待确认


class DLPStreamScanner:
    """实时流式 DLP 扫描器。

    使用滑动窗口缓冲区检测跨 chunk 边界的 DLP 违规。
    - 维护 ring buffer 存储近期文本
    - 每个 chunk 到达时扫描缓冲区
    - 无违规 → 立即转发
    - 部分匹配 → 缓冲等待确认
    - 确认违规 → 执行 action (BLOCK / REDACT)
    """

    def __init__(
        self,
        rules: list[DlpRule],
        buffer_window: int = 4096,
        flush_timeout_ms: int = 200,
    ) -> None:
        self.engine = DLPEngine(rules=rules)
        self.buffer_window = buffer_window
        self.flush_timeout_ms = flush_timeout_ms

        # 扫描状态
        self._buffer: str = ""
        self._confirmed_offset: int = 0  # 已确认可安全转发的偏移
        self._last_flush_time: float = time.monotonic()
        self._chunk_count: int = 0

    async def feed_chunk(self, text: str, direction: str = "response") -> StreamScanResult:
        """输入新的文本 chunk，返回可安全转发的内容。"""
        self._buffer += text
        self._chunk_count += 1

        # 运行 DLP 扫描
        result = await self.engine.scan(self._buffer, direction=direction)

        # 如果检测到 BLOCK
        if result.blocked:
            return StreamScanResult(
                emit_text="",
                blocked=True,
                violations=result.violations,
            )

        # 计算安全的转发边界
        safe_end = self._compute_safe_boundary(result)
        emit_text = self._apply_redactions(
            self._buffer[self._confirmed_offset : safe_end],
            result.violations,
        )
        self._confirmed_offset = safe_end

        # 超时检查：强制 flush 缓冲区
        now = time.monotonic()
        elapsed_ms = (now - self._last_flush_time) * 1000
        if elapsed_ms > self.flush_timeout_ms and len(self._buffer) > self._confirmed_offset:
            # 超时未确认的部分直接转发
            remaining = self._buffer[self._confirmed_offset :]
            emit_text += remaining
            self._confirmed_offset = len(self._buffer)
            self._last_flush_time = now

        # 修剪缓冲区
        if len(self._buffer) - self._confirmed_offset > self.buffer_window:
            excess = len(self._buffer) - self._confirmed_offset - self.buffer_window
            emit_text += self._buffer[self._confirmed_offset : self._confirmed_offset + excess]
            self._confirmed_offset += excess

        # 保持滑动窗口
        trim_point = max(0, self._confirmed_offset - self.buffer_window)
        self._buffer = self._buffer[trim_point:]
        self._confirmed_offset -= trim_point

        return StreamScanResult(
            emit_text=emit_text,
            violations=result.violations,
            pending=safe_end < len(self._buffer),
        )

    async def flush(self, direction: str = "response") -> StreamScanResult:
        """流结束时强制 flush 所有剩余文本。"""
        remaining = self._buffer[self._confirmed_offset :]
        if not remaining:
            return StreamScanResult()

        # 最终扫描
        result = await self.engine.scan(remaining, direction=direction)
        emit_text = self._apply_redactions(remaining, result.violations)

        return StreamScanResult(
            emit_text=emit_text,
            blocked=result.blocked,
            violations=result.violations,
        )

    def _compute_safe_boundary(self, result: DLPResult) -> int:
        """计算安全转发边界：总长度减去最长规则的 lookahead。"""
        import regex

        max_lookahead = 0
        for rule in self.engine.rules:
            if rule.rule_type == "regex":
                try:
                    compiled = regex.compile(rule.pattern)
                    # 估算最大可能匹配长度（粗略）
                    max_lookahead = max(max_lookahead, 256)
                except regex.error:
                    pass
            elif rule.rule_type == "keyword":
                import json
                try:
                    kws = json.loads(rule.pattern)
                    if isinstance(kws, list):
                        max_lookahead = max(max_lookahead, max(len(kw) for kw in kws) if kws else 0)
                except (json.JSONDecodeError, TypeError):
                    pass

        boundary = len(self._buffer) - max_lookahead
        return max(self._confirmed_offset, boundary)

    @staticmethod
    def _apply_redactions(text: str, violations: list[DLPMatch]) -> str:
        """对文本应用 REDACT 动作。"""
        redact_matches = [v for v in violations if v.action == "redact"]
        if not redact_matches:
            return text

        # 从后往前替换
        sorted_matches = sorted(redact_matches, key=lambda m: m.start, reverse=True)
        for m in sorted_matches:
            if 0 <= m.start < len(text) and m.end <= len(text):
                text = text[: m.start] + "[REDACTED]" + text[m.end :]
        return text

"""llm_client 单测:stream_completion 的 on_log 推理进度回调。

对应 app/ai_assistant/tools/llm_client.py 的 stream_completion(on_log):
推理内容每满 REASONING_PROGRESS_INTERVAL(1000)字符汇报一次,
控制台打印的同时调用 on_log,供 app/book_import 写入任务日志在前端展示。
不触网(client 为内存假对象)。
"""

from __future__ import annotations

import unittest

from app.ai_assistant.tools import llm_client
from app.ai_assistant.tools.common import utf8_stdout


class _FakeDelta:
    def __init__(self, content: str = "", reasoning: str = ""):
        self.content = content
        self.reasoning_content = reasoning


class _FakeChoice:
    def __init__(self, delta: _FakeDelta):
        self.delta = delta


class _FakeChunk:
    def __init__(self, delta: _FakeDelta):
        self.choices = [_FakeChoice(delta)]


class _FakeResponse:
    """模拟流式响应:把整段 reasoning 按 500 字符切成若干 chunk,正文整体一个 chunk。"""

    def __init__(self, reasoning: str = "", content: str = ""):
        chunks = [
            _FakeChunk(_FakeDelta(reasoning=reasoning[i : i + 500]))
            for i in range(0, len(reasoning), 500)
        ]
        if content:
            chunks.append(_FakeChunk(_FakeDelta(content=content)))
        self._chunks = chunks

    def __iter__(self):
        return iter(self._chunks)


class _FakeCompletions:
    def __init__(self, resp: _FakeResponse):
        self._resp = resp

    def create(self, **kwargs):
        return self._resp


class _FakeChat:
    def __init__(self, resp: _FakeResponse):
        self.completions = _FakeCompletions(resp)


class _FakeClient:
    def __init__(self, resp: _FakeResponse):
        self.chat = _FakeChat(resp)


class _FakeClientSeq:
    """按调用顺序依次返回不同响应(模拟重试)。"""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []
        responses_ref = self._responses
        calls_ref = self.calls

        class _Completions:
            def create(self, **kwargs):
                calls_ref.append(kwargs)
                return responses_ref.pop(0)

        chat = type("_Chat", (), {})()
        chat.completions = _Completions()
        self.chat = chat


class StreamCompletionLogTest(unittest.TestCase):
    def test_on_log_receives_reasoning_progress(self) -> None:
        utf8_stdout()
        reasoning_text = "思" * 2500
        lines: list[str] = []
        _, reasoning = llm_client.stream_completion(
            _FakeClient(_FakeResponse(reasoning_text)),
            [],
            model="deepseek-v4-flash",
            thinking=False,
            on_log=lines.append,
        )
        self.assertEqual(reasoning, reasoning_text)
        self.assertEqual(
            lines,
            ["  思考中... 已接收 1000 字符", "  思考中... 已接收 2000 字符"],
        )

    def test_without_on_log_still_works(self) -> None:
        utf8_stdout()
        reasoning_text = "思" * 1000
        _, reasoning = llm_client.stream_completion(
            _FakeClient(_FakeResponse(reasoning_text)),
            [],
            model="deepseek-v4-flash",
            thinking=False,
        )
        self.assertEqual(reasoning, reasoning_text)


class CallJsonCompletionRetryTest(unittest.TestCase):
    def test_retries_reasoning_only_then_recovers(self) -> None:
        """模型先返回「只思考无正文」→ 自动重试 → 第二次返回合法 JSON。"""
        utf8_stdout()
        client = _FakeClientSeq([
            _FakeResponse(reasoning="思" * 1200),  # 空正文:触发重试
            _FakeResponse(content='{"ok": true, "n": 1}'),
        ])
        result = llm_client.call_json_completion(
            client,
            [],
            model="deepseek-v4-flash",
            thinking=False,
            max_retries=2,
            backoff_seconds=0,
        )
        self.assertEqual(result, {"ok": True, "n": 1})
        self.assertEqual(len(client.calls), 2)

    def test_persistent_empty_content_raises_clear_error(self) -> None:
        """持续空正文时重试耗尽,抛出带「未返回正文内容」的明确错误。"""
        utf8_stdout()
        client = _FakeClientSeq([
            _FakeResponse(reasoning="思" * 1000),
            _FakeResponse(reasoning="思" * 1000),
            _FakeResponse(reasoning="思" * 1000),
        ])
        with self.assertRaises(ValueError) as ctx:
            llm_client.call_json_completion(
                client,
                [],
                model="deepseek-v4-flash",
                thinking=False,
                max_retries=2,
                backoff_seconds=0,
            )
        self.assertIn("未返回正文内容", str(ctx.exception))
        self.assertEqual(len(client.calls), 3)  # 首次 + 2 次重试


if __name__ == "__main__":
    unittest.main()

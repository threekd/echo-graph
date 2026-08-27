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
    """模拟流式响应:把整段 reasoning 按 500 字符切成若干 chunk。"""

    def __init__(self, reasoning: str):
        self._chunks = [
            _FakeChunk(_FakeDelta(reasoning=reasoning[i : i + 500]))
            for i in range(0, len(reasoning), 500)
        ]

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


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

"""DeepSeek LLM 调用公共工具。

供 agent_temp 下的实验脚本复用,避免各脚本各自维护一份 API 客户端代码:

- 统一从项目根目录 .env 加载 DEEPSEEK_* 配置(见 tools/common.load_dotenv_once)
- 模型名由 DEEPSEEK_MODEL 控制(默认 deepseek-v4-flash;官方另可选 deepseek-v4-pro)
- 深度思考由 DEEPSEEK_THINKING 控制(1/true/yes/on 开启)
- 统一的超时、重试、流式输出进度与 JSON 解析
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from openai import OpenAI

from agent_temp.tools.common import load_dotenv_once, utf8_stdout

# 导入即加载 .env,保证下面的 MODEL / THINKING 能读到项目配置覆盖
load_dotenv_once()

# 模型名:可用环境变量 DEEPSEEK_MODEL 覆盖
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

# 是否开启深度思考。开启后思考阶段只推 reasoning 内容,正文要等思考结束才
# 开始输出,首字延迟会明显变长(可能超过 1 分钟)。
THINKING = os.getenv("DEEPSEEK_THINKING", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

REQUEST_TIMEOUT_SECONDS = 120.0  # API 请求超时,避免网络/服务器无响应时无限挂起
MAX_RETRIES = 2  # API 请求失败时的重试次数
REASONING_PROGRESS_INTERVAL = 1000  # 思考阶段每隔多少字符汇报一次进度


def load_environment() -> tuple[str, str]:
    """加载项目根目录 .env 并校验必需配置,返回 (api_key, base_url)。"""
    load_dotenv_once()

    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL")
    if not api_key or not base_url:
        raise RuntimeError(
            "缺少 DEEPSEEK_API_KEY 或 DEEPSEEK_BASE_URL,请在项目根目录的 .env 中配置"
        )
    return api_key, base_url


def create_client(api_key: str, base_url: str) -> OpenAI:
    """创建带超时与重试策略的 OpenAI 客户端。"""
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
    )


def _process_chunk(delta: Any) -> tuple[str, str]:
    """从单个流式增量中提取正文与思考内容,返回 (content, reasoning_content)。"""
    # reasoning_content 是 DeepSeek 自定义字段,SDK 未声明类型,用 getattr 防御
    reasoning = getattr(delta, "reasoning_content", None) or ""
    content = delta.content or ""
    return content, reasoning


def stream_completion(
    client: OpenAI,
    messages: list[dict[str, str]],
    *,
    model: str = MODEL,
    thinking: bool = THINKING,
    on_log: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """调用模型并实时显示流式输出,返回 (content, reasoning_content)。

    on_log 可选:推理进度每到达一个汇报点(REASONING_PROGRESS_INTERVAL 字符),
    除了打印到控制台外,也会调用 on_log(行文本),供 Web 端把「思考中...
    已接收 N 字符」同步展示到前端。
    """
    utf8_stdout()
    request_options: dict[str, Any] = {}
    if thinking:
        request_options["extra_body"] = {"thinking": {"type": "enabled"}}

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        response_format={"type": "json_object"},
        **request_options,
    )

    content = ""
    reasoning_content = ""
    last_reported = 0
    print("▶ 开始接收流式响应(正文会实时显示,Ctrl+C 可中断):", flush=True)

    for chunk in response:
        if not chunk.choices:  # 跳过无 choices 的 chunk(如 usage 块)
            continue
        delta_content, delta_reasoning = _process_chunk(chunk.choices[0].delta)

        # 思考阶段没有正文输出,定期提示进度,避免看起来像卡死
        if delta_reasoning:
            reasoning_content += delta_reasoning
            if len(reasoning_content) - last_reported >= REASONING_PROGRESS_INTERVAL:
                line = f"  思考中... 已接收 {len(reasoning_content)} 字符"
                print(line, flush=True)
                if on_log is not None:
                    on_log(line)
                last_reported = len(reasoning_content)

        if delta_content:
            content += delta_content
            print(delta_content, end="", flush=True)  # 实时显示正文(最终结果即 JSON)

    print("", flush=True)
    return content, reasoning_content


def parse_json(content: str) -> dict[str, Any]:
    """解析模型输出的 JSON(容忍常见的 Markdown 代码围栏)。"""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败:{exc}\n原始内容:\n{content}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"JSON 顶层应为对象,实际为 {type(parsed).__name__}")
    return parsed

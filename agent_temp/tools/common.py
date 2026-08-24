"""agent_temp 实验管线共享工具:仓库根路径、日志、时间戳、JSON 读写与 .env 加载。

所有 agent_temp 下的 CLI 工具统一从这里取「项目根目录」与基础工具,
避免每个脚本各自维护一份 sys.path 拼接 / log / now_iso / JSON 读写。
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# 项目根目录:agent_temp/tools/common.py -> <root>/
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENT_TEMP_DIR = REPO_ROOT / "agent_temp"
TOOLS_DIR = AGENT_TEMP_DIR / "tools"

# 允许以「uv run python -m agent_temp.tools.<tool>」从仓库根目录运行
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_dotenv_loaded = False


def load_dotenv_once() -> None:
    """加载项目根目录 .env(幂等)。"""
    global _dotenv_loaded
    if not _dotenv_loaded:
        load_dotenv(REPO_ROOT / ".env")
        _dotenv_loaded = True


def log(msg: str) -> None:
    """带时间戳的立即输出,避免 stdout 缓冲导致看不到进度。"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def now_iso() -> str:
    """UTC 秒级 ISO-8601 时间戳。"""
    return datetime.now(UTC).isoformat(timespec="seconds")


def utf8_stdout() -> None:
    """把 stdout 切到 UTF-8,避免 Windows GBK 控制台打印任意 Unicode 报错。

    仅 CLI 入口调用(不改变导入方行为);重定向管道/文件时同样生效。
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, data: Any) -> Path:
    """原子写 JSON(UTF-8、缩进、非 ASCII 原样保留);返回写入路径。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target

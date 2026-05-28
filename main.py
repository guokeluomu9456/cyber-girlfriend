"""
Cyber Girlfriend - Entry Point

微信赛博女友启动入口，通过 Hermes Agent Gateway 接入微信。

用法:
    python main.py
    python main.py --config config.yaml
    python main.py --persona kawaii
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

# === Bootstrap ===
# 确保 UTF-8 输出（Windows）
try:
    import hermes_bootstrap  # noqa: F401
except ModuleNotFoundError:
    pass

# === Load environment variables ===
from dotenv import load_dotenv

# 从项目根目录加载 .env
_project_root = Path(__file__).parent.resolve()
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)
else:
    load_dotenv(override=True)  # 尝试从当前目录加载

# === Imports ===
import yaml
from persona_loader import PersonaLoader
from memory_store import MemoryStore

# Hermes Agent imports
from gateway.run import start_gateway
from hermes_cli.config import get_config_path, get_env_path
from hermes_constants import get_hermes_home


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cyber_girlfriend")


# =============================================================================
# Signal handling
# =============================================================================

def _sigterm_handler(signum, frame):
    logger.info("Received SIGTERM, shutting down gracefully...")
    sys.exit(0)


signal.signal(signal.SIGTERM, _sigterm_handler)


# =============================================================================
# Config loading
# =============================================================================

def load_project_config(config_path: str | None = None) -> dict:
    """加载项目级 config.yaml"""
    if config_path is None:
        config_path = _project_root / "config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        logger.warning("Config file not found: %s, using defaults", config_path)
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def merge_with_hermes_config(project_config: dict) -> dict:
    """将项目配置与 Hermes 全局配置合并"""
    hermes_config_path = get_config_path()
    if not hermes_config_path.exists():
        return project_config

    with open(hermes_config_path, "r", encoding="utf-8") as f:
        hermes_config = yaml.safe_load(f) or {}

    # 深合并：channels 和 personalities 以项目配置为准
    merged = dict(hermes_config)
    if "channels" in project_config:
        merged["channels"] = project_config["channels"]
    if "personalities" in project_config:
        merged["personalities"] = project_config["personalities"]
    if "memory" in project_config:
        merged["memory"] = project_config["memory"]

    return merged


# =============================================================================
# Environment variable validation
# =============================================================================

def _validate_secrets():
    """验证必要的环境变量"""
    missing = []

    # iLink Bot 凭证（微信接入必需）
    if not os.getenv("ILINK_API_KEY"):
        missing.append("ILINK_API_KEY")
    if not os.getenv("ILINK_BOT_ID"):
        missing.append("ILINK_BOT_ID")

    # LLM 凭证（至少需要一个）
    has_llm = any([
        os.getenv("MINIMAX_API_KEY"),
        os.getenv("OPENAI_API_KEY"),
        os.getenv("XAI_API_KEY"),
    ])
    if not has_llm:
        missing.append("MINIMAX_API_KEY / OPENAI_API_KEY / XAI_API_KEY (至少一个)")

    if missing:
        logger.warning(
            "Missing environment variables: %s\n"
            "Please fill in .env before running.\n"
            "See .env.example for reference.",
            ", ".join(missing),
        )


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Cyber Girlfriend - 微信赛博女友")
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml in project root)",
    )
    parser.add_argument(
        "--persona", "-p",
        default=None,
        help="Override default persona (e.g. kawaii, gentle, tsundere)",
    )
    parser.add_argument(
        "--skip-memory",
        action="store_true",
        help="Disable memory system",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 1. 加载项目配置
    project_config = load_project_config(args.config)
    logger.info("Project config loaded from %s", args.config)

    # 2. 验证必要的环境变量
    _validate_secrets()

    # 3. 初始化 Persona Loader
    persona_loader = PersonaLoader(project_config, _project_root)
    if args.persona:
        persona_loader.set_default_persona(args.persona)

    # 4. 初始化 Memory Store
    memory_config = project_config.get("memory", {})
    if not args.skip_memory and memory_config.get("enabled", True):
        memory_store = MemoryStore(
            auto_expire_days=memory_config.get("auto_expire_days", 30),
            tiers=memory_config.get("tiers", ["critical", "important", "normal", "minor"]),
        )
        logger.info(
            "Memory enabled (auto_expire_days=%s, tiers=%s)",
            memory_config.get("auto_expire_days", 30),
            memory_config.get("tiers", ["critical", "important", "normal", "minor"]),
        )
    else:
        memory_store = None
        logger.info("Memory disabled")

    # 5. 注入 persona 和 memory 到 Hermes 配置
    merged_config = merge_with_hermes_config(project_config)

    # 6. 启动 Gateway（阻塞）
    logger.info("Starting Cyber Girlfriend...")
    logger.info("Default persona: %s", persona_loader.get_default_persona_name())

    try:
        start_gateway(merged_config)
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting...")
    except Exception as e:
        logger.exception("Gateway error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
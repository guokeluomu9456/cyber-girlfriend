"""
Persona Loader - 人格加载模块

从 config.yaml 读取 persona 路径，动态加载 system prompt。
支持 'file:path/to/file.txt' 格式。

用法:
    loader = PersonaLoader(config, project_root)
    system_prompt = loader.get_system_prompt("kawaii")
    default_name = loader.get_default_persona_name()
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("persona_loader")

# Persona 路径解析正则：'file:path/to/file.txt' 或 'env:VAR_NAME'
_PERSONA_PATH_RE = re.compile(r"^file:(.+)$")


class PersonaNotFoundError(ValueError):
    """找不到指定的 persona"""
    pass


class PersonaLoader:
    """动态加载人格定义的模块"""

    def __init__(self, config: dict, project_root: Path | str):
        """
        Args:
            config: 解析后的 config.yaml dict
            project_root: 项目根目录（用于解析相对路径）
        """
        self._project_root = Path(project_root).resolve()
        self._personalities = config.get("personalities", {})
        self._channel_prompts = (
            config.get("channels", {})
            .get("weixin", {})
            .get("extra", {})
            .get("channel_prompts", {})
        )
        self._default_persona: str | None = None
        self._cache: dict[str, str] = {}

        # 自动选择第一个 persona 作为默认
        if self._personalities:
            self._default_persona = next(iter(self._personalities.keys()))

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_system_prompt(self, persona_name: str | None = None) -> str:
        """
        获取指定 persona 的完整 system prompt。

        Args:
            persona_name: personality key in config, or WeChat user ID
                         (e.g. 'kawaii' or 'user123@im.wechat')
        Returns:
            完整的 system prompt 字符串
        Raises:
            PersonaNotFoundError: persona 不存在
        """
        # 如果传入 WeChat user ID，尝试从 channel_prompts 映射
        resolved_name = self._resolve_channel_prompt(persona_name)
        if resolved_name is None:
            resolved_name = persona_name or self._default_persona
            if resolved_name is None:
                raise PersonaNotFoundError(
                    "No default persona set and no persona name provided"
                )

        # 检查缓存
        if resolved_name in self._cache:
            logger.debug("Using cached system prompt for '%s'", resolved_name)
            return self._cache[resolved_name]

        # 查找 personality 定义
        personality_config = self._personalities.get(resolved_name)
        if personality_config is None:
            raise PersonaNotFoundError(
                f"Persona '{resolved_name}' not found in config. "
                f"Available: {list(self._personalities.keys())}"
            )

        system_prompt = self._load_from_source(personality_config)

        # 缓存
        self._cache[resolved_name] = system_prompt
        logger.info("Loaded persona '%s' (cached=%s)", resolved_name, resolved_name in self._cache)

        return system_prompt

    def get_default_persona_name(self) -> str:
        """返回默认 persona 名称"""
        return self._default_persona or "kawaii"

    def set_default_persona(self, name: str) -> None:
        """设置默认 persona"""
        if name not in self._personalities:
            raise PersonaNotFoundError(
                f"Cannot set default to '{name}': not found. "
                f"Available: {list(self._personalities.keys())}"
            )
        self._default_persona = name
        logger.info("Default persona set to '%s'", name)

    def list_personas(self) -> list[str]:
        """返回所有可用 persona 名称"""
        return list(self._personalities.keys())

    def reload(self, persona_name: str | None = None) -> None:
        """
        重新加载 persona（清除缓存）。

        Args:
            persona_name: None 表示清除所有缓存
        """
        if persona_name:
            self._cache.pop(persona_name, None)
            logger.info("Reloaded '%s'", persona_name)
        else:
            self._cache.clear()
            logger.info("All persona caches cleared")

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _resolve_channel_prompt(self, name: str | None) -> str | None:
        """检查 name 是否是 WeChat user ID，尝试映射到 persona"""
        if name is None:
            return None
        # channel_prompts 的 key 格式: 'user_id@im.wechat'
        # value 格式: 'file:personas/kawaii.txt'
        for wechat_id, prompt_spec in self._channel_prompts.items():
            if wechat_id == name or wechat_id.startswith(name.split("@")[0]):
                # 从 prompt_spec 解析出 persona name
                return self._extract_persona_name_from_spec(prompt_spec)
        return None

    def _extract_persona_name_from_spec(self, spec: str) -> str | None:
        """从 'file:personas/kawaii.txt' 提取 'kawaii'"""
        match = _PERSONA_PATH_RE.match(spec)
        if not match:
            return None
        path_str = match.group(1)
        path = Path(path_str)
        # 文件名（不含扩展名）作为 persona name
        return path.stem

    def _load_from_source(self, personality_config: str | dict) -> str:
        """
        加载 prompt 内容。

        支持格式:
          - 'file:personas/kawaii.txt'   → 读取本地文件
          - 'env:PERSONA_KAWAII'         → 从环境变量读取
          - dict with 'type'/'source' keys
        """
        # 处理 dict 格式
        if isinstance(personality_config, dict):
            source = personality_config.get("system_prompt", "")
            if isinstance(source, str) and source.startswith("file:"):
                return self._load_file(source)
            return str(source)

        # 字符串格式
        if isinstance(personality_config, str):
            return self._load_file(personality_config)

        raise PersonaNotFoundError(
            f"Invalid personality config type: {type(personality_config).__name__}"
        )

    def _load_file(self, spec: str) -> str:
        """
        解析 'file:path/to/file.txt' 并读取文件内容。

        路径相对于 project_root。
        """
        match = _PERSONA_PATH_RE.match(spec)
        if not match:
            raise PersonaNotFoundError(
                f"Cannot parse file spec '{spec}'. Expected 'file:path/to/file.txt'"
            )

        relative_path = match.group(1)
        file_path = (self._project_root / relative_path).resolve()

        if not file_path.exists():
            raise PersonaNotFoundError(
                f"Persona file not found: {file_path}\n"
                f"Resolved from spec '{spec}'"
            )

        content = file_path.read_text(encoding="utf-8")
        return content.strip()
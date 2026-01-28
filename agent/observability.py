#!/usr/bin/env python3
"""
Observability utilities (LangSmith tracing)
"""

import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


HARDCODED_LANGSMITH_API_KEY = "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"
HARDCODED_LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"
HARDCODED_LANGSMITH_PROJECT = "test1"
HARDCODED_LANGSMITH_TRACING = "true"


def configure_langsmith() -> bool:
    """Enable LangSmith tracing if API key is present."""
    api_key = HARDCODED_LANGSMITH_API_KEY or os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not api_key:
        logger.info("LangSmith tracing not enabled (missing API key)")
        return False

    if HARDCODED_LANGSMITH_API_KEY and not os.getenv("LANGSMITH_API_KEY"):
        os.environ["LANGSMITH_API_KEY"] = HARDCODED_LANGSMITH_API_KEY

    if not os.getenv("LANGSMITH_TRACING") and HARDCODED_LANGSMITH_TRACING:
        os.environ["LANGSMITH_TRACING"] = HARDCODED_LANGSMITH_TRACING

    if not os.getenv("LANGSMITH_ENDPOINT") and HARDCODED_LANGSMITH_ENDPOINT:
        os.environ["LANGSMITH_ENDPOINT"] = HARDCODED_LANGSMITH_ENDPOINT

    if not os.getenv("LANGSMITH_PROJECT") and HARDCODED_LANGSMITH_PROJECT:
        os.environ["LANGSMITH_PROJECT"] = HARDCODED_LANGSMITH_PROJECT

    if os.getenv("LANGSMITH_API_KEY") and not os.getenv("LANGCHAIN_API_KEY"):
        os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGSMITH_API_KEY")

    if os.getenv("LANGSMITH_PROJECT") and not os.getenv("LANGCHAIN_PROJECT"):
        os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT")

    if os.getenv("LANGSMITH_ENDPOINT") and not os.getenv("LANGCHAIN_ENDPOINT"):
        os.environ["LANGCHAIN_ENDPOINT"] = os.getenv("LANGSMITH_ENDPOINT")

    if not (os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2")):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"

    _log_langsmith_status()
    logger.info("LangSmith tracing enabled")
    return True


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def _log_langsmith_status() -> None:
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    endpoint = os.getenv("LANGSMITH_ENDPOINT") or os.getenv("LANGCHAIN_ENDPOINT")
    project = os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT")
    tracing = os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2")
    logger.info(
        "LangSmith config: tracing=%s, endpoint=%s, project=%s, api_key=%s",
        tracing,
        endpoint,
        project,
        _mask_key(api_key or ""),
    )

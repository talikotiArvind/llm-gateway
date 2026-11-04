"""
Shared pytest configuration.

Sets dummy API keys and mocks the external 'agents' SDK before any src modules
are imported, so unit tests run without real credentials or network calls.
"""

import os
import sys
from unittest.mock import MagicMock

# Dummy credentials — must be set before src modules are imported
os.environ.setdefault("OPENAI_API_KEY", "sk-test-openai-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

# Replace the OpenAI 'agents' SDK with a MagicMock so base_openai.py can be
# imported without installing or initialising the real package.
if "agents" not in sys.modules:
    sys.modules["agents"] = MagicMock()

# Replace google.generativeai with a MagicMock so base_gemini.py can be
# imported without installing or initialising the real package.
if "google" not in sys.modules:
    sys.modules["google"] = MagicMock()
if "google.generativeai" not in sys.modules:
    sys.modules["google.generativeai"] = MagicMock()

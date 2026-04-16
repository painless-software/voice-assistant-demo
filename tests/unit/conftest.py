"""Unit test configuration.

Set PERSONA env var before any voice_assistant imports so that
config.py loads a valid persona at module level.
"""

import os

os.environ.setdefault("PERSONA", "velo_shop")

from __future__ import annotations

import os

from hypothesis import settings


settings.register_profile(
    "subschema-ci",
    derandomize=True,
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "subschema-ci"))

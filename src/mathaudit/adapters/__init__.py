# SPDX-License-Identifier: MIT

"""Built-in trace adapters."""

from .base import Adapter, ProblemContext, RunContext
from .canonical import CanonicalAdapter
from .icma import ICMAAdapter
from .mathgoal import MathGoalAdapter
from .mathrouter import MathRouterAdapter
from .otel import OTelAdapter

BUILTIN_ADAPTERS = [
    CanonicalAdapter(),
    ICMAAdapter(),
    MathRouterAdapter(),
    MathGoalAdapter(),
    OTelAdapter(),
]

__all__ = [
    "Adapter",
    "ProblemContext",
    "RunContext",
    "CanonicalAdapter",
    "ICMAAdapter",
    "MathRouterAdapter",
    "MathGoalAdapter",
    "OTelAdapter",
    "BUILTIN_ADAPTERS",
]

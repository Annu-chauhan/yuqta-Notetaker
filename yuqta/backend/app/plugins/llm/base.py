from collections.abc import Sequence
from typing import Protocol

from app.schemas.analysis import SignalExtraction
from app.schemas.transcript import SegmentIn


class LLMError(Exception):
    """Raised when a provider cannot extract signals."""


class LLMProvider(Protocol):
    """Language understanding capability: transcript -> structured business signals.

    `known_customers` lets the provider map mentions onto the business data. A real
    model will be prompted to return JSON matching SignalExtraction.
    """

    name: str

    def extract_signals(self, segments: Sequence[SegmentIn], known_customers: Sequence[str]) -> SignalExtraction: ...

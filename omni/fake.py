"""Explicit offline client; no credentials, networking, or call ledger."""
from .client import AssistantResult


class FakeOmniClient:
    def __init__(self, text="A chair is visible on the left of the camera view.", *, reason=None):
        self.text = text
        self.reason = reason

    def complete(self, prompt, jpeg, wav=None, *, timeout_s=None):
        if self.reason:
            return AssistantResult.unavailable(self.reason)
        return AssistantResult("success", self.text, "simulated")

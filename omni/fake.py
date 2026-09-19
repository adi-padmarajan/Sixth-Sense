"""Explicit offline client; no credentials, networking, or call ledger."""
from .client import AssistantResult


class FakeOmniClient:
    def __init__(self, text="A chair is visible on the left of the camera view.", *, reason=None):
        self.text = text
        self.reason = reason
        self.calls = 0
        self.last_call = None

    def complete(self, prompt, jpeg, wav=None, *, timeout_s=None):
        self.calls += 1
        self.last_call = dict(prompt=prompt, jpeg=jpeg, wav=wav, timeout_s=timeout_s)
        if self.reason:
            return AssistantResult.unavailable(self.reason)
        return AssistantResult("success", self.text, "simulated")

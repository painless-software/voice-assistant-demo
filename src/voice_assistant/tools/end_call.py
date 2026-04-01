"""End call tool -- signals that the agent wants to terminate the call."""

from __future__ import annotations


def end_call(reason: str, farewell_message: str = "") -> dict:
    """End the current call. Use when the customer indicates they want to hang up.

    Args:
        reason: Why the call is ending (e.g. "Customer said goodbye").
        farewell_message: Optional farewell to speak before disconnecting.
    """
    return {
        "status": "call_ended",
        "reason": reason,
        "farewell_message": farewell_message,
    }

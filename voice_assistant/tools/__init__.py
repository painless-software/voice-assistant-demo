"""Agent tools -- plain Python functions passed to ADK Agent(tools=[...]).

NOTE: The native audio live model (gemini-*-native-audio-*) does not
support function calling.  Tools registered here only work in text mode
(adk web / adk run).  Until native-audio tool support lands, keep the
live-facing tool list empty so Twilio calls don't crash with a 1008.
"""

ALL_TOOLS: list = []

"""Agent tools -- plain Python functions passed to ADK Agent(tools=[...]).

NOTE: The native audio live model (gemini-*-native-audio-*) does not
support function calling.  ``ALL_TOOLS`` is intentionally kept empty so
tools are disabled in all modes — avoiding 1008 session-close errors on
Twilio calls.  When native-audio tool support lands, or when text-only
runs are wired to use a separate tool list, re-enable by populating
``ALL_TOOLS`` for those flows.
"""

ALL_TOOLS: list = []

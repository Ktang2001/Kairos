"""Limits for test messages, shared so the client's message box can stop
at the same length the server accepts.
"""

#: Long enough for a display name or hostname.
MAX_SENDER_LENGTH = 100

#: Long enough for a chat message, short enough that one request cannot bloat
#: the database or flood the server window's log.
MAX_CONTENT_LENGTH = 2000

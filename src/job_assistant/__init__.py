"""Personal job-finding assistant.

Collects job postings from configured sources, filters them by user
preferences, deduplicates, persists to SQLite, and delivers concise
job cards to Telegram with Save / Ignore / Open / Mark-Applied actions.
"""

__version__ = "1.0.0"

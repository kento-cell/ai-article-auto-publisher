"""AI Morning Catchup — pull-based AI news digest for Slack.

Triggered manually via Slack `catchup` command (or CLI). Pulls from
official RSS / Hacker News / Reddit / arXiv, dedupes against SQLite,
summarises with local Gemma3, and posts a single digest message.

Cost: zero — no paid APIs, no scheduler.
"""

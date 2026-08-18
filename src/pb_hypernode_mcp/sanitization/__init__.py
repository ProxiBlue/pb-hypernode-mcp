"""Config-driven Magento PII sanitization + gateway-sandbox command generation.

This package only *generates* the ordered list of shell command strings a
later task (010) runs via `brancher_exec` against a Brancher node. It never
opens a database connection or SSH session itself.
"""

from __future__ import annotations

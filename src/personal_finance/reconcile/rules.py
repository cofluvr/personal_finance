"""The effective matching configuration. See decisions.md D-033.

One configuration applies to a whole account at a time. There is no per-import
setting, because different rules on different imports would break order
independence. Tests pass their own MatchingRules, and nothing stores them as
production configuration: the account marker only records what was used.
"""

import hashlib
import json
from dataclasses import asdict, dataclass

# Bump whenever matching behaviour changes in a way the settings below do not show.
RULES_VERSION = 1


@dataclass(frozen=True)
class MatchingRules:
    date_window_days: int = 3
    max_group_span_days: int = 14
    # A percentage, so that comparisons stay in integers.
    similarity_threshold_percent: int = 75
    min_single_token_length: int = 5
    min_shared_prefix_length: int = 4
    # Stripped only as a leading run, never from inside a description.
    channel_tokens: frozenset[str] = frozenset(
        {"pos", "debit", "checkcard", "ach", "purchase", "recurring"}
    )
    # Stripped only when followed by "*".
    star_prefixes: frozenset[str] = frozenset({"sq", "tst", "pp", "paypal"})
    # Words that say how money moved, not who received it.
    generic_tokens: frozenset[str] = frozenset(
        {
            "ach", "atm", "bill", "check", "credit", "debit", "deposit", "fee", "online",
            "payment", "pos", "purchase", "transfer", "withdrawal",
        }
    )

    def fingerprint(self) -> str:
        """Identify this configuration, including RULES_VERSION and any override."""
        settings = {
            key: sorted(value) if isinstance(value, frozenset) else value
            for key, value in asdict(self).items()
        }
        text = json.dumps({"version": RULES_VERSION, "settings": settings}, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


DEFAULT_RULES = MatchingRules()

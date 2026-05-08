"""
title: PII Redactor
description: Detects and redacts personally identifiable information in user messages
             before they reach the LLM provider. Covered entity types (each toggleable):
             email addresses, Canadian phone numbers (NANP), credit card numbers
             (Luhn-validated), IBANs (modulo-97 validated), Canadian SIN / Business
             Numbers (Luhn-validated), and Canadian postal codes.
             Sends a non-blocking warning in the chat when redaction occurs.
author: openweb-ui-local
version: 0.2.0
"""

import re
from typing import Callable, Optional

from pydantic import BaseModel, Field


# ── Checksum validators ────────────────────────────────────────────────────────

def _luhn_valid(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    digits.reverse()
    total = sum(
        d if i % 2 == 0 else (d * 2 - 9 if d * 2 > 9 else d * 2)
        for i, d in enumerate(digits)
    )
    return total % 10 == 0


def _iban_valid(raw: str) -> bool:
    iban = re.sub(r"\s", "", raw).upper()
    if len(iban) < 15 or len(iban) > 34:
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


# ── Regex patterns ─────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")

_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:"
    r"(?:\+1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}"  # NANP: (416) 555-1234 / +1 416 555 1234
    r"|\+1\d{10}"                                              # NANP compact: +14165551234
    r")"
    r"(?!\d)"
)

# Raw candidate: 13–19 digit sequences with optional separators; Luhn-validated below
_CC_CANDIDATE_RE = re.compile(r"\b(?:\d[ \-]?){12,18}\d\b")

# IBAN: 2-letter country code + 2 check digits + 11–30 alphanumeric; modulo-97 validated below
_IBAN_CANDIDATE_RE = re.compile(
    r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}[A-Z0-9]{0,3}\b"
)

# Canadian SIN / Business Number: 9 digits with optional dashes (NNN-NNN-NNN) or compact;
# Luhn-validated below to reduce false positives. SINs starting with 0 are invalid.
_SIN_CANDIDATE_RE = re.compile(r"\b[1-9]\d{2}[\s\-]?\d{3}[\s\-]?\d{3}\b")

# Canadian postal code: letter-digit-letter [space] digit-letter-digit
# First letter restricted to valid FSA characters (no D, F, I, O, Q, U)
_POSTAL_RE = re.compile(
    r"\b[ABCEGHJKLMNPRSTVXY]\d[ABCEGHJKLMNPRSTVWXYZ][\s\-]?\d[ABCEGHJKLMNPRSTVWXYZ]\d\b",
    re.IGNORECASE,
)


# ── Per-type redaction helpers ─────────────────────────────────────────────────

def _redact_cc(text: str) -> tuple[str, int]:
    count = 0

    def replace(m: re.Match) -> str:
        nonlocal count
        digits_only = re.sub(r"[ \-]", "", m.group(0))
        if 13 <= len(digits_only) <= 19 and _luhn_valid(digits_only):
            count += 1
            return "[REDACTED:CARD]"
        return m.group(0)

    return _CC_CANDIDATE_RE.sub(replace, text), count


def _redact_iban(text: str) -> tuple[str, int]:
    count = 0

    def replace(m: re.Match) -> str:
        nonlocal count
        if _iban_valid(m.group(0)):
            count += 1
            return "[REDACTED:IBAN]"
        return m.group(0)

    return _IBAN_CANDIDATE_RE.sub(replace, text), count


def _redact_sin(text: str) -> tuple[str, int]:
    count = 0

    def replace(m: re.Match) -> str:
        nonlocal count
        digits_only = re.sub(r"[\s\-]", "", m.group(0))
        if len(digits_only) == 9 and _luhn_valid(digits_only):
            count += 1
            return "[REDACTED:SIN]"
        return m.group(0)

    return _SIN_CANDIDATE_RE.sub(replace, text), count


def _redact_all(text: str, valves: "Filter.Valves") -> tuple[str, list[str]]:
    found: list[str] = []

    if valves.redact_email:
        new, n = _EMAIL_RE.subn("[REDACTED:EMAIL]", text)
        if n:
            text = new
            found.append("email address")

    if valves.redact_phone:
        new, n = _PHONE_RE.subn("[REDACTED:PHONE]", text)
        if n:
            text = new
            found.append("phone number")

    if valves.redact_credit_card:
        new, n = _redact_cc(text)
        if n:
            text = new
            found.append("credit card number")

    if valves.redact_iban:
        new, n = _redact_iban(text)
        if n:
            text = new
            found.append("IBAN")

    if valves.redact_sin:
        new, n = _redact_sin(text)
        if n:
            text = new
            found.append("SIN / Business Number")

    if valves.redact_postal_code:
        new, n = _POSTAL_RE.subn("[REDACTED:POSTAL]", text)
        if n:
            text = new
            found.append("postal code")

    return text, found


def _process_message(msg: dict, valves: "Filter.Valves") -> tuple[dict, list[str]]:
    content = msg.get("content", "")
    all_found: list[str] = []

    if isinstance(content, str):
        cleaned, found = _redact_all(content, valves)
        if found:
            return {**msg, "content": cleaned}, found
        return msg, []

    if isinstance(content, list):
        new_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                cleaned, found = _redact_all(part.get("text", ""), valves)
                all_found.extend(found)
                new_parts.append({**part, "text": cleaned})
            else:
                new_parts.append(part)
        if all_found:
            return {**msg, "content": new_parts}, all_found
        return msg, []

    return msg, []


# ── Filter ─────────────────────────────────────────────────────────────────────

class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=20, description="Execution order (lower runs first)")
        enabled: bool = Field(default=True)
        redact_email: bool = Field(default=True)
        redact_phone: bool = Field(default=True)
        redact_credit_card: bool = Field(default=True)
        redact_iban: bool = Field(
            default=False,
            description="IBAN (modulo-97 validated) — uncommon in Canada, off by default",
        )
        redact_sin: bool = Field(
            default=True,
            description="Canadian SIN / Business Number — 9-digit, Luhn-validated",
        )
        redact_postal_code: bool = Field(
            default=False,
            description="Canadian postal codes (A1A 1A1 format) — off by default to reduce false positives",
        )
        scan_all_messages: bool = Field(
            default=False,
            description=(
                "If True, scan the full message history. "
                "If False (default), only scan the last user message."
            ),
        )

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable] = None,
    ) -> dict:
        if not self.valves.enabled:
            return body

        messages: list[dict] = body.get("messages", [])
        if not messages:
            return body

        user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        if not user_indices:
            return body

        indices_to_scan = user_indices if self.valves.scan_all_messages else user_indices[-1:]
        all_found: list[str] = []
        modified = False

        for i in indices_to_scan:
            new_msg, found = _process_message(messages[i], self.valves)
            if found:
                messages[i] = new_msg
                all_found.extend(found)
                modified = True

        if modified:
            body["messages"] = messages
            if __event_emitter__:
                unique = list(dict.fromkeys(all_found))
                await __event_emitter__({
                    "type": "status",
                    "data": {
                        "description": (
                            f"⚠️ Sensitive data redacted before sending: {', '.join(unique)}."
                        ),
                        "done": True,
                    },
                })

        return body

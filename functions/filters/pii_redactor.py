"""
title: PII Redactor
description: Detects and redacts personally identifiable information in user messages
             before they reach the LLM provider. Covered entity types (each toggleable):
             email addresses, phone numbers, credit card numbers (Luhn-validated),
             IBANs (modulo-97 validated), French NIR (numéro de sécurité sociale),
             and French SIRET (Luhn-validated).
             Sends a non-blocking warning in the chat when redaction occurs.
author: openweb-ui-local
version: 0.1.0
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
    r"\+33\s?[1-9](?:[\s.\-]?\d{2}){4}"       # French international (+33)
    r"|0[1-9](?:[\s.\-]?\d{2}){4}"             # French local (0X XX XX XX XX)
    r"|\+\d{1,3}[\s.\-]?\(?\d{1,4}\)?[\s.\-]?\d{4,10}"  # Generic international
    r")"
    r"(?!\d)"
)

# Raw candidate: 13–19 digit sequences with optional separators; Luhn-validated below
_CC_CANDIDATE_RE = re.compile(r"\b(?:\d[ \-]?){12,18}\d\b")

# IBAN: 2-letter country code + 2 check digits + 11–30 alphanumeric; modulo-97 validated below
_IBAN_CANDIDATE_RE = re.compile(
    r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}[A-Z0-9]{0,3}\b"
)

# French NIR: 15 digits — sex digit (1/2) + YY + valid month + rest
_NIR_RE = re.compile(
    r"\b[12]\d{2}(?:0[1-9]|1[0-2]|20)\d{10}\b"
)

# SIRET: exactly 14 consecutive digits; Luhn-validated below
_SIRET_CANDIDATE_RE = re.compile(r"\b\d{14}\b")


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


def _redact_siret(text: str) -> tuple[str, int]:
    count = 0

    def replace(m: re.Match) -> str:
        nonlocal count
        if _luhn_valid(m.group(0)):
            count += 1
            return "[REDACTED:SIRET]"
        return m.group(0)

    return _SIRET_CANDIDATE_RE.sub(replace, text), count


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

    if valves.redact_nir:
        new, n = _NIR_RE.subn("[REDACTED:NIR]", text)
        if n:
            text = new
            found.append("NIR (numéro de sécurité sociale)")

    if valves.redact_siret:
        new, n = _redact_siret(text)
        if n:
            text = new
            found.append("SIRET")

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
        redact_iban: bool = Field(default=True)
        redact_nir: bool = Field(
            default=True,
            description="French numéro de sécurité sociale (15-digit NIR)",
        )
        redact_siret: bool = Field(
            default=True,
            description="French SIRET — 14-digit company identifier, Luhn-validated",
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

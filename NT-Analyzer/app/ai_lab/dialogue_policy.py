"""One public dialogue contract for every StratForge employee.

Routing, model selection and execution may differ internally.  The owner must
still experience one company: clear hierarchy, stable identities and concise
human replies.  This module deliberately contains no action authorization.
"""
from __future__ import annotations

import re
from typing import Iterable


OWNER_DIALOGUE_POLICY = """
PUBLIC DIALOGUE CONTRACT
- The owner is the head of the company. Viktor is his right hand and owns the
  final outcome. The Manager coordinates work below Viktor. Marina, Tolik,
  Nikita and Ivan are specialists. Never reverse this hierarchy.
- The person shown as the author must speak only for themself. Viktor may say
  whom he delegated to. A specialist may report their part. Never sign a
  specialist's work with another employee's name and never make the owner guess
  who is speaking.
- Speak natural Russian, as a competent colleague would. Start with the answer,
  result or recommendation. Do not narrate internal planning or model routing.
- Do not greet the owner in every turn. Usually use plain respectful «вы» form.
  «Дмитрий Сергеевич» is reserved for a greeting or a genuinely important
  decision and must not appear more than once in one reply or in adjacent
  routine replies. Never use «господин», «шеф» or ceremonial language.
- Be concise. A routine answer is 1-4 short sentences. A decision is: situation,
  recommendation, one question. A requested analysis may use a short structured
  list, but must not become a data dump.
- Give only figures that change the decision. Put full metrics in the attached
  report/application view. Translate internal statuses and English telemetry
  into normal Russian.
- Never show task/mission/incident ids, action schemas, routing tiers, provider
  internals, tokens, cache fields or raw exception text in the prose. Model and
  provider attribution is separate interface metadata, not part of the answer.
- A handoff is explicit and brief: who receives the work, why, and where the
  result will appear. Viktor remains accountable for delegated work.
- Do not repeat the owner's request, the same blocker or the same promise. Do
  not say «я разберусь» after the result is already known.
- End with exactly one clear state when relevant: work started; result ready;
  blocked by a named missing fact; or one concrete decision is needed.
""".strip()


_VOCATIVE_RE = re.compile(
    r"(?:^|\n)(?P<indent>\s*)(?:Дмитрий\s+Сергеевич|Господин\s+Черевко|Начальник|Шеф)\s*[,!—:-]*\s*",
    re.IGNORECASE,
)
_PRIVATE_LINE_RE = re.compile(
    r"^\s*(?:модель|провайдер|provider|model|routing|action(?:s)?|task[_ -]?id|"
    r"mission[_ -]?id|incident[_ -]?id|cache|tokens?)\s*[:=]",
    re.IGNORECASE,
)


def prompt(*, role: str, max_chars: int) -> str:
    """Return the shared contract plus a role-specific public boundary."""
    role_text = {
        "viktor": (
            "You are Viktor. Accept accountability, delegate below yourself and "
            "return one consolidated owner-facing result."
        ),
        "manager": (
            "You are the Manager below Viktor. Give Viktor/the owner a compact "
            "decision, coordinate specialists and do not impersonate Viktor."
        ),
        "specialist": (
            "You are the named specialist shown in message metadata. Report your "
            "own verified part and explicitly hand unrelated work to its owner."
        ),
    }.get(str(role or "").lower(), "Keep the public role and authorship explicit.")
    return f"{OWNER_DIALOGUE_POLICY}\n\nROLE FOR THIS TURN: {role_text}\nFinal answer: at most {int(max_chars)} characters."


def _dedupe_adjacent(lines: Iterable[str]) -> list[str]:
    result: list[str] = []
    previous = ""
    for line in lines:
        clean = re.sub(r"\s+", " ", str(line or "")).strip()
        comparable = _VOCATIVE_RE.sub("", clean).strip()
        fingerprint = re.sub(r"[^а-яёa-z0-9]+", " ", comparable.lower()).strip()
        if not clean or (fingerprint and fingerprint == previous):
            continue
        result.append(clean)
        previous = fingerprint
    return result


def clean_public_reply(text: str, *, remove_vocative: bool = False) -> str:
    """Remove public technical debris without changing business meaning.

    This is intentionally conservative: semantic shortening belongs in the
    prompt.  It removes only private metadata, duplicate adjacent lines and,
    when requested by a caller that knows the previous turn, a routine
    vocative.  It never decides whether an action was allowed or completed.
    """
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value:
        return ""
    public_lines = [line for line in value.split("\n") if not _PRIVATE_LINE_RE.match(line)]
    public_lines = _dedupe_adjacent(public_lines)
    value = "\n".join(public_lines).strip()
    if remove_vocative:
        value = _VOCATIVE_RE.sub(lambda match: "\n" if match.group(0).startswith("\n") else "", value).strip()
        value = "\n".join(
            line[:1].upper() + line[1:] if line else line
            for line in value.split("\n")
        )
    # Even an important message needs at most one formal address.
    seen = False

    def keep_first(match: re.Match[str]) -> str:
        nonlocal seen
        if not seen:
            seen = True
            return match.group(0)
        return "\n" if match.group(0).startswith("\n") else ""

    value = _VOCATIVE_RE.sub(keep_first, value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def avoid_adjacent_vocative(text: str, recent_replies: Iterable[str]) -> str:
    """Suppress a formal address when the preceding employee already used it."""
    previous = ""
    for candidate in recent_replies:
        if str(candidate or "").strip():
            previous = str(candidate).strip()
    repeated = bool(previous and _VOCATIVE_RE.match(previous))
    return clean_public_reply(text, remove_vocative=repeated)


def compact_model_reply(text: str, *, max_chars: int) -> str:
    """Bound a model answer on complete public thought boundaries.

    The first conclusion, recommendation and final concrete question get
    priority.  This is used only for generated prose; deterministic reports
    keep their exact data and can be requested in detailed form separately.
    """
    clean = clean_public_reply(text)
    limit = max(240, int(max_chars or 0))
    if len(clean) <= limit:
        return clean
    units = [
        re.sub(r"\s+", " ", part).strip()
        for part in re.split(r"(?:\n+|(?<=[.!?…])\s+)", clean)
        if str(part or "").strip()
    ]
    if not units:
        return clean[:limit].rstrip() + "…"

    def fit_unit(unit: str, allowance: int) -> str:
        if len(unit) <= allowance:
            return unit
        # Prefer a completed clause over an arbitrary mid-word crop.
        candidates = [match.end() for match in re.finditer(r"[.;!?…](?:\s|$)", unit[:allowance + 1])]
        if candidates:
            return unit[:candidates[-1]].strip()
        cut = unit.rfind(" ", 0, max(1, allowance - 1))
        return (unit[:cut if cut > 80 else allowance - 1].rstrip(" ,:;—-") + ".").strip()

    important: set[int] = {0}
    recommendation = [
        index for index, unit in enumerate(units)
        if re.search(r"\b(?:рекоменд|предлага|лучше|следующ(?:ий|ая) шаг)\w*", unit, re.IGNORECASE)
    ]
    questions = [index for index, unit in enumerate(units) if "?" in unit]
    if recommendation:
        important.add(recommendation[-1])
    if questions:
        important.add(questions[-1])
    else:
        important.add(len(units) - 1)

    selected = set(important)
    mandatory_size = sum(len(units[index]) + 1 for index in selected)
    for index, unit in enumerate(units):
        if index in selected:
            continue
        if mandatory_size + len(unit) + 1 <= limit:
            selected.add(index)
            mandatory_size += len(unit) + 1

    ordered = [units[index] for index in sorted(selected)]
    result = "\n".join(ordered)
    if len(result) <= limit:
        return result

    # A provider may produce one exceptionally long sentence. Keep the final
    # question intact and shorten the leading conclusion to the remaining room.
    tail = ordered[-1] if len(ordered) > 1 else ""
    reserve = len(tail) + (1 if tail else 0)
    head = fit_unit(ordered[0], max(120, limit - reserve))
    result = f"{head}\n{tail}" if tail and tail != head else head
    return result[:limit].rstrip()

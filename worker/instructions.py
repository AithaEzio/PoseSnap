"""Shared clause boundaries and exclusions for all checked movement parsers."""
import re

NEGATION = re.compile(r"\b(?:no|not|never|without|except|cannot)\b|\b(?:don|doesn|didn|can|won)['’]t\b", re.I)


def negated(text):
    return bool(NEGATION.search(text))


def clauses(text):
    # An exclusion also governs its coordinated continuation: "don't raise the
    # arm and bend the knee" cannot accidentally become a positive knee goal.
    parts = re.split(r"([.;,]|\b(?:and|but|while)\b|(?=\b(?:without|do not|don['’]t)\b))", text.lower())
    inherited = False
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part in ('.', ';', ',', 'but', 'while'):
            inherited = False
            continue
        if part == 'and':
            continue
        value = 'not '+part if inherited and not negated(part) else part
        inherited = negated(value)
        yield value


def positive_text(text):
    return '; '.join(c for c in clauses(text) if not negated(c))

"""Prompt profiles affect unspecified body language, never facial channels."""
import re

PROFILES = dict(natural='', expressive='Expressive body language.', dramatic='Dramatic body language.', happy='Happy body language.', sad='Sad body language.', tired='Tired body language.')


def direction(text, style):
    if style not in PROFILES: raise ValueError('Unknown pose character profile.')
    # An explicit mood in the direction takes precedence over the optional preset.
    # A negated mood is also authoritative: never append "Tired" after
    # "walk, but do not look tired", and never invent its opposite.
    explicit = re.search(r'\b(happy|sad|tired|angry|scared|relaxed|confident|expressive|dramatic)\b', text, re.I)
    suffix = PROFILES[style] if not explicit else ''
    text = text.strip().rstrip('.')
    if not re.match(r'^(?:a|an|the)\s+(?:person|woman|man|character)\b', text, re.I):
        text = 'A person: '+text
    return text+'.'+(' '+suffix if suffix else '')

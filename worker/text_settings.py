"""Body-only Text to Pose preferences; obsolete model choices are not retained."""
from storage import read_json

DEFAULTS = dict(textHandShapes=False)


def settings(root):
    saved = read_json(root/'data/settings.json', {})
    return dict(textHandShapes=saved.get('textHandShapes', False) is True)


def validate(value):
    if type(value.get('textHandShapes')) is not bool:
        raise ValueError('Invalid approximate hand shapes preference')

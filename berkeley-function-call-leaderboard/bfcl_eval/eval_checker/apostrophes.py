"""BFCL-Modified, change 3: a typographic apostrophe is read as the plain one (see MODIFICATIONS.md).

A model sometimes writes the typographic apostrophe where the text it works from, and the ground truth, has
the plain one, and BFCL's own question data uses both forms. The checkers read the two as the same
character wherever they compare text. This module is the one place that says which characters those are.
"""

import copy
from typing import Any

# The right single quotation mark (the typographic apostrophe), the left single quotation mark and the
# modifier letter apostrophe.
TYPOGRAPHIC_APOSTROPHES = "\u2019\u2018\u02bc"

_TO_PLAIN = str.maketrans(dict.fromkeys(TYPOGRAPHIC_APOSTROPHES, "'"))


def straight_apostrophes(text: str) -> str:
    """`text` with every typographic apostrophe replaced by the plain one."""
    return text.translate(_TO_PLAIN)


def with_straight_apostrophes(value: Any) -> Any:
    """A copy of `value` in which every string has its typographic apostrophes replaced by the plain one.

    Strings are read wherever they sit: in lists, tuples, sets and dicts (keys too) and in the attributes of
    objects, such as the state a multi-turn backend holds, which can refer back to itself. `value` itself is
    not modified.
    """
    return _straighten(value, {})


def _straighten(value: Any, made: dict) -> Any:
    if isinstance(value, str):
        return straight_apostrophes(value)
    if id(value) in made:
        return made[id(value)]
    if isinstance(value, dict):
        straightened_dict: dict = {}
        made[id(value)] = straightened_dict
        for key, item in value.items():
            straightened_dict[_straighten(key, made)] = _straighten(item, made)
        return straightened_dict
    if isinstance(value, list):
        straightened_list: list = []
        made[id(value)] = straightened_list
        straightened_list.extend(_straighten(item, made) for item in value)
        return straightened_list
    if type(value) in (tuple, set, frozenset):
        return type(value)(_straighten(item, made) for item in value)
    if hasattr(value, "__dict__") and not isinstance(value, type):
        try:
            clone = copy.copy(value)
        except (TypeError, copy.Error):
            return value
        if clone is value:  # an object that copies to itself (an enum member) is left as it is
            return value
        made[id(value)] = clone
        for name, attribute in vars(value).items():
            setattr(clone, name, _straighten(attribute, made))
        return clone
    return value

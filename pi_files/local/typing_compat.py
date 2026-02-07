"""Minimal typing fallbacks for CircuitPython/MicroPython."""

try:
    from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union
except Exception:
    class _TypingStub:
        def __getitem__(self, _item):
            return self

        def __call__(self, *args, **kwargs):
            return self

    _stub = _TypingStub()

    Any = _stub
    Callable = _stub
    Dict = _stub
    Iterable = _stub
    List = _stub
    Optional = _stub
    Sequence = _stub
    Tuple = _stub
    Union = _stub

from dataclasses import dataclass
from json import loads
from os import linesep
from pathlib import Path
from typing import AbstractSet, Iterator, Mapping, Optional, Sequence, Union

from std2.pickle import decode

from .types import ParsedSnippet, MetaSnippets


@dataclass
class _Unit:
    prefix: Union[str, Sequence[str]]
    body: Union[str, Sequence[str]]
    description: Optional[str] = None


_FMT = Mapping[str, _Unit]


def _prefix(prefix: Union[str, Sequence[str]]) -> AbstractSet[str]:
    if isinstance(prefix, str):
        return {prefix}
    elif isinstance(prefix, Sequence):
        return {*prefix}
    else:
        raise ValueError(prefix)


def _body(body: Union[str, Sequence[str]]) -> str:
    if isinstance(body, str):
        return body
    elif isinstance(body, Sequence):
        return linesep.join(body)
    else:
        raise ValueError(body)


def parse(path: Path) -> MetaSnippets:
    text = path.read_text("UTF-8") if path.exists() else ""
    json = loads(text)
    fmt: _FMT = decode(_FMT, json)

    def cont() -> Iterator[ParsedSnippet]:
        for label, values in fmt.items():
            snippet = ParsedSnippet(
                content=_body(values.body),
                doc=values.description,
                label=label,
                matches=_prefix(values.prefix),
                opts=set(),
            )
            yield snippet

    meta = MetaSnippets(snippets=tuple(cont()), extends=frozenset())
    return meta

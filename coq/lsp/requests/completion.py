from pathlib import Path
from typing import Iterator, Sequence
from uuid import uuid4

from pynvim.api.nvim import Nvim

from ...registry import atomic
from ...shared.types import UTF16, Completion, Context
from ..parse import parse
from .request import blocking_request

_LUA = (Path(__file__).resolve().parent / "completion.lua").read_text("UTF-8")

atomic.exec_lua(_LUA, ())


def request(
    nvim: Nvim,
    short_name: str,
    tie_breaker: int,
    context: Context,
) -> Iterator[Sequence[Completion]]:
    session = uuid4()
    row, c = context.position
    col = len(context.line_before[:c].encode(UTF16)) // 2

    go = True
    while go:
        reply = blocking_request(nvim, "COQlsp_comp", str(session), (row, col))
        go, comps = parse(short_name, tie_breaker=tie_breaker, reply=reply)
        yield comps

from asyncio import Task, wait
from dataclasses import asdict, dataclass
from os import linesep
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence, Tuple, cast
from uuid import uuid4

from pynvim import Nvim
from pynvim.api import Buffer, Window
from pynvim_pp.api import (
    buf_get_lines,
    buf_get_option,
    create_buf,
    list_wins,
    win_close,
    win_get_buf,
    win_get_var,
    win_set_option,
    win_set_var,
)
from pynvim_pp.lib import async_call, go
from pynvim_pp.preview import buf_set_preview, set_preview
from std2.ordinal import clamp
from std2.pickle import DecodeError, new_decoder
from std2.string import removeprefix

from ...lsp.requests.preview import request
from ...lsp.types import CompletionItem
from ...registry import autocmd, rpc
from ...shared.parse import display_width
from ...shared.settings import PreviewDisplay
from ...shared.timeit import timeit
from ...shared.trans import expand_tabs
from ...shared.types import UTF8, Context, Doc
from ..nvim.completions import VimCompletion
from ..rt_types import Stack
from ..state import State, state

_FLOAT_WIN_UUID = uuid4().hex


@dataclass(frozen=True)
class _Event:
    completed_item: VimCompletion
    row: int
    col: int
    height: int
    width: int
    size: int
    scrollbar: bool


@dataclass(frozen=True)
class _Pos:
    row: int
    col: int
    height: int
    width: int


def _ls(nvim: Nvim) -> Iterator[Window]:
    for win in list_wins(nvim):
        if win_get_var(nvim, win=win, key=_FLOAT_WIN_UUID):
            yield win


@rpc(blocking=True)
def _kill_win(nvim: Nvim, stack: Stack, reset: bool) -> None:
    if reset:
        state(pum_location=-1)

    for win in _ls(nvim):
        win_close(nvim, win=win)


autocmd("CompleteDone", "InsertLeave") << f"lua {_kill_win.name}(true)"


def _preprocess(context: Context, doc: Doc) -> Doc:
    sep = "```"
    if doc.syntax == "markdown":
        split = doc.text.splitlines()
        if (
            split
            and split[0].startswith(sep)
            and split[-1].startswith(sep)
            and not sum(line.startswith(sep) for line in split[1:-1])
        ):
            text = linesep.join(split[1:-1])
            ft = removeprefix(split[0], prefix=sep).strip()
            syntax = ft if ft.isalnum() else context.filetype
            return Doc(text=text, syntax=syntax)
        else:
            return doc
    else:
        return doc


def _clamp(margin: int, hi: int) -> Callable[[int], int]:
    return lambda i: clamp(1, i - margin, hi)


def _positions(
    display: PreviewDisplay,
    event: _Event,
    lines: Sequence[str],
    state: State,
) -> Iterator[Tuple[int, _Pos]]:
    scr_width, src_height = state.screen
    top, btm, left, right = (
        event.row,
        event.row + event.height + 1,
        event.col,
        event.col + event.width + event.scrollbar,
    )
    limit_h, limit_w = (
        _clamp(display.margin, hi=len(lines)),
        _clamp(
            display.margin,
            hi=min(
                display.x_max_len,
                max(display_width(line, tabsize=2) for line in lines),
            ),
        ),
    )

    ns_width = limit_w(scr_width - left)
    n_height = limit_h(top - 1)

    ns_col = left - 1
    n = _Pos(
        row=top - 1 - n_height,
        col=ns_col,
        height=n_height,
        width=ns_width,
    )
    if n.row > 0:
        yield 1, n

    s = _Pos(
        row=btm,
        col=ns_col,
        height=limit_h(src_height - btm),
        width=ns_width,
    )
    yield 2, s

    we_height = limit_h(src_height - top)
    w_width = limit_w(left - 1)

    w = _Pos(
        row=top,
        col=left - w_width - 2,
        height=we_height,
        width=w_width,
    )
    yield 3, w

    e = _Pos(
        row=top,
        col=right + 2,
        height=we_height,
        width=limit_w(scr_width - right - 2),
    )
    yield 4, e


def _set_win(nvim: Nvim, buf: Buffer, pos: _Pos) -> None:
    opts = {
        "relative": "editor",
        "anchor": "NW",
        "style": "minimal",
        "width": pos.width,
        "height": pos.height,
        "row": pos.row,
        "col": pos.col,
    }
    win: Window = nvim.api.open_win(buf, False, opts)
    win_set_option(nvim, win=win, key="wrap", val=True)
    win_set_var(nvim, win=win, key=_FLOAT_WIN_UUID, val=True)


@rpc(blocking=True, schedule=True)
def _go_show(
    nvim: Nvim,
    stack: Stack,
    syntax: str,
    preview: Sequence[str],
    _pos: Mapping[str, int],
) -> None:
    pos = _Pos(**_pos)
    buf = create_buf(
        nvim, listed=False, scratch=True, wipe=True, nofile=True, noswap=True
    )
    buf_set_preview(nvim, buf=buf, syntax=syntax, preview=preview)
    _set_win(nvim, buf=buf, pos=pos)


def _show_preview(nvim: Nvim, stack: Stack, event: _Event, doc: Doc, s: State) -> None:
    new_doc = _preprocess(s.context, doc=doc)
    text = expand_tabs(s.context, text=new_doc.text)
    lines = text.splitlines()
    (pum_location, pos), *_ = sorted(
        _positions(stack.settings.display.preview, event=event, lines=lines, state=s),
        key=lambda p: (p[1].height * p[1].width, p[0] == s.pum_location, -p[0]),
        reverse=True,
    )
    state(pum_location=pum_location)
    nvim.api.exec_lua(f"{_go_show.name}(...)", (new_doc.syntax, lines, asdict(pos)))


_TASK: Optional[Task] = None


def _resolve_comp(
    nvim: Nvim,
    stack: Stack,
    event: _Event,
    item: CompletionItem,
    maybe_doc: Optional[Doc],
    state: State,
) -> None:
    global _TASK
    timeout = stack.settings.display.preview.lsp_timeout if maybe_doc else None

    async def cont() -> None:
        done, _ = await wait((request(nvim, item=item),), timeout=timeout)
        doc = await done.pop() if done else maybe_doc
        if doc:
            await async_call(
                nvim,
                _show_preview,
                nvim,
                stack=stack,
                event=event,
                doc=doc,
                s=state,
            )

    _TASK = cast(Task, go(cont()))


_DECODER = new_decoder(_Event)


@rpc(blocking=True, schedule=True)
def _cmp_changed(nvim: Nvim, stack: Stack, event: Mapping[str, Any] = {}) -> None:
    if _TASK:
        _TASK.cancel()

    _kill_win(nvim, stack=stack, reset=False)
    with timeit("PREVIEW"):
        try:
            ev: _Event = _DECODER(event)
        except DecodeError:
            pass
        else:
            data = ev.completed_item.user_data
            if data:
                s = state()
                if data.doc and data.doc.text:
                    _show_preview(nvim, stack=stack, event=ev, doc=data.doc, s=s)
                elif data.extern:
                    _resolve_comp(
                        nvim,
                        stack=stack,
                        event=ev,
                        item=data.extern,
                        maybe_doc=data.doc,
                        state=s,
                    )


autocmd("CompleteChanged") << f"lua {_cmp_changed.name}(vim.v.event)"


@rpc(blocking=True, schedule=True)
def _bigger_preview(nvim: Nvim, stack: Stack, args: Tuple[str, Sequence[str]]) -> None:
    syntax, lines = args
    nvim.command("stopinsert")
    set_preview(nvim, syntax=syntax, preview=lines)


@rpc(blocking=True)
def preview_preview(nvim: Nvim, stack: Stack, *_: str) -> str:
    win = next(_ls(nvim), None)
    if win:
        buf = win_get_buf(nvim, win=win)
        syntax = buf_get_option(nvim, buf=buf, key="syntax")
        lines = buf_get_lines(nvim, buf=buf, lo=0, hi=-1)
        nvim.exec_lua(f"{_bigger_preview.name}(...)", (syntax, lines))

    escaped: str = nvim.api.replace_termcodes("<c-e>", True, False, True)
    return escaped


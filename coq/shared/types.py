from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path, PurePath
from typing import Any, Literal, Mapping, Optional, Sequence, Tuple, Union
from uuid import UUID, uuid4

UTF8: Literal["UTF-8"] = "UTF-8"
UTF16: Literal["UTF-16-LE"] = "UTF-16-LE"

# In nvim, the col is a ut8 byte offset
NvimPos = Tuple[int, int]
# Depends on `OffsetEncoding`
WTF8Pos = Tuple[int, int]

BYTE_TRANS = {
    UTF8: 1,
    UTF16: 2,
}


@dataclass(frozen=True)
class Context:
    """
    |...                            line                            ...|
    |...        line_before           🐭          line_after        ...|
    |...   <syms_before><words_before>🐭<words_after><syms_after>   ...|
    """

    manual: bool

    # CHANGE ID <-> Triggered by NVIM, ie lines changes
    change_id: UUID
    # COMMIT ID <-> Triggered by COQ
    commit_id: UUID

    cwd: PurePath
    buf_id: int
    filetype: str
    filename: str
    line_count: int
    linefeed: Literal["\r\n", "\n", "\r"]
    tabstop: int
    expandtab: bool
    comment: Tuple[str, str]

    position: NvimPos
    scr_col: int

    line: str
    line_before: str
    line_after: str

    lines: Sequence[str]
    lines_before: Sequence[str]
    lines_after: Sequence[str]

    words: str
    words_before: str
    words_after: str

    syms: str
    syms_before: str
    syms_after: str

    ws_before: str
    ws_after: str


@dataclass(frozen=True)
class Edit:
    new_text: str


@dataclass(frozen=True)
class ContextualEdit(Edit):
    """
    <new_prefix>🐭<new_suffix>
    """

    old_prefix: str
    new_prefix: str
    old_suffix: str = ""


@dataclass(frozen=True)
class RangeEdit(Edit):
    """
    End exclusve, like LSP
    """

    fallback: str
    begin: WTF8Pos
    end: WTF8Pos
    encoding: Literal["UTF-8", "UTF-16-LE"]


class SnippetGrammar(Enum):
    lsp = auto()
    snu = auto()


@dataclass(frozen=True)
class SnippetEdit(Edit):
    grammar: SnippetGrammar


@dataclass(frozen=True)
class SnippetRangeEdit(SnippetEdit, RangeEdit):
    ...


@dataclass(frozen=True)
class Mark:
    idx: int
    begin: NvimPos
    end: NvimPos
    text: str


@dataclass(frozen=True)
class Doc:
    text: str
    syntax: str


@dataclass(frozen=True)
class ExternLSP:
    item: Mapping
    command: Optional[Any]


@dataclass(frozen=True)
class ExternLUA(ExternLSP):
    ...


@dataclass(frozen=True)
class ExternPath:
    path: Path


@dataclass(frozen=True)
class Completion:
    source: str
    weight_adjust: float
    label: str
    sort_by: str
    primary_edit: Edit
    icon_match: Optional[str]

    uid: UUID = field(default_factory=uuid4)
    secondary_edits: Sequence[RangeEdit] = ()
    preselect: bool = False
    kind: str = ""
    doc: Optional[Doc] = None
    extern: Union[ExternLSP, ExternLUA, ExternPath, None] = None

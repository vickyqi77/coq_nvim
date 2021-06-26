from contextlib import suppress
from pathlib import Path
from shutil import which
from subprocess import check_output
from time import sleep
from typing import Iterator, Sequence, Tuple

from pynvim.api.nvim import Nvim, NvimError
from pynvim_pp.api import buf_filetype, buf_name, list_bufs
from pynvim_pp.lib import threadsafe_call
from pynvim_pp.logging import log

from ...shared.runtime import Supervisor
from ...shared.runtime import Worker as BaseWorker
from ...shared.settings import PollingClient
from ...shared.types import Completion, Context, Edit
from .parser import parse


def _ls(nvim: Nvim) -> Sequence[Tuple[Path, float, str]]:
    def cont() -> Sequence[Tuple[str, str]]:
        def c1() -> Iterator[Tuple[str, str]]:
            for buf in list_bufs(nvim, listed=True):
                with suppress(NvimError):
                    filename = buf_name(nvim, buf=buf)
                    filetype = buf_filetype(nvim, buf=buf)
                    yield filename, filetype

        return tuple(c1())

    def c2() -> Iterator[Tuple[Path, float, str]]:
        lsd = threadsafe_call(nvim, cont)
        for filename, filetype in lsd:
            path = Path(filename).resolve()
            with suppress(FileNotFoundError):
                stat = path.stat()
                yield path, stat.st_mtime, filetype

    return tuple(c2())


class Worker(BaseWorker[PollingClient, None]):
    def __init__(
        self, supervisor: Supervisor, options: PollingClient, misc: None
    ) -> None:
        super().__init__(supervisor, options=options, misc=misc)
        if which("etags"):
            supervisor.pool.submit(self._poll)

    def _poll(self) -> None:
        try:
            while True:
                lsd = _ls(self._supervisor.nvim)

                paths = tuple(str(path) for path, _, _ in lsd)
                raw = (
                    check_output(("etags", "-o", "-", *paths), text=True)
                    if paths
                    else ""
                )
                parsed = parse(raw, raise_err=False)
                sleep(self._options.polling_interval)
        except Exception as e:
            log.exception("%s", e)

    def work(self, context: Context) -> Iterator[Sequence[Completion]]:
        match = context.words or (context.syms if self._options.match_syms else "")

        path = Path(context.filename).resolve()
        if path.exists():

            def cont() -> Iterator[Completion]:
                # for section in :
                for tag in section.tags:
                    word = tag.name or tag.text
                    edit = Edit(new_text=word)
                    cmp = Completion(
                        source=self._options.short_name,
                        tie_breaker=self._options.tie_breaker,
                        primary_edit=edit,
                    )
                    yield cmp

            yield tuple(cont())

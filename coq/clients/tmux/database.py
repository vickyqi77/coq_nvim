from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from sqlite3 import Connection, OperationalError
from threading import Lock
from typing import Iterable, Iterator, Mapping, Sequence

from std2.sqllite3 import with_transaction

from ...consts import TMUX_DB
from ...shared.database import init_db
from ...shared.executor import Executor
from .sql import sql


def _init() -> Connection:
    conn = Connection(TMUX_DB, isolation_level=None)
    init_db(conn)
    conn.executescript(sql("create", "pragma"))
    conn.executescript(sql("create", "tables"))
    return conn


class Database:
    def __init__(self, pool: ThreadPoolExecutor) -> None:
        self._lock = Lock()
        self._ex = Executor(pool)
        self._conn: Connection = self._ex.submit(_init)

    def _interrupt(self) -> None:
        with self._lock:
            self._conn.interrupt()

    def periodical(self, panes: Mapping[str, Sequence[str]]) -> None:
        def m1(panes: Iterable[str]) -> Iterator[Mapping]:
            for pane_id in panes:
                yield {"pane_id": pane_id}

        def m2() -> Iterator[Mapping]:
            for pane_id, words in panes.items():
                for word in words:
                    yield {
                        "pane_id": pane_id,
                        "word": word,
                    }

        def cont() -> None:
            with self._lock, closing(self._conn.cursor()) as cursor:
                with with_transaction(cursor):
                    cursor.execute(sql("select", "panes"))
                    existing = {row["pane_id"] for row in cursor.fetchall()}
                    cursor.executemany(
                        sql("delete", "pane"), m1(existing - panes.keys())
                    )
                    cursor.executemany(sql("insert", "pane"), m1(panes.keys()))
                    cursor.executemany(sql("insert", "word"), m2())

        self._ex.submit(cont)

    def select(self, word: str, active_pane: str) -> Sequence[str]:
        def cont() -> Sequence[str]:
            try:
                with closing(self._conn.cursor()) as cursor:
                    cursor.execute(
                        sql("select", "words"),
                        {
                            "pane_id": active_pane,
                            "word": word,
                        },
                    )
                    return tuple(row["word"] for row in cursor.fetchall())
            except OperationalError:
                return ()

        self._interrupt()
        return self._ex.submit(cont)


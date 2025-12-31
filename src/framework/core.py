import asyncio
import signal
from contextlib import suppress
from dataclasses import dataclass
from types import FrameType
from typing import Any, Awaitable, Callable, Coroutine

from structlog.stdlib import BoundLogger

from framework.display import run as display_run
from framework.event import run as event_run
from framework.game import Application
from framework.game import run as game_run


@dataclass
class ShutdownHandler:
    exit_event: asyncio.Event
    logger: BoundLogger

    def __call__(
        self, signum: int | None = None, frame: FrameType | None = None
    ) -> None:
        self.logger.info("MAIN: Sending exit event to all tasks in pool")

        self.exit_event.set()

        for task in asyncio.all_tasks():
            task.cancel()


@dataclass
class DoneHandler:
    name: str
    shutdown_handler: ShutdownHandler
    logger: BoundLogger

    def __call__(self, task: asyncio.Task) -> None:
        self.logger.info(
            "Task is done, prompting others to quit.",
            name=self.name,
            future=task,
        )

        if task.exception() is not None:
            self.logger.error(type(task.exception()))  # type: ignore
            self.logger.exception(task.exception())  # type: ignore

        self.shutdown_handler(None, None)


@dataclass
class Submission:
    name: str
    exit_event: asyncio.Event
    shutdown_handler: ShutdownHandler
    logger: BoundLogger
    awaitable: Coroutine[None, None, Any]

    def submit(self, executor: asyncio.TaskGroup) -> asyncio.Task:
        task = executor.create_task(self.awaitable)

        # task.add_done_callback(
        #    DoneHandler(self.name, self.shutdown_handler, self.logger)
        # )

        return task


async def main_loop(
    application_setup: Callable[[asyncio.Event, BoundLogger], Awaitable[Application]],
    logger: BoundLogger,
) -> None:
    exit_event = asyncio.Event()
    mailbox = asyncio.Queue()

    shutdown_handler = ShutdownHandler(exit_event, logger)
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_event_loop().add_signal_handler(sig, shutdown_handler)

    with suppress(asyncio.exceptions.CancelledError):
        async with asyncio.TaskGroup() as tg:
            Submission(
                "game",
                exit_event,
                shutdown_handler,
                logger,
                game_run(application_setup, mailbox, exit_event, logger),
            ).submit(tg)
            Submission(
                "display",
                exit_event,
                shutdown_handler,
                logger,
                display_run(mailbox, exit_event, logger),
            ).submit(tg)
            Submission(
                "event",
                exit_event,
                shutdown_handler,
                logger,
                event_run(mailbox, exit_event, logger),
            ).submit(tg)

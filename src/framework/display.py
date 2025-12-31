import asyncio
from time import monotonic_ns

import pygame
from structlog.stdlib import BoundLogger

from framework.actor import (
    ExecuteRequest,
    SetRequest,
    execute_sync,
)
from framework.common import coroutine_loop
from framework.game import Application, SystemEvent, event_post

TARGET_FPS = 60
PROCESSING_BUFFER = 5
TARGET_FRAME_PROCESSING_TIME = (1_000_000_000 / TARGET_FPS) - PROCESSING_BUFFER


async def run(
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    exit_event: asyncio.Event,
    logger: BoundLogger,
) -> None:
    asyncio.create_task(coroutine_loop(update, mailbox, logger))

    await exit_event.wait()


async def check_is_time_to_render(start_time: int) -> bool:
    return (monotonic_ns() - start_time) >= TARGET_FRAME_PROCESSING_TIME


async def update(
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    logger: BoundLogger,
) -> None:
    await execute_sync(mailbox, None)(_update, logger)


async def _update(application: Application, logger: BoundLogger) -> bool:
    start_time = monotonic_ns()

    updates = []

    while True:
        try:
            updates.append(application.display_update.get_nowait())

        except asyncio.QueueEmpty:
            if await check_is_time_to_render(start_time):
                break

    pygame.display.update(updates)

    await event_post(application.events, SystemEvent.FRAME_NEXT)

    application.clock.tick()

    # asyncio.create_task(logger.adebug("Frame rate", fps=application.clock.get_fps()))

    return True

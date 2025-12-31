import asyncio
from uuid import UUID

import pygame
from frozendict import frozendict
from structlog.stdlib import BoundLogger

from framework.actor import (
    ExecuteRequest,
    SetRequest,
    execute,
    execute_sync,
)
from framework.common import coroutine_loop
from framework.game import (
    Application,
    Element,
    SystemEvent,
    event_post,
    event_quit,
)


async def run(
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    exit_event: asyncio.Event,
    logger: BoundLogger,
) -> None:
    asyncio.create_task(coroutine_loop(process, mailbox, logger))

    execute(mailbox, "events")(event_post, SystemEvent.INIT)

    await exit_event.wait()


def check_is_collide(element: type[Element], event: pygame.event.Event) -> bool:
    assert isinstance(element.position, pygame.Rect)

    mouse_x, mouse_y = event.pos

    return element.position.collidepoint(mouse_x, mouse_y)


async def dispatch_mouse(
    application: Application,
    event: pygame.event.Event,
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    logger: BoundLogger,
) -> None:
    async with asyncio.TaskGroup() as tg:
        listeners = application.listeners.get(event.type, frozendict())

        # dispatch application mousedown events
        tg.create_task(dispatch_to_target(application, event, None, mailbox, logger))

        for element_id in listeners.keys():
            if element_id == "*":
                continue

            if check_is_collide(application.elements[element_id], event):  # ty:ignore[invalid-argument-type]
                # dispatch element mousedown events
                tg.create_task(
                    dispatch_to_target(application, event, element_id, mailbox, logger)
                )


async def dispatch_to_target(
    application: Application,
    event: pygame.event.Event,
    target: UUID | None,
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    logger: BoundLogger,
) -> None:
    if target:
        for listener in application.listeners.get(event.type, frozendict()).get(
            target, ()
        ):
            asyncio.create_task(
                listener.op(event, application.elements[target], mailbox, logger)  # ty:ignore[invalid-argument-type]
            )

    else:
        for elem, listeners in application.listeners.get(
            event.type, frozendict()
        ).items():
            for listener in listeners:
                if elem == "*":
                    asyncio.create_task(
                        listener.op(event, application, mailbox, logger)
                    )
                else:
                    asyncio.create_task(
                        listener.op(event, application.elements[elem], mailbox, logger)  # ty:ignore[invalid-argument-type]
                    )


async def process(
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    logger: BoundLogger,
) -> None:
    sync_post = execute_sync(mailbox, "events")(event_post, SystemEvent.REFRESH)

    for event in pygame.event.get():
        match event.type:
            case pygame.QUIT:
                execute(mailbox, "exit_event")(event_quit)

            case pygame.MOUSEBUTTONDOWN:
                execute(mailbox)(dispatch_mouse, event, mailbox, logger)

            case custom if hasattr(event, "__target__") and custom >= pygame.USEREVENT:
                execute(mailbox)(
                    dispatch_to_target, event, event.__target__, mailbox, logger
                )

            case custom if custom >= pygame.USEREVENT:
                execute(mailbox)(dispatch_to_target, event, None, mailbox, logger)

    await sync_post

import asyncio
from dataclasses import dataclass, field, replace
from time import monotonic_ns

import pygame
import pygame.freetype
import structlog
from structlog.stdlib import BoundLogger
from toolz.functoolz import curry, thread_last

from framework.actor import ExecuteRequest, SetRequest, execute_sync
from framework.core import main_loop
from framework.game import (
    Application,
    Element,
    SystemEvent,
    add_event_listener,
    application_init,
    listener_add_list,
    queue_element,
    remove_element,
    update_element,
)


@dataclass(frozen=True)
class CharElem(Element):
    value: str = " "
    font: pygame.freetype.Font | None = None
    color: tuple[int, int, int] = (0, 0, 0)
    alpha: int = 0


async def char_create(
    application: Application,
    value: str,
    size: int,
    color: tuple[int, int, int],
    alpha: int,
    position: tuple[int, int],
) -> CharElem:
    assert len(value) == 1 and isinstance(value, str)

    font = pygame.freetype.Font("./RecMonoSmCasualNerdFont-Regular.ttf", size)

    surface, rect = font.render(value, (255, 255, 255, alpha))

    rect.topleft = position

    pygame.draw.rect(application.screen, (0, 0, 0), rect)
    application.screen.blit(surface, rect)

    return CharElem(position=rect, value=value, font=font, color=color, alpha=alpha)


async def char_update(application: Application, elem: CharElem, alpha: int) -> CharElem:
    assert elem.position
    assert elem.font

    surface, _ = elem.font.render(elem.value, elem.color + (alpha,))

    pygame.draw.rect(application.screen, (0, 0, 0), elem.position)
    application.screen.blit(surface, elem.position)

    return replace(elem, alpha=alpha)


@dataclass
class FadeOutHandler:
    duration: int
    start_time: int = field(default_factory=lambda: monotonic_ns() // 1_000_000)

    async def __call__(
        self,
        _event: pygame.event.Event,
        target: CharElem,
        mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
        _logger: BoundLogger,
    ) -> None:
        current = monotonic_ns() // 1_000_000
        elapsed = current - self.start_time
        remaining = 1.0 - (elapsed / self.duration)
        alpha = int(max(255 * remaining, 0))

        future_elem = execute_sync(mailbox, None)(char_update, target, alpha)

        queue_element(mailbox, await future_elem)  # ty:ignore[invalid-argument-type]

        if alpha > 0:
            update_element(mailbox, await future_elem)  # ty:ignore[invalid-argument-type]
        else:
            remove_element(mailbox, await future_elem)  # ty:ignore[invalid-argument-type]


async def application_setup(
    exit_event: asyncio.Event,
    logger: BoundLogger,
) -> Application:
    application = await application_init(
        Application(pygame.display.set_mode(size=(1000, 500)), exit_event)
    )
    application = replace(
        application,
        listeners=await listener_add_list(
            application.listeners,
            None,
            (application.events[SystemEvent.INIT], handle_init),  # ty:ignore[invalid-argument-type]
        ),
    )

    return application


async def handle_init(
    _event: pygame.event.Event,
    application: Application,
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    _logger: BoundLogger,
) -> None:
    application.screen.fill((0, 0, 0))

    add_event_listener(mailbox, None, pygame.MOUSEBUTTONDOWN, handle_click)

    pygame.display.flip()


def fade_out(
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    application: Application,
    elem: CharElem,
    duration: int,
) -> CharElem:
    return add_event_listener(
        mailbox,
        elem,  # ty:ignore[invalid-argument-type]
        application.events[SystemEvent.FRAME_NEXT],  # ty:ignore[invalid-argument-type]
        FadeOutHandler(duration),
    )  # ty:ignore[invalid-return-type]


async def handle_click(
    event: pygame.event.Event,
    application: Application,
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    _logger: BoundLogger,
) -> None:
    elem = fade_out(
        mailbox,
        application,
        await char_create(application, "a", 150, (255, 255, 0), 255, event.pos),
        1000,
    )

    thread_last(elem, curry(queue_element)(mailbox), curry(update_element)(mailbox))


async def run() -> None:
    logger = structlog.get_logger()

    await main_loop(application_setup, logger)

import asyncio
import signal
from dataclasses import dataclass, field, replace
from time import monotonic_ns
from typing import Any

import pygame
import pygame.freetype
import structlog
from structlog.stdlib import BoundLogger

from kitfucoda_intro2.core import (
    Application,
    ApplicationDataField,
    DeltaAdd,
    DeltaDelete,
    DeltaUpdate,
    Element,
    ExceptionHandler,
    ShutdownHandler,
    SystemEvent,
    add_event_listener,
    add_event_listeners,
    main_loop,
    screen_update,
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
        event: pygame.event.Event,
        target: CharElem,
        application: Application,
        logger: BoundLogger,
        **detail: Any,
    ) -> None:
        current = monotonic_ns() // 1_000_000
        elapsed = current - self.start_time
        remaining = 1.0 - (elapsed / self.duration)
        alpha = int(max(255 * remaining, 0))

        elem = await char_update(application, target, alpha)

        asyncio.create_task(screen_update(application, elem))

        if alpha > 0:
            asyncio.create_task(
                application.delta_data.put(
                    DeltaUpdate(ApplicationDataField.ELEMENTS, target, elem)
                )
            )
        else:
            asyncio.create_task(
                application.delta_data.put(
                    DeltaDelete(ApplicationDataField.ELEMENTS, target)
                )
            )


async def fade_out(application: Application, elem: CharElem, duration: int) -> CharElem:
    return await add_event_listener(
        elem,
        SystemEvent.FRAME_NEXT.value,
        FadeOutHandler(duration),
    )  # type: ignore


async def handle_click(
    event: pygame.event.Event, target: Application, logger: BoundLogger
) -> None:
    elem = await fade_out(
        target,
        await char_create(target, "a", 150, (255, 255, 0), 255, event.pos),
        1000,
    )

    asyncio.create_task(screen_update(target, elem))
    asyncio.create_task(
        target.delta_data.put(DeltaAdd(ApplicationDataField.ELEMENTS, elem))
    )


async def handle_init(
    event: pygame.event.Event, target: Application, logger: BoundLogger
) -> None:
    logger.info("Initializing")
    target.screen.fill((0, 0, 0))

    await add_event_listener(target, pygame.MOUSEBUTTONDOWN, handle_click)

    pygame.display.flip()


async def setup(logger: BoundLogger) -> Application:
    application = await add_event_listeners(
        Application(screen=pygame.display.set_mode((1000, 500))),
        (SystemEvent.INIT.value, handle_init),
    )

    assert isinstance(application, Application)

    shutdown_handler = ShutdownHandler(application.exit_event, logger)
    for s in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        asyncio.get_event_loop().add_signal_handler(s, shutdown_handler)

    asyncio.get_event_loop().set_exception_handler(
        ExceptionHandler(shutdown_handler, logger)
    )

    return application


async def run() -> None:
    logger = structlog.get_logger()

    await main_loop(setup(logger))

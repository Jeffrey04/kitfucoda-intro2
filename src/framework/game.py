"""Wrapper for pygame"""

import asyncio
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import reduce
from time import monotonic_ns
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID, uuid4

import pygame
from frozendict import frozendict
from structlog.stdlib import BoundLogger

from framework.actor import ExecuteRequest, SetRequest, execute, set_
from framework.actor import run as actor_run


class SystemEvent(Enum):
    INIT = auto()
    EXIT = auto()
    REFRESH = auto()
    FRAME_NEXT = auto()


@dataclass(frozen=True)
class Element:
    position: pygame.Rect | None = None
    id: UUID = field(default_factory=uuid4)


@dataclass
class Listener:
    event_type: int
    op: Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class Application:
    screen: pygame.Surface
    exit_event: asyncio.Event
    clock: pygame.time.Clock = field(default_factory=pygame.time.Clock)

    start: int = field(default_factory=monotonic_ns)
    events: frozendict[Any, int] = field(default_factory=lambda: frozendict())

    # listeners[event][* | element_id]
    listeners: frozendict[
        int, frozendict[Literal["*"] | UUID, tuple[Listener, ...]]
    ] = field(default_factory=lambda: frozendict())

    elements: frozendict[UUID, type[Element]] = field(
        default_factory=lambda: frozendict()
    )
    data: frozendict[str, Any] = field(default_factory=lambda: frozendict())

    display_update: asyncio.Queue[Element] = field(default_factory=asyncio.Queue)


async def run(
    setup: Callable[[asyncio.Event, BoundLogger], Awaitable[Application]],
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    exit_event: asyncio.Event,
    logger: BoundLogger,
) -> None:
    pygame.init()

    asyncio.create_task(actor_run(await setup(exit_event, logger), mailbox, exit_event))

    await exit_event.wait()


async def application_init(application: Application) -> Application:
    return await event_register_system(application)


async def display_update_queue(
    display_update: asyncio.Queue[pygame.Rect], elem: type[Element]
) -> None:
    if elem.position:
        display_update.put_nowait(elem.position)


async def event_post(
    events: frozendict[Any, int], event: Any, target: UUID | None = None
) -> None:
    if event_type := events.get(event):
        pygame.event.post(
            pygame.event.Event(event_type, __target__=target)
            if target
            else pygame.event.Event(event_type)
        )


async def event_register(
    events: frozendict[Any, int], event: Any
) -> frozendict[Any, int]:
    return events.set(event, pygame.event.custom_type())  # ty:ignore[no-matching-overload]


async def event_register_system(application: Application) -> Application:
    for event in SystemEvent:
        application = replace(
            application, events=await event_register(application.events, event)
        )

    return application


async def event_quit(exit_event: asyncio.Event) -> None:
    exit_event.set()


async def element_remove(
    elements: frozendict[UUID, type[Element]], element: type[Element]
) -> frozendict[UUID, type[Element]]:
    try:
        return elements.delete(element.id)  # ty:ignore[invalid-argument-type]
    except KeyError:
        return elements


async def element_update(
    elements: frozendict[UUID, type[Element]], element: type[Element]
) -> frozendict[UUID, type[Element]]:
    return elements.set(element.id, element)  # ty:ignore[no-matching-overload]


async def listeners_remove(
    listeners: frozendict[int, frozendict[Literal["*"] | UUID, tuple[Listener, ...]]],
    element: type[Element],
) -> frozendict[int, frozendict[Literal["*"] | UUID, tuple[Listener, ...]]]:
    def _delete_listeners(
        current: frozendict[int, frozendict[Literal["*"] | UUID, tuple[Listener, ...]]],
        incoming: tuple[int, frozendict[Literal["*"] | UUID, tuple[Listener, ...]]],
    ) -> frozendict[int, frozendict[Literal["*"] | UUID, tuple[Listener, ...]]]:
        event, listeners = incoming

        try:
            return current.set(event, listeners.delete(element.id))  # ty:ignore[no-matching-overload, invalid-argument-type]
        except KeyError:
            return current

    return reduce(_delete_listeners, listeners.items(), listeners)


async def listener_add_list(
    listeners: frozendict[int, frozendict[Literal["*"] | UUID, tuple[Listener, ...]]],
    target: type[Element] | None,
    *listeners_new: tuple[int, Callable[..., Awaitable[None]]],
) -> frozendict[int, frozendict[Literal["*"] | UUID, tuple[Listener, ...]]]:
    for event_type, listener in listeners_new:
        application = await listener_add(listeners, target, event_type, listener)

    return application


async def listener_add(
    listeners: frozendict[int, frozendict[Literal["*"] | UUID, tuple[Listener, ...]]],
    target: type[Element] | None,
    event_type: int,
    listener: Callable[..., Awaitable[None]],
) -> frozendict[int, frozendict[Literal["*"] | UUID, tuple[Listener, ...]]]:
    match target:
        case target if isinstance(target, Element):
            key = target.id

        case None:
            key = "*"

        case _:
            raise Exception("Not supported")

    return listeners.set(
        event_type,
        listeners.get(event_type, frozendict()).set(
            key,
            listeners.get(event_type, frozendict()).get(key, ())
            + (Listener(event_type, listener),),
        ),
    )  # ty:ignore[no-matching-overload]


# FRIENDLIER APIs (start with verb)
def add_event_listener(
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    target: type[Element] | None,
    event_type: int,
    listener: Callable[..., Awaitable[None]],
) -> type[Element] | None:
    set_(mailbox, "listeners")(listener_add, target, event_type, listener)

    return target


def remove_element(
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    target: type[Element],
) -> type[Element]:
    set_(mailbox, "elements")(element_remove, target)
    set_(mailbox, "listeners")(listeners_remove, target)

    return target


def update_element(
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    target: type[Element],
) -> type[Element]:
    set_(mailbox, "elements")(element_update, target)

    return target


def queue_element(
    mailbox: asyncio.Queue[SetRequest[Application] | ExecuteRequest[Application]],
    target: type[Element],
) -> type[Element]:
    execute(mailbox, "display_update")(display_update_queue, target)

    return target

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field, is_dataclass, replace
from typing import Any, Callable

from framework.common import coroutine_reduce


@dataclass
class Operation:
    op: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)


@dataclass
class SetRequest[State]:
    operation: Operation
    field: Any

    async def __call__(self, state: State) -> State:
        return _state_setter(
            state,
            self.field,
            await self.operation.op(
                _state_getter(state, self.field) if self.field else state,
                *self.operation.args,
                **self.operation.kwargs,
            ),
        )


@dataclass
class ExecuteRequest[State]:
    operation: Operation
    field: Any | None = None
    reply_to: asyncio.Future | None = None

    async def __call__(self, state: State) -> None:
        result = asyncio.create_task(
            self.operation.op(
                _state_getter(state, self.field) if self.field else state,
                *(self.operation.args),
                **(self.operation.kwargs),
            )
        )

        if self.reply_to:
            self.reply_to.set_result(await result)


async def run[State](
    data: State,
    mailbox: asyncio.Queue[SetRequest[State] | ExecuteRequest[State]],
    exit_event: asyncio.Event,
) -> None:
    asyncio.create_task(coroutine_reduce(consume, data, mailbox))

    await exit_event.wait()


async def consume[State](
    state: State,
    queue: asyncio.Queue[SetRequest[State] | ExecuteRequest[State]],
) -> State:
    result = state

    match request := await queue.get():
        case SetRequest():
            result = await request(state)

            assert result

        case ExecuteRequest():
            asyncio.create_task(request(state))

    return result


def execute[State](
    mailbox: asyncio.Queue[SetRequest[State] | ExecuteRequest[State]],
    field: Any | None = None,
) -> Callable[..., None]:
    def _inner(op: Callable[..., None], *args: Any, **kwargs: Any) -> None:
        mailbox.put_nowait(ExecuteRequest(Operation(op, args, kwargs), field))

    return _inner


def execute_sync[State, Result](
    mailbox: asyncio.Queue[SetRequest[State] | ExecuteRequest[State]],
    field: Any | None = None,
) -> Callable[..., Awaitable[Result]]:
    def _inner(
        op: Callable[..., Result], *args: Any, **kwargs: Any
    ) -> Awaitable[Result]:
        result = asyncio.Future()

        mailbox.put_nowait(ExecuteRequest(Operation(op, args, kwargs), field, result))

        return result

    return _inner


def set_[State](
    mailbox: asyncio.Queue[SetRequest[State] | ExecuteRequest[State]],
    field: Any | None = None,
) -> Callable[..., None]:
    def _inner(op: Callable[..., None], *args: Any, **kwargs: Any) -> None:
        mailbox.put_nowait(SetRequest(Operation(op, args, kwargs), field))

    return _inner


def _state_getter(state: object, key: Any) -> Any:
    return getattr(state, key)


def _state_setter[State](state: State, key: Any, value: Any) -> State:
    assert is_dataclass(state)

    return replace(state, **{key: value})  # type: ignore

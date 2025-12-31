import asyncio
from typing import Any, Awaitable, Callable


async def coroutine_loop(coro_func: Callable[..., Awaitable[None]], *args: Any) -> None:
    try:
        while True:
            await coro_func(*args)
    except asyncio.CancelledError:
        pass


async def coroutine_reduce[T](
    coro_func: Callable[..., Awaitable[T]], initial: T, *args: Any
) -> T:
    result = initial

    try:
        while True:
            result = await coro_func(result, *args)

    except asyncio.CancelledError:
        pass

    return result

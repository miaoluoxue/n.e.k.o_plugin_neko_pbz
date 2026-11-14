from __future__ import annotations

import asyncio
import time

from plugin.plugins.neko_pbz.adapters import LLMProvider


def test_sync_host_callback_does_not_block_event_loop() -> None:
    async def run() -> None:
        provider = LLMProvider(host_timeout=0.05)

        def blocking_host(_prompt: str) -> str:
            time.sleep(0.12)
            return "too late"

        provider.set_host_call(blocking_host)
        started = time.monotonic()
        task = asyncio.create_task(provider.call("test"))
        await asyncio.sleep(0.02)
        loop_responsive_at = time.monotonic() - started
        result = await task

        assert loop_responsive_at < 0.06
        assert result is None

    asyncio.run(run())


def test_async_host_callback_remains_supported() -> None:
    async def run() -> None:
        provider = LLMProvider(host_timeout=1.0)

        async def async_host(_prompt: str) -> str:
            await asyncio.sleep(0.01)
            return "宿主回复"

        provider.set_host_call(async_host)
        assert await provider.call("test") == "宿主回复"

    asyncio.run(run())

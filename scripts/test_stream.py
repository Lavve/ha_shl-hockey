"""Listen to the live stream shl.se's game center uses, and print what comes.

Usage:
    pip install aiohttp
    python scripts/test_stream.py            # listen for 60 seconds
    python scripts/test_stream.py 600        # listen for 10 minutes

On connect the stream first sends the day so far (every game's overview),
then new messages as they happen. Between events it sends nothing at all.
Everything is printed raw, so we can see the exact message format.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import aiohttp

STREAM_URL = "https://game-broadcaster.s8y.se/live/game"
USER_AGENT = "HomeAssistant-SHLHockey/stream-test"


async def main(seconds: int) -> None:
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=seconds)
    end = time.monotonic() + seconds
    kinds: dict[str, int] = {}
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            STREAM_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "text/event-stream"},
        ) as resp:
            print(f"HTTP {resp.status}  {resp.headers.get('Content-Type')}")
            resp.raise_for_status()
            data: list[str] = []
            while time.monotonic() < end:
                try:
                    raw = await asyncio.wait_for(
                        resp.content.readline(), timeout=end - time.monotonic()
                    )
                except TimeoutError:
                    break
                if not raw:
                    print("Stream closed by the server")
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith(":"):
                    print(f"[comment] {line}")
                    continue
                if line:
                    name, _, value = line.partition(":")
                    if name == "data":
                        data.append(value.removeprefix(" "))
                    elif name:
                        print(f"[{name}] {value.strip()}")
                    continue
                if not data:
                    continue
                text = "\n".join(data)
                data = []
                try:
                    message = json.loads(text)
                except ValueError:
                    print(f"[not json] {text[:500]}")
                    continue
                for kind in message if isinstance(message, dict) else ["?"]:
                    kinds[kind] = kinds.get(kind, 0) + 1
                print(f"\n--- {time.strftime('%H:%M:%S')} ---")
                print(json.dumps(message, ensure_ascii=False, indent=2)[:3000])

    print(f"\nMessages by kind: {kinds or 'none'}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 60))

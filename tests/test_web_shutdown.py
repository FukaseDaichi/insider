import asyncio

from insider_bot.web.server import close_all


class RecordingSocket:
    def __init__(self, name: str, gate: asyncio.Event, log: list[tuple[str, str]]) -> None:
        self.name, self.gate, self.log = name, gate, log

    async def close(self, code: int, message: bytes) -> bool:
        self.log.append(("start", self.name))
        await self.gate.wait()
        self.log.append(("end", self.name))
        return True


class BrokenSocket:
    async def close(self, code: int, message: bytes) -> bool:
        raise RuntimeError("接続は既に壊れている")


async def test_close_all_starts_closing_every_socket_before_any_finishes():
    # 1 本ずつ待つと、応答しない端末の数だけ close のタイムアウト（10 秒）が積み上がり、停止が TimeoutStopSec を超える
    gate = asyncio.Event()
    log: list[tuple[str, str]] = []
    sockets = [RecordingSocket(f"ws{i}", gate, log) for i in range(3)]
    task = asyncio.create_task(close_all(sockets))
    for _ in range(3):  # close_all のタスク → gather が作る 3 つのタスク、の順に動き出すまでループを譲る
        await asyncio.sleep(0)
    assert log == [("start", "ws0"), ("start", "ws1"), ("start", "ws2")]
    gate.set()
    await task
    assert sorted(name for kind, name in log if kind == "end") == ["ws0", "ws1", "ws2"]


async def test_close_all_keeps_going_when_one_socket_raises():
    gate = asyncio.Event()
    gate.set()
    log: list[tuple[str, str]] = []
    await close_all([BrokenSocket(), RecordingSocket("ws1", gate, log)])
    assert ("end", "ws1") in log

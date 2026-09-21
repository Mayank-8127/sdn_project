"""A tiny discrete-event simulation engine.

Real networks run in real time. To study them reproducibly we use *virtual
time*: instead of waiting 5 ms for a packet to cross a link, we write down
"at time now+0.005, deliver this packet" in an agenda (a priority queue) and
jump straight to the next item on the agenda. This is called discrete-event
simulation.

Example::

    sim = Simulator()
    sim.schedule(0.5, print, "half a second later")
    sim.run()
"""

from __future__ import annotations

import heapq
import itertools
from typing import Any, Callable


class Event:
    """A scheduled callback. Keep the handle if you may want to cancel it."""

    __slots__ = ("time", "fn", "args", "cancelled")

    def __init__(self, time: float, fn: Callable[..., Any], args: tuple):
        self.time = time
        self.fn = fn
        self.args = args
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class Simulator:
    """Virtual clock plus an agenda of future events.

    Events with the same time run in the order they were scheduled (FIFO),
    which makes every run fully deterministic.
    """

    def __init__(self) -> None:
        self.now: float = 0.0
        self._queue: list[tuple[float, int, Event]] = []
        self._counter = itertools.count()
        self.events_processed = 0

    def schedule(self, delay: float, fn: Callable[..., Any], *args: Any) -> Event:
        """Run ``fn(*args)`` after ``delay`` seconds of virtual time."""
        if delay < 0:
            raise ValueError(f"negative delay {delay}")
        return self.at(self.now + delay, fn, *args)

    def at(self, time: float, fn: Callable[..., Any], *args: Any) -> Event:
        """Run ``fn(*args)`` at absolute virtual time ``time``."""
        if time < self.now:
            raise ValueError(f"cannot schedule in the past ({time} < {self.now})")
        ev = Event(time, fn, args)
        heapq.heappush(self._queue, (time, next(self._counter), ev))
        return ev

    def run(self, until: float | None = None) -> None:
        """Process events until the agenda is empty or ``until`` is reached."""
        while self._queue:
            time, _, ev = self._queue[0]
            if until is not None and time > until:
                break
            heapq.heappop(self._queue)
            if ev.cancelled:
                continue
            self.now = time
            self.events_processed += 1
            ev.fn(*ev.args)
        if until is not None and until > self.now:
            self.now = until

    @property
    def pending(self) -> int:
        return sum(1 for _, _, ev in self._queue if not ev.cancelled)

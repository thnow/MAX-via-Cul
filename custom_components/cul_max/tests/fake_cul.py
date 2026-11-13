"""In-memory stand-in for a CUL running a-culfw, plus simulated MAX! devices.

The coordinator talks to it through the same StreamReader/StreamWriter pair
it gets from ``open_cul_connection``. The fake answers the credit query
("X"), books the duty-cycle cost of every send like a-culfw does, answers
"LOVF" when the credit is too low, and lets simulated devices ACK the
packets addressed to them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

PREAMBLE_COST = 100  # a-culfw: 1 s wake-up preamble of a "Zs" send


def packet_cost(cmd: str) -> int:
    """Credit a-culfw books for one Zs/Zf send (rf_moritz.c)."""
    packet = cmd[2:]
    return (PREAMBLE_COST if cmd.startswith("Zs") else 0) + (len(packet) * 4) // 10


@dataclass
class SentPacket:
    """One MAX! packet that went on air."""

    raw: str

    @property
    def counter(self) -> int:
        return int(self.raw[2:4], 16)

    @property
    def msg_type(self) -> int:
        return int(self.raw[6:8], 16)

    @property
    def src(self) -> str:
        return self.raw[8:14].upper()

    @property
    def dst(self) -> str:
        return self.raw[14:20].upper()


MSG_CONFIG_WEEK_PROFILE = 0x10
MSG_ADD_LINK_PARTNER = 0x20
MSG_REMOVE_LINK_PARTNER = 0x21
DEVICE_TYPE_WALL_THERMOSTAT = 3


@dataclass
class FakeDevice:
    """A MAX! heating thermostat that ACKs packets addressed to it.

    It keeps what a real one keeps: the week-profile chunks it received and
    its link partners. Like the real device it accepts only one wall
    thermostat as link partner and answers 0x81 to a second one.
    """

    address: str
    ignore_next: int = 0  # packets lost on air before the device hears one
    silent: bool = False  # never answers
    nack: bool = False  # answers "invalid command/argument"
    lose_from: int | None = None  # stop answering after this many received packets
    drop: set[int] = field(default_factory=set)  # numbers (1-based) of transmissions lost on air
    heard: int = 0  # transmissions addressed to this device so far
    received: list[SentPacket] = field(default_factory=list)
    week_profile: dict[tuple[int, int], str] = field(default_factory=dict)
    links: dict[str, int] = field(default_factory=dict)  # partner -> device type

    @property
    def wall_thermostats(self) -> list[str]:
        return [a for a, t in self.links.items() if t == DEVICE_TYPE_WALL_THERMOSTAT]

    def _apply(self, packet: SentPacket) -> bool:
        """Apply a configuration packet; False means 'invalid command'."""
        payload = packet.raw[22:]
        if packet.msg_type == MSG_CONFIG_WEEK_PROFILE:
            selector = int(payload[0:2], 16)
            self.week_profile[(selector & 0x07, (selector >> 3) & 0x01)] = payload[2:].upper()
        elif packet.msg_type == MSG_ADD_LINK_PARTNER:
            partner, kind = payload[0:6].upper(), int(payload[6:8], 16)
            if kind == DEVICE_TYPE_WALL_THERMOSTAT and any(
                wt != partner for wt in self.wall_thermostats
            ):
                return False
            self.links[partner] = kind
        elif packet.msg_type == MSG_REMOVE_LINK_PARTNER:
            self.links.pop(payload[0:6].upper(), None)
        return True

    def answer(self, packet: SentPacket) -> str | None:
        """Return the ACK line for a received packet, or None."""
        self.heard += 1
        if self.heard in self.drop:
            return None
        if self.silent:
            return None
        if self.ignore_next > 0:
            self.ignore_next -= 1
            return None
        if self.lose_from is not None and len(self.received) >= self.lose_from:
            return None
        self.received.append(packet)
        ok = not self.nack and self._apply(packet)
        status = "01" if ok else "81"
        body = f"{packet.counter:02X}0202{self.address}{packet.src}00{status}"
        return f"Z{len(body) // 2:02X}{body}"


class FakeWriter:
    """StreamWriter replacement that hands every written line to the CUL."""

    def __init__(self, cul: FakeCul) -> None:
        self._cul = cul
        self._buffer = ""
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.closed:
            raise ConnectionResetError("fake CUL connection closed")
        self._buffer += data.decode("ascii")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._cul.handle(line.strip())

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None

    def is_closing(self) -> bool:
        return self.closed

    def get_extra_info(self, name: str, default=None):
        return default


class FakeCul:
    """Simulated CUL: credit bookkeeping, LOVF, device ACKs, disconnects."""

    def __init__(self, credit: int = 900, ack_delay: float = 0.02) -> None:
        self.credit = credit
        self.ack_delay = ack_delay
        self.devices: dict[str, FakeDevice] = {}
        self.on_air: list[SentPacket] = []
        self.control: list[str] = []
        self.lovf_next = 0  # force LOVF for the next n sends
        self.answer_credit_query = True
        self.connections = 0
        self.refuse_connections = False
        self._reader: asyncio.StreamReader | None = None
        self._writer: FakeWriter | None = None
        self._timers: list[asyncio.TimerHandle] = []

    def add_device(self, address: str, **kwargs) -> FakeDevice:
        device = FakeDevice(address.upper(), **kwargs)
        self.devices[device.address] = device
        return device

    async def open(self, host: str, port: int, *, serial: bool = False):
        """Drop-in replacement for coordinator.open_cul_connection."""
        if self.refuse_connections:
            raise OSError("fake CUL refuses connections")
        self.connections += 1
        self._reader = asyncio.StreamReader()
        self._writer = FakeWriter(self)
        return self._reader, self._writer

    def disconnect(self) -> None:
        """Simulate a dropped TCP connection (Cube reboot, network glitch)."""
        if self._writer is not None:
            self._writer.closed = True
        if self._reader is not None:
            self._reader.feed_eof()

    def send_line(self, line: str) -> None:
        """Deliver one line from the CUL to the coordinator."""
        if self._reader is not None and not self._reader.at_eof():
            self._reader.feed_data(f"{line}\r\n".encode("ascii"))

    def handle(self, cmd: str) -> None:
        if cmd == "X":
            if self.answer_credit_query:
                self.send_line(f"21{self.credit:5d}")
            return
        if cmd.startswith(("Zs", "Zf")):
            cost = packet_cost(cmd)
            if self.lovf_next > 0 or self.credit < cost:
                self.lovf_next = max(0, self.lovf_next - 1)
                self.send_line("LOVF")
                return
            self.credit -= cost
            packet = SentPacket(cmd[2:])
            self.on_air.append(packet)
            device = self.devices.get(packet.dst)
            if device is not None:
                ack = device.answer(packet)
                if ack is not None:
                    self._timers.append(
                        asyncio.get_running_loop().call_later(self.ack_delay, self.send_line, ack)
                    )
            return
        self.control.append(cmd)

    def close(self) -> None:
        """Cancel ACKs still scheduled when a test ends."""
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()

    def on_air_to(self, address: str) -> list[SentPacket]:
        return [p for p in self.on_air if p.dst == address.upper()]

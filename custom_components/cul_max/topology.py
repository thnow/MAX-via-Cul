"""Render the MAX! device topology (rooms, devices, links) as a simple SVG."""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

ROOM_WIDTH = 400
ROOM_GAP = 16
COLUMNS = 3
NODE_WIDTH = 158
NODE_HEIGHT = 64  # name, status, address/serial
NODE_GAP = 10
ROOM_HEADER = 36
LEFT_X = 14
BRACKET_SPACE = 36  # room for wall-thermostat brackets right of the devices
RIGHT_X = ROOM_WIDTH - NODE_WIDTH - BRACKET_SPACE
NOTE_CHARS = 25
NOTE_MAX_LINES = 3
LINE_HEIGHT = 14

FONT = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
COLORS = {
    "background": "#f6f8fa",
    "room": "#ffffff",
    "room_border": "#d0d7de",
    "text": "#1f2328",
    "muted": "#59636e",
    "edge": "#8c959f",
    "warn": "#cf222e",
    "ok": "#1a7f37",
    "contact": "#e7f3ff",
    "contact_border": "#54aeff",
    "thermostat": "#fff4e5",
    "thermostat_border": "#d4a72c",
    "wall": "#fbefff",
    "wall_border": "#a475f9",
}

KIND_CONTACT = "contact"
KIND_THERMOSTAT = "thermostat"
KIND_WALL = "wall"


@dataclass
class TopologyNode:
    """One device in the picture."""

    key: str
    room: str
    kind: str
    name: str
    status: str = ""
    ident: str = ""  # MAX! address and serial number
    virtual: bool = False
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class TopologyEdge:
    """One on-device link between two devices."""

    a: str
    b: str


def _short(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _wrap(text: str, width: int = NOTE_CHARS, max_lines: int = NOTE_MAX_LINES) -> list[str]:
    """Word-wrap a note so it fits into a device box."""
    lines: list[str] = []
    current = ""
    for word in str(text).split():
        while len(word) > width:  # very long word: hard split
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:width])
            word = word[width:]
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _short(lines[-1] + " …", width)
    return lines or [""]


def _note_lines(node: TopologyNode) -> list[tuple[str, str]]:
    """All wrapped note/problem lines of a node as (text, colour)."""
    out: list[tuple[str, str]] = []
    for note in node.notes:
        out.extend((line, COLORS["ok"]) for line in _wrap(note))
    for problem in node.problems:
        out.extend((line, COLORS["warn"]) for line in _wrap(problem))
    return out


def _strip_room(name: str, room: str) -> str:
    """'Thermostat Kinderzimmer' in room 'Kinderzimmer' → 'Thermostat'."""
    if room and room.lower() in name.lower() and name.lower() != room.lower():
        idx = name.lower().index(room.lower())
        stripped = (name[:idx] + name[idx + len(room):]).strip(" -·")
        return stripped or name
    return name


def render_topology_svg(nodes: list[TopologyNode], edges: list[TopologyEdge], *, title: str) -> str:
    """Return an SVG document showing rooms, devices and their links."""
    by_key = {node.key: node for node in nodes}
    rooms: dict[str, list[TopologyNode]] = {}
    for node in nodes:
        rooms.setdefault(node.room, []).append(node)
    room_names = sorted(rooms, key=lambda r: (r == "Ohne Raum", r.lower()))

    # cross-room links become notes instead of lines
    local_edges: list[TopologyEdge] = []
    for edge in edges:
        a, b = by_key.get(edge.a), by_key.get(edge.b)
        if a is None or b is None:
            continue
        if a.room == b.room:
            local_edges.append(edge)
        else:
            a.problems.append(f"↔ {b.room}: {b.name}")
            b.problems.append(f"↔ {a.room}: {a.name}")

    # layout per room
    layout: dict[str, tuple[float, float]] = {}  # node key -> (x, y) relative to room
    room_heights: dict[str, float] = {}
    for room in room_names:
        members = rooms[room]
        left = sorted((n for n in members if n.kind == KIND_CONTACT), key=lambda n: n.name.lower())
        right = sorted(
            (n for n in members if n.kind != KIND_CONTACT),
            key=lambda n: (n.kind != KIND_WALL, n.name.lower()),
        )
        for column, x in ((left, LEFT_X), (right, RIGHT_X)):
            for idx, node in enumerate(column):
                extra = LINE_HEIGHT * len(_note_lines(node))
                y = ROOM_HEADER + sum(
                    NODE_HEIGHT + NODE_GAP + LINE_HEIGHT * len(_note_lines(n))
                    for n in column[:idx]
                )
                layout[node.key] = (x, y)
                node._extra = extra  # type: ignore[attr-defined]
        heights = [
            layout[n.key][1] + NODE_HEIGHT + getattr(n, "_extra", 0) for n in members
        ]
        room_heights[room] = max(heights, default=ROOM_HEADER) + 14

    # room positions
    room_pos: dict[str, tuple[float, float]] = {}
    y = 64
    for row_start in range(0, len(room_names), COLUMNS):
        row = room_names[row_start:row_start + COLUMNS]
        for col, room in enumerate(row):
            room_pos[room] = (ROOM_GAP + col * (ROOM_WIDTH + ROOM_GAP), y)
        y += max(room_heights[r] for r in row) + ROOM_GAP
    width = ROOM_GAP + COLUMNS * (ROOM_WIDTH + ROOM_GAP)
    height = y + 30

    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{FONT}">',
        f'<rect width="100%" height="100%" fill="{COLORS["background"]}"/>',
        f'<text x="{ROOM_GAP}" y="30" font-size="18" font-weight="600" fill="{COLORS["text"]}">{escape(title)}</text>',
        f'<text x="{ROOM_GAP}" y="50" font-size="12" fill="{COLORS["muted"]}">'
        "Linien = Verknüpfung auf den Geräten · gestrichelt = virtuell · rot = Handlungsbedarf</text>",
    ]
    for room in room_names:
        rx, ry = room_pos[room]
        out.append(
            f'<rect x="{rx}" y="{ry}" width="{ROOM_WIDTH}" height="{room_heights[room]}" rx="10" '
            f'fill="{COLORS["room"]}" stroke="{COLORS["room_border"]}"/>'
        )
        out.append(
            f'<text x="{rx + 14}" y="{ry + 23}" font-size="14" font-weight="600" fill="{COLORS["text"]}">'
            f"{escape(_short(room, 40))}</text>"
        )
        # edges first (under the boxes)
        room_edges = [
            e for e in local_edges if by_key[e.a].room == room
        ]
        same_column = [
            e for e in room_edges
            if (by_key[e.a].kind == KIND_CONTACT) == (by_key[e.b].kind == KIND_CONTACT)
        ]
        right_brackets = sum(1 for e in same_column if by_key[e.a].kind != KIND_CONTACT)
        left_brackets = len(same_column) - right_brackets
        # keep every bracket inside the room box
        right_step = min(5.0, (BRACKET_SPACE - 10) / max(right_brackets, 1))
        left_step = min(5.0, (LEFT_X - 4) / max(left_brackets, 1))
        right_n = left_n = 0
        for edge in room_edges:
            a, b = by_key[edge.a], by_key[edge.b]
            _ax, ay = layout[a.key]
            _bx, by = layout[b.key]
            ay_mid = ry + ay + NODE_HEIGHT / 2
            by_mid = ry + by + NODE_HEIGHT / 2
            if (a.kind == KIND_CONTACT) != (b.kind == KIND_CONTACT):
                c, t = (a, b) if a.kind == KIND_CONTACT else (b, a)
                cx, cy = layout[c.key]
                tx, ty = layout[t.key]
                x1, y1 = rx + cx + NODE_WIDTH, ry + cy + NODE_HEIGHT / 2
                x2, y2 = rx + tx, ry + ty + NODE_HEIGHT / 2
                mid = (x1 + x2) / 2
                out.append(
                    f'<path d="M{x1},{y1} C{mid},{y1} {mid},{y2} {x2},{y2}" fill="none" '
                    f'stroke="{COLORS["edge"]}" stroke-width="1.5"/>'
                )
            else:
                # both in the same column: bracket on the outer side
                if a.kind == KIND_CONTACT:
                    left_n += 1
                    x = rx + LEFT_X - 2 - left_step * left_n
                    edge_x = rx + LEFT_X
                else:
                    right_n += 1
                    x = rx + RIGHT_X + NODE_WIDTH + 4 + right_step * right_n
                    edge_x = rx + RIGHT_X + NODE_WIDTH
                out.append(
                    f'<path d="M{edge_x},{ay_mid} H{x} V{by_mid} H{edge_x}" fill="none" '
                    f'stroke="{COLORS["wall_border"]}" stroke-width="1.5"/>'
                )
        for node in rooms[room]:
            nx, ny = layout[node.key]
            x, y0 = rx + nx, ry + ny
            fill, border = {
                KIND_CONTACT: (COLORS["contact"], COLORS["contact_border"]),
                KIND_THERMOSTAT: (COLORS["thermostat"], COLORS["thermostat_border"]),
                KIND_WALL: (COLORS["wall"], COLORS["wall_border"]),
            }[node.kind]
            if node.problems:
                border = COLORS["warn"]
            h = NODE_HEIGHT + getattr(node, "_extra", 0)
            dash = ' stroke-dasharray="5 3"' if node.virtual else ""
            out.append(
                f'<rect x="{x}" y="{y0}" width="{NODE_WIDTH}" height="{h}" rx="7" fill="{fill}" '
                f'stroke="{border}" stroke-width="1.4"{dash}/>'
            )
            label = _strip_room(node.name, room)
            out.append(
                f'<text x="{x + 9}" y="{y0 + 18}" font-size="12.5" font-weight="600" fill="{COLORS["text"]}">'
                f"{escape(_short(label, 22))}</text>"
            )
            if node.status:
                out.append(
                    f'<text x="{x + 9}" y="{y0 + 35}" font-size="11.5" fill="{COLORS["muted"]}">'
                    f"{escape(_short(node.status, 26))}</text>"
                )
            if node.ident:
                out.append(
                    f'<text x="{x + 9}" y="{y0 + 50}" font-size="10.5" font-family="ui-monospace, Menlo, Consolas, monospace" '
                    f'fill="{COLORS["muted"]}">{escape(_short(node.ident, 28))}</text>'
                )
            line_y = y0 + 50 + LINE_HEIGHT
            for text, colour in _note_lines(node):
                out.append(
                    f'<text x="{x + 9}" y="{line_y}" font-size="11" fill="{colour}">'
                    f"{escape(text)}</text>"
                )
                line_y += LINE_HEIGHT
    out.append("</svg>")
    return "\n".join(out)

"""Render the MAX! device topology (rooms, devices, links) as a simple SVG."""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

ROOM_WIDTH = 380
ROOM_GAP = 16
COLUMNS = 3
NODE_WIDTH = 158
NODE_HEIGHT = 50
NODE_GAP = 10
ROOM_HEADER = 36
LEFT_X = 14
RIGHT_X = ROOM_WIDTH - NODE_WIDTH - 14

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
            a.problems.append(f"verknüpft mit {_short(b.name, 18)} ({b.room})")
            b.problems.append(f"verknüpft mit {_short(a.name, 18)} ({a.room})")

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
                extra = 14 * (len(node.problems) + len(node.notes))
                y = ROOM_HEADER + sum(
                    NODE_HEIGHT + NODE_GAP + 14 * (len(n.problems) + len(n.notes))
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
        bracket = 0
        for edge in room_edges:
            a, b = by_key[edge.a], by_key[edge.b]
            ax, ay = layout[a.key]
            bx, by = layout[b.key]
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
                bracket += 1
                outer = 6 + 5 * bracket
                if a.kind == KIND_CONTACT:
                    x = rx + LEFT_X - outer
                    edge_x = rx + LEFT_X
                else:
                    x = rx + RIGHT_X + NODE_WIDTH + outer
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
            line_y = y0 + 35 + 14
            for note in node.notes:
                out.append(
                    f'<text x="{x + 9}" y="{line_y}" font-size="11" fill="{COLORS["ok"]}">'
                    f"{escape(_short(note, 27))}</text>"
                )
                line_y += 14
            for problem in node.problems:
                out.append(
                    f'<text x="{x + 9}" y="{line_y}" font-size="11" fill="{COLORS["warn"]}">'
                    f"{escape(_short(problem, 27))}</text>"
                )
                line_y += 14
    out.append("</svg>")
    return "\n".join(out)

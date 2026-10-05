"""Fondo animado de la interfaz: una 'aurora' digital (bloques de luz muy
difuminados que derivan lentamente) mas una constelacion de puntos que
representan datos conectandose entre si con lineas finas -- movimiento
sutil, pensado para quedar de fondo detras de los paneles de vidrio sin
distraer del contenido.

Uso (ver main.py):

    bg = theme_bg.AnimatedBackground(page)
    root = ft.Stack([bg.stack, foreground], expand=True)
    page.add(root)
    page.run_task(bg.start)   # arranca los dos loops de animacion
    page.on_resize = bg.on_page_resize
"""
from __future__ import annotations

import asyncio
import random

import flet as ft
import flet.canvas as cv

import theme

_N_NODES = 40
_MAX_LINK_DIST = 135
_TICK_SECONDS = 0.09
_NODE_SPEED = 0.35
_AURORA_PERIOD_SECONDS = 10

_AURORA_SPECS = [
    (theme.ACCENT_CYAN, 640),
    (theme.ACCENT_VIOLET, 560),
    (theme.ACCENT_GOLD, 460),
]


class _Node:
    __slots__ = ("x", "y", "vx", "vy")

    def __init__(self, w: float, h: float):
        self.x = random.uniform(0, max(1.0, w))
        self.y = random.uniform(0, max(1.0, h))
        self.vx = _NODE_SPEED * random.uniform(0.4, 1.0) * random.choice((-1, 1))
        self.vy = _NODE_SPEED * random.uniform(0.4, 1.0) * random.choice((-1, 1))

    def step(self, w: float, h: float):
        self.x += self.vx
        self.y += self.vy
        if self.x <= 0 or self.x >= w:
            self.vx *= -1
            self.x = min(max(self.x, 0), max(w, 0))
        if self.y <= 0 or self.y >= h:
            self.vy *= -1
            self.y = min(max(self.y, 0), max(h, 0))


def _aurora_blob(color: str, size: int) -> ft.Container:
    return ft.Container(
        width=size,
        height=size,
        left=-size * 0.3,
        top=-size * 0.3,
        border_radius=size,
        gradient=ft.RadialGradient(
            colors=[ft.Colors.with_opacity(0.26, color), ft.Colors.with_opacity(0.0, color)],
        ),
        blur=ft.Blur(90, 90, ft.BlurTileMode.CLAMP) if hasattr(ft, "BlurTileMode") else 90,
        animate_position=ft.Animation(_AURORA_PERIOD_SECONDS * 1000, ft.AnimationCurve.EASE_IN_OUT),
    )


class AnimatedBackground:
    """Capa de fondo: color base + 'auroras' que derivan + constelacion de
    datos. Se agrega como el primer elemento de un ft.Stack, detras de
    toda la interfaz."""

    def __init__(self, page: ft.Page, width: float = 1180, height: float = 800):
        self.page = page
        self._w = width or 1180
        self._h = height or 800
        self._running = False
        self._nodes = [_Node(self._w, self._h) for _ in range(_N_NODES)]

        self._blobs = [_aurora_blob(color, size) for color, size in _AURORA_SPECS]
        self.canvas = cv.Canvas(shapes=[], expand=True)

        self.stack = ft.Stack(
            [
                ft.Container(expand=True, bgcolor=theme.BG_DEEP),
                *self._blobs,
                self.canvas,
            ],
            expand=True,
        )
        self._place_blobs_initial()

    def _place_blobs_initial(self):
        rnd = random.Random(7)
        for blob in self._blobs:
            blob.left = rnd.uniform(-blob.width * 0.35, max(0.0, self._w - blob.width * 0.65))
            blob.top = rnd.uniform(-blob.height * 0.35, max(0.0, self._h - blob.height * 0.65))

    def on_page_resize(self, e=None):
        w = getattr(e, "width", None) or self.page.window.width
        h = getattr(e, "height", None) or self.page.window.height
        if w and h:
            self._w, self._h = float(w), float(h)

    async def start(self):
        if self._running:
            return
        self._running = True
        asyncio.create_task(self._aurora_loop())
        asyncio.create_task(self._constellation_loop())

    def stop(self):
        self._running = False

    async def _aurora_loop(self):
        rnd = random.Random()
        while self._running:
            await asyncio.sleep(_AURORA_PERIOD_SECONDS)
            if not self._running:
                break
            for blob in self._blobs:
                blob.left = rnd.uniform(-blob.width * 0.35, max(0.0, self._w - blob.width * 0.65))
                blob.top = rnd.uniform(-blob.height * 0.35, max(0.0, self._h - blob.height * 0.65))
            try:
                self.stack.update()
            except Exception:
                pass

    async def _constellation_loop(self):
        while self._running:
            for n in self._nodes:
                n.step(self._w, self._h)

            shapes: list = []
            for i, a in enumerate(self._nodes):
                for b in self._nodes[i + 1 :]:
                    dx = a.x - b.x
                    dy = a.y - b.y
                    dist = (dx * dx + dy * dy) ** 0.5
                    if dist < _MAX_LINK_DIST:
                        op = 0.15 * (1 - dist / _MAX_LINK_DIST)
                        shapes.append(
                            cv.Line(
                                a.x, a.y, b.x, b.y,
                                paint=ft.Paint(
                                    color=ft.Colors.with_opacity(op, theme.ACCENT_CYAN),
                                    stroke_width=1,
                                    style=ft.PaintingStyle.STROKE,
                                ),
                            )
                        )
            for n in self._nodes:
                shapes.append(
                    cv.Circle(
                        n.x, n.y, 1.6,
                        paint=ft.Paint(
                            color=ft.Colors.with_opacity(0.5, theme.ACCENT_CYAN),
                            style=ft.PaintingStyle.FILL,
                        ),
                    )
                )

            self.canvas.shapes = shapes
            try:
                self.canvas.update()
            except Exception:
                pass
            await asyncio.sleep(_TICK_SECONDS)

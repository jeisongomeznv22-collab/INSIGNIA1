"""Paleta y helpers visuales: identidad "Insignia" -- casco legionario en
metal pulido sobre negro, monocromatico (plata / negro brillante), sin
neon de colores. Paneles tipo vidrio (glassmorphism) sobre fondo casi
negro, acentos en plata."""
import asyncio

import flet as ft

BG_DEEP = "#0A0A0C"          # fondo principal, negro (igual al concepto de marca elegido)
BG_PANEL = "#111113"         # base de los paneles
GLASS_FILL = ft.Colors.with_opacity(0.05, "#FFFFFF")
GLASS_BORDER = ft.Colors.with_opacity(0.14, "#C7C9CE")

ACCENT_CYAN = "#C7C9CE"      # plata -- acento interactivo primario (bordes, foco, iconos)
ACCENT_CYAN_DIM = ft.Colors.with_opacity(0.55, "#C7C9CE")
ACCENT_VIOLET = "#EDEEF0"    # plata brillante -- fondo de botones de accion principal
ACCENT_GOLD = "#C9CBD1"      # plata -- badge CEO / monograma "A G" en la cabecera

TEXT_PRIMARY = "#E8E9EC"
TEXT_SECONDARY = ft.Colors.with_opacity(0.62, "#E8E9EC")
TEXT_MUTED = ft.Colors.with_opacity(0.40, "#E8E9EC")

SUCCESS = "#37E29A"
WARNING = "#FFC84D"
ERROR = "#FF5C7A"

FONT_FAMILY = "Segoe UI"


def glass_card(content: ft.Control, padding=20, expand=None, opacity_bg=0.045) -> ft.Container:
    return ft.Container(
        content=content,
        padding=padding,
        expand=expand,
        bgcolor=ft.Colors.with_opacity(opacity_bg, "#FFFFFF"),
        border=ft.Border.all(1, GLASS_BORDER),
        border_radius=16,
        blur=ft.Blur(18, 18, ft.BlurTileMode.CLAMP) if hasattr(ft, "BlurTileMode") else 18,
        shadow=ft.BoxShadow(
            spread_radius=0,
            blur_radius=28,
            color=ft.Colors.with_opacity(0.35, "#000000"),
            offset=ft.Offset(0, 8),
        ),
    )


def section_title(text: str, icon: str = None) -> ft.Row:
    controls = []
    if icon:
        controls.append(ft.Icon(icon, color=ACCENT_CYAN, size=18))
    controls.append(
        ft.Text(
            text,
            size=13,
            weight=ft.FontWeight.W_600,
            color=TEXT_SECONDARY,
            font_family=FONT_FAMILY,
        )
    )
    return ft.Row(controls, spacing=8)


def neon_gradient_text(text: str, size: int = 26) -> ft.ShaderMask:
    """Titulo de marca "Insignia": negro brillante (degradado negro -> gris
    grafito -> negro) usando ShaderMask sobre el texto -- el mismo
    tratamiento del concepto de marca elegido ("A -- Insignia animado")."""
    txt = ft.Text(text, size=size, weight=ft.FontWeight.W_800, font_family=FONT_FAMILY, color="#FFFFFF")
    return ft.ShaderMask(
        content=txt,
        blend_mode=ft.BlendMode.SRC_IN,
        shader=ft.LinearGradient(
            begin=ft.Alignment.CENTER_LEFT,
            end=ft.Alignment.CENTER_RIGHT,
            colors=["#050505", "#4a4b50", "#050505"],
            stops=[0.0, 0.5, 1.0],
        ),
    )


def silver_gradient_text(text: str, size: int = 40, font_family: str = None) -> ft.ShaderMask:
    """Monograma / texto en degradado plata pulida (para el casco / "AG" del
    hero de marca)."""
    txt = ft.Text(text, size=size, weight=ft.FontWeight.W_800, font_family=font_family or FONT_FAMILY, color="#FFFFFF")
    return ft.ShaderMask(
        content=txt,
        blend_mode=ft.BlendMode.SRC_IN,
        shader=ft.LinearGradient(
            begin=ft.Alignment.CENTER_LEFT,
            end=ft.Alignment.CENTER_RIGHT,
            colors=["#0c0c0d", "#f4f5f7", "#0c0c0d"],
            stops=[0.0, 0.5, 1.0],
        ),
    )


class _BrandHeroSheen:
    """Bloque de marca grande (casco + "AG" + "INSIGNIA") con un barrido de
    luz diagonal, desvanecido en los bordes, que lo cruza de forma
    continua -- Flet no anima gradientes CSS (background-position) como
    el concepto de marca elegido ("A -- Insignia animado"), asi que el
    barrido se logra moviendo un contenedor angosto con degradado
    transparente->plata->transparente por encima del contenido, con
    `animate_position` (mismo mecanismo ya usado para las auroras del
    fondo en theme_bg.py) en vez de animar el gradiente del texto/casco
    directamente.

    OJO -- version anterior (reportada por Andres, sesion 2026-09-23):
    la primera pasada del barrido se veia perfecta, pero las siguientes
    quedaban "pegadas" en la esquina inferior derecha del bloque. La
    version anterior REUSABA el mismo Container para todas las pasadas,
    alternando su `animate_position` entre None (para el salto instantaneo
    de vuelta al punto de partida) y una Animation activa (para el
    barrido siguiente). Ese salto dependia de que el cliente (Flutter)
    dejara de usar el AnimatedPositioned anterior en ese mismo update --
    si no lo hacia (o lo hacia con un frame de retraso), el "salto"
    tambien se animaba, con la duracion vieja, dejando el control a medio
    camino cuando arrancaba la pasada siguiente. Una segunda version de
    este arreglo (crear un Container nuevo por pasada) tampoco mostraba
    ningun barrido visible en las pruebas.

    La solucion definitiva es no desactivar NUNCA `animate_position` ni
    recrear el control -- se deja siempre activo, exactamente como en la
    unica pasada que si se veia bien, y en vez de "saltar" de vuelta al
    punto de partida (lo que obligaba a apagar la animacion un instante),
    el barrido simplemente rebota: cruza hacia la derecha, despues cruza
    de vuelta hacia la izquierda, y asi sucesivamente. Es el mismo
    mecanismo ya usado en el fondo animado (theme_bg.py) para las
    'auroras', que nunca ha mostrado este problema porque tampoco apaga
    la animacion."""

    WIDTH = 340
    _SHEEN_W = 110
    _SHEEN_H = 520
    _SHEEN_DURATION_MS = 2600
    _PAUSA_ENTRE_PASADAS_S = 0.8

    def __init__(self, page: ft.Page, subtitle: str):
        self.page = page

        content = ft.Column(
            [
                ft.Image(src="helmet_hero.png", width=104, height=164, fit=ft.BoxFit.CONTAIN),
                ft.Container(height=10),
                silver_gradient_text("AG", size=44, font_family="Georgia"),
                ft.Container(height=2),
                neon_gradient_text("INSIGNIA", size=32),
                ft.Container(height=8),
                ft.Text(subtitle, size=11, color=TEXT_MUTED, text_align=ft.TextAlign.CENTER),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        )

        self._start_left = -self._SHEEN_W - 40
        self._end_left = self.WIDTH + 40

        self._sheen = ft.Container(
            width=self._SHEEN_W,
            height=self._SHEEN_H,
            left=self._start_left,
            top=-120,
            rotate=ft.Rotate(0.42),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[
                    ft.Colors.with_opacity(0.0, "#F4F5F7"),
                    ft.Colors.with_opacity(0.20, "#F4F5F7"),
                    ft.Colors.with_opacity(0.0, "#F4F5F7"),
                ],
                stops=[0.0, 0.5, 1.0],
            ),
            # SIEMPRE activo -- nunca se apaga ni se reemplaza el control
            # (ver nota de la clase arriba).
            animate_position=ft.Animation(self._SHEEN_DURATION_MS, ft.AnimationCurve.EASE_IN_OUT),
        )

        self.control = ft.Container(
            content=ft.Stack(
                [
                    ft.Container(content=content, padding=ft.Padding(28, 32, 28, 28), alignment=ft.Alignment.CENTER),
                    self._sheen,
                ],
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            ),
            width=self.WIDTH,
            alignment=ft.Alignment.CENTER,
            bgcolor=BG_DEEP,
            border_radius=18,
            border=ft.Border.all(1, GLASS_BORDER),
        )

    async def start(self):
        # Pequeña espera inicial para dar tiempo a que la pagina termine de
        # montar los controles (page.add) antes del primer .update().
        await asyncio.sleep(1.0)
        yendo_a_la_derecha = True
        while True:
            self._sheen.left = self._end_left if yendo_a_la_derecha else self._start_left
            if not self._safe_update():
                return  # la pagina/control ya no existe -- deja de intentar
            yendo_a_la_derecha = not yendo_a_la_derecha
            await asyncio.sleep(self._SHEEN_DURATION_MS / 1000 + self._PAUSA_ENTRE_PASADAS_S)

    def _safe_update(self) -> bool:
        try:
            self._sheen.update()
            return True
        except Exception:
            return False


def brand_hero(page: ft.Page, subtitle: str = "Centro de gestión ejecutiva · Ministerio de Educación Nacional") -> ft.Container:
    """Bloque de marca grande para la pantalla de Inicio (Dashboard): el
    mismo casco de la barra de tareas, el monograma "AG" y el wordmark
    "INSIGNIA" en negro brillante, con barrido de luz animado y
    desvanecido -- el concepto de marca elegido ("A -- Insignia animado")
    aplicado a la app."""
    hero = _BrandHeroSheen(page, subtitle)
    page.run_task(hero.start)
    return hero.control


def status_pill(text: str, color: str) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [
                ft.Container(width=8, height=8, bgcolor=color, border_radius=4),
                ft.Text(text, size=12, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
            ],
            spacing=6,
            tight=True,
        ),
        padding=ft.Padding(10, 6, 12, 6),
        bgcolor=ft.Colors.with_opacity(0.08, color),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.35, color)),
        border_radius=20,
    )


_LOG_ICONS = {
    SUCCESS: ft.Icons.CHECK_CIRCLE,
    ERROR: ft.Icons.ERROR,
    WARNING: ft.Icons.WARNING_AMBER,
    ACCENT_CYAN: ft.Icons.BOLT,
}


def log_result_card(text: str, color: str = None) -> ft.Container:
    """Recuadro 'tactil' para un resultado de procesamiento masivo: vidrio
    translucido, brillo suave en las esquinas segun el estado (exito /
    error / alerta / info), y arranca invisible + desplazado para que
    quien lo agregue pueda revelarlo con una pequeña animacion tipo
    'escalon' (ver reveal_log_card)."""
    color = color or TEXT_SECONDARY
    icon = _LOG_ICONS.get(color, ft.Icons.CIRCLE)
    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(icon, size=13, color=color),
                ft.Text(text, size=11.5, color=TEXT_PRIMARY, font_family="Consolas", expand=True),
            ],
            spacing=8,
        ),
        padding=ft.Padding(10, 7, 10, 7),
        margin=ft.Margin(0, 0, 0, 4),
        bgcolor=ft.Colors.with_opacity(0.045, "#FFFFFF"),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.18, color)),
        border_radius=10,
        shadow=[
            ft.BoxShadow(blur_radius=12, spread_radius=-6, color=ft.Colors.with_opacity(0.55, color), offset=ft.Offset(-2, -2)),
            ft.BoxShadow(blur_radius=12, spread_radius=-6, color=ft.Colors.with_opacity(0.55, color), offset=ft.Offset(2, 2)),
        ],
        opacity=0,
        scale=0.85,
        offset=ft.Offset(0.10, -0.22),
        animate_opacity=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
        animate_scale=ft.Animation(340, ft.AnimationCurve.EASE_OUT_BACK),
        animate_offset=ft.Animation(340, ft.AnimationCurve.EASE_OUT_BACK),
    )


def reveal_log_card(card: ft.Container) -> None:
    """Dispara la animacion de entrada tipo 'escalon' de una tarjeta creada
    con log_result_card: se llama un instante despues de agregarla a la
    lista, para que el cambio de opacity/scale/offset se anime en vez de
    aparecer de golpe."""
    card.opacity = 1
    card.scale = 1
    card.offset = ft.Offset(0, 0)


def nav_button(label: str, icon: str, selected: bool, on_click) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [ft.Icon(icon, size=17, color=ACCENT_CYAN if selected else TEXT_MUTED),
             ft.Text(label, size=13, weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_400,
                      color=TEXT_PRIMARY if selected else TEXT_SECONDARY, font_family=FONT_FAMILY)],
            spacing=8,
        ),
        padding=ft.Padding(16, 11, 16, 11),
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.10, ACCENT_CYAN) if selected else ft.Colors.TRANSPARENT,
        border=ft.Border.all(1, GLASS_BORDER) if selected else ft.Border.all(1, ft.Colors.TRANSPARENT),
        on_click=on_click,
        ink=True,
        animate=ft.Animation(160, ft.AnimationCurve.EASE_OUT),
    )

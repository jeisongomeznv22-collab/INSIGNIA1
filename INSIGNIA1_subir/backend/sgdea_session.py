"""
Cliente de sesion PROPIA (Playwright, navegador propio -- mismo patron que
backend/legacy_portal_client.py) para SGDEA/TMS (sgdea.mineducacion.gov.co).

A diferencia de sgdea_automation.conectar_chrome_existente() (que se
conecta via CDP al Chrome que Andres YA tiene abierto y en el que YA
inicio sesion el mismo -- por eso depende de que su Chrome este abierto,
en el tamaño de ventana correcto, y no se mueva), este cliente abre su
PROPIO Chromium e inicia sesion EL MISMO con usuario/clave guardados --
pedido explicito de Andres (sesion 2026-09-24): "que el aplicativo sea
capaz de conectarse con SGDEA de la misma forma que lo hace con los 472
... inicio sesión desde adentro y el pueda tomar todos los casos que
lleguen ... entrar a cada caso, realizar el proceso de gestión
automatizada ... y dejar una alerta ... (PARA APROBAR)".

Ventaja estructural, ademas de la independencia del Chrome de Andres: al
lanzar el navegador con un viewport FIJO (VIEWPORT_SGDEA, abajo) en vez de
depender del tamaño/posicion de la ventana de Chrome de Andres (que
cambiaba todo el tiempo en esta sesion y rompia las coordenadas de pegado
ya calibradas -- ver backend/sgdea_automation.py), las coordenadas quedan
estables para siempre una vez calibradas UNA SOLA VEZ contra este tamaño
fijo, sin importar la pantalla/monitor del equipo.

Confirmado por Andres (sesion 2026-09-24):
  - SGDEA SI tolera varias sesiones simultaneas del mismo usuario -- el
    mismo Andres trabaja a la vez desde su PC del trabajo, en el mismo
    perfil de SGDEA, mientras se probaba este cliente. La sesion solo
    expira por inactividad LARGA, no por un segundo login. Por eso
    `mantener_viva()` (re-navegar al tablero periodicamente) alcanza
    para que nunca expire mientras la app siga corriendo -- Andres
    confirmo que el boton de refrescar del tablero "sirve" para esto.
  - URL de login (compartida por Andres, con captura de pantalla real):
    ver LOGIN_URL abajo. Redirige a una pantalla "Iniciar sesión por
    dominio" (branding GOV.CO) con dos campos CON LABEL VISIBLE real
    ("Usuario" y "Contraseña" -- a diferencia del portal 4-72 legacy,
    donde ningun label/placeholder era localizable) y un boton "INICIAR
    SESIÓN". SIN CAPTCHA -- confirmado explicitamente por Andres ("prueba
    de que no tiene recapchat"), con captura de la pantalla de login.

NO CONFIRMADO EN VIVO todavia (pendiente de la primera corrida real,
supervisada por Andres -- igual disciplina que el resto del proyecto:
nunca se asume que algo nuevo funciona solo porque "deberia"):
  - Que el login funcione tal cual esta escrito aqui contra el DOM real
    (se intenta primero por label visible, ya que la captura de Andres
    muestra labels normales; se cae al mismo heuristico generico de
    legacy_portal_client.py -- password input visible + input de texto
    anterior -- como respaldo).
  - Que las coordenadas YA calibradas de Saludo/Cuerpo (config_472.json,
    calibradas 2026-09-24 contra el Chrome normal de Andres) sigan
    sirviendo contra el viewport fijo de este cliente -- MUY PROBABLE
    que NO, porque se calibraron contra un tamaño de ventana distinto.
    Hay que recalibrar UNA VEZ, usando el panel de "Calibración del
    editor" ya existente, con este cliente conectado.
  - El icono/URL exactos de "refrescar" del tablero -- por ahora
    mantener_viva() simplemente vuelve a navegar a TABLERO_URL, que
    Andres confirmo que sirve tanto para traer casos nuevos como para
    mantener la sesion viva.

Misma disciplina de seguridad que el resto del proyecto: este modulo
NUNCA intenta resolver un CAPTCHA (lanza SgdeaLoginError con mensaje
claro si detecta uno) y NUNCA hace nada mas que loguearse y navegar --
gestionar casos, pegar texto, etc. sigue siendo responsabilidad exclusiva
de backend/sgdea_automation.py (que recibe la `page` ya lista desde aqui).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PwTimeoutError,
)


BASE_URL = "https://sgdea.mineducacion.gov.co"

# Confirmada por Andres (sesion 2026-09-24, link + captura de pantalla
# reales de su login). El segmento "(SwgUB8M7)" parece un identificador
# de instalacion/entorno de la solucion TMS (aparece igual en la URL del
# tablero que Andres tambien compartio) -- si algun dia deja de funcionar,
# es el primer lugar donde revisar.
LOGIN_URL = (
    "https://sgdea.mineducacion.gov.co/TMS.Solution.MENGESDOC/(SwgUB8M7)"
    "/CR/es//Home/Corporativo"
)

# Vista "Tablero mis asignadas" (Inicio) -- misma URL que aparecia en la
# barra de Chrome de Andres estando en "Inicio - Mis asignadas". Se usa
# tanto para confirmar que el login funciono como para refrescar/mantener
# viva la sesion.
TABLERO_URL = (
    "https://sgdea.mineducacion.gov.co/TMS.Solution.MENGESDOC/(SwgUB8M7)"
    "/CR/es/MaM/TableroUsuario"
)

# Viewport FIJO para esta sesion propia -- a diferencia del Chrome de
# Andres (cuyo tamaño cambiaba constantemente durante esta sesion y rompia
# las coordenadas de pegado calibradas), este navegador SIEMPRE se abre
# con este mismo tamaño exacto, sin importar la pantalla/monitor del
# equipo. Las coordenadas calibradas (Saludo/Cuerpo, y cualquier otra que
# se calibre a futuro, como el bloque "Gestionar" del dashboard) solo
# sirven mientras este valor no cambie -- si algun dia hace falta uno
# distinto, hay que recalibrar todo de nuevo.
VIEWPORT_SGDEA = {"width": 1366, "height": 850}


class SgdeaSessionError(Exception):
    """Error generico al automatizar la sesion propia de SGDEA."""


class SgdeaLoginError(SgdeaSessionError):
    """No se pudo iniciar sesion (credenciales invalidas, CAPTCHA
    inesperado, cambio en el formulario de login, etc)."""


@dataclass
class SgdeaSessionClient:
    usuario: str
    password: str
    # Visible por defecto (igual que LegacyPortalClient): si algo raro
    # pasa (ej. un CAPTCHA no detectado por el heuristico), Andres puede
    # verlo y resolverlo el mismo en vez de que la automatizacion se
    # cuelgue a ciegas en segundo plano.
    headless: bool = False
    timeout_ms: int = 30000

    _playwright: object = field(default=None, init=False, repr=False)
    _browser: Optional[Browser] = field(default=None, init=False, repr=False)
    _context: Optional[BrowserContext] = field(default=None, init=False, repr=False)
    _page: Optional[Page] = field(default=None, init=False, repr=False)
    _logueado: bool = field(default=False, init=False, repr=False)

    @property
    def conectado(self) -> bool:
        return self._logueado and self._page is not None

    @property
    def pagina(self) -> Page:
        if not self.conectado:
            raise SgdeaSessionError(
                "La sesion propia de SGDEA no esta conectada -- llama a "
                "iniciar() primero (o conecta desde Configuración)."
            )
        return self._page

    async def iniciar(self, on_progreso: Optional[Callable[[str], Awaitable[None]]] = None) -> None:
        """Lanza un Chromium propio (independiente del Chrome de Andres)
        con viewport fijo (VIEWPORT_SGDEA) y hace login. Idempotente: si
        ya esta logueado, no hace nada -- llamar cerrar() primero para
        forzar un login nuevo (ej. con otro usuario)."""
        if self._logueado:
            return
        if on_progreso:
            await on_progreso("Abriendo navegador propio de SGDEA...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(viewport=VIEWPORT_SGDEA, accept_downloads=True)
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        if on_progreso:
            await on_progreso("Iniciando sesión en SGDEA...")
        await self._login()

    async def cerrar(self) -> None:
        """Cierra navegador y playwright de forma segura. A diferencia de
        sgdea_automation.py (que se conecta via CDP al Chrome REAL de
        Andres y por eso NUNCA puede llamar browser.close()), este
        navegador es 100% propio: cerrarlo aqui es seguro y correcto, no
        afecta el Chrome personal de Andres para nada."""
        try:
            if self._context is not None:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser is not None:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._logueado = False

    async def mantener_viva(self) -> None:
        """Vuelve a navegar al tablero de 'Inicio - Mis asignadas'.
        Andres confirmo (sesion 2026-09-24) que esto alcanza para que la
        sesion nunca expire por inactividad mientras la app siga
        corriendo, y de paso deja la pagina lista para
        detectar_casos_nuevos()/listar_casos_gestionar(). No lanza error
        si no esta conectada (no-op)."""
        if not self.conectado:
            return
        await self._page.goto(TABLERO_URL, wait_until="domcontentloaded")

    async def __aenter__(self) -> "SgdeaSessionClient":
        await self.iniciar()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.cerrar()

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------
    async def _login(self) -> None:
        page = self._page
        assert page is not None
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")

        ctx, password_input, usuario_input = await self._ubicar_form_login()
        if ctx is None:
            diagnostico = await self._diagnosticar_pagina_login()
            raise SgdeaLoginError(
                "No se encontro el formulario de login de SGDEA en "
                f"{LOGIN_URL!r} (¿cambio la pagina?). Diagnostico: {diagnostico}"
            )

        await usuario_input.fill(self.usuario)
        await password_input.fill(self.password)

        # Deteccion basica de CAPTCHA (Andres confirmo que hoy esta
        # pantalla NO lo pide, con captura de pantalla como prueba, pero
        # se deja el mismo heuristico que legacy_portal_client.py por si
        # cambia en el futuro). Nunca se intenta resolver.
        if (
            await ctx.locator("text=/captcha/i").count() > 0
            or await ctx.locator(
                "img[src*='captcha' i], iframe[src*='recaptcha' i], [class*='captcha' i]"
            ).count() > 0
        ):
            raise SgdeaLoginError(
                "SGDEA esta pidiendo resolver un CAPTCHA en el login. Este "
                "automatizador nunca intenta resolverlo: resuelvelo "
                "manualmente (el navegador queda visible, headless=False) "
                "y vuelve a intentar."
            )

        await ctx.get_by_role("button", name=re.compile("iniciar sesi", re.I)).click()

        try:
            await page.wait_for_url(re.compile(r"TableroUsuario|/MaM/|/Home/"), timeout=self.timeout_ms)
        except PwTimeoutError:
            texto_error = ""
            try:
                texto_error = (await page.locator("body").inner_text())[:400]
            except Exception:
                pass
            raise SgdeaLoginError(
                "El login no salio de la pantalla de 'Iniciar sesión por "
                "dominio' -- probablemente usuario/clave incorrectos, o "
                "cambio el flujo de navegacion tras el login. Texto "
                f"visible en la pagina: {texto_error!r}"
            )

        self._logueado = True

    async def _ubicar_form_login(self):
        """Misma tecnica que LegacyPortalClient._ubicar_form_login():
        busca el input de password (y, junto a el, el de usuario) tanto
        en el frame principal como en cada iframe, reintentando con
        sondeos cortos durante self.timeout_ms.

        A diferencia del portal 4-72 legacy (donde ningun label era
        localizable), la captura de Andres muestra labels reales
        ('Usuario'/'Contraseña') -- se intenta primero por label visible
        (mas preciso si existe) y se cae al heuristico generico (primer
        input de password visible + primer input de texto visible
        anterior) como respaldo si el label no se encuentra."""
        page = self._page
        assert page is not None
        intentos = max(1, self.timeout_ms // 500)
        for _ in range(intentos):
            candidatos = [page, *page.frames]
            for ctx in candidatos:
                try:
                    password_por_label = ctx.get_by_label(re.compile("contrase", re.I))
                    if await password_por_label.count() > 0 and await password_por_label.first.is_visible():
                        usuario_por_label = ctx.get_by_label(re.compile("usuario", re.I))
                        if await usuario_por_label.count() > 0 and await usuario_por_label.first.is_visible():
                            return ctx, password_por_label.first, usuario_por_label.first
                except Exception:
                    pass
                try:
                    password_input = ctx.locator('input[type="password"]:visible').first
                    if await password_input.count() > 0 and await password_input.is_visible():
                        usuario_input = ctx.locator(
                            'input:visible:not([type="password"]):not([type="hidden"])'
                            ':not([type="submit"]):not([type="button"])'
                        ).first
                        return ctx, password_input, usuario_input
                except Exception:
                    continue
            await page.wait_for_timeout(500)
        return None, None, None

    async def _diagnosticar_pagina_login(self) -> str:
        page = self._page
        assert page is not None
        partes = []
        try:
            partes.append(f"{len(page.frames)} frame(s): " + ", ".join(f.url for f in page.frames))
        except Exception:
            pass
        for i, ctx in enumerate([page, *page.frames]):
            try:
                total_inputs = await ctx.locator("input").count()
                total_pass = await ctx.locator('input[type="password"]').count()
                partes.append(f"[ctx{i}] inputs={total_inputs} password={total_pass}")
            except Exception:
                partes.append(f"[ctx{i}] (no se pudo inspeccionar)")
        return " | ".join(partes) if partes else "(sin datos)"

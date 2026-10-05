"""
Cliente de automatizacion (Playwright, navegador propio) para el portal
ANTIGUO de correo certificado 4-72:
    https://mineducacion.correocertificado4-72.com.co

A diferencia de PortalClient (portal_client.py), que habla con la API REST
del portal NUEVO (almacenamiento472.verificaia.com) via `requests`, este
portal antiguo es una aplicacion web tradicional (server-rendered), sin API
publica conocida. Por eso este cliente controla un navegador Chromium
PROPIO (no el Chrome de Andres, a diferencia de sgdea_automation.py, que se
conecta via CDP al navegador ya abierto) y hace login automatico con
usuario/clave guardados -- decision explicita de Andres (2026-09), pese al
riesgo de CAPTCHA mencionado en los comentarios de local_zip.py.

Este portal contiene todos los actos administrativos notificados HASTA el
31 de mayo de 2026 (despues de esa fecha, todo pasa por el portal nuevo /
PortalClient).

Flujo por cada ID del Excel masivo (ver main.py, seccion "Masivo"):
  1. iniciar() -- una sola vez por sesion de procesamiento (abre el
     navegador y hace login).
  2. buscar_y_descargar_testigo(message_id, email_destinatario=None) ->
     bytes del PDF ("testigo") descargado, listo para pasar a
     extractor.extract_acuse_from_pdf(pdf_bytes, origen) -- pipeline que
     YA EXISTE y no requiere cambios (fue escrito precisamente para acuses
     de "otro portal que exige captcha, descargados uno por uno").
  3. cerrar() -- al terminar el lote (o usar `async with LegacyPortalClient(...) as c:`).

CONFIRMADO EN VIVO (pantallazos reales de Andres, 2026-09-23):
  - index.php: dos campos de texto con placeholder "Usuario" y
    "Contrasena" (sin <label> separado visible), boton azul "INGRESAR".
    Sin ningun captcha visible en esta pantalla de login.
  - Tras un login exitoso, el portal NO cae directo en status.php: cae en
    home.php ("Datos personales" del suscriptor). El camino manual
    confirmado por Andres para llegar a la bandeja es: click en el menu
    "Estado mensajes" (arriba) -> click en la opcion "Correo" del
    desplegable -> eso navega a status.php. Por eso, tras el login, este
    cliente primero intenta ir DIRECTO a status.php (mas simple y
    confirmado que funciona por URL si la cookie de sesion ya es valida);
    si esa pagina no trae el formulario de busqueda esperado, cae de
    vuelta al camino de menu confirmado por Andres (Estado mensajes ->
    Correo) como respaldo.
  - status.php, con "Filtros avanzados" desplegado (link "Filtros
    avanzados" -> click para abrir el panel): trae, entre otros, un input
    con LABEL VISIBLE "Identificador del mensaje", un input "Email
    destinatario" (estilo placeholder, junto a "Nombre destinatario"), y
    DOS inputs de fecha en la misma fila que "Identificador del mensaje"
    (ej. "2026-01-01" y "2026-08-31" por defecto) que delimitan el rango
    de busqueda. Andres confirmo que el segundo (fecha limite superior)
    debe fijarse en "2026-05-31", ya que el portal antiguo solo tiene
    actos notificados hasta esa fecha.
  - La tabla de resultados: columna "Traza" con exactamente DOS iconos
    azules por fila -- un sobre/correo (primero) y un documento
    (segundo) -- confirmando la suposicion de tomar el ULTIMO icono
    clicable de la fila como el que abre el detalle de traza.

CONFIRMADO EN VIVO, LO MAS IMPORTANTE (corridas reales, 2026-09-23): en
este portal, "Usuario", "Contrasena", "Identificador del mensaje" y
"Fecha de envio hasta" se VEN como placeholders/labels pero NINGUNO es un
atributo `placeholder` ni un `<label>` real que Playwright pueda ubicar
por texto (get_by_placeholder/get_by_label fallaron las 3 veces que se
probaron en vivo, uno por uno). Por eso, para el panel de "Filtros
avanzados", este cliente abandona la busqueda por texto y ubica los
campos por POSICION dentro del contenedor con id "collapseOne" (id
confirmado: aparecio en la URL al pasar el mouse sobre el link "Filtros
avanzados" -> status.php#collapseOne), contando solo los inputs VISIBLES
que no sean de tipo hidden, en el orden que se ve igual en todas las
capturas de Andres:
    0: Nombre destinatario
    1: Email destinatario
    2: Identificador del mensaje
    3: Fecha desde (ya trae un valor, ej. "2026-01-01")
    4: Fecha hasta (a veces vacia, a veces con un valor -- aqui se fija
       en "2026-05-31" porque el portal antiguo solo tiene actos
       notificados hasta esa fecha)
    5: Valor del metadato
Ver PORTAL_FILTROS_INDICES / _campo_filtros_avanzados() mas abajo.

NO CONFIRMADO EN VIVO -- pendiente de calibracion contra el HTML real (no
hay acceso al DOM crudo, solo a las capturas de pantalla):
  - Si los inputs de fecha son campos de texto simples (aceptan .fill())
    o widgets de datepicker de JS que requieren otra interaccion (ya se
    confirmo que hace falta click + escribir, no fill() directo).
  - El boton "Buscar" y el link "Filtros avanzados" (se asume que hace
    falta abrir el panel antes de poder ver/llenar "Identificador del
    mensaje").
  - El modal "Detalle traza": texto/link "Descargar testigo" que dispara
    la descarga del PDF; boton "Aceptar" para cerrarlo despues.
  - Si el orden de los campos dentro de "collapseOne" cambia con el
    tamano de pantalla u otra condicion, los indices de arriba dejarian
    de ser validos -- si eso pasa, hay que volver a confirmar el orden
    con una captura nueva.

Regla del proyecto (igual que en sgdea_automation.py): este cliente NUNCA
intenta resolver ni saltarse un CAPTCHA. Si detecta uno en el login, lanza
LegacyLoginError con un mensaje claro para que Andres lo resuelva a mano.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PwTimeoutError,
)


BASE_URL = "https://mineducacion.correocertificado4-72.com.co"

# CONFIRMADO: contenedor del panel "Filtros avanzados" (visto en la URL de
# hover sobre ese link: status.php#collapseOne).
FILTROS_PANEL_SELECTOR = "#collapseOne"

# CONFIRMADO (orden visual, igual en todas las capturas de Andres):
# posicion (0-based) de cada campo entre los inputs VISIBLES y no-hidden
# dentro de FILTROS_PANEL_SELECTOR.
IDX_NOMBRE_DESTINATARIO = 0
IDX_EMAIL_DESTINATARIO = 1
IDX_IDENTIFICADOR_MENSAJE = 2
IDX_FECHA_DESDE = 3
IDX_FECHA_HASTA = 4
IDX_VALOR_METADATO = 5


class LegacyPortalError(Exception):
    """Error generico al automatizar el portal antiguo (4-72 legacy)."""


class LegacyLoginError(LegacyPortalError):
    """No se pudo iniciar sesion (credenciales invalidas, CAPTCHA, cambio
    en el formulario, etc)."""


class LegacyNotFoundError(LegacyPortalError):
    """La busqueda por ID (y, si aplica, por email) no arrojo ninguna fila
    coincidente en la tabla de resultados."""


def _instalar_chromium_bloqueante() -> tuple[bool, str]:
    """Corre el instalador de Chromium de Playwright ("playwright install
    chromium") de forma BLOQUEANTE -- SIEMPRE se llama via
    asyncio.to_thread(), nunca directo desde una corrutina.

    Para que: hasta ahora, para usar el portal antiguo en un PC nuevo
    hacia falta copiar Insignia.exe Y ADEMAS correr instalar_playwright.bat
    a mano en ese equipo (que a su vez necesitaba tener Python instalado
    alli). Pedido de Andres (2026-09-24): que Insignia.exe funcione en
    cualquier PC "sin tener que instalar nada". Esta funcion invoca el
    propio CLI de Playwright ("playwright install chromium") pero como
    llamada de Python normal (no como subproceso "python -m playwright
    ..."), usando el paquete playwright que YA viaja empacado DENTRO de
    Insignia.exe -- por eso no hace falta Python del sistema en el equipo
    nuevo, solo conexion a internet para la descarga (~300 MB) la PRIMERA
    vez que se usa el portal antiguo alli. Una vez descargado queda
    cacheado en %LOCALAPPDATA%\\ms-playwright de ESE equipo, igual que
    antes con el .bat -- en corridas siguientes (o en el PC de Andres,
    donde ya esta instalado) esta funcion ni se llama (ver
    _asegurar_chromium: solo se invoca si el ejecutable no esta ya ahi).

    CONFIRMADO Y CORREGIDO (2026-09-24): probado en vivo contra un PC nuevo
    (equipo de trabajo de Andres, jegomez) -- la descarga SI corria (se veia
    la ventana negra de progreso), pero al conectar fallaba con "Executable
    doesn't exist at ...\\AppData\\Local\\Temp\\_MEIxxxxxx\\playwright\\driver\\
    package\\.local-browsers\\...". Causa: sin fijar PLAYWRIGHT_BROWSERS_PATH,
    Playwright empaquetado con PyInstaller instala/busca el navegador DENTRO
    de la carpeta temporal donde PyInstaller extrae el .exe en cada corrida
    (_MEIxxxxxx), que se borra al cerrar la app -- por eso funcionaba una vez
    y luego ya no encontraba el ejecutable. Arreglo: main.py fija
    PLAYWRIGHT_BROWSERS_PATH a "%LOCALAPPDATA%\\ms-playwright" ANTES de
    importar playwright, para que tanto esta instalacion como el lanzamiento
    (_asegurar_chromium / chromium.launch) usen siempre esa misma carpeta
    estable del usuario, igual que una instalacion no empaquetada.

    Devuelve (exito, texto_de_salida_para_diagnostico)."""
    from playwright.__main__ import main as _playwright_cli_main

    argv_original = sys.argv
    sys.argv = ["playwright", "install", "chromium"]
    buffer_salida = io.StringIO()
    codigo_salida = 0
    try:
        with contextlib.redirect_stdout(buffer_salida), contextlib.redirect_stderr(buffer_salida):
            _playwright_cli_main()
    except SystemExit as exc:
        # El CLI de Playwright (basado en Click) termina SIEMPRE con
        # sys.exit(), incluso cuando todo sale bien (codigo 0) -- por eso
        # SystemExit se captura aqui como flujo NORMAL, no como error.
        codigo_salida = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except Exception as exc:  # noqa: BLE001
        return False, f"{buffer_salida.getvalue()}\n{type(exc).__name__}: {exc}"
    finally:
        sys.argv = argv_original
    return codigo_salida == 0, buffer_salida.getvalue()


def _target_url(pagina: str) -> str:
    """Construye la URL de login que, tras autenticar, redirige a `pagina`.

    CONFIRMADO: el parametro ?r= de index.php es el nombre de la pagina
    destino codificado en base64 (ej. "status.php" ->
    "c3RhdHVzLnBocA==", verificado contra un pantallazo real de Andres
    del 2026-09-23)."""
    token = base64.b64encode(pagina.encode("utf-8")).decode("ascii")
    return f"{BASE_URL}/index.php?r={token}"


LOGIN_URL = _target_url("status.php")
STATUS_URL = f"{BASE_URL}/status.php"


@dataclass
class LegacyPortalClient:
    usuario: str
    password: str
    # Se lanza con ventana visible por defecto: si algo raro pasa (ej. un
    # CAPTCHA no detectado por el heuristico de abajo), Andres puede verlo
    # y resolverlo el mismo en lugar de que la automatizacion se cuelgue
    # a ciegas en segundo plano.
    headless: bool = False
    timeout_ms: int = 30000

    _playwright: object = field(default=None, init=False, repr=False)
    _browser: Optional[Browser] = field(default=None, init=False, repr=False)
    _context: Optional[BrowserContext] = field(default=None, init=False, repr=False)
    _page: Optional[Page] = field(default=None, init=False, repr=False)
    _logueado: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    async def iniciar(
        self, on_progreso: Optional[Callable[[str], Awaitable[None]]] = None
    ) -> None:
        """Lanza un Chromium propio (independiente del Chrome de Andres)
        y hace login. Idempotente: si ya esta logueado, no hace nada.
        Llamar una sola vez antes de procesar el lote; usar cerrar() al
        terminar (o el patron `async with`).

        `on_progreso`: callback async opcional, llamado con un texto corto
        cuando hay algo que vale la pena mostrar en la UI mientras se
        conecta (por ahora, solo se usa durante la descarga automatica de
        Chromium en un equipo nuevo -- ver _asegurar_chromium)."""
        if self._logueado:
            return
        self._playwright = await async_playwright().start()
        await self._asegurar_chromium(on_progreso)
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(accept_downloads=True)
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        await self._login()

    async def _asegurar_chromium(
        self, on_progreso: Optional[Callable[[str], Awaitable[None]]] = None
    ) -> None:
        """Descarga el Chromium que Playwright necesita si este equipo
        todavia no lo tiene -- para que Insignia.exe funcione en un PC
        nuevo sin ningun paso manual aparte (ver docstring de
        _instalar_chromium_bloqueante para el detalle completo).

        Primero revisa si el ejecutable esperado ya existe (rapido, sin
        descargar nada) -- en el PC de Andres, donde ya se instalo con
        instalar_playwright.bat, esto siempre sale por aqui sin demora
        ninguna. Solo dispara la descarga (~300 MB, puede tardar varios
        minutos) si de verdad hace falta."""
        try:
            ruta_exe = self._playwright.chromium.executable_path
        except Exception:
            ruta_exe = None
        if ruta_exe and Path(ruta_exe).exists():
            return  # ya esta instalado en este equipo -- nada que hacer

        if on_progreso:
            await on_progreso(
                "Descargando el navegador Chromium (primera vez en este "
                "equipo; puede tardar varios minutos segun la conexion)..."
            )
        exito, salida = await asyncio.to_thread(_instalar_chromium_bloqueante)
        if not exito:
            raise LegacyPortalError(
                "No se pudo descargar automaticamente el navegador Chromium "
                "que necesita el portal antiguo. Revisa la conexion a "
                f"internet de este equipo e intenta de nuevo. Detalle: "
                f"{salida[-500:] if salida else '(sin detalle)'}"
            )
        if on_progreso:
            await on_progreso("Navegador descargado. Conectando...")

    async def cerrar(self) -> None:
        """Cierra navegador y playwright de forma segura. No lanza error
        si ya estaba cerrado o nunca se inicio."""
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

    async def abrir_pagina_trabajo(self) -> Page:
        """Abre una pestana NUEVA dentro del MISMO navegador/sesion ya
        logueada (comparte las cookies via self._context -- no hace falta
        loguearse de nuevo) y la deja lista en status.php con "Filtros
        avanzados" abierto.

        Para que: procesar un lote grande (1000+ IDs) en serie, una
        busqueda a la vez, tardaba ~1 minuto por ID (segun corrida real de
        Andres) -- inviable para lotes grandes. Abriendo varias pestanas
        de este tipo y repartiendo los IDs entre ellas (ver
        procesar_masivo_legacy en main.py), las busquedas/descargas corren
        EN PARALELO y el tiempo total baja proporcionalmente a la cantidad
        de pestanas usadas.

        Cuantas pestanas abrir a la vez es un balance: mas pestanas = mas
        rapido, pero tambien mas carga simultanea contra el portal (mayor
        riesgo de que active algun limite de tasa o CAPTCHA que no tenia
        con una sola sesion secuencial) -- NOT CONFIRMED cuantas tolera
        este portal en concreto; se arranca con un numero moderado (ver
        MAX_WORKERS_LEGACY en main.py) y se puede ajustar segun resultado
        real."""
        if self._context is None or not self._logueado:
            raise LegacyPortalError(
                "Llama a iniciar() antes de abrir pestanas de trabajo."
            )
        pagina = await self._context.new_page()
        pagina.set_default_timeout(self.timeout_ms)
        await self._ir_a_status(pagina)
        return pagina

    async def __aenter__(self) -> "LegacyPortalClient":
        await self.iniciar()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.cerrar()

    # ------------------------------------------------------------------
    # Login (CONFIRMADO en vivo -- ver docstring del modulo)
    # ------------------------------------------------------------------
    async def _login(self) -> None:
        page = self._page
        assert page is not None
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")

        # El formulario podria estar embebido en un iframe (el logo
        # "SealMail" al pie de la pagina sugiere un widget de terceros) --
        # por eso se busca el input de password tanto en el frame principal
        # como en cada iframe, no solo en `page` directamente. Reintenta
        # con sondeos cortos durante el tiempo de espera configurado, por
        # si el iframe tarda en cargar.
        ctx, password_input, usuario_input = await self._ubicar_form_login()
        if ctx is None:
            diagnostico = await self._diagnosticar_pagina_login()
            raise LegacyLoginError(
                "No se encontro el formulario de login en index.php "
                "(¿cambio la pagina, hay un iframe no contemplado, o algo "
                f"la esta bloqueando?). Diagnostico: {diagnostico}"
            )

        await usuario_input.fill(self.usuario)
        await password_input.fill(self.password)

        # Deteccion basica de CAPTCHA antes de enviar. Nunca se intenta
        # resolver -- solo se informa con un error claro para que Andres
        # lo resuelva a mano.
        if (
            await ctx.locator("text=/captcha/i").count() > 0
            or await ctx.locator(
                "img[src*='captcha' i], iframe[src*='recaptcha' i], "
                "[class*='captcha' i]"
            ).count()
            > 0
        ):
            raise LegacyLoginError(
                "El portal antiguo esta pidiendo resolver un CAPTCHA en el "
                "login. Este automatizador nunca intenta resolverlo: "
                "resuelvelo manualmente en el navegador (dejalo visible, "
                "headless=False) y vuelve a intentar."
            )

        await ctx.get_by_role("button", name=re.compile("ingresar", re.I)).click()

        # CONFIRMADO: un login exitoso cae en home.php ("Datos personales"
        # del suscriptor), NO directo en status.php. Se detecta el exito
        # esperando a salir de index.php (o a que aparezca el menu "Estado
        # mensajes", que solo esta presente ya logueado).
        try:
            await page.wait_for_url(re.compile(r"(home|status)\.php"), timeout=self.timeout_ms)
        except PwTimeoutError:
            texto_error = ""
            try:
                texto_error = (await page.locator("body").inner_text())[:400]
            except Exception:
                pass
            raise LegacyLoginError(
                "El login no salio de index.php -- probablemente "
                "usuario/clave incorrectos, o aparecio un CAPTCHA que el "
                "heuristico anterior no detecto. "
                f"Texto visible en la pagina: {texto_error!r}"
            )

        self._logueado = True

    async def _ubicar_form_login(self):
        """Busca el input de password (y, junto a el, el de usuario) tanto
        en el frame principal de la pagina como en cada iframe que tenga,
        reintentando con sondeos cortos durante self.timeout_ms.

        Devuelve (contexto, password_input, usuario_input), donde
        `contexto` es `self._page` o el `Frame` donde vive el formulario
        (todos los locators posteriores del login deben salir de ese mismo
        contexto). Si no encuentra nada, devuelve (None, None, None)."""
        page = self._page
        assert page is not None
        intentos = max(1, self.timeout_ms // 500)
        for _ in range(intentos):
            candidatos = [page, *page.frames]
            for ctx in candidatos:
                try:
                    password_input = ctx.locator('input[type="password"]:visible').first
                    if await password_input.count() > 0 and await password_input.is_visible():
                        # CONFIRMADO en vivo (2026-09-23): sin ":visible" esto
                        # tambien puede resolver a un input oculto que no es
                        # type=hidden (ej. <input id="language" hidden=...>,
                        # un selector de idioma) -- por eso se exige visible.
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
        """Arma un resumen corto de lo que SI se encontro en la pagina de
        login, para no quedar a ciegas si _ubicar_form_login() falla (ej.
        cuantos frames hay, cuantos inputs de cada tipo, etc)."""
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

    # ------------------------------------------------------------------
    # Navegacion a la bandeja de busqueda (status.php)
    # ------------------------------------------------------------------
    async def _ir_a_status(self, page: Page) -> None:
        """Deja `page` posicionada en status.php con el formulario de
        busqueda visible.

        CONFIRMADO (camino manual, pantallazo de Andres): tras el login se
        cae en home.php; para llegar a la bandeja hay que abrir el menu
        "Estado mensajes" (arriba) y hacer click en "Correo".

        Intenta primero ir DIRECTO por URL (mas simple, y el link "Correo"
        del menu efectivamente apunta a status.php) y solo si esa pagina no
        trae el formulario esperado, cae al camino de menu confirmado por
        Andres como respaldo.

        Recibe `page` explicitamente (en vez de usar self._page fijo) para
        poder posicionar VARIAS pestanas del mismo navegador/sesion en
        paralelo -- cada pestana comparte las cookies de sesion (mismo
        `self._context`) pero tiene su propio DOM/estado independiente."""

        async def _formulario_visible() -> bool:
            campo = await self._campo_filtros_avanzados(page, IDX_IDENTIFICADOR_MENSAJE)
            try:
                return await campo.count() > 0 and await campo.is_visible()
            except Exception:
                return False

        if page.url.split("?")[0].rstrip("/") != STATUS_URL:
            await page.goto(STATUS_URL, wait_until="domcontentloaded")

        # El formulario de "Identificador del mensaje" vive dentro de
        # "Filtros avanzados" (colapsado por defecto) -- se abre si hace
        # falta, antes de decidir si tambien hace falta el camino de menu.
        await self._abrir_filtros_avanzados(page)
        if await _formulario_visible():
            return

        # Respaldo: camino de menu confirmado por Andres.
        await page.get_by_role("button", name=re.compile("estado mensajes", re.I)).or_(
            page.get_by_text(re.compile("estado mensajes", re.I))
        ).first.click()
        await page.get_by_role("link", name=re.compile("^correo$", re.I)).or_(
            page.get_by_text(re.compile("^correo$", re.I))
        ).first.click()
        await page.wait_for_url(re.compile(r"status\.php"), timeout=self.timeout_ms)
        await self._abrir_filtros_avanzados(page)

        if not await _formulario_visible():
            raise LegacyPortalError(
                "Se llego a status.php pero no aparece el campo "
                "'Identificador del mensaje' esperado (hace falta "
                "recalibrar selectores)."
            )

    async def _abrir_filtros_avanzados(self, page: Page) -> None:
        """Abre el panel colapsable "Filtros avanzados" si esta cerrado."""
        link = page.get_by_text(re.compile("filtros avanzados", re.I))
        if await link.count() == 0:
            return
        campo = await self._campo_filtros_avanzados(page, IDX_IDENTIFICADOR_MENSAJE)
        try:
            if await campo.count() > 0 and await campo.is_visible():
                return  # ya esta abierto
        except Exception:
            pass
        try:
            await link.first.click()
            await campo.wait_for(state="visible", timeout=self.timeout_ms)
        except Exception:
            pass

    async def _campo_filtros_avanzados(self, page: Page, indice: int):
        """Devuelve el locator del input VISIBLE (no hidden) en la
        posicion `indice` (0-based) dentro del panel "Filtros avanzados"
        de `page`.

        CONFIRMADO: ver el docstring del modulo -- en este portal el texto
        que se ve junto a cada campo (labels/placeholders aparentes) NO es
        localizable por Playwright, asi que se ubica por posicion dentro
        de FILTROS_PANEL_SELECTOR (id "collapseOne", confirmado por URL de
        hover). Si ese contenedor no aparece (ej. cambio de estructura),
        cae a buscar en toda la pagina como respaldo."""
        panel = page.locator(FILTROS_PANEL_SELECTOR)
        if await panel.count() == 0:
            panel = page
        return panel.locator('input:visible:not([type="hidden"])').nth(indice)

    async def _fijar_fecha_limite(self, page: Page, fecha_iso: str = "2026-05-31") -> None:
        """Fija la fecha limite superior del rango de busqueda de `page` en
        `fecha_iso` (por defecto 2026-05-31, confirmado por Andres: el
        portal antiguo solo tiene actos notificados hasta esa fecha).

        CONFIRMADO por Andres (2026-09-23): el campo NO acepta un valor
        puesto "a la fuerza" (tipo fill() directo) -- hay que entrar al
        campo (click) y escribir la fecha como lo haria una persona. Por
        eso aqui se hace click, se selecciona todo el contenido actual y
        se escribe caracter por caracter, cerrando despues cualquier
        calendario emergente con Escape.

        CONFIRMADO en vivo (2026-09-23): ni el placeholder aparente
        ("Fecha de envio hasta") ni un label son localizables aqui (ver
        docstring del modulo) -- se ubica por POSICION dentro del panel
        de filtros avanzados (IDX_FECHA_HASTA), igual que el resto de
        campos de esta seccion.

        OPTIMIZACION (2026-09-24, pedido de Andres: "más ágil"): esta
        fecha NO cambia entre busquedas dentro de un mismo lote -- solo
        el ID (y a veces el email) cambian. Escribirla caracter por
        caracter en CADA busqueda (como exige este campo, ~10 caracteres
        a 40ms cada uno + click + escape) es tiempo perdido si el valor
        ya esta puesto de una busqueda anterior en esta misma pestana. Por
        eso primero se lee el valor actual del campo y solo se vuelve a
        escribir si de verdad cambio (por ejemplo, si "Buscar" recargo la
        pagina y la reseteo a su valor por defecto) -- esto es
        AUTO-VERIFICABLE: nunca deja pasar una fecha incorrecta, solo
        evita el reescritura cuando es innecesaria."""
        objetivo = await self._campo_filtros_avanzados(page, IDX_FECHA_HASTA)
        if await objetivo.count() == 0:
            return  # no se encontro el campo; no se bloquea el flujo
        try:
            valor_actual = await objetivo.input_value()
        except Exception:
            valor_actual = None
        if valor_actual == fecha_iso:
            return  # ya esta puesta correctamente -- no hace falta reescribir
        try:
            await objetivo.click()
            await page.keyboard.press("Control+A")
            await objetivo.type(fecha_iso, delay=40)
            await page.keyboard.press("Escape")
        except Exception:
            # Puede ser un datepicker de JS mas exigente; se deja
            # constancia via docstring (NOT CONFIRMED) para seguir
            # calibrando si la primera corrida supervisada lo requiere.
            pass

    # ------------------------------------------------------------------
    # Busqueda + descarga del "testigo" (NOT CONFIRMED -- ver docstring)
    # ------------------------------------------------------------------
    async def buscar_y_descargar_testigo(
        self,
        message_id: str,
        email_destinatario: str | None = None,
        pagina: Page | None = None,
    ) -> bytes:
        """Busca `message_id` en "Identificador del mensaje" y, si se da
        `email_destinatario`, tambien lo escribe en "Email destinatario"
        para mayor precision. Abre el detalle de traza de la fila que
        coincide y descarga el PDF del link "Descargar testigo".

        `pagina`: pestana donde correr la busqueda. Por defecto usa la
        pestana principal (self._page, la que hizo login) -- se mantiene
        asi para no romper el script de prueba de un solo ID. Para
        procesar un LOTE en paralelo, abre pestanas adicionales con
        `abrir_pagina_trabajo()` y pasa cada una aqui: comparten la misma
        sesion (cookies), asi que no hace falta loguearse de nuevo en
        cada una.

        Devuelve los bytes del PDF descargado.

        Lanza:
          - LegacyPortalError si iniciar() no se ha llamado.
          - LegacyNotFoundError si la busqueda no arroja ninguna fila.
          - LegacyPortalError si algo en el flujo de descarga no coincide
            con lo esperado (icono de traza, modal, link de descarga) --
            senal de que hace falta recalibrar selectores contra el HTML
            real (ver NOT CONFIRMED en el docstring del modulo)."""
        if not self._logueado or self._page is None:
            raise LegacyPortalError("Llama a iniciar() antes de buscar.")
        page = pagina if pagina is not None else self._page

        await self._ir_a_status(page)
        await self._fijar_fecha_limite(page)

        # ANTES: se hacia click en "Limpiar filtros" antes de cada
        # busqueda, para no arrastrar el email de la busqueda anterior.
        # OPTIMIZACION (2026-09-24, pedido de Andres: "más ágil"): ese
        # click (y, si el portal recarga la pagina al hacerlo, la vuelta a
        # abrir "Filtros avanzados" que le seguia) sale sobrando si en vez
        # de "limpiar y confiar en que quedo vacio" ESCRIBIMOS siempre un
        # valor explicito y completo en cada campo que nos importa -- el
        # ID (abajo) y el email (aqui: el destinatario si se dio, o una
        # cadena vacia para borrar cualquier valor que haya quedado de la
        # busqueda anterior en esta misma pestana). Con eso el resultado
        # es el mismo (nunca queda un filtro viejo puesto) sin pagar el
        # costo del click+recarga+reabrir panel en cada ID del lote.
        #
        # CONFIRMADO: ni label ni placeholder son localizables en este
        # portal (ver docstring del modulo) -- se ubica por POSICION. A
        # diferencia de la fecha (confirmado que necesita click+type), el
        # ID y el email son inputs de texto normales -- .fill() directo
        # SI funciona (confirmado: la corrida que descargo bien el testigo
        # 1363712 uso este mismo .fill()) y es mucho mas rapido para un
        # lote grande que escribir caracter por caracter.
        id_input = await self._campo_filtros_avanzados(page, IDX_IDENTIFICADOR_MENSAJE)
        if await id_input.count() == 0:
            raise LegacyPortalError(
                "No se encontro el campo 'Identificador del mensaje' por "
                "posicion (hace falta recalibrar IDX_IDENTIFICADOR_MENSAJE)."
            )
        await id_input.fill(message_id)

        email_input = await self._campo_filtros_avanzados(page, IDX_EMAIL_DESTINATARIO)
        if await email_input.count() > 0:
            await email_input.fill(email_destinatario or "")

        await page.get_by_role("button", name=re.compile("buscar", re.I)).first.click()

        # Esperar directamente a que aparezca una fila de resultado (o a
        # que se agote un tiempo corto si realmente no hay ninguna) es
        # mucho mas rapido y confiable que esperar "networkidle": esa
        # espera puede demorarse de mas (o nunca completar) si la pagina
        # sigue con trafico de fondo (analytics, polling, etc) que nunca
        # queda del todo quieto.
        try:
            await page.wait_for_selector("table tbody tr", timeout=min(self.timeout_ms, 8000))
        except PwTimeoutError:
            pass  # puede que de verdad no haya resultados; se valida abajo

        filas = page.locator("table tbody tr")
        total_filas = await filas.count()
        if total_filas == 0:
            raise LegacyNotFoundError(
                f"El portal antiguo no devolvio resultados para el ID {message_id!r}."
            )

        fila = filas.first
        if total_filas > 1 and email_destinatario:
            candidata = filas.filter(has_text=email_destinatario)
            if await candidata.count() > 0:
                fila = candidata.first
            # Si ninguna fila coincide con el email, se sigue usando la
            # primera (la busqueda por ID deberia bastar); no se lanza
            # error solo por esto.

        # Columna "Traza": se asume que el icono de DOCUMENTO es el ULTIMO
        # de los iconos clicables en la fila (el primero seria el de
        # sobre/correo). NOT CONFIRMED -- calibrar en la primera corrida.
        iconos_traza = fila.locator("a, button")
        total_iconos = await iconos_traza.count()
        if total_iconos == 0:
            raise LegacyPortalError(
                "No se encontro ningun icono clicable en la fila de "
                "resultados (la estructura de la tabla puede haber cambiado; "
                "hace falta recalibrar selectores)."
            )
        icono_documento = iconos_traza.nth(total_iconos - 1)
        await icono_documento.click()

        # Modal "Detalle traza" con el link "Descargar testigo".
        descargar_link = page.get_by_text(re.compile("descargar testigo", re.I))
        try:
            await descargar_link.wait_for(state="visible", timeout=self.timeout_ms)
        except PwTimeoutError as exc:
            raise LegacyPortalError(
                "Se hizo clic en el icono de traza pero no aparecio el "
                "modal 'Detalle traza' con el link 'Descargar testigo' "
                "esperado (hace falta recalibrar selectores)."
            ) from exc

        async with page.expect_download(timeout=self.timeout_ms) as descarga_info:
            await descargar_link.first.click()
        descarga = await descarga_info.value
        ruta_temporal = await descarga.path()
        if ruta_temporal is None:
            raise LegacyPortalError(
                f"La descarga del testigo para {message_id!r} no se pudo completar."
            )
        pdf_bytes = Path(ruta_temporal).read_bytes()

        # Cerrar el modal para dejar la pagina lista para la siguiente busqueda.
        aceptar = page.get_by_role("button", name=re.compile("aceptar", re.I))
        if await aceptar.count() > 0:
            try:
                await aceptar.first.click()
            except Exception:
                pass

        return pdf_bytes

"""
Centro de Envíos de 4-72 (https://mailcertificadoapp.com): descarga de los
acuses que todavía NO aparecen en el portal nuevo (los de menos de un mes).

Guía de Andrés (1-oct-2026, "RUTA PARA DESCARGAR ACUSES QUE NO APARECEN EN LA
NUEVA PLATAFORMA DE 472.pdf"), confirmada en vivo el mismo día:
  1. La plataforma pide reCAPTCHA al iniciar sesión -> el inicio de sesión lo
     hace ANDRÉS a mano en la ventana que abre Insignia (Insignia nunca
     escribe la contraseña ni toca el captcha). La sesión queda en
     sessionStorage ('currentUser'): dura mientras la ventana siga abierta.
  2. Menú "Descargar Acuses" -> formulario "DESCARGA DE ACUSES":
       Usuario (select: 'notificacionesmen@...' por defecto, 'Todos los Usuarios'),
       De / A (input type=date), Destinatario (input type=email),
       Asunto (placeholder 'Buscar por asunto...'), Estado de entrega, Buscar.
  3. Rango máximo: 30 días hacia atrás desde hoy. Si se pasa, la página dice
     "No se pueden buscar acuses con más de 1 mes (30 días) de antigüedad por
     disposición de RPost." (probado en vivo con 23/06–21/07).
  4. Resultados: tabla Fecha | Destinatario | Asunto | ID del Correo | Estado |
     Acuse; en la columna Acuse, button[title="Acuse RPost"] baja '<ID>.pdf'
     (el acuse RPost: PDF con el .eml adentro, el mismo que procesa
     extractor.extract_acuse_from_pdf). "Volver a Filtros Principales" regresa.
  5. Filtros: Destinatario = correo del Cuadro_2026; Asunto = número de la
     resolución ('25850' encuentra 'Resolución 025850 DE 25 SEP 2026'). Los
     Autos se buscan SOLO por destinatario: el asunto dice 'AUTO DE 18 SEP 2026'
     y la fecha puede no coincidir con la del Cuadro (Auto 2297: Cuadro 17/09,
     asunto 18/09) -- confirmado en vivo.
Pruebas en vivo (1-oct): Res. 25850 / ciudadano1@example.com -> 1 fila,
ID AA7B9793CA74D8B5308DF824A82BEAB722D4DE35, el PDF bajado arma
'2026_25850.pdf'; Auto 2297 / ciudadano2@example.com -> 1 fila (AUTO DE 18 SEP 2026).

Inactividad (Andrés, 1-oct): la página muestra "¿Sigues ahí? Tu sesión se cerrará
por inactividad en N segundos" con el botón azul "¡Seguir conectado!" y el enlace
"Cerrar sesión ahora". El cliente vigila la ventana y pulsa SOLO "¡Seguir
conectado!" (nunca "Cerrar sesión ahora"), así Andrés no tiene que volver a
iniciar sesión.

Nunca se adivina: este cliente solo baja; main.py verifica el CONTENIDO de cada
acuse (tipo, fecha, número o correo/titular) antes de usarlo.
"""
from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import re
import unicodedata
from pathlib import Path
from typing import Awaitable, Callable, Optional

URL = "https://mailcertificadoapp.com/"
USUARIO_ENVIOS = "notificacionesmen@mineducacion.gov.co"
USUARIO_TODOS = "Todos los Usuarios"
DIAS_MAXIMOS = 29          # 'De' no puede ser anterior a hoy - 29 dias (el portal dice "1 mes (30 dias)")
DIAS_ACTO_MAXIMOS = 45     # un acto mas viejo que esto ya no puede tener el acuse en este portal
TEXTO_MAS_DE_UN_MES = "más de 1 mes"
TEXTO_PENDIENTE = "pendiente por llegar"


class CentroEnviosError(Exception):
    pass


class CentroEnviosSinSesion(CentroEnviosError):
    """La sesion no esta iniciada (o vencio): Andres debe iniciarla en la ventana."""


@dataclasses.dataclass
class FilaAcuse:
    fecha: str
    destinatario: str
    asunto: str
    message_id: str
    estado: str
    remitente: str = ""


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def rango_busqueda(fecha_acto: dt.date, hoy: Optional[dt.date] = None) -> Optional[tuple]:
    """(desde, hasta) para un acto, o None si el acto es demasiado viejo para
    este portal. 'desde' = un dia antes del acto, pero nunca antes de hoy-29."""
    hoy = hoy or dt.date.today()
    if fecha_acto is None or fecha_acto > hoy or (hoy - fecha_acto).days > DIAS_ACTO_MAXIMOS:
        return None
    desde = max(fecha_acto - dt.timedelta(days=1), hoy - dt.timedelta(days=DIAS_MAXIMOS))
    return desde, hoy


RE_RADICADO_EE = re.compile(r"(\d{4})\s*-\s*EE\s*-\s*0*(\d+)", re.I)


def _radicados_en(texto: str) -> set:
    return {f"{a}-EE-{n}" for a, n in RE_RADICADO_EE.findall(texto or "")}


def fila_es_del_acto(fila: FilaAcuse, tipo: str, numero, correos: list, radicados: Optional[list] = None) -> bool:
    """Filtro de la tabla (el contenido se vuelve a verificar despues). El correo
    del Cuadro debe coincidir siempre; ademas, o el asunto nombra el acto, o trae
    el radicado de notificacion electronica del Cuadro ('Comunicación de respuesta
    (2026-EE-285449)')."""
    if correos and (fila.destinatario or "").strip().lower() not in {c.strip().lower() for c in correos}:
        return False
    if radicados and _radicados_en(fila.asunto) & {r for c in radicados for r in _radicados_en(c)}:
        return True
    asunto = _norm(fila.asunto)
    if tipo == "Resolucion":
        n = str(numero or "").strip().lstrip("0")
        return bool(n) and bool(re.search(rf"resoluci\w*\s*(?:no\.?\s*)?0*{n}(?!\d)", asunto))
    if tipo == "Auto":
        return bool(re.search(r"\bauto\b", asunto))
    return False


def asunto_de_busqueda(tipo: str, numero) -> str:
    if tipo == "Resolucion":
        return str(numero or "").strip().lstrip("0")
    return ""   # Autos: solo por destinatario (ver docstring)


class CentroEnviosClient:
    """Navegador propio (perfil persistente: recuerda el usuario) con ventana
    visible para que Andres inicie sesion. Una busqueda a la vez."""

    def __init__(self, perfil_dir: Path, headless: bool = False, timeout_ms: int = 30000,
                 url: str = URL, carpeta_descargas: Optional[Path] = None,
                 preparar_contexto: Optional[Callable] = None):
        self.perfil_dir = Path(perfil_dir)
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.url = url
        self.carpeta_descargas = carpeta_descargas
        self.preparar_contexto = preparar_contexto   # solo pruebas (maqueta)
        self._pw = None
        self._context = None
        self._page = None
        self._lock = asyncio.Lock()
        self.ultimo_error = ""
        self._vigia = None
        self.reactivaciones = 0

    # ---------------- ciclo de vida ----------------
    async def abrir(self, on_progreso: Optional[Callable[[str], Awaitable[None]]] = None) -> None:
        from playwright.async_api import async_playwright
        if self._page is not None:
            return
        self.perfil_dir.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        try:
            self._context = await self._pw.chromium.launch_persistent_context(
                str(self.perfil_dir), headless=self.headless, accept_downloads=True,
                viewport={"width": 1366, "height": 860},
            )
        except Exception:
            await self._pw.stop()
            self._pw = None
            raise
        if self.preparar_contexto is not None:
            await self.preparar_contexto(self._context)
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        await self._page.goto(self.url, wait_until="domcontentloaded")
        self._vigia = asyncio.ensure_future(self._vigilar_inactividad())

    async def seguir_conectado(self) -> bool:
        """Si esta el aviso '¿Sigues ahí?', pulsa '¡Seguir conectado!'. True si lo pulso."""
        if not self.abierto:
            return False
        try:
            boton = self._page.get_by_role("button", name=re.compile(r"seguir conectado", re.I))
            if await boton.count() and await boton.first.is_visible():
                await boton.first.click()
                self.reactivaciones += 1
                return True
        except Exception:
            pass
        return False

    async def _vigilar_inactividad(self, cada_s: float = 3) -> None:
        while self.abierto:
            await self.seguir_conectado()
            await asyncio.sleep(cada_s)

    async def cerrar(self) -> None:
        if self._vigia is not None:
            self._vigia.cancel()
            self._vigia = None
        for paso in (lambda: self._context.close() if self._context else None,
                     lambda: self._pw.stop() if self._pw else None):
            try:
                r = paso()
                if r is not None:
                    await r
            except Exception:
                pass
        self._pw = self._context = self._page = None

    @property
    def abierto(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    async def sesion_activa(self) -> bool:
        if not self.abierto:
            return False
        try:
            return bool(await self._page.evaluate("() => !!sessionStorage.getItem('currentUser')"))
        except Exception:
            return False

    async def esperar_login(self, max_s: float = 600,
                            on_progreso: Optional[Callable[[str], Awaitable[None]]] = None) -> bool:
        """Espera a que ANDRES inicie sesion en la ventana (no escribe nada)."""
        if on_progreso:
            await on_progreso("Inicia sesión en la ventana del Centro de Envíos (usuario, contraseña y 'No soy un robot').")
        limite = asyncio.get_running_loop().time() + max_s
        while asyncio.get_running_loop().time() < limite:
            if await self.sesion_activa():
                return True
            if not self.abierto:
                return False
            await asyncio.sleep(2)
        return False

    # ---------------- formulario ----------------
    async def _ir_al_formulario(self) -> None:
        page = self._page
        if not await self.sesion_activa():
            raise CentroEnviosSinSesion("La sesión del Centro de Envíos no está iniciada (o venció): inicia sesión en su ventana.")
        volver = page.get_by_role("button", name=re.compile(r"Volver a Filtros", re.I))
        if await volver.count() and await volver.first.is_visible():
            await volver.first.click()
        titulo = page.get_by_text(re.compile(r"^\s*descarga de acuses\s*$", re.I))
        if not (await titulo.count() and await titulo.first.is_visible()):
            boton = page.locator("nav button", has_text="Descargar Acuses")
            n = await boton.count()
            for i in range(n):
                if await boton.nth(i).is_visible():
                    await boton.nth(i).click()
                    break
            else:
                await page.get_by_role("button", name="Descargar Acuses").first.click()
        await titulo.first.wait_for(state="visible", timeout=self.timeout_ms)

    async def buscar(self, destinatario: str, asunto: str, desde: dt.date, hasta: dt.date,
                     usuario: str = USUARIO_ENVIOS, max_espera_s: float = 150) -> list:
        page = self._page
        await self._ir_al_formulario()
        main = page.locator("main")
        await main.locator("select").first.select_option(usuario)
        fechas = main.locator("input[type=date]")
        await fechas.nth(0).fill(desde.isoformat())
        await fechas.nth(1).fill(hasta.isoformat())
        await main.locator("input[type=email]").first.fill(destinatario or "")
        await main.get_by_placeholder("Buscar por asunto...").fill(asunto or "")
        await main.get_by_role("button", name="Buscar", exact=True).click()
        resultados = page.get_by_text(re.compile(r"Resultados \(\d+\)"))
        limite = asyncio.get_running_loop().time() + max_espera_s
        while asyncio.get_running_loop().time() < limite:
            if await resultados.count() and await resultados.first.is_visible():
                break
            cuerpo = await page.locator("body").inner_text()
            if TEXTO_MAS_DE_UN_MES in cuerpo:
                raise CentroEnviosError("El Centro de Envíos solo busca acuses de los últimos 30 días.")
            if not await self.sesion_activa():
                raise CentroEnviosSinSesion("La sesión del Centro de Envíos venció: inicia sesión de nuevo en su ventana.")
            await asyncio.sleep(1)
        else:
            raise CentroEnviosError(f"El Centro de Envíos no respondió la búsqueda en {int(max_espera_s)} s.")
        filas = []
        trs = main.locator("table tbody tr")
        for i in range(await trs.count()):
            tds = trs.nth(i).locator("td")
            if await tds.count() < 5:
                continue
            textos = [(await tds.nth(k).inner_text()).strip() for k in range(5)]
            mid = (await tds.nth(3).get_attribute("title")) or textos[3]
            filas.append(FilaAcuse(fecha=textos[0], destinatario=textos[1], asunto=textos[2],
                                   message_id=mid.strip(), estado=textos[4]))
        return filas

    async def descargar(self, fila: FilaAcuse, max_espera_s: float = 120) -> tuple:
        """(nombre_sugerido, bytes) del acuse de esa fila."""
        page = self._page
        tr = page.locator("main table tbody tr", has_text=fila.message_id).first
        boton = tr.locator("button[title='Acuse RPost']").first
        await boton.scroll_into_view_if_needed()
        # La pagina avisa con un aviso que se borra solo ("Acuse pendiente por
        # llegar"): se vigila MIENTRAS se espera la descarga, no al final.
        espera = asyncio.ensure_future(page.wait_for_event("download", timeout=int(max_espera_s * 1000)))
        await boton.click()
        descarga = None
        try:
            while not espera.done():
                try:
                    cuerpo = await page.locator("body").inner_text()
                except Exception:
                    cuerpo = ""
                if TEXTO_PENDIENTE in cuerpo:
                    raise CentroEnviosError(f"{fila.message_id[:12]}…: el acuse está pendiente por llegar.")
                await asyncio.sleep(0.4)
            descarga = espera.result()
        except CentroEnviosError:
            raise
        except Exception as exc:
            raise CentroEnviosError(f"{fila.message_id[:12]}…: no se pudo bajar el acuse ({type(exc).__name__}).") from exc
        finally:
            if not espera.done():
                espera.cancel()
        ruta = await descarga.path()
        datos = Path(ruta).read_bytes()
        return descarga.suggested_filename or f"{fila.message_id}.pdf", datos

    async def buscar_y_descargar(self, tipo: str, numero, fecha_acto: dt.date, correos: list,
                                 hoy: Optional[dt.date] = None, radicados: Optional[list] = None) -> tuple:
        """([(FilaAcuse, nombre, bytes)], nota). Busca con cada correo del acto;
        si con el usuario de envios no hay filas, reintenta con 'Todos los Usuarios'
        y, si el Cuadro trae el radicado de notificacion electronica, con ese
        radicado en el asunto ('Comunicación de respuesta (2026-EE-...)')."""
        rango = rango_busqueda(fecha_acto, hoy)
        if rango is None:
            return [], "el acto tiene más de un mes: el Centro de Envíos ya no lo tiene"
        desde, hasta = rango
        async with self._lock:
            bajados, notas = [], []
            for correo in [c for c in correos if c] or [""]:
                filas = []
                intentos = [(USUARIO_ENVIOS, asunto_de_busqueda(tipo, numero)),
                            (USUARIO_TODOS, asunto_de_busqueda(tipo, numero))]
                intentos += [(USUARIO_TODOS, r) for r in (radicados or [])]
                for usuario, asunto in intentos:
                    filas = [f for f in await self.buscar(correo, asunto, desde, hasta, usuario)
                             if fila_es_del_acto(f, tipo, numero, [correo] if correo else [], radicados)]
                    if filas:
                        break
                if not filas:
                    notas.append(f"{correo or '(sin correo)'}: sin resultados")
                    continue
                for fila in filas:
                    try:
                        nombre, datos = await self.descargar(fila)
                        bajados.append((fila, nombre, datos))
                    except CentroEnviosError as exc:
                        notas.append(str(exc))
            return bajados, "; ".join(notas)

    # ---------------- 'Reporte de Envíos' (sin el limite de 30 dias) ----------------
    # CONFIRMADO EN VIVO (1-oct):
    #  - Esta pantalla NO tiene la validacion de 30 dias de 'Descargar Acuses'.
    #  - Al pulsar Buscar la pagina pide a RPost (POST .../api/Reports/UsageReport)
    #    TODO el reporte del rango (el destinatario y el asunto NO viajan: la pagina
    #    filtra despues). Con 'Todos los Usuarios' un rango de 15 dias trae ~40.000
    #    envios (~40 MB) y tarda 40-60 s. Cada fila trae DateSentUTC ('dd/mm/aaaa'),
    #    SenderAddress, RecipientAddress, Subject, MessageId, DeliveryStatus.
    #  - Por eso el cliente LEE ESA RESPUESTA (no la tabla, que se pagina) y la guarda
    #    en memoria 2 h por rango: varios actos del mismo dia usan una sola consulta.
    #  - Remitentes: notificacionesmen@ ('[ticket] Acta de notificación electrónica
    #    ... - AUTO DE 22 JUL 2026', lo mismo que el Excel Reporte_Envios) y
    #    mineducacion472@ ('Comunicación de respuesta (2026-EE-285449)': el SGDEA). Los
    #    Autos 1510 y 1939 se notificaron por el segundo, con el radicado que el Cuadro
    #    trae en 'RADICADO NOTIFICACION ELECTRONICA'.
    #  - 'Volver a Filtros Principales' regresa al formulario (conserva las fechas y
    #    borra el destinatario).
    REPORTE_CACHE_SEG = 7200

    async def _ir_al_reporte(self) -> None:
        page = self._page
        if not await self.sesion_activa():
            raise CentroEnviosSinSesion("La sesión del Centro de Envíos no está iniciada (o venció): inicia sesión en su ventana.")
        volver = page.get_by_role("button", name=re.compile(r"Volver a Filtros", re.I))
        if await volver.count() and await volver.first.is_visible():
            await volver.first.click()
        # el titulo se busca DENTRO de <main>: el menu lateral tambien dice "Reporte de Envíos"
        titulo = page.locator("main").get_by_text(re.compile(r"^\s*reporte de env[ií]os\s*$", re.I))
        if await titulo.count() and await titulo.first.is_visible():
            return
        boton = page.locator("nav button", has_text="Reporte de Envíos")
        for i in range(await boton.count()):
            if await boton.nth(i).is_visible():
                await boton.nth(i).click()
                break
        else:
            await page.get_by_role("button", name=re.compile(r"Ver Reportes|Reporte de Env", re.I)).first.click()
        await titulo.first.wait_for(state="visible", timeout=self.timeout_ms)

    async def reporte_envios(self, desde: dt.date, hasta: dt.date, usuario: str = USUARIO_TODOS,
                             correo: str = "", max_espera_s: float = 240) -> list:
        """[FilaAcuse] de TODOS los envios del rango (de la respuesta de RPost).
        `correo` solo se escribe en la pantalla para que la tabla quede corta."""
        cache = self.__dict__.setdefault("_reporte_cache", {})
        clave = (usuario, desde.isoformat(), hasta.isoformat())
        ahora = asyncio.get_running_loop().time()
        if clave in cache and ahora - cache[clave][0] < self.REPORTE_CACHE_SEG:
            return cache[clave][1]
        page = self._page
        await self._ir_al_reporte()
        main = page.locator("main")
        await main.locator("select").first.select_option(usuario)
        fechas = main.locator("input[type=date]")
        await fechas.nth(0).fill(desde.isoformat())
        await fechas.nth(1).fill(hasta.isoformat())
        await main.locator("input[type=email]").first.fill(correo or "")
        await main.get_by_placeholder("Buscar por asunto...").first.fill("")
        def es_reporte(r):
            return "reports/usagereport" in r.url.lower() and r.request.method == "POST"
        try:
            async with page.expect_response(es_reporte, timeout=int(max_espera_s * 1000)) as info:
                await main.get_by_role("button", name="Buscar", exact=True).first.click()
            resp = await info.value
            datos = await resp.json()
        except Exception as exc:  # noqa: BLE001
            if not await self.sesion_activa():
                raise CentroEnviosSinSesion("La sesión del Centro de Envíos venció: inicia sesión de nuevo en su ventana.") from exc
            raise CentroEnviosError(f"El Reporte de Envíos no respondió ({type(exc).__name__}).") from exc
        filas = filas_de_reporte(datos)
        cache[clave] = (ahora, filas)
        if len(cache) > 6:
            cache.pop(min(cache, key=lambda k: cache[k][0]))
        return filas

    async def ids_de_acto(self, tipo: str, numero, fecha_acto: dt.date, correos: list,
                          radicados: Optional[list] = None, fechas_notif: Optional[list] = None,
                          hoy: Optional[dt.date] = None) -> tuple:
        """([FilaAcuse] del acto, nota). Rango: alrededor de la FECHA DE NOTIFICACION
        ELECTRONICA del Cuadro (-2/+3 dias) o, si no la hay, del acto (-1/+15)."""
        hoy = hoy or dt.date.today()
        rangos = []
        for f in sorted({f for f in (fechas_notif or []) if f}):
            rangos.append((f - dt.timedelta(days=2), min(f + dt.timedelta(days=3), hoy)))
        if not rangos:
            rangos.append((fecha_acto - dt.timedelta(days=1), min(fecha_acto + dt.timedelta(days=15), hoy)))
        async with self._lock:
            hallado, vistos = [], set()
            for desde, hasta in rangos:
                if desde > hasta:
                    continue
                todas = await self.reporte_envios(desde, hasta, USUARIO_TODOS, (correos or [""])[0])
                for f in todas:
                    if f.message_id not in vistos and fila_es_del_acto(f, tipo, numero, correos, radicados):
                        vistos.add(f.message_id)
                        hallado.append(f)
            if hallado:
                return hallado, ""
            desde, hasta = rangos[0][0], rangos[-1][1]
            return [], (f"ningún envío a {', '.join(correos) or '(sin correo)'} del {desde:%d/%m/%Y} al "
                        f"{hasta:%d/%m/%Y} es de este acto"
                        + (f" (ni con el radicado {', '.join(radicados)})" if radicados else ""))

    async def descargar_por_id(self, fila: FilaAcuse, hoy: Optional[dt.date] = None) -> tuple:
        """Baja por 'Descargar Acuses' el acuse de un envio de los ultimos 30 dias.
        (nombre, bytes). La fila se busca por destinatario (y radicado/numero en
        el asunto) y se toma la que tenga ESE ID."""
        hoy = hoy or dt.date.today()
        enviado = fecha_de_fila(fila)
        if enviado is None or (hoy - enviado).days > DIAS_MAXIMOS:
            raise CentroEnviosError(f"{fila.message_id[:12]}…: tiene más de 30 días; se baja del portal nuevo")
        desde = max(enviado - dt.timedelta(days=1), hoy - dt.timedelta(days=DIAS_MAXIMOS))
        async with self._lock:
            filas = await self.buscar(fila.destinatario, "", desde, hoy, USUARIO_TODOS)
            propia = next((f for f in filas if f.message_id.upper() == fila.message_id.upper()), None)
            if propia is None:
                raise CentroEnviosError(f"{fila.message_id[:12]}…: no aparece en 'Descargar Acuses'")
            return await self.descargar(propia)


def fecha_de_fila(fila: FilaAcuse) -> Optional[dt.date]:
    t = (fila.fecha or "").strip().split()[0] if (fila.fecha or "").strip() else ""
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(t, formato).date()
        except ValueError:
            continue
    return None


def filas_de_reporte(datos) -> list:
    """Respuesta de RPost UsageReport -> [FilaAcuse] (fecha 'dd/mm/aaaa' UTC)."""
    if isinstance(datos, dict):
        datos = datos.get("Usage") or datos.get("usage") or []
    filas, vistos = [], set()
    for r in datos or []:
        if not isinstance(r, dict):
            continue
        mid = str(r.get("MessageId") or "").strip().upper()
        dest = str(r.get("RecipientAddress") or "").strip().lower()
        if not re.fullmatch(r"[0-9A-F]{20,64}", mid) or (mid, dest) in vistos:
            continue
        vistos.add((mid, dest))
        filas.append(FilaAcuse(fecha=str(r.get("DateSentUTC") or "").strip(), destinatario=dest,
                               asunto=str(r.get("Subject") or ""), message_id=mid,
                               estado=str(r.get("DeliveryStatus") or ""),
                               remitente=str(r.get("SenderAddress") or "").strip().lower()))
    return filas

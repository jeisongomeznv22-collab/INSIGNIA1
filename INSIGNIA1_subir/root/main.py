"""
Insignia — Centro de Gestión Ejecutiva (MEN - SRC)
Aplicativo de escritorio (Flet) de Jeison Andres Gomez Nova: Dashboard de
gestion, automatizacion del Portal de Acuses 4-72 (Resolucion/Auto + Acta +
Acuse) y del flujo de Memorando respuesta en SGDEA/TMS.

Autor: generado con Claude para Jeison Andres Gomez Nova (MEN - SRC).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Optional

# --- Playwright + empaquetado (PyInstaller): forzar una carpeta PERSISTENTE
# para los navegadores (Chromium), en vez de la carpeta temporal donde
# PyInstaller extrae el .exe en cada ejecucion (_MEIxxxxxx), que se borra al
# cerrar la app. Sin esto, al correr como .exe empaquetado, Playwright
# detecta el modo "paquete" y por defecto instala/busca el navegador DENTRO
# de esa carpeta temporal -- por eso la descarga parecia funcionar (se veia
# la ventana negra de progreso) pero al conectar fallaba con
# "Executable doesn't exist at ...\_MEIxxxxxx\playwright\driver\package\
# .local-browsers\..." -- cada ejecucion crea una carpeta _MEI distinta y la
# anterior ya no existe. Fijar esta variable de entorno ANTES de importar
# playwright (por eso va aqui, antes del import de backend.legacy_portal_client
# mas abajo, que es el que importa playwright) hace que tanto la instalacion
# como el lanzamiento del navegador usen siempre la misma carpeta estable del
# usuario, igual que una instalacion normal de Playwright (no empaquetada).
os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home())), "ms-playwright"),
)

import flet as ft

from backend.portal_client import PortalClient, PortalError, LoginError, NotFoundError
from backend.legacy_portal_client import (
    LegacyPortalClient,
    LegacyPortalError,
    LegacyLoginError,
    LegacyNotFoundError,
)
from backend.extractor import process_zip, extract_acuse, extract_acuse_from_pdf, merge_acuses, ExtractionError
from backend.extractor import _build_final_filename
from backend.excel_io import read_ids_from_excel, write_report_excel, write_local_report_excel
from backend.local_zip import collect_zip_sources, collect_pdf_sources, LocalZipError
from backend.cuadro_lookup import load_cuadro, CuadroError, con_cuadro_anterior
from backend.estado_mensajes_lookup import load_estado_mensajes, load_reporte_envios, EstadoMensajesError
from backend import fuentes_acuses
from backend import adjuntos_ids
from backend import adjuntos_locales
from backend import visor_pdf
from backend import contingencia
from backend import carpeta_caso
import shutil
from backend.centro_envios_client import CentroEnviosClient, CentroEnviosError, CentroEnviosSinSesion
from backend.centro_envios_client import rango_busqueda as centro_rango_busqueda
from backend.centro_envios_client import fecha_de_fila as centro_fecha_de_fila
from backend import autorrevision
from backend import casos_pendientes
from backend import sgdea_automation
from backend import sgdea_peticion
from backend import sgdea_carta
from backend import dashboard
from backend import barrido
from backend.sgdea_session import SgdeaSessionClient, SgdeaLoginError, SgdeaSessionError

# Cuantas pestanas del portal ANTIGUO (4-72 legacy) corren en paralelo al
# procesar un lote Masivo. Mas alto = mas rapido, pero tambien mas carga
# simultanea contra el portal (riesgo NOT CONFIRMED de activar algun
# limite de tasa o CAPTCHA que no aparecia con una sola pestana en serie).
# Se arranca en 4 -- si el portal lo tolera bien, se puede subir; si da
# problemas (mas fallos/timeouts que antes), se puede bajar.
MAX_WORKERS_LEGACY = 4
import theme
import theme_bg


def _base_dir() -> Path:
    """Carpeta base para guardar config.json: junto al .exe si esta empaquetado,
    o junto a este script en desarrollo."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


CONFIG_PATH = _base_dir() / "config_472.json"

# Cada cuanto revisa el ciclo automatico de SGDEA si hay casos nuevos (ver
# sgdea_auto_switch / _ciclo_automatico_sgdea en main()). 10 minutos: lo
# bastante seguido para que Andres vea casos nuevos con rapidez razonable,
# sin bombardear SGDEA con sincronizaciones constantes.
SGDEA_AUTO_INTERVALO_SEG = 600
SGDEA_REINTENTO_RAPIDO_SEG = 240  # 4 min (Andres, 29-sep)

# De que portal/reporte sale cada acuse segun la fecha del acto (reglas de
# Andres, 28-sep): ver backend/fuentes_acuses.py.


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(data: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def unique_path(folder: Path, filename: str) -> Path:
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    i = 2
    while True:
        candidate = folder / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


# VERSION (agregada sesion 2026-09-25, pedido explicito de Andres:
# "empaqueta y actualiza la version de insignia" -- hasta ahora el
# aplicativo no mostraba ningun numero de version en ningun lado, lo que
# hacia dificil confirmar despues de un despliegue si Andres de verdad
# habia reiniciado el proceso (run_dev.bat NO tiene hot-reload: cualquier
# cambio de main.py/backend exige cerrar la terminal y volver a correrlo)
# o si seguia corriendo una copia vieja en memoria. Se muestra en el
# titulo de la ventana Y en el header del Dashboard -- visible sin tener
# que abrir Configuracion. Bump esta constante en cada despliegue real a
# la maquina de Andres.
# v1.5.12 (30-sep-2026, revision programada): 'ya está radicado' se reconoce
# aunque el visor PDF de Chrome este en un marco anidado de 'Ver documentos'
# (2026-IE-035664 se reintentaba cada ~5 min, 45 s por intento).
APP_VERSION = "1.5.15"
# Marca (en los pasos del barrido) de un caso en revision al que hay que rehacerle
# el cuadro y el adjunto (carpeta del caso en Descargas, 1-oct).
MARCA_REHACER = "rehacer_carpeta"
# Capturas de pantalla cuando algo falla en SGDEA (dist\\diagnosticos).
sgdea_automation.CARPETA_DIAGNOSTICOS = _base_dir() / "diagnosticos"
dashboard.VERSION_APP = APP_VERSION


def _configurar_log_empaquetado() -> None:
    """En el .exe empaquetado (flet pack = ventana sin consola) sys.stdout
    es None y TODOS los print()/_log_paso() se pierden en silencio -- en
    otro PC no quedaria ningun rastro de por que fallo una gestion. Aqui,
    solo cuando corre empaquetado (o sin stdout), se redirige la salida a
    'insignia_run.log' junto al .exe (append, line-buffered), con una
    rotacion simple a los 5 MB. En desarrollo no hace nada: run_dev.bat ya
    redirige a dev_run.log."""
    if not getattr(sys, "frozen", False) and sys.stdout is not None:
        return
    try:
        ruta = _base_dir() / "insignia_run.log"
        if ruta.exists() and ruta.stat().st_size > 5 * 1024 * 1024:
            ruta.replace(ruta.with_name("insignia_run.log.1"))
        archivo = open(ruta, "a", encoding="utf-8", buffering=1)
        sys.stdout = archivo
        sys.stderr = archivo
        print(f"===== Insignia v{APP_VERSION} iniciado {datetime.now():%Y-%m-%d %H:%M:%S} =====", flush=True)
    except Exception:
        pass


async def main(page: ft.Page):
    _configurar_log_empaquetado()
    page.title = f"Insignia — Centro de Gestión Ejecutiva (v{APP_VERSION})"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = theme.BG_DEEP
    page.padding = 0
    page.window.width = 1180
    page.window.height = 800
    page.window.min_width = 980
    page.window.min_height = 680
    page.window.bgcolor = theme.BG_DEEP
    page.fonts = {}

    client: PortalClient | None = None
    legacy_client: LegacyPortalClient | None = None
    # Centro de Envios de 4-72 (mailcertificadoapp.com, 1-oct-2026): acuses de
    # menos de un mes. Andres inicia sesion a mano (reCAPTCHA) en su ventana.
    centro_envios: CentroEnviosClient | None = None
    centro_estado = {"desde": None}   # timestamp del ultimo inicio de sesion detectado
    # Sesion PROPIA de SGDEA (navegador propio, login independiente del
    # Chrome de Andres) -- ver backend/sgdea_session.py. None hasta que
    # Andres conecte desde Configuración; mientras tanto todos los flujos
    # de SGDEA siguen usando el Chrome de Andres via CDP, exactamente
    # igual que antes (ver _conectar_si_hace_falta / _sincronizar_dashboard,
    # que prefieren sgdea_client cuando esta conectado y caen al CDP como
    # respaldo).
    sgdea_client: SgdeaSessionClient | None = None

    def _actualizar_seguro(*controles):
        """.update() que no revienta si el control no esta en pantalla.
        Evidencia (insignia_run.log 27-sep 20:30): la autoconexion al abrir
        Insignia actualizaba los indicadores de 'Configuración' mientras se
        veia el Dashboard -> RuntimeError 'Control must be added to the page
        first' -> se cayo antes de conectar SGDEA. El valor igual queda
        guardado en el control y se ve al abrir esa pestaña."""
        for c in controles:
            try:
                c.update()
            except RuntimeError:
                pass

    # Candado UNICO de SGDEA a nivel de TODA la app (sesion 2026-09-27).
    # Antes el candado `automatizacion_en_curso` vivia DENTRO del dialogo
    # de cada caso: dos dialogos distintos tenian candados distintos, y el
    # ciclo automatico en segundo plano, 'Sincronizar con SGDEA' y
    # 'Aprobar' no usaban ninguno -- todos pueden manejar la MISMA pestaña
    # de SGDEA (sgdea_client.pagina, o pages[0] del Chrome por CDP) al
    # mismo tiempo, que es exactamente el sintoma de "Chrome congelado sin
    # error" ya visto en vivo. Ahora todos los flujos que tocan SGDEA
    # chequean y marcan ESTE mismo diccionario; "quien" dice cual flujo lo
    # tiene tomado, para mostrarlo en el aviso.
    automatizacion_sgdea = {"activa": False, "quien": ""}

    def _coordenadas_calibradas():
        """(saludo, cuerpo) calibrados en config, o None si no lo estan.
        Ya no son obligatorios -- ver gestionar_caso_completo."""
        def _par(kx, ky):
            x, y = config_state.get(kx), config_state.get(ky)
            return (x, y) if all(isinstance(v, (int, float)) for v in (x, y)) else None
        return _par("calib_saludo_x", "calib_saludo_y"), _par("calib_cuerpo_x", "calib_cuerpo_y")

    def _sgdea_ocupado_msg() -> str:
        return (
            "Ya hay una automatización de SGDEA corriendo "
            f"({automatizacion_sgdea['quien'] or 'otra tarea'}) -- espera a que termine."
        )
    cfg = load_config()
    config_state = dict(cfg)

    # ------------------------------------------------------------------
    # Cierre limpio de los navegadores PROPIOS al cerrar la ventana --
    # mejora de almacenamiento/rendimiento (sesion 2026-09-25, revision de
    # codigo pedida por Andres): legacy_client y sgdea_client cada uno
    # lanza su PROPIO Chromium (backend/legacy_portal_client.py /
    # backend/sgdea_session.py), cada uno con un metodo cerrar() que ya
    # existe y se usa al RECONECTAR (ver mas abajo, antes de crear un
    # cliente nuevo) -- pero que nunca se llamaba al cerrar la ventana de
    # Insignia. Confirmado en vivo: el Administrador de tareas mostraba
    # varios procesos "chrome.exe" (ms-playwright) sueltos, acumulados de
    # sesiones anteriores donde la app se cerro/reinicio sin pasar por
    # aqui -- cada reinicio dejaba uno mas, sin que nada los liberara. La
    # variable 'client' (PortalClient, portal nuevo) NO necesita esto: es
    # un cliente HTTP, nunca abre navegador.
    #
    # prevent_close=True detiene el cierre real hasta que el cleanup
    # async de abajo termine (el cierre de un navegador es asincrono) --
    # despues se llama page.window.destroy() para completar el cierre.
    # Todo envuelto en try/except (ademas de que cerrar() en si mismo ya
    # es best-effort) para NUNCA dejar la ventana colgada si algo falla
    # durante el cleanup -- se prefiere cerrar la ventana igual, aunque
    # algun navegador quede sin liberar esta vez, a que Andres se quede
    # sin poder cerrar Insignia.
    # ------------------------------------------------------------------
    page.window.prevent_close = True

    async def _on_window_event(e: ft.WindowEvent) -> None:
        if e.type != ft.WindowEventType.CLOSE:
            return
        try:
            if legacy_client is not None:
                await legacy_client.cerrar()
        except Exception:
            pass
        try:
            if sgdea_client is not None:
                await sgdea_client.cerrar()
        except Exception:
            pass
        try:
            if centro_envios is not None:
                await centro_envios.cerrar()
        except Exception:
            pass
        try:
            await page.window.destroy()
        except Exception:
            pass

    page.window.on_event = _on_window_event

    # ------------------------------------------------------------------
    # Controles compartidos
    # ------------------------------------------------------------------
    file_picker = ft.FilePicker()
    page.services.append(file_picker)
    clipboard = ft.Clipboard()
    page.services.append(clipboard)

    conn_status = theme.status_pill("Sin conectar", theme.WARNING)

    email_field = ft.TextField(
        label="Correo del portal",
        value=cfg.get("email", ""),
        color=theme.TEXT_PRIMARY,
        label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
        border_color=theme.GLASS_BORDER,
        focused_border_color=theme.ACCENT_CYAN,
        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
        border_radius=10,
        text_size=13,
        content_padding=ft.Padding(12, 10, 12, 10),
    )
    password_field = ft.TextField(
        label="Contraseña",
        value=cfg.get("password", ""),
        password=True,
        can_reveal_password=True,
        color=theme.TEXT_PRIMARY,
        label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
        border_color=theme.GLASS_BORDER,
        focused_border_color=theme.ACCENT_CYAN,
        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
        border_radius=10,
        text_size=13,
        content_padding=ft.Padding(12, 10, 12, 10),
    )
    remember_switch = ft.Switch(
        label="Recordar en este equipo",
        value=bool(cfg.get("remember", False)),
        active_color=theme.ACCENT_CYAN,
        label_text_style=ft.TextStyle(color=theme.TEXT_SECONDARY, size=12),
    )

    async def do_login(e=None):
        nonlocal client
        email = email_field.value.strip()
        pwd = password_field.value
        if not email or not pwd:
            page.show_dialog(ft.SnackBar(content=ft.Text("Ingresa correo y contraseña."), bgcolor=theme.ERROR))
            return
        conn_status.content.controls[1].value = "Conectando..."
        conn_status.content.controls[0].bgcolor = theme.WARNING
        _actualizar_seguro(conn_status)
        try:
            new_client = PortalClient(email, pwd)
            await asyncio.to_thread(new_client.login)
            client = new_client
            conn_status.content.controls[1].value = f"Conectado ({email})"
            conn_status.content.controls[0].bgcolor = theme.SUCCESS
            if remember_switch.value:
                config_state.update({"email": email, "password": pwd, "remember": True})
            else:
                config_state.update({"email": "", "password": "", "remember": False})
            save_config(config_state)
            page.show_dialog(ft.SnackBar(content=ft.Text("Conectado al portal correctamente."), bgcolor=theme.SUCCESS))
        except LoginError as exc:
            conn_status.content.controls[1].value = "Credenciales invalidas"
            conn_status.content.controls[0].bgcolor = theme.ERROR
            page.show_dialog(ft.SnackBar(content=ft.Text(str(exc)), bgcolor=theme.ERROR))
        except PortalError as exc:
            conn_status.content.controls[1].value = "Sin conexion"
            conn_status.content.controls[0].bgcolor = theme.ERROR
            page.show_dialog(ft.SnackBar(content=ft.Text(str(exc)), bgcolor=theme.ERROR))
        _actualizar_seguro(conn_status)

    login_button = ft.FilledButton(
        content=ft.Row([ft.Icon(ft.Icons.LOGIN, size=16), ft.Text("Conectar")], spacing=6, tight=True),
        on_click=do_login,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_CYAN},
            color={ft.ControlState.DEFAULT: "#001018"},
            shape=ft.RoundedRectangleBorder(radius=10),
        ),
    )

    # ------------------------------------------------------------------
    # Credenciales del Portal ANTIGUO (4-72 legacy, actos notificados
    # hasta el 31 de mayo de 2026). A diferencia del portal nuevo (arriba,
    # API via requests), este abre su PROPIO navegador Chromium (Playwright,
    # no el Chrome de Andres) y hace login automatico con estas credenciales
    # guardadas -- decision explicita de Andres (2026-09). Nunca resuelve
    # un CAPTCHA si aparece: el login simplemente falla con un mensaje claro.
    # ------------------------------------------------------------------
    legacy_conn_status = theme.status_pill("Sin conectar", theme.WARNING)

    legacy_email_field = ft.TextField(
        label="Usuario del portal antiguo",
        value=cfg.get("legacy_email", ""),
        color=theme.TEXT_PRIMARY,
        label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
        border_color=theme.GLASS_BORDER,
        focused_border_color=theme.ACCENT_CYAN,
        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
        border_radius=10,
        text_size=13,
        content_padding=ft.Padding(12, 10, 12, 10),
    )
    legacy_password_field = ft.TextField(
        label="Contraseña",
        value=cfg.get("legacy_password", ""),
        password=True,
        can_reveal_password=True,
        color=theme.TEXT_PRIMARY,
        label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
        border_color=theme.GLASS_BORDER,
        focused_border_color=theme.ACCENT_CYAN,
        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
        border_radius=10,
        text_size=13,
        content_padding=ft.Padding(12, 10, 12, 10),
    )
    legacy_remember_switch = ft.Switch(
        label="Recordar en este equipo",
        value=bool(cfg.get("legacy_remember", False)),
        active_color=theme.ACCENT_CYAN,
        label_text_style=ft.TextStyle(color=theme.TEXT_SECONDARY, size=12),
    )

    # Detalle del ultimo error de conexion/login, PERSISTENTE (a diferencia
    # del SnackBar, que desaparece solo) -- queda visible debajo del pill de
    # estado hasta el siguiente intento, para poder leerlo con calma o
    # copiarlo/mandarlo como captura sin tener que ser rapido con el celular.
    legacy_conn_error_detail = ft.Text(
        "",
        size=11,
        color=theme.ERROR,
        selectable=True,
        visible=False,
    )

    async def do_login_legacy(e=None):
        nonlocal legacy_client
        usuario = legacy_email_field.value.strip()
        pwd = legacy_password_field.value
        if not usuario or not pwd:
            page.show_dialog(ft.SnackBar(content=ft.Text("Ingresa usuario y contraseña del portal antiguo."), bgcolor=theme.ERROR))
            return
        legacy_conn_status.content.controls[1].value = "Conectando..."
        legacy_conn_status.content.controls[0].bgcolor = theme.WARNING
        legacy_conn_error_detail.visible = False
        _actualizar_seguro(legacy_conn_status)
        _actualizar_seguro(legacy_conn_error_detail)
        try:
            if legacy_client is not None:
                await legacy_client.cerrar()
            new_legacy_client = LegacyPortalClient(usuario, pwd, headless=False)

            async def _progreso_conexion_legacy(texto: str):
                # Se usa sobre todo la PRIMERA vez que este equipo procesa
                # con el portal antiguo (descarga automatica de Chromium,
                # ver _asegurar_chromium en legacy_portal_client.py) --
                # sin esto, la UI se veria "colgada" en "Conectando..."
                # varios minutos sin explicar por que.
                legacy_conn_status.content.controls[1].value = texto
                _actualizar_seguro(legacy_conn_status)

            await new_legacy_client.iniciar(on_progreso=_progreso_conexion_legacy)
            legacy_client = new_legacy_client
            legacy_conn_status.content.controls[1].value = f"Conectado ({usuario})"
            legacy_conn_status.content.controls[0].bgcolor = theme.SUCCESS
            if legacy_remember_switch.value:
                config_state.update({"legacy_email": usuario, "legacy_password": pwd, "legacy_remember": True})
            else:
                config_state.update({"legacy_email": "", "legacy_password": "", "legacy_remember": False})
            save_config(config_state)
            page.show_dialog(ft.SnackBar(content=ft.Text("Conectado al portal antiguo correctamente."), bgcolor=theme.SUCCESS))
        except LegacyLoginError as exc:
            # Se imprime SIEMPRE a stdout (queda en dev_run.log via run_dev.bat,
            # que redirige con "> dev_run.log 2>&1") ademas de mostrarse en la
            # UI -- asi el detalle no se pierde aunque no se alcance a leer/
            # capturar el SnackBar o el texto persistente a tiempo.
            print(f"[legacy_login] LegacyLoginError: {exc}")
            legacy_conn_status.content.controls[1].value = "No se pudo iniciar sesion"
            legacy_conn_status.content.controls[0].bgcolor = theme.ERROR
            legacy_conn_error_detail.value = str(exc)
            legacy_conn_error_detail.visible = True
            page.show_dialog(ft.SnackBar(content=ft.Text(str(exc)), bgcolor=theme.ERROR))
        except LegacyPortalError as exc:
            print(f"[legacy_login] LegacyPortalError: {exc}")
            legacy_conn_status.content.controls[1].value = "Sin conexion"
            legacy_conn_status.content.controls[0].bgcolor = theme.ERROR
            legacy_conn_error_detail.value = str(exc)
            legacy_conn_error_detail.visible = True
            page.show_dialog(ft.SnackBar(content=ft.Text(str(exc)), bgcolor=theme.ERROR))
        except Exception as exc:  # noqa: BLE001
            # Cualquier otro error inesperado (ej. algo especifico de correr
            # Playwright dentro del loop de Flet) -- antes se perdia por
            # completo si no era LegacyLoginError/LegacyPortalError; ahora
            # tambien queda visible y en el log.
            print(f"[legacy_login] ERROR INESPERADO ({type(exc).__name__}): {exc}")
            legacy_conn_status.content.controls[1].value = "Sin conexion"
            legacy_conn_status.content.controls[0].bgcolor = theme.ERROR
            legacy_conn_error_detail.value = f"Error inesperado ({type(exc).__name__}): {exc}"
            legacy_conn_error_detail.visible = True
            page.show_dialog(ft.SnackBar(content=ft.Text(f"Error inesperado: {exc}"), bgcolor=theme.ERROR))
        _actualizar_seguro(legacy_conn_status)
        _actualizar_seguro(legacy_conn_error_detail)

    legacy_login_button = ft.FilledButton(
        content=ft.Row([ft.Icon(ft.Icons.LOGIN, size=16), ft.Text("Conectar")], spacing=6, tight=True),
        on_click=do_login_legacy,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_CYAN},
            color={ft.ControlState.DEFAULT: "#001018"},
            shape=ft.RoundedRectangleBorder(radius=10),
        ),
    )

    # ------------------------------------------------------------------
    # Centro de Envios 4-72 (1-oct-2026, guia de Andres): acuses que aun no
    # estan en el portal nuevo (menos de un mes). El portal tiene reCAPTCHA:
    # Insignia abre la ventana y ANDRES inicia sesion; despues busca y baja
    # sola. Nunca escribe la contraseña ni toca el captcha.
    # ------------------------------------------------------------------
    centro_conn_status = theme.status_pill("Sin conectar", theme.WARNING)
    centro_conn_detail = ft.Text("", size=11, color=theme.TEXT_MUTED, selectable=True, visible=False)

    def _estado_centro(texto: str, color, detalle: str = "") -> None:
        centro_conn_status.content.controls[1].value = texto
        centro_conn_status.content.controls[0].bgcolor = color
        centro_conn_detail.value = detalle
        centro_conn_detail.visible = bool(detalle)
        _actualizar_seguro(centro_conn_status, centro_conn_detail)

    async def do_conectar_centro_envios(e=None):
        nonlocal centro_envios
        try:
            if centro_envios is None or not centro_envios.abierto:
                if centro_envios is not None:
                    await centro_envios.cerrar()
                _estado_centro("Abriendo la ventana...", theme.WARNING)
                centro_envios = CentroEnviosClient(_base_dir() / "perfil_centro_envios", headless=False)
                await centro_envios.abrir()
            if await centro_envios.sesion_activa():
                centro_estado["desde"] = centro_estado["desde"] or datetime.now().timestamp()
                _estado_centro("Conectado", theme.SUCCESS)
                return

            async def _progreso(texto):
                _estado_centro("Esperando tu inicio de sesión...", theme.WARNING, texto)

            print("[centro_envios] esperando que Andres inicie sesion en la ventana...", flush=True)
            if await centro_envios.esperar_login(max_s=600, on_progreso=_progreso):
                print("[centro_envios] sesion iniciada.", flush=True)
                centro_estado["desde"] = datetime.now().timestamp()
                _estado_centro("Conectado", theme.SUCCESS)
            else:
                _estado_centro("Sin conectar", theme.ERROR, "No se inició sesión en 10 minutos. Pulsa 'Conectar' de nuevo.")
        except Exception as exc:
            print(f"[centro_envios] ERROR al conectar: {type(exc).__name__}: {exc}", flush=True)
            _estado_centro("Sin conexion", theme.ERROR, f"{type(exc).__name__}: {exc}")
            try:
                if centro_envios is not None:
                    await centro_envios.cerrar()
            except Exception:
                pass
            centro_envios = None

    centro_login_button = ft.FilledButton(
        content=ft.Row([ft.Icon(ft.Icons.LOGIN, size=16), ft.Text("Conectar (abre la ventana)")], spacing=6, tight=True),
        on_click=lambda e: page.run_task(do_conectar_centro_envios),
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_CYAN},
            color={ft.ControlState.DEFAULT: "#001018"},
            shape=ft.RoundedRectangleBorder(radius=10),
        ),
    )

    # ------------------------------------------------------------------
    # Sesion PROPIA de SGDEA (backend/sgdea_session.py) -- pedido
    # explicito de Andres (sesion 2026-09-24): que Insignia se conecte a
    # SGDEA igual que ya se conecta al portal 472 antiguo (arriba), con
    # su propio navegador y login independiente, para poder correr un
    # ciclo automatico en segundo plano sin depender de que Andres tenga
    # su Chrome personal abierto en el tamaño/posicion correctos. Cuando
    # esta conectada, _conectar_si_hace_falta() (por-caso) y
    # _sincronizar_dashboard() la prefieren sobre el CDP-attach al Chrome
    # de Andres; si no esta conectada, todo sigue funcionando exactamente
    # igual que antes (CDP al Chrome de Andres).
    # ------------------------------------------------------------------
    sgdea_conn_status = theme.status_pill("Sin conectar", theme.WARNING)

    sgdea_usuario_field = ft.TextField(
        label="Usuario de dominio SGDEA",
        value=cfg.get("sgdea_usuario", ""),
        color=theme.TEXT_PRIMARY,
        label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
        border_color=theme.GLASS_BORDER,
        focused_border_color=theme.ACCENT_CYAN,
        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
        border_radius=10,
        text_size=13,
        content_padding=ft.Padding(12, 10, 12, 10),
    )
    sgdea_password_field = ft.TextField(
        label="Contraseña",
        value=cfg.get("sgdea_password", ""),
        password=True,
        can_reveal_password=True,
        color=theme.TEXT_PRIMARY,
        label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
        border_color=theme.GLASS_BORDER,
        focused_border_color=theme.ACCENT_CYAN,
        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
        border_radius=10,
        text_size=13,
        content_padding=ft.Padding(12, 10, 12, 10),
    )
    sgdea_remember_switch = ft.Switch(
        label="Recordar en este equipo",
        value=bool(cfg.get("sgdea_remember", False)),
        active_color=theme.ACCENT_CYAN,
        label_text_style=ft.TextStyle(color=theme.TEXT_SECONDARY, size=12),
    )
    sgdea_conn_error_detail = ft.Text("", size=11, color=theme.ERROR, selectable=True, visible=False)
    sgdea_auto_switch = ft.Switch(
        label="Gestión automática en segundo plano (barrido de TODOS los casos cada 10 min; nunca envía a aprobación)",
        value=bool(cfg.get("sgdea_auto_activo", True)),
        active_color=theme.ACCENT_CYAN,
        label_text_style=ft.TextStyle(color=theme.TEXT_SECONDARY, size=12),
    )
    sgdea_auto_status = ft.Text("", size=11, color=theme.TEXT_MUTED, selectable=True)

    async def do_login_sgdea(e=None):
        nonlocal sgdea_client
        usuario = sgdea_usuario_field.value.strip()
        pwd = sgdea_password_field.value
        if not usuario or not pwd:
            page.show_dialog(ft.SnackBar(content=ft.Text("Ingresa usuario y contraseña de SGDEA."), bgcolor=theme.ERROR))
            return
        sgdea_conn_status.content.controls[1].value = "Conectando..."
        sgdea_conn_status.content.controls[0].bgcolor = theme.WARNING
        sgdea_conn_error_detail.visible = False
        _actualizar_seguro(sgdea_conn_status)
        _actualizar_seguro(sgdea_conn_error_detail)
        try:
            if sgdea_client is not None:
                await sgdea_client.cerrar()
            nuevo_sgdea_client = SgdeaSessionClient(usuario, pwd, headless=False)

            async def _progreso_conexion_sgdea(texto: str):
                sgdea_conn_status.content.controls[1].value = texto
                _actualizar_seguro(sgdea_conn_status)

            await nuevo_sgdea_client.iniciar(on_progreso=_progreso_conexion_sgdea)
            sgdea_client = nuevo_sgdea_client
            sgdea_conn_status.content.controls[1].value = f"Conectado ({usuario})"
            sgdea_conn_status.content.controls[0].bgcolor = theme.SUCCESS
            if sgdea_remember_switch.value:
                config_state.update({"sgdea_usuario": usuario, "sgdea_password": pwd, "sgdea_remember": True})
            else:
                config_state.update({"sgdea_usuario": "", "sgdea_password": "", "sgdea_remember": False})
            save_config(config_state)
            page.show_dialog(ft.SnackBar(content=ft.Text("Conectado a SGDEA con sesión propia."), bgcolor=theme.SUCCESS))
        except SgdeaLoginError as exc:
            print(f"[sgdea_login] SgdeaLoginError: {exc}")
            sgdea_conn_status.content.controls[1].value = "No se pudo iniciar sesion"
            sgdea_conn_status.content.controls[0].bgcolor = theme.ERROR
            sgdea_conn_error_detail.value = str(exc)
            sgdea_conn_error_detail.visible = True
            page.show_dialog(ft.SnackBar(content=ft.Text(str(exc)), bgcolor=theme.ERROR))
        except SgdeaSessionError as exc:
            print(f"[sgdea_login] SgdeaSessionError: {exc}")
            sgdea_conn_status.content.controls[1].value = "Sin conexion"
            sgdea_conn_status.content.controls[0].bgcolor = theme.ERROR
            sgdea_conn_error_detail.value = str(exc)
            sgdea_conn_error_detail.visible = True
            page.show_dialog(ft.SnackBar(content=ft.Text(str(exc)), bgcolor=theme.ERROR))
        except Exception as exc:  # noqa: BLE001
            print(f"[sgdea_login] ERROR INESPERADO ({type(exc).__name__}): {exc}")
            sgdea_conn_status.content.controls[1].value = "Sin conexion"
            sgdea_conn_status.content.controls[0].bgcolor = theme.ERROR
            sgdea_conn_error_detail.value = f"Error inesperado ({type(exc).__name__}): {exc}"
            sgdea_conn_error_detail.visible = True
            page.show_dialog(ft.SnackBar(content=ft.Text(f"Error inesperado: {exc}"), bgcolor=theme.ERROR))
        _actualizar_seguro(sgdea_conn_status)
        _actualizar_seguro(sgdea_conn_error_detail)

    sgdea_login_button = ft.FilledButton(
        content=ft.Row([ft.Icon(ft.Icons.LOGIN, size=16), ft.Text("Conectar")], spacing=6, tight=True),
        on_click=lambda e: page.run_task(do_login_sgdea, e),
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_CYAN},
            color={ft.ControlState.DEFAULT: "#001018"},
            shape=ft.RoundedRectangleBorder(radius=10),
        ),
    )

    def _guardar_sgdea_auto(e):
        config_state["sgdea_auto_activo"] = bool(sgdea_auto_switch.value)
        save_config(config_state)

    sgdea_auto_switch.on_change = _guardar_sgdea_auto

    # -- Cuadro_2026 (opcional): permite identificar actos con varios
    # notificados/comunicados con mas precision (nombre de la institucion
    # cuando aplica, y alertar si faltan IDs en el lote de entrada). --
    cuadro_path_value = {"value": cfg.get("cuadro_2026_path", "")}
    cuadro_path_text = ft.Text(
        cuadro_path_value["value"] or "Ningún archivo seleccionado (opcional)",
        size=12,
        color=theme.TEXT_SECONDARY if cuadro_path_value["value"] else theme.TEXT_MUTED,
    )

    def _get_cuadro_index():
        """Devuelve el CuadroIndex cargado (con cache), o None si no hay
        ruta configurada o el archivo no se pudo leer. Nunca lanza."""
        # El Cuadro_2026 MAS NUEVO entre el elegido y los de Descargas: cuando
        # Andres baja uno actualizado, se usa solo (29-sep: 5 masivas se
        # detuvieron por actos del 14 al 23-sep que no estaban en el Cuadro viejo).
        path = _mas_nuevo(cuadro_path_value["value"], _archivo_mas_reciente("Cuadro_2026*.xlsx"))
        if not path:
            return None
        try:
            principal = load_cuadro(path)
        except (CuadroError, Exception):
            return None
        # Cuadro del año anterior (Cuadro_2025*.xlsx en la misma carpeta),
        # para expedientes resueltos en 2025.
        anterior = None
        try:
            candidatos = sorted(
                (c for c in Path(path).parent.glob("Cuadro_2025*.xlsx") if c.is_file() and not c.name.startswith("~$")),
                key=lambda c: c.stat().st_mtime,
            )
            if candidatos:
                anterior = load_cuadro(candidatos[-1])
        except Exception as exc:
            print(f"[cuadro] no se pudo leer el Cuadro_2025: {exc}", flush=True)
        return con_cuadro_anterior(principal, anterior)

    async def pick_cuadro_path(e):
        result = await file_picker.pick_files(
            dialog_title="Elige el archivo Cuadro_2026 (opcional)",
            allowed_extensions=["xlsx", "xls"],
            allow_multiple=False,
        )
        if result:
            cuadro_path_value["value"] = result[0].path
            cuadro_path_text.value = result[0].path
            cuadro_path_text.color = theme.TEXT_SECONDARY
            cuadro_path_text.update()
            config_state["cuadro_2026_path"] = result[0].path
            save_config(config_state)

    async def quitar_cuadro_path(e):
        cuadro_path_value["value"] = ""
        cuadro_path_text.value = "Ningún archivo seleccionado (opcional)"
        cuadro_path_text.color = theme.TEXT_MUTED
        cuadro_path_text.update()
        config_state["cuadro_2026_path"] = ""
        save_config(config_state)

    # -- EstadoMensajes (opcional): reporte de estado de mensajes del
    # sistema de correo/notificaciones (columnas Asunto/Id/Evento), que
    # trae el ID del portal antiguo (4-72) para cada acto -- pedido
    # explicito de Andres (sesion 2026-09-24) para poder, dentro de
    # "Gestionar caso completo", bajar solo el acuse de 472 antiguo que
    # corresponde y adjuntarlo, sin que Andres tenga que buscarlo a mano.
    # Ver backend/estado_mensajes_lookup.py para el detalle del cruce.
    estado_mensajes_path_value = {"value": cfg.get("estado_mensajes_path", "")}
    estado_mensajes_path_text = ft.Text(
        estado_mensajes_path_value["value"] or "Ningún archivo seleccionado (opcional)",
        size=12,
        color=theme.TEXT_SECONDARY if estado_mensajes_path_value["value"] else theme.TEXT_MUTED,
    )

    def _get_estado_mensajes_index():
        """Devuelve el EstadoMensajesIndex cargado (con cache), o None si
        no hay ruta configurada o el archivo no se pudo leer. Nunca
        lanza."""
        path = _mas_nuevo(estado_mensajes_path_value["value"], _archivo_mas_reciente("EstadoMensajes*.csv"))
        if not path:
            return None
        try:
            return load_estado_mensajes(path)
        except (EstadoMensajesError, Exception):
            return None

    # Reporte de Envios (portal NUEVO) -- regla de Andres 28-sep: los actos
    # del 17 de junio de 2026 en adelante se ubican ahi (ver
    # backend/fuentes_acuses.py). Si no se elige a mano, se usa el
    # 'Reporte_Envios*.xlsx' mas reciente junto al .exe o en Descargas.
    reporte_envios_path_value = {"value": cfg.get("reporte_envios_path", "")}

    def _archivo_mas_reciente(patron: str) -> str:
        candidatos = []
        for carpeta in (_base_dir(), Path.home() / "Downloads"):
            try:
                candidatos.extend(carpeta.glob(patron))
            except Exception:
                pass
        candidatos = [c for c in candidatos if c.is_file() and not c.name.startswith("~$")]
        return str(max(candidatos, key=lambda c: c.stat().st_mtime)) if candidatos else ""

    def _mas_nuevo(*rutas) -> str:
        """El archivo mas reciente entre el elegido en Configuración y el que
        se encontro solo: si Andres baja un reporte nuevo a Descargas, se usa
        ese sin tener que volver a elegirlo."""
        existentes = [Path(r) for r in rutas if r and Path(r).is_file()]
        return str(max(existentes, key=lambda p: p.stat().st_mtime)) if existentes else ""

    def _ruta_reporte_envios() -> str:
        return _mas_nuevo(reporte_envios_path_value["value"], _archivo_mas_reciente("Reporte_Envios*.xlsx"))

    def _get_reporte_envios_index():
        path = _ruta_reporte_envios()
        if not path:
            return None
        try:
            return load_reporte_envios(path)
        except Exception as exc:
            print(f"[reporte_envios] no se pudo leer {path!r}: {exc}", flush=True)
            return None

    reporte_envios_path_text = ft.Text(
        _ruta_reporte_envios() or "Ningún archivo (se busca 'Reporte_Envios*.xlsx' junto a Insignia o en Descargas)",
        size=12,
        color=theme.TEXT_SECONDARY if _ruta_reporte_envios() else theme.TEXT_MUTED,
    )

    async def pick_reporte_envios_path(e):
        result = await file_picker.pick_files(
            dialog_title="Elige el 'Reporte_Envios...xlsx' (portal nuevo)",
            allowed_extensions=["xlsx"],
            allow_multiple=False,
        )
        if result:
            reporte_envios_path_value["value"] = result[0].path
            reporte_envios_path_text.value = result[0].path
            reporte_envios_path_text.color = theme.TEXT_SECONDARY
            _actualizar_seguro(reporte_envios_path_text)
            config_state["reporte_envios_path"] = result[0].path
            save_config(config_state)

    async def pick_estado_mensajes_path(e):
        result = await file_picker.pick_files(
            dialog_title="Elige el reporte 'EstadoMensajes...' (opcional)",
            allowed_extensions=["csv"],
            allow_multiple=False,
        )
        if result:
            estado_mensajes_path_value["value"] = result[0].path
            estado_mensajes_path_text.value = result[0].path
            estado_mensajes_path_text.color = theme.TEXT_SECONDARY
            estado_mensajes_path_text.update()
            config_state["estado_mensajes_path"] = result[0].path
            save_config(config_state)

    async def quitar_estado_mensajes_path(e):
        estado_mensajes_path_value["value"] = ""
        estado_mensajes_path_text.value = "Ningún archivo seleccionado (opcional)"
        estado_mensajes_path_text.color = theme.TEXT_MUTED
        estado_mensajes_path_text.update()
        config_state["estado_mensajes_path"] = ""
        save_config(config_state)

    cdp_url_field = ft.TextField(
        label="URL de depuracion remota de Chrome (CDP)",
        value=cfg.get("sgdea_cdp_url", "http://localhost:9222"),
        color=theme.TEXT_PRIMARY,
        label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
        border_color=theme.GLASS_BORDER,
        focused_border_color=theme.ACCENT_CYAN,
        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
        border_radius=10,
        text_size=13,
        content_padding=ft.Padding(12, 10, 12, 10),
    )

    def _guardar_cdp_url(e):
        config_state["sgdea_cdp_url"] = (cdp_url_field.value or "").strip() or "http://localhost:9222"
        save_config(config_state)

    cdp_url_field.on_blur = _guardar_cdp_url

    config_panel = theme.glass_card(
        ft.Column(
            [
                theme.section_title("Credenciales del Portal de Acuses", ft.Icons.VPN_KEY),
                ft.Container(height=6),
                email_field,
                password_field,
                ft.Row([remember_switch, login_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Container(height=10),
                ft.Text(
                    "Las credenciales se guardan solo en este equipo (config_472.json, junto al .exe), "
                    "nunca se envian a ningun otro sitio distinto al portal de 4-72.",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Divider(color=theme.GLASS_BORDER, height=24),
                theme.section_title("Credenciales del Portal ANTIGUO (4-72 legacy)", ft.Icons.HISTORY),
                ft.Text(
                    "Portal donde quedaron los actos administrativos notificados HASTA el 31 de "
                    "mayo de 2026 (antes del portal nuevo de arriba). Este cliente abre su propio "
                    "Chromium e inicia sesion automaticamente con estas credenciales -- nunca "
                    "resuelve un CAPTCHA si aparece uno, el login simplemente falla con aviso claro.",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Container(height=6),
                legacy_email_field,
                legacy_password_field,
                ft.Row([legacy_remember_switch, legacy_login_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Container(height=6),
                legacy_conn_status,
                legacy_conn_error_detail,
                ft.Divider(color=theme.GLASS_BORDER, height=24),
                theme.section_title("Centro de Envíos 4-72 (acuses del último mes)", ft.Icons.MARK_EMAIL_READ),
                ft.Text(
                    "mailcertificadoapp.com: acuses que todavía no aparecen en el portal nuevo "
                    "(menos de 30 días). Tiene reCAPTCHA: 'Conectar' abre su ventana y TÚ inicias "
                    "sesión; después Insignia busca por correo del Cuadro (y número de la resolución) "
                    "y baja los acuses sola. Deja esa ventana abierta mientras trabajas.",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Container(height=6),
                ft.Row([centro_conn_status, centro_login_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                centro_conn_detail,
                ft.Divider(color=theme.GLASS_BORDER, height=24),
                theme.section_title("Sesión propia de SGDEA", ft.Icons.HUB),
                ft.Text(
                    "Igual que el Portal antiguo arriba: Insignia abre su propio navegador e "
                    "inicia sesión en SGDEA con estas credenciales, sin depender de que tengas "
                    "tu Chrome personal abierto. Con esto conectado, 'Generar respuesta', "
                    "'Gestionar caso completo', 'Sincronizar con SGDEA' y la gestión automática "
                    "de abajo la usan a ella en vez de tu Chrome. Nunca resuelve un CAPTCHA.",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Container(height=6),
                sgdea_usuario_field,
                sgdea_password_field,
                ft.Row([sgdea_remember_switch, sgdea_login_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Container(height=6),
                sgdea_conn_status,
                sgdea_conn_error_detail,
                ft.Container(height=10),
                sgdea_auto_switch,
                ft.Text(
                    "Cada 10 minutos (mientras la sesión propia esté conectada): busca casos "
                    "nuevos en 'Gestionar', y para los que puede reconocer con confianza "
                    "(Tratamiento y categoría inferibles) corre 'Gestionar caso completo' sola. "
                    "Nunca envía a aprobación por su cuenta -- deja cada caso en Memorandos, "
                    "'PARA APROBAR', esperando tu revisión y tu clic en 'Aprobar y enviar'.",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                sgdea_auto_status,
                ft.Divider(color=theme.GLASS_BORDER, height=24),
                theme.section_title("Cuadro_2026 (opcional)", ft.Icons.TABLE_CHART),
                ft.Text(
                    "Si lo seleccionas, se usa para: identificar el nombre de la institucion en "
                    "Autos con varios notificados/comunicados (en vez del nombre de quien firma por "
                    "ella), y para alertar en el reporte si el numero de acuses procesados es menor "
                    "al de notificados/comunicados que Cuadro_2026 registra para ese acto. Sin este "
                    "archivo, el programa sigue funcionando igual, solo sin esas dos ayudas.",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Container(height=4),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN, size=16), ft.Text("Elegir archivo")], spacing=6, tight=True),
                            on_click=pick_cuadro_path,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        ft.TextButton(
                            content=ft.Row([ft.Icon(ft.Icons.CLOSE, size=14), ft.Text("Quitar")], spacing=4, tight=True),
                            on_click=quitar_cuadro_path,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.TEXT_MUTED}),
                        ),
                        cuadro_path_text,
                    ],
                    spacing=10,
                ),
                ft.Divider(color=theme.GLASS_BORDER, height=24),
                theme.section_title("Reporte EstadoMensajes (opcional)", ft.Icons.HISTORY_EDU),
                ft.Text(
                    "CSV que exporta el sistema de correo/notificaciones (columnas Asunto/Id/Evento). "
                    "Si lo seleccionas, 'Gestionar caso completo' lo usa para ubicar automáticamente "
                    "el ID del portal antiguo (4-72) del acto de cada caso, bajar su acuse y "
                    "adjuntarlo -- sin este archivo, ese paso simplemente se salta (no bloquea el resto).",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Container(height=4),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN, size=16), ft.Text("Elegir archivo")], spacing=6, tight=True),
                            on_click=pick_estado_mensajes_path,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        ft.TextButton(
                            content=ft.Row([ft.Icon(ft.Icons.CLOSE, size=14), ft.Text("Quitar")], spacing=4, tight=True),
                            on_click=quitar_estado_mensajes_path,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.TEXT_MUTED}),
                        ),
                        estado_mensajes_path_text,
                    ],
                    spacing=10,
                ),
                ft.Divider(color=theme.GLASS_BORDER, height=24),
                theme.section_title("Reporte de Envíos (portal nuevo)", ft.Icons.MARK_EMAIL_READ),
                ft.Text(
                    "De dónde sale cada acuse (regla de Andrés): actos hasta el 31/05/2026 -> EstadoMensajes "
                    "(portal antiguo); del 17/06/2026 en adelante -> Reporte_Envios (portal nuevo, que publica "
                    "con ~1 mes de retraso); del 1 al 16 de junio y lo enviado hace menos de un mes -> descarga "
                    "manual: deja el PDF en 'adjuntos_manuales\\<radicado>' junto a Insignia y pulsa "
                    "'Reintentar automático'.",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Container(height=4),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN, size=16), ft.Text("Elegir archivo")], spacing=6, tight=True),
                            on_click=pick_reporte_envios_path,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        reporte_envios_path_text,
                    ],
                    spacing=10,
                ),
                ft.Divider(color=theme.GLASS_BORDER, height=24),
                theme.section_title("Memorandos / SGDEA", ft.Icons.FACT_CHECK),
                ft.Text(
                    "Para 'Aprobar y enviar' en la pestaña Memorandos, esta URL debe apuntar a "
                    "un Chrome que ya tengas abierto en modo de depuracion remota "
                    "(--remote-debugging-port) y en el que ya iniciaste sesion en SGDEA. El "
                    "aplicativo nunca inicia sesion por su cuenta.",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Container(height=4),
                cdp_url_field,
                ft.Container(height=20),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
        expand=True,
    )

    # ------------------------------------------------------------------
    # Panel INDIVIDUAL
    # ------------------------------------------------------------------
    individual_id_field = ft.TextField(
        label="ID del correo (pegar aqui)",
        hint_text="Ej: F927BFFC84A8F7A891718D6F3552B45DBC3C019A",
        color=theme.TEXT_PRIMARY,
        label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
        border_color=theme.GLASS_BORDER,
        focused_border_color=theme.ACCENT_CYAN,
        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
        border_radius=10,
        text_size=13,
        content_padding=ft.Padding(12, 10, 12, 10),
    )
    individual_folder_text = ft.Text("Ninguna carpeta seleccionada", size=12, color=theme.TEXT_MUTED)
    individual_folder_path = {"value": ""}

    async def pick_individual_folder(e):
        path = await file_picker.get_directory_path(dialog_title="Elige la carpeta destino")
        if path:
            individual_folder_path["value"] = path
            individual_folder_text.value = path
            individual_folder_text.color = theme.TEXT_SECONDARY
            individual_folder_text.update()

    individual_result = ft.Column([], spacing=6)

    async def procesar_individual(e):
        if client is None:
            page.show_dialog(ft.SnackBar(content=ft.Text("Primero conecta con el portal en Configuración."), bgcolor=theme.WARNING))
            return
        msg_id = individual_id_field.value.strip()
        folder = individual_folder_path["value"]
        if not msg_id:
            page.show_dialog(ft.SnackBar(content=ft.Text("Pega un ID de correo."), bgcolor=theme.WARNING))
            return
        if not folder:
            page.show_dialog(ft.SnackBar(content=ft.Text("Elige una carpeta destino."), bgcolor=theme.WARNING))
            return

        individual_result.controls = [ft.Row([ft.ProgressRing(width=16, height=16, stroke_width=2, color=theme.ACCENT_CYAN), ft.Text("Consultando...", color=theme.TEXT_SECONDARY, size=12)], spacing=8)]
        individual_result.update()

        zip_bytes = None
        try:
            zip_bytes = await asyncio.to_thread(client.download_zip_bytes, msg_id)
            expediente = await asyncio.to_thread(process_zip, zip_bytes)
            out_path = unique_path(Path(folder), expediente.final_filename)
            out_path.write_bytes(expediente.pdf_bytes)

            rows = [
                ("Tipo", expediente.tipo),
                ("Numero", expediente.numero or "-"),
                ("Fecha", expediente.fecha or "-"),
                ("Titular", expediente.nombre_titular or "-"),
                ("Destinatario", expediente.destinatario_email or "-"),
                ("Archivo", out_path.name),
            ]
            info_rows = [
                ft.Row([ft.Text(k, size=11, color=theme.TEXT_MUTED, width=110), ft.Text(v, size=12, color=theme.TEXT_PRIMARY)])
                for k, v in rows
            ]
            warn_texts = list(expediente.warnings)
            cuadro_idx = _get_cuadro_index()
            if cuadro_idx is not None:
                esperados = cuadro_idx.notificados_esperados(expediente.tipo, expediente.numero)
                if len(esperados) > 1:
                    warn_texts.append(
                        f"Cuadro_2026 indica que este acto tiene {len(esperados)} notificados/comunicados "
                        "en total; este expediente individual solo incluye este ID. Para reunirlos todos en "
                        "un mismo expediente usa Masivo (con todos los IDs) o Acuses Manuales."
                    )
            warn_rows = [
                ft.Row([ft.Icon(ft.Icons.WARNING_AMBER, size=14, color=theme.WARNING), ft.Text(w, size=11, color=theme.WARNING)])
                for w in warn_texts
            ]
            individual_result.controls = [
                ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, color=theme.SUCCESS, size=18), ft.Text("Expediente generado", color=theme.SUCCESS, weight=ft.FontWeight.W_600)]),
                *info_rows,
                *warn_rows,
            ]
        except NotFoundError:
            individual_result.controls = [ft.Row([ft.Icon(ft.Icons.ERROR, color=theme.ERROR, size=18), ft.Text("ID no encontrado en el portal", color=theme.ERROR)])]
        except (PortalError, ExtractionError) as exc:
            debug_note = ""
            if isinstance(exc, ExtractionError) and zip_bytes is not None:
                try:
                    debug_path = unique_path(Path(folder), f"{msg_id}_RAW_DEBUG.zip")
                    debug_path.write_bytes(zip_bytes)
                    debug_note = f" (ZIP original guardado como {debug_path.name} para revisar)"
                except Exception:
                    pass
            individual_result.controls = [ft.Row([ft.Icon(ft.Icons.ERROR, color=theme.ERROR, size=18), ft.Text(str(exc) + debug_note, color=theme.ERROR, size=12)])]
        except Exception:
            individual_result.controls = [ft.Row([ft.Icon(ft.Icons.ERROR, color=theme.ERROR, size=18), ft.Text("Error inesperado, revisa el ID e intenta de nuevo.", color=theme.ERROR, size=12)])]
        individual_result.update()

    individual_panel = theme.glass_card(
        ft.Column(
            [
                theme.section_title("Consulta Individual", ft.Icons.SEARCH),
                ft.Container(height=6),
                individual_id_field,
                ft.Row(
                    [
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN, size=16), ft.Text("Elegir carpeta")], spacing=6, tight=True),
                            on_click=pick_individual_folder,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        individual_folder_text,
                    ],
                    spacing=10,
                ),
                ft.Container(height=6),
                ft.FilledButton(
                    content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=18), ft.Text("Procesar")], spacing=6, tight=True),
                    on_click=procesar_individual,
                    style=ft.ButtonStyle(bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_VIOLET}, color={ft.ControlState.DEFAULT: "#0A0014"}, shape=ft.RoundedRectangleBorder(radius=10)),
                ),
                ft.Divider(color=theme.GLASS_BORDER, height=24),
                individual_result,
            ],
            spacing=10,
        ),
    )

    # ------------------------------------------------------------------
    # Panel INDIVIDUAL (Portal Antiguo) -- pedido explicito de Andres
    # (sesion 2026-09-24: "el nuevo boton de 472 antiguo para individuales
    # en Insignia, si no lo tienes habilitado, habilitalo"). No existia
    # ningun equivalente para un solo ID contra el portal antiguo (solo
    # "Masivo (Portal Antiguo)", que pide un Excel completo) -- este panel
    # reutiliza EXACTAMENTE las mismas piezas ya probadas en vivo ahi
    # (legacy_client.buscar_y_descargar_testigo + extract_acuse_from_pdf +
    # merge_acuses, con una lista de un solo acuse), solo que para un ID
    # pegado a mano, igual que "Consulta Individual" hace para el portal
    # nuevo arriba.
    # ------------------------------------------------------------------
    individual_legacy_id_field = ft.TextField(
        label="ID del mensaje (portal antiguo, pegar aqui)",
        hint_text="Ej: 1363712",
        color=theme.TEXT_PRIMARY,
        label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
        border_color=theme.GLASS_BORDER,
        focused_border_color=theme.ACCENT_CYAN,
        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
        border_radius=10,
        text_size=13,
        content_padding=ft.Padding(12, 10, 12, 10),
    )
    individual_legacy_email_field = ft.TextField(
        label="Email destinatario (opcional, ayuda a precisar si hay varias filas)",
        color=theme.TEXT_PRIMARY,
        label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
        border_color=theme.GLASS_BORDER,
        focused_border_color=theme.ACCENT_CYAN,
        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
        border_radius=10,
        text_size=13,
        content_padding=ft.Padding(12, 10, 12, 10),
    )
    individual_legacy_folder_text = ft.Text("Ninguna carpeta seleccionada", size=12, color=theme.TEXT_MUTED)
    individual_legacy_folder_path = {"value": ""}

    async def pick_individual_legacy_folder(e):
        path = await file_picker.get_directory_path(dialog_title="Elige la carpeta destino")
        if path:
            individual_legacy_folder_path["value"] = path
            individual_legacy_folder_text.value = path
            individual_legacy_folder_text.color = theme.TEXT_SECONDARY
            individual_legacy_folder_text.update()

    individual_legacy_result = ft.Column([], spacing=6)

    async def procesar_individual_legacy(e):
        if legacy_client is None:
            page.show_dialog(ft.SnackBar(content=ft.Text("Primero conecta con el portal antiguo en Configuración."), bgcolor=theme.WARNING))
            return
        msg_id = individual_legacy_id_field.value.strip()
        email = individual_legacy_email_field.value.strip()
        folder = individual_legacy_folder_path["value"]
        if not msg_id:
            page.show_dialog(ft.SnackBar(content=ft.Text("Pega un ID de mensaje del portal antiguo."), bgcolor=theme.WARNING))
            return
        if not folder:
            page.show_dialog(ft.SnackBar(content=ft.Text("Elige una carpeta destino."), bgcolor=theme.WARNING))
            return

        individual_legacy_result.controls = [ft.Row([ft.ProgressRing(width=16, height=16, stroke_width=2, color=theme.ACCENT_CYAN), ft.Text("Consultando el portal antiguo...", color=theme.TEXT_SECONDARY, size=12)], spacing=8)]
        individual_legacy_result.update()

        try:
            pdf_bytes = await legacy_client.buscar_y_descargar_testigo(msg_id, email or None)
            acuse = await asyncio.to_thread(extract_acuse_from_pdf, pdf_bytes, msg_id)
            cuadro_idx = _get_cuadro_index()
            expediente = await asyncio.to_thread(merge_acuses, [acuse], cuadro_idx)
            out_path = unique_path(Path(folder), expediente.final_filename)
            out_path.write_bytes(expediente.pdf_bytes)

            rows = [
                ("Tipo", expediente.tipo),
                ("Numero", expediente.numero or "-"),
                ("Fecha", expediente.fecha or "-"),
                ("Titular", expediente.nombre_titular or "-"),
                ("Archivo", out_path.name),
            ]
            info_rows = [
                ft.Row([ft.Text(k, size=11, color=theme.TEXT_MUTED, width=110), ft.Text(v, size=12, color=theme.TEXT_PRIMARY)])
                for k, v in rows
            ]
            warn_rows = [
                ft.Row([ft.Icon(ft.Icons.WARNING_AMBER, size=14, color=theme.WARNING), ft.Text(w, size=11, color=theme.WARNING)])
                for w in expediente.warnings
            ]
            individual_legacy_result.controls = [
                ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, color=theme.SUCCESS, size=18), ft.Text("Expediente generado", color=theme.SUCCESS, weight=ft.FontWeight.W_600)]),
                *info_rows,
                *warn_rows,
            ]
        except LegacyNotFoundError:
            individual_legacy_result.controls = [ft.Row([ft.Icon(ft.Icons.ERROR, color=theme.ERROR, size=18), ft.Text("ID no encontrado en el portal antiguo", color=theme.ERROR)])]
        except (LegacyPortalError, ExtractionError) as exc:
            individual_legacy_result.controls = [ft.Row([ft.Icon(ft.Icons.ERROR, color=theme.ERROR, size=18), ft.Text(str(exc), color=theme.ERROR, size=12)])]
        except Exception as exc:
            individual_legacy_result.controls = [ft.Row([ft.Icon(ft.Icons.ERROR, color=theme.ERROR, size=18), ft.Text(f"Error inesperado ({type(exc).__name__}): {exc}", color=theme.ERROR, size=12)])]
        individual_legacy_result.update()

    individual_legacy_panel = theme.glass_card(
        ft.Column(
            [
                theme.section_title("Consulta Individual (Portal Antiguo)", ft.Icons.HISTORY),
                ft.Text(
                    "Para un solo ID del portal antiguo (4-72) -- descarga el acuse/testigo y arma el "
                    "expediente con el mismo formato que Masivo (Portal Antiguo). Necesita estar "
                    "conectado al portal antiguo en Configuración.",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Container(height=6),
                individual_legacy_id_field,
                individual_legacy_email_field,
                ft.Row(
                    [
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN, size=16), ft.Text("Elegir carpeta")], spacing=6, tight=True),
                            on_click=pick_individual_legacy_folder,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        individual_legacy_folder_text,
                    ],
                    spacing=10,
                ),
                ft.Container(height=6),
                ft.FilledButton(
                    content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=18), ft.Text("Procesar")], spacing=6, tight=True),
                    on_click=procesar_individual_legacy,
                    style=ft.ButtonStyle(bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_VIOLET}, color={ft.ControlState.DEFAULT: "#0A0014"}, shape=ft.RoundedRectangleBorder(radius=10)),
                ),
                ft.Divider(color=theme.GLASS_BORDER, height=24),
                individual_legacy_result,
            ],
            spacing=10,
        ),
    )

    individual_view = ft.Column(
        [individual_panel, ft.Container(height=16), individual_legacy_panel],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    # ------------------------------------------------------------------
    # Panel MASIVO
    # ------------------------------------------------------------------
    masivo_excel_path = {"value": ""}
    masivo_excel_text = ft.Text("Ningun Excel seleccionado", size=12, color=theme.TEXT_MUTED)
    masivo_folder_path = {"value": ""}
    masivo_folder_text = ft.Text("Ninguna carpeta seleccionada", size=12, color=theme.TEXT_MUTED)

    progress_bar = ft.ProgressBar(value=0, color=theme.ACCENT_CYAN, bgcolor=ft.Colors.with_opacity(0.08, "#FFFFFF"), border_radius=6, bar_height=8)
    progress_text = ft.Text("0 / 0", size=12, color=theme.TEXT_SECONDARY)
    stats_row = ft.Row(
        [
            theme.status_pill("OK: 0", theme.SUCCESS),
            theme.status_pill("Fallidos: 0", theme.ERROR),
            theme.status_pill("No encontrados: 0", theme.WARNING),
        ],
        spacing=8,
    )
    log_list = ft.ListView([], spacing=4, height=220, auto_scroll=True)
    is_processing = {"value": False}

    async def pick_masivo_excel(e):
        result = await file_picker.pick_files(
            dialog_title="Elige el Excel con los IDs",
            allowed_extensions=["xlsx", "xls"],
            allow_multiple=False,
        )
        if result:
            masivo_excel_path["value"] = result[0].path
            masivo_excel_text.value = result[0].name
            masivo_excel_text.color = theme.TEXT_SECONDARY
            masivo_excel_text.update()

    async def pick_masivo_folder(e):
        path = await file_picker.get_directory_path(dialog_title="Elige la carpeta destino")
        if path:
            masivo_folder_path["value"] = path
            masivo_folder_text.value = path
            masivo_folder_text.color = theme.TEXT_SECONDARY
            masivo_folder_text.update()

    async def _log(text: str, color: str = None):
        card = theme.log_result_card(text, color)
        log_list.controls.append(card)
        if len(log_list.controls) > 500:
            log_list.controls.pop(0)
        log_list.update()
        await asyncio.sleep(0.02)
        theme.reveal_log_card(card)
        log_list.update()

    async def procesar_masivo(e):
        if is_processing["value"]:
            return
        if client is None:
            page.show_dialog(ft.SnackBar(content=ft.Text("Primero conecta con el portal en Configuración."), bgcolor=theme.WARNING))
            return
        excel_path = masivo_excel_path["value"]
        folder = masivo_folder_path["value"]
        if not excel_path or not folder:
            page.show_dialog(ft.SnackBar(content=ft.Text("Elige el Excel de IDs y la carpeta destino."), bgcolor=theme.WARNING))
            return

        is_processing["value"] = True
        log_list.controls.clear()
        log_list.update()
        ok_count = fail_count = notfound_count = 0

        try:
            rows_in = await asyncio.to_thread(read_ids_from_excel, excel_path)
        except Exception as exc:
            page.show_dialog(ft.SnackBar(content=ft.Text(f"No se pudo leer el Excel: {exc}"), bgcolor=theme.ERROR))
            is_processing["value"] = False
            return

        total = len(rows_in)
        await _log(f"Se encontraron {total} IDs unicos en el Excel.", theme.ACCENT_CYAN)
        progress_bar.value = 0
        progress_text.value = f"0 / {total}"
        progress_bar.update()
        progress_text.update()

        report_rows = []
        out_folder = Path(folder)

        # Fase 1: descargar y extraer cada acuse por separado (sin fusionar
        # todavia), agrupando por (tipo, numero) del acto administrativo.
        # Un mismo Resolucion/Auto puede tener varios notificados/comunicados
        # (cada uno con su propio ID/acuse); en ese caso se fusionan en un
        # solo expediente en la Fase 2.
        grupos: dict[tuple[str, str], list[tuple[str, object, object]]] = {}

        for i, row in enumerate(rows_in, start=1):
            msg_id = row.message_id
            try:
                zip_bytes = await asyncio.to_thread(client.download_zip_bytes, msg_id)
                acuse = await asyncio.to_thread(extract_acuse, zip_bytes)
                key = (acuse.tipo, acuse.numero or f"__{msg_id}")
                grupos.setdefault(key, []).append((msg_id, row, acuse))
                ok_count += 1
                await _log(f"[OK] {msg_id[:12]}...  {acuse.tipo} {acuse.numero or '-'}", theme.SUCCESS)
            except NotFoundError:
                notfound_count += 1
                report_rows.append({"tipo": "", "numero": "", "fecha": "", "nombre": "", "destinatario": row.destinatario, "id_mensaje": msg_id, "archivo": "", "estado": "NO ENCONTRADO", "observacion": "El ID no arrojo resultados en el portal."})
                await _log(f"[NO ENCONTRADO] {msg_id[:12]}...", theme.WARNING)
            except (PortalError, ExtractionError) as exc:
                fail_count += 1
                report_rows.append({"tipo": "", "numero": "", "fecha": "", "nombre": "", "destinatario": row.destinatario, "id_mensaje": msg_id, "archivo": "", "estado": "ERROR", "observacion": str(exc)})
                await _log(f"[ERROR] {msg_id[:12]}...  {exc}", theme.ERROR)
            except Exception as exc:
                fail_count += 1
                report_rows.append({"tipo": "", "numero": "", "fecha": "", "nombre": "", "destinatario": row.destinatario, "id_mensaje": msg_id, "archivo": "", "estado": "ERROR", "observacion": f"Error inesperado: {exc}"})
                await _log(f"[ERROR] {msg_id[:12]}...  error inesperado", theme.ERROR)

            progress_bar.value = i / total
            progress_text.value = f"{i} / {total}"
            stats_row.controls[0] = theme.status_pill(f"OK: {ok_count}", theme.SUCCESS)
            stats_row.controls[1] = theme.status_pill(f"Fallidos: {fail_count}", theme.ERROR)
            stats_row.controls[2] = theme.status_pill(f"No encontrados: {notfound_count}", theme.WARNING)
            progress_bar.update()
            progress_text.update()
            stats_row.update()
            await asyncio.sleep(0)

        # Fase 2: armar el expediente final de cada grupo (1 o varios
        # notificados/comunicados), en el orden Resolucion/Auto -> Acta ->
        # Acuse, repetido cronologicamente por cada notificado.
        cuadro_idx = _get_cuadro_index()
        if cuadro_path_value["value"] and cuadro_idx is None:
            await _log("Aviso: no se pudo leer el Cuadro_2026 configurado; se continua sin ese cruce.", theme.WARNING)
        await _log(f"Armando {len(grupos)} expediente(s) a partir de {ok_count} acuse(s) descargados...", theme.ACCENT_CYAN)
        expedientes_ok = 0
        for key, items in grupos.items():
            acuses = [a for (_mid, _row, a) in items]
            try:
                expediente = await asyncio.to_thread(merge_acuses, acuses, cuadro_idx)
                out_path = unique_path(out_folder, expediente.final_filename)
                out_path.write_bytes(expediente.pdf_bytes)
                expedientes_ok += 1

                multi_note = (
                    f"Expediente con {expediente.n_notificados} notificados/comunicados fusionados."
                    if expediente.n_notificados > 1 else ""
                )
                if cuadro_idx is not None:
                    esperados = cuadro_idx.notificados_esperados(expediente.tipo, expediente.numero)
                    if esperados and len(esperados) > expediente.n_notificados:
                        alerta = (
                            f"ALERTA: Cuadro_2026 registra {len(esperados)} notificados/comunicados "
                            f"esperados para este acto, pero solo se procesaron {expediente.n_notificados} "
                            f"(revisa si falta algun ID en el Excel de entrada)."
                        )
                        multi_note = (multi_note + " " if multi_note else "") + alerta
                        await _log(f"[ALERTA] {expediente.tipo} {expediente.numero}: {alerta}", theme.WARNING)
                for msg_id, row, acuse in items:
                    observacion_parts = list(acuse.warnings)
                    if multi_note:
                        observacion_parts.append(multi_note)
                    if row.estado_entrega and row.estado_entrega.strip().lower() == "fallido":
                        observacion_parts.append(
                            "Entrega FALLIDA segun Reporte de Envios (se descarga igual como evidencia)."
                        )
                    report_rows.append(
                        {
                            "tipo": expediente.tipo,
                            "numero": expediente.numero,
                            "fecha": expediente.fecha,
                            "nombre": acuse.nombre_titular or expediente.nombre_titular,
                            "destinatario": acuse.destinatario_email or row.destinatario,
                            "id_mensaje": msg_id,
                            "archivo": out_path.name,
                            "estado": "OK",
                            "observacion": "; ".join(p for p in observacion_parts if p),
                        }
                    )
                if expediente.n_notificados > 1:
                    await _log(f"[FUSIONADO] {expediente.tipo} {expediente.numero}: {expediente.n_notificados} notificados -> {out_path.name}", theme.ACCENT_CYAN)
                else:
                    await _log(f"[ARCHIVO] {out_path.name}", theme.SUCCESS)
            except Exception as exc:
                fail_count += len(items)
                for msg_id, row, acuse in items:
                    report_rows.append({"tipo": acuse.tipo, "numero": acuse.numero, "fecha": acuse.fecha, "nombre": acuse.nombre_titular, "destinatario": acuse.destinatario_email or row.destinatario, "id_mensaje": msg_id, "archivo": "", "estado": "ERROR", "observacion": f"Error al fusionar/guardar el expediente: {exc}"})
                await _log(f"[ERROR] no se pudo armar el expediente {key[0]} {key[1]}: {exc}", theme.ERROR)

        stats_row.controls[1] = theme.status_pill(f"Fallidos: {fail_count}", theme.ERROR)
        stats_row.update()

        report_path = unique_path(out_folder, "Reporte_Procesamiento_472.xlsx")
        await asyncio.to_thread(write_report_excel, str(report_path), report_rows)
        await _log(f"Reporte final guardado: {report_path.name}", theme.ACCENT_CYAN)
        page.show_dialog(ft.SnackBar(content=ft.Text(f"Lote terminado: {expedientes_ok} expediente(s) generado(s) ({ok_count} acuses), {fail_count} con error, {notfound_count} no encontrados."), bgcolor=theme.SUCCESS))
        is_processing["value"] = False

    masivo_panel = theme.glass_card(
        ft.Column(
            [
                theme.section_title("Procesamiento Masivo", ft.Icons.DYNAMIC_FEED),
                ft.Container(height=6),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.UPLOAD_FILE, size=16), ft.Text("Elegir Excel de IDs")], spacing=6, tight=True),
                            on_click=pick_masivo_excel,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        masivo_excel_text,
                    ],
                    spacing=10,
                ),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN, size=16), ft.Text("Elegir carpeta destino")], spacing=6, tight=True),
                            on_click=pick_masivo_folder,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        masivo_folder_text,
                    ],
                    spacing=10,
                ),
                ft.Container(height=6),
                ft.FilledButton(
                    content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=18), ft.Text("Procesar Lote")], spacing=6, tight=True),
                    on_click=lambda e: page.run_task(procesar_masivo, e),
                    style=ft.ButtonStyle(bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_VIOLET}, color={ft.ControlState.DEFAULT: "#0A0014"}, shape=ft.RoundedRectangleBorder(radius=10)),
                ),
                ft.Container(height=10),
                ft.Row([progress_bar, progress_text], spacing=10),
                ft.Container(height=6),
                stats_row,
                ft.Container(height=6),
                ft.Container(
                    content=log_list,
                    bgcolor=ft.Colors.with_opacity(0.35, "#000000"),
                    border_radius=10,
                    padding=10,
                    border=ft.Border.all(1, theme.GLASS_BORDER),
                ),
            ],
            spacing=8,
        ),
    )

    # ------------------------------------------------------------------
    # Panel MASIVO -- PORTAL ANTIGUO (4-72 legacy, hasta el 31 de mayo de
    # 2026). Mismo flujo que el Masivo de arriba (Excel de IDs -> expediente
    # unificado y renombrado), pero descargando el "testigo" via
    # LegacyPortalClient (su propio Chromium/Playwright) en vez del cliente
    # REST del portal nuevo, y extrayendo con extract_acuse_from_pdf en vez
    # de extract_acuse (porque aqui se descarga un PDF suelto, no un ZIP).
    # ------------------------------------------------------------------
    masivo_legacy_excel_path = {"value": ""}
    masivo_legacy_excel_text = ft.Text("Ningun Excel seleccionado", size=12, color=theme.TEXT_MUTED)
    masivo_legacy_folder_path = {"value": ""}
    masivo_legacy_folder_text = ft.Text("Ninguna carpeta seleccionada", size=12, color=theme.TEXT_MUTED)

    progress_bar_legacy = ft.ProgressBar(value=0, color=theme.ACCENT_CYAN, bgcolor=ft.Colors.with_opacity(0.08, "#FFFFFF"), border_radius=6, bar_height=8)
    progress_text_legacy = ft.Text("0 / 0", size=12, color=theme.TEXT_SECONDARY)
    stats_row_legacy = ft.Row(
        [
            theme.status_pill("OK: 0", theme.SUCCESS),
            theme.status_pill("Fallidos: 0", theme.ERROR),
            theme.status_pill("No encontrados: 0", theme.WARNING),
        ],
        spacing=8,
    )
    log_list_legacy = ft.ListView([], spacing=4, height=220, auto_scroll=True)
    is_processing_legacy = {"value": False}

    async def pick_masivo_legacy_excel(e):
        result = await file_picker.pick_files(
            dialog_title="Elige el Excel con los IDs (portal antiguo)",
            allowed_extensions=["xlsx", "xls"],
            allow_multiple=False,
        )
        if result:
            masivo_legacy_excel_path["value"] = result[0].path
            masivo_legacy_excel_text.value = result[0].name
            masivo_legacy_excel_text.color = theme.TEXT_SECONDARY
            masivo_legacy_excel_text.update()

    async def pick_masivo_legacy_folder(e):
        path = await file_picker.get_directory_path(dialog_title="Elige la carpeta destino")
        if path:
            masivo_legacy_folder_path["value"] = path
            masivo_legacy_folder_text.value = path
            masivo_legacy_folder_text.color = theme.TEXT_SECONDARY
            masivo_legacy_folder_text.update()

    async def _log_legacy(text: str, color: str = None):
        card = theme.log_result_card(text, color)
        log_list_legacy.controls.append(card)
        if len(log_list_legacy.controls) > 500:
            log_list_legacy.controls.pop(0)
        log_list_legacy.update()
        await asyncio.sleep(0.02)
        theme.reveal_log_card(card)
        log_list_legacy.update()

    async def procesar_masivo_legacy(e):
        if is_processing_legacy["value"]:
            return
        if legacy_client is None:
            page.show_dialog(ft.SnackBar(content=ft.Text("Primero conecta con el portal antiguo en Configuración."), bgcolor=theme.WARNING))
            return
        excel_path = masivo_legacy_excel_path["value"]
        folder = masivo_legacy_folder_path["value"]
        if not excel_path or not folder:
            page.show_dialog(ft.SnackBar(content=ft.Text("Elige el Excel de IDs y la carpeta destino."), bgcolor=theme.WARNING))
            return

        is_processing_legacy["value"] = True
        log_list_legacy.controls.clear()
        log_list_legacy.update()
        ok_count = fail_count = notfound_count = 0

        try:
            rows_in = await asyncio.to_thread(read_ids_from_excel, excel_path)
        except Exception as exc:
            page.show_dialog(ft.SnackBar(content=ft.Text(f"No se pudo leer el Excel: {exc}"), bgcolor=theme.ERROR))
            is_processing_legacy["value"] = False
            return

        total = len(rows_in)
        await _log_legacy(f"Se encontraron {total} IDs unicos en el Excel.", theme.ACCENT_CYAN)
        progress_bar_legacy.value = 0
        progress_text_legacy.value = f"0 / {total}"
        progress_bar_legacy.update()
        progress_text_legacy.update()

        report_rows = []
        out_folder = Path(folder)

        # Fase 1: descargar (via el navegador propio del portal antiguo) y
        # extraer cada acuse por separado, agrupando por (tipo, numero) --
        # igual que el Masivo del portal nuevo. A diferencia del Masivo
        # nuevo (que habla con una API y puede lanzar muchas peticiones a
        # la vez sin abrir nada visual), este cliente controla un
        # navegador real -- por eso aqui se reparte el lote entre VARIAS
        # pestanas del mismo navegador/sesion ya logueada, corriendo en
        # paralelo, en vez de una pestana sola en serie (que a ~1 minuto
        # por ID, segun la ultima prueba, harian un lote de 1000 IDs
        # inviable -- mas de 16 horas).
        grupos: dict[tuple[str, str], list[tuple[str, object, object]]] = {}

        n_workers = min(MAX_WORKERS_LEGACY, total) or 1
        await _log_legacy(
            f"Abriendo {n_workers} pestana(s) de trabajo en paralelo en el portal antiguo...",
            theme.ACCENT_CYAN,
        )
        paginas_trabajo = []
        for _ in range(n_workers):
            try:
                paginas_trabajo.append(await legacy_client.abrir_pagina_trabajo())
            except Exception as exc:
                await _log_legacy(
                    f"Aviso: no se pudo abrir una pestana de trabajo adicional ({exc}); "
                    "se continua con las que si se lograron abrir.",
                    theme.WARNING,
                )
                break
        if not paginas_trabajo:
            page.show_dialog(ft.SnackBar(content=ft.Text("No se pudo abrir ninguna pestana de trabajo en el portal antiguo."), bgcolor=theme.ERROR))
            is_processing_legacy["value"] = False
            return
        if len(paginas_trabajo) < n_workers:
            await _log_legacy(f"Se sigue con {len(paginas_trabajo)} pestana(s) en vez de {n_workers}.", theme.WARNING)

        cola_ids: asyncio.Queue = asyncio.Queue()
        for row in rows_in:
            cola_ids.put_nowait(row)

        completados = 0

        async def _reportar_avance():
            nonlocal completados
            completados += 1
            progress_bar_legacy.value = completados / total
            progress_text_legacy.value = f"{completados} / {total}"
            stats_row_legacy.controls[0] = theme.status_pill(f"OK: {ok_count}", theme.SUCCESS)
            stats_row_legacy.controls[1] = theme.status_pill(f"Fallidos: {fail_count}", theme.ERROR)
            stats_row_legacy.controls[2] = theme.status_pill(f"No encontrados: {notfound_count}", theme.WARNING)
            progress_bar_legacy.update()
            progress_text_legacy.update()
            stats_row_legacy.update()

        async def _trabajador(pagina_trabajo):
            nonlocal ok_count, fail_count, notfound_count
            while True:
                try:
                    row = cola_ids.get_nowait()
                except asyncio.QueueEmpty:
                    return
                msg_id = row.message_id
                try:
                    pdf_bytes = await legacy_client.buscar_y_descargar_testigo(
                        msg_id, row.destinatario, pagina=pagina_trabajo
                    )
                    acuse = await asyncio.to_thread(extract_acuse_from_pdf, pdf_bytes, msg_id)
                    key = (acuse.tipo, acuse.numero or f"__{msg_id}")
                    grupos.setdefault(key, []).append((msg_id, row, acuse))
                    ok_count += 1
                    await _log_legacy(f"[OK] {msg_id[:12]}...  {acuse.tipo} {acuse.numero or '-'}", theme.SUCCESS)
                except LegacyNotFoundError:
                    notfound_count += 1
                    report_rows.append({"tipo": "", "numero": "", "fecha": "", "nombre": "", "destinatario": row.destinatario, "id_mensaje": msg_id, "archivo": "", "estado": "NO ENCONTRADO", "observacion": "El ID no arrojo resultados en el portal antiguo."})
                    await _log_legacy(f"[NO ENCONTRADO] {msg_id[:12]}...", theme.WARNING)
                except (LegacyPortalError, ExtractionError) as exc:
                    fail_count += 1
                    report_rows.append({"tipo": "", "numero": "", "fecha": "", "nombre": "", "destinatario": row.destinatario, "id_mensaje": msg_id, "archivo": "", "estado": "ERROR", "observacion": str(exc)})
                    await _log_legacy(f"[ERROR] {msg_id[:12]}...  {exc}", theme.ERROR)
                except Exception as exc:
                    fail_count += 1
                    report_rows.append({"tipo": "", "numero": "", "fecha": "", "nombre": "", "destinatario": row.destinatario, "id_mensaje": msg_id, "archivo": "", "estado": "ERROR", "observacion": f"Error inesperado: {exc}"})
                    await _log_legacy(f"[ERROR] {msg_id[:12]}...  error inesperado", theme.ERROR)

                await _reportar_avance()

        await asyncio.gather(*(_trabajador(p) for p in paginas_trabajo))

        for p in paginas_trabajo:
            try:
                await p.close()
            except Exception:
                pass

        # Fase 2: armar el expediente final de cada grupo -- identico al
        # Masivo del portal nuevo (misma funcion merge_acuses, mismo cruce
        # opcional con Cuadro_2026 para alertar si falta algun ID).
        cuadro_idx = _get_cuadro_index()
        if cuadro_path_value["value"] and cuadro_idx is None:
            await _log_legacy("Aviso: no se pudo leer el Cuadro_2026 configurado; se continua sin ese cruce.", theme.WARNING)
        await _log_legacy(f"Armando {len(grupos)} expediente(s) a partir de {ok_count} acuse(s) descargados...", theme.ACCENT_CYAN)
        expedientes_ok = 0
        for key, items in grupos.items():
            acuses = [a for (_mid, _row, a) in items]
            try:
                expediente = await asyncio.to_thread(merge_acuses, acuses, cuadro_idx)
                out_path = unique_path(out_folder, expediente.final_filename)
                out_path.write_bytes(expediente.pdf_bytes)
                expedientes_ok += 1

                multi_note = (
                    f"Expediente con {expediente.n_notificados} notificados/comunicados fusionados."
                    if expediente.n_notificados > 1 else ""
                )
                if cuadro_idx is not None:
                    esperados = cuadro_idx.notificados_esperados(expediente.tipo, expediente.numero)
                    if esperados and len(esperados) > expediente.n_notificados:
                        alerta = (
                            f"ALERTA: Cuadro_2026 registra {len(esperados)} notificados/comunicados "
                            f"esperados para este acto, pero solo se procesaron {expediente.n_notificados} "
                            f"(revisa si falta algun ID en el Excel de entrada)."
                        )
                        multi_note = (multi_note + " " if multi_note else "") + alerta
                        await _log_legacy(f"[ALERTA] {expediente.tipo} {expediente.numero}: {alerta}", theme.WARNING)
                for msg_id, row, acuse in items:
                    observacion_parts = list(acuse.warnings)
                    if multi_note:
                        observacion_parts.append(multi_note)
                    if row.estado_entrega and row.estado_entrega.strip().lower() == "fallido":
                        observacion_parts.append(
                            "Entrega FALLIDA segun Reporte de Envios (se descarga igual como evidencia)."
                        )
                    report_rows.append(
                        {
                            "tipo": expediente.tipo,
                            "numero": expediente.numero,
                            "fecha": expediente.fecha,
                            "nombre": acuse.nombre_titular or expediente.nombre_titular,
                            "destinatario": acuse.destinatario_email or row.destinatario,
                            "id_mensaje": msg_id,
                            "archivo": out_path.name,
                            "estado": "OK",
                            "observacion": "; ".join(p for p in observacion_parts if p),
                        }
                    )
                if expediente.n_notificados > 1:
                    await _log_legacy(f"[FUSIONADO] {expediente.tipo} {expediente.numero}: {expediente.n_notificados} notificados -> {out_path.name}", theme.ACCENT_CYAN)
                else:
                    await _log_legacy(f"[ARCHIVO] {out_path.name}", theme.SUCCESS)
            except Exception as exc:
                fail_count += len(items)
                for msg_id, row, acuse in items:
                    report_rows.append({"tipo": acuse.tipo, "numero": acuse.numero, "fecha": acuse.fecha, "nombre": acuse.nombre_titular, "destinatario": acuse.destinatario_email or row.destinatario, "id_mensaje": msg_id, "archivo": "", "estado": "ERROR", "observacion": f"Error al fusionar/guardar el expediente: {exc}"})
                await _log_legacy(f"[ERROR] no se pudo armar el expediente {key[0]} {key[1]}: {exc}", theme.ERROR)

        stats_row_legacy.controls[1] = theme.status_pill(f"Fallidos: {fail_count}", theme.ERROR)
        stats_row_legacy.update()

        report_path = unique_path(out_folder, "Reporte_Procesamiento_472_PortalAntiguo.xlsx")
        await asyncio.to_thread(write_report_excel, str(report_path), report_rows)
        await _log_legacy(f"Reporte final guardado: {report_path.name}", theme.ACCENT_CYAN)
        page.show_dialog(ft.SnackBar(content=ft.Text(f"Lote terminado: {expedientes_ok} expediente(s) generado(s) ({ok_count} acuses), {fail_count} con error, {notfound_count} no encontrados."), bgcolor=theme.SUCCESS))
        is_processing_legacy["value"] = False

    masivo_legacy_panel = theme.glass_card(
        ft.Column(
            [
                theme.section_title("Procesamiento Masivo (Portal Antiguo)", ft.Icons.HISTORY),
                ft.Text(
                    "Igual que Masivo, pero busca cada ID en el portal antiguo 4-72 (actos "
                    "notificados hasta el 31 de mayo de 2026). Conecta primero en Configuración.",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Container(height=6),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.UPLOAD_FILE, size=16), ft.Text("Elegir Excel de IDs")], spacing=6, tight=True),
                            on_click=pick_masivo_legacy_excel,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        masivo_legacy_excel_text,
                    ],
                    spacing=10,
                ),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN, size=16), ft.Text("Elegir carpeta destino")], spacing=6, tight=True),
                            on_click=pick_masivo_legacy_folder,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        masivo_legacy_folder_text,
                    ],
                    spacing=10,
                ),
                ft.Container(height=6),
                ft.FilledButton(
                    content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=18), ft.Text("Procesar Lote")], spacing=6, tight=True),
                    on_click=lambda e: page.run_task(procesar_masivo_legacy, e),
                    style=ft.ButtonStyle(bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_VIOLET}, color={ft.ControlState.DEFAULT: "#0A0014"}, shape=ft.RoundedRectangleBorder(radius=10)),
                ),
                ft.Container(height=10),
                ft.Row([progress_bar_legacy, progress_text_legacy], spacing=10),
                ft.Container(height=6),
                stats_row_legacy,
                ft.Container(height=6),
                ft.Container(
                    content=log_list_legacy,
                    bgcolor=ft.Colors.with_opacity(0.35, "#000000"),
                    border_radius=10,
                    padding=10,
                    border=ft.Border.all(1, theme.GLASS_BORDER),
                ),
            ],
            spacing=8,
        ),
    )

    # ------------------------------------------------------------------
    # Panel CARGAR ZIP (acuses descargados manualmente, sin portal)
    # ------------------------------------------------------------------
    ziploc_source_path = {"value": "", "kind": ""}
    ziploc_source_text = ft.Text("Ninguna carpeta ni ZIP seleccionado", size=12, color=theme.TEXT_MUTED)
    ziploc_folder_path = {"value": ""}
    ziploc_folder_text = ft.Text("Ninguna carpeta seleccionada", size=12, color=theme.TEXT_MUTED)

    ziploc_progress_bar = ft.ProgressBar(value=0, color=theme.ACCENT_CYAN, bgcolor=ft.Colors.with_opacity(0.08, "#FFFFFF"), border_radius=6, bar_height=8)
    ziploc_progress_text = ft.Text("0 / 0", size=12, color=theme.TEXT_SECONDARY)
    ziploc_stats_row = ft.Row(
        [
            theme.status_pill("OK: 0", theme.SUCCESS),
            theme.status_pill("Fallidos: 0", theme.ERROR),
        ],
        spacing=8,
    )
    ziploc_log_list = ft.ListView([], spacing=4, height=220, auto_scroll=True)
    ziploc_is_processing = {"value": False}

    async def pick_ziploc_carpeta(e):
        path = await file_picker.get_directory_path(
            dialog_title="Elige la carpeta con los acuses (.zip y/o .pdf sueltos)"
        )
        if path:
            ziploc_source_path["value"] = path
            ziploc_source_path["kind"] = "carpeta"
            ziploc_source_text.value = f"Carpeta: {path}"
            ziploc_source_text.color = theme.TEXT_SECONDARY
            ziploc_source_text.update()

    async def pick_ziploc_zip(e):
        result = await file_picker.pick_files(
            dialog_title="Elige un archivo .zip o .pdf (un solo acuse, o un ZIP con varios adentro)",
            allowed_extensions=["zip", "pdf"],
            allow_multiple=False,
        )
        if result:
            ziploc_source_path["value"] = result[0].path
            ziploc_source_path["kind"] = "archivo"
            ziploc_source_text.value = f"Archivo: {result[0].name}"
            ziploc_source_text.color = theme.TEXT_SECONDARY
            ziploc_source_text.update()

    async def pick_ziploc_folder(e):
        path = await file_picker.get_directory_path(dialog_title="Elige la carpeta destino")
        if path:
            ziploc_folder_path["value"] = path
            ziploc_folder_text.value = path
            ziploc_folder_text.color = theme.TEXT_SECONDARY
            ziploc_folder_text.update()

    async def _log_ziploc(text: str, color: str = None):
        card = theme.log_result_card(text, color)
        ziploc_log_list.controls.append(card)
        if len(ziploc_log_list.controls) > 500:
            ziploc_log_list.controls.pop(0)
        ziploc_log_list.update()
        await asyncio.sleep(0.02)
        theme.reveal_log_card(card)
        ziploc_log_list.update()

    async def procesar_ziploc(e):
        if ziploc_is_processing["value"]:
            return
        src = ziploc_source_path["value"]
        folder = ziploc_folder_path["value"]
        if not src:
            page.show_dialog(ft.SnackBar(content=ft.Text("Elige la carpeta o el ZIP con los acuses."), bgcolor=theme.WARNING))
            return
        if not folder:
            page.show_dialog(ft.SnackBar(content=ft.Text("Elige una carpeta destino."), bgcolor=theme.WARNING))
            return

        ziploc_is_processing["value"] = True
        ziploc_log_list.controls.clear()
        ziploc_log_list.update()
        ok_count = fail_count = 0

        # Reune por separado los acuses empaquetados en .zip (formato del
        # portal 4-72) y los .pdf sueltos (acuses descargados uno por uno,
        # a mano, de otro portal) -- ambos pueden convivir en la misma
        # carpeta. Solo se falla si NINGUNO de los dos formatos aparece.
        p = Path(src)
        zip_sources: list[tuple[str, bytes]] = []
        pdf_sources: list[tuple[str, bytes]] = []
        try:
            if p.is_dir():
                zip_sources = await asyncio.to_thread(collect_zip_sources, src)
                pdf_sources = await asyncio.to_thread(collect_pdf_sources, src)
            elif p.is_file() and p.suffix.lower() == ".zip":
                zip_sources = await asyncio.to_thread(collect_zip_sources, src)
            elif p.is_file() and p.suffix.lower() == ".pdf":
                pdf_sources = await asyncio.to_thread(collect_pdf_sources, src)
            else:
                page.show_dialog(ft.SnackBar(content=ft.Text("La ruta elegida no es una carpeta, ni un .zip, ni un .pdf."), bgcolor=theme.ERROR))
                ziploc_is_processing["value"] = False
                return
        except LocalZipError as exc:
            page.show_dialog(ft.SnackBar(content=ft.Text(str(exc)), bgcolor=theme.ERROR))
            ziploc_is_processing["value"] = False
            return
        except Exception as exc:
            page.show_dialog(ft.SnackBar(content=ft.Text(f"No se pudo leer la carpeta/archivo: {exc}"), bgcolor=theme.ERROR))
            ziploc_is_processing["value"] = False
            return

        sources = [(origen, data, "zip") for origen, data in zip_sources] + [
            (origen, data, "pdf") for origen, data in pdf_sources
        ]
        if not sources:
            page.show_dialog(
                ft.SnackBar(
                    content=ft.Text(
                        "No se encontro ningun acuse reconocible: se esperaba al menos un .zip "
                        "(con un .eml adentro) o un .pdf de acuse en la carpeta/archivo elegido."
                    ),
                    bgcolor=theme.ERROR,
                )
            )
            ziploc_is_processing["value"] = False
            return

        total = len(sources)
        await _log_ziploc(
            f"Se encontraron {total} acuse(s): {len(zip_sources)} en .zip y {len(pdf_sources)} en .pdf sueltos.",
            theme.ACCENT_CYAN,
        )
        ziploc_progress_bar.value = 0
        ziploc_progress_text.value = f"0 / {total}"
        ziploc_progress_bar.update()
        ziploc_progress_text.update()

        report_rows = []
        out_folder = Path(folder)

        # Fase 1: extraer cada acuse por separado (sin fusionar todavia),
        # agrupando por (tipo, numero) del acto administrativo, igual que en
        # Masivo -- para detectar actos con varios notificados/comunicados.
        grupos: dict[tuple[str, str], list[tuple[str, object]]] = {}

        for i, (origen, data, kind) in enumerate(sources, start=1):
            try:
                if kind == "zip":
                    acuse = await asyncio.to_thread(extract_acuse, data)
                else:
                    acuse = await asyncio.to_thread(extract_acuse_from_pdf, data, origen)
                key = (acuse.tipo, acuse.numero or f"__{origen}")
                grupos.setdefault(key, []).append((origen, acuse))
                ok_count += 1
                await _log_ziploc(f"[OK] {origen}  {acuse.tipo} {acuse.numero or '-'}", theme.SUCCESS)
            except (ExtractionError, Exception) as exc:
                fail_count += 1
                report_rows.append({"tipo": "", "numero": "", "fecha": "", "nombre": "", "destinatario": "", "origen": origen, "archivo": "", "estado": "ERROR", "observacion": str(exc)})
                await _log_ziploc(f"[ERROR] {origen}  {exc}", theme.ERROR)

            ziploc_progress_bar.value = i / total
            ziploc_progress_text.value = f"{i} / {total}"
            ziploc_stats_row.controls[0] = theme.status_pill(f"OK: {ok_count}", theme.SUCCESS)
            ziploc_stats_row.controls[1] = theme.status_pill(f"Fallidos: {fail_count}", theme.ERROR)
            ziploc_progress_bar.update()
            ziploc_progress_text.update()
            ziploc_stats_row.update()
            await asyncio.sleep(0)

        # Fase 2: armar el expediente final de cada grupo (1 o varios
        # notificados/comunicados), en el orden Resolucion/Auto -> Acta ->
        # Acuse, repetido cronologicamente por cada notificado.
        cuadro_idx = _get_cuadro_index()
        if cuadro_path_value["value"] and cuadro_idx is None:
            await _log_ziploc("Aviso: no se pudo leer el Cuadro_2026 configurado; se continua sin ese cruce.", theme.WARNING)
        await _log_ziploc(f"Armando {len(grupos)} expediente(s) a partir de {ok_count} acuse(s)...", theme.ACCENT_CYAN)
        expedientes_ok = 0
        for key, items in grupos.items():
            acuses = [a for (_origen, a) in items]
            try:
                expediente = await asyncio.to_thread(merge_acuses, acuses, cuadro_idx)
                out_path = unique_path(out_folder, expediente.final_filename)
                out_path.write_bytes(expediente.pdf_bytes)
                expedientes_ok += 1

                multi_note = (
                    f"Expediente con {expediente.n_notificados} notificados/comunicados fusionados."
                    if expediente.n_notificados > 1 else ""
                )
                if cuadro_idx is not None:
                    esperados = cuadro_idx.notificados_esperados(expediente.tipo, expediente.numero)
                    if esperados and len(esperados) > expediente.n_notificados:
                        alerta = (
                            f"ALERTA: Cuadro_2026 registra {len(esperados)} notificados/comunicados "
                            f"esperados para este acto, pero solo se procesaron {expediente.n_notificados} "
                            f"(revisa si falta algun acuse en la carpeta/ZIP de entrada)."
                        )
                        multi_note = (multi_note + " " if multi_note else "") + alerta
                        await _log_ziploc(f"[ALERTA] {expediente.tipo} {expediente.numero}: {alerta}", theme.WARNING)
                for origen, acuse in items:
                    observacion_parts = list(acuse.warnings)
                    if multi_note:
                        observacion_parts.append(multi_note)
                    report_rows.append(
                        {
                            "tipo": expediente.tipo,
                            "numero": expediente.numero,
                            "fecha": expediente.fecha,
                            "nombre": acuse.nombre_titular or expediente.nombre_titular,
                            "destinatario": acuse.destinatario_email,
                            "origen": origen,
                            "archivo": out_path.name,
                            "estado": "OK",
                            "observacion": "; ".join(p for p in observacion_parts if p),
                        }
                    )
                if expediente.n_notificados > 1:
                    await _log_ziploc(f"[FUSIONADO] {expediente.tipo} {expediente.numero}: {expediente.n_notificados} notificados -> {out_path.name}", theme.ACCENT_CYAN)
                else:
                    await _log_ziploc(f"[ARCHIVO] {out_path.name}", theme.SUCCESS)
            except Exception as exc:
                fail_count += len(items)
                for origen, acuse in items:
                    report_rows.append({"tipo": acuse.tipo, "numero": acuse.numero, "fecha": acuse.fecha, "nombre": acuse.nombre_titular, "destinatario": acuse.destinatario_email, "origen": origen, "archivo": "", "estado": "ERROR", "observacion": f"Error al fusionar/guardar el expediente: {exc}"})
                await _log_ziploc(f"[ERROR] no se pudo armar el expediente {key[0]} {key[1]}: {exc}", theme.ERROR)

        ziploc_stats_row.controls[1] = theme.status_pill(f"Fallidos: {fail_count}", theme.ERROR)
        ziploc_stats_row.update()

        report_path = unique_path(out_folder, "Reporte_ZIP_Local_472.xlsx")
        await asyncio.to_thread(write_local_report_excel, str(report_path), report_rows)
        await _log_ziploc(f"Reporte final guardado: {report_path.name}", theme.ACCENT_CYAN)
        page.show_dialog(ft.SnackBar(content=ft.Text(f"Lote terminado: {expedientes_ok} expediente(s) generado(s) ({ok_count} acuses), {fail_count} con error."), bgcolor=theme.SUCCESS))
        ziploc_is_processing["value"] = False

    ziploc_panel = theme.glass_card(
        ft.Column(
            [
                theme.section_title("Cargar Acuses Manuales (sin portal)", ft.Icons.FOLDER_ZIP),
                ft.Container(height=6),
                ft.Text(
                    "Para acuses descargados a mano desde otro sitio (por ejemplo cuando el "
                    "portal de 4-72 aun no los tiene indexados, o desde un portal distinto). "
                    "No requiere conexion al portal: arma el expediente (Resolucion/Auto + "
                    "Acta + Acuse) igual que en Individual/Masivo, y lo renombra con el mismo "
                    "patron. Acepta una carpeta con .zip (como los que descarga el portal "
                    "4-72), una carpeta con .pdf sueltos (un PDF por acuse, descargado uno por "
                    "uno), o una mezcla de ambos en la misma carpeta.",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Container(height=6),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.FOLDER_ZIP, size=16), ft.Text("Elegir carpeta (.zip y/o .pdf)")], spacing=6, tight=True),
                            on_click=pick_ziploc_carpeta,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.UPLOAD_FILE, size=16), ft.Text("...o un solo archivo")], spacing=6, tight=True),
                            on_click=pick_ziploc_zip,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                    ],
                    spacing=10,
                ),
                ziploc_source_text,
                ft.Container(height=4),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN, size=16), ft.Text("Elegir carpeta destino")], spacing=6, tight=True),
                            on_click=pick_ziploc_folder,
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        ziploc_folder_text,
                    ],
                    spacing=10,
                ),
                ft.Container(height=6),
                ft.FilledButton(
                    content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=18), ft.Text("Procesar")], spacing=6, tight=True),
                    on_click=lambda e: page.run_task(procesar_ziploc, e),
                    style=ft.ButtonStyle(bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_VIOLET}, color={ft.ControlState.DEFAULT: "#0A0014"}, shape=ft.RoundedRectangleBorder(radius=10)),
                ),
                ft.Container(height=10),
                ft.Row([ziploc_progress_bar, ziploc_progress_text], spacing=10),
                ft.Container(height=6),
                ziploc_stats_row,
                ft.Container(height=6),
                ft.Container(
                    content=ziploc_log_list,
                    bgcolor=ft.Colors.with_opacity(0.35, "#000000"),
                    border_radius=10,
                    padding=10,
                    border=ft.Border.all(1, theme.GLASS_BORDER),
                ),
            ],
            spacing=8,
        ),
    )

    # ------------------------------------------------------------------
    # Panel MEMORANDOS (cola de revision/aprobacion de Memorando respuesta)
    # ------------------------------------------------------------------
    memorandos_state: dict = {"casos": []}
    memorandos_list_view = ft.Column([], spacing=8)
    memorandos_empty_text = ft.Text(
        "No hay memorandos pendientes de revision por ahora.",
        size=12,
        color=theme.TEXT_MUTED,
    )

    def _estado_pill(estado: str) -> ft.Container:
        color = {
            "pendiente": theme.WARNING,
            "enviado": theme.SUCCESS,
            "error": theme.ERROR,
        }.get(estado, theme.TEXT_MUTED)
        return theme.status_pill(estado.capitalize(), color)

    def _abrir_revision(radicado: str):
        try:
            caso = casos_pendientes.obtener_caso(radicado)
        except casos_pendientes.CasosPendientesError as exc:
            page.show_dialog(ft.SnackBar(content=ft.Text(f"No se pudo leer casos_pendientes.json: {exc}"), bgcolor=theme.ERROR))
            return
        if caso is None:
            page.show_dialog(ft.SnackBar(content=ft.Text(f"El caso {radicado} ya no esta en la cola."), bgcolor=theme.WARNING))
            _refrescar_memorandos()
            return

        adjunto_existe = bool(caso.adjunto_path) and Path(caso.adjunto_path).exists()

        estado_texto = ft.Text(
            caso.notas_error or "",
            size=12,
            color=theme.ERROR if caso.notas_error else theme.TEXT_SECONDARY,
        )

        if caso.estado == "enviado":
            texto_boton_inicial = "Ya enviado"
        elif caso.estado == "error":
            texto_boton_inicial = "Reintentar envio"
        else:
            texto_boton_inicial = "Aprobar y enviar"

        boton_enviar = ft.FilledButton(
            content=ft.Row([ft.Icon(ft.Icons.SEND, size=16), ft.Text(texto_boton_inicial)], spacing=6, tight=True),
            disabled=(caso.estado == "enviado"),
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: theme.SUCCESS},
                color={ft.ControlState.DEFAULT: "#00160B"},
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
        )

        async def _confirmar_envio(e):
            if automatizacion_sgdea["activa"]:
                page.show_dialog(ft.SnackBar(content=ft.Text(_sgdea_ocupado_msg()), bgcolor=theme.WARNING))
                return
            automatizacion_sgdea["activa"] = True
            automatizacion_sgdea["quien"] = f"Aprobar y enviar {caso.radicado}"
            boton_enviar.disabled = True
            boton_enviar.content = ft.Row(
                [ft.ProgressRing(width=14, height=14, stroke_width=2, color="#00160B"), ft.Text("Enviando...")],
                spacing=6,
                tight=True,
            )
            estado_texto.value = ""
            boton_enviar.update()
            estado_texto.update()

            cdp_url = config_state.get("sgdea_cdp_url") or "http://localhost:9222"
            try:
                resultado = await sgdea_automation.ejecutar_flujo_aprobacion(
                    caso.radicado, caso.mensaje_aprobacion, cdp_url,
                    page=(sgdea_client.pagina if sgdea_client is not None and sgdea_client.conectado else None),
                )
            except Exception as exc:
                resultado = sgdea_automation.ResultadoAutomatizacion(ok=False, pasos_completados=[], warnings=[f"Error inesperado: {exc}"])
            finally:
                automatizacion_sgdea["activa"] = False
                automatizacion_sgdea["quien"] = ""

            if resultado.ok:
                casos_pendientes.marcar_enviado(caso.radicado)
                page.pop_dialog()
                _refrescar_memorandos()
                page.show_dialog(ft.SnackBar(content=ft.Text(f"Enviado a aprobacion: {caso.radicado}"), bgcolor=theme.SUCCESS))
            else:
                mensaje_error = "; ".join(resultado.warnings) or "Error desconocido durante el envio."
                casos_pendientes.marcar_error(caso.radicado, mensaje_error)
                boton_enviar.disabled = False
                boton_enviar.content = ft.Row([ft.Icon(ft.Icons.SEND, size=16), ft.Text("Reintentar envio")], spacing=6, tight=True)
                estado_texto.value = f"No se pudo enviar: {mensaje_error}"
                estado_texto.color = theme.ERROR
                boton_enviar.update()
                estado_texto.update()
                _refrescar_memorandos()

        boton_enviar.on_click = lambda e: page.run_task(_confirmar_envio, e)

        warnings_col = ft.Column(
            [
                ft.Row([ft.Icon(ft.Icons.WARNING_AMBER, size=13, color=theme.WARNING), ft.Text(w, size=11, color=theme.WARNING, expand=True)])
                for w in caso.warnings
            ],
            spacing=4,
        )

        def _fila_resumen(label: str, value: str) -> ft.Row:
            return ft.Row(
                [
                    ft.Text(label, size=11, color=theme.TEXT_MUTED, width=130),
                    ft.Text(value or "-", size=12, color=theme.TEXT_PRIMARY, expand=True),
                ]
            )

        resumen_col = ft.Column(
            [
                _fila_resumen("Destinatario", caso.destinatario_nombre),
                _fila_resumen("Cargo", caso.destinatario_cargo),
                _fila_resumen("Subdireccion", caso.destinatario_subdireccion),
                _fila_resumen("Asunto", caso.asunto),
                _fila_resumen("Saludo", caso.saludo),
                ft.Divider(color=theme.GLASS_BORDER, height=16),
                ft.Text("Cuerpo (resumen guardado localmente, sin re-verificar en vivo):", size=11, color=theme.TEXT_MUTED),
                ft.Container(
                    content=ft.Text(caso.cuerpo_parrafo or "(vacio)", size=12, color=theme.TEXT_PRIMARY, selectable=True),
                    padding=10,
                    bgcolor=ft.Colors.with_opacity(0.3, "#000000"),
                    border_radius=8,
                    border=ft.Border.all(1, theme.GLASS_BORDER),
                ),
                ft.Divider(color=theme.GLASS_BORDER, height=16),
                ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.CHECK_CIRCLE if adjunto_existe else ft.Icons.ERROR,
                            size=15,
                            color=theme.SUCCESS if adjunto_existe else theme.ERROR,
                        ),
                        ft.Text(
                            f"Adjunto: {caso.adjunto_nombre}"
                            + ("" if adjunto_existe else " (no se encuentra el archivo local -- revisar)"),
                            size=12,
                            color=theme.TEXT_PRIMARY if adjunto_existe else theme.ERROR,
                            expand=True,
                        ),
                    ],
                    spacing=6,
                ),
                *([warnings_col] if caso.warnings else []),
                ft.Divider(color=theme.GLASS_BORDER, height=16),
                ft.Text("Mensaje que se enviara a la Dra. Diana al aprobar:", size=11, color=theme.TEXT_MUTED),
                ft.Text(caso.mensaje_aprobacion, size=12, italic=True, color=theme.TEXT_SECONDARY),
                ft.Container(height=4),
                estado_texto,
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # ---- Visor de la peticion / del adjunto (pedido de Andres, 30-sep):
        # ver lo que pidieron al lado de la respuesta, con scroll, y aprobar
        # ahi mismo con mas certeza.
        ancho_total = int(min(1320, max(900, (page.width or 1300) - 60)))
        alto_total = int(max(420, (page.height or 760) - 200))
        ancho_resumen = 430
        ancho_visor = ancho_total - ancho_resumen - 24
        documentos = []
        ruta_pet = visor_pdf.ruta_peticion(_base_dir() / "peticiones_descargadas", caso.radicado)
        if ruta_pet is not None:
            documentos.append(("Petición", str(ruta_pet)))
        documentos += visor_pdf.documentos_de_adjunto(caso.adjunto_path)
        fuentes = {str(k): fuente for k, (_etq, fuente) in enumerate(documentos)}
        doc_actual = {"key": "0" if documentos else None, "token": 0}

        paginas_col = ft.Column([], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        visor_estado = ft.Text("", size=11, color=theme.TEXT_MUTED)

        def _mensaje_visor(texto: str, color=None) -> None:
            paginas_col.controls = [ft.Container(ft.Text(texto, size=12, color=color or theme.TEXT_MUTED), padding=20)]

        async def _cargar_documento(key: str) -> None:
            doc_actual["token"] += 1
            token = doc_actual["token"]
            fuente = fuentes.get(key)
            if fuente is None:
                return
            paginas_col.controls = [ft.Container(ft.Row([ft.ProgressRing(width=16, height=16, stroke_width=2),
                                                         ft.Text("Cargando el PDF...", size=12, color=theme.TEXT_MUTED)],
                                                        spacing=8), padding=20)]
            visor_estado.value = ""
            try:
                paginas_col.update()
                visor_estado.update()
            except Exception:
                pass
            try:
                imagenes, total = await asyncio.to_thread(visor_pdf.renderizar, fuente)
            except Exception as exc:
                if token == doc_actual["token"]:
                    _mensaje_visor(f"No se pudo mostrar el PDF aquí ({exc}). Usa 'Abrir en el visor de Windows'.", theme.WARNING)
                    try:
                        paginas_col.update()
                    except Exception:
                        pass
                return
            if token != doc_actual["token"]:
                return  # se eligio otro documento mientras cargaba
            paginas_col.controls = [
                ft.Container(
                    ft.Image(src=png, width=ancho_visor - 40, fit=ft.BoxFit.FIT_WIDTH),
                    border_radius=4,
                    bgcolor="#FFFFFF",
                )
                for png in imagenes
            ]
            visor_estado.value = (f"{total} página(s)" if len(imagenes) == total
                                  else f"se muestran {len(imagenes)} de {total} páginas")
            try:
                paginas_col.update()
                visor_estado.update()
            except Exception:
                pass

        def _elegir_documento(e) -> None:
            doc_actual["key"] = selector_doc.value
            page.run_task(_cargar_documento, selector_doc.value)

        def _abrir_fuera(e) -> None:
            fuente = fuentes.get(doc_actual["key"] or "")
            if fuente is None:
                return
            error = visor_pdf.abrir_con_windows(fuente)
            if error:
                page.show_dialog(ft.SnackBar(content=ft.Text(error), bgcolor=theme.ERROR))

        selector_doc = ft.Dropdown(
            options=[ft.dropdown.Option(key=str(k), text=etq) for k, (etq, _f) in enumerate(documentos)],
            value=doc_actual["key"],
            on_select=_elegir_documento,
            dense=True,
            text_size=12,
            width=min(420, ancho_visor - 260),
            color=theme.TEXT_PRIMARY,
            border_color=theme.GLASS_BORDER,
            focused_border_color=theme.ACCENT_CYAN,
            bgcolor=theme.BG_PANEL,   # fondo solido: la lista desplegada se lee bien
            border_radius=8,
            content_padding=ft.Padding(10, 6, 10, 6),
            disabled=not documentos,
        )
        if not documentos:
            _mensaje_visor("No se encontró la petición descargada de este caso en "
                           "'peticiones_descargadas' (se guarda cuando Insignia gestiona el caso).", theme.WARNING)

        visor = ft.Container(
            width=ancho_visor,
            padding=10,
            border_radius=10,
            bgcolor=ft.Colors.with_opacity(0.35, "#000000"),
            border=ft.Border.all(1, theme.GLASS_BORDER),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PICTURE_AS_PDF, size=16, color=theme.ACCENT_CYAN),
                            selector_doc,
                            visor_estado,
                            ft.Container(expand=True),
                            ft.TextButton(
                                content=ft.Row([ft.Icon(ft.Icons.OPEN_IN_NEW, size=14),
                                                ft.Text("Abrir en el visor de Windows", size=11)], spacing=4, tight=True),
                                on_click=_abrir_fuera,
                                disabled=not documentos,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    paginas_col,
                ],
                spacing=8,
                expand=True,
            ),
        )

        dialog = ft.AlertDialog(
            title=ft.Text(f"Revisar memorando — {caso.radicado}", size=15, color=theme.TEXT_PRIMARY),
            inset_padding=ft.Padding(16, 16, 16, 16),
            content=ft.Container(
                width=ancho_total,
                height=alto_total,
                content=ft.Row(
                    [
                        visor,
                        ft.Container(width=ancho_resumen, content=resumen_col),
                    ],
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
            ),
            actions=[
                ft.TextButton("Cerrar", on_click=lambda e: page.pop_dialog()),
                boton_enviar,
            ],
        )
        page.show_dialog(dialog)
        if documentos:
            page.run_task(_cargar_documento, doc_actual["key"])

    async def _aprobar_directo(e, radicado: str, boton: ft.OutlinedButton):
        """Boton rapido 'Aprobar' directamente en la fila de la lista de
        Memorandos (pedido explicito de Andres, sesion 2026-09-24) --
        hace exactamente lo mismo que 'Aprobar y enviar' dentro de
        'Revisar' (ejecutar_flujo_aprobacion: pulsa 'Inicio ciclo de
        aprobación'/'Solicitar aprobación' en SGDEA y pega el mensaje de
        caso.mensaje_aprobacion) pero sin pasar primero por el dialogo de
        revision -- para el caso ya confiado, gestionado automaticamente.
        Sigue exigiendo el click explicito de Andres aqui; nunca se
        dispara sola."""
        if automatizacion_sgdea["activa"]:
            page.show_dialog(ft.SnackBar(content=ft.Text(_sgdea_ocupado_msg()), bgcolor=theme.WARNING))
            return
        automatizacion_sgdea["activa"] = True
        automatizacion_sgdea["quien"] = f"Aprobar {radicado}"
        boton.disabled = True
        texto_original = boton.content
        boton.content = ft.Row(
            [ft.ProgressRing(width=14, height=14, stroke_width=2, color=theme.ACCENT_CYAN), ft.Text("Aprobando...")],
            spacing=6,
            tight=True,
        )
        boton.update()

        cdp_url = config_state.get("sgdea_cdp_url") or "http://localhost:9222"
        caso_actual = casos_pendientes.obtener_caso(radicado)
        mensaje = caso_actual.mensaje_aprobacion if caso_actual else casos_pendientes.MENSAJE_APROBACION_DEFAULT
        try:
            resultado = await sgdea_automation.ejecutar_flujo_aprobacion(
                radicado, mensaje, cdp_url,
                page=(sgdea_client.pagina if sgdea_client is not None and sgdea_client.conectado else None),
            )
        except Exception as exc:
            resultado = sgdea_automation.ResultadoAutomatizacion(ok=False, pasos_completados=[], warnings=[f"Error inesperado: {exc}"])
        finally:
            automatizacion_sgdea["activa"] = False
            automatizacion_sgdea["quien"] = ""

        if resultado.ok:
            casos_pendientes.marcar_enviado(radicado)
            page.show_dialog(ft.SnackBar(content=ft.Text(f"Enviado a aprobación: {radicado}"), bgcolor=theme.SUCCESS))
        else:
            mensaje_error = "; ".join(resultado.warnings) or "Error desconocido durante el envio."
            casos_pendientes.marcar_error(radicado, mensaje_error)
            page.show_dialog(ft.SnackBar(content=ft.Text(f"No se pudo aprobar {radicado}: {mensaje_error}"), bgcolor=theme.ERROR))
        boton.disabled = False
        boton.content = texto_original
        boton.update()
        _refrescar_memorandos()

    def _fila_caso(caso) -> ft.Container:
        asunto_corto = (caso.asunto[:70] + "...") if len(caso.asunto) > 70 else caso.asunto
        aprobar_btn = ft.OutlinedButton(
            content=ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=16), ft.Text("Aprobar")], spacing=6, tight=True),
            disabled=(caso.estado == "enviado"),
            style=ft.ButtonStyle(
                color={ft.ControlState.DEFAULT: theme.SUCCESS},
                side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.SUCCESS)},
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
        )
        aprobar_btn.on_click = lambda e, r=caso.radicado, b=aprobar_btn: page.run_task(_aprobar_directo, e, r, b)
        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(caso.radicado, size=13, weight=ft.FontWeight.W_600, color=theme.TEXT_PRIMARY),
                                    _estado_pill(caso.estado),
                                ],
                                spacing=10,
                            ),
                            ft.Text(caso.destinatario_nombre, size=12, color=theme.TEXT_SECONDARY),
                            ft.Text(asunto_corto, size=11, color=theme.TEXT_MUTED),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.Row(
                        [
                            ft.OutlinedButton(
                                content=ft.Row([ft.Icon(ft.Icons.FACT_CHECK, size=16), ft.Text("Revisar")], spacing=6, tight=True),
                                on_click=lambda e, r=caso.radicado: _abrir_revision(r),
                                style=ft.ButtonStyle(
                                    color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN},
                                    side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)},
                                    shape=ft.RoundedRectangleBorder(radius=10),
                                ),
                            ),
                            aprobar_btn,
                        ],
                        spacing=8,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.Padding(14, 12, 14, 12),
            bgcolor=ft.Colors.with_opacity(0.035, "#FFFFFF"),
            border=ft.Border.all(1, theme.GLASS_BORDER),
            border_radius=12,
        )

    def _refrescar_memorandos(update: bool = True):
        try:
            casos = casos_pendientes.cargar_casos()
        except casos_pendientes.CasosPendientesError as exc:
            casos = []
            page.show_dialog(ft.SnackBar(content=ft.Text(f"No se pudo leer casos_pendientes.json: {exc}"), bgcolor=theme.ERROR))
        casos.sort(key=lambda c: c.fecha_generado, reverse=True)
        memorandos_state["casos"] = casos
        memorandos_list_view.controls = [_fila_caso(c) for c in casos] if casos else [memorandos_empty_text]
        if update:
            memorandos_list_view.update()

    memorandos_panel = theme.glass_card(
        ft.Column(
            [
                ft.Row(
                    [
                        theme.section_title("Memorandos pendientes de revision", ft.Icons.FACT_CHECK),
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.REFRESH, size=16), ft.Text("Refrescar")], spacing=6, tight=True),
                            on_click=lambda e: _refrescar_memorandos(),
                            style=ft.ButtonStyle(
                                color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN},
                                side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)},
                                shape=ft.RoundedRectangleBorder(radius=10),
                            ),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Text(
                    "Casos que ya quedaron listos en SGDEA (carta pegada, adjunto cargado, revisora "
                    "asignada) esperando tu revision final y el envio a aprobacion. 'Aprobar y enviar' "
                    "pulsa 'Solicitar aprobación'/'Inicio ciclo de aprobación' en SGDEA con el mensaje "
                    "de arriba -- necesita que ya tengas Chrome abierto, con sesion iniciada en SGDEA, "
                    "en modo de depuracion remota (ver Configuración).",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                ft.Container(height=6),
                memorandos_list_view,
            ],
            spacing=10,
        ),
    )
    _refrescar_memorandos(update=False)

    # ------------------------------------------------------------------
    # Panel DASHBOARD (métricas + casos activos, alimentado desde SGDEA)
    # ------------------------------------------------------------------
    dashboard_sync_status = ft.Text("", size=11, color=theme.TEXT_MUTED)
    # Correcciones de codigo que la revision autonoma (tarea programada de
    # Claude) dejo en la carpeta de Insignia y que todavia no estan en el .exe.
    aviso_correcciones_text = ft.Text("", size=12, color=theme.WARNING, weight=ft.FontWeight.W_600, visible=False)

    def _correcciones_sin_compilar() -> list:
        if not getattr(sys, "frozen", False):
            return []
        try:
            exe = Path(sys.executable)
            carpeta = exe.parent.parent
            fuentes = [carpeta / "main.py", *sorted((carpeta / "backend").glob("*.py"))]
            limite = exe.stat().st_mtime + 60
            return [f.name for f in fuentes if f.is_file() and f.stat().st_mtime > limite]
        except OSError:
            return []

    def _revisar_correcciones_pendientes():
        nuevos = _correcciones_sin_compilar()
        aviso_correcciones_text.visible = bool(nuevos)
        aviso_correcciones_text.value = (
            f"Hay correcciones nuevas de Insignia sin compilar ({', '.join(nuevos[:4])}"
            f"{'...' if len(nuevos) > 4 else ''}): cierra Insignia, ejecuta build.bat y ábrelo de nuevo."
        ) if nuevos else ""
        try:
            aviso_correcciones_text.update()
        except Exception:
            pass
    dashboard_tiles_row = ft.Row([], spacing=16)
    dashboard_list_view = ft.Column([], spacing=8)
    dashboard_empty_text = ft.Text(
        "No hay casos activos en el Dashboard todavia. Usa 'Sincronizar con SGDEA' para detectar los casos nuevos.",
        size=12,
        color=theme.TEXT_MUTED,
    )

    def _stat_tile(valor: int, etiqueta: str, color: str) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(str(valor), size=28, weight=ft.FontWeight.W_700, color=theme.TEXT_PRIMARY),
                    ft.Text(etiqueta, size=11, color=theme.TEXT_MUTED),
                ],
                spacing=4,
            ),
            padding=ft.Padding(18, 16, 18, 16),
            bgcolor=ft.Colors.with_opacity(0.035, "#FFFFFF"),
            border=ft.Border(
                top=ft.BorderSide(2, color),
                right=ft.BorderSide(1, theme.GLASS_BORDER),
                bottom=ft.BorderSide(1, theme.GLASS_BORDER),
                left=ft.BorderSide(1, theme.GLASS_BORDER),
            ),
            border_radius=14,
            expand=True,
        )

    def _pill_prioridad(p: str) -> ft.Container:
        return theme.status_pill("Urgente" if p == "urgente" else "Normal", theme.ERROR if p == "urgente" else theme.TEXT_MUTED)

    def _pill_estado_gestion(s: str) -> ft.Container:
        if s == "gestionado":
            # Texto pedido explicitamente por Andres (sesion 2026-09-24):
            # una alerta de color que diga "PARA APROBAR" -- el caso ya
            # quedo diligenciado (a mano o por el ciclo automatico) y
            # esta esperando su revision en Memorandos.
            return theme.status_pill("PARA APROBAR", theme.SUCCESS)
        if s == "espera_tercero":
            return theme.status_pill("Espera de tercero", theme.WARNING)
        return theme.status_pill("En gestión", theme.ACCENT_CYAN)

    def _abrir_caso_dashboard(radicado: str):
        casos = dashboard.cargar_casos()
        caso = next((c for c in casos if c.radicado == radicado), None)
        if caso is None:
            page.show_dialog(ft.SnackBar(content=ft.Text(f"El caso {radicado} ya no esta en el Dashboard."), bgcolor=theme.WARNING))
            _refrescar_dashboard()
            return

        prioridad_texto = ft.Text(f"Prioridad actual: {caso.prioridad}", size=12, color=theme.TEXT_SECONDARY)
        estado_texto_d = ft.Text(f"Estado actual: {caso.estado_gestion}", size=12, color=theme.TEXT_SECONDARY)

        def _set_prioridad(nueva: str):
            def _handler(e):
                try:
                    dashboard.set_prioridad(radicado, nueva)
                    prioridad_texto.value = f"Prioridad actual: {nueva}"
                    prioridad_texto.update()
                    _refrescar_dashboard()
                except dashboard.DashboardError as exc:
                    page.show_dialog(ft.SnackBar(content=ft.Text(str(exc)), bgcolor=theme.ERROR))
            return _handler

        def _set_estado(nuevo: str):
            def _handler(e):
                try:
                    dashboard.set_estado_gestion(radicado, nuevo)
                    estado_texto_d.value = f"Estado actual: {nuevo}"
                    estado_texto_d.update()
                    _refrescar_dashboard()
                except dashboard.DashboardError as exc:
                    page.show_dialog(ft.SnackBar(content=ft.Text(str(exc)), bgcolor=theme.ERROR))
            return _handler

        termino_field = ft.TextField(
            label="Termino / fecha limite (YYYY-MM-DD, opcional)",
            value=caso.termino_fecha_limite or "",
            color=theme.TEXT_PRIMARY,
            label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
            border_color=theme.GLASS_BORDER,
            focused_border_color=theme.ACCENT_CYAN,
            bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
            border_radius=10,
            text_size=13,
            content_padding=ft.Padding(12, 10, 12, 10),
        )

        def _guardar_termino(e):
            try:
                dashboard.set_termino(radicado, termino_field.value.strip() or None)
                _refrescar_dashboard()
                page.show_dialog(ft.SnackBar(content=ft.Text("Termino guardado."), bgcolor=theme.SUCCESS))
            except dashboard.DashboardError as exc:
                page.show_dialog(ft.SnackBar(content=ft.Text(str(exc)), bgcolor=theme.ERROR))

        notas_field = ft.TextField(
            label="Notas",
            value=caso.notas,
            multiline=True,
            min_lines=2,
            max_lines=4,
            color=theme.TEXT_PRIMARY,
            label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
            border_color=theme.GLASS_BORDER,
            focused_border_color=theme.ACCENT_CYAN,
            bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
            border_radius=10,
            text_size=13,
            content_padding=ft.Padding(12, 10, 12, 10),
        )

        def _guardar_notas(e):
            dashboard.set_notas(radicado, notas_field.value or "")
            _refrescar_dashboard()

        notas_field.on_blur = _guardar_notas

        # ------------------------------------------------------------------
        # Conexion compartida a Chrome (CDP) para este dialogo -- se abre
        # la primera vez que hace falta (generar respuesta o calibrar) y
        # se cierra al cerrar el dialogo. Mismo patron de
        # conectar_chrome_existente/close ya usado en _sincronizar_dashboard
        # y ejecutar_flujo_aprobacion: nunca cierra el Chrome real de
        # Andres, solo la conexion de Playwright.
        # ------------------------------------------------------------------
        conexion_caso = {"playwright": None, "browser": None, "context": None, "page": None}

        # CORRECCION (sesion 2026-09-25, caso real 2026-IE-036117):
        # candado compartido entre 'Generar respuesta' y 'Gestionar caso
        # completo'. Ambos botones terminan operando sobre la MISMA
        # `page` de SGDEA (ya sea la sesion propia de sgdea_client o la
        # conexion CDP guardada en conexion_caso) -- si cualquiera de los
        # dos se dispara mientras el OTRO (o el mismo) ya esta corriendo,
        # las dos corridas navegan/clickean sobre la misma pestaña al
        # mismo tiempo. Confirmado en vivo: dos clicks seguidos en
        # 'Gestionar caso completo' dejaron el Chrome de SGDEA congelado
        # mas de 15 minutos sin ningun error ni progreso -- las llamadas
        # de Playwright quedan esperando un estado de la pagina que la
        # OTRA corrida ya cambio, sin que ninguna de las dos llegue nunca
        # a un punto que lance una excepcion limpia. Cada handler debe
        # chequear y marcar este candado ANTES de tocar `page_sgdea`, y
        # liberarlo en su `finally` -- ver _generar_respuesta /
        # _gestionar_caso_completo mas abajo.
        automatizacion_en_curso = automatizacion_sgdea  # candado UNICO de la app (ver su definicion en main())

        async def _conectar_si_hace_falta():
            # Preferir la sesion PROPIA de SGDEA (backend/sgdea_session.py,
            # conectada desde Configuración) cuando esta disponible: es una
            # unica pagina persistente durante toda la corrida de la app,
            # asi que aqui no hay nada que abrir/cerrar por dialogo -- solo
            # se devuelve directamente. Si no esta conectada, cae al
            # comportamiento de siempre (CDP-attach al Chrome de Andres,
            # una conexion por dialogo).
            if sgdea_client is not None and sgdea_client.conectado:
                return sgdea_client.pagina
            if conexion_caso["page"] is not None:
                return conexion_caso["page"]
            cdp_url = config_state.get("sgdea_cdp_url") or "http://localhost:9222"
            playwright, browser, context = await sgdea_automation.conectar_chrome_existente(cdp_url)
            if not context.pages:
                # OJO -- nunca browser.close() aqui: cierra de verdad el
                # Chrome real de Andres via el comando CDP 'Browser.close'
                # (ver nota igual en sgdea_automation.py). Solo se detiene
                # el lado de Playwright.
                await playwright.stop()
                raise sgdea_automation.AutomatizacionError("El Chrome conectado no tiene ninguna pestaña abierta.")
            conexion_caso["playwright"] = playwright
            conexion_caso["browser"] = browser
            conexion_caso["context"] = context
            conexion_caso["page"] = context.pages[0]
            return conexion_caso["page"]

        async def _cerrar_conexion_caso():
            # OJO -- nunca conexion_caso["browser"].close() aqui: en una
            # conexion CDP ese Browser es el Chrome real de Andres, ya
            # logueado en SGDEA -- no uno que Playwright abrio. .close()
            # manda el comando CDP 'Browser.close' y SI cierra esa
            # ventana de verdad (confirmado en vivo, sesion 2026-09-23:
            # cerrar este dialogo de caso mataba la sesion de depuracion
            # de Chrome, dejando colgada sin error la siguiente conexion
            # -- p.ej. el siguiente 'Sincronizar con SGDEA'). Solo se
            # detiene el lado de Playwright con playwright.stop().
            if conexion_caso["playwright"] is not None:
                try:
                    await conexion_caso["playwright"].stop()
                except Exception:
                    pass
            conexion_caso["playwright"] = None
            conexion_caso["browser"] = None
            conexion_caso["context"] = None
            conexion_caso["page"] = None

        def _cerrar_dialogo_caso(e):
            page.run_task(_cerrar_conexion_caso)
            page.pop_dialog()

        # ------------------------------------------------------------------
        # Generar respuesta -- descarga la peticion en PDF (panel
        # 'Expediente'), la lee y genera la carta segun las plantillas ya
        # establecidas (backend.sgdea_peticion / backend.sgdea_carta).
        # TODAVIA NO pega/asigna nada en SGDEA. CORRECCION (sesion
        # 2026-09-23, video de Andres): destinatario y asunto NO se pegan
        # como texto libre -- van por los modales "Destinatario
        # Tipificación" / "Asunto" (sgdea_automation.seleccionar_
        # destinatario_tipificacion / establecer_asunto), que todavia no
        # se han probado en vivo. Solo saludo/cuerpo siguen necesitando
        # una coordenada de click POR CAMPO (pegar_en_campo) que hoy no
        # esta confirmada -- ver el panel de calibracion mas abajo.
        # Mientras tanto deja cada campo listo para copiar con un click.
        # ------------------------------------------------------------------
        def _recordar_tratamiento(e):
            # Lo recuerda para el barrido automatico (sesion 2026-09-27): si la
            # inferencia de Doctor/Doctora no es confiable, el barrido usa este.
            try:
                dashboard.set_tratamiento_manual(radicado, tratamiento_dropdown.value)
            except dashboard.DashboardError:
                pass

        tratamiento_dropdown = ft.Dropdown(
            label="Tratamiento (obligatorio -- nunca se adivina)",
            options=[ft.dropdown.Option("Doctor"), ft.dropdown.Option("Doctora")],
            value=getattr(caso, "tratamiento_manual", None),
            on_select=_recordar_tratamiento,
            color=theme.TEXT_PRIMARY,
            label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
            border_color=theme.GLASS_BORDER,
            focused_border_color=theme.ACCENT_CYAN,
            bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
            border_radius=10,
            text_size=13,
            content_padding=ft.Padding(12, 10, 12, 10),
        )
        generar_status = ft.Text("", size=12, color=theme.TEXT_MUTED)
        generar_resultado = ft.Column([], spacing=6, visible=False)

        def _campo_copiable(etiqueta: str, valor: str) -> ft.Row:
            async def _copiar(e2, v=valor, et=etiqueta):
                await clipboard.set(v)
                page.show_dialog(ft.SnackBar(content=ft.Text(f"{et} copiado al portapapeles."), bgcolor=theme.SUCCESS))
            return ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(etiqueta, size=10, color=theme.TEXT_MUTED),
                            ft.Text(valor, size=12, color=theme.TEXT_PRIMARY, selectable=True),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.IconButton(icon=ft.Icons.CONTENT_COPY, icon_size=16, icon_color=theme.ACCENT_CYAN, on_click=_copiar),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )

        async def _generar_respuesta(e):
            # Igual que en _gestionar_caso_completo: Tratamiento se infiere
            # despues de leer la peticion si Andres no eligio nada a mano
            # (ver sgdea_carta.inferir_tratamiento).
            #
            # CORRECCION (sesion 2026-09-25, caso real 2026-IE-036117):
            # guarda de reentrada usando el candado COMPARTIDO
            # `automatizacion_en_curso` (no solo generar_button.disabled)
            # -- este boton y 'Gestionar caso completo' operan sobre la
            # MISMA `page` de SGDEA, asi que la guarda tiene que cubrir a
            # los dos, no solo a clicks repetidos de este mismo boton. Ver
            # el comentario junto a `automatizacion_en_curso` (mas arriba,
            # junto a `conexion_caso`) para el sintoma confirmado en vivo
            # (Chrome de SGDEA congelado 15+ minutos sin error).
            if automatizacion_en_curso["activa"]:
                page.show_dialog(ft.SnackBar(content=ft.Text(_sgdea_ocupado_msg()), bgcolor=theme.WARNING))
                return
            cuadro = _get_cuadro_index()
            if cuadro is None:
                page.show_dialog(ft.SnackBar(content=ft.Text("Configura el archivo Cuadro_2026 en Configuración antes de generar."), bgcolor=theme.WARNING))
                return

            automatizacion_en_curso["activa"] = True
            automatizacion_en_curso["quien"] = f"Generar respuesta {radicado}"
            generar_button.disabled = True
            generar_resultado.visible = False
            generar_status.value = "Conectando a SGDEA..."
            generar_status.color = theme.TEXT_MUTED
            generar_button.update()
            generar_status.update()
            generar_resultado.update()

            try:
                page_sgdea = await _conectar_si_hace_falta()

                generar_status.value = "Descargando la petición en PDF desde 'Expediente'..."
                generar_status.update()
                carpeta_destino = str(_base_dir() / "peticiones_descargadas")
                ruta_pdf = await sgdea_automation.descargar_peticion_caso(page_sgdea, radicado, carpeta_destino)

                generar_status.value = f"Petición descargada ({ruta_pdf}). Leyendo..."
                generar_status.update()
                peticion = sgdea_peticion.leer_peticion(ruta_pdf)

                tratamiento_usado = tratamiento_dropdown.value
                if not tratamiento_usado:
                    nombre_firmante = peticion.destinatario.nombre if peticion.destinatario else ""
                    inferido, confiable = sgdea_carta.inferir_tratamiento(nombre_firmante)
                    if not confiable or not inferido:
                        generar_button.disabled = False
                        generar_button.update()
                        generar_status.value = (
                            f"No se pudo inferir Doctor/Doctora con confianza para "
                            f"'{nombre_firmante or '(nombre no leido)'}' -- elígelo tú "
                            "mismo arriba y vuelve a pulsar 'Generar respuesta'."
                        )
                        generar_status.color = theme.WARNING
                        generar_status.update()
                        return
                    tratamiento_usado = inferido
                    tratamiento_dropdown.value = inferido
                    tratamiento_dropdown.update()

                generar_status.value = "Generando la carta con las plantillas ya establecidas..."
                generar_status.update()
                carta = sgdea_carta.generar_carta(peticion, cuadro, tratamiento_usado)

                filas = [
                    _campo_copiable(
                        "Destinatario",
                        f"{carta.destinatario_nombre} — {carta.destinatario_cargo} ({carta.destinatario_subdireccion})",
                    ),
                    _campo_copiable("Asunto", carta.asunto),
                    _campo_copiable("Saludo", carta.saludo),
                    _campo_copiable("Cuerpo", carta.cuerpo_parrafo),
                ]
                if peticion.warnings or carta.warnings:
                    advertencias = list(peticion.warnings) + list(carta.warnings)
                    filas.append(ft.Text("Advertencias: " + "; ".join(advertencias), size=11, color=theme.WARNING))

                generar_resultado.controls = filas
                generar_resultado.visible = True
                generar_status.value = (
                    "Listo. Revisa el contenido y cópialo a SGDEA -- el pegado automático todavía "
                    "no está conectado aquí (ver panel de calibración abajo)."
                )
                generar_status.color = theme.SUCCESS
            except sgdea_automation.AutomatizacionError as exc:
                generar_status.value = str(exc)
                generar_status.color = theme.ERROR
            except ValueError as exc:
                generar_status.value = str(exc)
                generar_status.color = theme.ERROR
            except Exception as exc:
                generar_status.value = f"Error inesperado ({type(exc).__name__}): {exc}"
                generar_status.color = theme.ERROR
            finally:
                automatizacion_en_curso["activa"] = False
                generar_button.disabled = False
                generar_button.update()
                generar_status.update()
                generar_resultado.update()

        generar_button = ft.FilledButton(
            content=ft.Row([ft.Icon(ft.Icons.AUTO_FIX_HIGH, size=16), ft.Text("Generar respuesta")], spacing=6, tight=True),
            on_click=lambda e: page.run_task(_generar_respuesta, e),
            style=ft.ButtonStyle(bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, color={ft.ControlState.DEFAULT: "#001018"}, shape=ft.RoundedRectangleBorder(radius=10)),
        )

        # ------------------------------------------------------------------
        # Calibracion (TEMPORAL) -- hoy no existe ninguna coordenada
        # confirmada para saludo/cuerpo dentro del editor de SGDEA
        # (destinatario y asunto YA NO necesitan coordenada: van por los
        # modales "Destinatario Tipificación"/"Asunto", ubicables por
        # data-original-title -- ver correccion arriba y en
        # sgdea_automation.py). Este panel abre el documento y prueba
        # clicks SIN pegar nada (sgdea_automation.probar_click_editor),
        # para poder encontrar esas coordenadas en vivo sin arriesgar
        # contenido real. Una vez confirmadas, se vuelven constantes en
        # sgdea_automation.py y este panel deja de hacer falta.
        # ------------------------------------------------------------------
        calib_status = ft.Text("", size=12, color=theme.TEXT_MUTED)
        _estilo_num = dict(
            color=theme.TEXT_PRIMARY,
            label_style=ft.TextStyle(color=theme.TEXT_SECONDARY),
            border_color=theme.GLASS_BORDER,
            focused_border_color=theme.ACCENT_CYAN,
            bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"),
            border_radius=10,
            text_size=13,
            content_padding=ft.Padding(12, 10, 12, 10),
            width=100,
        )
        calib_x = ft.TextField(label="X", **_estilo_num)
        calib_y = ft.TextField(label="Y", **_estilo_num)

        async def _abrir_documento_calib(e):
            calib_status.value = "Abriendo 'Ver documentos'..."
            calib_status.color = theme.TEXT_MUTED
            calib_status.update()
            try:
                page_sgdea = await _conectar_si_hace_falta()
                # CORRECCION (confirmado en vivo por Andres, sesion
                # 2026-09-25, caso real 2026-IE-036117): aunque el caso ya
                # tenga otros documentos en el panel "Expediente" (p.ej. el
                # memo de asignacion/reasignacion, o la peticion original),
                # SGDEA NO ofrece un icono "Ver documentos" para abrirlos --
                # el UNICO camino a la vista "Ver documentos" es el icono
                # "Crear documento" del toolbar del caso (abre directo el
                # editor en blanco de "Memorando respuesta"). Por eso aqui
                # se pasa crear_documento_si_hace_falta=True tambien para
                # la calibracion -- ya no existe un camino "solo mirar" sin
                # crear el documento.
                await sgdea_automation.navegar_a_caso(page_sgdea, radicado, crear_documento_si_hace_falta=True)
                calib_status.value = "Documento abierto -- ya puedes probar coordenadas abajo."
                calib_status.color = theme.SUCCESS
            except sgdea_automation.AutomatizacionError as exc:
                calib_status.value = str(exc)
                calib_status.color = theme.ERROR
            except Exception as exc:
                calib_status.value = f"Error inesperado ({type(exc).__name__}): {exc}"
                calib_status.color = theme.ERROR
            calib_status.update()

        async def _probar_click_calib(e):
            try:
                x = float((calib_x.value or "").strip())
                y = float((calib_y.value or "").strip())
            except ValueError:
                page.show_dialog(ft.SnackBar(content=ft.Text("X/Y deben ser números."), bgcolor=theme.WARNING))
                return
            calib_status.value = f"Probando click en ({x:g}, {y:g})..."
            calib_status.color = theme.TEXT_MUTED
            calib_status.update()
            try:
                page_sgdea = await _conectar_si_hace_falta()
                ok, desc = await sgdea_automation.probar_click_editor(page_sgdea, x, y)
                if ok:
                    calib_status.value = f"SI cae en el punto de pegado: ({x:g}, {y:g}) -- foco: {desc}"
                    calib_status.color = theme.SUCCESS
                else:
                    calib_status.value = f"NO cae en el punto de pegado: ({x:g}, {y:g}) -- foco quedo en: {desc}"
                    calib_status.color = theme.ERROR
            except sgdea_automation.AutomatizacionError as exc:
                calib_status.value = str(exc)
                calib_status.color = theme.ERROR
            except Exception as exc:
                calib_status.value = f"Error inesperado ({type(exc).__name__}): {exc}"
                calib_status.color = theme.ERROR
            calib_status.update()

        # ------------------------------------------------------------------
        # Persistencia de las coordenadas calibradas (saludo/cuerpo) --
        # una vez que Andres confirma con "Probar click (sin pegar)" que
        # una coordenada SI cae en el punto de pegado, este par de
        # botones la guarda en config_472.json (mismo archivo/patron que
        # el resto de la configuracion, ver load_config/save_config
        # arriba) para que "Gestionar caso completo" mas abajo pueda
        # usarla sin que Andres tenga que volver a calibrar cada vez.
        # ------------------------------------------------------------------
        def _valor_guardado(clave_x: str, clave_y: str) -> str:
            x = config_state.get(clave_x)
            y = config_state.get(clave_y)
            return f"({x:g}, {y:g})" if isinstance(x, (int, float)) and isinstance(y, (int, float)) else "(sin calibrar)"

        calib_guardadas_texto = ft.Text(
            f"Saludo guardado: {_valor_guardado('calib_saludo_x', 'calib_saludo_y')} · "
            f"Cuerpo guardado: {_valor_guardado('calib_cuerpo_x', 'calib_cuerpo_y')}",
            size=11,
            color=theme.TEXT_MUTED,
        )

        def _guardar_coordenada(clave_x: str, clave_y: str, etiqueta: str):
            def _handler(e):
                try:
                    x = float((calib_x.value or "").strip())
                    y = float((calib_y.value or "").strip())
                except ValueError:
                    page.show_dialog(ft.SnackBar(content=ft.Text("X/Y deben ser números antes de guardar."), bgcolor=theme.WARNING))
                    return
                config_state[clave_x] = x
                config_state[clave_y] = y
                save_config(config_state)
                calib_guardadas_texto.value = (
                    f"Saludo guardado: {_valor_guardado('calib_saludo_x', 'calib_saludo_y')} · "
                    f"Cuerpo guardado: {_valor_guardado('calib_cuerpo_x', 'calib_cuerpo_y')}"
                )
                calib_guardadas_texto.update()
                page.show_dialog(ft.SnackBar(content=ft.Text(f"Coordenada de {etiqueta} guardada: ({x:g}, {y:g})."), bgcolor=theme.SUCCESS))
            return _handler

        # ------------------------------------------------------------------
        # Gestionar caso completo (automático) -- encadena TODO lo que ya
        # esta conectado (destinatario/asunto por modal, saludo/cuerpo por
        # pegado usando las coordenadas guardadas arriba, adjunto/tamaño
        # legal/revisor) y deja el documento listo para que Andres SOLO
        # tenga que entrar a SGDEA a revisarlo y pulsar el envio a
        # aprobacion el mismo (pedido de Andres, sesion 2026-09-23). Ver
        # sgdea_automation.gestionar_caso_completo() -- varios de estos
        # pasos (destinatario/asunto, "Crear documento") todavia NO se
        # han confirmado en vivo; la PRIMERA corrida de este boton debe
        # hacerse con Andres mirando la pantalla de Chrome.
        # ------------------------------------------------------------------
        gestionar_status = ft.Text("", size=12, color=theme.TEXT_MUTED)

        async def _gestionar_caso_completo(e):
            # CORRECCION (sesion 2026-09-25): print de entrada ANTES de
            # cualquier otra cosa -- ni el candado de reentrada, ni la
            # validacion de cuadro/coordenadas/categoria de abajo pueden
            # ocultar si el on_click en si se disparo. Sin esto no hay forma
            # de distinguir "el click no llego al boton" de "el boton se
            # activo pero algo aborto en silencio antes del primer print
            # existente" -- justo la duda que costo varios clicks en vivo
            # diagnosticar el bug de extraer_categoria_proceso.
            print(f"[gestionar_caso_completo][main] {radicado}: on_click disparado.", flush=True)
            # Tratamiento YA NO se pide de entrada (pedido explicito de
            # Andres, sesion 2026-09-24: "que yo solo entre a insignia a
            # darle 'aprobar'"): se infiere mas abajo, DESPUES de leer la
            # peticion, a partir de quien la firma -- ver
            # sgdea_carta.inferir_tratamiento(). Si Andres ya eligio algo a
            # mano en el desplegable, eso manda siempre (nunca se pisa una
            # eleccion explicita). Si no se puede inferir con confianza Y
            # el desplegable sigue vacio, se pide igual (ver abajo) -- la
            # regla "nunca se adivina" se mantiene para el caso ambiguo.
            #
            # CORRECCION (sesion 2026-09-25, caso real 2026-IE-036117):
            # misma guarda de reentrada que _generar_respuesta, con el
            # candado COMPARTIDO `automatizacion_en_curso` (ver su
            # comentario junto a `conexion_caso` mas arriba) -- este boton
            # y 'Generar respuesta' comparten la misma `page` de SGDEA.
            # Confirmado en vivo: dos clicks seguidos en este mismo boton
            # dejaron el Chrome de SGDEA congelado 15+ minutos sin ningun
            # error ni progreso, porque las dos corridas competian por la
            # misma pestaña sin que ninguna llegara nunca a un punto que
            # lanzara una excepcion limpia.
            # CORRECCION (sesion 2026-09-25, prueba en vivo caso real
            # 2026-IE-036117, DESPUES de arreglar el bug de
            # extraer_categoria_proceso): estas validaciones previas
            # (candado, cuadro, coordenadas, categoria) vivian FUERA de
            # cualquier try/except -- cualquier excepcion no prevista aqui
            # (ej. `caso` es None por desincronizacion con el Dashboard,
            # `caso.columnas_crudas` con forma inesperada, config_state
            # corrupto) se perdia en el vacio: ni SnackBar, ni print en
            # dev_run.log, ni excepcion visible en ningun lado -- un click
            # real sobre el boton que no dejaba NINGUN rastro, indistinguible
            # de un click que simplemente no llego al boton. Se envuelve
            # todo el preflight en try/except para que la regla del
            # proyecto ("nunca un colgado sin rastro") tambien cubra esta
            # seccion, no solo el bloque de automatizacion de mas abajo.
            try:
                if automatizacion_en_curso["activa"]:
                    page.show_dialog(ft.SnackBar(content=ft.Text(_sgdea_ocupado_msg()), bgcolor=theme.WARNING))
                    return
                cuadro = _get_cuadro_index()
                if cuadro is None:
                    page.show_dialog(ft.SnackBar(content=ft.Text("Configura el archivo Cuadro_2026 en Configuración antes de gestionar."), bgcolor=theme.WARNING))
                    return
                # Sesion 2026-09-27: la calibracion YA NO es requisito. Saludo y
                # cuerpo se escriben con la API del editor (sin coordenadas); si
                # hay coordenadas calibradas se usan solo como respaldo del cuerpo.
                coord_saludo, coord_cuerpo = _coordenadas_calibradas()
                if caso is None:
                    page.show_dialog(ft.SnackBar(content=ft.Text(f"No se encontro el caso {radicado} en la lista cargada del Dashboard -- pulsa 'Refrescar' o 'Sincronizar con SGDEA' y vuelve a intentar."), bgcolor=theme.ERROR))
                    return
                categoria = sgdea_automation.extraer_categoria_proceso(caso.columnas_crudas)
                if not categoria:
                    page.show_dialog(ft.SnackBar(content=ft.Text("No se pudo determinar la categoría ('Proceso') de este caso a partir de sus datos crudos -- revisa manualmente en SGDEA."), bgcolor=theme.ERROR))
                    return
            except Exception as exc:
                print(f"[gestionar_caso_completo][main] {radicado}: EXCEPCION en validacion previa (antes del candado, antes del primer print) -- {type(exc).__name__}: {exc}", flush=True)
                page.show_dialog(ft.SnackBar(content=ft.Text(f"Error inesperado antes de iniciar 'Gestionar caso completo' ({type(exc).__name__}): {exc}"), bgcolor=theme.ERROR))
                return

            automatizacion_en_curso["activa"] = True
            automatizacion_en_curso["quien"] = f"Gestionar caso completo {radicado}"
            gestionar_button.disabled = True
            gestionar_status.value = "Conectando a SGDEA..."
            gestionar_status.color = theme.TEXT_MUTED
            gestionar_button.update()
            gestionar_status.update()
            # Mismo motivo que sgdea_automation._log_paso: la sesion
            # 2026-09-25 (caso real 2026-IE-036117) se colgo 15+ minutos sin
            # que el texto de estado de Flet mostrara NADA en las capturas de
            # pantalla revisadas -- imprimir aqui tambien, a nivel de este
            # handler (ademas de dentro de sgdea_automation), deja en
            # dev_run.log constancia de que este codigo si se ejecuto, para
            # distinguir "el handler nunca arranco" de "se colgo mas adentro,
            # dentro de sgdea_automation.gestionar_caso_completo".
            print(f"[gestionar_caso_completo][main] {radicado}: handler iniciado, conectando a SGDEA...", flush=True)

            try:
                page_sgdea = await _conectar_si_hace_falta()
                print(f"[gestionar_caso_completo][main] {radicado}: conectado, descargando peticion...", flush=True)

                gestionar_status.value = "Descargando la petición en PDF desde 'Expediente'..."
                gestionar_status.update()
                carpeta_destino = str(_base_dir() / "peticiones_descargadas")
                ruta_pdf = await sgdea_automation.descargar_peticion_caso(page_sgdea, radicado, carpeta_destino)
                print(f"[gestionar_caso_completo][main] {radicado}: peticion descargada en {ruta_pdf!r}, leyendo...", flush=True)

                gestionar_status.value = f"Petición descargada ({ruta_pdf}). Leyendo..."
                gestionar_status.update()
                peticion = sgdea_peticion.leer_peticion(ruta_pdf)

                tratamiento_usado = tratamiento_dropdown.value
                if not tratamiento_usado:
                    nombre_firmante = peticion.destinatario.nombre if peticion.destinatario else ""
                    inferido, confiable = sgdea_carta.inferir_tratamiento(nombre_firmante)
                    if not confiable or not inferido:
                        gestionar_button.disabled = False
                        gestionar_button.update()
                        gestionar_status.value = (
                            f"No se pudo inferir Doctor/Doctora con confianza para "
                            f"'{nombre_firmante or '(nombre no leido)'}' -- elígelo tú "
                            "mismo arriba y vuelve a pulsar 'Gestionar caso completo'."
                        )
                        gestionar_status.color = theme.WARNING
                        gestionar_status.update()
                        return
                    tratamiento_usado = inferido
                    tratamiento_dropdown.value = inferido
                    tratamiento_dropdown.update()
                    gestionar_status.value = f"Tratamiento inferido de quien firma la petición ({nombre_firmante}): {inferido}."
                    gestionar_status.color = theme.TEXT_MUTED
                    gestionar_status.update()

                print(f"[gestionar_caso_completo][main] {radicado}: peticion leida, tratamiento={tratamiento_usado!r}, generando carta...", flush=True)
                gestionar_status.value = "Generando la carta con las plantillas ya establecidas..."
                gestionar_status.update()
                carta = sgdea_carta.generar_carta(peticion, cuadro, tratamiento_usado)

                # Expediente 472 antiguo (pedido explicito de Andres, sesion
                # 2026-09-24, caso 2026-IE-035458): si hay un reporte
                # EstadoMensajes configurado Y el portal antiguo esta
                # conectado, se cotejan tipo+numero+fecha+nombre del acto ya
                # resuelto contra ese reporte para ubicar el ID de 472
                # antiguo, se baja su acuse y se arma el expediente -- TODO
                # esto es best-effort: si falta cualquier cosa (reporte no
                # configurado, portal antiguo no conectado, acto no
                # encontrado/ambiguo, es una peticion masiva) simplemente se
                # sigue SIN adjunto y se deja constancia en el estado, nunca
                # bloquea el resto de la gestion.
                # Mismas reglas de fuente que el barrido (ver
                # _preparar_adjunto_caso / backend/fuentes_acuses.py). En el
                # boton manual no bloquea: si falta el adjunto se sigue sin el
                # y se avisa.
                gestionar_status.value = "Preparando el adjunto (acuse 4-72)..."
                gestionar_status.update()
                actos_resueltos = sgdea_carta.resolver_actos(peticion, cuadro)
                if carta.es_masiva:
                    actos_resueltos = [a for a in actos_resueltos if a.emparejado]
                ruta_pdf_carta_472, motivo_adj, _manual_adj = await _preparar_adjunto_caso(radicado, carta, actos_resueltos, cuadro)
                if ruta_pdf_carta_472 is None:
                    gestionar_status.value = f"(Sin adjunto: {motivo_adj})"
                    gestionar_status.color = theme.WARNING
                    carta.warnings.append(f"Adjunto pendiente: {motivo_adj}")
                else:
                    gestionar_status.value = f"Adjunto listo: {Path(ruta_pdf_carta_472).name}."
                    gestionar_status.color = theme.SUCCESS
                gestionar_status.update()

                print(f"[gestionar_caso_completo][main] {radicado}: adjunto 472 resuelto (ruta={ruta_pdf_carta_472!r}), entrando a sgdea_automation.gestionar_caso_completo...", flush=True)
                gestionar_status.value = (
                    f"Gestionando en SGDEA (destinatario, asunto, saludo, cuerpo, tamaño legal, "
                    f"revisora Ema) -- categoría: {categoria}..."
                )
                gestionar_status.update()
                resultado = await sgdea_automation.gestionar_caso_completo(
                    page_sgdea,
                    radicado,
                    carta,
                    coordenada_saludo=coord_saludo,
                    coordenada_cuerpo=coord_cuerpo,
                    categoria_nivel1=categoria,
                    ruta_pdf_carta=ruta_pdf_carta_472,
                )
                print(f"[gestionar_caso_completo][main] {radicado}: gestionar_caso_completo devolvio ok={resultado.ok} pasos={resultado.pasos_completados}", flush=True)

                if resultado.ok:
                    # Conecta este resultado con la cola de "Memorandos": sin
                    # esto, un caso gestionado automaticamente nunca llegaba
                    # a "Aprobar y enviar" -- habia que armarlo a mano ahi
                    # tambien. agregar_caso reemplaza (no duplica) si el
                    # radicado ya estaba en la cola de una corrida anterior.
                    casos_pendientes.agregar_caso(
                        casos_pendientes.CasoPendiente.desde_carta(radicado, carta, adjunto_path=ruta_pdf_carta_472 or "")
                    )
                    try:
                        dashboard.set_estado_gestion(radicado, "gestionado")
                    except dashboard.DashboardError:
                        pass  # el caso puede no estar en dashboard_casos.json (p.ej. si se gestiono sin pasar por "Sincronizar con SGDEA") -- no es fatal
                    _refrescar_dashboard()
                    _refrescar_memorandos()
                    gestionar_status.value = (
                        "Listo -- documento diligenciado (" + ", ".join(resultado.pasos_completados) + "). "
                        "Se agregó a Memorandos, pendiente de tu aprobación (nunca se envía solo). "
                        "Entra a SGDEA a revisarlo y pulsa tú mismo el envío a aprobación cuando estés conforme."
                    )
                    gestionar_status.color = theme.SUCCESS
                else:
                    pasos_ok = ", ".join(resultado.pasos_completados) or "ninguno"
                    gestionar_status.value = (
                        f"Se detuvo -- pasos completados: {pasos_ok}. "
                        + (resultado.warnings[0] if resultado.warnings else "Error sin detalle.")
                    )
                    gestionar_status.color = theme.ERROR
            except sgdea_automation.AutomatizacionError as exc:
                print(f"[gestionar_caso_completo][main] {radicado}: AutomatizacionError: {exc}", flush=True)
                gestionar_status.value = str(exc)
                gestionar_status.color = theme.ERROR
            except ValueError as exc:
                print(f"[gestionar_caso_completo][main] {radicado}: ValueError: {exc}", flush=True)
                gestionar_status.value = str(exc)
                gestionar_status.color = theme.ERROR
            except Exception as exc:
                print(f"[gestionar_caso_completo][main] {radicado}: error inesperado ({type(exc).__name__}): {exc}", flush=True)
                gestionar_status.value = f"Error inesperado ({type(exc).__name__}): {exc}"
                gestionar_status.color = theme.ERROR
            finally:
                print(f"[gestionar_caso_completo][main] {radicado}: FIN handler (finally, liberando candado).", flush=True)
                automatizacion_en_curso["activa"] = False
                gestionar_button.disabled = False
                gestionar_button.update()
                gestionar_status.update()

        gestionar_button = ft.FilledButton(
            content=ft.Row([ft.Icon(ft.Icons.ROCKET_LAUNCH, size=16), ft.Text("Gestionar caso completo (automático)")], spacing=6, tight=True),
            on_click=lambda e: page.run_task(_gestionar_caso_completo, e),
            style=ft.ButtonStyle(bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_VIOLET}, color={ft.ControlState.DEFAULT: "#0A0014"}, shape=ft.RoundedRectangleBorder(radius=10)),
        )

        def _archivar(e):
            dashboard.archivar(radicado)
            page.run_task(_cerrar_conexion_caso)
            page.pop_dialog()
            _refrescar_dashboard()
            page.show_dialog(ft.SnackBar(content=ft.Text(f"Caso {radicado} archivado."), bgcolor=theme.SUCCESS))

        columnas_texto = " · ".join(caso.columnas_crudas) if caso.columnas_crudas else "(sin datos crudos guardados)"

        dialog = ft.AlertDialog(
            title=ft.Text(f"Caso — {caso.radicado}", size=15, color=theme.TEXT_PRIMARY),
            content=ft.Container(
                width=480,
                content=ft.Column(
                    [
                        ft.Text(
                            "Datos crudos leidos de SGDEA (columnas sin mapear todavia, ver "
                            "sgdea_automation.listar_casos_gestionar):",
                            size=11,
                            color=theme.TEXT_MUTED,
                        ),
                        ft.Text(columnas_texto, size=12, color=theme.TEXT_PRIMARY),
                        ft.Divider(color=theme.GLASS_BORDER, height=16),
                        prioridad_texto,
                        ft.Row(
                            [
                                ft.OutlinedButton("Marcar Normal", on_click=_set_prioridad("normal")),
                                ft.OutlinedButton("Marcar Urgente", on_click=_set_prioridad("urgente")),
                            ],
                            spacing=8,
                        ),
                        estado_texto_d,
                        ft.Row(
                            [
                                ft.OutlinedButton("En gestión", on_click=_set_estado("en_gestion")),
                                ft.OutlinedButton("Espera de tercero", on_click=_set_estado("espera_tercero")),
                            ],
                            spacing=8,
                        ),
                        ft.Divider(color=theme.GLASS_BORDER, height=16),
                        termino_field,
                        ft.OutlinedButton("Guardar termino", on_click=_guardar_termino),
                        ft.Container(height=6),
                        notas_field,
                        ft.Divider(color=theme.GLASS_BORDER, height=16),
                        theme.section_title("Generar respuesta", ft.Icons.AUTO_FIX_HIGH),
                        ft.Text(
                            "Descarga la petición del caso, la lee y genera la carta con las "
                            "plantillas ya establecidas. El llenado automático en SGDEA todavía no "
                            "está conectado -- destinatario/asunto van por los modales propios de "
                            "SGDEA (no se pegan como texto libre) y saludo/cuerpo por pegado -- por "
                            "ahora deja cada campo listo para copiar.",
                            size=11,
                            color=theme.TEXT_MUTED,
                        ),
                        tratamiento_dropdown,
                        generar_button,
                        generar_status,
                        generar_resultado,
                        ft.Divider(color=theme.GLASS_BORDER, height=16),
                        theme.section_title("Calibración del editor (temporal)", ft.Icons.CENTER_FOCUS_STRONG),
                        ft.Text(
                            "Para poder pegar saludo/cuerpo automáticamente hace falta la coordenada "
                            "de cada campo dentro del editor (destinatario/asunto ya NO se calibran "
                            "aquí -- van por los modales propios de SGDEA, como lo hace la Dra. Ema). "
                            "Este panel abre el documento y prueba clicks SIN pegar nada -- úsalo "
                            "mirando la pantalla de Chrome para encontrar cada coordenada. OJO: si el "
                            "caso todavía no tiene un 'Memorando respuesta' creado, 'Abrir Ver "
                            "documentos' lo CREA (clic en 'Crear documento') -- es el único camino a "
                            "esa vista en SGDEA, no hay forma de solo mirar sin crear.",
                            size=11,
                            color=theme.TEXT_MUTED,
                        ),
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.OPEN_IN_NEW, size=16), ft.Text("Abrir 'Ver documentos'")], spacing=6, tight=True),
                            on_click=lambda e: page.run_task(_abrir_documento_calib, e),
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        ft.Row([calib_x, calib_y], spacing=10),
                        ft.OutlinedButton(
                            content=ft.Row([ft.Icon(ft.Icons.ADS_CLICK, size=16), ft.Text("Probar click (sin pegar)")], spacing=6, tight=True),
                            on_click=lambda e: page.run_task(_probar_click_calib, e),
                            style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                        ),
                        calib_status,
                        ft.Text(
                            "Cuando 'Probar click' confirme que SI cae en el punto de pegado, "
                            "guarda esa coordenada aquí (una sola vez -- queda guardada en "
                            "config_472.json para todos los casos):",
                            size=11,
                            color=theme.TEXT_MUTED,
                        ),
                        ft.Row(
                            [
                                ft.OutlinedButton("Guardar como Saludo", on_click=_guardar_coordenada("calib_saludo_x", "calib_saludo_y", "Saludo")),
                                ft.OutlinedButton("Guardar como Cuerpo", on_click=_guardar_coordenada("calib_cuerpo_x", "calib_cuerpo_y", "Cuerpo")),
                            ],
                            spacing=8,
                        ),
                        calib_guardadas_texto,
                        ft.Divider(color=theme.GLASS_BORDER, height=16),
                        theme.section_title("Gestionar caso completo (automático)", ft.Icons.ROCKET_LAUNCH),
                        ft.Text(
                            "Encadena todo lo de arriba (destinatario, asunto, saludo, cuerpo, "
                            "tamaño legal, revisora Ema) y deja el documento listo -- tú solo "
                            "entras a SGDEA a revisarlo y pulsas el envío a aprobación tú mismo "
                            "(esto NUNCA lo hace por su cuenta). Necesita Doctor/Doctora elegido "
                            "arriba. Ya no requiere calibrar: la calibración de abajo es solo un "
                            "respaldo opcional para el cuerpo.",
                            size=11,
                            color=theme.TEXT_MUTED,
                        ),
                        gestionar_button,
                        gestionar_status,
                    ],
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                    tight=True,
                ),
            ),
            actions=[
                ft.TextButton("Cerrar", on_click=_cerrar_dialogo_caso),
                ft.FilledButton(
                    content=ft.Row([ft.Icon(ft.Icons.ARCHIVE, size=16), ft.Text("Archivar")], spacing=6, tight=True),
                    on_click=_archivar,
                    style=ft.ButtonStyle(bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_VIOLET}, color={ft.ControlState.DEFAULT: "#0A0014"}, shape=ft.RoundedRectangleBorder(radius=10)),
                ),
            ],
        )
        page.show_dialog(dialog)

    def _texto_auto(caso) -> tuple[str, str]:
        """Linea de estado de la gestion automatica para la fila del caso."""
        estado = getattr(caso, "auto_estado", "")
        msg = (getattr(caso, "auto_mensaje", "") or "").strip()
        if estado == "listo_revision":
            return "Listo para tu revisión en SGDEA (Memorandos › Aprobar).", theme.SUCCESS
        if estado == "requiere_manual":
            return f"Requiere revisión manual: {msg[:220]}", theme.ERROR
        if estado == "reintentar":
            return f"Se reintenta en el próximo barrido ({caso.auto_intentos}/{dashboard.MAX_INTENTOS_AUTO}): {msg[:180]}", theme.WARNING
        if not getattr(caso, "en_sgdea", True):
            return "Ya no está en tu bandeja de SGDEA.", theme.TEXT_MUTED
        return "", theme.TEXT_MUTED

    def _reintentar_auto(radicado: str):
        try:
            dashboard.reiniciar_auto(radicado)
            page.show_dialog(ft.SnackBar(content=ft.Text(f"{radicado} vuelve a la cola del barrido automático."), bgcolor=theme.SUCCESS))
        except dashboard.DashboardError as exc:
            page.show_dialog(ft.SnackBar(content=ft.Text(str(exc)), bgcolor=theme.ERROR))
        _refrescar_dashboard()

    def _fila_caso_dashboard(caso) -> ft.Container:
        preview = " · ".join(caso.columnas_crudas[:3]) if caso.columnas_crudas else ""
        auto_txt, auto_color = _texto_auto(caso)
        acciones = []
        if getattr(caso, "auto_estado", "") == "requiere_manual":
            acciones.append(ft.TextButton(
                "Reintentar automático",
                on_click=lambda e, r=caso.radicado: _reintentar_auto(r),
                style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}),
            ))
        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(caso.radicado, size=13, weight=ft.FontWeight.W_600, color=theme.TEXT_PRIMARY),
                                    _pill_prioridad(caso.prioridad),
                                    _pill_estado_gestion(caso.estado_gestion),
                                ],
                                spacing=8,
                            ),
                            ft.Text(preview, size=11, color=theme.TEXT_MUTED),
                            *([ft.Text(auto_txt, size=11, color=auto_color, selectable=True)] if auto_txt else []),
                            *([ft.Text(f"Revisión automática: {caso.auto_revision_nota}", size=11,
                                       color=theme.ACCENT_CYAN, selectable=True)]
                              if getattr(caso, "auto_revision_nota", "") and caso.auto_estado != "listo_revision" else []),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    *acciones,
                    ft.OutlinedButton(
                        content=ft.Row([ft.Icon(ft.Icons.TUNE, size=16), ft.Text("Gestionar")], spacing=6, tight=True),
                        on_click=lambda e, r=caso.radicado: _abrir_caso_dashboard(r),
                        style=ft.ButtonStyle(
                            color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN},
                            side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)},
                            shape=ft.RoundedRectangleBorder(radius=10),
                        ),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.Padding(14, 12, 14, 12),
            bgcolor=ft.Colors.with_opacity(0.035, "#FFFFFF"),
            border=ft.Border.all(1, theme.GLASS_BORDER),
            border_radius=12,
        )

    def _refrescar_dashboard(update: bool = True):
        m = dashboard.metricas()
        dashboard_tiles_row.controls = [
            _stat_tile(m["terminos_por_vencer"], "Términos por vencer", theme.WARNING),
            _stat_tile(m["casos_urgentes"], "Casos urgentes", theme.ERROR),
            _stat_tile(m["en_espera_tercero"], "En espera de tercero", theme.TEXT_MUTED),
        ]
        casos = [c for c in dashboard.cargar_casos() if not c.archivado]
        casos.sort(key=lambda c: c.fecha_detectado, reverse=True)
        dashboard_list_view.controls = [_fila_caso_dashboard(c) for c in casos] if casos else [dashboard_empty_text]
        _refrescar_autorrevision({c.radicado for c in casos if c.en_sgdea})
        if update:
            dashboard_tiles_row.update()
            dashboard_list_view.update()
            try:
                autorrevision_view.update()
            except Exception:
                pass

    autorrevision_view = ft.Column([], spacing=4)
    _ETIQUETAS_REVISION = {
        "reencolar": ("Vuelve a la cola", theme.SUCCESS),
        "esperar": ("Esperando", theme.WARNING),
        "decision": ("Necesita tu decisión", theme.ERROR),
        "tope": ("Revisar a mano", theme.ERROR),
    }

    def _refrescar_autorrevision(activos: set):
        historial = [d for d in autorrevision.leer_historial(RUTA_AUTORREVISION) if d.get("radicado") in activos]
        filas = [
            ft.Text("Revisión automática de errores", size=13, weight=ft.FontWeight.W_600, color=theme.TEXT_PRIMARY),
            ft.Text("En cada barrido Insignia revisa los casos detenidos, reconoce el error con lo aprendido y, "
                    "si la causa ya se resolvió (adjunto en Descargas, reporte nuevo, portal al día, versión "
                    "nueva, falla pasajera de SGDEA), los vuelve a gestionar solo.", size=11, color=theme.TEXT_MUTED),
        ]
        if not historial:
            filas.append(ft.Text("Sin casos detenidos por revisar.", size=11, color=theme.TEXT_MUTED))
        for d in historial[:20]:
            etiqueta, color = _ETIQUETAS_REVISION.get(d.get("accion"), (d.get("accion", ""), theme.TEXT_MUTED))
            filas.append(ft.Text(f"{d.get('radicado')} · {etiqueta}: {d.get('nota', '')}"[:260],
                                 size=11, color=color, selectable=True))
        autorrevision_view.controls = filas

    async def _obtener_page_sgdea_o_cdp():
        """Devuelve (page, playwright_a_cerrar_o_None). Si la sesion
        PROPIA de SGDEA esta conectada, la reutiliza (segundo elemento
        None -- esa pagina es persistente, nadie debe cerrarla aqui). Si
        no, abre una conexion CDP nueva al Chrome de Andres (mismo
        comportamiento de siempre) y devuelve su `playwright` para que el
        llamador lo detenga el ÉL MISMO al terminar (NUNCA
        browser.close() sobre una conexion CDP -- ver notas de siempre en
        este archivo/sgdea_automation.py)."""
        if sgdea_client is not None and sgdea_client.conectado:
            return sgdea_client.pagina, None
        cdp_url = config_state.get("sgdea_cdp_url") or "http://localhost:9222"
        playwright, browser, context = await sgdea_automation.conectar_chrome_existente(cdp_url)
        if not context.pages:
            await playwright.stop()
            raise sgdea_automation.AutomatizacionError("El Chrome conectado no tiene ninguna pestaña abierta.")
        return context.pages[0], playwright

    async def _detectar_y_registrar_casos_nuevos():
        """Logica compartida entre el boton manual 'Sincronizar con
        SGDEA' y el ciclo automatico en segundo plano: conecta (sesion
        propia si esta disponible, si no CDP al Chrome de Andres), lee la
        lista 'Gestionar', y registra en dashboard_casos.json los casos
        que todavia no se conocian. Devuelve la lista de CasoDashboard
        recien agregados (puede ser vacia)."""
        page_sgdea, playwright_a_cerrar = await _obtener_page_sgdea_o_cdp()
        try:
            conocidos = dashboard.radicados_conocidos()
            detectados = await sgdea_automation.detectar_casos_nuevos(page_sgdea, conocidos)
            return dashboard.registrar_casos_nuevos(detectados)
        finally:
            if playwright_a_cerrar is not None:
                await playwright_a_cerrar.stop()

    # Errores de la automatizacion que NO se arreglan reintentando (hace
    # falta una decision de Andres): el barrido los marca 'requiere_manual'
    # de una vez en vez de gastar reintentos.
    _MARCAS_REQUIERE_MANUAL = (
        "no se adivina", "otro destinatario", "revisar a mano", "no se cambia por cuenta propia",
        "hay que acortarlo", "no tiene exactamente una opcion", "ya está radicado",
    )

    def _normalizar_txt(t: str) -> str:
        return sgdea_automation._normalizar(t or "")

    CATEGORIAS_AUTOMATIZABLES = {
        _normalizar_txt("SOLICITUDES INTERNAS GENERALES"),
        _normalizar_txt("SOLICITUD DE INFORMACION DE RESOLUCIONES"),
        # Andres (29-sep, caso 2026-IE-036323): las pruebas de entrega de una
        # comunicacion masiva se responden con la plantilla MASIVA: los actos
        # se ubican en el Cuadro por el radicado interno y van en un ZIP.
        _normalizar_txt("SOLICITUD DE PRUEBAS DE ENTREGA DOCUMENTOS EXTERNOS ENVIADOS"),
    }

    def _carpeta_manual(radicado: str) -> Path:
        return _base_dir() / "adjuntos_manuales" / radicado

    def _carpeta_expedientes(radicado: str) -> Path:
        return _base_dir() / "expedientes_472_adjuntos" / radicado

    def _pdf_por_numero(carpeta: Path, acto, unico: bool) -> Optional[Path]:
        """PDF de la carpeta que lleve el NUMERO del acto en el nombre (p.ej.
        '2026_1510.pdf'); si el caso tiene un solo acto, tambien el unico PDF."""
        if not carpeta.is_dir():
            return None
        pdfs = sorted(p for p in carpeta.glob("*.pdf") if p.is_file())
        numero = str(acto.numero_final or "").lstrip("0")
        if numero:
            import re as _re
            por_numero = [p for p in pdfs if _re.search(rf"(?<!\d)0*{numero}(?!\d)", p.stem)]
            if len(por_numero) == 1:
                return por_numero[0]
        if unico and len(pdfs) == 1:
            return pdfs[0]
        return None

    def _como_expediente(radicado: str, acto, ruta: Path) -> Path:
        """30-sep (Andres, 'expediente completo con acuse de contingencia adjuntar y
        renombrar como siempre 2026_15134.pdf'; 'AUTO 1407 del 04 06 2026.pdf'): un PDF
        que YA es el expediente se sube con el nombre de siempre ('2026_15134.pdf',
        'AUTO 04 06 2026 <TITULAR>.pdf'), no con el nombre que trae. Se copia a
        expedientes_472_adjuntos\\<radicado> con ese nombre; el original no se toca."""
        import shutil
        try:
            nombre = _build_final_filename(acto.tipo_final, str(acto.numero_final or ""), acto.fecha_final or "",
                                           (acto.nombre_titular_cuadro or acto.anexo.nombre or "").strip())
        except Exception:
            return ruta
        if not nombre or nombre == ruta.name or acto.tipo_final not in ("Resolucion", "Auto"):
            return ruta
        destino_dir = _carpeta_expedientes(radicado)
        try:
            destino_dir.mkdir(parents=True, exist_ok=True)
            destino = destino_dir / nombre
            shutil.copy2(ruta, destino)
        except OSError:
            return ruta
        print(f"[adjuntos] {radicado}: {ruta.name} -> se sube como {nombre}", flush=True)
        return destino

    def _ubicar_acto(radicado: str, acto, unico: bool):
        """Sin descargar nada: ('archivo', ruta) si ya existe (lo dejo Andres
        en adjuntos_manuales o se descargo en un intento anterior),
        ('descargar', UbicacionAcuse) o ('manual', motivo)."""
        armado = _expediente_de_acuses_manuales(radicado, acto)
        if armado is not None:
            return armado
        manual = _pdf_por_numero(_carpeta_manual(radicado), acto, unico)
        if manual is not None and not _es_acuse(manual):
            print(f"[adjuntos] {radicado}: usando el PDF que dejaste a mano (ya es el expediente): {manual.name}", flush=True)
            return "archivo", _como_expediente(radicado, acto, manual)
        ya = _pdf_por_numero(_carpeta_expedientes(radicado), acto, unico)
        if ya is not None:
            print(f"[adjuntos] {radicado}: {acto.tipo_final} {acto.numero_final} ya descargado antes: {ya.name}", flush=True)
            return "archivo", ya
        nombre = acto.nombre_titular_cuadro or acto.anexo.nombre
        principal = getattr(acto, "email", "")
        # Regla de Andres (29-sep): TODOS los correos que el Cuadro tenga para
        # el acto (alcaldia, hacienda, personeria, concejo...), cada uno con su
        # ID en los reportes; el expediente lleva todos los acuses en orden
        # cronologico.
        cuadro = _get_cuadro_index()
        rad_interno = acto.anexo.expediente if "-IE-" in (acto.anexo.expediente or "").upper() else ""
        correos = (cuadro.correos_del_acto(acto.tipo_final, acto.numero_final, principal, rad_interno)
                   if cuadro is not None else fuentes_acuses.partir_correos(principal))
        estado_idx, reporte_idx = _get_estado_mensajes_index(), _get_reporte_envios_index()
        if len(correos) > 1:
            ubs, sin_mensaje, motivo = fuentes_acuses.ubicar_acuses_de_acto(
                acto.tipo_final, acto.numero_final, acto.fecha_final, nombre, correos, estado_idx, reporte_idx,
            )
            if ubs:
                return "descargar", (ubs, sin_mensaje)
            if motivo and "no aparece en" not in motivo:
                return _de_descargas(radicado, acto, motivo)
        # Un solo correo (o ninguno de los correos aparecio por separado): la
        # busqueda de siempre (correo principal, y si no, por nombre).
        ub = fuentes_acuses.ubicar_acuse(
            acto.tipo_final, acto.numero_final, acto.fecha_final, nombre, principal, estado_idx, reporte_idx,
        )
        if ub.fuente == fuentes_acuses.FUENTE_MANUAL:
            return _de_descargas(radicado, acto, ub.motivo)
        return "descargar", ([ub], [c for c in correos if c != principal] if len(correos) > 1 else [])

    _cache_acuses_pdf: dict = {}

    def _acuse_de_pdf(ruta: Path):
        """El Acuse que trae un PDF de acuse RPost (el que se baja del portal:
        2 paginas + un .eml adjunto), o None si el PDF no es un acuse (p.ej.
        ya es el expediente armado). Con cache por archivo y fecha."""
        try:
            clave = (str(ruta), ruta.stat().st_mtime)
        except OSError:
            return None
        if clave not in _cache_acuses_pdf:
            try:
                _cache_acuses_pdf[clave] = extract_acuse_from_pdf(ruta.read_bytes(), ruta.name)
            except Exception:
                _cache_acuses_pdf[clave] = None
        return _cache_acuses_pdf[clave]

    def _es_acuse(ruta: Path) -> bool:
        return _acuse_de_pdf(ruta) is not None

    def _acuse_es_del_acto(ac, acto) -> bool:
        """Nunca se adivina: tipo y fecha iguales, y ademas el numero (o, en
        Autos -- el acuse trae la numeracion SIGAA, p.ej. 020113 para el Auto
        2128 --, el correo o el nombre del titular del Cuadro)."""
        def num(n):
            t = str(n or "").strip()
            return str(int(t)) if t.isdigit() else t
        if ac.tipo != acto.tipo_final:
            return False
        correos = {c.lower() for c in fuentes_acuses.partir_correos(getattr(acto, "email", ""))}
        mismo_correo = bool(ac.destinatario_email) and (ac.destinatario_email or "").lower() in correos
        titular = sgdea_automation._normalizar(acto.nombre_titular_cuadro or acto.anexo.nombre or "")
        mismo_titular = bool(titular) and titular == sgdea_automation._normalizar(ac.nombre_titular or "")
        if (ac.fecha or "") != (acto.fecha_final or ""):
            # 30-sep: el acuse del Auto 2298 (Robin Arley Fandiño, 2026-IE-036694)
            # trae el Auto del 18/09/2026 y el Cuadro dice 17/09/2026. Solo en
            # Autos, y solo si coinciden A LA VEZ el correo y el titular, se
            # acepta hasta 3 dias de diferencia.
            try:
                dias = abs((datetime.strptime(ac.fecha, "%d/%m/%Y") - datetime.strptime(acto.fecha_final, "%d/%m/%Y")).days)
            except (TypeError, ValueError):
                return False
            return acto.tipo_final == "Auto" and dias <= 3 and mismo_correo and mismo_titular
        if num(ac.numero) and num(ac.numero) == num(acto.numero_final):
            return True
        if acto.tipo_final != "Auto":
            return False
        return mismo_correo or mismo_titular

    def _expediente_de_acuses_manuales(radicado: str, acto):
        """Pedido de Andres (29-sep, 2026-IE-036231): si lo que hay a mano es un
        ACUSE (no el expediente), se lee, se verifica que sea de este acto y se
        arma el expediente con la funcion de acuses manuales (merge_acuses),
        con todos los acuses del acto que haya, en orden cronologico."""
        carpeta = _carpeta_manual(radicado)
        if not carpeta.is_dir():
            return None
        acuses, archivos = [], []
        for f in sorted(carpeta.glob("*.pdf")):
            ac = _acuse_de_pdf(f)
            if ac is not None and _acuse_es_del_acto(ac, acto):
                acuses.append(ac)
                archivos.append(f.name)
        if not acuses:
            return None
        try:
            exp = merge_acuses(acuses, _get_cuadro_index())
        except Exception as exc:
            return "manual", f"{acto.tipo_final} {acto.numero_final}: no se pudo armar el expediente con {archivos}: {exc}"
        destino = _carpeta_expedientes(radicado)
        destino.mkdir(parents=True, exist_ok=True)
        ruta = destino / exp.final_filename
        ruta.write_bytes(exp.pdf_bytes)
        print(f"[adjuntos] {radicado}: {acto.tipo_final} {acto.numero_final}: expediente armado con el/los acuse(s) "
              f"que dejaste a mano ({', '.join(archivos)}) -> {ruta.name}", flush=True)
        return "archivo", ruta

    def _carpetas_descargas() -> list:
        """Donde Andres baja los acuses a mano: su carpeta Descargas (y la que
        contiene la carpeta de Insignia, si es otra)."""
        carpetas = [Path.home() / "Downloads", Path.home() / "Descargas"]
        try:
            carpetas.append(_base_dir().parent.parent)  # ...\Downloads\Automatizador_472_App\dist -> Downloads
        except Exception:
            pass
        vistas, unicas = set(), []
        for c in carpetas:
            try:
                clave = str(c.resolve()).lower()
            except Exception:
                continue
            if clave not in vistas and c.is_dir():
                vistas.add(clave)
                unicas.append(c)
        return unicas

    def _carpetas_acuses_sueltos() -> list:
        """Donde Andres deja acuses sueltos, fuera de la carpeta del caso:
        Descargas y la RAIZ de adjuntos_manuales (30-sep: dejo ahi 9 acuses
        'acuse AUTO DE 17 SEP 2026 <NOMBRE>.pdf')."""
        carpetas = list(_carpetas_descargas())
        raiz = _base_dir() / "adjuntos_manuales"
        if raiz.is_dir():
            carpetas.append(raiz)
        return carpetas

    _MAX_BYTES_ACUSE_SUELTO = 20_000_000

    def _acuses_sueltos() -> list:
        """[(ruta, Acuse)] de los PDF de acuse RPost en el primer nivel de esas
        carpetas, reconocidos por su CONTENIDO (no por el nombre: 30-sep, los
        nombres traian el mes en letras y dos venian cruzados -- 'AUTO DE 01 SEP
        2026 MIURIKA...' era el acuse de David Jaimes). Con cache por archivo."""
        out = []
        for carpeta in _carpetas_acuses_sueltos():
            try:
                archivos = sorted(p for p in carpeta.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
                                  and not p.name.startswith("~$"))
            except OSError:
                continue
            for p in archivos:
                try:
                    if p.stat().st_size > _MAX_BYTES_ACUSE_SUELTO:
                        continue
                except OSError:
                    continue
                ac = _acuse_de_pdf(p)
                if ac is not None:
                    out.append((p, ac))
        return out

    def _copiar_a_carpeta_caso(radicado: str, ruta: Path) -> Path:
        """Copia `ruta` a adjuntos_manuales\\<radicado> (queda con el caso). Si ya
        hay un archivo con ese nombre y otro tamaño, se guarda como 'x (2).pdf'."""
        import shutil
        destino_dir = _carpeta_manual(radicado)
        destino_dir.mkdir(parents=True, exist_ok=True)
        destino = destino_dir / ruta.name
        n = 2
        try:
            while destino.exists() and destino.stat().st_size != ruta.stat().st_size:
                destino = destino_dir / f"{ruta.stem} ({n}){ruta.suffix}"
                n += 1
            if not destino.exists():
                shutil.copy2(ruta, destino)
        except OSError:
            return ruta
        return destino

    def _piezas_contingencia(radicado: str, acto):
        return contingencia.piezas(
            _carpetas_acuses_sueltos() + [_carpeta_manual(radicado)], acto.tipo_final, acto.numero_final,
            acto.fecha_final, acto.nombre_titular_cuadro or acto.anexo.nombre or "",
            fuentes_acuses.partir_correos(getattr(acto, "email", "")))

    def _armar_contingencia(radicado: str, acto):
        """1-oct (franja 1-16 de junio, acuse manual): acto (R_/AA_) + acta
        (A<ticket>_...) + acuse de contingencia del Ironport, sueltos en Descargas
        o en adjuntos_manuales -> el expediente, con el nombre de siempre."""
        try:
            pz = _piezas_contingencia(radicado, acto)
            if pz is None:
                return None
            nombre = _build_final_filename(acto.tipo_final, str(acto.numero_final or ""), acto.fecha_final or "",
                                           (acto.nombre_titular_cuadro or acto.anexo.nombre or "").strip())
            destino_dir = _carpeta_expedientes(radicado)
            destino_dir.mkdir(parents=True, exist_ok=True)
            ruta = destino_dir / nombre
            ruta.write_bytes(contingencia.unir(list(pz)))
        except Exception as exc:
            print(f"[adjuntos] {radicado}: no se pudo armar con las piezas de contingencia: {exc}", flush=True)
            return None
        print(f"[adjuntos] {radicado}: {acto.tipo_final} {acto.numero_final}: expediente armado con acto + acta + "
              f"acuse de contingencia ({', '.join(p.name for p in pz)}) -> {nombre}", flush=True)
        return "archivo", ruta

    def _de_descargas(radicado: str, acto, motivo: str):
        """Antes de pedirlo a mano: ¿ya esta en Descargas (o suelto en
        adjuntos_manuales)? (29-sep: '2026_24208.pdf' y 'Auto 2128 del 08 09
        2026.pdf' estaban ahi y no se tomaron).
          1. Por CONTENIDO: todo acuse RPost suelto que sea de ESTE acto (tipo,
             fecha y numero, o correo/titular del Cuadro) se copia a
             adjuntos_manuales\\<radicado> y se arma el expediente con todos.
          2. Por NOMBRE: un PDF que no es acuse (p.ej. el expediente ya armado)."""
        propios = [(p, ac) for p, ac in _acuses_sueltos() if _acuse_es_del_acto(ac, acto)]
        if propios:
            copiados = [_copiar_a_carpeta_caso(radicado, p).name for p, _ac in propios]
            print(f"[adjuntos] {radicado}: {acto.tipo_final} {acto.numero_final}: acuse(s) reconocido(s) por su "
                  f"contenido en Descargas/adjuntos_manuales: {', '.join(p.name for p, _ac in propios)}", flush=True)
            armado = _expediente_de_acuses_manuales(radicado, acto)
            if armado is not None:
                return armado
            motivo = motivo + f" (se copiaron {copiados} pero no se pudo armar el expediente)"
        armado = _armar_contingencia(radicado, acto)
        if armado is not None:
            return armado
        ruta, nota = adjuntos_locales.buscar_en_descargas(
            _carpetas_descargas(), acto.tipo_final, acto.numero_final, acto.fecha_final,
            acto.nombre_titular_cuadro or acto.anexo.nombre,
        )
        if ruta is None:
            return "manual", motivo + (f" ({nota})" if nota else "")
        if _es_acuse(ruta):
            # Si fuera de este acto ya lo habria tomado el paso 1: el nombre engaña.
            ac = _acuse_de_pdf(ruta)
            # (sin "<tipo> <n> del dd/mm/aaaa" para el acto ajeno: la autorrevision
            # lee de este mensaje los actos que faltan)
            return "manual", (f"{ruta.name} es el acuse de {ac.tipo} {ac.numero} ({ac.fecha}, "
                              f"{ac.nombre_titular}), no de {acto.tipo_final} {acto.numero_final} del "
                              f"{acto.fecha_final} -- no se usa. {motivo}")
        destino = _copiar_a_carpeta_caso(radicado, ruta)
        print(f"[adjuntos] {radicado}: {nota} -> {destino}", flush=True)
        return "archivo", _como_expediente(radicado, acto, destino)

    AVISO_CONECTAR_CENTRO = ("conecta el Centro de Envíos (Configuración) para que Insignia baje "
                             "este acuse sola")

    CENTRO_REINTENTO_SEG = 2 * 3600
    _centro_sin_resultado: dict = {}   # (tipo, numero, fecha) -> momento de la ultima busqueda sin acuse util

    def _centro_envios_listo() -> bool:
        return centro_envios is not None and centro_envios.abierto

    def _centro_aplica(acto, motivo: str) -> bool:
        """Acuses de menos de un mes que no estan en los reportes / portal nuevo
        (guia de Andres, 1-oct): ese es el caso del Centro de Envios."""
        if acto.tipo_final not in ("Resolucion", "Auto"):
            return False
        if not any(k in (motivo or "") for k in ("retraso", "no aparece en Reporte_Envios", "aún no lo tiene")):
            return False
        try:
            fecha = datetime.strptime(acto.fecha_final or "", "%d/%m/%Y").date()
        except ValueError:
            return False
        return centro_rango_busqueda(fecha) is not None

    async def _desde_centro_envios(radicado: str, acto) -> tuple:
        """(('archivo', ruta) | None, nota). Busca y baja del Centro de Envios los
        acuses del acto (cada correo del Cuadro), los deja en
        adjuntos_manuales\\<radicado>\\<ID>.pdf y arma el expediente con los que
        sean DE ESTE ACTO por contenido (_expediente_de_acuses_manuales)."""
        cuadro = _get_cuadro_index()
        principal = getattr(acto, "email", "") or ""
        rad_interno = acto.anexo.expediente if "-IE-" in (acto.anexo.expediente or "").upper() else ""
        try:
            correos = cuadro.correos_del_acto(acto.tipo_final, acto.numero_final, principal, rad_interno) if cuadro else []
        except Exception:
            correos = []
        correos = correos or fuentes_acuses.partir_correos(principal)
        if not correos:
            return None, "sin correo en el Cuadro para buscarlo en el Centro de Envíos"
        fecha = datetime.strptime(acto.fecha_final, "%d/%m/%Y").date()
        etiqueta = f"{acto.tipo_final} {acto.numero_final}"
        clave = (acto.tipo_final, str(acto.numero_final), acto.fecha_final)
        # cada busqueda tarda ~15-30 s: lo que no aparecio no se vuelve a buscar en 2 horas
        # (las masivas tienen decenas de actos y se reintentan cada pocos minutos)
        hace = datetime.now().timestamp() - _centro_sin_resultado.get(clave, 0)
        if hace < CENTRO_REINTENTO_SEG:
            return None, f"Centro de Envíos: buscado hace {int(hace // 60)} min sin acuse; se vuelve a buscar en 2 h"
        print(f"[centro_envios] {radicado}: {etiqueta}: buscando con {correos}...", flush=True)
        try:
            bajados, nota = await centro_envios.buscar_y_descargar(acto.tipo_final, acto.numero_final, fecha, correos,
                                                                   radicados=_notificacion_de(acto)[0])
        except CentroEnviosSinSesion as exc:
            return None, f"{exc} -- {AVISO_CONECTAR_CENTRO}"
        except CentroEnviosError as exc:
            return None, f"Centro de Envíos: {exc}"
        carpeta = _carpeta_manual(radicado)
        carpeta.mkdir(parents=True, exist_ok=True)
        for fila, nombre, datos in bajados:
            if datos[:2] == b"PK":   # la pagina no pudo convertir el ZIP: se saca el PDF del acuse
                try:
                    datos = extract_acuse(datos).acuse_bytes or b""
                except Exception:
                    datos = b""
            if not datos:
                continue
            destino = carpeta / f"{fila.message_id}.pdf"
            if not destino.exists():
                destino.write_bytes(datos)
            print(f"[centro_envios] {radicado}: {etiqueta}: bajado {destino.name} ({fila.asunto[-40:]})", flush=True)
        armado = _expediente_de_acuses_manuales(radicado, acto)
        if armado is not None and armado[0] == "archivo":
            return armado, ""
        if bajados:
            nota = (nota + "; " if nota else "") + "lo bajado no corresponde a este acto por contenido"
        _centro_sin_resultado[clave] = datetime.now().timestamp()
        return None, f"Centro de Envíos: {nota or 'sin resultados'}"

    def _correos_de(acto) -> list:
        cuadro = _get_cuadro_index()
        principal = getattr(acto, "email", "") or ""
        rad_interno = acto.anexo.expediente if "-IE-" in (acto.anexo.expediente or "").upper() else ""
        try:
            correos = cuadro.correos_del_acto(acto.tipo_final, acto.numero_final, principal, rad_interno) if cuadro else []
        except Exception:
            correos = []
        return correos or fuentes_acuses.partir_correos(principal)

    def _notificacion_de(acto) -> tuple:
        """([radicados EE], [fechas]) de 'RADICADO / FECHA NOTIFICACION ELECTRONICA'
        del Cuadro para el acto (todas sus filas)."""
        cuadro = _get_cuadro_index()
        try:
            filas = cuadro.notificacion_electronica(acto.tipo_final, acto.numero_final) if cuadro else []
        except Exception:
            filas = []
        correos = set(_correos_de(acto))
        if correos and any(f.email in correos for f in filas):
            filas = [f for f in filas if not f.email or f.email in correos]
        radicados = list(dict.fromkeys(f.radicado for f in filas if f.radicado))
        fechas = []
        for f in filas:
            try:
                fechas.append(datetime.strptime(f.fecha or "", "%d/%m/%Y").date())
            except ValueError:
                pass
        return radicados, sorted(set(fechas))

    async def _desde_reporte_centro(radicado: str, acto) -> tuple:
        """Actos desde el 17-jun que no estan en el Excel Reporte_Envios (o cuyo
        acuse aun no publica el portal nuevo): el ID sale del 'Reporte de Envíos'
        del Centro (todos los remitentes, sin limite de 30 dias), por correo del
        Cuadro + acto en el asunto, o por el radicado de notificacion electronica
        del Cuadro. El acuse se baja del Centro si el envio es de los ultimos 30
        dias, si no del PORTAL NUEVO. Cada acuse se verifica por contenido antes
        de usarlo. (('archivo', ruta) | None, nota)."""
        etiqueta = f"{acto.tipo_final} {acto.numero_final}"
        clave = ("reporte",) + (acto.tipo_final, str(acto.numero_final), acto.fecha_final)
        hace = datetime.now().timestamp() - _centro_sin_resultado.get(clave, 0)
        if hace < CENTRO_REINTENTO_SEG:
            return None, f"buscado en el Reporte de Envíos hace {int(hace // 60)} min sin acuse; se vuelve a buscar en 2 h"
        correos = _correos_de(acto)
        if not correos:
            return None, "sin correo en el Cuadro para buscarlo"
        radicados, fechas_notif = _notificacion_de(acto)
        fecha = datetime.strptime(acto.fecha_final, "%d/%m/%Y").date()
        print(f"[centro_envios] {radicado}: {etiqueta}: buscando en el Reporte de Envíos con {correos}"
              + (f" / radicado {radicados}" if radicados else "") + "...", flush=True)
        try:
            filas, nota = await centro_envios.ids_de_acto(acto.tipo_final, acto.numero_final, fecha, correos,
                                                          radicados=radicados, fechas_notif=fechas_notif)
        except CentroEnviosSinSesion as exc:
            return None, f"{exc} -- {AVISO_CONECTAR_CENTRO}"
        except CentroEnviosError as exc:
            return None, f"Reporte de Envíos: {exc}"
        if not filas:
            _centro_sin_resultado[clave] = datetime.now().timestamp()
            return None, f"Reporte de Envíos: {nota or 'sin resultados'}"
        carpeta = _carpeta_manual(radicado)
        carpeta.mkdir(parents=True, exist_ok=True)
        notas, pendientes = [], False
        for fila in filas:
            destino = carpeta / f"{fila.message_id}.pdf"
            if destino.exists():
                continue
            enviado = centro_fecha_de_fila(fila)
            datos, origen = b"", ""
            if enviado is not None and (datetime.now().date() - enviado).days <= 29:
                try:
                    _n, datos = await centro_envios.descargar_por_id(fila)
                    origen = "Centro de Envíos"
                    if datos[:2] == b"PK":
                        datos = (await asyncio.to_thread(extract_acuse, datos)).acuse_bytes or b""
                except (CentroEnviosError, ExtractionError) as exc:
                    notas.append(f"ID {fila.message_id[:12]}…: {exc}")
                    pendientes = True
                    continue
            else:
                if client is None:
                    notas.append(f"ID {fila.message_id[:12]}… (enviado {fila.fecha}): conecta el portal nuevo (Configuración) para bajarlo")
                    pendientes = True
                    continue
                try:
                    zb = await asyncio.to_thread(client.download_zip_bytes, fila.message_id)
                    datos = (await asyncio.to_thread(extract_acuse, zb)).acuse_bytes or b""
                    origen = "portal nuevo"
                except NotFoundError:
                    notas.append(f"ID {fila.message_id[:12]}… (enviado {fila.fecha}): el portal nuevo aún no lo tiene")
                    pendientes = True
                    continue
                except (PortalError, ExtractionError) as exc:
                    notas.append(f"ID {fila.message_id[:12]}…: {exc}")
                    pendientes = True
                    continue
            if not datos:
                notas.append(f"ID {fila.message_id[:12]}…: no trae el PDF del acuse")
                continue
            destino.write_bytes(datos)
            print(f"[centro_envios] {radicado}: {etiqueta}: ID {fila.message_id} ({fila.asunto[:60]}) -> {origen} -> "
                  f"{destino.name}", flush=True)
        armado = _expediente_de_acuses_manuales(radicado, acto)
        if armado is not None and armado[0] == "archivo":
            return armado, ""
        if not pendientes:
            _centro_sin_resultado[clave] = datetime.now().timestamp()
        hallados = ", ".join(f"{f.message_id[:12]}… ({f.asunto[:50]})" for f in filas)
        return None, "Reporte de Envíos: " + ("; ".join(notas) or
                                               f"se hallaron {hallados} pero su acuse no corresponde a este acto por "
                                               "contenido -- revísalo a mano")

    async def _otras_fuentes(radicado: str, acto, motivo: str) -> tuple:
        """Regla de Andres (1-oct): todo acto esta en alguna fuente segun su fecha;
        solo la franja del 1 al 16 de junio es acuse manual."""
        try:
            fecha = datetime.strptime(acto.fecha_final or "", "%d/%m/%Y").date()
        except ValueError:
            return "manual", motivo
        if acto.tipo_final not in ("Resolucion", "Auto"):
            return "manual", motivo
        if fuentes_acuses.fuente_por_fecha(fecha) == fuentes_acuses.FUENTE_MANUAL:
            return "manual", (f"{motivo} -- deja en Descargas el acto (R_/AA_…), su acta (A…_R_…) y el acuse de "
                              "contingencia (<número>_<correo>.pdf) y Insignia los une")
        if fuentes_acuses.fuente_por_fecha(fecha) == fuentes_acuses.FUENTE_ESTADO_MENSAJES:
            return "manual", motivo   # portal antiguo: el ID sale del archivo EstadoMensajes
        # desde el 17 de junio
        if not _centro_envios_listo():
            return "manual", f"{motivo} -- {AVISO_CONECTAR_CENTRO}"
        if centro_rango_busqueda(fecha) is not None and _centro_aplica(acto, motivo):
            res, nota = await _desde_centro_envios(radicado, acto)
            if res is not None:
                return res
            motivo = f"{motivo} ({nota})" if nota else motivo
        if "no aparece en Reporte_Envios" in motivo:
            # 1-oct: el Excel Reporte_Envios solo trae notificacionesmen@; el Reporte de
            # Envíos del Centro trae TODOS los remitentes (tambien mineducacion472@, por
            # donde el SGDEA notifica 'Comunicación de respuesta (2026-EE-…)').
            res, nota = await _desde_reporte_centro(radicado, acto)
            if res is not None:
                return res
            motivo = f"{motivo} ({nota})" if nota else motivo
            if "ningún envío a" in (nota or ""):
                motivo += (" -- no está en ningún aplicativo de 4-72 consultado (Reporte_Envios, Centro de Envíos con "
                           "todos los remitentes); si tienes el acuse, déjalo en Descargas y Insignia lo toma")
        return "manual", motivo

    async def _descargar_acto(radicado: str, acto, ubicacion, avisos: Optional[list] = None
                              ) -> tuple[Optional[Path], str, bool]:
        """Baja el acuse de CADA destinatario (portal que corresponda a la
        fuente) y arma UN expediente con todos, en orden cronologico
        (merge_acuses), en expedientes_472_adjuntos\\<radicado>. Si falla el
        del destinatario principal, el acto no se arma; si falla el de otro
        destinatario, se arma sin el y queda un aviso. (ruta, motivo, manual)."""
        ubs, sin_mensaje = ubicacion
        etiqueta = f"{acto.tipo_final} {acto.numero_final}"
        acuses, avisos_acto = [], []
        for i, ub in enumerate(ubs):
            es_portal_nuevo = ub.fuente == fuentes_acuses.FUENTE_REPORTE_ENVIOS
            cliente_472 = client if es_portal_nuevo else legacy_client
            if cliente_472 is None:
                return None, f"el portal {'nuevo' if es_portal_nuevo else 'antiguo'} de 4-72 no está conectado", False
            if ub.advertencia and "no coincide" in ub.advertencia:
                avisos_acto.append(f"{etiqueta}: {ub.advertencia}")
            print(f"[adjuntos] {radicado}: {etiqueta} -> {ub.fuente} ID {ub.message_id}"
                  + (f" (destinatario {i + 1} de {len(ubs)})" if len(ubs) > 1 else "")
                  + (f" (aviso: {ub.advertencia})" if ub.advertencia else ""), flush=True)
            try:
                if es_portal_nuevo:
                    zip_bytes_472 = await asyncio.to_thread(cliente_472.download_zip_bytes, ub.message_id)
                    acuses.append(await asyncio.to_thread(extract_acuse, zip_bytes_472))
                else:
                    pdf_bytes_472 = await cliente_472.buscar_y_descargar_testigo(ub.message_id)
                    acuses.append(await asyncio.to_thread(extract_acuse_from_pdf, pdf_bytes_472, ub.message_id))
            except (NotFoundError, LegacyNotFoundError) as exc:
                if i == 0:
                    return None, f"{etiqueta}: el portal aún no lo tiene ({exc})", True
                avisos_acto.append(f"{etiqueta}: el acuse del ID {ub.message_id[:12]}… aún no está en el portal ({exc})")
            except (PortalError, LegacyPortalError, ExtractionError) as exc:
                if i == 0:
                    return None, f"{etiqueta}: {exc}", False
                avisos_acto.append(f"{etiqueta}: no se pudo usar el acuse del ID {ub.message_id[:12]}… ({exc})")
        try:
            expediente_472 = await asyncio.to_thread(merge_acuses, acuses, _get_cuadro_index())
        except (ExtractionError, ValueError) as exc:
            return None, f"{etiqueta}: {exc}", False
        if sin_mensaje:
            avisos_acto.append(f"{etiqueta}: estos correos del Cuadro no tienen mensaje en los reportes -- "
                               f"el expediente va sin su acuse: {', '.join(sin_mensaje)}")
        if avisos is not None:
            avisos.extend(avisos_acto)
        carpeta = _carpeta_expedientes(radicado)
        carpeta.mkdir(parents=True, exist_ok=True)
        out_path_472 = carpeta / expediente_472.final_filename
        out_path_472.write_bytes(expediente_472.pdf_bytes)
        if len(acuses) > 1:
            print(f"[adjuntos] {radicado}: {etiqueta}: expediente con {len(acuses)} acuses (orden cronologico).", flush=True)
        return out_path_472, "", False

    def _carpeta_caso(radicado: str) -> Optional[Path]:
        """Descargas\\<radicado>\\ (Andres, 1-oct, 2026-IE-036987): ahi reune los
        PDF que hubo que pedir (Magda) junto con los demas de la respuesta."""
        try:
            return carpeta_caso.carpeta_del_caso(_carpetas_descargas(), radicado)
        except Exception:
            return None

    def _aplicar_carpeta_caso(radicado: str, actos: list) -> tuple:
        """(actos, avisos, problemas). Cada caso pedido toma su PDF de la carpeta
        del caso si esta ahi (ver backend/carpeta_caso.py)."""
        carpeta = _carpeta_caso(radicado)
        if carpeta is None:
            return actos, [], []
        docs, ilegibles = carpeta_caso.leer(carpeta)
        print(f"[carpeta_caso] {radicado}: {carpeta} -> {len(docs)} resolución(es) identificada(s)"
              + (f"; sin identificar: {ilegibles}" if ilegibles else ""), flush=True)
        actos, avisos, _pend, problemas = carpeta_caso.asignar(docs, actos)
        for a in actos:
            if getattr(a, "archivo_carpeta", None):
                print(f"[carpeta_caso] {radicado}: {a.anexo.expediente or '-'} -> {a.tipo_final} {a.numero_final} "
                      f"del {a.fecha_final} ({Path(a.archivo_carpeta).name})", flush=True)
        return actos, avisos, list(ilegibles) + problemas

    def _texto_pendientes(radicado: str, actos: list) -> str:
        magda = [a for a in actos if a.pedir_a_magda]
        otros = [a for a in actos if not a.emparejado and not a.pedir_a_magda]
        partes = []
        if magda:
            partes.append("PEDIR A MAGDA (expediente anterior a 2025): "
                          + "; ".join(sgdea_carta._describir_acto(a) for a in magda))
        if otros:
            partes.append("NO UBICADOS en el Cuadro: " + "; ".join(
                sgdea_carta._describir_acto(a) + (f" [{a.warnings[-1]}]" if a.warnings else "") for a in otros))
        donde = _carpetas_descargas()[0] / radicado if _carpetas_descargas() else Path(radicado)
        partes.append(f"cuando tengas los PDF, déjalos (con los demás de la respuesta) en {donde}\\ y Insignia arma "
                      f"la respuesta con los {len(actos)} caso(s) pedidos")
        return "; ".join(partes)

    def _anotar_pedir_a_magda(radicado: str, actos: list) -> None:
        """adjuntos_manuales\\<radicado>\\PEDIR_A_MAGDA.txt con lo que no se puede
        responder con el Cuadro (anteriores a 2025 y no ubicados)."""
        magda = [a for a in actos if a.pedir_a_magda]
        otros = [a for a in actos if not a.emparejado and not a.pedir_a_magda]
        lineas = [f"{radicado} -- {datetime.now():%d/%m/%Y %H:%M}", ""]
        if magda:
            lineas += ["PEDIR A MAGDA (anteriores a 2025):"] + [f"  - {sgdea_carta._describir_acto(a)}" for a in magda] + [""]
        if otros:
            lineas += ["NO UBICADOS en el Cuadro (revisar o actualizar el Cuadro):"] + \
                      [f"  - {sgdea_carta._describir_acto(a)}" for a in otros]
        try:
            carpeta = _carpeta_manual(radicado)
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / "PEDIR_A_MAGDA.txt").write_text("\r\n".join(lineas) + "\r\n", encoding="utf-8")
        except OSError as exc:
            print(f"[preparacion] {radicado}: no se pudo escribir PEDIR_A_MAGDA.txt: {exc}", flush=True)

    def _ids_manuales(radicado: str) -> tuple:
        """IDs del portal nuevo que Andres dejo en adjuntos_manuales\\<radicado>\\
        (ver backend/adjuntos_ids.py)."""
        return adjuntos_ids.leer_ids(_carpeta_manual(radicado))

    async def _preparar_desde_ids(radicado: str, carta, actos: list, ids: list, fuente: str
                                  ) -> tuple[Optional[str], str, bool]:
        if client is None:
            return None, "el portal nuevo de 4-72 no está conectado", False
        rutas, motivo, manual = await adjuntos_ids.preparar_desde_ids(
            ids, fuente, actos, _carpeta_expedientes(radicado),
            descargar=client.download_zip_bytes, extraer=extract_acuse,
            fusionar=lambda acuses: merge_acuses(acuses, _get_cuadro_index()),
            errores_no_encontrado=(NotFoundError,), errores_otros=(PortalError, ExtractionError),
            avisos=carta.warnings, log=lambda m: print(f"[adjuntos] {radicado}: {m}", flush=True),
        )
        if rutas is None:
            if manual:
                _carpeta_manual(radicado).mkdir(parents=True, exist_ok=True)
            return None, motivo, manual
        if not carta.es_masiva:
            return str(rutas[0]), "", False
        return _comprimir_masiva(radicado, carta, rutas), "", False

    def _comprimir_masiva(radicado: str, carta, rutas: list) -> str:
        destino = _carpeta_expedientes(radicado) / (getattr(carta, "adjunto_nombre", "") or f"{radicado}.zip")
        destino, n, megas = adjuntos_ids.comprimir(rutas, destino)
        print(f"[adjuntos] {radicado}: ZIP listo -> {destino.name} ({n} expediente(s), {megas:.1f} MB).", flush=True)
        if megas > 50:
            carta.warnings.append(f"El ZIP pesa {megas:.0f} MB: revisa que SGDEA lo haya aceptado completo.")
        return str(destino)

    async def _preparar_adjunto_caso(radicado: str, carta, actos: list, cuadro) -> tuple[Optional[str], str, bool]:
        """Individual: el PDF del acto. Masiva: un solo ZIP '<radicado>.zip'
        con el PDF de cada acto (formato aprobado, caso 2026-IE-035664); si
        Andres dejo ese zip a mano en adjuntos_manuales\\<radicado>, se usa
        tal cual. PRIMERO se ubica cada acto sin descargar nada: si alguno
        toca a mano, no se descarga ninguno (evidencia log 28-sep: 035664 bajo
        3 acuses en cada vuelta y se detenia en el 4o). Lo ya descargado se
        reutiliza. Devuelve (ruta, motivo, requiere_manual)."""
        if not actos:
            return None, "la petición no trae actos identificables", True
        nombre_zip = getattr(carta, "adjunto_nombre", "") or f"{radicado}.zip"
        # 1-oct (2026-IE-036987): lo que viene de la carpeta del caso en Descargas
        # va tal cual (con el nombre de siempre); el resto sigue el camino normal.
        de_carpeta = []
        for a in actos:
            if getattr(a, "archivo_carpeta", None):
                destino = _carpeta_expedientes(radicado) / _build_final_filename(
                    a.tipo_final, str(a.numero_final or ""), a.fecha_final or "",
                    (a.nombre_titular_cuadro or a.anexo.nombre or "").strip())
                destino.parent.mkdir(parents=True, exist_ok=True)
                if not destino.is_file() or destino.stat().st_size != Path(a.archivo_carpeta).stat().st_size:
                    shutil.copyfile(a.archivo_carpeta, destino)
                de_carpeta.append(str(destino))
        actos = [a for a in actos if not getattr(a, "archivo_carpeta", None)]
        if not actos:
            if not carta.es_masiva:
                return de_carpeta[0], "", False
            return _comprimir_masiva(radicado, carta, de_carpeta), "", False
        if carta.es_masiva and not de_carpeta:
            zip_manual = _carpeta_manual(radicado) / nombre_zip
            if zip_manual.is_file():
                return str(zip_manual), "", False
        ids, fuente_ids = _ids_manuales(radicado)
        if ids and not de_carpeta:
            return await _preparar_desde_ids(radicado, carta, actos, ids, fuente_ids)
        unico = len(actos) == 1 and not de_carpeta
        ubicaciones = [(acto, *_ubicar_acto(radicado, acto, unico)) for acto in actos]
        # 1-oct-2026: lo que falta y tiene menos de un mes se busca en el Centro
        # de Envios (si Andres ya inicio sesion alli); si no, se le avisa.
        # 1-oct-2026 (regla de Andres): cada acto que falte se busca donde debe
        # estar segun su FECHA (ver _otras_fuentes): ultimo mes -> Centro de
        # Envios; mas viejo (desde el 17-jun) -> portal nuevo (con el ID del
        # Reporte de Envios del Centro si no esta en el Excel); 1-16 jun ->
        # acuse manual (contingencia); hasta el 31-may -> portal antiguo.
        con_centro = []
        for acto, clase, dato in ubicaciones:
            if clase == "manual":
                clase, dato = await _otras_fuentes(radicado, acto, dato)
            con_centro.append((acto, clase, dato))
        ubicaciones = con_centro
        manuales = [dato for _, clase, dato in ubicaciones if clase == "manual"]
        if manuales:
            _carpeta_manual(radicado).mkdir(parents=True, exist_ok=True)
            return None, "; ".join(manuales + [
                f"deja el/los PDF en {_carpeta_manual(radicado)} (con el número del acto en el nombre), "
                "o un ids.txt con los ID de mensaje del portal nuevo (uno por línea), "
                "y pulsa 'Reintentar automático'"]), True
        rutas, faltan, alguno_manual = [], [], False
        for acto, clase, dato in ubicaciones:
            if clase == "archivo":
                rutas.append(dato)
                continue
            ruta, motivo, es_manual = await _descargar_acto(radicado, acto, dato, carta.warnings)
            if ruta is None:
                faltan.append(motivo)
                alguno_manual = alguno_manual or es_manual
            else:
                rutas.append(ruta)
        if faltan:
            if alguno_manual:
                _carpeta_manual(radicado).mkdir(parents=True, exist_ok=True)
                faltan.append(f"deja el/los PDF en {_carpeta_manual(radicado)} y pulsa 'Reintentar automático'")
            return None, "; ".join(faltan), alguno_manual
        rutas = de_carpeta + [str(r) for r in rutas]
        if not carta.es_masiva:
            return str(rutas[0]), "", False
        return _comprimir_masiva(radicado, carta, rutas), "", False

    async def _procesar_caso_automatico(
        radicado: str, columnas_crudas: list, omitir: set | None = None, tratamiento_manual: str | None = None,
    ) -> tuple[bool, str, bool, list]:
        """Version SIN interfaz de 'Gestionar caso completo', usada por el
        barrido automatico. Devuelve (ok, mensaje, requiere_manual, pasos):
          - requiere_manual=True: falta una decision de Andres (categoria,
            Doctor/Doctora dudoso, destinatario ambiguo, peticion sin actos
            identificables...) -- el barrido no lo reintenta solo.
          - pasos: pasos completados (el barrido los guarda y los omite en
            el proximo intento).
        NUNCA pulsa 'Inicio de Ciclo' ni ningun boton de envio: el caso queda
        PARA APROBAR en Memorandos (pendiente_revision_humana siempre True)."""
        rehacer = MARCA_REHACER in set(omitir or ())
        omitir = set(omitir or ()) - {MARCA_REHACER}
        cuadro = _get_cuadro_index()
        if cuadro is None:
            return False, "Cuadro_2026 no configurado.", False, []

        coord_saludo, coord_cuerpo = _coordenadas_calibradas()  # opcionales (solo respaldo)

        categoria = sgdea_automation.extraer_categoria_proceso(columnas_crudas)
        if not categoria:
            return False, "No se pudo determinar la categoría ('Proceso') del caso -- revisarlo a mano.", True, []
        # Solo se responden solas las categorias con plantilla aprobada
        # ('se remite copia y constancia de notificación'). Evidencia 28-sep:
        # 2026-IE-034825 (REMISION DE ACTOS... NOTIFICAR) pide una notificacion
        # personal y 2026-IE-036323 (PRUEBAS DE ENTREGA) pide constancias de
        # envio: responderlas con la plantilla seria un error.
        if _normalizar_txt(categoria) not in CATEGORIAS_AUTOMATIZABLES:
            return False, (f"Categoría '{categoria}' sin plantilla automática -- este tipo de solicitud "
                           "se responde a mano."), True, []

        playwright_a_cerrar = None
        try:
            page_sgdea, playwright_a_cerrar = await _obtener_page_sgdea_o_cdp()

            # ---------------- FASE 1: PREPARAR (sin tocar el documento) -----
            # Pedido de Andres (28-sep): primero la peticion (descargar y leer,
            # incluido QUIEN FIRMA al final), luego el/los adjuntos, y SOLO
            # con todo listo se crea el documento en SGDEA. Si algo de esto
            # falla, el documento NO se crea.
            carpeta_destino = str(_base_dir() / "peticiones_descargadas")
            ruta_pdf = await sgdea_automation.descargar_peticion_caso(page_sgdea, radicado, carpeta_destino)
            peticion = sgdea_peticion.leer_peticion(ruta_pdf)
            print(f"[preparacion] {radicado}: peticion leida -- firma "
                  f"{(peticion.destinatario.nombre if peticion.destinatario else None)!r}, "
                  f"{len(peticion.anexos)} acto(s) solicitado(s).", flush=True)

            if peticion.destinatario is None:
                return False, ("No se pudo leer quién firma la petición (bloque de firma al final) -- "
                               "no se crea el documento; revisarla a mano."), True, []
            nombre_firmante = peticion.destinatario.nombre
            if not peticion.destinatario.confirmado:
                print(f"[preparacion] {radicado}: AVISO -- el firmante {nombre_firmante!r} no aparece en 'Aprobó'.", flush=True)

            if tratamiento_manual in ("Doctor", "Doctora"):
                tratamiento_usado = tratamiento_manual
            else:
                tratamiento_usado, confiable = sgdea_carta.inferir_tratamiento(nombre_firmante)
                if not confiable or not tratamiento_usado:
                    return False, (
                        f"Firma la petición: '{nombre_firmante}'. No se pudo saber si es Doctor o Doctora -- "
                        "elígelo en el caso (Tratamiento) y pulsa 'Reintentar automático'. No se creó el documento."
                    ), True, []

            # 1-oct (Andres, 2026-IE-036987): la respuesta lleva EXACTAMENTE los
            # casos que pide la peticion (contados en su lista, sin duplicados).
            # Lo anterior a 2025 se pide a Magda (alerta) pero TAMBIEN va: el
            # documento no se crea hasta que sus PDF esten en Descargas\<radicado>\.
            avisos_conteo = [w for w in peticion.warnings if w.startswith("CONTEO:")]
            if avisos_conteo:
                return False, (f"{avisos_conteo[0]} No se creó el documento (la respuesta debe llevar exactamente "
                               "los casos pedidos)."), True, []
            actos = sgdea_carta.resolver_actos(peticion, cuadro)
            actos, avisos_carpeta, problemas_carpeta = _aplicar_carpeta_caso(radicado, actos)
            if problemas_carpeta:
                return False, ("Carpeta del caso en Descargas: " + "; ".join(problemas_carpeta)
                               + ". No se creó el documento (no se adivina)."), True, []
            if any(not a.emparejado for a in actos):
                _anotar_pedir_a_magda(radicado, actos)
                return False, (f"Adjunto pendiente: {_texto_pendientes(radicado, actos)}. "
                               "No se creó el documento."), True, []
            try:
                carta = sgdea_carta.generar_carta(peticion, cuadro, tratamiento_usado, actos_resueltos=actos)
            except ValueError as exc:
                return False, f"No se pudo armar la carta: {exc}. No se creó el documento.", True, []
            carta.warnings.extend(avisos_carpeta)
            if (carta.es_masiva and carta.tabla is not None and not peticion.por_radicados_internos
                    and len(carta.tabla) != len(peticion.anexos)):
                return False, (f"CONTEO: la petición pide {len(peticion.anexos)} caso(s) y el cuadro quedaría con "
                               f"{len(carta.tabla)} -- no se creó el documento."), True, []
            pedidos_magda = [a for a in actos if getattr(a, "archivo_carpeta", None)
                             and (sgdea_peticion.anio_expediente(a.anexo.expediente) or 9999) < 2025]
            if pedidos_magda:
                carta.warnings.append("Expedientes anteriores a 2025 (de Magda), incluidos desde la carpeta del caso: "
                                      + "; ".join(f"{a.anexo.expediente} -> Resolución {a.numero_final} del "
                                                  f"{a.fecha_final}" for a in pedidos_magda))

            ruta_adjunto, motivo_adjunto, adjunto_manual = await _preparar_adjunto_caso(radicado, carta, actos, cuadro)
            if ruta_adjunto is None:
                # Descarga manual (franja 1-16 jun, retraso del portal nuevo,
                # acto que no esta en los reportes): queda para Andres con la
                # carpeta donde dejar el PDF. Otros fallos (portal caido) se
                # reintentan solos.
                return False, f"Adjunto pendiente: {motivo_adjunto}. No se creó el documento.", adjunto_manual, []
            print(f"[preparacion] {radicado}: adjunto listo -> {Path(ruta_adjunto).name}. "
                  + ("Rehaciendo el cuadro y el adjunto del memorando..." if rehacer else "Creando el documento..."),
                  flush=True)
            ruta_pdf_carta_472 = ruta_adjunto

            if rehacer:
                previo = casos_pendientes.obtener_caso(radicado)
                anteriores = [f"{radicado}.zip"]
                if previo is not None and getattr(previo, "adjunto_path", ""):
                    anteriores.insert(0, Path(previo.adjunto_path).name)
                if carta.es_masiva:
                    nuevo = Path(ruta_adjunto).with_name(f"{radicado}_completo.zip")
                    shutil.copyfile(ruta_adjunto, nuevo)
                    ruta_pdf_carta_472 = str(nuevo)
                res = await sgdea_automation.rehacer_tabla_y_adjunto(page_sgdea, radicado, carta, ruta_pdf_carta_472,
                                                                    adjuntos_anteriores=anteriores)
                if not res.ok:
                    detalle = res.warnings[0] if res.warnings else "sin detalle"
                    return False, f"No se pudo rehacer el cuadro/adjunto: {detalle}", True, ["-" + MARCA_REHACER]
                carta.warnings = list(dict.fromkeys(
                    w for w in res.warnings
                    if "No se encontro 'a nombre de" not in w and "No se reconocio a que tipo de acto" not in w))
                casos_pendientes.agregar_caso(
                    casos_pendientes.CasoPendiente.desde_carta(radicado, carta, adjunto_path=ruta_pdf_carta_472 or "")
                )
                avisos = f" Avisos: {' | '.join(carta.warnings)}" if carta.warnings else ""
                return (True, f"Listo para tu revisión -- cuadro rehecho con los {len(carta.tabla or [])} caso(s) pedidos "
                        f"y adjunto {Path(ruta_pdf_carta_472).name}; sigue en Memorandos, PARA APROBAR." + avisos,
                        False, ["-" + MARCA_REHACER])

            # ---------------- FASE 2: DOCUMENTO EN SGDEA --------------------
            resultado = await sgdea_automation.gestionar_caso_completo(
                page_sgdea,
                radicado,
                carta,
                coordenada_saludo=coord_saludo,
                coordenada_cuerpo=coord_cuerpo,
                categoria_nivel1=categoria,
                ruta_pdf_carta=ruta_pdf_carta_472,
                omitir=omitir,
            )

            # Pasos para la memoria del barrido: los hechos, y con '-' los que
            # el documento NO mostro (se olvidan para rehacerlos).
            pasos_memoria = list(resultado.pasos_completados) + [
                "-" + p for p in getattr(resultado, "pasos_a_rehacer", []) or []
                if p not in resultado.pasos_completados
            ]
            if not resultado.ok:
                pasos_ok = ", ".join(resultado.pasos_completados) or "ninguno"
                detalle = resultado.warnings[0] if resultado.warnings else "Error sin detalle."
                manual = any(m in detalle.lower() for m in _MARCAS_REQUIERE_MANUAL)
                return False, f"Se detuvo -- pasos completados: {pasos_ok}. {detalle}", manual, pasos_memoria

            # Avisos ya resueltos no se muestran en la revision (en 2026-IE-036295
            # salian 3 avisos amarillos que no pedian nada): el acto ya quedo
            # identificado y el adjunto ya se subio.
            if ruta_pdf_carta_472:
                carta.warnings = [
                    w for w in carta.warnings
                    if "No se encontro el nombre de archivo final" not in w and "se intenta desambiguar" not in w
                ]
            # Aqui todos los actos ya quedaron identificados en el Cuadro (si no,
            # no se habria creado el documento): los avisos de lectura de la
            # peticion sobre titular/tipo de acto ya no piden nada (en
            # 2026-IE-036479 salian 4, repetidos). Y ningun aviso se repite.
            carta.warnings = list(dict.fromkeys(
                w for w in carta.warnings
                if "No se encontro 'a nombre de" not in w and "No se reconocio a que tipo de acto" not in w
            ))
            casos_pendientes.agregar_caso(
                casos_pendientes.CasoPendiente.desde_carta(radicado, carta, adjunto_path=ruta_pdf_carta_472 or "")
            )
            avisos = f" Avisos: {' | '.join(carta.warnings)}" if carta.warnings else ""
            return True, "Listo para tu revisión -- quedó en Memorandos, PARA APROBAR." + avisos, False, pasos_memoria
        except sgdea_automation.AutomatizacionError as exc:
            return False, str(exc), False, []
        except Exception as exc:
            return False, f"Error inesperado ({type(exc).__name__}): {exc}", False, []
        finally:
            if playwright_a_cerrar is not None:
                await playwright_a_cerrar.stop()

    # Un SOLO corredor de barridos (el ciclo). 'Sincronizar con SGDEA' no
    # corre un barrido aparte: despierta al ciclo para que corra YA, asi
    # nunca hay dos barridos a la vez.
    sgdea_auto_task = {"corriendo": False, "en_barrido": False, "forzar": False, "despertar": asyncio.Event()}
    BARRIDO_ESPERA_SESION_SEG = 180  # maximo a esperar la autoconexion antes del primer barrido

    async def _tomar_candado(quien: str, espera_max_s: int = 600) -> bool:
        """Espera (sin bloquear la interfaz) a que el candado de SGDEA este
        libre y lo toma. False si no se libero en `espera_max_s`."""
        loop = asyncio.get_running_loop()
        limite = loop.time() + espera_max_s
        while automatizacion_sgdea["activa"]:
            if loop.time() >= limite:
                return False
            await asyncio.sleep(5)
        automatizacion_sgdea["activa"] = True
        automatizacion_sgdea["quien"] = quien
        return True

    def _soltar_candado():
        automatizacion_sgdea["activa"] = False
        automatizacion_sgdea["quien"] = ""

    def _estado_barrido(texto: str, color=None):
        print(f"[barrido] {datetime.now():%H:%M:%S} {texto}", flush=True)
        # Se ve en Configuración y en el Dashboard.
        for control in (sgdea_auto_status, dashboard_sync_status):
            try:
                control.value = texto
                control.color = color or theme.TEXT_MUTED
                control.update()
            except Exception:
                pass

    RUTA_AUTORREVISION = _base_dir() / "autorrevision.json"

    def _adjunto_disponible(caso) -> tuple:
        """¿Ya apareció lo que faltaba para el adjunto de este caso?"""
        ultimo = None
        try:
            ultimo = datetime.fromisoformat(caso.auto_ultimo_intento).timestamp() if caso.auto_ultimo_intento else None
        except ValueError:
            pass
        cc = _carpeta_caso(caso.radicado)
        if cc is not None and (ultimo is None or carpeta_caso.mas_nuevo(cc) > ultimo):
            return True, f"Está la carpeta del caso en Descargas ({cc.name}, {len(carpeta_caso.pdfs(cc))} PDF).", True
        carpeta = _carpeta_manual(caso.radicado)
        if carpeta.is_dir():
            nuevos = [f for f in carpeta.iterdir() if f.is_file() and not f.name.startswith("~$")
                      and f.suffix.lower() in (".pdf", ".zip", ".txt", ".xlsx")
                      and (ultimo is None or f.stat().st_mtime > ultimo)]
            if nuevos and (any(f.suffix.lower() in (".pdf", ".zip") for f in nuevos)
                           or adjuntos_ids.leer_ids(carpeta)[0]):
                return True, f"Apareció en adjuntos_manuales: {', '.join(f.name for f in nuevos[:3])}.", True
        if (AVISO_CONECTAR_CENTRO in (caso.auto_mensaje or "") and _centro_envios_listo()
                and centro_estado["desde"] and (ultimo is None or centro_estado["desde"] > ultimo)):
            return True, "El Centro de Envíos ya está conectado: se buscan ahí los acuses del último mes.", True
        encontrados = []
        nuevo = False
        faltan = adjuntos_locales.actos_en_mensaje(caso.auto_mensaje)
        for tipo, numero, fecha in faltan:
            ruta, _nota = adjuntos_locales.buscar_en_descargas(_carpetas_descargas(), tipo, numero, fecha)
            if ruta is not None and not _es_acuse(ruta):
                encontrados.append(ruta.name)
                nuevo = True
        # 30-sep: acuses sueltos reconocidos por su CONTENIDO (Descargas o raiz de
        # adjuntos_manuales) de alguno de los actos que faltan, que el caso aun
        # no tiene en su carpeta (si ya se copio, ya se intento con el).
        if faltan:
            try:
                ya = {f.stat().st_size for f in carpeta.iterdir() if f.is_file()} if carpeta.is_dir() else set()
            except OSError:
                ya = set()
            sueltos = [(p, ac) for p, ac in _acuses_sueltos() if p.stat().st_size not in ya]
            n_sueltos_nuevos = len(sueltos)   # los de Descargas / raiz que el caso aun no tiene
            # 30-sep (2026-IE-036696): Andres dejo el acuse del Auto 2115 DIRECTO
            # en adjuntos_manuales\\<radicado> a los 5 s de empezar el intento;
            # el intento no lo vio y, como el archivo quedo "mas viejo" que el fin
            # del intento, nunca se reintento. Un acuse que ya esta en la carpeta
            # del caso y es de un acto que el mensaje sigue dando por faltante
            # tambien cuenta.
            if carpeta.is_dir():
                try:
                    en_carpeta = [f for f in carpeta.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                except OSError:
                    en_carpeta = []
                for f in en_carpeta:
                    ac = _acuse_de_pdf(f)
                    if ac is not None:
                        sueltos.append((f, ac))
            if sueltos:
                try:
                    idx = _get_cuadro_index()
                except Exception:
                    idx = None
                for tipo, numero, fecha in faltan:
                    actos = [types.SimpleNamespace(tipo_final=tipo, numero_final=numero, fecha_final=fecha,
                                                   email=a.email, nombre_titular_cuadro=a.nombre,
                                                   anexo=types.SimpleNamespace(nombre=""))
                             for a in (idx.buscar_por_numero(tipo, numero) if idx else []) if a.fecha == fecha]
                    actos = actos or [types.SimpleNamespace(tipo_final=tipo, numero_final=numero, fecha_final=fecha,
                                                            email="", nombre_titular_cuadro="",
                                                            anexo=types.SimpleNamespace(nombre=""))]
                    for k, (p, ac) in enumerate(sueltos):
                        if p.name not in encontrados and any(_acuse_es_del_acto(ac, a) for a in actos):
                            encontrados.append(p.name)
                            nuevo = nuevo or k < n_sueltos_nuevos
        if faltan:
            try:
                idx_c = _get_cuadro_index()
            except Exception:
                idx_c = None
            for tipo, numero, fecha in faltan:
                for a in (idx_c.buscar_por_numero(tipo, numero) if idx_c else []):
                    if a.fecha != fecha:
                        continue
                    falso = types.SimpleNamespace(tipo_final=tipo, numero_final=numero, fecha_final=fecha, email=a.email,
                                                  nombre_titular_cuadro=a.nombre, anexo=types.SimpleNamespace(nombre=""))
                    try:
                        pz = _piezas_contingencia(caso.radicado, falso)
                    except Exception:
                        pz = None
                    if pz:
                        encontrados.append(pz[0].name)
                        nuevo = nuevo or ultimo is None or any(p.stat().st_mtime > ultimo for p in pz)
                    break
        if encontrados:
            return True, f"Está en Descargas/adjuntos_manuales: {', '.join(encontrados[:3])}" + \
                (f" (y {len(encontrados) - 3} más)." if len(encontrados) > 3 else "."), nuevo
        return False, "", False

    def _reportes_actualizados_desde(iso: str | None) -> bool:
        if not iso:
            return False
        try:
            ultimo = datetime.fromisoformat(iso).timestamp()
        except ValueError:
            return False
        for ruta in (_ruta_reporte_envios(), _mas_nuevo(estado_mensajes_path_value["value"],
                                                        _archivo_mas_reciente("EstadoMensajes*.csv"))):
            try:
                if ruta and Path(ruta).stat().st_mtime > ultimo:
                    return True
            except OSError:
                pass
        return False

    def _cuadro_actualizado_desde(iso: str | None) -> bool:
        try:
            ultimo = datetime.fromisoformat(iso).timestamp() if iso else None
            ruta = _mas_nuevo(cuadro_path_value["value"], _archivo_mas_reciente("Cuadro_2026*.xlsx"))
            return bool(ultimo and ruta and Path(ruta).stat().st_mtime > ultimo)
        except (ValueError, OSError):
            return False

    def _categoria_automatizable(caso) -> bool:
        categoria = sgdea_automation.extraer_categoria_proceso(caso.columnas_crudas)
        return bool(categoria) and _normalizar_txt(categoria) in CATEGORIAS_AUTOMATIZABLES

    def _autorrevisar(activos: set) -> list:
        """Revision automatica de errores (backend/autorrevision.py): corre al
        empezar cada barrido. Devuelve lineas para el estado del barrido."""
        ctx = autorrevision.Contexto(
            hoy=datetime.now().date(), ahora=datetime.now(), version_app=APP_VERSION,
            adjunto_disponible=_adjunto_disponible, reportes_actualizados_desde=_reportes_actualizados_desde,
            categoria_automatizable=_categoria_automatizable,
            cuadro_actualizado_desde=_cuadro_actualizado_desde,
        )
        decisiones, reencolados = [], []
        for caso in dashboard.cargar_casos():
            if caso.radicado not in activos:
                continue
            # 1-oct (2026-IE-036987): el caso ya quedo en revision pero despues
            # aparecio (o cambio) su carpeta en Descargas con los PDF que faltaban:
            # se rehacen el cuadro y el adjunto del memorando (sin crear otro).
            if caso.auto_estado == "listo_revision" and caso.en_sgdea and not caso.archivado:
                cc = _carpeta_caso(caso.radicado)
                try:
                    ultimo = datetime.fromisoformat(caso.auto_ultimo_intento).timestamp() if caso.auto_ultimo_intento else 0
                except ValueError:
                    ultimo = 0
                if cc is not None and carpeta_caso.mas_nuevo(cc) > ultimo:
                    nota = (f"Apareció la carpeta del caso en Descargas ({cc.name}): se rehacen el cuadro y el adjunto "
                            "del memorando que está en revisión.")
                    dashboard.reabrir_para_rehacer(caso.radicado, nota, MARCA_REHACER)
                    reencolados.append(caso.radicado)
                    print(f"[autorrevision] {caso.radicado}: listo_revision -> rehacer -- {nota}", flush=True)
                    decisiones.append(autorrevision.Decision(caso.radicado, autorrevision.CLASE_ADJUNTO, "reencolar", nota,
                                                             fecha=datetime.now().isoformat(timespec="seconds")))
                continue
            d = autorrevision.revisar_caso(caso, ctx, dashboard.MAX_INTENTOS_AUTO)
            if d is None:
                continue
            d.fecha = datetime.now().isoformat(timespec="seconds")
            if d.accion == "reencolar" or d.nota != (caso.auto_revision_nota or ""):
                dashboard.aplicar_revision(caso.radicado, d.accion, d.nota)
            if d.accion == "reencolar":
                reencolados.append(caso.radicado)
            print(f"[autorrevision] {caso.radicado}: {d.clase} -> {d.accion} -- {d.nota}", flush=True)
            decisiones.append(d)
        autorrevision.guardar_historial(decisiones, RUTA_AUTORREVISION)
        if reencolados:
            return [f"Revisión automática: vuelven a la cola {', '.join(reencolados)}."]
        return []

    async def _barrido_automatico():
        """UNA vuelta del barrido (la logica vive en backend/barrido.py; aqui
        solo se le conectan SGDEA, el candado y la interfaz)."""
        if _get_cuadro_index() is None:
            _estado_barrido("Barrido en pausa: falta configurar el Cuadro_2026.", theme.WARNING)
            return

        async def _listar():
            await sgdea_client.mantener_viva()
            return await sgdea_automation.listar_casos_gestionar(sgdea_client.pagina)

        def _actualizar_vistas():
            # Si el Dashboard/Memorandos no estan en pantalla, .update() falla;
            # los datos ya quedaron guardados y se ven al abrir la pestaña.
            for refrescar in (_refrescar_dashboard, _refrescar_memorandos):
                try:
                    refrescar()
                except RuntimeError:
                    pass

        resumen = await barrido.ejecutar_barrido(
            listar_bandeja=_listar,
            procesar_caso=_procesar_caso_automatico,
            tomar_candado=_tomar_candado,
            soltar_candado=_soltar_candado,
            puede_seguir=lambda: bool(sgdea_auto_switch.value) and sgdea_client is not None and sgdea_client.conectado,
            informar=lambda t: _estado_barrido(f"Barrido {datetime.now():%H:%M} -- {t}"),
            al_actualizar=_actualizar_vistas,
            autorrevisar=_autorrevisar,
        )
        if not resumen.detenido:
            _estado_barrido(
                f"Último barrido {datetime.now():%H:%M}: {resumen.listos} listo(s) para tu revisión, "
                f"{resumen.reintentar} a reintentar, {resumen.manuales} requieren revisión manual "
                f"({resumen.en_bandeja} en la bandeja).",
                theme.SUCCESS if resumen.listos else theme.TEXT_SECONDARY,
            )

    async def _ciclo_automatico_sgdea():
        """Ciclo en segundo plano: arranca solo al abrir Insignia y, mientras
        la gestion automatica este activa y la sesion propia de SGDEA
        conectada, hace un barrido de TODOS los casos cada
        SGDEA_AUTO_INTERVALO_SEG (contados desde que termina el anterior)."""
        if sgdea_auto_task["corriendo"]:
            return
        sgdea_auto_task["corriendo"] = True
        despertar = sgdea_auto_task["despertar"]
        try:
            # Primer barrido apenas la sesion propia de SGDEA queda conectada
            # (antes: 90 s fijos aunque ya estuviera lista).
            loop = asyncio.get_running_loop()
            limite = loop.time() + BARRIDO_ESPERA_SESION_SEG
            while (sgdea_client is None or not sgdea_client.conectado) and loop.time() < limite and not despertar.is_set():
                await asyncio.sleep(3)
            while True:
                despertar.clear()
                _revisar_correcciones_pendientes()
                forzado = sgdea_auto_task["forzar"]
                sgdea_auto_task["forzar"] = False
                if not (sgdea_auto_switch.value or forzado):
                    pass
                elif sgdea_client is None or not sgdea_client.conectado:
                    _estado_barrido("Gestión automática activa, esperando la sesión propia de SGDEA (Configuración).", theme.WARNING)
                else:
                    sgdea_auto_task["en_barrido"] = True
                    try:
                        await _barrido_automatico()
                    except Exception as exc:  # nunca dejar que el ciclo se muera
                        _estado_barrido(f"Error en el barrido: {type(exc).__name__}: {exc}", theme.ERROR)
                    finally:
                        sgdea_auto_task["en_barrido"] = False
                        _habilitar_boton_sincronizar()
                # Espera el intervalo, o menos si 'Sincronizar con SGDEA' lo despierta.
                # Pedido de Andres (29-sep): si hay casos por reintentar tras una
                # falla pasajera, la proxima vuelta es en 4 min, no en 10.
                espera = SGDEA_AUTO_INTERVALO_SEG
                try:
                    if any(c.en_sgdea and not c.archivado and (
                               c.auto_estado == "reintentar"
                               or (c.auto_estado == "requiere_manual"
                                   and autorrevision.clasificar(c.auto_mensaje) == autorrevision.CLASE_SGDEA
                                   and (c.auto_revisiones or 0) < autorrevision.MAX_REINTENTOS_SGDEA))
                           for c in dashboard.cargar_casos()):
                        espera = SGDEA_REINTENTO_RAPIDO_SEG
                        _estado_barrido(f"Hay casos por reintentar: próxima vuelta en {espera // 60} min.")
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(despertar.wait(), timeout=espera)
                except asyncio.TimeoutError:
                    pass
        finally:
            sgdea_auto_task["corriendo"] = False

    async def _autoconectar_cuentas():
        """Al abrir Insignia conecta solas las cuentas guardadas con
        'Recordar en este equipo' (portal nuevo, portal antiguo y sesion
        propia de SGDEA), para que el barrido arranque sin clics."""
        await asyncio.sleep(3)

        async def _intentar(nombre, funcion):
            print(f"[autoconexion] {nombre}...", flush=True)
            try:
                await funcion()
                print(f"[autoconexion] {nombre}: terminado.", flush=True)
            except Exception as exc:  # una cuenta nunca impide conectar las otras
                print(f"[autoconexion] {nombre}: ERROR ({type(exc).__name__}): {exc}", flush=True)

        # SGDEA primero: es la que necesita el barrido.
        if config_state.get("sgdea_remember") and sgdea_usuario_field.value and sgdea_password_field.value and (sgdea_client is None or not sgdea_client.conectado):
            await _intentar("sesion propia de SGDEA", do_login_sgdea)
        if config_state.get("remember") and email_field.value and password_field.value and client is None:
            await _intentar("portal nuevo 4-72", do_login)
        if config_state.get("legacy_remember") and legacy_email_field.value and legacy_password_field.value and legacy_client is None:
            await _intentar("portal antiguo 4-72", do_login_legacy)

    def _habilitar_boton_sincronizar():
        try:
            dashboard_sync_button.disabled = False
            dashboard_sync_button.update()
        except Exception:
            pass

    async def _sincronizar_dashboard(e):
        # Con la sesion propia de SGDEA: barrido COMPLETO ya mismo (lee toda
        # la bandeja y gestiona los casos pendientes, sin pulsar 'Gestionar'
        # caso por caso). Sin ella: solo lectura por Chrome (ruta antigua).
        if sgdea_client is not None and sgdea_client.conectado:
            if sgdea_auto_task["en_barrido"]:
                page.show_dialog(ft.SnackBar(content=ft.Text("Ya hay un barrido en curso -- mira su avance aquí abajo."), bgcolor=theme.WARNING))
                return
            sgdea_auto_task["forzar"] = True
            sgdea_auto_task["despertar"].set()
            if not sgdea_auto_task["corriendo"]:
                page.run_task(_ciclo_automatico_sgdea)
            dashboard_sync_button.disabled = True
            _actualizar_seguro(dashboard_sync_button)
            _estado_barrido("Barrido solicitado: leyendo TODA la bandeja 'Gestionar' y gestionando los casos pendientes...")
            return
        if automatizacion_sgdea["activa"]:
            page.show_dialog(ft.SnackBar(content=ft.Text(_sgdea_ocupado_msg()), bgcolor=theme.WARNING))
            return
        automatizacion_sgdea["activa"] = True
        automatizacion_sgdea["quien"] = "Sincronizar con SGDEA"
        dashboard_sync_button.disabled = True
        dashboard_sync_status.value = "Conectando a SGDEA..."
        dashboard_sync_status.color = theme.TEXT_MUTED
        dashboard_sync_button.update()
        dashboard_sync_status.update()
        try:
            nuevos = await _detectar_y_registrar_casos_nuevos()
            if nuevos:
                dashboard_sync_status.value = f"{len(nuevos)} caso(s) nuevo(s) agregado(s) al Dashboard."
                dashboard_sync_status.color = theme.SUCCESS
            else:
                dashboard_sync_status.value = "Sincronizado: no hay casos nuevos."
                dashboard_sync_status.color = theme.TEXT_SECONDARY
        except sgdea_automation.AutomatizacionError as exc:
            dashboard_sync_status.value = str(exc)
            dashboard_sync_status.color = theme.ERROR
        except Exception as exc:
            dashboard_sync_status.value = f"Error inesperado: {exc}"
            dashboard_sync_status.color = theme.ERROR
        finally:
            automatizacion_sgdea["activa"] = False
            automatizacion_sgdea["quien"] = ""
            dashboard_sync_button.disabled = False
            dashboard_sync_button.update()
            dashboard_sync_status.update()
        _refrescar_dashboard()

    dashboard_sync_button = ft.FilledButton(
        content=ft.Row([ft.Icon(ft.Icons.SYNC, size=16), ft.Text("Sincronizar con SGDEA")], spacing=6, tight=True),
        on_click=lambda e: page.run_task(_sincronizar_dashboard, e),
        style=ft.ButtonStyle(bgcolor={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, color={ft.ControlState.DEFAULT: "#001018"}, shape=ft.RoundedRectangleBorder(radius=10)),
    )

    dashboard_panel = theme.glass_card(
        ft.Column(
            [
                ft.Row(
                    [
                        theme.section_title("Dashboard", ft.Icons.SPACE_DASHBOARD),
                        ft.Row(
                            [
                                ft.OutlinedButton(
                                    content=ft.Row([ft.Icon(ft.Icons.REFRESH, size=16), ft.Text("Refrescar")], spacing=6, tight=True),
                                    on_click=lambda e: _refrescar_dashboard(),
                                    style=ft.ButtonStyle(color={ft.ControlState.DEFAULT: theme.ACCENT_CYAN}, side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.GLASS_BORDER)}, shape=ft.RoundedRectangleBorder(radius=10)),
                                ),
                                dashboard_sync_button,
                            ],
                            spacing=8,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Text(
                    "'Sincronizar con SGDEA' lee TODA la bandeja 'Gestionar' (todas las páginas) y "
                    "gestiona de una vez los casos pendientes: los deja en Memorandos, PARA APROBAR, "
                    "para tu revisión (nunca envía a aprobación). Lo mismo corre solo cada 10 minutos. "
                    "Necesita la sesión propia de SGDEA conectada (Configuración).",
                    size=11,
                    color=theme.TEXT_MUTED,
                ),
                dashboard_sync_status,
                aviso_correcciones_text,
                ft.Container(height=6),
                dashboard_tiles_row,
                ft.Container(height=10),
                ft.Container(
                    content=autorrevision_view,
                    padding=ft.Padding(14, 10, 14, 10),
                    bgcolor=ft.Colors.with_opacity(0.035, "#FFFFFF"),
                    border=ft.Border.all(1, theme.GLASS_BORDER),
                    border_radius=12,
                ),
                ft.Container(height=10),
                dashboard_list_view,
            ],
            spacing=10,
        ),
    )
    _refrescar_dashboard(update=False)

    dashboard_view = ft.Column(
        [theme.brand_hero(page), ft.Container(height=16), dashboard_panel],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    # ------------------------------------------------------------------
    # Navegacion
    # ------------------------------------------------------------------
    content_area = ft.Container(content=dashboard_view, expand=True, animate_opacity=200)
    nav_state = {"selected": "dashboard"}
    nav_row = ft.Row([], spacing=8)

    def build_nav(update: bool = False):
        items = [
            ("dashboard", "Dashboard", ft.Icons.SPACE_DASHBOARD),
            ("individual", "Individual", ft.Icons.SEARCH),
            ("masivo", "Masivo", ft.Icons.DYNAMIC_FEED),
            ("masivo_legacy", "Masivo (Portal Antiguo)", ft.Icons.HISTORY),
            ("zip_local", "Acuses Manuales", ft.Icons.FOLDER_ZIP),
            ("memorandos", "Memorandos", ft.Icons.FACT_CHECK),
            ("config", "Configuración", ft.Icons.SETTINGS),
        ]
        nav_row.controls = [
            theme.nav_button(label, icon, nav_state["selected"] == key, lambda e, k=key: select_tab(k))
            for key, label, icon in items
        ]
        if update:
            nav_row.update()

    def select_tab(key: str):
        nav_state["selected"] = key
        content_area.content = {
            "dashboard": dashboard_view,
            "individual": individual_view,
            "masivo": masivo_panel,
            "masivo_legacy": masivo_legacy_panel,
            "zip_local": ziploc_panel,
            "memorandos": memorandos_panel,
            "config": config_panel,
        }[key]
        if key == "memorandos":
            _refrescar_memorandos(update=False)
        elif key == "dashboard":
            _refrescar_dashboard(update=False)
        build_nav(update=True)
        content_area.update()

    build_nav()

    header = ft.Container(
        content=ft.Row(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Image(src="logo_insignia.png", width=28, height=42, fit=ft.BoxFit.CONTAIN),
                                ft.Text(
                                    "A G",
                                    size=8,
                                    weight=ft.FontWeight.W_600,
                                    color=theme.ACCENT_GOLD,
                                ),
                            ],
                            spacing=2,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Column(
                            [
                                theme.neon_gradient_text("INSIGNIA", size=20),
                                ft.Text("Ministerio de Educación Nacional · Subdirección de Relacionamiento con la Ciudadanía", size=10, color=theme.TEXT_MUTED),
                                ft.Text(f"v{APP_VERSION}", size=9, color=theme.TEXT_MUTED),
                            ],
                            spacing=0,
                        ),
                    ],
                    spacing=10,
                ),
                conn_status,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        padding=ft.Padding(24, 18, 24, 18),
    )

    body = ft.Container(
        content=ft.Column(
            [nav_row, ft.Container(height=14), content_area],
            expand=True,
        ),
        padding=ft.Padding(24, 0, 24, 24),
        expand=True,
    )

    foreground = ft.Container(
        content=ft.Column([header, body], expand=True),
        expand=True,
        gradient=ft.RadialGradient(
            center=ft.Alignment.TOP_RIGHT,
            radius=1.4,
            colors=[ft.Colors.with_opacity(0.08, theme.ACCENT_VIOLET), ft.Colors.with_opacity(0, theme.ACCENT_VIOLET)],
        ),
    )

    animated_bg = theme_bg.AnimatedBackground(page, page.window.width, page.window.height)

    ceo_label = ft.Container(
        content=ft.Row(
            [
                ft.Container(width=6, height=6, bgcolor=theme.ACCENT_GOLD, border_radius=3),
                ft.Text(
                    "CEO — JEISON ANDRÉS GÓMEZ NOVA",
                    size=10.5,
                    weight=ft.FontWeight.W_600,
                    color=ft.Colors.with_opacity(0.55, theme.ACCENT_GOLD),
                    font_family=theme.FONT_FAMILY,
                ),
            ],
            spacing=6,
            tight=True,
        ),
        right=18,
        bottom=14,
        padding=ft.Padding(10, 6, 12, 6),
        bgcolor=ft.Colors.with_opacity(0.06, "#FFFFFF"),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.25, theme.ACCENT_GOLD)),
        border_radius=20,
    )

    root = ft.Stack([animated_bg.stack, foreground, ceo_label], expand=True)
    page.add(root)

    def _on_page_resize(e):
        animated_bg.on_page_resize(e)

    page.on_resize = _on_page_resize
    page.run_task(animated_bg.start)

    # Ciclo automatico de gestion de SGDEA (ver Configuración -> "Sesión
    # propia de SGDEA"): se lanza SIEMPRE al abrir la app, pero de entrada
    # no hace nada -- solo actua si sgdea_auto_switch esta activo Y la
    # sesion propia de SGDEA esta conectada (ambas cosas las decide
    # Andres). Nunca envia nada a aprobacion por su cuenta.
    # v1.4.3: el paso 2 (destinatario) se corrigio con el video del 28-sep;
    # los casos que se detuvieron por ese error vuelven solos a la cola.
    try:
        # Solo mensajes que el codigo nuevo YA NO produce (asi no se reinician
        # en cada arranque).
        reiniciados = dashboard.reiniciar_por_mensaje((
            "dio 0 coincidencias", "no aparecio su tarjeta (campo 'Nivel 1')",
        ))
        if reiniciados:
            print(f"[barrido] casos devueltos a la cola tras la correccion del paso 2: {reiniciados}", flush=True)
        # v1.5.0 (una sola vez): lectura de la peticion y desplegables corregidos.
        if not config_state.get("reinicio_v1_5_10"):
            # 29-sep-2026: la firma que cierra con "se suscribe" (sin 'Cordialmente')
            # ya se lee (2026-IE-036741, log 15:36/15:48 "firma None"). Esos casos
            # estaban como "decisión" y no se reintentaban solos: vuelven una vez.
            reiniciados = dashboard.reiniciar_por_mensaje(("No se pudo leer quién firma la petición",))
            config_state["reinicio_v1_5_10"] = True
            save_config(config_state)
            if reiniciados:
                print(f"[barrido] v1.5.10: casos devueltos a la cola: {reiniciados}", flush=True)
        if not config_state.get("reinicio_v1_5_8"):
            # Casos que quedaron en revision con un ACUSE crudo como adjunto (antes de
            # que Insignia armara el expediente con los acuses manuales; 2026-IE-036231):
            # vuelven a la cola; el intento comprueba el documento, arma el expediente
            # y lo sube (los demas pasos ya hechos no se repiten).
            reparar = []
            for cp in casos_pendientes.cargar_casos():
                ruta_adj = Path(cp.adjunto_path) if getattr(cp, "adjunto_path", "") else None
                if cp.estado != "pendiente" or ruta_adj is None or ruta_adj.suffix.lower() != ".pdf" or not ruta_adj.is_file():
                    continue
                try:
                    extract_acuse_from_pdf(ruta_adj.read_bytes(), ruta_adj.name)
                except Exception:
                    continue  # no es un acuse crudo: esta bien
                reparar.append(cp.radicado)
            for rad in reparar:
                try:
                    dashboard._actualizar(rad, estado_gestion="en_gestion", auto_estado="", auto_intentos=0,
                                          auto_revision_nota="Se subió el acuse sin armar el expediente: se arma y se sube el expediente.")
                except dashboard.DashboardError:
                    pass
            config_state["reinicio_v1_5_8"] = True
            save_config(config_state)
            if reparar:
                print(f"[barrido] v1.5.8: casos con acuse crudo como adjunto, vuelven a la cola: {reparar}", flush=True)
        if not config_state.get("reinicio_v1_5_5"):
            # Pruebas de entrega (2026-IE-036323) ya tienen plantilla masiva.
            reiniciados = dashboard.reiniciar_por_mensaje((
                "SOLICITUD DE PRUEBAS DE ENTREGA DOCUMENTOS EXTERNOS ENVIADOS' sin plantilla",
            ))
            config_state["reinicio_v1_5_5"] = True
            save_config(config_state)
            if reiniciados:
                print(f"[barrido] v1.5.5: casos devueltos a la cola: {reiniciados}", flush=True)
        if not config_state.get("reinicio_v1_5_4"):
            reiniciados = dashboard.reiniciar_por_mensaje((
                "no se llego a la vista 'Ver documentos'", "sweet-overlay", "'Nivel 1'",
            ))
            config_state["reinicio_v1_5_4"] = True
            save_config(config_state)
            if reiniciados:
                print(f"[barrido] v1.5.4: casos devueltos a la cola: {reiniciados}", flush=True)
        if not config_state.get("reinicio_v1_5_3"):
            reiniciados = dashboard.reiniciar_por_mensaje((
                "Timeout 30000ms exceeded", "no aparecio el modal 'Este documento finaliza",
            ))
            config_state["reinicio_v1_5_3"] = True
            save_config(config_state)
            if reiniciados:
                print(f"[barrido] v1.5.3: casos devueltos a la cola: {reiniciados}", flush=True)
        if not config_state.get("reinicio_v1_5_2"):
            reiniciados = dashboard.reiniciar_por_mensaje((
                "Título/Profesión", "No se encontro como abrir el desplegable", "Se abrio el desplegable",
                "TargetClosedError",
            ))
            config_state["reinicio_v1_5_2"] = True
            save_config(config_state)
            if reiniciados:
                print(f"[barrido] v1.5.2: casos devueltos a la cola: {reiniciados}", flush=True)
        if not config_state.get("reinicio_v1_5_1"):
            reiniciados = dashboard.reiniciar_por_mensaje((
                "No se pudo preparar el adjunto", "no aparece en EstadoMensajes", "Adjunto pendiente",
                "No se pudo inferir Doctor/Doctora para", "Se abrio el desplegable", "coincidencias para",
                "No se pudo armar la carta", "Actos que no se pudieron identificar",
            ))
            config_state["reinicio_v1_5_1"] = True
            config_state["reinicio_v1_5_0"] = True
            save_config(config_state)
            if reiniciados:
                print(f"[barrido] v1.5.1: casos devueltos a la cola: {reiniciados}", flush=True)
        if not config_state.get("reinicio_v1_5_0"):
            reiniciados = dashboard.reiniciar_por_mensaje((
                "No se pudo inferir Doctor/Doctora para", "Se abrio el desplegable", "coincidencias para",
                "No se pudo armar la carta", "no se encontro la opcion",
            ))
            config_state["reinicio_v1_5_0"] = True
            save_config(config_state)
            if reiniciados:
                print(f"[barrido] v1.5.0: casos devueltos a la cola: {reiniciados}", flush=True)
    except Exception as exc:
        print(f"[barrido] no se pudieron reiniciar casos: {exc}", flush=True)
    page.run_task(_autoconectar_cuentas)
    page.run_task(_ciclo_automatico_sgdea)


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")

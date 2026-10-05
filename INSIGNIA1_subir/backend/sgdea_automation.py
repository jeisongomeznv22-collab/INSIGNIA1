"""
Automatizacion (Playwright) del llenado del Memorando respuesta en
SGDEA/TMS, a partir del cuerpo/tabla que ya arma backend/sgdea_carta.py.

Disciplina de seguridad (igual que en toda prueba manual hecha en este
proyecto, ver README del diseño):

  - Este modulo NUNCA inicia sesion ni escribe una contraseña. Se conecta,
    via Playwright `connect_over_cdp`, a un Chrome que ANDRES ya abrio y en
    el que YA inicio sesion el mismo (con Chrome arrancado en modo
    depuracion remota, ver `conectar_chrome_existente`). Si no hay una
    sesion ya autenticada, esto simplemente no funciona -- por diseño, no
    intenta arreglarlo solo.
  - Nunca resuelve ni intenta saltarse un CAPTCHA.
  - Nunca pulsa "Guardar", "Generar PDF" ni "Solicitar aprobación" por su
    cuenta. Deja el editor listo, con el cuerpo pegado y los campos
    diligenciados, para que Andres lo revise y sea EL quien decida cuando
    guardar/generar/enviar. `ResultadoAutomatizacion.pendiente_revision_humana`
    es siempre True.

Que esta CONFIRMADO (verificado a mano contra un caso real en SGDEA --
2026-IE-035342 -- con Ctrl+Z para revertir cada prueba, incluida una
segunda ronda de verificacion visual porque la primera ronda de pruebas dio
un resultado ambiguo/erroneo, ver mas abajo "Error de verificacion..."):

  - El editor del cuerpo del memorando es un canvas DevExpress ASPxRichEdit
    -- NO acepta escritura de teclado sintetica ni edicion via DOM.
    Unicamente responde a un evento de paste real (Ctrl+V) con contenido
    puesto de verdad en el portapapeles del sistema operativo.
  - Estructura: esta anidado dentro de DOS iframes del mismo origen: el
    iframe externo '#frameVerDocumentos' (su src trae
    'idTipoDocumento=439', el id exacto de "Memorando respuesta") y, dentro
    de ese, el iframe target nativo de pegado de DevExpress. OJO: ese
    iframe interno tiene el atributo `id` VACIO -- solo se puede localizar
    por su CLASE: `iframe.dxreInputTarget` (un selector por
    `iframe[id*='dxreInputTarget']`, como se penso en un primer momento,
    NUNCA lo encuentra).
  - El ribbon "Archivo" del editor tiene exactamente 4 botones: Guardar,
    Generar PDF, Propiedades, Solicitar aprobación.
  - "Propiedades" solo trae metadatos genericos del documento (Título,
    Descripción, Palabras clave) -- NO es donde estan destinatario/asunto.
  - CORRECCION IMPORTANTE (sesion 2026-09-23, video de Andres sobre el
    caso real 2026-IE-035458): el bloque de destinatario y la linea de
    "Asunto:" NUNCA se pegan como texto libre en un parrafo del cuerpo --
    eso fue un error de una version anterior de este modulo/documento.
    Asi es como lo hace de verdad el revisor (la Dra. Ema): existe una
    columna de iconos a la izquierda del documento, DENTRO de
    #frameVerDocumentos ("Destinatario Tipificación", "Asunto",
    "Firmante", "Copia Interna", "Anexo", "Radicación Relacionada" --
    misma familia que el icono "Revisores ciclo adHoc" que ya usa
    seleccionar_revisor_ema() mas abajo, mismo tipo de modal generico
    #TMSDialogModalDialog). El flujo real, confirmado visualmente en el
    video:
      1. Click en el icono "Destinatario Tipificación" -> se abre un
         modal con un campo "Buscar destinatario" (busqueda en vivo
         contra el directorio de SGDEA); al elegir un resultado de la
         grilla aparece una tarjeta "Destinatarios seleccionados" con
         Título/Profesión, Destinatario y Dependencia YA rellenados por
         SGDEA (vienen del directorio, no se escriben a mano), mas dos
         desplegables que si hay que elegir: "Tipo" (ej. "Memorando") y
         "Nivel 1" (la categoria del tramite, ej. "SOLICITUDES INTERNAS
         GENERALES"). Al pulsar el "Guardar" de ESE modal, SGDEA
         autocompleta POR SU CUENTA, dentro del cuerpo del documento,
         tanto el bloque "Para: <tratamiento> <nombre> / <cargo> /
         <subdireccion>" como la linea "Eje temático: <categoria>" --
         ver seleccionar_destinatario_tipificacion() mas abajo.
      2. Click en el icono "Asunto" -> se abre un modal mas simple con un
         <textarea> (limite confirmado en vivo: 200 caracteres) y su
         propio "Guardar"; al guardar, SGDEA autocompleta la linea
         "Asunto:" del cuerpo -- ver establecer_asunto() mas abajo.
    Lo que SIGUE siendo cierto (esto si se sigue pegando como texto libre
    en un parrafo-plantilla del cuerpo, porque NO existe un icono/modal
    para esto en la columna de la izquierda -- se confirmo revisando esa
    columna completa en el video):
      - La misma linea de "Saludo," (se pega/escribe A CONTINUACION de la
        coma, en la misma linea/parrafo).
      - El parrafo EN BLANCO entre "Saludo," y "Cordialmente," -- aqui va
        el cuerpo/parrafo de la respuesta (o la tabla, si es masiva).
    Cada uno de estos DOS se probo por separado pegando un texto de
    prueba distintivo, confirmando visualmente que aparecio en el lugar
    correcto, y deshaciendo con Ctrl+Z antes de seguir.
  - HALLAZGO CRITICO sobre donde hacer click: un click SOLO deja el cursor
    realmente ubicado (y por lo tanto el pegado SOLO llega a buen puerto)
    si cae DENTRO del area de una linea/parrafo real del flujo de texto del
    documento -- así el parrafo este vacio, como el caso del destinatario o
    el cuerpo. Un click en el margen/padding en blanco FUERA de todo el
    flujo del documento (por ejemplo, muy por debajo de la ultima linea de
    contenido, en el area gris/blanca de relleno del panel) deja el foco en
    el DIV contenedor del editor (`dxrControl`), NO en el iframe de pegado
    (`dxreInputTarget") -- y en ese caso el Ctrl+V NO FALLA CON ERROR, pero
    tampoco pega nada en ningun lado: queda en silencio. Esto fue la causa
    real de una ronda entera de pruebas fallidas en la sesion anterior (se
    interpreto, erroneamente al principio, como que el pegado no funcionaba
    en absoluto). CONSECUENCIA PRACTICA: la automatizacion real debe hacer
    click sobre una coordenada que caiga sobre texto/linea visible conocida
    (p. ej. literalmente sobre las letras de "Asunto:"), nunca sobre una
    coordenada "generica" del cuerpo del documento.
  - Se puede verificar, ANTES de pegar, si el click realmente ubico el
    cursor en el lugar correcto revisando cual elemento quedo con foco dentro
    del documento del iframe externo -- si es
    `iframe.dxreInputTarget` el click sirvio; si es el DIV `dxrControl` (u
    otro), el click cayo fuera del flujo de texto y hay que reintentar en
    otra coordenada.
  - Orden critico al escribir en el portapapeles: `navigator.clipboard
    .writeText` debe llamarse ANTES de mover el foco hacia el iframe
    interno (o inmediatamente despues de un click que ya lo dejo enfocado),
    nunca despues de forzar foco manualmente con `.focus()` sobre el
    iframe interno vía JS -- forzar ese foco por separado le quita el foco
    al documento de nivel superior y la propia llamada
    `navigator.clipboard.writeText` falla con
    `NotAllowedError: Document is not focused`. El patron seguro y
    confirmado es: click (real, de mouse, sobre la linea correcta) ->
    escribir portapapeles -> Ctrl+V, sin ningun `.focus()` manual de por
    medio.
  - Ctrl+Z para deshacer NO siempre revierte la prueba completa con una
    sola pulsacion -- a veces hacen falta 2. Y una rafaga de Ctrl+Z de mas
    (se probo con 6 seguidos cuando bastaba con 1) puede hacer que el editor
    tire un dialogo de error: "Un error no especificado ocurrió y el editor
    necesita ser recargada. Los últimos cambios se puede perder." (con un
    boton "Aceptar"). No se perdio nada porque nunca se habia pulsado
    Guardar, pero por las dudas: deshacer de a 1-2 pulsaciones, verificando
    visualmente entre cada una, en vez de mandar una rafaga fija.
  - Sincroniza los cambios con el servidor via llamadas POST a
    'DXS.ashx' en teoria (protocolo propio de sincronizacion de documentos
    de DevExpress) pero esto NO se pudo confirmar de forma consistente via
    `read_network_requests` en esta sesion (aparecio vacio incluso sin
    filtro) -- no depender de este mecanismo para verificar un pegado,
    usar en cambio verificacion visual (screenshot) o el chequeo de
    `activeElement` de mas arriba.
  - Un documento "Memorando respuesta" recien creado por "Crear documento"
    aparentemente SI queda registrado/persistido en la lista "Ver
    documentos" del caso (aparece como borrador en blanco) AUNQUE nunca se
    haya pulsado el boton "Guardar" del ribbon -- ese borrador puede
    quedarse ahi sin problema (Andres confirmo que si el caso de todos
    modos hay que responderlo, no hace falta borrar el borrador de prueba,
    simplemente se sigue llenando cuando se responda de verdad).

Error de verificacion a evitar (aprendido de la manera dificil): revisar
si un pegado/tecleo llego a buen puerto leyendo `innerText`/`innerHTML`
del documento del editor NO SIRVE -- el contenido vivo del RichEdit no se
refleja ahi (es esencialmente un canvas). Ni siquiera una tecla literal
tecleada de verdad aparecio en `innerText` en una prueba de control. La
UNICA verificacion confiable que se encontro es la visual: tomar un
screenshot de la zona exacta (hace falta hacer scroll hasta ahi primero) y
mirarlo, o pedirle a Andres que mire directamente su pantalla.

Que TODAVIA NO esta confirmado / sigue pendiente:
  - Coordenadas de click ESTABLES y reutilizables por Playwright SOLO para
    saludo/cuerpo (destinatario y asunto ya NO necesitan coordenada -- ver
    la correccion arriba, van por modal/icono, ubicables por
    data-original-title como cualquier otro elemento normal del DOM):
    como el editor es un canvas, Playwright NO puede ubicar "Saludo," por
    texto (no es texto accesible del DOM) -- solo por coordenadas de
    pantalla, que dependen del zoom/tamaño de ventana y de cuanto haya
    que hacer scroll. Falta disenar una estrategia robusta (por ejemplo:
    fijar SIEMPRE el mismo tamaño de ventana/zoom antes de automatizar,
    hacer Ctrl+Home para ir al inicio del documento, y usar offsets Y
    fijos medidos una sola vez en esa configuracion -- o algun mecanismo
    de reconocimiento visual). No se inventa un numero de pixeles fijo
    aqui sin haber fijado antes esa configuracion base.
  - Los selectores exactos de los desplegables "Tipo" y "Nivel 1" dentro
    del modal "Destinatario Tipificación", y del <textarea> dentro del
    modal "Asunto" -- ver las advertencias en los docstrings de
    seleccionar_destinatario_tipificacion() y establecer_asunto() mas
    abajo; su primera corrida real debe hacerse con Andres mirando la
    pantalla de Chrome.
  - Los campos por FUERA del cuerpo del documento (tipo de documento,
    revisora + mensaje de "Solicitar aprobación", numero de adjuntos):
    "revisora + mensaje" es parte del flujo de "Solicitar aprobación", que
    esta deliberadamente sin explorar (ver disciplina de seguridad arriba).
    "Anexos al documento" SI se confirmo en la sesion anterior: es un
    input de archivo HTML estandar (botón "Seleccionar archivos..."), sin
    trucos de portapapeles, automatizable con `set_input_files` de
    Playwright cuando llegue el momento.

Actualizacion (sesion 2026-09-22, caso real 2026-IE-035142, sin CAPTCHA ni
credenciales de por medio en ningun momento) -- CONFIRMADO EN VIVO:

  - Navegacion al caso por radicado: cada fila de la lista "Gestionar"
    trae un checkbox con id `chkSol{radicado}-1` (ej.
    `chkSol2026-IE-035142-1`) y, dentro de esa misma fila `<tr>`, un
    `button.gestion` que abre el caso -- si el documento ya existe para
    ese caso, este click lleva DIRECTO a "Ver documentos" (no hace falta
    pasar por "Crear documento" de nuevo). El cuadro de busqueda de esa
    lista es `input.form-control.form-control-sm` (sin id/name propios).
    El bloque "Gestionar" del dashboard de "Inicio" (donut + barra con el
    conteo de Memorandos) es un <canvas>, SIN texto accesible por DOM --
    Playwright no puede ubicarlo por texto, solo por click de coordenada
    fija (misma limitacion que el editor: depende de un tamaño de ventana
    conocido).
  - El icono "Revisores ciclo adHoc" (el check azul en la columna de
    iconos a la izquierda del documento, junto a "Destinatario
    Tipificación", "Asunto", "Firmante", "Copia Interna", "Anexo",
    "Radicación Relacionada") vive DENTRO de #frameVerDocumentos, y el
    dialogo que abre TAMBIEN (no es un dialogo de nivel superior aunque
    visualmente cubra toda la pantalla) -- ese dialogo usa un contenedor
    generico y reutilizable, `#TMSDialogModalDialog` (con
    `h4#TMSDialogModalTitulo` como titulo), que muy probablemente
    tambien es el que usan OTROS dialogos de TMS (incluido, con alta
    probabilidad pero SIN CONFIRMAR, el de "Solicitar aprobación" /
    "Inicio ciclo de aprobación" -- ver advertencia en
    `enviar_a_aprobacion()` mas abajo). El campo "Buscar revisor" filtra
    la grilla en vivo, pero SOLO si el evento de teclado incluye una
    tecla real despues de escribir (se confirmo que escribir todo el
    texto de una sola vez, via `fill()`/paste sintetico, puede dejar la
    grilla sin filtrar -- conviene escribir y luego un caracter adicional
    de verdad, o usar `press_sequentially`, para forzar el evento).
    Una vez seleccionado un revisor de la grilla, aparece bajo "Revisores
    seleccionados"; el boton "Guardar" de ESE dialogo (scoped dentro de
    `#TMSDialogModalDialog`, texto visible "Guardar", SIN
    data-original-title propio -- no confundir con el "Guardar" del
    ribbon del documento, que si tiene data-original-title="Guardar" y
    esta prohibido) persiste la asignacion; al reabrir el dialogo despues
    el revisor sigue ahi, confirmando que quedo guardado. Tras guardar,
    el boton del ribbon que antes decia "Solicitar aprobación" pasa a
    decir "Inicio ciclo de aprobación" (MISMO boton, cambia el texto
    visible; no se confirmo si su atributo data-original-title tambien
    cambia -- por eso `enviar_a_aprobacion` prueba ambos textos).
  - "Adjuntar archivo" del toolbar superior del caso (fuera de
    #frameVerDocumentos) sube el archivo al "Expediente" del caso
    (visible mas abajo en la pagina, con Autor/fecha/tipo de documento);
    la seccion "Anexos al documento" (visible al hacer scroll debajo del
    editor, DENTRO del flujo normal de "Ver documentos", fuera del
    iframe) es la que efectivamente se envia con la comunicacion --
    ambas son inputs de archivo HTML estandar con un link de texto
    "Subir archivo"/"Subir todos" para confirmar la carga; conviene subir
    el adjunto en LAS DOS.

Informacion adicional de Andres (sesion 2026-09-22) -- DESCRITA POR EL,
TODAVIA SIN VERIFICAR EN VIVO por este modulo (a diferencia de todo lo de
arriba, que si se confirmo contra el DOM real):

  - En el ribbon del editor del documento hay un boton "Distribución de
    página"; al entrar ahi aparece otro boton "Tamaño" que despliega una
    lista de tamaños de papel. Andres SIEMPRE elige "Legal" ahi, porque
    es el tamaño que mas probablemente deja todo el contenido del
    memorando en una sola pagina. El motivo practico: con un tamaño mas
    chico, el bloque de firma de la Dra. Diana puede terminar solo, sin
    nada mas de contenido, en una pagina aparte al final del documento --
    algo que se quiere evitar. Ver `configurar_tamano_legal()` mas abajo
    -- escrita defensivamente (igual que `enviar_a_aprobacion`) porque
    todavia no se inspecciono este ribbon en vivo; su primera corrida
    real debe hacerse con Andres mirando la pantalla.
"""
from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import re
import time
import unicodedata
from pathlib import Path
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

# CORRECCION (sesion 2026-09-25, caso real 2026-IE-036117): "Gestionar
# caso completo" se colgo en vivo mas de 15 minutos sin ningun error, sin
# ninguna linea nueva en dev_run.log y sin ningun cambio visible en el
# texto de estado de Flet -- una caja negra total, imposible de saber en
# cual de los 8 pasos (o cual sub-paso dentro de ellos) se habia quedado
# sin volver a mirar la pantalla de Chrome a ciegas. `_log_paso` imprime
# a stdout (con flush=True, para que quede en dev_run.log al instante, no
# solo al cerrar el proceso) antes/despues de cada paso real de Playwright
# en este modulo -- a diferencia del texto de estado de Flet (que vive
# solo en la UI y requiere una captura de pantalla para verse), esto
# queda escrito en disco de inmediato. La proxima vez que esto se cuelgue,
# dev_run.log debe decir exactamente en que paso se quedo, en vez de tener
# que adivinar.
# CORRECCION (sesion 2026-09-27): el prefijo estaba fijo en
# "[gestionar_caso_completo]" para TODO el modulo -- asi, cuando el ciclo
# automatico en segundo plano de main.py (cada 10 min) llamaba a
# listar_casos_gestionar(), sus lineas salian en dev_run.log rotuladas como
# si fueran de "Gestionar caso completo". El 2026-09-25 a las 15:09 eso hizo
# parecer que alguien habia disparado otra gestion sobre 2026-IE-036192
# (Andres confirmo que no fue el) cuando en realidad era la revision
# automatica de casos nuevos. Ahora cada flujo fija su propio rotulo.
_CONTEXTO_LOG: contextvars.ContextVar[str] = contextvars.ContextVar("contexto_log", default="sgdea")


_ULTIMO_LOG = {"t": None}


def _log_paso(mensaje: str) -> None:
    # (+X.Xs) = tiempo desde la linea anterior: asi el log real mide cuanto
    # tarda cada boton/respuesta de SGDEA, sin adivinar (v1.4.2).
    ahora = time.monotonic()
    previo = _ULTIMO_LOG["t"]
    _ULTIMO_LOG["t"] = ahora
    delta = f" (+{ahora - previo:.1f}s)" if previo is not None and ahora - previo < 3600 else ""
    print(f"[{_CONTEXTO_LOG.get()}] {time.strftime('%H:%M:%S')}{delta} {mensaje}", flush=True)


# Tope de tiempo total para gestionar_caso_completo() -- ver el comentario
# junto a asyncio.wait_for() en esa funcion.
TIMEOUT_CASO_COMPLETO_SEG = 15 * 60  # Andres: si SGDEA tarda, se espera


IFRAME_DOCUMENTOS = "#frameVerDocumentos"
# OJO: el iframe interno tiene id="" (vacio) -- solo se localiza por clase.
IFRAME_INPUT_TARGET = "iframe.dxreInputTarget"
ID_TIPO_DOCUMENTO_MEMORANDO_RESPUESTA = "439"

RIBBON_BOTON_GUARDAR = "Guardar"
RIBBON_BOTON_GENERAR_PDF = "Generar PDF"
RIBBON_BOTON_PROPIEDADES = "Propiedades"
RIBBON_BOTON_SOLICITAR_APROBACION = "Solicitar aprobación"

RIBBON_BOTON_INICIO_CICLO_APROBACION = "Inicio ciclo de aprobación"

# botones que este modulo tiene PROHIBIDO pulsar POR SU CUENTA -- es decir,
# como efecto secundario de cualquier funcion de "dejar el documento listo"
# (pegar_en_campo, seleccionar_revisor_ema, adjuntar_archivo_*, etc). La
# UNICA excepcion deliberada es `enviar_a_aprobacion()`, mas abajo: esa
# funcion existe PRECISAMENTE para pulsar "Solicitar aprobación" / "Inicio
# ciclo de aprobación", pero solo se llama a si misma cuando Andres pulsa
# "Aprobar y enviar" en el aplicativo (nunca de forma pasiva/automatica en
# segundo plano) -- ver casos_pendientes.py y la seccion "Memorandos" de
# main.py. El resto de funciones de este modulo deben seguir sin tocar
# NUNCA estos botones.
_BOTONES_PROHIBIDOS = {RIBBON_BOTON_GUARDAR, RIBBON_BOTON_GENERAR_PDF, RIBBON_BOTON_SOLICITAR_APROBACION}


class AutomatizacionError(Exception):
    """Algo en el flujo de automatizacion no se pudo completar. Nunca se
    usa esta excepcion para forzar un paso saltandose una verificacion."""


class _PasoOmitido(Exception):
    """Uso interno del orquestador: el paso ya se hizo en un intento anterior."""


class EditorApiNoDisponible(AutomatizacionError):
    """La API de JavaScript del editor no existe o no responde. Es el UNICO
    caso en que se permite el respaldo por coordenada para el cuerpo: si la
    API SI responde pero el documento esta en un estado inesperado (p.ej.
    ya lleno a medias), pegar por coordenada podria duplicar texto."""


@dataclasses.dataclass
class ResultadoAutomatizacion:
    ok: bool
    pasos_completados: list
    pendiente_revision_humana: bool = True  # SIEMPRE True: el envio final nunca es automatico
    warnings: list = dataclasses.field(default_factory=list)
    # Pasos que un intento anterior dio por hechos pero el documento NO los
    # muestra (verificado): el barrido los borra de su memoria para rehacerlos.
    pasos_a_rehacer: list = dataclasses.field(default_factory=list)


async def conectar_chrome_existente(cdp_url: str = "http://localhost:9222"):
    """Se conecta a un Chrome que Andres ya tiene abierto (arrancado con
    --remote-debugging-port=9222) y en el que YA inicio sesion en SGDEA.
    Nunca abre una sesion nueva, nunca pide ni escribe credenciales.
    Devuelve (playwright, browser, context) -- quien llame es responsable
    de cerrar playwright/browser al terminar."""
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(cdp_url)
    if not browser.contexts:
        raise AutomatizacionError(
            "El Chrome conectado no tiene ninguna pestaña/contexto abierto; "
            "Andres debe tener SGDEA ya abierto antes de correr esto"
        )
    context = browser.contexts[0]
    return playwright, browser, context


async def _frame_editor(page):
    """Localiza el frame del editor DevExpress (dentro del iframe anidado
    #frameVerDocumentos), listo para ubicar sus elementos internos."""
    return page.frame_locator(IFRAME_DOCUMENTOS)


async def _foco_actual_es_input_target(page) -> tuple[bool, str]:
    """Revisa cual elemento tiene el foco DENTRO del documento del iframe
    #frameVerDocumentos. Devuelve (ok, descripcion) -- ok=True solo si el
    foco esta realmente en el iframe.dxreInputTarget (la unica situacion en
    la que un Ctrl+V posterior va a pegar algo en el lugar esperado). Si
    ok=False, el llamador debe reintentar el click en otra coordenada --
    NUNCA asumir que un click "probablemente" funciono."""
    info = await page.evaluate(
        """
        () => {
            const outer = document.querySelector('#frameVerDocumentos');
            if (!outer) return { ok: false, desc: 'no existe #frameVerDocumentos' };
            const innerDoc = outer.contentDocument;
            const el = innerDoc ? innerDoc.activeElement : null;
            if (!el) return { ok: false, desc: 'sin activeElement' };
            const desc = el.tagName + '.' + (el.className || '');
            return { ok: el.tagName === 'IFRAME' && (el.className || '').includes('dxreInputTarget'), desc };
        }
        """
    )
    return info["ok"], info["desc"]


async def probar_click_editor(page, x: float, y: float) -> tuple[bool, str]:
    """Ayuda de CALIBRACION -- NUNCA pega ni escribe nada. Hace click en
    (x, y) dentro del documento actualmente abierto en 'Ver documentos' y
    devuelve exactamente la misma verificacion que pegar_en_campo() usa
    antes de pegar (_foco_actual_es_input_target), pero sin el paso de
    pegado. Pensada para descubrir en vivo, sin ningun riesgo de escribir
    contenido real sobre un documento real, que coordenada corresponde a
    cada campo (destinatario, asunto, saludo, cuerpo) -- coordenadas que
    hoy no existen confirmadas en este modulo."""
    await page.mouse.click(x, y)
    return await _foco_actual_es_input_target(page)


async def pegar_en_campo(page, coordenada_click: tuple[float, float], texto: str) -> None:
    """Hace click en `coordenada_click` (coordenadas de VIEWPORT, no del
    documento -- deben caer sobre una linea/parrafo real y visible del
    documento, p. ej. literalmente sobre el texto "Asunto:"; un click en
    blanco fuera del flujo del texto deja el pegado sin efecto Y SIN
    ERROR), verifica que el foco quedo en el punto correcto, pone `texto`
    en el portapapeles real del navegador, y lo pega con Ctrl+V -- el UNICO
    mecanismo confirmado contra este editor (escribir directo, o un Ctrl+V
    sintetico sin portapapeles real detras, NO llega a nada).

    Reemplaza a la antigua `pegar_cuerpo` (que asumia una sola coordenada
    generica de "el cuerpo"): ahora cada campo (destinatario, asunto,
    saludo, cuerpo) se pega por separado, con su propia coordenada, porque
    son parrafos distintos del mismo documento.

    Lanza AutomatizacionError si, tras el click, el foco no quedo en el
    iframe de pegado -- en vez de pegar a ciegas y confiar en que funciono."""
    context = page.context
    await context.grant_permissions(["clipboard-read", "clipboard-write"])

    _log_paso(f"pegar_en_campo({coordenada_click}): click en la coordenada...")
    await page.mouse.click(*coordenada_click)

    ok, desc = await _foco_actual_es_input_target(page)
    if not ok:
        raise AutomatizacionError(
            f"El click en {coordenada_click} no ubico el cursor dentro del "
            f"area de texto del documento (foco quedo en: {desc}). Este "
            "click probablemente cayo en un margen/espacio en blanco fuera "
            "del parrafo objetivo -- hay que apuntar a una coordenada sobre "
            "texto/linea real del documento."
        )

    # IMPORTANTE: escribir el portapapeles AQUI, después del click y sin
    # ningún .focus() manual de por medio -- forzar foco por separado antes
    # de esto rompe navigator.clipboard.writeText ("Document is not focused").
    _log_paso(f"pegar_en_campo({coordenada_click}): foco OK, escribiendo portapapeles y pegando (Ctrl+V)...")
    await page.evaluate(
        "async (texto) => { await navigator.clipboard.writeText(texto); }",
        texto,
    )
    await page.keyboard.press("Control+V")
    _log_paso(f"pegar_en_campo({coordenada_click}): OK, Ctrl+V enviado.")


async def verificar_pegado_via_red(page, timeout_ms: int = 5000) -> bool:
    """Intenta confirmar que el pegado disparo una sincronizacion con el
    servidor (llamada a DXS.ashx). ADVERTENCIA: en la sesion de pruebas mas
    reciente esta señal no aparecio de forma consistente (incluso sin
    filtro, sin ninguna peticion detectada) -- no usar como UNICA fuente de
    verdad; complementar siempre con una verificacion visual (screenshot de
    la zona exacta, con scroll previo si hace falta)."""
    visto = False

    def _on_request(request):
        nonlocal visto
        if "DXS.ashx" in request.url:
            visto = True

    page.on("request", _on_request)
    try:
        await page.wait_for_timeout(timeout_ms)
    finally:
        page.remove_listener("request", _on_request)
    return visto


async def deshacer_cambios(page, veces: int = 2) -> None:
    """Ctrl+Z dentro del editor para revertir una prueba. OJO: el valor por
    defecto se bajo de 5 a 2 porque una rafaga de Ctrl+Z de mas (se probo
    con 6 seguidos cuando bastaba con 1-2) puede hacer que el editor tire
    un dialogo de error ("Un error no especificado ocurrió y el editor
    necesita ser recargada"). Preferir deshacer de a poco y verificar
    visualmente entre cada intento en vez de mandar una rafaga fija y
    grande."""
    outer = await _frame_editor(page)
    inner = outer.frame_locator(IFRAME_INPUT_TARGET)
    await inner.locator("body").click()
    for _ in range(veces):
        await page.keyboard.press("Control+Z")


async def diligenciar_campos_pendiente(*args, **kwargs):
    """PLACEHOLDER historico -- DEJADO A PROPOSITO, ver nota abajo.

    Cuando se escribio esto, "revisora + mensaje de aprobación" y
    "adjuntos" todavia no se habian mapeado contra el DOM real. Desde la
    sesion del 2026-09-22 eso ya no es cierto: `seleccionar_revisor_ema`,
    `adjuntar_archivo_caso`, `adjuntar_archivo_documento` y
    `enviar_a_aprobacion` (mas abajo) cubren exactamente eso, cada una
    confirmada en vivo por separado salvo `enviar_a_aprobacion` (que sigue
    sin probarse en vivo, ver su propio docstring). Esta funcion se deja
    sin borrar solo como referencia historica de la disciplina del
    proyecto (no inventar selectores sin haberlos visto en vivo); no la
    use codigo nuevo -- llame a las funciones especificas de abajo."""
    raise NotImplementedError(
        "Reemplazada por funciones especificas (seleccionar_revisor_ema, "
        "adjuntar_archivo_caso, adjuntar_archivo_documento, "
        "enviar_a_aprobacion) -- no usar esta funcion en codigo nuevo."
    )


async def _primer_visible(locator, timeout_ms: int = 5000, intervalo_ms: int = 250):
    """Devuelve el primer elemento VISIBLE de `locator` (sondeando hasta
    `timeout_ms`), o None si ninguno llega a estar visible.

    Existe porque en SGDEA el mismo texto/selector aparece a menudo varias
    veces en el DOM, con copias OCULTAS de vistas anteriores (la grilla
    'Gestionar', los modales #TMSDialogModalDialog ya cerrados, etc.).
    `locator.first` elige la primera en orden de documento aunque este
    oculta -- y un click sobre ella se queda esperando 30s hasta el
    timeout. Esta ayuda elige siempre una que de verdad se ve."""
    loop = asyncio.get_running_loop()
    limite = loop.time() + timeout_ms / 1000
    while True:
        try:
            n = await locator.count()
        except Exception:
            n = 0
        for i in range(n):
            candidato = locator.nth(i)
            try:
                if await candidato.is_visible():
                    return candidato
            except Exception:
                continue
        if loop.time() >= limite:
            return None
        await asyncio.sleep(intervalo_ms / 1000)


# Carpeta donde se guardan capturas de pantalla cuando algo falla (la fija
# main.py: dist\diagnosticos). Sirven para ver despues que mostraba SGDEA sin
# que Andres tenga que estar mirando. Solo se guardan las ultimas 60.
CARPETA_DIAGNOSTICOS: Optional[Path] = None
MAX_CAPTURAS_DIAGNOSTICO = 60


async def _capturar_pantalla(page, nombre: str) -> str:
    if CARPETA_DIAGNOSTICOS is None:
        return ""
    try:
        carpeta = Path(CARPETA_DIAGNOSTICOS)
        carpeta.mkdir(parents=True, exist_ok=True)
        limpio = re.sub(r"[^A-Za-z0-9_.-]+", "_", nombre)[:80]
        ruta = carpeta / f"{datetime.now():%Y%m%d_%H%M%S}_{limpio}.png"
        await page.screenshot(path=str(ruta), full_page=False, timeout=8000)
        viejas = sorted(carpeta.glob("*.png"), key=lambda x: x.stat().st_mtime)
        for v in viejas[:-MAX_CAPTURAS_DIAGNOSTICO]:
            try:
                v.unlink()
            except Exception:
                pass
        _log_paso(f"captura de pantalla guardada: {ruta.name}")
        return ruta.name
    except Exception:
        return ""


async def _diagnostico_pagina(page) -> str:
    """Resumen corto del estado real de la pagina, para anexar a los
    mensajes de AutomatizacionError: URL + tooltips (data-original-title)
    visibles + los primeros textos de menus/modales visibles. Nunca lanza
    -- si algo falla al diagnosticar, se omite esa parte. Reemplaza la
    antigua 'pista' basada en el texto 'tipo de documento', que daba un
    falso positivo siempre (esa frase existe fija en el panel
    'Expediente' de todo caso)."""
    partes = []
    try:
        partes.append(f"URL: {page.url}")
    except Exception:
        pass
    try:
        titulos = await page.locator("[data-original-title]").evaluate_all(
            "els => els.filter(e => e.offsetParent !== null)"
            ".map(e => e.getAttribute('data-original-title'))"
        )
        partes.append(f"tooltips visibles: {titulos!r}")
    except Exception:
        pass
    try:
        textos = await page.locator(
            ".dropdown-menu, .modal-dialog, [role=dialog], [role=menu]"
        ).evaluate_all(
            "els => els.filter(e => e.offsetParent !== null)"
            ".map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120))"
            ".filter(t => t)"
        )
        if textos:
            partes.append(f"menus/modales visibles: {textos!r}")
    except Exception:
        pass
    try:
        aviso = await _leer_aviso_sweet(page)
        if aviso:
            partes.append(f"aviso SGDEA: {aviso.get('titulo')!r} {aviso.get('texto')!r} (tipo {aviso.get('tipo') or '?'})")
    except Exception:
        pass
    try:
        # 30-sep-2026 (v1.5.12): las URL de los marcos (sin parametros) dejan
        # evidencia de que hay en 'Ver documentos' cuando el editor no carga
        # (2026-IE-035664: el diagnostico no decia que era un PDF).
        marcos = [(f.name or "-") + "=" + (f.url or "").split("?")[0][-80:] for f in page.frames[1:8]]
        if marcos:
            partes.append(f"marcos: {marcos!r}")
    except Exception:
        pass
    captura = await _capturar_pantalla(page, "diagnostico")
    if captura:
        partes.append(f"captura: diagnosticos\\{captura}")
    try:
        titulos_frame = await page.frame_locator(IFRAME_DOCUMENTOS).locator("[data-original-title]").evaluate_all(
            "els => els.filter(e => e.offsetParent !== null).map(e => e.getAttribute('data-original-title'))"
        )
        partes.append(f"tooltips dentro del editor: {titulos_frame!r}")
    except Exception:
        partes.append("editor: sin acceso a su contenido")
    return (" [Diagnostico -- " + " | ".join(partes) + "]") if partes else ""


# CORRECCION (evidencia: insignia_run.log, 27-sep 19:57, caso 2026-IE-036231
# + explicacion de Andres): el documento se creo en 1s y #frameVerDocumentos
# aparecio de inmediato, pero SGDEA tarda 2-4s (a veces mas) en DIBUJAR el
# editor y la columna de iconos de la izquierda. El paso 2 busco el icono
# 'Destinatario Tipificación' solo 5s y fallo. Ahora navegar_a_caso() no se
# da por terminado hasta ver la columna de iconos dentro del frame (hasta
# 45s, con sondeo), y deja en el log cuanto tardo de verdad.
ICONO_REFERENCIA_EDITOR = '[data-original-title="Destinatario Tipificación"]'
TIMEOUT_EDITOR_LISTO_MS = 45000


_SELECTOR_VISOR_PDF = "embed[type*='pdf'], object[type*='pdf'], embed[src*='.pdf'], iframe[src*='.pdf'], iframe[src*='pdf'], pdf-viewer"


def _es_url_pdf(url: str) -> bool:
    u = (url or "").lower()
    return ".pdf" in u or u.startswith("chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai")  # visor PDF de Chrome


async def _muestra_pdf_final(page) -> bool:
    """True si 'Ver documentos' muestra un visor de PDF (documento ya radicado)."""
    for raiz in (page.frame_locator(IFRAME_DOCUMENTOS), page):
        try:
            if await raiz.locator(_SELECTOR_VISOR_PDF).count():
                return True
        except Exception:
            pass
    # 30-sep-2026 (v1.5.12), evidencia insignia_run.log 08:51:00 y 08:56:44 +
    # capturas 20260930_085059/085643_diagnostico.png, caso 2026-IE-035664: la
    # pantalla muestra el visor de PDF de Chrome con el memorando YA RADICADO
    # (2026-IE-036536), pero la revision de arriba no lo vio (el visor no esta en
    # el primer nivel de #frameVerDocumentos) y el caso se siguio reintentando
    # (45 s por intento, cada 4 min). Ahora se revisan TODOS los marcos de la
    # pagina, a cualquier profundidad: su URL o un <embed> de PDF dentro.
    for fr in page.frames:
        try:
            if fr is not page.main_frame and _es_url_pdf(fr.url):
                return True
            if await fr.locator(_SELECTOR_VISOR_PDF).count():
                return True
        except Exception:
            pass
    try:
        src = await page.locator(IFRAME_DOCUMENTOS).first.get_attribute("src", timeout=1000)
        if src and ".pdf" in src.lower():
            return True
    except Exception:
        pass
    return False


async def _esperar_editor_listo(page, radicado: str = "") -> None:
    loop = asyncio.get_running_loop()
    inicio = loop.time()
    frame = page.frame_locator(IFRAME_DOCUMENTOS)
    icono = await _primer_visible(frame.locator(ICONO_REFERENCIA_EDITOR), timeout_ms=TIMEOUT_EDITOR_LISTO_MS)
    segundos = loop.time() - inicio
    if icono is None and await _muestra_pdf_final(page):
        # Evidencia (29-sep, 2026-IE-035664, 10 intentos seguidos): 'Ver
        # documentos' mostraba el PDF YA RADICADO (2026-IE-036536) en el visor,
        # no el editor: el caso ya se respondio. No se vuelve a intentar.
        raise AutomatizacionError(
            f"El caso {radicado!r} ya está radicado: 'Ver documentos' muestra el PDF final (no el editor) -- "
            "ya se respondió; Insignia no lo toca."
        )
    if icono is None:
        raise AutomatizacionError(
            f"El documento del caso {radicado!r} se abrio pero el editor no termino de cargar "
            f"en {TIMEOUT_EDITOR_LISTO_MS // 1000}s (no aparece la columna de iconos). "
            "OJO: el documento ya existe -- la proxima corrida entra por 'Ver documentos'."
            + await _diagnostico_pagina(page)
        )
    _log_paso(f"editor listo en {segundos:.1f}s (columna de iconos visible).")
    await asyncio.sleep(0.8)  # margen para que terminen los manejadores de SGDEA


async def _esperar_modal_tms(frame, que: str, timeout_ms: int = 8000):
    """Espera a que el modal generico #TMSDialogModalDialog este VISIBLE
    dentro de `frame` y lo devuelve. Reemplaza el patron anterior
    `wait_for_timeout(800)` + `modal.count()`, que tenia un fallo real: el
    contenedor del modal queda en el DOM (oculto) despues de cerrarse, asi
    que count() > 0 pasaba aunque el modal NUEVO nunca se hubiera abierto
    -- y el siguiente .fill()/.click() sobre un campo oculto se quedaba
    30s esperando. Lanza AutomatizacionError con un mensaje claro."""
    modal = await _primer_visible(frame.locator(ID_MODAL_GENERICO_TMS), timeout_ms=timeout_ms)
    if modal is None:
        raise AutomatizacionError(
            f"Se hizo click en '{que}' pero el modal esperado "
            f"({ID_MODAL_GENERICO_TMS}) no quedo visible en {timeout_ms // 1000}s."
        )
    return modal


# ------------------------------------------------------------------
# Navegacion al caso por radicado (confirmado en vivo, sesion 2026-09-22,
# caso real 2026-IE-035142). Todo esto vive en DOM normal (fuera del
# canvas del editor), asi que Playwright puede ubicar los elementos por
# atributo/texto -- salvo el bloque "Gestionar" del dashboard, que es un
# <canvas> y solo se puede clickear por coordenada fija.
# ------------------------------------------------------------------

SELECTOR_BUSQUEDA_GESTIONAR = "input.form-control.form-control-sm"
# Coordenada de click fija (viewport) para el bloque "Gestionar" del
# dashboard de "Inicio" -- confirmada en vivo con la ventana en su tamaño
# por defecto de esta sesion. Igual que las coordenadas del editor: solo
# es valida si la ventana/zoom estan en esa misma configuracion; si
# cambia el tamaño de ventana hay que reconfirmarla visualmente.
COORDENADA_BLOQUE_GESTIONAR = (644, 270)
TIMEOUT_BREADCRUMB_MS = 8000


async def _asegurar_bloque_gestionar_abierto(page) -> None:
    """Deja visible el cuadro 'Buscar:' de la lista 'Gestionar', abriendo
    el bloque del dashboard SOLO si hace falta -- revisa el estado real
    (busqueda.is_visible()) ANTES de decidir si toca clickear.

    El bloque 'Gestionar' es un <canvas> DevExpress sin sub-elementos de
    DOM direccionables (confirmado en vivo), asi que solo se puede
    abrir/cerrar por click de coordenada fija (COORDENADA_BLOQUE_GESTIONAR)
    -- pero ese click es un TOGGLE: si el bloque ya estaba abierto, el
    mismo click lo PLIEGA en vez de desplegarlo. Clickear a ciegas sin
    revisar el estado real fue la causa confirmada en vivo (sesion
    2026-09-25, caso real 2026-IE-036117) de 'Error inesperado
    (TimeoutError): Locator.click: Timeout 30000ms exceeded' con 'element
    is not visible' repetido durante los 30s completos -- el cuadro
    'Buscar:' SI estaba en el DOM, solo que recien plegado por nuestro
    propio click anterior. Por eso esta funcion es la UNICA que debe
    tocar COORDENADA_BLOQUE_GESTIONAR en todo el modulo.

    Lanza AutomatizacionError si, despues de intentarlo, el cuadro sigue
    sin quedar visible -- nunca sigue adelante a ciegas."""
    busqueda = page.locator(SELECTOR_BUSQUEDA_GESTIONAR).first
    if await busqueda.count() and await busqueda.first.is_visible():
        return  # ya esta abierto -- no tocar el toggle

    await page.mouse.click(*COORDENADA_BLOQUE_GESTIONAR)
    busqueda = page.locator(SELECTOR_BUSQUEDA_GESTIONAR).first
    try:
        await busqueda.wait_for(state="visible", timeout=3000)
        return
    except Exception:
        pass

    if not await busqueda.count():
        raise AutomatizacionError(
            "No aparecio el cuadro 'Buscar:' de la lista 'Gestionar' "
            "despues de hacer click en el bloque del dashboard -- el "
            "layout puede haber cambiado, o el click por coordenada "
            f"fija {COORDENADA_BLOQUE_GESTIONAR} ya no cae sobre ese "
            "bloque (revisar tamaño/zoom de ventana)."
        )

    # El cuadro esta en el DOM pero no quedo visible -- lo mas probable
    # es que el click de arriba haya PLEGADO un bloque que, pese al
    # chequeo is_visible() inicial, ya estaba abierto (p.ej. por un
    # repintado en curso en ese instante). Un segundo click deberia
    # "destogglearlo" de vuelta.
    await page.mouse.click(*COORDENADA_BLOQUE_GESTIONAR)
    try:
        await busqueda.wait_for(state="visible", timeout=3000)
    except Exception:
        raise AutomatizacionError(
            "El cuadro 'Buscar:' de la lista 'Gestionar' aparecio en el "
            "DOM pero no quedo visible tras dos clicks en el bloque "
            f"{COORDENADA_BLOQUE_GESTIONAR} -- revisar manualmente en "
            "que pantalla/estado quedo Chrome."
        ) from None


async def _regresar_a_lista_gestionar(page) -> None:
    """Deja visible el cuadro 'Buscar:' de la lista 'Gestionar', usando la
    ruta de navegacion mas directa segun donde este `page` en este momento
    -- reemplaza las llamadas directas a _asegurar_bloque_gestionar_abierto
    en los puntos donde `page` puede estar DENTRO de un caso ya abierto (no
    solo en el dashboard de 'Inicio').

    CORRECCION (sesion 2026-09-25, evidencia directa: 3 capturas anotadas
    que Andres compartio de su propio flujo manual con el caso
    2026-IE-035690) -- confirmado en vivo, NO adivinado:
      1. Al terminar un caso (documento enviado a aprobacion), la pagina
         de detalle del caso muestra un breadcrumb "Inicio / Memorando /
         {radicado} - Memorando" en la parte superior.
      2. Andres regresa a la lista 'Gestionar' haciendo click en el
         segmento intermedio del breadcrumb, con texto EXACTO "Memorando"
         (no "Inicio", no el radicado completo -- y "Memorando" tambien
         aparece dentro de la frase "Proceso: Memorando - SOLICITUDES..."
         en esa misma pagina, por lo que hace falta match EXACTO -- no
         substring -- para no clickear el lugar equivocado).
      3. Ese click deja la pagina DIRECTAMENTE en la lista 'Gestionar' ya
         renderizada, con el cuadro 'Buscar:' visible de una -- sin pasar
         en absoluto por el bloque-canvas del dashboard de 'Inicio'.

    Esto explica el AutomatizacionError real visto en vivo (sesion
    2026-09-25, caso 2026-IE-036117, mensaje "aparecio en el DOM pero no
    quedo visible tras dos clicks en el bloque (644, 270)"): navegar_a_caso()
    llama internamente dos veces a _abrir_caso_landing(), y la segunda vez
    ocurre DESPUES de que descargar_peticion_caso() ya entro y salio de un
    caso -- es decir, `page` esta en la pagina de detalle de ESE caso, no
    en el dashboard de 'Inicio'. Clickear ahi la coordenada fija
    COORDENADA_BLOQUE_GESTIONAR (que solo tiene sentido sobre el <canvas>
    del dashboard) no hace nada util -- por eso el cuadro 'Buscar:' nunca
    aparecia.

    Por eso esta funcion revisa 3 rutas EN ORDEN, cada una solo si la
    anterior no aplico -- nunca clickea a ciegas:
      1. Si el cuadro 'Buscar:' ya esta visible, no hace nada (idempotente).
      2. Si hay un breadcrumb con texto EXACTO 'Memorando' visible, lo
         clickea (ruta confirmada en vivo -- caso: `page` esta dentro de
         un caso ya abierto).
      3. Si no, cae al toggle de coordenada fija del bloque 'Gestionar'
         del dashboard, via _asegurar_bloque_gestionar_abierto (ruta
         original -- caso: `page` esta en 'Inicio').

    Lanza AutomatizacionError si, tras agotar las 3 rutas, el cuadro
    'Buscar:' sigue sin quedar visible -- nunca sigue adelante a ciegas
    (la excepcion final la lanza _asegurar_bloque_gestionar_abierto)."""
    busqueda = page.locator(SELECTOR_BUSQUEDA_GESTIONAR).first
    if await busqueda.count() and await busqueda.first.is_visible():
        return  # ya esta en la lista 'Gestionar' -- nada que hacer

    breadcrumb_memorando = page.get_by_text("Memorando", exact=True)
    if await breadcrumb_memorando.count() and await breadcrumb_memorando.first.is_visible():
        _log_paso("_regresar_a_lista_gestionar: breadcrumb 'Memorando' visible, clickeando (ruta confirmada en vivo, sesion 2026-09-25)...")
        await breadcrumb_memorando.first.click()
        busqueda = page.locator(SELECTOR_BUSQUEDA_GESTIONAR).first
        try:
            # Evidencia (insignia_run.log): cuando el breadcrumb SI lleva a la
            # lista, 'Buscar:' aparece en menos de 1 s (27-sep 19:57:13); cuando
            # no, no aparece nunca (28-sep 08:31: 25 s perdidos). 8 s cubre la
            # lentitud de SGDEA (2-4 s) sin desperdiciar tiempo.
            await busqueda.wait_for(state="visible", timeout=TIMEOUT_BREADCRUMB_MS)
            _log_paso("_regresar_a_lista_gestionar: OK via breadcrumb 'Memorando'.")
            return
        except Exception:
            # El "Memorando" encontrado por get_by_text pudo no ser el del
            # breadcrumb (podria haber otro match exacto en la pagina) --
            # no se lanza error todavia, se cae a la ruta 3 como respaldo.
            _log_paso("_regresar_a_lista_gestionar: breadcrumb clickeado pero el cuadro 'Buscar:' no aparecio -- probando el toggle del dashboard como respaldo...")

    _log_paso("_regresar_a_lista_gestionar: sin breadcrumb 'Memorando' utilizable, usando el toggle de coordenada fija del bloque 'Gestionar' (ruta dashboard)...")
    await _asegurar_bloque_gestionar_abierto(page)


async def _buscar_radicado_en_gestionar(page, radicado: str, espera_ms: int = 800) -> None:
    """Escribe `radicado` en el cuadro 'Buscar:' de la lista 'Gestionar'
    (que debe estar YA visible -- llamar primero a
    _asegurar_bloque_gestionar_abierto) y espera `espera_ms` a que la
    grilla DevExpress se refiltre. Reescribir el radicado (aunque sea el
    mismo de antes) tambien sirve para FORZAR un repintado fresco de la
    grilla, ya que dispara de nuevo el filtro AJAX interno de DevExpress."""
    busqueda = page.locator(SELECTOR_BUSQUEDA_GESTIONAR).first
    await busqueda.click()
    # Se limpia primero -- si quedo texto de una busqueda anterior (de
    # otro radicado), .fill() sin vaciar antes puede dejar el cuadro con
    # una mezcla de texto en vez de reemplazarlo.
    await busqueda.fill("")
    await busqueda.fill(radicado)
    # La grilla es de modo servidor: el filtro viaja a SGDEA y vuelve. Se
    # espera a que la grilla YA FILTRADA muestre solo ese caso (hasta 15 s).
    # Evidencia (log 28-sep 10:23): esperar solo a "ver la fila" hacia clic
    # sobre la fila de la lista completa, que SGDEA redibujaba enseguida ->
    # 'click fallo, refrescando y reintentando' (+7 s por caso).
    loop = asyncio.get_running_loop()
    limite = loop.time() + 15
    while loop.time() < limite:
        try:
            visibles = [f["radicado"] for f in await _leer_filas_visibles(page)]
        except Exception:
            visibles = []
        if visibles == [radicado]:
            break
        await asyncio.sleep(0.3)
    await page.wait_for_timeout(espera_ms)


async def _pagina_parece_login(page) -> bool:
    """Deteccion basica de si terminamos en la pantalla de login en vez
    del dashboard/caso esperado -- si esto da True, el llamador debe
    detenerse de inmediato (AutomatizacionError) y NUNCA intentar
    loguearse ni tocar el formulario."""
    try:
        texto = (await page.locator("body").inner_text(timeout=5000))[:800].lower()
    except Exception:
        return False
    return "contraseña" in texto and ("iniciar sesión" in texto or "usuario" in texto)


async def _abrir_caso_landing(page, radicado: str) -> None:
    """Deja `page` en la pagina de aterrizaje/detalle del caso `radicado`
    (la que muestra "Informacion de proceso", "Asunto", "Informacion de
    negocio" y el panel "Expediente" con los documentos adjuntos, entre
    ellos la peticion original) -- SIN avanzar a "Ver documentos".

    Factoriza la parte de navegacion que es comun a navegar_a_caso() (que
    SI avanza a "Ver documentos" despues de esto) y a
    descargar_peticion_caso() (que se queda en esta pagina, porque es
    donde vive el panel "Expediente"). Confirmado en vivo (sesion
    2026-09-22, caso 2026-IE-035142): cada fila de la lista "Gestionar"
    trae un checkbox `#chkSol{radicado}-1`, y dentro de esa misma fila
    <tr> un boton `button.gestion` que abre el caso.

    Si la fila no esta ya visible (lista "Gestionar" no abierta todavia),
    primero hace click en el bloque "Gestionar" del dashboard (un canvas,
    por eso es por coordenada fija) y despues busca el radicado en el
    cuadro "Buscar:".

    Lanza AutomatizacionError si en cualquier punto la pagina parece ser
    la de login (sesion expirada) o si el radicado no aparece en la
    lista -- nunca sigue adelante a ciegas."""
    if await _pagina_parece_login(page):
        raise AutomatizacionError(
            "La sesion de SGDEA parece haber expirado (se ve la pantalla "
            "de login). No se toca -- Andres debe iniciar sesion el "
            "mismo antes de reintentar."
        )

    fila_checkbox = page.locator(f"#chkSol{radicado}-1")

    async def _checkbox_visible() -> bool:
        # OJO: no basta con .count() > 0 -- la lista 'Gestionar' es un
        # grid de DevExpress que puede dejar en el DOM checkboxes de una
        # busqueda/filtro ANTERIOR (de otro radicado ya revisado en esta
        # misma sesion de Chrome) ocultos por CSS en vez de removidos.
        # .count() los sigue contando aunque no se vean, lo que hacia que
        # esta funcion se saltara la busqueda y despues se quedara
        # esperando 30s un click sobre un boton que nunca aparece
        # (confirmado en vivo, sesion 2026-09-23, caso 2026-IE-035692:
        # TimeoutError esperando 'button.gestion' con 'element is not
        # visible' repetido). Por eso aqui se exige ademas is_visible().
        return bool(await fila_checkbox.count()) and await fila_checkbox.first.is_visible()

    if not await _checkbox_visible():
        _log_paso(f"_abrir_caso_landing({radicado!r}): fila no visible, regresando a la lista 'Gestionar' y buscando...")
        await _regresar_a_lista_gestionar(page)
        await _buscar_radicado_en_gestionar(page, radicado)
        fila_checkbox = page.locator(f"#chkSol{radicado}-1")
        _log_paso(f"_abrir_caso_landing({radicado!r}): busqueda hecha, reintentando ubicar la fila.")

    if not await fila_checkbox.count():
        raise AutomatizacionError(
            f"No se encontro el caso {radicado!r} en la lista 'Gestionar' "
            "(revisar que el radicado sea correcto y que el caso siga "
            "asignado a Andres)."
        )

    if not await _checkbox_visible():
        raise AutomatizacionError(
            f"Se encontro el caso {radicado!r} en la lista 'Gestionar' "
            "pero la fila sigue sin quedar visible despues de buscar por "
            "el radicado -- revisar manualmente (puede que la ventana "
            "este en un tamaño/zoom distinto al calibrado, o que haya "
            "paginacion en la lista que la esconda)."
        )

    async def _click_boton_gestion() -> None:
        fila = page.locator(f"#chkSol{radicado}-1").locator("xpath=ancestor::tr[1]")
        boton = fila.locator("button.gestion")
        if not await boton.count():
            raise AutomatizacionError(
                f"Se encontro la fila del caso {radicado!r} pero no el "
                "boton 'button.gestion' dentro de ella -- revisar si el "
                "markup de la fila cambio."
            )
        # scroll_into_view_if_needed antes del click: la grilla de
        # DevExpress puede dejar la fila dentro de un contenedor con
        # scroll propio -- is_visible() (CSS) no detecta eso, solo el
        # chequeo de accionabilidad real de Playwright antes del click.
        await boton.first.scroll_into_view_if_needed()
        await boton.first.click(timeout=10000)

    from playwright.async_api import Error as _PlaywrightError

    try:
        _log_paso(f"_abrir_caso_landing({radicado!r}): click en button.gestion...")
        await _click_boton_gestion()
        _log_paso(f"_abrir_caso_landing({radicado!r}): click en button.gestion OK (primer intento).")
    except _PlaywrightError:
        _log_paso(f"_abrir_caso_landing({radicado!r}): click en button.gestion fallo, refrescando grilla y reintentando...")
        # CORRECCION (sesion 2026-09-23, caso real 2026-IE-035845,
        # TimeoutError "element is not visible" reportado por Andres):
        # is_visible() de _checkbox_visible() es un chequeo CSS liviano
        # que puede dar True aunque la fila este en realidad TAPADA por
        # la vista actualmente activa (p. ej. si Chrome quedo mirando el
        # documento/landing page de una corrida anterior en vez de la
        # grilla 'Gestionar' -- SGDEA parece dejar esa grilla montada en
        # el DOM en vez de removerla al navegar a otra vista). El chequeo
        # de accionabilidad real que hace Playwright antes de un click SI
        # detecta esa oclusion -- por eso aqui, en vez de fallar de una,
        # se fuerza una navegacion fresca (click en el bloque 'Gestionar'
        # + rebuscar el radicado) y se reintenta el click UNA vez mas.
        #
        # AMPLIACION (confirmado en vivo, sesion 2026-09-25, caso real
        # 2026-IE-036117): ademas del TimeoutError original, tambien se
        # vio en vivo 'Locator.scroll_into_view_if_needed: Element is
        # not attached to the DOM' -- un Error de Playwright (NO
        # TimeoutError) que ocurre cuando la grilla DevExpress hace un
        # segundo repintado justo despues del filtro por radicado (el
        # `wait_for_timeout(800)` de mas arriba no alcanza a cubrir ese
        # repintado tardio), y la fila que se acababa de ubicar queda
        # obsoleta entre encontrarla y actuar sobre ella. Por eso aqui se
        # capta el Error base de Playwright (que incluye TimeoutError
        # como subclase) en vez de solo TimeoutError -- el mismo
        # reintento (refrescar la grilla + rebuscar) cubre ambos casos.
        #
        # OJO -- NO se llama a page.mouse.click(*COORDENADA_BLOQUE_GESTIONAR)
        # a ciegas aqui: si llegamos a este bloque es porque
        # _click_boton_gestion() ya fallo DESPUES de que la fila del caso
        # (y por lo tanto el panel 'Gestionar') ya estaba visible -- es
        # decir, el panel YA esta abierto. Clickear la coordenada del
        # bloque en ese estado lo PLIEGA en vez de refrescarlo (mismo
        # 'element is not visible' confirmado en vivo, ver
        # _asegurar_bloque_gestionar_abierto).
        #
        # AMPLIACION (sesion 2026-09-25, caso real 2026-IE-036117): este
        # punto tambien se alcanza cuando `page` esta DENTRO de un caso ya
        # abierto (segunda llamada interna a _abrir_caso_landing desde
        # navegar_a_caso, despues de que descargar_peticion_caso() ya entro
        # y salio de un caso) -- ahi la coordenada del dashboard no aplica
        # en absoluto, ni abierto ni plegado, porque `page` no esta en
        # 'Inicio'. Por eso aqui se usa _regresar_a_lista_gestionar(), que
        # revisa el estado real (ya visible / breadcrumb 'Memorando'
        # disponible / dashboard) y solo entonces decide como volver a la
        # lista -- _asegurar_bloque_gestionar_abierto() sigue siendo la
        # UNICA que toca COORDENADA_BLOQUE_GESTIONAR, ahora como ultimo
        # recurso dentro de _regresar_a_lista_gestionar(). Luego de eso
        # hace falta forzar un repintado de la grilla, y eso lo logra
        # _buscar_radicado_en_gestionar() al reescribir el radicado (dispara
        # de nuevo el filtro AJAX de DevExpress), con mas margen que el
        # intento inicial para no pisar el mismo repintado tardio.
        await _regresar_a_lista_gestionar(page)
        await _buscar_radicado_en_gestionar(page, radicado, espera_ms=1500)
        try:
            await _click_boton_gestion()
            _log_paso(f"_abrir_caso_landing({radicado!r}): click en button.gestion OK (reintento).")
        except _PlaywrightError as exc:
            raise AutomatizacionError(
                f"El boton 'button.gestion' del caso {radicado!r} sigue "
                "sin quedar clickeable (timeout o elemento no adjunto al "
                "DOM) despues de refrescar la grilla 'Gestionar' y "
                "reintentar -- revisar manualmente en que pantalla quedo "
                "Chrome (puede que la vista actual este tapando la "
                "grilla, o que el repintado de la grilla tarde mas de lo "
                "esperado)."
            ) from exc

    _log_paso(f"_abrir_caso_landing({radicado!r}): caso abierto, esperando 1200ms a que asiente la pagina...")
    await page.wait_for_timeout(1200)
    # SGDEA lento: 1.2 s no siempre alcanzan. Se espera ademas (hasta 15 s) a
    # ver la barra del caso -- sus iconos 'Crear documento'/'Ver documentos'
    # son los que el diagnostico real mostro visibles en esta pagina
    # (insignia_run.log 27-sep 19:57:25).
    barra = await _primer_visible(
        page.locator('[data-original-title="Crear documento"], [data-original-title="Ver documentos"]'), timeout_ms=15000
    )
    if barra is None:
        _log_paso(f"_abrir_caso_landing({radicado!r}): AVISO -- en 15 s no se vio la barra del caso ('Crear documento'/'Ver documentos').")

    if await _pagina_parece_login(page):
        raise AutomatizacionError(
            "La sesion expiro justo al abrir el caso. No se toca -- "
            "Andres debe iniciar sesion el mismo antes de reintentar."
        )
    _log_paso(f"_abrir_caso_landing({radicado!r}): OK, en pagina de aterrizaje.")


async def navegar_a_caso(page, radicado: str, crear_documento_si_hace_falta: bool = False) -> None:
    """Deja `page` en la vista "Ver documentos" del caso `radicado` (p.ej.
    '2026-IE-035142') -- primero pasa por la pagina de aterrizaje (ver
    _abrir_caso_landing) y despues avanza a "Ver documentos". Si el
    documento ya existe (como en el flujo de esta funcion: casos que YA
    se dejaron listos por el pipeline/proceso previo), el click de
    _abrir_caso_landing() lleva DIRECTO a "Ver documentos", sin pasar por
    "Crear documento" de nuevo.

    Si `crear_documento_si_hace_falta` es True y el caso todavia NO tiene
    ningun documento (ni "Ver documentos" ni el icono del toolbar
    aparecen), hace click en "Crear documento" y despues encadena los DOS
    pasos que en vivo resultaron obligatorios (CONFIRMADO en vivo, sesion
    2026-09-25, caso real 2026-IE-036192, evidencia directa de Andres --
    la hipotesis anterior, de que el icono abria directo el editor en
    blanco, quedo descartada por dos corridas reales fallidas): el click en
    "Crear documento" abre un DESPLEGABLE debajo del icono con el item de
    texto 'Memorando respuesta' (corregido 2026-09-27 releyendo la captura
    de Andres -- no es un icono con tooltip), y despues 'Guardar' en el
    modal de confirmacion "Este documento finaliza la gestión?" (se
    verifica que 'Si' este marcado, sin tocarlo). Por defecto
    `crear_documento_si_hace_falta` queda en False
    porque gestionar_caso_completo() es la unica llamadora que la activa
    -- las demas funciones de este modulo (navegar_a_caso desde el panel
    de calibracion, por ejemplo) siguen exigiendo que el documento ya
    exista, para no crear documentos nuevos como efecto secundario de
    solo estar probando algo.

    Lanza AutomatizacionError si en cualquier punto la pagina parece ser
    la de login (sesion expirada), si el radicado no aparece en la
    lista, o si nunca se llega a "Ver documentos" -- nunca sigue
    adelante a ciegas."""
    await _abrir_caso_landing(page, radicado)
    await _abrir_ver_documentos(page, radicado, crear_documento_si_hace_falta)
    if not await page.locator(IFRAME_DOCUMENTOS).count() and not crear_documento_si_hace_falta:
        # Evidencia (log 28-sep 16:53, caso 2026-IE-035691): el documento ya
        # existia pero 'Ver documentos' no abrio el editor. Se vuelve a abrir
        # el caso desde la lista y se intenta una vez mas antes de rendirse.
        _log_paso(f"navegar_a_caso({radicado!r}): 'Ver documentos' no abrio el editor -- se reabre el caso y se reintenta una vez...")
        await _capturar_pantalla(page, f"{radicado}_ver_documentos_1")
        await _abrir_caso_landing(page, radicado)
        await _abrir_ver_documentos(page, radicado, crear_documento_si_hace_falta)
    await _crear_documento_si_hace_falta(page, radicado, crear_documento_si_hace_falta)


async def _abrir_ver_documentos(page, radicado: str, crear_documento_si_hace_falta: bool) -> None:
    # Si el click en 'gestion' no llevo directo a "Ver documentos" (puede
    # pasar si el caso no tenia todavia un documento creado), se intenta
    # el icono del toolbar.
    #
    # CORRECCION (sesion 2026-09-24, caso real 2026-IE-036117, confirmado
    # en vivo): en un caso SIN documento creado todavia, este icono SIGUE
    # presente en el DOM pero oculto/no interactuable (Playwright lo
    # resuelve pero nunca lo ve "visible, enabled and stable") -- con el
    # timeout por defecto de Playwright (30s) esto colgaba 30 segundos
    # completos y terminaba en un TimeoutError crudo sin mensaje util, en
    # vez de caer rapido al fallback de "Crear documento" de abajo. Por
    # eso aqui el click usa un timeout corto (3s): si el icono no esta
    # realmente clickeable en ese tiempo, se asume que este caso no tiene
    # documento todavia y se sigue de una vez al bloque de abajo.
    if not await page.locator(IFRAME_DOCUMENTOS).count():
        icono_ver_documentos = page.locator('[data-original-title="Ver documentos"]')
        if await icono_ver_documentos.count():
            # Si un intento anterior YA creo el documento (crear=False), se le da
            # todo el tiempo a 'Ver documentos' y NUNCA se crea otro. Evidencia
            # (log 28-sep 16:19, caso 2026-IE-035691): con SGDEA lento el clic
            # rapido de 3 s fallo, Insignia creyo que no habia documento y
            # empezo a crear un SEGUNDO memorando.
            # Aun cuando se permite crear, se le dan 8 s (SGDEA lento): mejor
            # esperar que arriesgar un memorando duplicado.
            espera_ms = 8000 if crear_documento_si_hace_falta else 20000
            _log_paso(f"navegar_a_caso({radicado!r}): click en 'Ver documentos' (hasta {espera_ms // 1000} s)...")
            try:
                await icono_ver_documentos.first.click(timeout=espera_ms)
                await page.wait_for_timeout(1000)
                if not crear_documento_si_hace_falta:
                    await page.locator(IFRAME_DOCUMENTOS).wait_for(state="attached", timeout=20000)
            except Exception:
                pass  # no clickeable rapido -- se asume sin documento, sigue abajo


async def _crear_documento_si_hace_falta(page, radicado: str, crear_documento_si_hace_falta: bool) -> None:
    if not await page.locator(IFRAME_DOCUMENTOS).count() and crear_documento_si_hace_falta:
        icono_crear = page.locator('[data-original-title="Crear documento"]')
        if not await icono_crear.count():
            raise AutomatizacionError(
                f"El caso {radicado!r} no tiene 'Ver documentos' ni se "
                "encontro el icono 'Crear documento' -- revisar "
                "manualmente en que pantalla quedo."
                + await _diagnostico_pagina(page)
            )

        # CORRECCION (sesion 2026-09-27, evidencia DIRECTA: la captura
        # anotada de Andres del caso real 2026-IE-036192, re-leida pixel a
        # pixel). La version del 2026-09-25 buscaba
        # [data-original-title="Memorando respuesta"] asumiendo que era OTRO
        # icono de la barra -- eso fue una suposicion, y fallo en vivo (el
        # log de las 15:05 lo registra: "no aparecio el icono 'Memorando
        # respuesta'"). Lo que la captura muestra en realidad: al hacer
        # click en el icono "Crear documento" (el 2do de la barra, la hoja)
        # se despliega DEBAJO de ese mismo icono un pequeño MENU con un
        # item de TEXTO VISIBLE "Memorando respuesta" (resaltado en
        # amarillo en la captura). Es texto normal del DOM, no un tooltip
        # -- por eso se ubica por texto visible exacto, y solo entre los
        # elementos VISIBLES (el mismo texto puede existir oculto en otras
        # partes del DOM de SGDEA).
        item_memorando = page.get_by_text("Memorando respuesta", exact=True)

        # Chequeo de estado ANTES de actuar: el icono es un toggle de
        # desplegable -- si el menu ya esta abierto (p.ej. por un click
        # previo), otro click lo CERRARIA. Solo se hace click si el item
        # todavia no esta visible.
        item_visible = await _primer_visible(item_memorando, timeout_ms=300)
        if item_visible is None:
            _log_paso(f"navegar_a_caso({radicado!r}): sin documento todavia, click en 'Crear documento' (abre el desplegable)...")
            await icono_crear.first.click()
            item_visible = await _primer_visible(item_memorando, timeout_ms=8000)
        if item_visible is None:
            raise AutomatizacionError(
                f"Se hizo click en 'Crear documento' del caso {radicado!r} "
                "pero no aparecio el item 'Memorando respuesta' del "
                "desplegable (se espero 8s). No se crea nada a ciegas."
                + await _diagnostico_pagina(page)
            )

        _log_paso(f"navegar_a_caso({radicado!r}): click en 'Memorando respuesta' del desplegable...")
        await item_visible.click()

        # Segunda captura de Andres (misma sesion): modal "Este documento
        # finaliza la gestión?" con radios Si/No ('Si' marcado por
        # defecto) y botones Cancelar / Guardar. Se ubica por el TEXTO de
        # la pregunta (no por #TMSDialogModalDialog, que para este modal no
        # esta confirmado) y el contenedor se define como el ancestro MAS
        # CERCANO de la pregunta que ademas contiene un 'Guardar' -- asi el
        # boton queda acotado a ESTE modal y nunca se confunde con otro
        # 'Guardar' de la pagina (ver advertencia al inicio del modulo).
        # La version anterior tomaba el primer <div> ancestro de la
        # pregunta, que es solo la cabecera del modal (el 'Guardar' vive en
        # el pie) -- ese respaldo nunca habria encontrado el boton.
        pregunta = await _primer_visible(
            page.get_by_text(re.compile(r"finaliza la gesti", re.IGNORECASE)),
            timeout_ms=8000,
        )
        if pregunta is None:
            raise AutomatizacionError(
                f"Se eligio 'Memorando respuesta' en el caso {radicado!r} "
                "pero no aparecio el modal 'Este documento finaliza la "
                "gestión?' (se espero 8s)."
                + await _diagnostico_pagina(page)
            )
        contenedor = pregunta.locator(
            "xpath=ancestor::*[.//*[normalize-space(text())='Guardar']][1]"
        )
        if not await contenedor.count():
            raise AutomatizacionError(
                "Aparecio el modal 'finaliza la gestión' pero no se "
                "encontro un 'Guardar' dentro de el -- revisar manualmente."
                + await _diagnostico_pagina(page)
            )

        # Verificacion de estado ANTES de guardar: Andres pidio dejar 'Si'
        # marcado. Si por cualquier motivo el radio marcado no es 'Si', se
        # detiene -- nunca se cambia una decision del modal por su cuenta.
        estado_radio = await contenedor.first.evaluate(
            """(root) => {
                const radios = [...root.querySelectorAll('input[type=radio]')];
                const m = radios.find(r => r.checked);
                if (!m) return {n: radios.length, marcado: null};
                let txt = '';
                if (m.id) {
                    const l = root.querySelector('label[for="' + CSS.escape(m.id) + '"]');
                    if (l) txt = l.innerText;
                }
                if (!txt && m.closest('label')) txt = m.closest('label').innerText;
                if (!txt && m.nextSibling) txt = m.nextSibling.textContent || '';
                return {n: radios.length, marcado: (txt || '').trim(), valor: m.value || ''};
            }"""
        )
        marcado = (estado_radio.get("marcado") or "").strip().lower()
        marcado_sin_tilde = marcado.replace("í", "i")
        if not estado_radio.get("n"):
            raise AutomatizacionError(
                "El modal 'finaliza la gestión' no tiene radios Si/No "
                "localizables -- no se guarda a ciegas."
            )
        if not marcado_sin_tilde.startswith("si"):
            raise AutomatizacionError(
                "En el modal 'finaliza la gestión' la opcion marcada no es "
                f"'Si' (marcado: {estado_radio.get('marcado')!r}) -- no se "
                "cambia por cuenta propia; revisar manualmente."
            )

        boton_guardar_modal = await _primer_visible(
            contenedor.first.get_by_text("Guardar", exact=True), timeout_ms=2000
        )
        if boton_guardar_modal is None:
            raise AutomatizacionError(
                "Se encontro el modal 'finaliza la gestión' pero su boton "
                "'Guardar' no esta visible -- revisar manualmente."
            )
        _log_paso(
            f"navegar_a_caso({radicado!r}): confirmando modal 'finaliza la "
            "gestión' (Guardar, 'Si' verificado como marcado)..."
        )
        await boton_guardar_modal.click()

        # A partir de aqui el documento YA quedo creado en SGDEA. Se le da
        # mas margen (20s) al editor para montarse: SGDEA es lento, y un
        # fallo aqui NO debe llevar a reintentar la creacion.
        try:
            await page.locator(IFRAME_DOCUMENTOS).wait_for(state="attached", timeout=20000)
        except Exception:
            raise AutomatizacionError(
                f"Se confirmo la creacion del 'Memorando respuesta' del caso "
                f"{radicado!r}, pero el editor (#frameVerDocumentos) no se "
                "monto en 20s. OJO: el documento probablemente YA EXISTE en "
                "SGDEA -- NO volver a pulsar 'Gestionar caso completo' sin "
                "revisar primero (la proxima corrida deberia entrar por "
                "'Ver documentos' en vez de crear otro)."
                + await _diagnostico_pagina(page)
            ) from None

    if not await page.locator(IFRAME_DOCUMENTOS).count():
        raise AutomatizacionError(
            f"Se abrio el caso {radicado!r} pero no se llego a la vista "
            "'Ver documentos' (no aparece #frameVerDocumentos)"
            + (" y no se pidio crear el documento." if not crear_documento_si_hace_falta else ".")
            + await _diagnostico_pagina(page)
        )
    await _esperar_editor_listo(page, radicado)
    _log_paso(f"navegar_a_caso({radicado!r}): OK, editor completo (columna de iconos visible).")


# ------------------------------------------------------------------
# Descarga de la peticion en PDF -- vive en el panel "Expediente" de la
# pagina de aterrizaje del caso (ver _abrir_caso_landing), ANTES de
# entrar a "Ver documentos". Pensada para alimentar
# backend.sgdea_peticion.leer_peticion() con un archivo local, que es lo
# unico que le faltaba a ese modulo (destinatario/anexos ya se extraen
# de un PDF local desde hace tiempo).
#
# ***ADVERTENCIA -- A DIFERENCIA de navegar_a_caso()/_abrir_caso_landing()
# (confirmadas en vivo), ESTA FUNCION NO SE HA PROBADO EN VIVO todavia.***
# Se escribio a partir de la captura de pantalla que Andres compartio
# (caso real 2026-IE-035296, panel "Expediente" con la fila
# "2026-IE-035296-Comunicacion interna - Memorando - inicial-XXXXXXXX.pdf"
# circulada en rojo), pero el comportamiento real del click sobre esa
# fila (descarga nativa del navegador vs. nueva pestaña/visor de PDF) NO
# esta confirmado contra el DOM real. Por eso prueba DOS rutas distintas
# de deteccion, en orden, y lanza AutomatizacionError con un mensaje
# especifico si ninguna funciona -- nunca adivina ni devuelve una ruta
# que no se pudo confirmar que existe con contenido. La PRIMERA corrida
# real de esta funcion debe hacerse con Andres mirando la pantalla,
# listo para confirmar (o corregir) estos selectores contra un caso real.
# ------------------------------------------------------------------

PATRON_ARCHIVO_PDF = re.compile(r"\.pdf\s*$", re.IGNORECASE)
# Heuristica NO CONFIRMADA para distinguir la peticion original de otros
# PDFs que puedan aparecer en "Expediente" (p.ej. anexos que el propio
# ciudadano adjunto a su solicitud): en el unico caso real visto hasta
# ahora, el nombre de archivo de la peticion incluye la palabra
# "inicial". Si en algun caso real esto no alcanza para distinguirla
# (mas de un PDF con "inicial", o la peticion sin esa palabra), la
# funcion se detiene y pide revision manual en vez de adivinar.
TEXTO_HEURISTICA_PETICION = "inicial"


async def descargar_peticion_caso(page, radicado: str, carpeta_destino: str) -> str:
    """Abre el caso `radicado` (pagina de aterrizaje, panel 'Expediente')
    y descarga a disco, dentro de `carpeta_destino`, el PDF de la
    peticion original que dio origen al caso. Devuelve la ruta local del
    PDF descargado.

    Identifica la fila del PDF de la peticion asi: si en 'Expediente'
    hay exactamente un archivo .pdf listado, usa ese; si hay varios,
    exige que la heuristica de TEXTO_HEURISTICA_PETICION deje un UNICO
    candidato; en cualquier otro caso (cero candidatos, o varios incluso
    despues de la heuristica) lanza AutomatizacionError en vez de
    adivinar cual PDF es la peticion.

    Ver la advertencia arriba de este bloque: NO CONFIRMADO EN VIVO."""
    await _abrir_caso_landing(page, radicado)

    if not await page.get_by_text("Expediente").count():
        raise AutomatizacionError(
            f"Se abrio el caso {radicado!r} pero no se encontro el panel "
            "'Expediente' en la pagina de aterrizaje -- revisar "
            "manualmente en que pantalla quedo (puede que el click en "
            "'button.gestion' haya llevado directo a 'Ver documentos' en "
            "vez de a esta pagina de detalle, por ejemplo si este caso ya "
            "tenia un documento creado)."
        )

    # CORRECCION (confirmado en vivo, sesion 2026-09-25, caso real
    # 2026-IE-036117, con la sesion PROPIA de SGDEA -- sgdea_client):
    # el panel 'Expediente' ya esta en el DOM (por eso el chequeo de
    # arriba de "Expediente" pasa), pero sus FILAS de archivos se
    # terminan de poblar un poco despues, por una llamada aparte -- en
    # corridas normales el wait_for_timeout(1200) del final de
    # _abrir_caso_landing alcanza a cubrirlo, pero se vio en vivo, mas
    # de una vez seguida contra el mismo caso con datos ya confirmados
    # (Expediente con 2 documentos reales), que filas_pdf.count() daba 0
    # justo despues de abrir el caso, y en un reintento inmediato SI
    # aparecian. Por eso aqui se sondea (poll) hasta ~6s en vez de
    # confiar en un unico conteo inmediato -- esto NO adivina contenido,
    # solo le da tiempo real al DOM que ya sabemos que existe (Andres
    # confirmo visualmente el Expediente con sus 2 PDFs) antes de
    # concluir que no hay nada.
    filas_pdf = page.get_by_text(PATRON_ARCHIVO_PDF)
    total_candidatos = await filas_pdf.count()
    if total_candidatos == 0:
        for _ in range(6):
            await page.wait_for_timeout(1000)
            total_candidatos = await filas_pdf.count()
            if total_candidatos:
                break
    if total_candidatos == 0:
        raise AutomatizacionError(
            f"No se encontro ningun archivo .pdf listado en el panel "
            f"'Expediente' del caso {radicado!r} (se espero ~6s adicionales "
            "por si el panel tardaba en poblarse) -- revisar manualmente "
            "si la peticion esta realmente adjunta ahi."
        )

    if total_candidatos == 1:
        elegido = filas_pdf.first
    else:
        con_heuristica = filas_pdf.filter(
            has_text=re.compile(TEXTO_HEURISTICA_PETICION, re.IGNORECASE)
        )
        n_heuristica = await con_heuristica.count()
        if n_heuristica != 1:
            raise AutomatizacionError(
                f"Se encontraron {total_candidatos} archivos .pdf en el "
                f"panel 'Expediente' del caso {radicado!r} y no se pudo "
                "distinguir cual es la peticion original (la heuristica "
                f"'{TEXTO_HEURISTICA_PETICION}' encontro {n_heuristica}, "
                "se necesita exactamente 1) -- revisar manualmente cual "
                "archivo es la peticion y ajustar esta funcion antes de "
                "continuar."
            )
        elegido = con_heuristica.first

    texto_fila = ((await elegido.inner_text()) or "").strip()
    nombre_archivo = texto_fila.splitlines()[-1].strip() if texto_fila else ""
    if not nombre_archivo.lower().endswith(".pdf"):
        nombre_archivo = f"{radicado}-peticion.pdf"

    destino = Path(carpeta_destino)
    destino.mkdir(parents=True, exist_ok=True)
    ruta_local = destino / nombre_archivo

    # --- Via 1: descarga nativa del navegador ---
    descarga_nativa_ok = False
    try:
        async with page.expect_download(timeout=8000) as info_descarga:
            await elegido.click()
        descarga = await info_descarga.value
        await descarga.save_as(str(ruta_local))
        descarga_nativa_ok = True
    except Exception:
        descarga_nativa_ok = False

    if descarga_nativa_ok and ruta_local.exists() and ruta_local.stat().st_size > 0:
        return str(ruta_local)

    # --- Via 2: el click abrio una pestaña/visor nuevo en vez de descargar ---
    #
    # CORRECCION (confirmado en vivo, sesion 2026-09-25, caso real
    # 2026-IE-036105): esta via SI se ejecuta (el click abre una pestaña
    # nueva), pero esa pestaña es el visor HTML propio de SGDEA ("Ver
    # PDF", con un <iframe> que renderiza el archivo) -- pagina_pdf.url
    # es la URL de ESE VISOR, no del PDF en si. Descargar esa URL por
    # HTTP (como hacia antes esta funcion) guardaba el HTML del visor
    # con extension .pdf en vez del PDF real -- confirmado inspeccionando
    # el archivo guardado para el caso 2026-IE-036105: era HTML puro
    # ("<!DOCTYPE html>...<title>Ver PDF</title>..."), pdfplumber ni
    # siquiera podia abrirlo ("No /Root object! - Is this really a
    # PDF?"). Ese mismo HTML del visor SI trae, en su propio marcado, el
    # link real de descarga del binario:
    #   <a href="/TMS.Solution.MENGESDOC/.../GestorArchivo/Obtener/<guid>"
    #      title="<nombre-del-archivo>.pdf">
    # (hay tambien un <iframe src=".../GestorArchivo/Renderizar/<guid>">
    # con el mismo guid, para visualizacion en linea -- se prefiere
    # "Obtener" por su nombre, que sugiere descarga directa). Por eso
    # aqui se busca primero ese link dentro de la pestaña-visor; solo si
    # no aparece se usa la URL de la pestaña misma como ultimo recurso
    # (y la verificacion de firma '%PDF' de mas abajo evita guardar HTML
    # aunque este fallback tambien falle).
    # OJO -- pagina_pdf se declara ANTES del try y se cierra en un
    # `finally` (confirmado en vivo, sesion 2026-09-25: en la version
    # anterior el `await pagina_pdf.close()` vivia al final del bloque
    # `try`, asi que si algo fallaba DESPUES de abrir la pestaña-visor
    # pero ANTES de esa linea -- p.ej. wait_for_load_state() con timeout,
    # o el link_obtener.get_attribute() -- la pestaña quedaba abierta
    # para siempre en el Chrome de depuracion remota compartido. Como
    # esta funcion se llama una vez POR CASO -- incluida la gestion
    # automatica en segundo plano, que recorre muchos casos seguidos --
    # cada error dejaba una pestaña huerfana mas, acumulando memoria/
    # pestañas durante el dia. Cerrarla en `finally` la cierra siempre,
    # haya ido bien o mal, sin cambiar el mensaje de error que ve Andres.
    pagina_pdf = None
    try:
        async with page.context.expect_page(timeout=8000) as info_pagina:
            await elegido.click()
        pagina_pdf = await info_pagina.value
        await pagina_pdf.wait_for_load_state("load", timeout=8000)

        link_obtener = pagina_pdf.locator('a[href*="GestorArchivo/Obtener/"]')
        if await link_obtener.count():
            href = await link_obtener.first.get_attribute("href")
            url_pdf = urljoin(pagina_pdf.url, href) if href else pagina_pdf.url
        else:
            url_pdf = pagina_pdf.url
    except Exception as exc:
        raise AutomatizacionError(
            f"No se pudo descargar el PDF de la peticion del caso "
            f"{radicado!r} ({nombre_archivo}): el click sobre el archivo "
            "no disparo una descarga nativa NI abrio una pestaña/visor "
            f"nuevo detectable (ultimo error: {type(exc).__name__}: "
            f"{exc}). Hay que revisar en vivo, con Andres mirando la "
            "pantalla, que pasa realmente al hacer click en ese archivo "
            "dentro del panel 'Expediente', y ajustar esta funcion contra "
            "el comportamiento real."
        )
    finally:
        if pagina_pdf is not None and not pagina_pdf.is_closed():
            try:
                await pagina_pdf.close()
            except Exception:
                pass  # best-effort -- nunca tapar el error real de arriba por esto

    if not url_pdf or not url_pdf.lower().startswith("http"):
        raise AutomatizacionError(
            f"Se abrio una pestaña nueva al hacer click en el PDF de la "
            f"peticion del caso {radicado!r} pero su URL ({url_pdf!r}) no "
            "parece un enlace HTTP descargable -- revisar manualmente."
        )

    respuesta = await page.context.request.get(url_pdf)
    if not respuesta.ok:
        raise AutomatizacionError(
            f"Se obtuvo la URL del PDF de la peticion del caso "
            f"{radicado!r} ({url_pdf}) pero la descarga por HTTP fallo "
            f"(status {respuesta.status})."
        )
    contenido = await respuesta.body()
    if not contenido:
        raise AutomatizacionError(
            f"La descarga por HTTP del PDF de la peticion del caso "
            f"{radicado!r} ({url_pdf}) devolvio un cuerpo vacio -- no se "
            "guarda un archivo que no se pudo confirmar que tiene "
            "contenido."
        )
    # Verificacion de firma '%PDF' (confirmado en vivo, sesion 2026-09-25:
    # esta via YA devolvio una vez HTML del visor en vez del PDF real, ver
    # correccion arriba) -- nunca se guarda con extension .pdf algo que no
    # es realmente un PDF, aunque la descarga HTTP en si haya sido "ok".
    if not contenido[:5].startswith(b"%PDF"):
        raise AutomatizacionError(
            f"La descarga del PDF de la peticion del caso {radicado!r} "
            f"({url_pdf}) no empieza con la firma '%PDF' -- no es un PDF "
            "real (probablemente se descargo por error la pagina "
            "visor/HTML en vez del archivo). No se guarda -- revisar "
            "manualmente el enlace de descarga real en esa pestaña."
        )
    ruta_local.write_bytes(contenido)
    if not ruta_local.exists() or ruta_local.stat().st_size == 0:
        raise AutomatizacionError(
            f"Se descargo el PDF de la peticion del caso {radicado!r} "
            f"por HTTP pero el archivo guardado en {ruta_local} quedo "
            "vacio o no se creo."
        )
    return str(ruta_local)


# ------------------------------------------------------------------
# Deteccion de casos nuevos (solo lectura) -- para alimentar el Dashboard.
# Reutiliza el mismo bloque "Gestionar" y el mismo patron de click por
# coordenada fija ya confirmados en navegar_a_caso() -- lo unico nuevo es
# LEER las filas de la grilla en vez de buscar una en particular.
#
# ***ADVERTENCIA -- A DIFERENCIA de navegar_a_caso() (que si se confirmo
# en vivo), la extraccion de columnas de esta funcion (fecha, asunto,
# tipo) NO esta confirmada contra el DOM real todavia.*** Solo el
# radicado (via el id `chkSol{radicado}-1`, igual que en navegar_a_caso)
# es un dato confirmado. El resto de columnas se extrae de forma
# generica (todo el texto visible de cada <td> de la fila, en orden) en
# vez de adivinar nombres de columna -- para no inventar un mapeo que
# despues resulte incorrecto. La primera corrida real debe hacerse con
# Andres mirando la pantalla, para confirmar cual posicion de columna
# corresponde a que dato y, si hace falta, ajustar esta funcion para
# devolver campos con nombre en vez de la lista cruda `columnas`.
# ------------------------------------------------------------------

PATRON_RADICADO_DESDE_CHECKBOX = re.compile(r"^chkSol(.+)-1$")


async def listar_casos_gestionar(page) -> list[dict]:
    """Lee (SIN modificar nada) todas las filas actualmente visibles en la
    lista 'Gestionar' del dashboard de Inicio -- abre el bloque si hace
    falta (mismo click por coordenada fija que navegar_a_caso), pero
    NUNCA hace click en ninguna fila ni boton de gestion.

    Devuelve una lista de dicts `{"radicado": str, "columnas": list[str]}`
    -- `radicado` sale del id confirmado `chkSol{radicado}-1`; `columnas`
    es el texto crudo de cada <td> de esa fila, en el orden en que
    aparecen en el DOM (ver advertencia arriba: el mapeo columna->campo
    todavia no esta confirmado en vivo).

    Lanza AutomatizacionError si la sesion parece expirada (login) o si
    no se encuentra la grilla -- nunca devuelve una lista vacia como si
    fuera un resultado valido cuando en realidad algo fallo."""
    if await _pagina_parece_login(page):
        raise AutomatizacionError(
            "La sesion de SGDEA parece haber expirado (se ve la pantalla "
            "de login). No se toca -- Andres debe iniciar sesion el "
            "mismo antes de reintentar."
        )

    # CORRECCION (sesion 2026-09-25): antes solo se chequeaba
    # busqueda.count() (existe en el DOM), no si esta VISIBLE -- si el
    # bloque 'Gestionar' estaba en el DOM pero plegado, esta funcion
    # seguia de largo hacia 'filas' y terminaba lanzando el mensaje
    # generico de 'no se encontro ninguna fila', que no explica la causa
    # real (panel plegado). Se usa _regresar_a_lista_gestionar() (en vez
    # de llamar directo a _asegurar_bloque_gestionar_abierto) por
    # consistencia con _abrir_caso_landing() -- misma logica DRY: revisa
    # el estado real (ya visible / breadcrumb 'Memorando' / dashboard) y
    # decide la ruta correcta; _asegurar_bloque_gestionar_abierto() sigue
    # siendo la UNICA que toca COORDENADA_BLOQUE_GESTIONAR, como ultimo
    # recurso (ver su docstring: clickear a ciegas un bloque ya abierto lo
    # pliega en vez de abrirlo).
    token_log = _CONTEXTO_LOG.set("listar_casos_gestionar")
    try:
        _log_paso("inicio (lectura de la lista 'Gestionar', solo lectura)...")
        await _regresar_a_lista_gestionar(page)
        # Filtro previo, carga lenta y paginacion: ver _leer_bandeja_completa.
        resultado = await _leer_bandeja_completa(page)
        return resultado
    finally:
        _CONTEXTO_LOG.reset(token_log)


# ------------------------------------------------------------------
# Lectura COMPLETA de la grilla 'Gestionar' (v1.4.2).
#
# Evidencia (insignia_run.log del exe, 28-sep 08:31-08:33):
#   grilla: {'total': 0, 'filas_por_pagina_antes': 50, 'paginas_antes': 0,
#            'filas_por_pagina_ahora': -1, 'server_side': True}
# La grilla es jQuery DataTables en modo SERVIDOR (cada pagina la trae
# SGDEA por AJAX) y la v1.4.1 la leyo 2 s despues de abrirla, cuando aun no
# habia llegado la primera respuesta (0 registros), y le pidio "todas las
# filas" (largo -1). El servidor de SGDEA no devolvio nada con largo -1 y
# la grilla quedo vacia -- tambien en la segunda lectura (08:33:27), que
# encontro el largo -1 que habia dejado la primera. Con la v1.4.0 (sin
# tocar la grilla) esa misma pantalla SI mostraba sus filas.
#
# Por eso ahora: (1) se espera a que la grilla termine su carga inicial;
# (2) si quedo con largo -1 se restaura su largo original; (3) se quita el
# filtro 'Buscar:' que haya dejado el ultimo caso abierto; (4) se recorre
# pagina por pagina con el paginador de la PROPIA grilla (mismo pedido que
# hace el boton "Siguiente"), nunca con largo -1; (5) se comprueba que las
# filas leidas coincidan con el total que informa SGDEA.
# ------------------------------------------------------------------

_JS_GRILLA_GESTIONAR = r"""async ({accion, pagina, largo}) => {
    const $ = window.jQuery;
    if (!$ || !$.fn || !$.fn.dataTable) return {api: false, motivo: 'sin jQuery DataTables'};
    const visible = (el) => !!el && el.offsetParent !== null;
    const nodos = Array.from($.fn.dataTable.tables());
    let nodo = nodos.find(n => visible(n) && n.querySelector('[id^="chkSol"]'));
    if (!nodo) {
        // Grilla aun vacia: la que comparte contenedor con la caja 'Buscar:' visible.
        for (const caja of document.querySelectorAll('input.form-control.form-control-sm')) {
            if (!visible(caja)) continue;
            const w = caja.closest('.dataTables_wrapper');
            const t = w && w.querySelector('table');
            if (t && $.fn.dataTable.isDataTable(t)) { nodo = t; break; }
        }
    }
    if (!nodo) return {api: false, motivo: 'no se identifico la grilla Gestionar', tablas: nodos.length};
    const dt = $(nodo).DataTable();
    const esperarDibujo = (accionar) => new Promise(res => {
        const t = setTimeout(() => res(false), 30000);
        $(nodo).one('draw.dt', () => { clearTimeout(t); res(true); });
        accionar();
    });
    let dibujo = null;
    if (accion === 'reparar_largo') dibujo = await esperarDibujo(() => dt.page.len(largo).draw());
    else if (accion === 'limpiar_busqueda') dibujo = await esperarDibujo(() => { dt.search(''); dt.columns().search(''); dt.draw(); });
    else if (accion === 'ir_a_pagina') dibujo = await esperarDibujo(() => dt.page(pagina).draw('page'));
    const i = dt.page.info();
    let largoInicial = null, json = null;
    try { largoInicial = (dt.init() || {}).pageLength ?? null; } catch (e) {}
    try { json = dt.ajax.json(); } catch (e) {}
    const proc = nodo.closest('.dataTables_wrapper') && nodo.closest('.dataTables_wrapper').querySelector('.dataTables_processing');
    return {api: true, dibujo: dibujo, server_side: !!i.serverSide, largo: i.length, largo_inicial: largoInicial,
            pagina: i.page, paginas: i.pages, total: i.recordsTotal, total_filtrado: i.recordsDisplay,
            busqueda: dt.search() || '', respuesta_recibida: json !== undefined && json !== null,
            procesando: !!(proc && visible(proc)),
            filas_dom: Array.from(nodo.querySelectorAll('[id^="chkSol"]')).filter(visible).length};
}"""

# Evidencia (log 28-sep 08:31:50): largo original de la grilla 'Gestionar'.
LARGO_PAGINA_GRILLA_RESPALDO = 50
TIMEOUT_CARGA_LISTA_SEG = 25
MAX_PAGINAS_GRILLA = 200


async def _grilla_gestionar(page, accion: str = "estado", **kw) -> dict:
    try:
        return await page.evaluate(_JS_GRILLA_GESTIONAR, {"accion": accion, "pagina": kw.get("pagina"), "largo": kw.get("largo")})
    except Exception as exc:
        return {"api": False, "motivo": f"error: {exc}"}


_JS_FILAS_VISIBLES = """els => els.filter(tr => tr.offsetParent !== null).map(tr => {
    const chk = tr.querySelector('[id^="chkSol"]');
    return {id: chk ? chk.id : '', columnas: Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').trim())};
})"""


async def _leer_filas_visibles(page) -> list[dict]:
    """Filas VISIBLES de la grilla (una sola llamada al navegador). Las filas
    ocultas de filtros anteriores se ignoran (ver _abrir_caso_landing)."""
    crudas = await page.locator("tr").filter(has=page.locator('[id^="chkSol"]')).evaluate_all(_JS_FILAS_VISIBLES)
    resultado = []
    for f in crudas:
        m = PATRON_RADICADO_DESDE_CHECKBOX.match(f.get("id") or "")
        if m:  # fila sin patron reconocible -- se ignora, no se adivina
            resultado.append({"radicado": m.group(1), "columnas": f.get("columnas") or []})
    return resultado


async def _esperar_carga_grilla(page) -> dict:
    """Espera (hasta TIMEOUT_CARGA_LISTA_SEG) a que la grilla termine su
    carga inicial: filas visibles, o respuesta de SGDEA que diga 0 casos.
    Repara de paso el largo -1 que dejo la v1.4.1."""
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    reparado = False
    est: dict = {}
    while True:
        est = await _grilla_gestionar(page)
        filas_dom = est.get("filas_dom") if est.get("api") else len(await _leer_filas_visibles(page))
        if est.get("api") and est.get("largo") == -1 and not reparado:
            li = est.get("largo_inicial")
            largo = li if isinstance(li, int) and li > 0 else LARGO_PAGINA_GRILLA_RESPALDO
            _log_paso(f"la grilla quedo en 'todas las filas' (largo -1, lo dejo la v1.4.1) -- restaurando largo {largo}...")
            est = await _grilla_gestionar(page, "reparar_largo", largo=largo)
            reparado = True
            continue
        if filas_dom:
            break
        if est.get("api") and not est.get("procesando") and est.get("respuesta_recibida") and est.get("total_filtrado") == 0:
            break  # SGDEA ya respondio: 0 casos con el filtro actual
        if loop.time() - t0 > TIMEOUT_CARGA_LISTA_SEG:
            break
        await asyncio.sleep(0.4)
    est["espera_carga_s"] = round(loop.time() - t0, 1)
    return est


async def _leer_bandeja_completa(page) -> list[dict]:
    est = await _esperar_carga_grilla(page)
    _log_paso(f"grilla lista en {est.get('espera_carga_s')} s: {est!r}")

    if not est.get("api"):
        return await _leer_bandeja_sin_api(page)

    if est.get("busqueda"):
        _log_paso(f"quitando el filtro 'Buscar:' que dejo el ultimo caso abierto ({est['busqueda']!r})...")
        est = await _grilla_gestionar(page, "limpiar_busqueda")
        if not est.get("dibujo"):
            raise AutomatizacionError("SGDEA no respondio en 30 s al quitar el filtro de la lista 'Gestionar'.")

    total = est.get("total_filtrado") or 0
    if total == 0:
        if est.get("respuesta_recibida") or not est.get("server_side"):
            _log_paso("OK -- SGDEA informa 0 casos en la bandeja 'Gestionar'.")
            return []
        raise AutomatizacionError(
            f"La lista 'Gestionar' no termino de cargar en {TIMEOUT_CARGA_LISTA_SEG} s (SGDEA no respondio). "
            "Se reintenta en la proxima vuelta."
        )

    paginas = min(max(est.get("paginas") or 1, 1), MAX_PAGINAS_GRILLA)
    loop = asyncio.get_running_loop()
    leidos: dict[str, dict] = {}
    pagina_actual = est.get("pagina") or 0
    for p in range(paginas):
        t0 = loop.time()
        if p != pagina_actual:
            e = await _grilla_gestionar(page, "ir_a_pagina", pagina=p)
            if not e.get("dibujo"):
                raise AutomatizacionError(f"SGDEA no entrego la pagina {p + 1}/{paginas} de la lista 'Gestionar' en 30 s.")
            pagina_actual = p
        filas = await _leer_filas_visibles(page)
        for f in filas:
            leidos.setdefault(f["radicado"], f)
        _log_paso(f"pagina {p + 1}/{paginas}: {len(filas)} fila(s) en {loop.time() - t0:.1f} s")
    # No se regresa a la pagina 1: la siguiente busqueda por radicado ya
    # reinicia la grilla (y asi se ahorra un pedido a SGDEA).

    resultado = list(leidos.values())
    if len(resultado) != total:
        raise AutomatizacionError(
            f"La grilla 'Gestionar' informa {total} caso(s) pero se leyeron {len(resultado)} -- "
            "no se sigue con una lista incompleta."
        )
    _log_paso(f"OK -- {len(resultado)} caso(s) leidos en {paginas} pagina(s) (total informado por SGDEA: {total}).")
    return resultado


async def _leer_bandeja_sin_api(page) -> list[dict]:
    """Respaldo si la grilla no expone la API de DataTables: quita el filtro
    con teclado real y recorre el paginador con el boton 'Siguiente'."""
    busqueda = page.locator(SELECTOR_BUSQUEDA_GESTIONAR).first
    if await busqueda.count() and (await busqueda.input_value()).strip():
        _log_paso("limpiando el filtro 'Buscar:' que dejo el ultimo caso abierto...")
        await busqueda.click()
        await busqueda.fill("")
        await page.keyboard.press("Space")
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(1500)
    leidos: dict[str, dict] = {}
    siguiente = page.locator(".dataTables_paginate .next:not(.disabled), .pagination li.next:not(.disabled) a").first
    for p in range(MAX_PAGINAS_GRILLA):
        filas = await _leer_filas_visibles(page)
        for f in filas:
            leidos.setdefault(f["radicado"], f)
        if not (await siguiente.count() and await siguiente.is_visible()):
            break
        primero = filas[0]["radicado"] if filas else ""
        await siguiente.click()
        for _ in range(60):  # hasta 30 s a que cambie la pagina
            await page.wait_for_timeout(500)
            nuevas = await _leer_filas_visibles(page)
            if nuevas and nuevas[0]["radicado"] != primero:
                break
        else:
            raise AutomatizacionError("La lista 'Gestionar' no cambio de pagina en 30 s tras 'Siguiente'.")
    if not leidos:
        raise AutomatizacionError(
            "El cuadro 'Buscar:' de 'Gestionar' esta visible pero no aparecio ninguna fila "
            f"con checkbox 'chkSol...-1' en {TIMEOUT_CARGA_LISTA_SEG} s."
        )
    _log_paso(f"OK -- {len(leidos)} caso(s) leidos (sin API de la grilla, con el paginador).")
    return list(leidos.values())


async def detectar_casos_nuevos(page, radicados_conocidos: set[str]) -> list[dict]:
    """Igual que listar_casos_gestionar(), pero filtra y deja solo los
    casos cuyo radicado NO este en `radicados_conocidos` -- pensado para
    que el llamador (main.py / backend/dashboard.py) pase el conjunto de
    radicados que ya tiene registrados localmente (ver
    backend/dashboard.py: registrar_casos_detectados) y reciba de vuelta
    solo los realmente nuevos, listos para agregar a la cola del
    Dashboard. Solo lee -- nunca marca ni modifica nada en SGDEA."""
    todos = await listar_casos_gestionar(page)
    return [c for c in todos if c["radicado"] not in radicados_conocidos]


# ------------------------------------------------------------------
# Seleccion de revisor (modal "Revisores ciclo adHoc") -- confirmado en
# vivo, sesion 2026-09-22, caso 2026-IE-035142, para EMA CONSUELO CORONEL
# FUENTES.
# ------------------------------------------------------------------

ID_MODAL_GENERICO_TMS = "#TMSDialogModalDialog"
NOMBRE_REVISOR_EMA = "EMA CONSUELO CORONEL FUENTES"
TEXTO_BUSQUEDA_REVISOR_EMA = "ema c"


CARGO_REVISOR_EMA = "Profesional Especializado"
DEPENDENCIA_REVISOR_EMA = "Subdirección de Relacionamiento con la Ciudadanía"


async def seleccionar_revisor_ema(page) -> None:
    """Revisora EMA CONSUELO CORONEL FUENTES en "Revisores ciclo adHoc".

    Flujo tomado del video de Andres (25-sep, caso 2026-IE-035690, 4:52-5:20):
      icono 'Revisores ciclo adHoc' -> escribir 'ema c' -> clic en EMA (la
      grilla puede cambiar en el clic: se verifica la tarjeta 'Revisor:')
      -> Guardar -> aviso "Editor documental TMS! La información se guardó
      exitosamente" -> OK -> "Espere por favor" (~10 s) -> la cinta cambia
      'Solicitar aprobación' por 'Inicio ciclo de aprobación'.
    Esa cinta es la prueba de que quedo asignada."""
    frame = page.frame_locator(IFRAME_DOCUMENTOS)
    if await _primer_visible(frame.get_by_text(PATRON_BOTON_INICIO_CICLO), timeout_ms=0) is not None:
        _log_paso("seleccionar_revisor_ema: la cinta ya dice 'Inicio ciclo de aprobación' (revisora asignada) -- no se toca.")
        return
    for intento in (1, 2):
        try:
            await _revisor_una_vez(page, frame)
            break
        except _SeleccionEquivocada as exc:
            if intento == 2:
                raise
            _log_paso(f"seleccionar_revisor_ema: {exc} -- reintentando una vez...")
            await _esperar_sgdea_libre(page, "antes de reintentar la revisora")

    await _aceptar_aviso_guardado(page, max_s=30)
    await _esperar_sgdea_libre(page, "tras guardar la revisora")
    if await _primer_visible(frame.get_by_text(PATRON_BOTON_INICIO_CICLO), timeout_ms=60000) is None:
        raise AutomatizacionError(
            "Se guardo la revisora pero en 60 s la cinta no cambio a 'Inicio ciclo de aprobación' -- "
            "revisar el documento a mano."
        )
    _log_paso("seleccionar_revisor_ema: OK -- la cinta dice 'Inicio ciclo de aprobación'.")


async def _revisor_una_vez(page, frame) -> None:
    await _esperar_sgdea_libre(page, "antes de abrir 'Revisores ciclo adHoc'")
    icono = frame.locator('[data-original-title="Revisores ciclo adHoc"]')
    if await _primer_visible(icono, timeout_ms=15000) is None:
        raise AutomatizacionError(
            "No se encontro el icono 'Revisores ciclo adHoc' dentro de #frameVerDocumentos -- "
            "revisar si el documento esta realmente abierto en 'Ver documentos'."
        )
    await (await _primer_visible(icono, timeout_ms=0)).click()
    raiz, modal = await _modal_por_titulo(page, re.compile(r"Revisores\s+ciclo\s+adHoc", re.IGNORECASE), timeout_ms=30000)
    if modal is None:
        raise AutomatizacionError("Se hizo clic en 'Revisores ciclo adHoc' pero el modal no aparecio en 30 s.")
    try:
        ya = _personas_en_tarjetas(await modal.inner_text(), "Revisor")
        if ya:
            if any(_es_la_persona(n, NOMBRE_REVISOR_EMA) for n in ya) and len(ya) == 1:
                _log_paso(f"seleccionar_revisor_ema: el modal ya tiene a {ya!r} -- se guarda tal cual.")
            else:
                raise AutomatizacionError(
                    f"El documento ya tiene otro(s) revisor(es) {ya!r} -- no se cambia por cuenta propia; revisar a mano."
                )
        else:
            campo = await _campo_busqueda(modal, "Buscar revisor", "revisor")
            await _elegir_persona(raiz, modal, campo, TEXTO_BUSQUEDA_REVISOR_EMA, NOMBRE_REVISOR_EMA,
                                  CARGO_REVISOR_EMA, DEPENDENCIA_REVISOR_EMA, "Revisor")
        # El aviso de exito aparece al guardar: no se exige que el modal se
        # cierre solo (se valida despues con la cinta).
        boton = await _primer_visible(modal.get_by_role("button", name="Guardar", exact=True), timeout_ms=1500)
        if boton is None:
            boton = await _primer_visible(modal.get_by_text("Guardar", exact=True), timeout_ms=1500)
        if boton is None:
            raise AutomatizacionError("No se encontro el 'Guardar' del modal de revisores.")
        _log_paso("seleccionar_revisor_ema: click en 'Guardar' del modal...")
        await boton.click()
    except AutomatizacionError:
        await _cerrar_modal_sin_guardar(modal, "Revisores ciclo adHoc")
        raise


# ------------------------------------------------------------------
# Destinatario, Asunto y Saludo/Cuerpo -- REESCRITO (sesion 2026-09-27)
# con la evidencia DIRECTA de Andres: 6 capturas del flujo real sobre el
# caso 2026-IE-036192, paso a paso:
#   1. Modal "Destinatario Tipificación": campo "Buscar destinatario"
#      (label arriba del input) -> grilla "Seleccione los destinatarios a
#      asignar" con columnas Nombre / Cargo / Dependencia (puede haber
#      NOMBRES REPETIDOS con distinto cargo, p.ej. NOMBRE APELLIDO
#      TOVAR x2) -> al elegir una fila aparece bajo "Destinatarios
#      seleccionados" una tarjeta con: Título/Profesión (chip, p.ej.
#      "Doctora"), Destinatario, Dependencia, Tipo ("Memorando" ya puesto)
#      y Nivel 1 ("Seleccione" -> desplegable con la lista de categorias;
#      Andres elige SIEMPRE la categoria del caso, p.ej. SOLICITUDES
#      INTERNAS GENERALES). Con Nivel 1 elegido aparece "No existen más
#      niveles". Botones del pie: Cerrar / Guardar. Al Guardar, SGDEA
#      escribe en el documento el bloque "Para: ..." y "Eje temático: ...".
#   2. Modal "Asunto" (icono lapiz, 2do de la columna izquierda):
#      <textarea> con contador "35 / 200", botones Cerrar / Guardar. Al
#      Guardar, el documento muestra "Asunto:Respuesta a Radicado ...".
#   3. La plantilla del documento trae la linea "Saludo," y, mas abajo,
#      "Cordialmente," (captura con los campos aplicados). La carta
#      aprobada dice "Cordial Saludo, Doctora <Nombre>:" (ver
#      backend/sgdea_carta.py) -- o sea: a "Saludo," se le agrega
#      "Cordial " antes y " Doctora <Nombre>:" despues.
# Los selectores de abajo se derivan de esas capturas: se ubican por el
# TEXTO VISIBLE que muestran (etiquetas, titulos, botones), nunca por ids
# o clases inventados, y cada paso verifica el estado real antes y
# despues de actuar.
# ------------------------------------------------------------------

def _normalizar(texto: str) -> str:
    """Mayusculas, sin tildes, sin la 'x' de los chips y con espacios
    colapsados -- para comparar nombres de SGDEA ('HERNÁNDEZ') contra los
    de la peticion ('HERNANDEZ') sin falsos negativos."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return " ".join(t.replace("×", " ").upper().split())


def _raices_busqueda(page):
    """Donde buscar los modales: primero dentro de #frameVerDocumentos
    (confirmado para el modal de revisores, y las capturas muestran los
    modales dentro del area del editor), despues la pagina principal."""
    return [page.frame_locator(IFRAME_DOCUMENTOS), page]


async def _modal_por_titulo(page, patron_titulo, timeout_ms: int = 8000, boton: str = "Guardar"):
    """Devuelve (raiz, contenedor) del modal VISIBLE cuyo titulo calza con
    `patron_titulo`. El contenedor es el ancestro <div> mas cercano del
    titulo que ademas tiene un 'Guardar' VISIBLE -- asi todo lo que se busque
    despues (campos, opciones, el propio 'Guardar') queda acotado a ESE
    modal. Se busca primero dentro de #frameVerDocumentos durante todo el
    plazo (ahi viven los modales confirmados de este editor) y solo al
    final, brevemente, en la pagina principal."""
    async def _en(raiz, plazo_ms):
        loop = asyncio.get_running_loop()
        limite = loop.time() + plazo_ms / 1000
        while True:
            # Se revisan TODAS las coincidencias visibles (no solo la primera):
            # el tooltip del icono puede tener el mismo texto que el titulo
            # (p.ej. 'Anexo') y no pertenece a ningun modal.
            coincidencias = raiz.get_by_text(patron_titulo)
            try:
                n = await coincidencias.count()
            except Exception:
                n = 0
            for i in range(n):
                titulo = coincidencias.nth(i)
                try:
                    if not await titulo.is_visible():
                        continue
                except Exception:
                    continue
                cont = titulo.locator(f"xpath=ancestor::div[.//*[normalize-space(text())='{boton}']][1]")
                if await cont.count() and await _primer_visible(cont.first.get_by_text(boton, exact=True), timeout_ms=0) is not None:
                    return cont.first
            if n:
                generico = await _primer_visible(raiz.locator(ID_MODAL_GENERICO_TMS), timeout_ms=0)
                if generico is not None:
                    return generico
            if loop.time() >= limite:
                return None
            await asyncio.sleep(0.25)

    frame = page.frame_locator(IFRAME_DOCUMENTOS)
    cont = await _en(frame, timeout_ms)
    if cont is not None:
        return frame, cont
    cont = await _en(page, 1500)
    return (page, cont) if cont is not None else (None, None)


async def _despejar_capa_modal_editor(page) -> None:
    """Evidencia (log 28-sep 16:04, caso 2026-IE-035691): un
    <div class="dxmodalSys"> (capa de una ventana emergente del editor
    DevExpress) tapaba el icono 'Asunto' y el clic esperaba 30 s. Se espera a
    que se quite sola (hasta 10 s); si sigue, Escape; y se deja constancia del
    texto de la ventana que la produce."""
    # Aviso SweetAlert pendiente (su capa .sweet-overlay tapa todo el editor):
    # si es de exito se espera a que se cierre solo (o se pulsa OK); si NO lo
    # es, se detiene con su texto -- ese guardado anterior no se aplico.
    loop = asyncio.get_running_loop()
    limite_sweet = loop.time() + 8
    while True:
        aviso = await _leer_aviso_sweet(page)
        if not aviso:
            break
        if not _aviso_es_exito(aviso):
            await _cerrar_aviso_sweet(aviso)
            raise AutomatizacionError(
                f"SGDEA mostro un aviso que no es de exito: {aviso.get('titulo')!r} {aviso.get('texto')!r} "
                "-- el paso anterior pudo no guardarse; se reintenta verificando el documento."
            )
        if loop.time() >= limite_sweet:
            await _cerrar_aviso_sweet(aviso)
            _log_paso("aviso de exito de SGDEA seguia abierto -> OK.")
            break
        await asyncio.sleep(0.4)

    frame = page.frame_locator(IFRAME_DOCUMENTOS)
    capa = frame.locator(".dxmodalSys")
    limite = loop.time() + 10
    while loop.time() < limite:
        if await _primer_visible(capa, timeout_ms=0) is None:
            return
        await asyncio.sleep(0.5)
    texto = ""
    try:
        texto = " | ".join(await frame.locator(".dxpc-headerContent, .dxpc-header, .dxpcLite .dxpc-content").evaluate_all(
            "els => els.filter(e => e.offsetParent !== null).map(e => (e.innerText || '').trim()).filter(Boolean).slice(0, 3)"
        ))
    except Exception:
        pass
    _log_paso(f"capa modal del editor visible ({texto or 'sin titulo'}) -- se cierra con Escape.")
    await page.keyboard.press("Escape")
    await asyncio.sleep(1)
    if await _primer_visible(capa, timeout_ms=0) is not None:
        cerrar = await _primer_visible(frame.locator(".dxpc-closeBtn, .dxWeb_pcCloseButton"), timeout_ms=500)
        if cerrar is not None:
            await cerrar.click(timeout=3000)
            await asyncio.sleep(1)
    if await _primer_visible(capa, timeout_ms=0) is not None:
        raise AutomatizacionError(f"Una ventana del editor ({texto or 'sin titulo'}) tapa el documento y no se pudo cerrar.")


async def _click_icono_documento(page, titulo_icono: str) -> None:
    """Click en un icono de la columna izquierda del documento (dentro de
    #frameVerDocumentos), ubicado por su data-original-title."""
    await _despejar_capa_modal_editor(page)
    icono = await _primer_visible(
        page.frame_locator(IFRAME_DOCUMENTOS).locator(f'[data-original-title="{titulo_icono}"]'),
        timeout_ms=15000,
    )
    if icono is None:
        raise AutomatizacionError(
            f"No se encontro visible el icono '{titulo_icono}' en la columna "
            "izquierda del documento -- revisar que el documento este abierto."
            + await _diagnostico_pagina(page)
        )
    await icono.click(timeout=15000)


_JS_SWEET = r"""els => {
    const vis = e => e && e.getClientRects().length > 0 && getComputedStyle(e).display !== 'none'
        && getComputedStyle(e).visibility !== 'hidden' && parseFloat(getComputedStyle(e).opacity || '1') > 0.05;
    for (const el of els) {
        if (!vis(el)) continue;
        const icono = [...el.querySelectorAll('.sa-icon')].find(vis);
        const tipo = icono ? (['error', 'warning', 'info', 'success', 'custom'].find(t => icono.classList.contains('sa-' + t)) || '') : '';
        const h = el.querySelector('h2'), p = el.querySelector('p');
        return {tipo, titulo: ((h && h.innerText) || '').trim(), texto: ((p && p.innerText) || '').trim()};
    }
    return null;
}"""


async def _leer_aviso_sweet(page):
    """Aviso SweetAlert VISIBLE (dentro del editor o en la pagina): dict con
    tipo/titulo/texto, o None."""
    for raiz in _raices_busqueda(page):
        try:
            r = await raiz.locator(".sweet-alert").evaluate_all(_JS_SWEET)
        except Exception:
            r = None
        if r:
            r["raiz"] = raiz
            return r
    return None


def _aviso_es_exito(aviso: dict) -> bool:
    """Solo se da por bueno un aviso que DIGA que se guardo (o traiga el icono
    de exito). Cualquier otro (error, advertencia, texto desconocido) detiene
    el paso: nunca se adivina que el guardado funciono."""
    texto = _normalizar(f"{aviso.get('titulo', '')} {aviso.get('texto', '')}")
    return aviso.get("tipo") == "success" or any(p in texto for p in ("EXITOSAMENTE", "EXITOSA", "CORRECTAMENTE"))


async def _cerrar_aviso_sweet(aviso: dict) -> None:
    raiz = aviso.get("raiz")
    if raiz is None:
        return
    try:
        ok = await _primer_visible(raiz.locator(".sweet-alert button.confirm"), timeout_ms=1000)
        if ok is not None:
            await ok.click(timeout=3000)
    except Exception:
        pass


async def _revisar_aviso_tras_guardar(page, que: str, espera_s: float = 3.0) -> None:
    """Tras 'Guardar' en un modal: si SGDEA muestra un aviso que NO es de
    exito, se cierra y se detiene con su texto. Evidencia (log 28-sep 16:06,
    caso 2026-IE-036479): tras guardar el destinatario quedo un aviso
    SweetAlert (capa .sweet-overlay) que tapo el icono 'Asunto' 30 s; ese
    guardado no se aplico y el memorando llego a revision sin destinatario."""
    loop = asyncio.get_running_loop()
    limite = loop.time() + espera_s
    while loop.time() < limite:
        aviso = await _leer_aviso_sweet(page)
        if aviso:
            if _aviso_es_exito(aviso):
                return
            await _cerrar_aviso_sweet(aviso)
            raise AutomatizacionError(
                f"SGDEA no acepto el guardado de '{que}': aviso "
                f"{(aviso.get('titulo') + ' -- ' if aviso.get('titulo') else '')}{aviso.get('texto') or '(sin texto)'!r}"
                f" (tipo {aviso.get('tipo') or 'desconocido'})."
            )
        await asyncio.sleep(0.3)


async def _guardar_modal_y_esperar_cierre(page, modal, que: str, boton_texto: str = "Guardar",
                                         revisar_aviso: bool = True) -> None:
    """Pulsa el 'Guardar' DEL modal (nunca el del ribbon) y espera a que el
    modal se cierre. Si sigue abierto (p.ej. SGDEA mostro una validacion),
    se detiene con el texto visible del modal como diagnostico."""
    boton = await _primer_visible(modal.get_by_role("button", name=boton_texto, exact=True), timeout_ms=1500)
    if boton is None:
        boton = await _primer_visible(modal.get_by_text(boton_texto, exact=True), timeout_ms=1500)
    if boton is None:
        raise AutomatizacionError(f"No se encontro el boton '{boton_texto}' del modal '{que}'.")
    _log_paso(f"{que}: click en '{boton_texto}' del modal...")
    await boton.click()
    loop = asyncio.get_running_loop()
    limite = loop.time() + 12
    while loop.time() < limite:
        try:
            cerrado = not await modal.is_visible()
        except Exception:
            cerrado = True  # el modal se desmonto del DOM -- tambien es cierre
        if cerrado:
            _log_paso(f"{que}: modal cerrado tras Guardar.")
            if revisar_aviso:
                await _revisar_aviso_tras_guardar(page, que)
            return
        aviso = await _leer_aviso_sweet(page) if revisar_aviso else None
        if aviso and not _aviso_es_exito(aviso):
            await _cerrar_aviso_sweet(aviso)
            raise AutomatizacionError(
                f"SGDEA no acepto el guardado de '{que}': aviso {aviso.get('texto') or aviso.get('titulo')!r}."
            )
        await asyncio.sleep(0.3)
    texto = ""
    try:
        texto = " ".join((await modal.inner_text()).split())[:300]
    except Exception:
        pass
    raise AutomatizacionError(
        f"Se pulso '{boton_texto}' en el modal '{que}' pero no se cerro en 12s "
        f"(puede haber un campo obligatorio vacio). Texto del modal: {texto!r}"
    )


async def _fila_de_campo(modal, etiqueta: str):
    """Fila (label + control) de un campo de la tarjeta del destinatario,
    ubicada por el texto EXACTO de su etiqueta ('Tipo', 'Nivel 1',
    'Título/Profesión')."""
    lab = await _primer_visible(modal.get_by_text(etiqueta, exact=True), timeout_ms=8000)
    if lab is None:
        return None
    fila = lab.locator(
        "xpath=ancestor::*[.//select or .//input[not(@type='hidden')] or .//*[@role='combobox']"
        " or .//*[contains(@class,'select2')] or .//*[contains(@class,'chosen')]][1]"
    )
    return fila.first if await fila.count() else None


_JS_VALOR_FILA = """(r, etiqueta) => {
    const limpia = s => (s || '').replace(/\\u00d7/g, '').trim();
    // MagicSuggest (el control real de SGDEA, HTML visto en el log del 28-sep):
    // lo elegido queda como <div class="ms-sel-item">Doctora<span class="ms-close-btn">.
    const chips = [...r.querySelectorAll('.ms-sel-item, .select2-selection__choice, .chosen-choices .search-choice')]
        .map(e => limpia(e.getAttribute('title') || e.innerText)).filter(Boolean);
    if (chips.length) return chips.join(' | ');
    // MagicSuggest SIN chip = SIN valor, aunque la caja tenga texto escrito.
    // Evidencia (log 28-sep 16:06, caso 2026-IE-036479): se escribio
    // 'SOLICITUD DE INFORMACION DE RESOLUCIONES' en 'Nivel 1', no hubo lista
    // (esa opcion no existe para Memorando), Enter no creo chip y el texto de
    // la caja se tomo como valor elegido -> SGDEA no guardo el destinatario.
    if (r.querySelector('.ms-ctn')) return '';
    const s2 = r.querySelector('.select2-selection__rendered, .chosen-single span');
    if (s2) return limpia(s2.getAttribute('title') || s2.innerText);
    const sel = r.querySelector('select');
    if (sel && sel.selectedIndex >= 0 && sel.options[sel.selectedIndex]) return limpia(sel.options[sel.selectedIndex].text);
    // Con caja de texto, el valor ES lo que tenga la caja (vacia = sin valor).
    // Evidencia 28-sep: Título/Profesión es una caja "Diligencie por favor..."
    // con un boton de flecha al lado; leer el texto de la fila tomaba esa
    // flecha como si fuera un valor.
    const inp = r.querySelector('input:not([type=hidden])');
    if (inp) return limpia(inp.value);
    return limpia((r.innerText || '').replace(etiqueta, ''));
}"""


async def _valor_campo(fila, etiqueta: str) -> str:
    try:
        valor = await fila.evaluate(_JS_VALOR_FILA, etiqueta)
    except Exception:
        return ""
    return "" if _normalizar(valor) in ("", "SELECCIONE") else valor


# Opciones de un desplegable: SOLO las que aparecieron despues de abrirlo
# (se marcan las visibles antes del clic). Asi nunca se toma por opcion un
# texto igual que ya estaba en pantalla -- p.ej. el 'Memorando' del
# breadcrumb o el chip de un valor ya elegido.
_JS_OPCIONES = r"""(body, args) => {
    const doc = body.ownerDocument;
    const norm = s => (s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/\u00d7/g, ' ')
        .toUpperCase().split(/\s+/).filter(Boolean).join(' ');
    const vis = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
    const els = [...doc.querySelectorAll('.ms-res-item,[role=option],[role=treeitem],[role=menuitem],li,.dropdown-item,.tt-suggestion,.ui-menu-item-wrapper')];
    if (args.accion === 'marcar_previos') {
        doc.querySelectorAll('[data-insignia-previo]').forEach(e => e.removeAttribute('data-insignia-previo'));
        els.forEach(e => { if (vis(e)) e.setAttribute('data-insignia-previo', '1'); });
        return null;
    }
    doc.querySelectorAll('[data-insignia-opcion]').forEach(e => e.removeAttribute('data-insignia-opcion'));
    const nuevas = els.filter(e => vis(e) && !e.hasAttribute('data-insignia-previo') && !e.closest('.breadcrumb, nav')
        && !/\n/.test((e.innerText || '').trim()));
    const exacta = nuevas.find(e => norm(e.innerText) === args.objetivo);
    if (exacta) { exacta.setAttribute('data-insignia-opcion', '1'); return {ok: true}; }
    return {ok: false, visibles: nuevas.map(e => (e.innerText || '').trim()).filter(Boolean).slice(0, 20)};
}"""


async def _opciones_js(raiz, args: dict):
    try:
        return await raiz.locator("body").first.evaluate(_JS_OPCIONES, args)
    except Exception:
        return None


async def _esperar_opcion(raices, objetivo: str, segundos: float):
    """Busca la opcion en cada raiz (el desplegable puede quedar en la
    pagina principal aunque el modal este dentro del editor)."""
    loop = asyncio.get_running_loop()
    limite = loop.time() + segundos
    while True:
        for raiz in raices:
            r = await _opciones_js(raiz, {"accion": "buscar", "objetivo": objetivo})
            if r and r.get("ok"):
                return raiz.locator('[data-insignia-opcion="1"]').first
        if loop.time() >= limite:
            return None
        await asyncio.sleep(0.25)


async def _elegir_opcion_campo(raiz, modal, etiqueta: str, opcion: str, page=None) -> str:
    """Deja `opcion` elegida en el desplegable `etiqueta` de la tarjeta del
    destinatario, SOLO si hace falta (revisa el valor actual antes). Soporta
    <select> nativo o desplegable con busqueda (el de la captura: caja
    'Seleccione' + lista de opciones). Verifica el valor final. Devuelve
    'ya_estaba' o 'elegido'."""
    fila = await _fila_de_campo(modal, etiqueta)
    if fila is None:
        raise AutomatizacionError(f"No se encontro el campo '{etiqueta}' en la tarjeta del destinatario.")
    objetivo = _normalizar(opcion)
    actual = await _valor_campo(fila, etiqueta)
    if objetivo in [_normalizar(v) for v in actual.split("|")]:
        _log_paso(f"destinatario: '{etiqueta}' ya tiene {actual!r} -- no se toca.")
        return "ya_estaba"

    nativo = await _primer_visible(fila.locator("select"), timeout_ms=200)
    if nativo is not None:
        opciones = await nativo.evaluate("s => [...s.options].map(o => o.text)")
        elegidas = [o for o in opciones if _normalizar(o) == objetivo]
        if len(elegidas) != 1:
            raise AutomatizacionError(
                f"El desplegable '{etiqueta}' no tiene exactamente una opcion "
                f"{opcion!r} (opciones: {opciones[:15]!r})."
            )
        await nativo.select_option(label=elegidas[0])
    else:
        disparador = await _primer_visible(
            fila.locator(".ms-ctn input:not([type=hidden]), .ms-trigger, .select2-selection, .chosen-single, .chosen-choices, [role=combobox], .dropdown-toggle, input:not([type=hidden])"),
            timeout_ms=2000,
        )
        if disparador is None:
            raise AutomatizacionError(f"No se encontro como abrir el desplegable '{etiqueta}'.")
        raices = [raiz] + ([r for r in _raices_busqueda(page)] if page is not None else [])
        for r in raices:
            await _opciones_js(r, {"accion": "marcar_previos"})
        _log_paso(f"destinatario: abriendo desplegable '{etiqueta}'...")
        await disparador.click()
        item = await _esperar_opcion(raices, objetivo, 2.5)
        if item is None:
            # Evidencia (videos 25 y 28-sep): en Título/Profesión y Tipo se
            # ESCRIBE ('doctora' -> chip 'Doctora ×'). Se escribe con el
            # teclado real sobre el campo que quedo con el foco.
            caja = await _primer_visible(fila.locator(".ms-ctn input:not([type=hidden])"), timeout_ms=200)
            if caja is None:
                caja = await _primer_visible(raiz.locator(".select2-container--open .select2-search__field"), timeout_ms=200)
            if caja is None:
                caja = await _primer_visible(fila.locator("input:not([type=hidden])"), timeout_ms=200)
            _log_paso(f"destinatario: escribiendo {opcion!r} en '{etiqueta}'...")
            if caja is not None:
                await caja.click()
                await caja.fill("")
                await caja.type(opcion, delay=40)
            elif page is not None:
                await page.keyboard.type(opcion, delay=40)
            # La lista (p.ej. 'Doctor' / 'Doctora') la trae SGDEA despues de
            # escribir: se espera hasta 12 s a que aparezca y se hace CLIC en
            # la opcion exacta (asi lo hace Andres).
            item = await _esperar_opcion(raices, objetivo, 12)
            if item is None and page is not None:
                # Sin lista reconocible: Enter elige la opcion resaltada (como
                # lo hace Andres). Solo si el foco sigue en ESTE campo, y el
                # resultado se verifica abajo -- si no es exactamente la
                # opcion pedida, se detiene.
                en_campo = False
                try:
                    en_campo = await fila.evaluate(
                        "r => r.contains(document.activeElement) || (document.activeElement && "
                        "document.activeElement.classList.contains('select2-search__field'))"
                    )
                except Exception:
                    pass
                if en_campo:
                    _log_paso(f"destinatario: sin lista visible; Enter para elegir {opcion!r} en '{etiqueta}'...")
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(0.8)
                    if objetivo in [_normalizar(v) for v in (await _valor_campo(fila, etiqueta)).split("|")]:
                        _log_paso(f"destinatario: '{etiqueta}' = {opcion!r} (verificado, con Enter).")
                        return "elegido"
        if item is None:
            info = await _opciones_js(raiz, {"accion": "buscar", "objetivo": objetivo}) or {}
            diag = ""
            try:
                diag = (await fila.evaluate("r => r.outerHTML"))[:1500]
            except Exception:
                pass
            _log_paso(f"DIAGNOSTICO campo '{etiqueta}': {diag}")
            raise AutomatizacionError(
                f"Se abrio el desplegable '{etiqueta}' pero no aparecio la opcion "
                f"{opcion!r}. Opciones visibles: {info.get('visibles')!r}"
            )
        _log_paso(f"destinatario: eligiendo {opcion!r} en '{etiqueta}'...")
        await item.click()

    loop = asyncio.get_running_loop()
    limite = loop.time() + 6
    while True:
        actual = await _valor_campo(fila, etiqueta)
        if objetivo in [_normalizar(v) for v in actual.split("|")]:
            _log_paso(f"destinatario: '{etiqueta}' = {actual!r} (verificado).")
            return "elegido"
        if loop.time() >= limite:
            raise AutomatizacionError(
                f"Se eligio {opcion!r} en '{etiqueta}' pero el campo quedo en {actual!r}."
            )
        await asyncio.sleep(0.25)


async def seleccionar_destinatario_tipificacion(page, *args, **kwargs) -> list:
    """Paso 2 con UN reintento si la grilla cambio en el clic y quedo
    elegida otra persona (el modal ya se cerro SIN guardar)."""
    try:
        return await _seleccionar_destinatario_una_vez(page, *args, **kwargs)
    except _SeleccionEquivocada as exc:
        _log_paso(f"destinatario: {exc} -- reintentando una vez...")
        await _esperar_sgdea_libre(page, "antes de reintentar el destinatario")
        return await _seleccionar_destinatario_una_vez(page, *args, **kwargs)


async def _seleccionar_destinatario_una_vez(
    page,
    texto_busqueda: str,
    nombre_exacto: str,
    tipo_documento: str,
    categoria_nivel1: str,
    tratamiento: Optional[str] = None,
    cargo: str = "",
    dependencia: str = "",
) -> list:
    """Paso 2 (ver capturas en el encabezado de este bloque). Devuelve una
    lista de avisos (vacia si todo calzo) para que el llamador los muestre
    en la revision -- p.ej. si SGDEA trae un Título/Profesión distinto al
    tratamiento de la carta."""
    avisos: list = []
    _log_paso("seleccionar_destinatario_tipificacion: click en icono 'Destinatario Tipificación'...")
    await _click_icono_documento(page, "Destinatario Tipificación")
    raiz, modal = await _modal_por_titulo(page, re.compile(r"^\s*Destinatario\s+Tipificaci[oó]n\s*$", re.IGNORECASE))
    if modal is None:
        raise AutomatizacionError(
            "Se hizo click en 'Destinatario Tipificación' pero el modal no quedo visible."
            + await _diagnostico_pagina(page)
        )

    # Chequeo de estado ANTES de buscar (sesion 2026-09-27): si el documento
    # ya tiene destinatario (p.ej. 2026-IE-036192, que Andres lleno a mano),
    # la tarjeta "Destinatario: <NOMBRE>" ya aparece en el modal. Volver a
    # elegir la fila podria agregar un SEGUNDO destinatario. Si ya esta el
    # correcto, se salta la busqueda y solo se revisan Tipo / Nivel 1; si
    # esta OTRO, se detiene sin tocar nada.
    try:
        texto_modal = await modal.inner_text()
    except Exception:
        texto_modal = ""
    ya_asignados = [
        _normalizar(m.group(1)) for m in re.finditer(r"Destinatario:\s*([^\n]+)", texto_modal)
    ]
    ya_asignados = [n for n in ya_asignados if n]
    try:
        if ya_asignados:
            if not (_normalizar(nombre_exacto) in ya_asignados or any(
                set(_normalizar(nombre_exacto).split()) <= set(n.split()) for n in ya_asignados
            )):
                raise AutomatizacionError(
                    f"El documento ya tiene otro destinatario asignado ({ya_asignados!r}), distinto de "
                    f"{nombre_exacto!r} -- no se agrega un segundo; revisar a mano."
                )
            _log_paso(f"seleccionar_destinatario_tipificacion: el documento YA tiene a {ya_asignados!r} -- no se vuelve a elegir.")
        else:
            await _elegir_fila_destinatario(raiz, modal, texto_busqueda, nombre_exacto, cargo, dependencia)

        # Evidencia (video de Andres 28-sep 09:26, caso 2026-IE-035664): al
        # elegir la fila aparece la tarjeta con Título/Profesión ("Diligencie
        # por favor..."), Destinatario, Dependencia y Tipo ("Seleccione").
        # 'Nivel 1' NO esta todavia: aparece despues de elegir el Tipo. La
        # version anterior esperaba 'Nivel 1' justo tras el clic y fallaba.
        tarjeta = await _primer_visible(
            modal.get_by_text(re.compile(r"^\s*(T[ií]tulo/Profesi[oó]n|Tipo)\s*$")), timeout_ms=10000
        )
        if tarjeta is None:
            raise AutomatizacionError(
                "Se hizo clic en el destinatario pero no aparecio su tarjeta (Título/Profesión / Tipo) "
                "bajo 'Destinatarios seleccionados'."
            )

        # Título/Profesión: si viene vacio se pone el tratamiento de la carta
        # (en el video: se escribe 'doctor' y se elige 'Doctor' de la lista);
        # si viene DISTINTO no se cambia (dato del directorio), solo se avisa.
        if tratamiento:
            fila_titulo = await _fila_de_campo(modal, "Título/Profesión")
            if fila_titulo is not None:
                titulo_actual = await _valor_campo(fila_titulo, "Título/Profesión")
                if not titulo_actual:
                    await _elegir_opcion_campo(raiz, modal, "Título/Profesión", tratamiento, page=page)
                elif _normalizar(tratamiento) not in [_normalizar(v) for v in titulo_actual.split("|")]:
                    aviso = (
                        f"SGDEA trae Título/Profesión {titulo_actual!r} para {nombre_exacto} pero la carta "
                        f"usa {tratamiento!r} en el saludo -- revisar cual es el correcto."
                    )
                    avisos.append(aviso)
                    _log_paso(f"AVISO: {aviso}")

        await _elegir_opcion_campo(raiz, modal, "Tipo", tipo_documento, page=page)
        # 'Nivel 1' aparece despues del Tipo (SGDEA lento: hasta 10 s).
        if await _primer_visible(modal.get_by_text("Nivel 1", exact=True), timeout_ms=10000) is None:
            raise AutomatizacionError("Se eligio el Tipo pero no aparecio el campo 'Nivel 1' en 10 s.")
        await _elegir_opcion_campo(raiz, modal, "Nivel 1", categoria_nivel1, page=page)
        # Sin 'No existen más niveles' la tipificacion NO esta completa y SGDEA
        # no guarda el destinatario (caso 2026-IE-036479, 28-sep: se pulso
        # Guardar sin ese texto y el memorando llego a revision sin 'Para:').
        # En todos los casos que si quedaron bien, el texto aparecio en <2 s.
        if await _primer_visible(modal.get_by_text("No existen más niveles", exact=False), timeout_ms=8000) is None:
            raise AutomatizacionError(
                f"Se eligio {categoria_nivel1!r} en 'Nivel 1' pero SGDEA no mostro 'No existen más niveles' "
                "(la tipificacion no quedo completa) -- no se guarda el destinatario."
            )
        _log_paso("seleccionar_destinatario_tipificacion: 'No existen más niveles' visible (Nivel 1 completo).")

        await _guardar_modal_y_esperar_cierre(page, modal, "Destinatario Tipificación")
    except AutomatizacionError:
        # No dejar el modal abierto a medio llenar: se cierra SIN guardar (lo
        # elegido se descarta) y el error sigue su curso.
        await _cerrar_modal_sin_guardar(modal, "Destinatario Tipificación")
        raise
    return avisos


async def _cerrar_modal_sin_guardar(modal, que: str) -> None:
    try:
        boton = await _primer_visible(modal.get_by_text(re.compile(r"^\s*(Cerrar|Cancelar)\s*$")), timeout_ms=1000)
        if boton is not None:
            await boton.click()
            _log_paso(f"{que}: modal cerrado SIN guardar (por el error).")
    except Exception:
        pass


# Busca el destinatario por su TEXTO visible, sin suponer la estructura de la
# grilla (tabla, filas div, etc.) ni que este dentro del contenedor del
# modal. Evidencia 28-sep (video + error 'dio 0 coincidencias ... Filas: []'):
# la grilla SI mostraba "Octavio Eduardo Ibarra Consuegra" (2 filas) y la
# lectura por 'tr:has(td)' dentro del modal no encontro ninguna en 8 s.
_JS_CANDIDATOS_DESTINATARIO = r"""(raiz, args) => {
    const norm = s => (s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/\u00d7/g, ' ')
        .toUpperCase().split(/\s+/).filter(Boolean).join(' ');
    const visible = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
    const doc = raiz.ownerDocument || document;
    doc.querySelectorAll('[data-insignia-dest]').forEach(e => e.removeAttribute('data-insignia-dest'));
    const objetivo = norm(args.nombre);
    const tokens = objetivo.split(' ').filter(Boolean);
    const salida = [];
    for (const el of raiz.querySelectorAll('*')) {
        if (['INPUT', 'TEXTAREA', 'SELECT', 'OPTION', 'SCRIPT', 'STYLE'].includes(el.tagName)) continue;
        const propio = norm([...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' '));
        if (!propio || !visible(el)) continue;
        const toks = new Set(propio.split(' '));
        const exacto = propio === objetivo;
        if (!exacto && !(tokens.length && tokens.every(t => toks.has(t)))) continue;
        const fila = el.closest('tr, [role=row], li, .dx-row') || el.parentElement;
        const textoFila = (fila.innerText || '').split(/[\t\n]+/).map(t => t.trim()).filter(Boolean);
        const nf = norm(textoFila.join(' '));
        if (nf.startsWith('DESTINATARIO:') || nf.startsWith('REVISOR:')) continue;   // tarjeta ya elegida
        if (/(Destinatario|Revisor):/i.test(el.textContent)) continue;
        el.setAttribute('data-insignia-dest', String(salida.length));
        salida.push({exacto: exacto, celdas: textoFila, etiqueta: el.tagName});
    }
    return salida;
}"""


class _SeleccionEquivocada(AutomatizacionError):
    """La grilla cambio justo al hacer clic y quedo elegida OTRA persona."""


def _personas_en_tarjetas(texto_modal: str, prefijo: str) -> list:
    return [n for n in (_normalizar(m.group(1)) for m in re.finditer(rf"{prefijo}:\s*([^\n]+)", texto_modal or "")) if n]


def _es_la_persona(nombre_tarjeta: str, nombre_buscado: str) -> bool:
    a, b = _normalizar(nombre_tarjeta), _normalizar(nombre_buscado)
    return a == b or (bool(b) and set(b.split()) <= set(a.split()))


async def _elegir_persona(raiz, modal, campo, texto_busqueda: str, nombre_exacto: str,
                          cargo: str, dependencia: str, prefijo_tarjeta: str) -> None:
    """Escribe en la caja de busqueda, espera a que la grilla se ESTABILICE,
    hace clic en el NOMBRE correcto y verifica en la tarjeta que quedo
    elegida esa persona.

    Evidencia (video de Andres 25-sep, caso 2026-IE-035690, 4:56): en el
    modal de revisores la grilla se volvio a dibujar justo en el clic y
    quedo elegida OTRA persona (ANA YISED CASTRO ORTIZ en vez de EMA). Por
    eso: (1) solo se hace clic cuando dos lecturas seguidas de la grilla
    son iguales, y (2) despues del clic se lee la tarjeta; si es otra
    persona se lanza _SeleccionEquivocada (el modal se cierra SIN guardar y
    se reintenta)."""
    await campo.click()
    await campo.fill(texto_busqueda)
    # Evento de teclado real para que la grilla filtre (confirmado en vivo).
    await campo.press("Backspace")
    await campo.type(texto_busqueda[-1])
    _log_paso(f"{prefijo_tarjeta.lower()}: buscado {texto_busqueda!r}, esperando resultados estables...")

    dep_n, cargo_n = _normalizar(dependencia), _normalizar(cargo)
    loop = asyncio.get_running_loop()
    limite = loop.time() + 20
    anterior = None
    candidatos: list = []
    donde = modal
    while True:
        await asyncio.sleep(0.8)
        for donde in (modal, raiz.locator("body")):
            try:
                candidatos = await donde.evaluate(_JS_CANDIDATOS_DESTINATARIO, {"nombre": nombre_exacto}) or []
            except Exception:
                candidatos = []
            if candidatos:
                break
        firma = [tuple(c["celdas"]) for c in candidatos]
        if candidatos and firma == anterior:
            break  # dos lecturas iguales: la grilla ya no esta cambiando
        anterior = firma
        if loop.time() >= limite:
            break

    elegibles = [c for c in candidatos if c["exacto"]] or candidatos
    if len(elegibles) > 1 and cargo_n and dep_n:
        # Regla de Andres (29-sep, caso 2026-IE-036323): un funcionario puede
        # tener VARIOS perfiles (JAVIER SEGURA MUNAR: Coordinador / Grupo de
        # Recaudo, Profesional Especializado / Grupo de Recaudo, Profesional
        # Universitario / Subdireccion de Gestion Financiera). Se usa SOLO el
        # perfil con el que firmo la peticion: cargo Y dependencia exactos.
        exactos = [
            c for c in elegibles
            if any(_normalizar(t) == cargo_n for t in c["celdas"][1:])
            and any(_normalizar(t) == dep_n for t in c["celdas"][1:])
        ]
        if len(exactos) == 1:
            elegibles = exactos
    if len(elegibles) > 1:
        filtrados = [
            c for c in elegibles
            if (dep_n and any(dep_n in _normalizar(t) or _normalizar(t) in dep_n for t in c["celdas"][1:] if len(t) > 8))
            or (cargo_n and any(_normalizar(t) == cargo_n for t in c["celdas"][1:]))
        ]
        if len(filtrados) == 1:
            elegibles = filtrados
    if not elegibles:
        diag = ""
        try:
            diag = " ".join((await modal.inner_text()).split())[:400]
        except Exception:
            pass
        # 0 resultados NO es 'revisar a mano' de una vez: puede ser lentitud.
        raise AutomatizacionError(
            f"La busqueda {texto_busqueda!r} no mostro a {nombre_exacto!r} en 20 s. Texto del modal: {diag!r}"
        )
    if len(elegibles) != 1:
        raise AutomatizacionError(
            f"La busqueda {texto_busqueda!r} dio {len(elegibles)} coincidencias para {nombre_exacto!r} "
            f"y ninguna calza exacto con la firma de la peticion (cargo {cargo!r}, dependencia {dependencia!r}) "
            f"-- no se adivina. Filas: {[' / '.join(c['celdas']) for c in elegibles][:8]!r}"
        )
    elegido = elegibles[0]
    indice = candidatos.index(elegido)
    _log_paso(f"{prefijo_tarjeta.lower()}: clic en el nombre de la fila {' / '.join(elegido['celdas'])!r}...")
    await donde.locator(f'[data-insignia-dest="{indice}"]').first.click()

    # Verificacion: la tarjeta 'Destinatario: X' / 'Revisor: X' debe ser ESA persona.
    limite = loop.time() + 10
    while True:
        try:
            nombres = _personas_en_tarjetas(await modal.inner_text(), prefijo_tarjeta)
        except Exception:
            nombres = []
        if any(_es_la_persona(n, nombre_exacto) for n in nombres):
            _log_paso(f"{prefijo_tarjeta.lower()}: tarjeta verificada ({nombres!r}).")
            return
        if nombres:
            raise _SeleccionEquivocada(
                f"Al hacer clic quedo elegido {nombres!r} en vez de {nombre_exacto!r} (la grilla cambio en el clic)."
            )
        if loop.time() >= limite:
            raise AutomatizacionError(
                f"Se hizo clic en {nombre_exacto!r} pero no aparecio su tarjeta '{prefijo_tarjeta}:' en 10 s."
            )
        await asyncio.sleep(0.4)


async def _campo_busqueda(modal, etiqueta: str, palabra_placeholder: str):
    campo = await _primer_visible(
        modal.locator(f'input[placeholder*="{palabra_placeholder}" i], input[placeholder*="buscar" i]'), timeout_ms=300
    )
    if campo is None:
        campo = await _primer_visible(
            modal.get_by_text(etiqueta, exact=True).locator("xpath=following::input[not(@type='hidden')][1]"),
            timeout_ms=5000,
        )
    if campo is None:
        raise AutomatizacionError(f"El modal no muestra el campo '{etiqueta}'.")
    return campo


async def _elegir_fila_destinatario(raiz, modal, texto_busqueda: str, nombre_exacto: str, cargo: str, dependencia: str) -> None:
    campo = await _campo_busqueda(modal, "Buscar destinatario", "destinatario")
    await _elegir_persona(raiz, modal, campo, texto_busqueda, nombre_exacto, cargo, dependencia, "Destinatario")


# ------------------------------------------------------------------
# Esperas de SGDEA (video 25-sep): tras guardar, SGDEA muestra "Espere por
# favor" entre 2 y 30 s, y a veces el aviso "Editor documental TMS! La
# información se guardó exitosamente" con un boton OK. Nada se hace
# mientras se vea ese aviso.
# ------------------------------------------------------------------

async def _esperar_sgdea_libre(page, que: str = "", max_s: float = 120) -> None:
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    libres_seguidos = 0
    while True:
        ocupado = False
        for raiz in _raices_busqueda(page):
            try:
                if await _primer_visible(raiz.get_by_text("Espere por favor", exact=False), timeout_ms=0) is not None:
                    ocupado = True
                    break
            except Exception:
                pass
        libres_seguidos = 0 if ocupado else libres_seguidos + 1
        if libres_seguidos >= 2:
            break
        if loop.time() - t0 > max_s:
            raise AutomatizacionError(f"SGDEA siguio en 'Espere por favor' mas de {int(max_s)} s ({que}).")
        await asyncio.sleep(0.5)
    espera = loop.time() - t0
    if espera > 1.5:
        _log_paso(f"SGDEA ocupado ('Espere por favor') {espera:.1f} s {que}".rstrip())


async def _aceptar_aviso_guardado(page, max_s: float = 20) -> bool:
    """Si aparece 'La información se guardó exitosamente', pulsa su OK."""
    loop = asyncio.get_running_loop()
    limite = loop.time() + max_s
    while loop.time() < limite:
        for raiz in _raices_busqueda(page):
            aviso = await _primer_visible(raiz.get_by_text(re.compile(r"se guard[oó] exitosamente", re.IGNORECASE)), timeout_ms=0)
            if aviso is not None:
                ok = await _primer_visible(raiz.get_by_role("button", name=re.compile(r"^\s*OK\s*$", re.IGNORECASE)), timeout_ms=2000)
                if ok is None:
                    ok = await _primer_visible(raiz.get_by_text(re.compile(r"^\s*OK\s*$")), timeout_ms=1000)
                if ok is not None:
                    # Evidencia (log 28-sep 16:02): el boton OK (SweetAlert,
                    # button.confirm) se anima y el aviso se cierra solo; un clic
                    # con espera de 30 s tumbaba el paso de la revisora.
                    try:
                        await ok.click(timeout=3000)
                        _log_paso("aviso 'La información se guardó exitosamente' -> OK.")
                    except Exception:
                        _log_paso("aviso 'La información se guardó exitosamente' se cerró solo.")
                    return True
        await asyncio.sleep(0.4)
    return False


LIMITE_CARACTERES_ASUNTO = 200


async def establecer_asunto(page, texto_asunto: str) -> None:
    """Paso 3 (captura de Andres: icono lapiz -> textarea -> Guardar)."""
    if len(texto_asunto) > LIMITE_CARACTERES_ASUNTO:
        raise AutomatizacionError(
            f"El asunto tiene {len(texto_asunto)} caracteres, mas de los "
            f"{LIMITE_CARACTERES_ASUNTO} que acepta SGDEA -- hay que acortarlo "
            "(no se trunca solo)."
        )
    _log_paso("establecer_asunto: click en icono 'Asunto'...")
    await _click_icono_documento(page, "Asunto")
    raiz, modal = await _modal_por_titulo(page, re.compile(r"^\s*Asunto\s*$"))
    if modal is None:
        raise AutomatizacionError("Se hizo click en 'Asunto' pero el modal no quedo visible." + await _diagnostico_pagina(page))
    campo = await _primer_visible(modal.locator("textarea"), timeout_ms=3000)
    if campo is None:
        raise AutomatizacionError("El modal 'Asunto' no muestra su campo de texto.")
    await campo.click()
    await campo.fill(texto_asunto)
    valor = await campo.input_value()
    if valor.strip() != texto_asunto.strip():
        raise AutomatizacionError(f"El campo de 'Asunto' quedo con {valor!r} en vez de {texto_asunto!r}.")
    await _guardar_modal_y_esperar_cierre(page, modal, "Asunto")


# ------------------------------------------------------------------
# Saludo y cuerpo SIN coordenadas (sesion 2026-09-27): el editor es un
# DevExpress ASPxRichEdit. Ademas del canvas, ese control expone una API de
# JavaScript propia (comandos del editor: buscar texto, mover el cursor,
# insertar texto). Aqui se usa esa API en vez de clicks por coordenada:
#   - Se ubica "Saludo," y "Cordialmente," por BUSQUEDA de texto en el
#     documento (cada uno debe aparecer exactamente 1 vez).
#   - El cuerpo se inserta al inicio del primer parrafo en blanco que hay
#     entre esas dos lineas (si no hay parrafo en blanco, no se toca nada).
#   - "Saludo," queda como "Cordial Saludo, Doctora <Nombre>:" insertando
#     SOLO lo que falta antes y despues (nunca se borra texto de SGDEA).
#   - Cada insercion se verifica buscando el texto resultante.
# La API se DETECTA antes de usarla (no se asume): si el control o algun
# comando no existe, o la busqueda de control ("Cordialmente," una vez)
# no da el resultado esperado, no se escribe nada y el llamador cae al
# respaldo. NO CONFIRMADO EN VIVO todavia -- la primera corrida deja en el
# log que partes de la API encontro.
# ------------------------------------------------------------------

_JS_EDITOR_API = r"""(args) => {
    const accion = args.accion;
    const encontrados = [];
    try {
        const col = window.ASPxClientControl && ASPxClientControl.GetControlCollection
            ? ASPxClientControl.GetControlCollection() : null;
        if (col && typeof col.ForEachControl === 'function') {
            col.ForEachControl(c => { if (c && c.commands && c.commands.insertText) encontrados.push(c); });
        } else if (col && col.elements) {
            for (const k in col.elements) { const c = col.elements[k]; if (c && c.commands && c.commands.insertText) encontrados.push(c); }
        }
    } catch (e) {}
    if (!encontrados.length) {
        for (const k of Object.keys(window)) {
            try { const v = window[k]; if (v && typeof v === 'object' && v.commands && v.commands.insertText && v.selection) { encontrados.push(v); } } catch (e) {}
        }
    }
    const info = {controles: encontrados.length};
    if (!encontrados.length) return {ok: false, motivo: 'no se encontro el control RichEdit', info};
    const re = encontrados[0];
    const cmds = [];
    for (const k in re.commands) { cmds.push(k); }
    info.tiene = {
        findAll: !!re.commands.findAll, insertText: !!re.commands.insertText,
        setSelection: !!(re.selection && typeof re.selection.setSelection === 'function'),
        intervals: !!(re.selection && 'intervals' in re.selection),
    };
    info.total_comandos = cmds.length;
    if (accion === 'sondear') return {ok: true, info};

    const buscar = (texto) => {
        const res = [];
        const ret = re.commands.findAll.execute(texto, true, false, res);
        const arr = res.length ? res : (Array.isArray(ret) ? ret : []);
        return arr.filter(iv => iv && typeof iv.start === 'number').map(iv => ({start: iv.start, length: iv.length, _iv: iv}));
    };
    const cursor = (pos, muestra) => {
        if (typeof re.selection.setSelection === 'function') {
            re.selection.setSelection(pos);
        } else {
            const iv = Object.assign(Object.create(Object.getPrototypeOf(muestra)), muestra);
            iv.start = pos; iv.length = 0;
            re.selection.intervals = [iv];
        }
        const act = re.selection.intervals && re.selection.intervals[0];
        if (!act || act.start !== pos || act.length !== 0) throw new Error('el cursor no quedo en la posicion ' + pos);
    };
    if (!info.tiene.findAll || !info.tiene.insertText || !(info.tiene.setSelection || info.tiene.intervals)) {
        return {ok: false, motivo: 'faltan comandos del editor', info};
    }
    const cord = buscar('Cordialmente,');
    const sal = buscar('Saludo,');
    const c0 = () => cord[0].start;
    info.cordialmente = cord.length; info.saludo = sal.length;
    if (cord.length !== 1 || sal.length !== 1) return {ok: false, motivo: 'la plantilla no tiene exactamente un "Saludo," y un "Cordialmente,"', info};
    if (args.saludo && args.cuerpo && buscar(args.saludo).length === 1 && buscar(args.cuerpo.slice(0, 60)).length === 1) {
        info.tabla_presente = buscar(args.marca_tabla || 'Tipo de AA').length > 0;
        if (accion === 'borrar_tabla') {
            // 1-oct (2026-IE-036987): rehacer el cuadro de un memorando que ya esta
            // en revision. Se valida TODO antes de borrar; si algo no cuadra no se
            // toca el documento.
            const marcas = buscar(args.marca_tabla || 'Tipo de AA');
            info.cuadros = marcas.length;
            if (marcas.length !== 1) return {ok: false, motivo: 'el documento tiene ' + marcas.length + ' cuadro(s) (se esperaba 1)', info};
            if (!re.commands.deleteTable) return {ok: false, motivo: 'el editor no tiene el comando para borrar tablas', info};
            const vcu = buscar(args.cuerpo.slice(0, 60));
            const finCuerpo = vcu[0].start + args.cuerpo.length;
            const pos = marcas[0].start;
            if (!(pos > finCuerpo && pos < c0())) return {ok: false, motivo: 'el cuadro no esta entre el cuerpo y "Cordialmente,"', info};
            cursor(pos, marcas[0]._iv);
            re.commands.deleteTable.execute();
            info.borrada = buscar(args.marca_tabla || 'Tipo de AA').length === 0;
            if (!info.borrada) return {ok: false, motivo: 'el cuadro anterior no se borro', info};
            try { cursor(pos, vcu[0]._iv); } catch (e) {
                try { re.commands.undo.execute(); } catch (e2) {}
                return {ok: false, motivo: 'no se pudo dejar el cursor donde estaba el cuadro (se deshizo el borrado)', info};
            }
            info.pos_tabla = pos;
            return {ok: true, info};
        }
        if (accion === 'deshacer') {
            try { re.commands.undo.execute(); return {ok: true, info}; } catch (e) { return {ok: false, motivo: String(e), info}; }
        }
        if (accion === 'cursor_tabla') {
            // Reintento de un caso masivo al que le falto la tabla (2026-IE-036323,
            // 29-sep): el cursor va al segundo parrafo despues del cuerpo.
            if (info.tabla_presente) return {ok: false, motivo: 'la tabla ya esta en el documento', info};
            const vcu = buscar(args.cuerpo.slice(0, 60));
            const finCuerpo = vcu[0].start + args.cuerpo.length;
            if (c0() - finCuerpo < 3) return {ok: false, motivo: 'no hay parrafos en blanco entre el cuerpo y "Cordialmente," para la tabla', info};
            cursor(finCuerpo + 2, vcu[0]._iv);
            info.pos_tabla = finCuerpo + 2;
            return {ok: true, info};
        }
        return {ok: true, ya_estaba: true, info};
    }
    if (accion === 'cursor_tabla') return {ok: false, motivo: 'el saludo y el cuerpo no estan en el documento: no se ubica la tabla', info};
    if (accion === 'borrar_tabla' || accion === 'deshacer') return {ok: false, motivo: 'el saludo y el cuerpo de esta carta no estan tal cual en el documento (¿se edito a mano?)', info};
    if (buscar('Saludo, ').length) return {ok: false, motivo: '"Saludo," ya tiene texto a continuacion pero no es el de esta carta -- revisar a mano', info};
    const a = sal[0].start, c = cord[0].start;
    const finSaludo = a + 'Saludo,'.length;
    info.hueco = c - finSaludo;
    // Se deja UNA linea en blanco entre el saludo y el cuerpo (y, en masivas,
    // otra entre el cuerpo y la tabla) -- observacion de Andres sobre el
    // primer caso 100% autonomo (2026-IE-036295, 28-sep).
    if (c - finSaludo < 3) return {ok: false, motivo: 'faltan parrafos en blanco entre "Saludo," y "Cordialmente," (se necesitan 2)', info};
    if (args.tabla && c - finSaludo < 5) return {ok: false, motivo: 'caso masivo: hacen falta 4 parrafos en blanco (espacio + cuerpo + espacio + tabla) entre "Saludo," y "Cordialmente,"', info};
    if (accion === 'verificar') return {ok: true, info};

    // 1) cuerpo en el SEGUNDO parrafo en blanco: el primero queda como espacio
    //    entre el saludo y el cuerpo.
    cursor(finSaludo + 2, sal[0]._iv);
    re.commands.insertText.execute(args.cuerpo);
    const muestraCuerpo = args.cuerpo.slice(0, 60);
    const vc = buscar(muestraCuerpo);
    if (vc.length !== 1 || vc[0].start !== finSaludo + 2) throw new Error('el cuerpo no quedo donde se esperaba');
    // 2) saludo: prefijo antes y sufijo despues de "Saludo," (sin borrar nada)
    if (args.prefijo) { cursor(a, sal[0]._iv); re.commands.insertText.execute(args.prefijo); }
    if (args.sufijo) { cursor(a + args.prefijo.length + 'Saludo,'.length, sal[0]._iv); re.commands.insertText.execute(args.sufijo); }
    const vs = buscar(args.saludo);
    if (vs.length !== 1 || vs[0].start !== a) throw new Error('el saludo no quedo como se esperaba');
    if (args.tabla) {
        // la tabla va en el segundo parrafo en blanco despues del cuerpo (uno de
        // espacio, como en la respuesta masiva aprobada de 2026-IE-035664)
        const vc2 = buscar(muestraCuerpo);
        const posTabla = vc2[0].start + args.cuerpo.length + 2;
        cursor(posTabla, sal[0]._iv);
        info.pos_tabla = posTabla;
    }
    return {ok: true, info};
}"""


async def _frame_editor_obj(page):
    handle = await page.locator(IFRAME_DOCUMENTOS).element_handle(timeout=5000)
    frame = await handle.content_frame() if handle else None
    if frame is None:
        raise AutomatizacionError("No se pudo acceder al contenido de #frameVerDocumentos.")
    return frame


async def rellenar_saludo_y_cuerpo(page, saludo: str, cuerpo: str, tabla: Optional[list] = None,
                                   encabezado: Optional[list] = None, formato: Optional[dict] = None) -> str:
    """Deja el saludo y el cuerpo en el documento usando la API del editor
    (ver comentario arriba). Devuelve 'api' si lo hizo. Lanza
    AutomatizacionError con detalle si la API no esta disponible o si una
    verificacion falla -- el llamador decide el respaldo."""
    if "Saludo," not in saludo:
        raise AutomatizacionError(f"El saludo de la carta no contiene 'Saludo,': {saludo!r}")
    i = saludo.index("Saludo,")
    prefijo, sufijo = saludo[:i], saludo[i + len("Saludo,"):]
    encabezado = list(encabezado or (formato or {}).get("encabezado") or ENCABEZADO_TABLA_ACTOS)
    marca = encabezado[0]
    # Un aviso de SGDEA que quedo abierto (p.ej. tras guardar el asunto) roba el
    # foco: 2026-IE-036323 perdio la tabla con 'foco: BUTTON.confirm'.
    await _despejar_capa_modal_editor(page)
    frame = await _frame_editor_obj(page)
    try:
        sondeo = await frame.evaluate(
            _JS_EDITOR_API, {"accion": "verificar", "tabla": bool(tabla), "saludo": saludo, "cuerpo": cuerpo,
                             "marca_tabla": marca}
        )
    except Exception as exc:
        raise EditorApiNoDisponible(f"API del editor no utilizable (error al sondear: {exc})") from None
    _log_paso(f"rellenar_saludo_y_cuerpo: API del editor -> {sondeo!r}")
    if not sondeo.get("ok"):
        motivo = sondeo.get("motivo") or ""
        clase = EditorApiNoDisponible if motivo in ("no se encontro el control RichEdit", "faltan comandos del editor") else AutomatizacionError
        raise clase(f"API del editor: {motivo} ({sondeo.get('info')})")
    if sondeo.get("ya_estaba"):
        # Reintento sobre un documento que YA tiene saludo y cuerpo (p.ej.
        # una corrida anterior se corto despues del paso 4): no se escribe nada.
        _log_paso("rellenar_saludo_y_cuerpo: el documento YA tiene este saludo y cuerpo -- no se escribe de nuevo.")
        if tabla and not (sondeo.get("info") or {}).get("tabla_presente"):
            _log_paso("rellenar_saludo_y_cuerpo: falta la tabla de actos -- se pega ahora.")
            pos = await frame.evaluate(_JS_EDITOR_API, {"accion": "cursor_tabla", "tabla": True, "saludo": saludo,
                                                         "cuerpo": cuerpo, "marca_tabla": marca})
            if not pos.get("ok"):
                return f"api_sin_tabla: {pos.get('motivo')}"
            try:
                await _pegar_tabla_actos(page, frame, tabla, encabezado, formato)
            except Exception as exc_tabla:
                _log_paso(f"tabla de actos: NO se pego ({type(exc_tabla).__name__}: {exc_tabla}).")
                return f"api_sin_tabla: {exc_tabla}"
            return "api"
        return "ya_estaba"
    try:
        res = await frame.evaluate(
            _JS_EDITOR_API,
            {"accion": "escribir", "cuerpo": cuerpo, "saludo": saludo, "prefijo": prefijo, "sufijo": sufijo, "tabla": bool(tabla)},
        )
    except Exception as exc:
        raise AutomatizacionError(
            f"La API del editor fallo a mitad de camino ({exc}). Revisar el documento: puede haber "
            "quedado texto parcial (se deshace con Ctrl+Z; nada se guardo)."
        ) from None
    if not res.get("ok"):
        raise AutomatizacionError(f"API del editor: {res.get('motivo')} ({res.get('info')})")
    _log_paso("rellenar_saludo_y_cuerpo: OK -- saludo y cuerpo escritos y verificados via API.")
    if tabla:
        # El saludo y el cuerpo YA quedaron escritos: un fallo de la tabla
        # NO puede propagarse como fallo de este paso (el llamador caeria al
        # respaldo por coordenada y pegaria el cuerpo OTRA vez). Se devuelve
        # el motivo para que quede como aviso.
        try:
            await _pegar_tabla_actos(page, frame, tabla, encabezado, formato)
        except Exception as exc_tabla:
            _log_paso(f"tabla de actos: NO se pego ({type(exc_tabla).__name__}: {exc_tabla}).")
            return f"api_sin_tabla: {exc_tabla}"
    return "api"


# Tabla de actos de los casos MASIVOS. Evidencia (sesion 2026-09-27):
#   - Andres la arma en Excel, la copia y la pega directo en SGDEA.
#   - La respuesta masiva aprobada 2026-IE-035561 (PDF real, leido con
#     pdfplumber) trae la tabla justo debajo del parrafo del cuerpo, con
#     encabezado exacto "Expediente | Tipo de AA | Número | Fecha", fondo
#     azul oscuro y texto blanco en negrilla, bordes finos y "Número"
#     alineado a la derecha -- el mismo formato que backend/excel_io.py.
# Se reproduce lo que hace Andres: el portapapeles recibe la tabla como
# HTML (lo mismo que deja Excel al copiar) + texto con tabulaciones, y se
# pega con Ctrl+V -- el UNICO mecanismo confirmado en vivo contra este
# editor. El cursor lo ubica la API del editor (sin coordenadas).
# Evidencia definitiva (captura de Andres 28-sep, caso 2026-IE-035664):
# "Tipo de AA | Numero | Fecha | Expediente", encabezado azul oscuro con
# letra blanca en negrilla, celdas centradas y el expediente en letra mas
# pequena. Fechas como '19/06/2026' / '6/08/2026' (ver sgdea_carta).
ENCABEZADO_TABLA_ACTOS = ["Tipo de AA", "Numero", "Fecha", "Expediente"]


# Formato por defecto (masiva por expedientes). Los formatos guardados viven
# en backend/sgdea_carta.py (FORMATO_TABLA_*).
_FORMATO_TABLA_DEFECTO = {
    "encabezado": ENCABEZADO_TABLA_ACTOS, "alineacion": ["center", "center", "center", "left"],
    "fondo_encabezado": "#1F3864", "fuente": "Verdana", "fuente_pt": 9, "fuente_pt_columna": {3: 8}, "anchos_px": None,
}


def _tabla_actos_html(tabla: list, encabezado: Optional[list] = None, formato: Optional[dict] = None) -> tuple:
    import html as _html
    f = dict(_FORMATO_TABLA_DEFECTO, **(formato or {}))
    encabezado = list(encabezado or f["encabezado"])
    n = len(encabezado)
    alineacion = list(f.get("alineacion") or [])
    alineacion += ["center"] * (n - len(alineacion))
    anchos = f.get("anchos_px") or []
    pt_col = {int(k): v for k, v in (f.get("fuente_pt_columna") or {}).items()}
    base = f"border:1px solid #000000;padding:1px 4px;font-family:{f['fuente']};font-size:{f['fuente_pt']}pt"

    def ancho(j):
        return f";width:{anchos[j]}px" if j < len(anchos) and anchos[j] else ""

    cab = [f'<td style="{base};background:{f["fondo_encabezado"]};color:#FFFFFF;font-weight:bold;'
           f'text-align:center{ancho(j)}">{_html.escape(t)}</td>' for j, t in enumerate(encabezado)]
    filas = ["<tr>" + "".join(cab) + "</tr>"]
    for fila in tabla:
        tds = []
        for j, v in enumerate(fila):
            estilo = f";text-align:{alineacion[j] if j < n else 'center'}"
            if j in pt_col:
                estilo += f";font-size:{pt_col[j]}pt"
            tds.append(f'<td style="{base}{estilo}{ancho(j)}">{_html.escape(str(v or ""))}</td>')
        filas.append("<tr>" + "".join(tds) + "</tr>")
    html_tabla = '<table style="border-collapse:collapse">' + "".join(filas) + "</table>"
    texto = "\n".join("\t".join(str(v or "") for v in f) for f in [encabezado, *tabla])
    return html_tabla, texto


async def _pegar_tabla_actos(page, frame, tabla: list, encabezado: Optional[list] = None,
                            formato: Optional[dict] = None) -> None:
    encabezado = list(encabezado or (formato or {}).get("encabezado") or ENCABEZADO_TABLA_ACTOS)
    html_tabla, texto = _tabla_actos_html(tabla, encabezado, formato)
    await _despejar_capa_modal_editor(page)
    await page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    # Orden confirmado en vivo: portapapeles PRIMERO, foco al editor DESPUES.
    await page.evaluate(
        """async ({html, texto}) => {
            const item = new ClipboardItem({
                'text/html': new Blob([html], {type: 'text/html'}),
                'text/plain': new Blob([texto], {type: 'text/plain'}),
            });
            await navigator.clipboard.write([item]);
        }""",
        {"html": html_tabla, "texto": texto},
    )
    enfocado, ok_foco, desc = False, False, ""
    for _intento in range(4):
        enfocado = await frame.evaluate(
            """() => {
                let re = null;
                try { ASPxClientControl.GetControlCollection().ForEachControl(c => { if (!re && c && c.commands && c.commands.insertText) re = c; }); } catch (e) {}
                if (!re || typeof re.Focus !== 'function') return false;
                re.Focus(); return true;
            }"""
        )
        ok_foco, desc = await _foco_actual_es_input_target(page)
        if enfocado and ok_foco:
            break
        # El foco lo tiene otra cosa (el OK de un aviso de SGDEA): se despeja y se reintenta.
        _log_paso(f"tabla de actos: el foco esta en {desc} -- se despeja y se reintenta.")
        await _despejar_capa_modal_editor(page)
        aviso = await _leer_aviso_sweet(page)
        if aviso:
            await _cerrar_aviso_sweet(aviso)
        await asyncio.sleep(1)
    if not (enfocado and ok_foco):
        raise AutomatizacionError(f"No se pudo dejar el foco en el editor para pegar la tabla (foco: {desc}).")
    _log_paso(f"tabla de actos: pegando {len(tabla)} fila(s) con Ctrl+V...")
    await page.keyboard.press("Control+V")
    primer_expediente = str(tabla[0][-1]) if tabla and tabla[0] else ""
    loop = asyncio.get_running_loop()
    limite = loop.time() + 8
    while True:
        n_cab = await buscar_en_documento(page, encabezado[0])
        n_exp = await buscar_en_documento(page, primer_expediente) if primer_expediente else 1
        if n_cab and n_exp:
            _log_paso("tabla de actos: OK -- encabezado y primer expediente visibles en el documento.")
            return
        if loop.time() >= limite:
            raise AutomatizacionError(
                "Se envio Ctrl+V con la tabla de actos pero no aparece en el documento "
                f"('Tipo de AA': {n_cab!r}, primer expediente: {n_exp!r})."
            )
        await asyncio.sleep(0.5)


async def buscar_en_documento(page, texto: str) -> Optional[int]:
    """Cuantas veces aparece `texto` en el documento (via la API del
    editor), o None si la API no esta disponible. Solo lectura."""
    try:
        frame = await _frame_editor_obj(page)
        return await frame.evaluate(
            r"""(t) => {
                let re = null;
                try { const col = ASPxClientControl.GetControlCollection();
                      col.ForEachControl(c => { if (!re && c && c.commands && c.commands.findAll) re = c; }); } catch (e) {}
                if (!re) return null;
                const res = []; const ret = re.commands.findAll.execute(t, true, false, res);
                const arr = res.length ? res : (Array.isArray(ret) ? ret : []);
                return arr.length;
            }""",
            texto,
        )
    except Exception:
        return None


# ------------------------------------------------------------------
# Adjuntar archivo -- las DOS vias confirmadas en vivo, sesion
# 2026-09-22: "Adjuntar archivo" (toolbar del caso, sube al Expediente) y
# "Anexos al documento" (dentro de "Ver documentos", esta si viaja con la
# comunicacion). Ambas son <input type=file> HTML estandar.
# ------------------------------------------------------------------

async def adjuntar_archivo_caso(page, ruta_pdf: str) -> None:
    """Sube `ruta_pdf` via el boton 'Adjuntar archivo' del toolbar
    superior del caso (fuera de #frameVerDocumentos) -- esto lo deja en
    el 'Expediente' del caso, NO necesariamente en lo que se envia con la
    comunicacion (ver adjuntar_archivo_documento para eso)."""
    boton = page.locator('[data-original-title="Adjuntar archivo"]')
    if not await boton.count():
        raise AutomatizacionError(
            "No se encontro el boton 'Adjuntar archivo' del toolbar del "
            "caso."
        )
    await boton.first.click()
    await page.wait_for_timeout(600)

    input_archivo = page.locator('input[type="file"]').first
    if not await input_archivo.count():
        raise AutomatizacionError(
            "Se abrio el panel de 'Adjuntar archivo' pero no se "
            "encontro el <input type=file>."
        )
    await input_archivo.set_input_files(ruta_pdf)
    await page.wait_for_timeout(500)

    boton_subir = page.get_by_text("Subir todos", exact=False)
    if not await boton_subir.count():
        raise AutomatizacionError(
            "Se selecciono el archivo pero no se encontro el boton "
            "'Subir todos' para confirmar la carga."
        )
    await boton_subir.first.click()
    await page.wait_for_timeout(1500)


PATRON_TITULO_MODAL_ANEXO = re.compile(r"^\s*Anexo\s*$", re.IGNORECASE)


async def establecer_numero_anexos(page, cantidad: int = 1, forzar_guardar: bool = False) -> str:
    """Icono 'Anexo' de la columna izquierda -> modal 'Anexo' con una caja
    numerica -> 'cantidad' -> Guardar. El pie del documento pasa a decir
    'Anexos: 1'. Evidencia: video de Andres 25-sep (caso 2026-IE-035690,
    5:21-5:41): tras el clic SGDEA muestra "Espere por favor" ~15 s antes
    de abrir el modal. Devuelve 'ya_estaba' o 'establecido'."""
    await _esperar_sgdea_libre(page, "antes de 'Anexo'")
    _log_paso("establecer_numero_anexos: click en icono 'Anexo'...")
    await _click_icono_documento(page, "Anexo")
    await _esperar_sgdea_libre(page, "abriendo el modal 'Anexo'")
    raiz, modal = await _modal_por_titulo(page, PATRON_TITULO_MODAL_ANEXO, timeout_ms=45000)
    if modal is None:
        raise AutomatizacionError("Se hizo clic en el icono 'Anexo' pero el modal 'Anexo' no aparecio en 45 s.")
    try:
        caja = await _primer_visible(modal.locator("input:not([type=hidden])"), timeout_ms=5000)
        if caja is None:
            raise AutomatizacionError("El modal 'Anexo' no muestra la caja del numero de anexos.")
        actual = (await caja.input_value()).strip()
        if actual == str(cantidad) and forzar_guardar:
            # 1-oct (rehacer el cuadro): 'Guardar' en este modal guarda TAMBIEN el
            # documento ("La información se guardó exitosamente").
            _log_paso(f"establecer_numero_anexos: ya dice {actual} -- se guarda igual para guardar el documento.")
            await _guardar_modal_y_esperar_cierre(page, modal, "Anexo")
            await _aceptar_aviso_guardado(page, max_s=8)
            await _esperar_sgdea_libre(page, "tras guardar 'Anexo'")
            return "guardado"
        if actual == str(cantidad):
            _log_paso(f"establecer_numero_anexos: ya dice {actual} -- se cierra sin cambiar.")
            await _cerrar_modal_sin_guardar(modal, "Anexo")
            return "ya_estaba"
        await caja.click()
        await caja.fill(str(cantidad))
        await caja.press("Tab")
        if (await caja.input_value()).strip() != str(cantidad):
            raise AutomatizacionError(f"No se pudo escribir {cantidad} en la caja del modal 'Anexo'.")
        await _guardar_modal_y_esperar_cierre(page, modal, "Anexo")
    except AutomatizacionError:
        await _cerrar_modal_sin_guardar(modal, "Anexo")
        raise
    await _aceptar_aviso_guardado(page, max_s=5)
    await _esperar_sgdea_libre(page, "tras guardar 'Anexo'")
    _log_paso(f"establecer_numero_anexos: OK -- Anexos: {cantidad}.")
    return "establecido"


async def adjuntar_archivo_documento(page, ruta_pdf: str) -> str:
    """Sube `ruta_pdf` en 'Anexos al documento' (la via que viaja con la
    comunicacion). Evidencia: 3 capturas de Andres (27-sep) -- recuadro
    verde 'Anexos al documento' debajo del editor, caja 'Seleccionar
    archivos...' + boton 'Examinar ...'; al elegir el archivo aparece su
    miniatura ('2026_17478.pdf (420.07 KB)') y los botones 'Quitar' /
    'Subir archivo'; tras 'Subir archivo' el pie del documento muestra
    'Nombre anexos: 2026_17478.pdf'.

    En vez del dialogo nativo de Windows (el que abre 'Examinar ...'), se
    le entrega el archivo directo al <input type=file> de esa seccion --
    mismo resultado, sin ventana. Chequeo de estado previo: si el documento
    ya muestra ese nombre en 'Nombre anexos', no se vuelve a subir.
    Devuelve 'ya_estaba', 'verificado' o 'sin_verificar'."""
    nombre = Path(ruta_pdf).name
    if not Path(ruta_pdf).is_file():
        raise AutomatizacionError(f"No existe el archivo a adjuntar: {ruta_pdf!r}")
    if (await buscar_en_documento(page, nombre) or 0) >= 1:
        _log_paso(f"adjuntar_archivo_documento: el documento ya lista {nombre!r} -- no se sube de nuevo.")
        return "ya_estaba"

    titulo = await _primer_visible(page.get_by_text("Anexos al documento", exact=True), timeout_ms=5000)
    if titulo is None:
        raise AutomatizacionError("No se encontro la seccion 'Anexos al documento' debajo del editor." + await _diagnostico_pagina(page))
    await titulo.scroll_into_view_if_needed()
    ya_listado = await _primer_visible(
        titulo.locator(f"xpath=following::*[contains(normalize-space(text()), {nombre!r})]"), timeout_ms=0
    )
    if ya_listado is not None:
        _log_paso(f"adjuntar_archivo_documento: {nombre!r} ya aparece en 'Anexos al documento' -- no se sube de nuevo.")
        return "ya_estaba"
    entrada = titulo.locator("xpath=following::input[@type='file'][1]")
    if not await entrada.count():
        raise AutomatizacionError("La seccion 'Anexos al documento' no tiene campo de archivo.")
    _log_paso(f"adjuntar_archivo_documento: entregando {nombre!r} al campo de archivo...")
    await entrada.first.set_input_files(ruta_pdf)

    if await _primer_visible(page.get_by_text(nombre, exact=False), timeout_ms=8000) is None:
        raise AutomatizacionError(f"Se eligio {nombre!r} pero no aparecio su miniatura en 'Anexos al documento'.")
    subir = await _primer_visible(
        titulo.locator("xpath=following::*[self::button or self::a][contains(normalize-space(.),'Subir archivo')]"),
        timeout_ms=4000,
    )
    if subir is None:
        raise AutomatizacionError("Aparecio el archivo pero no el boton 'Subir archivo'.")
    _log_paso("adjuntar_archivo_documento: click en 'Subir archivo'...")
    await subir.click()
    # Video 25-sep (5:58-6:19): "Subiendo archivo 1 de 1..." y luego el
    # editor se recarga con "Espere por favor" ~15-20 s antes de mostrar
    # 'Nombre anexos: <archivo>'. Se espera a que SGDEA termine.
    # Un ZIP masivo grande (2026-IE-036323: 109 expedientes) tarda mas en
    # subir: las esperas crecen con el tamaño del archivo.
    megas = Path(ruta_pdf).stat().st_size / 1_000_000
    espera_extra = int(3 * megas)
    if megas > 5:
        _log_paso(f"adjuntar_archivo_documento: archivo de {megas:.1f} MB -- se esperan hasta {60 + espera_extra} s de mas.")
    await asyncio.sleep(2)
    await _esperar_sgdea_libre(page, "tras 'Subir archivo'", max_s=180 + espera_extra)
    await _esperar_editor_listo(page)

    loop = asyncio.get_running_loop()
    limite = loop.time() + 60 + espera_extra
    while True:
        n = await buscar_en_documento(page, nombre)
        if n:
            _log_paso(f"adjuntar_archivo_documento: OK -- el documento muestra 'Nombre anexos: {nombre}'.")
            return "verificado"
        if n is None:
            # Sin API del editor no se puede leer el pie; se acepta si el
            # boton 'Subir archivo' desaparecio (la carga termino).
            await asyncio.sleep(2)
            if await _primer_visible(titulo.locator(
                "xpath=following::*[self::button or self::a][contains(normalize-space(.),'Subir archivo')]"
            ), timeout_ms=0) is None:
                _log_paso("adjuntar_archivo_documento: 'Subir archivo' ya no se ve -- carga terminada (sin verificar el pie).")
                return "sin_verificar"
        if loop.time() >= limite:
            raise AutomatizacionError(
                f"Se pulso 'Subir archivo' pero en {60 + espera_extra} s el documento no muestra 'Nombre anexos: {nombre}'."
            )
        await asyncio.sleep(0.8)


# ------------------------------------------------------------------
# Tamaño de pagina "Legal" (Distribución de página -> Tamaño -> Legal) --
# INFORMACION DESCRITA POR ANDRES (sesion 2026-09-22), TODAVIA NO
# INSPECCIONADA EN VIVO contra el DOM real por este modulo -- ver
# advertencia en el docstring de configurar_tamano_legal().
# ------------------------------------------------------------------

# Evidencia (3 capturas de Andres del 27-sep, caso 2026-IE-036192):
#   1. La cinta tiene la pestaña "Distribución de Página" (P MAYUSCULA -- la
#      version anterior la buscaba con p minuscula y coincidencia exacta).
#   2. Dentro, grupo "Configurar Página": boton "Tamaño" (con flechita).
#   3. El menu desplegado lista: Carta, Legal, Folio, A4, B5, Ejecutivo,
#      A5, A6 y, separado al final, "Más Tamaños de Papel". El tamaño
#      activo lleva un chulo (en la captura, Legal ya estaba marcado).
# El item "Legal" se busca DENTRO de ese menu (el contenedor mas cercano
# que tiene a la vez "Legal" y "Más Tamaños de Papel"), no en toda la
# pagina. Si ya esta marcado, no se toca. Si el paso falla, gestionar_caso_
# completo deja un aviso y sigue (no bloquea a la revisora).
PATRON_PESTANA_DISTRIBUCION = re.compile(r"^\s*Distribuci[oó]n\s+de\s+p[aá]gina\s*$", re.IGNORECASE)
PATRON_PESTANA_ARCHIVO = re.compile(r"^\s*Archivo\s*$", re.IGNORECASE)
PATRON_BOTON_TAMANO = re.compile(r"^\s*Tama[nñ]o\s*$", re.IGNORECASE)
PATRON_OPCION_LEGAL = re.compile(r"^\s*Legal\s*$", re.IGNORECASE)
PATRON_MAS_TAMANOS = re.compile(r"^\s*M[aá]s\s+Tama[nñ]os\s+de\s+Papel\s*$", re.IGNORECASE)

_JS_ITEM_MARCADO = """(el) => {
    for (let n = el, i = 0; n && i < 4; n = n.parentElement, i++) {
        const c = (n.className && n.className.baseVal !== undefined) ? n.className.baseVal : (n.className || '');
        if (/checked|selected/i.test(c) || n.getAttribute('aria-checked') === 'true') return true;
    }
    return false;
}"""


async def _abrir_menu_tamano(frame):
    """Abre Tamaño y devuelve el item 'Legal' DEL MENU (o None)."""
    boton = await _primer_visible(frame.locator('[data-original-title="Tamaño"]'), timeout_ms=300)
    if boton is None:
        boton = await _primer_visible(frame.get_by_text(PATRON_BOTON_TAMANO), timeout_ms=4000)
    if boton is None:
        raise AutomatizacionError("Se abrio 'Distribución de Página' pero no aparecio el boton 'Tamaño'.")
    await boton.click()
    mas = await _primer_visible(frame.get_by_text(PATRON_MAS_TAMANOS), timeout_ms=4000)
    if mas is not None:
        menu = mas.locator("xpath=ancestor::*[.//*[normalize-space(text())='Legal']][1]")
        if await menu.count():
            item = await _primer_visible(menu.first.get_by_text(PATRON_OPCION_LEGAL), timeout_ms=1000)
            if item is not None:
                return item
    return await _primer_visible(frame.get_by_text(PATRON_OPCION_LEGAL), timeout_ms=2000)


async def configurar_tamano_legal(page) -> None:
    """Distribución de Página > Tamaño > Legal (Andres SIEMPRE usa Legal
    para que la firma no quede sola en una pagina aparte). Al terminar
    vuelve a la pestaña 'Archivo' de la cinta."""
    frame = page.frame_locator(IFRAME_DOCUMENTOS)
    pestana = await _primer_visible(frame.get_by_text(PATRON_PESTANA_DISTRIBUCION), timeout_ms=5000)
    if pestana is None:
        raise AutomatizacionError("No se encontro la pestaña 'Distribución de Página' en la cinta del editor." + await _diagnostico_pagina(page))
    _log_paso("configurar_tamano_legal: click en pestaña 'Distribución de Página'...")
    await pestana.click()

    _log_paso("configurar_tamano_legal: abriendo 'Tamaño'...")
    legal = await _abrir_menu_tamano(frame)
    if legal is None:
        raise AutomatizacionError("Se desplego 'Tamaño' pero no aparecio la opcion 'Legal'.")
    if await legal.evaluate(_JS_ITEM_MARCADO):
        _log_paso("configurar_tamano_legal: 'Legal' ya estaba marcado -- no se toca.")
        await page.keyboard.press("Escape")
    else:
        _log_paso("configurar_tamano_legal: click en 'Legal'...")
        await legal.click()
        # Verificacion: reabrir el menu y ver el chulo en 'Legal'.
        legal2 = await _abrir_menu_tamano(frame)
        marcado = legal2 is not None and await legal2.evaluate(_JS_ITEM_MARCADO)
        await page.keyboard.press("Escape")
        _log_paso("configurar_tamano_legal: " + ("'Legal' verificado con chulo." if marcado else "'Legal' elegido (no se pudo leer el chulo para verificar)."))

    archivo = await _primer_visible(frame.get_by_text(PATRON_PESTANA_ARCHIVO), timeout_ms=2000)
    if archivo is not None:
        await archivo.click()
    # Un menu 'Tamaño' que quede abierto tapa los iconos del documento y
    # bloquea los pasos siguientes: se confirma que se cerro.
    if await _primer_visible(frame.get_by_text(PATRON_OPCION_LEGAL), timeout_ms=0) is not None:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)
        if await _primer_visible(frame.get_by_text(PATRON_OPCION_LEGAL), timeout_ms=0) is not None:
            raise AutomatizacionError("El menu 'Tamaño' quedo abierto y no se pudo cerrar.")
    _log_paso("configurar_tamano_legal: OK.")


# ------------------------------------------------------------------
# Orquestador -- encadena todo lo de arriba (destinatario, asunto,
# saludo/cuerpo, adjunto, tamaño legal, revisor) para dejar el
# documento listo para que Andres SOLO tenga que entrar a revisarlo y
# pulsar el "Solicitar aprobación"/"Aprobar y enviar" el mismo (pedido
# de Andres, sesion 2026-09-23: "que falta para que pueda gestionar
# casos el solo y yo solo entre a revisión y darle enviar a
# revisión?"). NUNCA pulsa ese boton -- sigue siendo la unica excepcion
# deliberada (ver _BOTONES_PROHIBIDOS y enviar_a_aprobacion() mas
# abajo), y sigue exactamente el mismo patron que ejecutar_flujo_
# aprobacion() para eso: se detiene ahi y deja pendiente_revision_
# humana=True siempre.
#
# ADVERTENCIA -- a diferencia de ejecutar_flujo_aprobacion() (que solo
# encadena pasos YA confirmados en vivo por separado), este orquestador
# encadena TAMBIEN los pasos nuevos de esta sesion (seleccionar_
# destinatario_tipificacion, establecer_asunto, la rama "Crear
# documento" de navegar_a_caso) que todavia NO se han probado en vivo.
# Su primera corrida real, de principio a fin, debe hacerse con Andres
# mirando la pantalla de Chrome -- exactamente igual que se hizo antes
# con seleccionar_revisor_ema y configurar_tamano_legal.
# ------------------------------------------------------------------

# CORRECCION (sesion 2026-09-25, caso real 2026-IE-036117, prueba en vivo
# de "Gestionar caso completo" hasta dejarlo listo para revision): el
# patron original exigia que la columna completa terminara justo despues
# de la categoria (ancla "$", y "." no cruza saltos de linea sin
# re.DOTALL) -- valido para el ejemplo limpio de 2026-IE-035458 ("Memorando
# - SOLICITUDES INTERNAS GENERALES"), pero la columna real de SGDEA para
# un caso REASIGNADO trae la categoria y el estado pegados en el mismo
# string con una linea en blanco de por medio, ej. columnas_crudas[3] de
# 2026-IE-036117 (verificado con dashboard_casos.json real, no adivinado):
#   "Memorando - SOLICITUDES INTERNAS GENERALES\n\nRE-ASIGNADO"
# Contra ese texto, `.match()` fallaba SIEMPRE (no solo en este caso --
# en CUALQUIER caso reasignado), porque "$" sin re.MULTILINE solo calza al
# final absoluto del string, y el "\n\nRE-ASIGNADO" final nunca lo deja
# llegar ahi. El boton fallaba en silencio (SnackBar roja que desaparece
# sola en unos segundos) ANTES de tocar el candado de reentrada o el
# primer print de diagnostico -- por eso el log de "Gestionar caso
# completo" instrumentado esta sesion se veia completamente vacio pese a
# clicks reales sobre el boton. Fix: "(?:\n|$)" en vez de solo "$" -- el
# patron ahora se detiene en el primer salto de linea (la categoria real
# nunca lo tiene) en vez de exigir que sea literalmente el final del
# string completo. Probado contra ambas formas (limpia y con
# "\n\nRE-ASIGNADO" pegado) antes de desplegar.
PATRON_CATEGORIA_PROCESO = re.compile(r"^Memorando\s*-\s*(.+?)\.?\s*(?:\n|$)", re.IGNORECASE)


def extraer_categoria_proceso(columnas_crudas: list) -> Optional[str]:
    """Busca, dentro de `columnas_crudas` (las columnas crudas de la fila
    del caso en la lista 'Gestionar', ya guardadas por
    listar_casos_gestionar/detectar_casos_nuevos en CasoDashboard), el
    texto con forma "Memorando - <CATEGORIA>" -- la misma categoria que
    hay que elegir en el desplegable 'Nivel 1' del modal 'Destinatario
    Tipificación' (confirmado visualmente en el video de Andres, sesion
    2026-09-23: para el caso 2026-IE-035458 esa columna decia 'Memorando
    - SOLICITUDES INTERNAS GENERALES' y ese fue exactamente el valor que
    Andres eligio en 'Nivel 1'). Tolera contenido extra pegado despues de
    un salto de linea (p.ej. "\\n\\nRE-ASIGNADO" en casos reasignados,
    confirmado en vivo con 2026-IE-036117) -- ver comentario junto al
    patron arriba.

    Devuelve la categoria en MAYUSCULAS (asi es como aparecen las
    opciones del desplegable) o None si ninguna columna calza con el
    patron -- el llamador debe tratar None como "no se pudo determinar
    la categoria" y detenerse a pedir revision manual, nunca adivinar
    una por defecto."""
    for col in columnas_crudas or []:
        m = PATRON_CATEGORIA_PROCESO.match((col or "").strip())
        if m:
            return m.group(1).strip().upper()
    return None


# ------------------------------------------------------------------
# Verificacion del documento REAL (no de la memoria del barrido).
# Evidencia (28-sep, caso 2026-IE-036479): un intento dio el destinatario
# por guardado (SGDEA no lo guardo), el siguiente lo omitio confiando en esa
# memoria y el memorando llego a revision SIN 'Para:'. Ademas, el log muestra
# que justo despues de guardar un modal el editor todavia NO refleja el
# cambio (asunto 0 veces a las 16:02:12 y 16:22:23; 1 vez al reabrir), asi
# que la verificacion se hace con el documento recien abierto.
# ------------------------------------------------------------------
_JS_TEXTO_EDITOR = r"""(args) => {
    const variantes = args.variantes, mayus = !!args.mayus;
    let re = null;
    try { ASPxClientControl.GetControlCollection().ForEachControl(c => { if (!re && c && c.commands && c.commands.findAll) re = c; }); } catch (e) {}
    if (!re) return {api: false};
    let texto = null;
    try { const d = re.document; const sd = d && (d.activeSubDocument || d.mainSubDocument);
          if (sd && typeof sd.text === 'string') texto = sd.text;
          else if (sd && typeof sd.getText === 'function') texto = sd.getText();
          else if (d && typeof d.getText === 'function') texto = d.getText(); } catch (e) {}
    if (typeof texto !== 'string') texto = null;
    const conteos = (variantes || []).map(t => { try { const res = []; const ret = re.commands.findAll.execute(t, mayus, false, res);
        return (res.length ? res : (Array.isArray(ret) ? ret : [])).length; } catch (e) { return 0; } });
    return {api: true, texto, conteos};
}"""


def _sin_tildes(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c))


_TILDE = {"A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú"}


def _variantes_tildes(texto: str, tope: int = 400) -> list:
    """Para nombres: la busqueda del editor distingue tildes, y la peticion
    puede escribir 'HERNANDEZ' donde SGDEA tiene 'HERNÁNDEZ' (o al reves).
    Cada palabra en mayusculas toma su forma sin tilde o con UNA tilde en
    cualquiera de sus vocales. Solo para textos cortos (hasta 6 palabras)."""
    import itertools
    palabras = _sin_tildes(texto).upper().split()
    if not palabras or len(palabras) > 6:
        return []
    opciones = []
    for w in palabras:
        ops = [w] + [w[:i] + _TILDE[c] + w[i + 1:] for i, c in enumerate(w) if c in _TILDE]
        opciones.append(ops)
    total = 1
    for o in opciones:
        total *= len(o)
    if total > tope:
        return []
    return [" ".join(c) for c in itertools.product(*opciones)]


async def _esta_en_documento(page, texto: str, es_nombre: bool = False) -> Optional[bool]:
    """True/False si el documento abierto contiene `texto` (sin importar
    mayusculas, tildes ni espacios); None si la API del editor no responde."""
    texto = " ".join((texto or "").split())
    if not texto:
        return True
    variantes = list(dict.fromkeys([texto, texto.upper(), _sin_tildes(texto), _sin_tildes(texto).upper()]
                                   + (_variantes_tildes(texto) if es_nombre else [])))
    try:
        frame = await _frame_editor_obj(page)
        r = await frame.evaluate(_JS_TEXTO_EDITOR, {"variantes": variantes, "mayus": False})
    except Exception:
        return None
    if not r or not r.get("api"):
        return None
    if isinstance(r.get("texto"), str) and _normalizar(texto) in _normalizar(r["texto"]):
        return True
    if any((n or 0) > 0 for n in (r.get("conteos") or [])):
        return True
    palabras = _sin_tildes(texto).upper().split()
    if es_nombre and len(palabras) >= 3:
        # La peticion puede traer el nombre incompleto (sin segundo nombre):
        # basta con los dos APELLIDOS en MAYUSCULAS (asi va el bloque 'Para:';
        # el saludo los lleva en minusculas, por eso se exige mayuscula).
        apellidos = " ".join(palabras[-2:])
        if isinstance(r.get("texto"), str) and apellidos in _sin_tildes(r["texto"]):
            return True
        try:
            r2 = await frame.evaluate(_JS_TEXTO_EDITOR, {"variantes": _variantes_tildes(apellidos), "mayus": True})
            if r2 and any((n or 0) > 0 for n in (r2.get("conteos") or [])):
                return True
        except Exception:
            pass
    return False


async def _esperar_en_documento(page, texto: str, segundos: float, es_nombre: bool = False) -> Optional[bool]:
    loop = asyncio.get_running_loop()
    limite = loop.time() + segundos
    while True:
        r = await _esta_en_documento(page, texto, es_nombre)
        if r is not False or loop.time() >= limite:
            return r
        await asyncio.sleep(1)


def _elementos_a_verificar(carta, ruta_adjunto: Optional[str] = None) -> list:
    """(paso, que, texto) que el memorando terminado DEBE mostrar."""
    cuerpo = " ".join((getattr(carta, "cuerpo_parrafo", "") or "").split())
    extra = []
    if getattr(carta, "es_masiva", False) and getattr(carta, "tabla", None):
        encabezado = getattr(carta, "tabla_encabezado", None) or ((getattr(carta, "tabla_formato", None) or {}).get("encabezado")) \
            or ENCABEZADO_TABLA_ACTOS
        extra.append(("saludo_y_cuerpo", "la tabla de actos", encabezado[0]))
    if ruta_adjunto:
        # 29-sep: 2026-IE-036231 quedo en revision sin su expediente en 'Nombre anexos'.
        extra.append(("carta_adjuntada", "el adjunto en 'Nombre anexos'", Path(ruta_adjunto).name))
    return extra + [
        ("destinatario_asignado", "el destinatario (Para:)", getattr(carta, "destinatario_nombre", "") or ""),
        ("asunto_asignado", "el asunto", getattr(carta, "asunto", "") or ""),
        ("saludo_y_cuerpo", "el saludo", getattr(carta, "saludo", "") or ""),
        ("saludo_y_cuerpo", "el cuerpo", cuerpo[:60]),
    ]


# 'Nivel 1' (Eje tematico) del MEMORANDO de respuesta segun el 'Proceso' del
# caso. Evidencia (28-sep, caso 2026-IE-036479, captura de Andres con el
# memorando corregido): el caso venia como 'SOLICITUD DE INFORMACION DE
# RESOLUCIONES' pero el memorando va con Eje tematico 'SOLICITUDES INTERNAS
# GENERALES' -- esa otra opcion ni siquiera existe en 'Nivel 1' para el Tipo
# Memorando (se escribio y SGDEA no mostro ninguna lista).
NIVEL1_MEMORANDO = {
    "SOLICITUDES INTERNAS GENERALES": "SOLICITUDES INTERNAS GENERALES",
    "SOLICITUD DE INFORMACION DE RESOLUCIONES": "SOLICITUDES INTERNAS GENERALES",
    # Caso 2026-IE-036323 (pruebas de entrega, Grupo de Recaudo): misma
    # tipificacion de respuesta (si SGDEA no la acepta, el paso 2 se detiene
    # sin guardar -- ver 'No existen más niveles').
    "SOLICITUD DE PRUEBAS DE ENTREGA DOCUMENTOS EXTERNOS ENVIADOS": "SOLICITUDES INTERNAS GENERALES",
}


def nivel1_para_memorando(categoria: str) -> str:
    return NIVEL1_MEMORANDO.get(_normalizar(categoria or ""), categoria or "")


async def gestionar_caso_completo(
    page,
    radicado: str,
    carta,
    coordenada_saludo: Optional[tuple] = None,
    coordenada_cuerpo: Optional[tuple] = None,
    categoria_nivel1: str = "",
    ruta_pdf_carta: Optional[str] = None,
    omitir: Optional[set] = None,
) -> ResultadoAutomatizacion:
    """Deja el "Memorando respuesta" del caso `radicado` completamente
    diligenciado y listo para que Andres SOLO tenga que entrar a
    revisarlo y pulsar el boton de envio a aprobacion el mismo -- esta
    funcion NUNCA lo pulsa (pendiente_revision_humana siempre True en el
    resultado, igual que el resto del modulo).

    `carta` es el objeto que ya arma backend.sgdea_carta.generar_carta()
    (con destinatario_nombre/cargo/subdireccion, asunto, saludo,
    cuerpo_parrafo). `coordenada_saludo`/`coordenada_cuerpo` son las
    coordenadas de click confirmadas con el panel de "Calibración del
    editor" para esos dos campos (los UNICOS que siguen necesitando
    coordenada -- ver la correccion sobre destinatario/asunto al inicio
    de este archivo). `categoria_nivel1` es la categoria a elegir en el
    desplegable 'Nivel 1' del modal de destinatario -- usar
    extraer_categoria_proceso() sobre caso.columnas_crudas para
    obtenerla, y detenerse si da None (no adivinar). `ruta_pdf_carta` es
    opcional: si se pasa, se adjunta con adjuntar_archivo_documento()
    (la via que SI viaja con la comunicacion).

    Pasos, en orden (cada uno solo se intenta si el anterior tuvo
    exito -- ver `pasos_completados` en el resultado para saber donde se
    detuvo si algo falla):
      1. navegar_a_caso (crea el documento si todavia no existe)
      2. seleccionar_destinatario_tipificacion (+ Tipo, Nivel 1, Título)
      3. establecer_asunto
      4. rellenar_saludo_y_cuerpo (API del editor, SIN coordenadas; las
         coordenadas calibradas quedan solo como respaldo opcional del
         cuerpo -- ya no son requisito)
      5. adjuntar_archivo_documento (solo si ruta_pdf_carta no es None)
      6. configurar_tamano_legal (si falla: aviso, NO detiene)
      7. seleccionar_revisor_ema

    NUNCA llama enviar_a_aprobacion ni ningun boton de
    _BOTONES_PROHIBIDOS -- deja el documento ahi, para que Andres
    revise TODO (incluida la firma que quedo o no aislada en su propia
    pagina, ver advertencia de configurar_tamano_legal) antes de decidir
    el mismo cuando enviarlo."""
    pasos: list = []
    token_log = _CONTEXTO_LOG.set("gestionar_caso_completo")
    categoria_caso = categoria_nivel1
    categoria_nivel1 = nivel1_para_memorando(categoria_nivel1)
    _log_paso(f"INICIO caso={radicado!r} categoria_nivel1={categoria_nivel1!r}"
              + (f" (Proceso del caso: {categoria_caso!r})" if categoria_caso != categoria_nivel1 else "")
              + f" adjunto={'si' if ruta_pdf_carta else 'no'}")
    paso_actual = {"n": "0/8 (validacion previa)"}

    # `omitir`: pasos que un intento ANTERIOR ya completo (los guarda el
    # barrido automatico por caso). Se saltan para no repetir trabajo; el
    # paso 1 (abrir el documento) nunca se salta. Cada paso ademas revisa
    # el estado real antes de actuar, asi que esto es una segunda red.
    # Si un intento anterior ya creo el documento, este intento NO debe crear
    # otro (solo abrirlo con 'Ver documentos').
    ya_habia_documento = "navegado_a_caso" in set(omitir or ())
    omitir = set(omitir or ()) - {"navegado_a_caso"}
    a_rehacer: list = []

    def _ya_hecho(numero: str, nombre: str) -> bool:
        if nombre in omitir:
            pasos.append(nombre)
            _log_paso(f"paso {numero}: {nombre} ya se hizo en un intento anterior -- se omite.")
            return True
        return False

    async def _paso(numero: str, nombre: str, coro):
        if _ya_hecho(numero, nombre):
            coro.close()
            return
        paso_actual["n"] = f"{numero} ({nombre})"
        await _esperar_sgdea_libre(page, f"antes del paso {numero}")
        _log_paso(f"paso {numero}: {nombre}...")
        await coro
        pasos.append(nombre)
        _log_paso(f"paso {numero}: OK -- {nombre}")

    async def _todos_los_pasos():
        if not categoria_nivel1:
            raise AutomatizacionError(
                "No se pudo determinar la categoria ('Nivel 1') del caso "
                f"{radicado!r} a partir de sus columnas crudas -- revisar "
                "manualmente cual es el Proceso del caso en SGDEA y "
                "pasarla explicitamente (no se adivina)."
            )
        texto_busqueda = " ".join((carta.destinatario_nombre or "").split()[:2]).lower()
        if not texto_busqueda:
            raise AutomatizacionError(
                f"carta.destinatario_nombre esta vacio para el caso "
                f"{radicado!r} -- no hay con que buscar el destinatario "
                "en el modal 'Destinatario Tipificación'."
            )

        await _paso("1/8", "navegado_a_caso",
                    navegar_a_caso(page, radicado, crear_documento_si_hace_falta=not ya_habia_documento))

        # Lo que un intento anterior dio por hecho se COMPRUEBA en el documento
        # recien abierto; lo que no aparezca se rehace en este mismo intento.
        for nombre_paso, que, texto in _elementos_a_verificar(carta, ruta_pdf_carta):
            if nombre_paso not in omitir:
                continue
            presente = await _esperar_en_documento(page, texto, 6, es_nombre=(nombre_paso == "destinatario_asignado"))
            if presente is False:
                omitir.discard(nombre_paso)
                if nombre_paso not in a_rehacer:
                    a_rehacer.append(nombre_paso)
                _log_paso(f"verificacion: {que} NO aparece en el documento aunque un intento anterior lo dio por "
                          f"hecho -- se rehace '{nombre_paso}'.")

        avisos_destinatario: list = []

        async def _destinatario():
            avisos_destinatario.extend(await seleccionar_destinatario_tipificacion(
                page,
                texto_busqueda=texto_busqueda,
                nombre_exacto=carta.destinatario_nombre,
                tipo_documento="Memorando",
                categoria_nivel1=categoria_nivel1,
                tratamiento=getattr(carta, "tratamiento", None),
                cargo=getattr(carta, "destinatario_cargo", "") or "",
                dependencia=getattr(carta, "destinatario_subdireccion", "") or "",
            ))
        await _paso("2/8", "destinatario_asignado", _destinatario())
        carta.warnings.extend(avisos_destinatario)

        await _paso("3/8", "asunto_asignado", establecer_asunto(page, carta.asunto))
        n_asunto = await buscar_en_documento(page, carta.asunto)
        _log_paso(f"verificacion: el asunto aparece {n_asunto!r} vez/veces en el documento (None = API del editor no disponible).")

        # Paso 4 -- saludo y cuerpo. Ruta principal: API del editor (sin
        # coordenadas). Si no esta disponible NO se detiene la gestion: el
        # resto de pasos se completa y queda un aviso claro para pegarlos a
        # mano (los textos estan en 'Generar respuesta'). El respaldo por
        # coordenada se usa solo para el CUERPO y solo si esta calibrado --
        # el saludo por coordenada pegaba "Cordial Saludo..." DESPUES de un
        # "Saludo," que ya trae la plantilla (quedaba duplicado).
        es_masiva = bool(getattr(carta, "es_masiva", False) and getattr(carta, "tabla", None))
        tabla_pegada = False
        paso_actual["n"] = "4/8 (saludo_y_cuerpo)"
        if _ya_hecho("4/8", "saludo_y_cuerpo"):
            tabla_pegada = not es_masiva
            if es_masiva:
                # El saludo/cuerpo ya estaban, pero la TABLA se comprueba siempre
                # (2026-IE-036323 llego a revision sin ella): si falta, se pega.
                await _esperar_sgdea_libre(page, "antes de revisar la tabla")
                resultado_texto = await rellenar_saludo_y_cuerpo(
                    page, carta.saludo, carta.cuerpo_parrafo, tabla=carta.tabla,
                    encabezado=getattr(carta, "tabla_encabezado", None), formato=getattr(carta, "tabla_formato", None),
                )
                tabla_pegada = resultado_texto in ("api", "ya_estaba")
                _log_paso(f"paso 4/8: tabla de actos -> {resultado_texto}")
        else:
            await _esperar_sgdea_libre(page, "antes del paso 4/8")
            _log_paso("paso 4/8: saludo_y_cuerpo (API del editor, sin coordenadas)...")
            try:
                resultado_texto = await rellenar_saludo_y_cuerpo(
                    page, carta.saludo, carta.cuerpo_parrafo, tabla=carta.tabla if es_masiva else None,
                    encabezado=getattr(carta, "tabla_encabezado", None), formato=getattr(carta, "tabla_formato", None),
                )
                pasos.append("saludo_y_cuerpo")
                tabla_pegada = es_masiva and resultado_texto in ("api", "ya_estaba")
                _log_paso(f"paso 4/8: OK -- saludo_y_cuerpo ({resultado_texto})")
            except AutomatizacionError as exc_api:
                _log_paso(f"paso 4/8: la API del editor no sirvio ({exc_api}).")
                cuerpo_ok = False
                if coordenada_cuerpo and isinstance(exc_api, EditorApiNoDisponible):
                    try:
                        await pegar_en_campo(page, coordenada_cuerpo, carta.cuerpo_parrafo)
                        pasos.append("cuerpo_pegado_por_coordenada")
                        cuerpo_ok = True
                    except AutomatizacionError as exc_coord:
                        _log_paso(f"paso 4/8: respaldo por coordenada tampoco sirvio ({exc_coord}).")
                if cuerpo_ok:
                    aviso = ("El SALUDO no se escribio automaticamente (la API del editor no respondio) -- "
                             f"completar a mano: {carta.saludo}")
                elif not isinstance(exc_api, EditorApiNoDisponible):
                    aviso = f"El saludo y el cuerpo no se escribieron: {exc_api} -- revisar el documento a mano."
                else:
                    aviso = ("El SALUDO y el CUERPO no se escribieron automaticamente (la API del editor no "
                             "respondio y no hay coordenadas calibradas) -- pegarlos a mano desde 'Generar respuesta'.")
                carta.warnings.append(aviso)
                _log_paso(f"AVISO: {aviso}")

        # Casos MASIVOS: la carta trae una tabla (Expediente / Tipo / Numero
        # / Fecha) que este orquestador TODAVIA NO sabe insertar en el
        # editor-canvas (no hay evidencia en vivo de como pegar una tabla
        # ahi). En vez de dar el caso por "listo" en silencio con la tabla
        # faltante, se deja un aviso visible en el dialogo 'Revisar' de
        # Memorandos (carta.warnings viaja a CasoPendiente.warnings).
        # Andres (29-sep): un caso masivo NUNCA pasa a revision sin su tabla.
        # Se detiene aqui; el reintento (4 min) solo pega la tabla.
        if es_masiva and not tabla_pegada:
            raise AutomatizacionError(
                "Caso MASIVO: la tabla de actos no quedo en el documento -- se reintenta pegarla "
                "(el caso no pasa a revision sin la tabla)."
            )

        # Paso 5 -- tamaño Legal. Va ANTES de la revisora: al guardar la
        # revisora SGDEA guarda el documento ("La información se guardó
        # exitosamente"), asi el tamaño queda guardado aunque no haya adjunto.
        # Si falla NO impide la revisora (solo aviso).
        await _esperar_sgdea_libre(page, "antes del tamaño Legal")
        paso_actual["n"] = "5/8 (tamano_legal)"
        try:
            if _ya_hecho("5/8", "tamano_legal_configurado"):
                raise _PasoOmitido()
            await configurar_tamano_legal(page)
            pasos.append("tamano_legal_configurado")
            _log_paso("paso 5/8: OK -- tamano_legal_configurado")
        except _PasoOmitido:
            pass
        except Exception as exc_legal:
            try:
                await page.keyboard.press("Escape")  # cerrar cualquier menu que haya quedado abierto
            except Exception:
                pass
            aviso = f"No se pudo poner el tamaño de pagina en Legal ({str(exc_legal).splitlines()[0][:200]}) -- hacerlo a mano."
            carta.warnings.append(aviso)
            _log_paso(f"AVISO: {aviso}")

        await _paso("6/8", "revisor_asignado", seleccionar_revisor_ema(page))

        # Pasos 7 y 8 -- en el orden del video de Andres (25-sep): despues de
        # la revisora, 'Anexo' = 1 y luego subir el PDF en 'Anexos al
        # documento'. No bloquean: si fallan quedan como aviso.
        if ruta_pdf_carta:
            paso_actual["n"] = "7/8 (anexos_contados)"
            if not _ya_hecho("7/8", "anexos_contados"):
                _log_paso("paso 7/8: anexos_contados...")
                try:
                    estado_anexos = await establecer_numero_anexos(page, 1)
                    pasos.append("anexos_contados")
                    _log_paso(f"paso 7/8: OK -- anexos_contados ({estado_anexos})")
                except Exception as exc_anx:
                    aviso = f"No se pudo poner 'Anexo' = 1 ({str(exc_anx).splitlines()[0][:200]}) -- ponerlo a mano (icono 'Anexo')."
                    carta.warnings.append(aviso)
                    _log_paso(f"AVISO: {aviso}")
        if ruta_pdf_carta and _ya_hecho("8/8", "carta_adjuntada"):
            pass
        elif ruta_pdf_carta:
            await _esperar_sgdea_libre(page, "antes de subir el adjunto")
            paso_actual["n"] = "8/8 (carta_adjuntada)"
            _log_paso("paso 8/8: carta_adjuntada...")
            try:
                estado_adjunto = await adjuntar_archivo_documento(page, ruta_pdf_carta)
                pasos.append("carta_adjuntada")
                _log_paso(f"paso 8/8: OK -- carta_adjuntada ({estado_adjunto})")
                if estado_adjunto == "sin_verificar":
                    carta.warnings.append(f"Revisar que 'Nombre anexos' muestre {Path(ruta_pdf_carta).name}.")
            except Exception as exc_adj:
                aviso = f"No se pudo adjuntar {Path(ruta_pdf_carta).name} ({str(exc_adj).splitlines()[0][:200]}) -- adjuntarlo a mano."
                carta.warnings.append(aviso)
                _log_paso(f"AVISO: {aviso}")
        else:
            _log_paso("pasos 7-8/8: omitidos (sin acuse 4-72 para adjuntar)")

        # Revision final con el documento RECIEN REABIERTO (el editor no
        # refleja lo guardado por los modales hasta recargar). Si falta algo,
        # el caso NO pasa a revision: se rehace en el siguiente intento.
        paso_actual["n"] = "revision final"
        await _esperar_sgdea_libre(page, "antes de la revision final")
        _log_paso("revision final: reabriendo el documento para comprobar lo que quedo guardado...")
        try:
            await navegar_a_caso(page, radicado, crear_documento_si_hace_falta=False)
        except Exception as exc_reabrir:
            aviso = (f"No se pudo reabrir el documento para la revision final ({str(exc_reabrir).splitlines()[0][:160]}) "
                     "-- revisar a mano que tenga destinatario (Para:), asunto, saludo y cuerpo.")
            carta.warnings.append(aviso)
            _log_paso(f"AVISO: {aviso}")
            return
        faltan, sin_api = [], False
        for nombre_paso, que, texto in _elementos_a_verificar(carta, ruta_pdf_carta):
            presente = await _esperar_en_documento(page, texto, 15, es_nombre=(nombre_paso == "destinatario_asignado"))
            if presente is None:
                sin_api = True
                break
            if presente is False:
                faltan.append((nombre_paso, que))
        if sin_api:
            aviso = ("No se pudo leer el documento para la revision final (API del editor) -- revisar a mano "
                     "destinatario (Para:), asunto, saludo y cuerpo.")
            carta.warnings.append(aviso)
            _log_paso(f"AVISO: {aviso}")
            return
        if faltan:
            for nombre_paso, _ in faltan:
                while nombre_paso in pasos:
                    pasos.remove(nombre_paso)
                if nombre_paso not in a_rehacer:
                    a_rehacer.append(nombre_paso)
            raise AutomatizacionError(
                "Revision final: el memorando NO muestra " + ", ".join(q for _, q in faltan)
                + " -- no pasa a revision; se rehace en el proximo intento."
            )
        _log_paso("revision final: OK -- destinatario, asunto, saludo y cuerpo presentes en el documento.")


    # Tope de tiempo GLOBAL por caso (sesion 2026-09-27): cada llamada de
    # Playwright ya tiene su propio timeout, pero una corrida entera no
    # tenia ninguno -- si algo quedaba esperando indefinidamente (p.ej. un
    # page.mouse.click contra un navegador que se cerro/crasheo), el
    # handler de main.py nunca llegaba a su `finally` y el candado de
    # automatizacion quedaba tomado para siempre. Con este tope la corrida
    # siempre termina, con un mensaje que dice en que paso se quedo.
    try:
        await asyncio.wait_for(_todos_los_pasos(), timeout=TIMEOUT_CASO_COMPLETO_SEG)
        _log_paso("FIN -- exito, todos los pasos completados")
        return ResultadoAutomatizacion(ok=True, pasos_completados=pasos, pasos_a_rehacer=a_rehacer, warnings=list(getattr(carta, "warnings", []) or []))
    except asyncio.TimeoutError:
        msg = (
            f"La gestion del caso {radicado!r} supero el tope de "
            f"{TIMEOUT_CASO_COMPLETO_SEG // 60} minutos y se detuvo en el paso "
            f"{paso_actual['n']} -- revisar manualmente en que pantalla quedo "
            "SGDEA antes de reintentar."
        )
        _log_paso(f"FIN -- TIMEOUT tras pasos={pasos}: {msg}")
        return ResultadoAutomatizacion(ok=False, pasos_completados=pasos, pasos_a_rehacer=a_rehacer, warnings=[msg])
    except AutomatizacionError as exc:
        await _capturar_pantalla(page, f"{radicado}_fallo")
        _log_paso(f"FIN -- AutomatizacionError en paso {paso_actual['n']} tras pasos={pasos}: {exc}")
        return ResultadoAutomatizacion(ok=False, pasos_completados=pasos, pasos_a_rehacer=a_rehacer, warnings=[str(exc)])
    except Exception as exc:  # nunca dejar una excepcion cruda sin contexto
        await _capturar_pantalla(page, f"{radicado}_error")
        _log_paso(f"FIN -- error inesperado ({type(exc).__name__}) en paso {paso_actual['n']} tras pasos={pasos}: {exc}")
        return ResultadoAutomatizacion(
            ok=False,
            pasos_completados=pasos,
            pasos_a_rehacer=a_rehacer,
            warnings=[f"Error inesperado ({type(exc).__name__}) en paso {paso_actual['n']}: {exc}"],
        )
    finally:
        _CONTEXTO_LOG.reset(token_log)


# ------------------------------------------------------------------
# Rehacer el cuadro y el adjunto de un memorando que YA esta en revision
# (Andres, 1-oct, caso 2026-IE-036987: llego a revision sin los expedientes que
# hubo que pedirle a Magda; cuando estan en Descargas\\<radicado>\\ el cuadro
# debe relacionarlos todos y el ZIP traerlos). NUNCA envia a aprobacion. Si el
# memorando ya no esta en la revision de Andres (la cinta no dice 'Inicio ciclo
# de aprobación') no se toca.
# ------------------------------------------------------------------
TEXTO_NO_SE_TOCA = "no se toca el memorando"


def _nombre_libre(ruta: str, usados: set) -> str:
    p = Path(ruta)
    if p.name not in usados:
        return str(p)
    for i in range(2, 50):
        cand = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if cand.name not in usados:
            import shutil
            shutil.copyfile(p, cand)
            return str(cand)
    raise AutomatizacionError("No se encontro un nombre libre para el adjunto nuevo.")


async def rehacer_tabla_y_adjunto(page, radicado: str, carta, ruta_adjunto: Optional[str],
                                  adjuntos_anteriores: Optional[list] = None) -> ResultadoAutomatizacion:
    """Abre el memorando, cambia el cuadro de actos por el de `carta.tabla`
    (verificado y guardado) y sube `ruta_adjunto` (con otro nombre si el
    documento ya muestra ese). Nunca crea documentos ni envia a aprobacion."""
    pasos: list = []
    avisos: list = list(getattr(carta, "warnings", []) or [])
    token_log = _CONTEXTO_LOG.set("rehacer_tabla_y_adjunto")
    formato = getattr(carta, "tabla_formato", None)
    encabezado = list(getattr(carta, "tabla_encabezado", None) or (formato or {}).get("encabezado")
                      or ENCABEZADO_TABLA_ACTOS)
    tabla = getattr(carta, "tabla", None) if getattr(carta, "es_masiva", False) else None

    async def _verificar_tabla(que: str) -> None:
        n_cab = await buscar_en_documento(page, encabezado[0])
        faltan = []
        for fila in tabla:
            for dato in (str(fila[-1]), str(fila[1])):
                if dato and not await buscar_en_documento(page, dato):
                    faltan.append(dato)
        if n_cab != 1 or faltan:
            raise AutomatizacionError(f"{que}: el cuadro nuevo no se ve completo en el documento (encabezados: {n_cab!r}, "
                                      f"faltan: {faltan[:6]}) -- revisa el memorando a mano.")

    async def _todo():
        _log_paso(f"INICIO caso={radicado!r} filas={len(tabla) if tabla else 0} "
                  f"adjunto={Path(ruta_adjunto).name if ruta_adjunto else '-'}")
        await _esperar_sgdea_libre(page, "antes de abrir el memorando")
        await navegar_a_caso(page, radicado, crear_documento_si_hace_falta=False)
        frame = page.frame_locator(IFRAME_DOCUMENTOS)
        if await _primer_visible(frame.get_by_text(PATRON_BOTON_INICIO_CICLO), timeout_ms=15000) is None:
            raise AutomatizacionError(
                "El memorando ya no está en tu revisión (la cinta no dice 'Inicio ciclo de aprobación'): "
                f"{TEXTO_NO_SE_TOCA}. Si hay que corregirlo, hazlo a mano.")
        pasos.append("navegado_a_caso")
        if tabla:
            fo = await _frame_editor_obj(page)
            res = await fo.evaluate(_JS_EDITOR_API, {"accion": "borrar_tabla", "saludo": carta.saludo,
                                                     "cuerpo": carta.cuerpo_parrafo, "marca_tabla": encabezado[0],
                                                     "tabla": True})
            _log_paso(f"cuadro anterior: {res!r}")
            if not res.get("ok"):
                raise AutomatizacionError(f"No se pudo quitar el cuadro anterior ({res.get('motivo')}) -- "
                                          f"{TEXTO_NO_SE_TOCA}; revísalo a mano.")
            try:
                await _pegar_tabla_actos(page, fo, tabla, encabezado, formato)
            except Exception as exc:
                try:
                    await fo.evaluate(_JS_EDITOR_API, {"accion": "deshacer", "saludo": carta.saludo,
                                                       "cuerpo": carta.cuerpo_parrafo})
                except Exception:
                    pass
                raise AutomatizacionError(f"No se pudo pegar el cuadro nuevo ({exc}); se deshizo el borrado del anterior "
                                          f"(nada se guardó) -- {TEXTO_NO_SE_TOCA}.") from None
            await _verificar_tabla("recién pegado")
            # 'Guardar' del modal 'Anexo' guarda el documento (como en el paso 7 normal)
            await establecer_numero_anexos(page, 1, forzar_guardar=True)
            await navegar_a_caso(page, radicado, crear_documento_si_hace_falta=False)
            await _verificar_tabla("tras guardar y reabrir")
            pasos.append("tabla_rehecha")
            _log_paso(f"cuadro nuevo con {len(tabla)} fila(s) guardado y verificado.")
        if ruta_adjunto:
            previos = [n for n in (adjuntos_anteriores or []) if n]
            usados = set()
            for n in dict.fromkeys(previos + [Path(ruta_adjunto).name]):
                if await buscar_en_documento(page, n):
                    usados.add(n)
            ruta_final = _nombre_libre(ruta_adjunto, usados)
            estado = await adjuntar_archivo_documento(page, ruta_final)
            pasos.append("carta_adjuntada")
            await navegar_a_caso(page, radicado, crear_documento_si_hace_falta=False)
            if not await buscar_en_documento(page, Path(ruta_final).name):
                raise AutomatizacionError(f"Se subió {Path(ruta_final).name} pero el documento no lo muestra en "
                                          "'Nombre anexos'.")
            quedan = [n for n in usados if n != Path(ruta_final).name and await buscar_en_documento(page, n)]
            if quedan:
                avisos.append(f"El memorando conserva también el anexo anterior ({', '.join(sorted(quedan))}): quítalo en "
                              f"'Anexos al documento' antes de aprobar; el completo es {Path(ruta_final).name}.")
            _log_paso(f"adjunto nuevo {Path(ruta_final).name} ({estado}).")
        if tabla:
            await _verificar_tabla("revisión final")

    try:
        await asyncio.wait_for(_todo(), timeout=TIMEOUT_CASO_COMPLETO_SEG)
        _log_paso("FIN -- cuadro y adjunto rehechos.")
        return ResultadoAutomatizacion(ok=True, pasos_completados=pasos, warnings=avisos)
    except asyncio.TimeoutError:
        return ResultadoAutomatizacion(ok=False, pasos_completados=pasos, warnings=[
            f"Rehacer el cuadro superó el tope de tiempo (pasos: {pasos}) -- revisa el memorando."])
    except AutomatizacionError as exc:
        await _capturar_pantalla(page, f"{radicado}_rehacer")
        _log_paso(f"FIN -- {exc}")
        return ResultadoAutomatizacion(ok=False, pasos_completados=pasos, warnings=[str(exc)])
    except Exception as exc:  # noqa: BLE001
        await _capturar_pantalla(page, f"{radicado}_rehacer_error")
        return ResultadoAutomatizacion(ok=False, pasos_completados=pasos, warnings=[
            f"Error inesperado ({type(exc).__name__}) al rehacer el cuadro: {exc}"])
    finally:
        _CONTEXTO_LOG.reset(token_log)


# ------------------------------------------------------------------
# Envio a aprobacion -- la funcion que de verdad pulsa el boton
# prohibido-para-el-resto-del-modulo. Ver la nota junto a
# _BOTONES_PROHIBIDOS arriba: esta es la UNICA excepcion, y solo debe
# llamarse quien orquesta el click explicito de Andres en "Aprobar y
# enviar" dentro del aplicativo (ver ejecutar_flujo_aprobacion mas abajo
# y la seccion "Memorandos" de main.py) -- NUNCA de forma pasiva o en
# segundo plano sin ese click.
# ------------------------------------------------------------------

# Textos candidatos para el boton que efectivamente confirma/envia el
# ciclo de aprobacion DENTRO del dialogo que se abre al pulsar el boton
# del ribbon. NO CONFIRMADO EN VIVO -- ver advertencia en
# enviar_a_aprobacion().
# Evidencia (capturas de Andres, 27-sep, caso 2026-IE-036192): con la
# revisora ya asignada, el grupo "Gestionar" de la cinta muestra el boton
# "Inicio ciclo de aprobación"; al pulsarlo abre el modal "Comentarios" con
# un campo de texto (contador 0 / 2000) y los botones "Cerrar" / "Inicio de
# Ciclo". La version anterior buscaba "Enviar"/"Iniciar"/"Aceptar"/
# "Guardar" -- ninguno existe en ese modal.
PATRON_BOTON_INICIO_CICLO = re.compile(r"^\s*Inicio\s+ciclo\s+de\s+aprobaci[oó]n\s*$", re.IGNORECASE)
PATRON_BOTON_SOLICITAR_APROBACION = re.compile(r"^\s*Solicitar\s+aprobaci[oó]n\s*$", re.IGNORECASE)
TEXTO_BOTON_CONFIRMAR_CICLO = "Inicio de Ciclo"
LIMITE_CARACTERES_COMENTARIO = 2000


async def enviar_a_aprobacion(page, mensaje: str) -> None:
    """UNICO paso irreversible del modulo. Solo se llama cuando Andres pulsa
    'Aprobar' / 'Aprobar y enviar' en Insignia (nunca en segundo plano).

    Exige ver 'Inicio ciclo de aprobación' (revisora asignada). Si la cinta
    todavia dice 'Solicitar aprobación' (sin revisora), se detiene: ese es
    otro flujo, sin captura, y no se adivina."""
    if len(mensaje) > LIMITE_CARACTERES_COMENTARIO:
        raise AutomatizacionError(f"El mensaje tiene {len(mensaje)} caracteres; el maximo es {LIMITE_CARACTERES_COMENTARIO}.")
    frame = page.frame_locator(IFRAME_DOCUMENTOS)
    boton = await _primer_visible(frame.get_by_text(PATRON_BOTON_INICIO_CICLO), timeout_ms=5000)
    if boton is None:
        if await _primer_visible(frame.get_by_text(PATRON_BOTON_SOLICITAR_APROBACION), timeout_ms=0) is not None:
            raise AutomatizacionError(
                "La cinta dice 'Solicitar aprobación' (no 'Inicio ciclo de aprobación'): el documento "
                "no tiene revisora asignada. No se envia -- correr primero 'Gestionar caso completo'."
            )
        raise AutomatizacionError("No se encontro el boton 'Inicio ciclo de aprobación'." + await _diagnostico_pagina(page))
    _log_paso("enviar_a_aprobacion: click en 'Inicio ciclo de aprobación'...")
    await boton.click()

    _, modal = await _modal_por_titulo(page, re.compile(r"^\s*Comentarios\s*$"), boton=TEXTO_BOTON_CONFIRMAR_CICLO)
    if modal is None:
        raise AutomatizacionError("Se pulso 'Inicio ciclo de aprobación' pero no aparecio el modal 'Comentarios'." + await _diagnostico_pagina(page))
    campo = await _primer_visible(modal.locator("textarea"), timeout_ms=3000)
    if campo is None:
        raise AutomatizacionError("El modal 'Comentarios' no muestra su campo de texto.")
    await campo.click()
    await campo.fill(mensaje)
    if (await campo.input_value()).strip() != mensaje.strip():
        raise AutomatizacionError("El comentario no quedo escrito tal cual en el modal -- no se envia.")
    # Aqui NO se interpreta el aviso posterior: el ciclo ya se inicio y un
    # texto inesperado no debe hacer creer que fallo (evita un doble envio).
    await _guardar_modal_y_esperar_cierre(page, modal, "Comentarios", boton_texto=TEXTO_BOTON_CONFIRMAR_CICLO,
                                          revisar_aviso=False)

    if await _pagina_parece_login(page):
        raise AutomatizacionError(
            "Despues de 'Inicio de Ciclo' la pagina parece la de login -- verificar a mano en SGDEA "
            "si el ciclo quedo iniciado."
        )
    _log_paso("enviar_a_aprobacion: OK -- ciclo de aprobacion iniciado.")


# ------------------------------------------------------------------
# Orquestador de alto nivel -- pensado para llamarse desde la seccion
# "Memorandos" del aplicativo Flet (main.py) cuando Andres pulsa "Aprobar
# y enviar" sobre un CasoPendiente. Hace SOLO la navegacion + el envio a
# aprobacion (NO vuelve a pegar la carta ni a adjuntar el archivo -- eso
# ya quedo hecho cuando el caso se agrego a la cola, ver
# casos_pendientes.py).
# ------------------------------------------------------------------

async def ejecutar_flujo_aprobacion(
    radicado: str,
    mensaje: str,
    cdp_url: str = "http://localhost:9222",
    page=None,
) -> ResultadoAutomatizacion:
    """Conecta al Chrome que Andres ya tiene abierto, navega al caso
    `radicado`, y ejecuta enviar_a_aprobacion(mensaje) sobre el
    documento que ya deberia estar listo (carta pegada, adjunto cargado,
    revisor asignado -- todo eso hecho ANTES de que el caso llegara a la
    cola de casos_pendientes.json).

    Pensada para ser llamada UNICAMENTE como reaccion directa al click
    de Andres en 'Aprobar y enviar' dentro del aplicativo -- nunca de
    forma automatica/pasiva. Cierra siempre la conexion de Playwright
    (aunque falle), pero DELIBERADAMENTE deja el Chrome real de Andres
    abierto (nunca lo cierra: es su navegador, no uno propio de la
    automatizacion).

    Devuelve un ResultadoAutomatizacion; en caso de error, `ok=False` y
    el mensaje queda en `warnings` -- el llamador (main.py) es quien
    decide si marcar el caso como 'error' via
    casos_pendientes.marcar_error()."""
    # `page` opcional (sesion 2026-09-27): si main.py ya tiene la sesion
    # PROPIA de SGDEA conectada (backend/sgdea_session.py), la pasa aqui y
    # NO hace falta el Chrome de depuracion (puerto 9222) abierto -- antes
    # 'Aprobar' fallaba siempre que Andres trabajaba solo con la sesion
    # propia, aunque 'Gestionar caso completo' si funcionara con ella.
    pasos: list[str] = []
    playwright = browser = None
    token_log = _CONTEXTO_LOG.set("ejecutar_flujo_aprobacion")
    try:
        if page is None:
            playwright, browser, context = await conectar_chrome_existente(cdp_url)
            if not context.pages:
                raise AutomatizacionError(
                    "El Chrome conectado no tiene ninguna pestaña abierta."
                )
            page = context.pages[0]
            pasos.append("conectado_chrome")
        else:
            pasos.append("sesion_propia_sgdea")
        _log_paso(f"INICIO caso={radicado!r} (envio a aprobacion, click explicito de Andres)")

        await navegar_a_caso(page, radicado)
        pasos.append("navegado_a_caso")

        await enviar_a_aprobacion(page, mensaje)
        pasos.append("enviado_a_aprobacion")
        _log_paso("FIN -- enviado a aprobacion")

        return ResultadoAutomatizacion(ok=True, pasos_completados=pasos)
    except AutomatizacionError as exc:
        _log_paso(f"FIN -- AutomatizacionError tras pasos={pasos}: {exc}")
        return ResultadoAutomatizacion(ok=False, pasos_completados=pasos, warnings=[str(exc)])
    except Exception as exc:  # nunca dejar una excepcion cruda sin contexto
        _log_paso(f"FIN -- error inesperado ({type(exc).__name__}) tras pasos={pasos}: {exc}")
        return ResultadoAutomatizacion(
            ok=False,
            pasos_completados=pasos,
            warnings=[f"Error inesperado ({type(exc).__name__}): {exc}"],
        )
    finally:
        _CONTEXTO_LOG.reset(token_log)
        # OJO -- NUNCA llamar aqui a browser.close(): en una conexion CDP
        # (connect_over_cdp) ese Browser NO es "nuestro" -- es el Chrome
        # real que Andres ya tenia abierto y logueado. browser.close()
        # manda el comando CDP 'Browser.close', que SI cierra la ventana
        # de Chrome real (confirmado en vivo, sesion 2026-09-23: tras un
        # primer uso exitoso, la siguiente conexion se quedaba colgada
        # sin error -- el Chrome de depuracion ya no estaba). Solo se
        # detiene el lado de Playwright (playwright.stop()), que es lo
        # unico que nos pertenece.
        if playwright is not None:
            await playwright.stop()

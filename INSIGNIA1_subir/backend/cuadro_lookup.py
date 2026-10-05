"""
Lector OPCIONAL de Cuadro_2026: permite, para un Resolucion/Auto dado,
saber cuantos notificados/comunicados se esperan y -- lo mas importante --
si alguno de ellos es una persona JURIDICA (una institucion de educacion
superior investigada, por ejemplo), con su nombre oficial.

Por que hace falta esto y no basta con lo que ya se extrae de cada Acta:
cuando un Auto se notifica al investigado (persona natural) y se COMUNICA
ademas a una institucion (por ejemplo a su representante legal o su
apoderado), el Acta de esa comunicacion suele traer el nombre de la
PERSONA que firma por la institucion (ej. "Jorge Enrique Senior Martinez"),
no el nombre de la institucion (ej. "Universidad Autonoma del Caribe").
Para nombrar el expediente final con el nombre de la institucion -- que es
lo que se pidio -- hace falta cruzar contra Cuadro_2026, que si trae la
columna "NOMBRE PERSONA JURIDICA" para esas filas.

Estructura observada en Cuadro_2026 (hojas "RESOLUCIONES" y "AUTOS"): cada
acto administrativo ocupa una o varias filas consecutivas. Solo la PRIMERA
fila de cada acto trae el numero en la columna "No. Resolucion"/"No. Auto";
las filas siguientes lo dejan en blanco -- son notificados/comunicados
adicionales de ESE MISMO acto (family/continuacion). Por eso el indice se
arma haciendo "forward fill" del numero hacia abajo.

Este modulo es completamente opcional: si el usuario no configura una ruta
a Cuadro_2026, o el archivo no se puede leer, el resto del programa sigue
funcionando exactamente igual que sin este cruce (ver los usos en main.py,
siempre dentro de try/except).

--------------------------------------------------------------------------
Cruce por Expediente (agregado para automatizar respuestas SGDEA)
--------------------------------------------------------------------------
Cuadro_2026/2025 tiene ADEMAS una columna "NUMERO DE SOLICITUD DE PROCESO"
que es, verificado contra datos reales, exactamente el numero de
"Expediente EE-XXXXXX" que trae toda peticion interna: es el criterio que
Andres usa a diario para individualizar, a partir del numero de expediente
que allega el peticionario, exactamente que Resolucion/Auto es (y de ahi
sacar la fecha, el nombre completo, la cedula, etc. -- toda la informacion
necesaria esta en el propio Cuadro, no hay que inventarla ni cruzarla con
nada mas).

Ese numero de expediente casi siempre identifica un unico acto, pero no
siempre (se encontraron ~560 casos en RESOLUCIONES, de 20 mil, con 2 filas
para el mismo expediente -- ej. una Resolucion inicial y luego otra
posterior para la misma persona). Por eso `buscar_por_expediente` devuelve
una LISTA: cuando trae mas de un resultado, hace falta el "criterio
compuesto" que menciona Andres (nombre, cedula, tipo de acto, numero de
acto, si la peticion los trae) para desempatar -- eso lo hace quien use
este indice (ver backend/sgdea_carta.py), no este modulo.

`ActoPorExpediente.tipo_tramite` (columna 'TIPO DE TRAMITE') y su
propiedad `es_archivo`: confirmado por Andres (caso real 2025-EE-104761,
Auto de Archivo No. 2336) que un "Auto de Archivo" se cita en la carta
SOLO por su fecha, sin el numero interno que trae el Cuadro (ese numero es
de uso interno del Cuadro, no algo que se comunique) -- a diferencia de un
Auto/Resolucion normal, donde el numero SI va en la carta (verificado
contra una respuesta real ya aprobada). `es_archivo` es lo que usa
backend/sgdea_carta.py para decidir cual de las dos redacciones usar.
"""
from __future__ import annotations

import dataclasses
import functools
from pathlib import Path
from typing import Optional


class CuadroError(Exception):
    """No se pudo cargar o leer Cuadro_2026 con la estructura esperada."""


@dataclasses.dataclass
class NotificadoEsperado:
    tipo_persona: str          # "Natural" | "Juridica" | (lo que traiga la celda)
    nombre_juridica: str       # nombre oficial de la institucion, si aplica
    cargo: str
    direccion_electronica: str


@dataclasses.dataclass
class ActoPorExpediente:
    """Una fila de RESOLUCIONES/AUTOS encontrada por su numero de
    Expediente EE-XXXXXX (columna 'NUMERO DE SOLICITUD DE PROCESO')."""
    tipo: str                  # "Resolucion" | "Auto"
    numero: str                # numero oficial del acto, sin ceros a la izquierda
    fecha: Optional[str]       # dd/mm/aaaa (misma convencion que extractor.py); None si no se pudo leer
    nombre: str                # nombre completo tal como esta en el Cuadro
    cedula: str
    tipo_persona: str
    expediente: str = ""       # 'NUMERO DE SOLICITUD DE PROCESO' (EE-XXXXXX) de la fila
    tipo_aa: str = ""          # 'TIPO AA SEGÚN TIPO DE TRAMITE' (ej. "Recurso de Apelación")
    email: str = ""            # 'DIRECCIÓN ELECTRÓNICA' de la persona notificada en esa fila
    radicado_interno: str = "" # 'NUMERO DE RADICADO' (2026-IE-XXXXXX): comunicacion interna con
                                # la que la dependencia pidio notificar el acto (caso 2026-IE-036323)
    tipo_tramite: str = ""     # columna 'TIPO DE TRAMITE' (ej. "Auto de Archivo") --
                                # confirmado por Andres: un "Auto de Archivo" se cita en
                                # la carta SOLO por su fecha, sin el numero interno del
                                # Cuadro (ese numero es de uso interno, no se comunica)

    @property
    def es_archivo(self) -> bool:
        """True si el tramite es de tipo "Auto de Archivo": ver nota de
        `tipo_tramite` -- cambia como se redacta la carta (sin numero)."""
        return "archivo" in self.tipo_tramite.lower()


@dataclasses.dataclass
class NotificacionElectronica:
    fecha: Optional[str]       # dd/mm/aaaa
    radicado: str              # 2026-EE-XXXXXX
    email: str = ""


@dataclasses.dataclass
class CuadroIndex:
    resoluciones: dict            # numero normalizado -> list[NotificadoEsperado]
    autos: dict                   # numero normalizado -> list[NotificadoEsperado]
    por_expediente: dict = dataclasses.field(default_factory=dict)  # expediente -> list[ActoPorExpediente]
    por_radicado_interno: dict = dataclasses.field(default_factory=dict)  # 2026-IE-XXXXXX -> list[ActoPorExpediente]
    notificaciones: dict = dataclasses.field(default_factory=dict)  # (tipo, numero) -> list[NotificacionElectronica]

    def notificacion_electronica(self, tipo: str, numero) -> list:
        """Columnas 'FECHA NOTIFICACION ELECTRONICA' y 'RADICADO NOTIFICACION
        ELECTRONICA' de cada fila del acto (1-oct: los Autos 1510 y 1939 se
        notificaron como 'Comunicación de respuesta (<ese radicado EE>)' desde
        mineducacion472, no desde notificacionesmen)."""
        key = _numero_key(numero)
        return list((getattr(self, "notificaciones", None) or {}).get((tipo, key), [])) if key else []

    def notificados_esperados(self, tipo: str, numero) -> list:
        key = _numero_key(numero)
        if key is None:
            return []
        tabla = self.resoluciones if tipo == "Resolucion" else self.autos
        return tabla.get(key, [])

    def nombre_institucion(self, tipo: str, numero) -> Optional[str]:
        """Si alguno de los notificados esperados de este acto es una
        persona juridica con nombre registrado, lo devuelve (el primero
        que aparezca). None si no aplica o no hay dato."""
        for n in self.notificados_esperados(tipo, numero):
            if _is_juridica(n.tipo_persona) and n.nombre_juridica:
                return n.nombre_juridica
        return None

    def buscar_por_numero(self, tipo: str, numero) -> list:
        """Todos los actos del Cuadro con ese tipo y numero (una Resolucion
        puede cubrir a varias personas/expedientes: entonces vuelven varios
        y quien llama NO elige -- no se adivina). Evidencia: 2026-IE-036295
        pide 'Resolución 021685 del 06 de agosto de 2026' sin expediente."""
        key = _numero_key(numero)
        if key is None:
            return []
        return [a for actos in self.por_expediente.values() for a in actos if a.tipo == tipo and a.numero == key]

    def buscar_por_radicado_interno(self, radicado: str) -> list:
        """Actos (uno por tipo+numero, en el orden del Cuadro) que se
        notificaron por pedido de la comunicacion interna `radicado` (columna
        'NUMERO DE RADICADO'). Metodo de Andres para 2026-IE-036323: 'se
        ubican las resoluciones por numero de radicado interno en el
        Cuadro_2026'. Cada acto trae el correo de su fila PRINCIPAL (la que
        lleva el numero); los demas destinatarios quedan en `otros_correos`."""
        filas = self.por_radicado_interno.get(_norm_text(radicado).upper(), [])
        vistos: dict = {}
        for a in filas:
            clave = (a.tipo, a.numero)
            if clave not in vistos:
                vistos[clave] = a
        return list(vistos.values())

    def correos_de_acto(self, radicado: str, tipo: str, numero: str) -> list:
        filas = self.por_radicado_interno.get(_norm_text(radicado).upper(), [])
        return [a.email for a in filas if a.tipo == tipo and a.numero == numero and a.email]

    def correos_del_acto(self, tipo: str, numero, correo_principal: str = "", radicado_interno: str = "") -> list:
        """TODOS los correos que el Cuadro registra para un acto (fila principal
        + filas de continuacion), el principal primero. Regla de Andres
        (29-sep): cada correo es un destinatario y su acuse va al expediente.
        Por numero solo se confia en el indice del año principal si ese indice
        contiene el correo principal (asi no se mezcla con otro acto del mismo
        numero de otro año)."""
        import re as _re
        def partir(t):
            return [c.lower() for c in _re.split(r"[;,\s/]+", t or "") if "@" in c]
        principal = partir(correo_principal)
        if radicado_interno:
            filas = self.correos_de_acto(radicado_interno, tipo, _numero_key(numero) or "")
        else:
            filas = [n.direccion_electronica for n in self.notificados_esperados(tipo, numero)]
        todos = [c for f in filas for c in partir(f)]
        if principal and not radicado_interno and not set(principal) & set(todos):
            todos = []
        return list(dict.fromkeys(principal + todos))

    def buscar_por_cedula(self, cedula: str) -> list:
        """Actos del Cuadro de la persona con esa cedula (solo digitos). Sirve
        cuando el expediente de la peticion no aparece (Andres, 29-sep:
        'buscar por numero de expediente y cedula, y la fecha que ya nos dan')."""
        import re as _re
        clave = _re.sub(r"\D", "", str(cedula or ""))
        if len(clave) < 5:
            return []
        indice = getattr(self, "_por_cedula", None)
        if indice is None:
            indice = {}
            for actos in self.por_expediente.values():
                for a in actos:
                    k = _re.sub(r"\D", "", a.cedula or "")
                    if k:
                        indice.setdefault(k, []).append(a)
            object.__setattr__(self, "_por_cedula", indice)
        return list(indice.get(clave, []))

    def buscar_por_expediente(self, expediente: str) -> list:
        """Todos los actos (Resolucion y/o Auto) registrados en el Cuadro
        bajo este numero de Expediente EE-XXXXXX. Normalmente una lista de
        1 elemento; ver nota del modulo sobre cuando trae mas de uno."""
        key = _norm_text(expediente).upper()
        return self.por_expediente.get(key, [])


def _norm_text(v) -> str:
    if v is None:
        return ""
    text = str(v).replace("\r", " ").replace("\n", " ").strip()
    while "  " in text:
        text = text.replace("  ", " ")
    return text


def _is_juridica(tipo_persona: str) -> bool:
    return (tipo_persona or "").strip().lower().startswith("jur")


def _numero_key(v) -> Optional[str]:
    """Normaliza un numero de acto (venga como int, float o texto con
    ceros a la izquierda) a una clave de texto comparable."""
    if v is None or v == "":
        return None
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        s = str(v).strip()
        if not s:
            return None
        stripped = s.lstrip("0")
        return stripped or "0"


_MES_NUM = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10,
    "NOVIEMBRE": 11, "DICIEMBRE": 12,
}


def _fecha_dia_mes_anio(dia, mes_texto, anio) -> Optional[str]:
    """Las columnas DIA/MES/ANIO de Cuadro_2026 traen el mes en texto
    ('SEPTIEMBRE') y el dia/anio como numero. Se arma 'dd/mm/aaaa' (misma
    convencion que extractor.py). None si algo no se puede interpretar --
    nunca se inventa una fecha a medias."""
    mes_num = _MES_NUM.get(_norm_text(mes_texto).upper())
    if mes_num is None:
        return None
    try:
        dia_num = int(float(dia))
        anio_num = int(float(anio))
    except (TypeError, ValueError):
        return None
    return f"{dia_num:02d}/{mes_num:02d}/{anio_num}"


def _nombre_completo(*partes) -> str:
    return _norm_text(" ".join(p for p in (_norm_text(x) for x in partes) if p))


def _parse_sheet_por_expediente(
    ws,
    tipo: str,
    col_numero: int,
    col_dia: int,
    col_mes: int,
    col_anio: int,
    col_expediente: int,
    col_cedula: int,
    col_tipo_persona: int,
    col_nombres: list,
    col_tipo_tramite: Optional[int] = None,
    col_tipo_aa: Optional[int] = None,
    col_email: Optional[int] = None,
) -> dict:
    """Indice expediente EE-XXXXXX -> list[ActoPorExpediente], con
    forward-fill del numero de acto igual que _parse_sheet (solo la
    primera fila de cada acto trae el numero)."""
    out: dict = {}
    current_key: Optional[str] = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row is None:
            continue
        raw_num = row[col_numero] if col_numero < len(row) else None
        key = _numero_key(raw_num)
        if key is not None:
            current_key = key
        if current_key is None:
            continue

        raw_exp = row[col_expediente] if col_expediente < len(row) else None
        exp_key = _norm_text(raw_exp).upper()
        if not exp_key:
            continue

        fecha = _fecha_dia_mes_anio(
            row[col_dia] if col_dia < len(row) else None,
            row[col_mes] if col_mes < len(row) else None,
            row[col_anio] if col_anio < len(row) else None,
        )
        nombre = _nombre_completo(*(row[c] if c < len(row) else None for c in col_nombres))
        tipo_tramite = ""
        if col_tipo_tramite is not None and col_tipo_tramite < len(row):
            tipo_tramite = _norm_text(row[col_tipo_tramite])
        acto = ActoPorExpediente(
            tipo=tipo,
            numero=current_key,
            fecha=fecha,
            nombre=nombre,
            cedula=_norm_text(row[col_cedula] if col_cedula < len(row) else ""),
            tipo_persona=_norm_text(row[col_tipo_persona] if col_tipo_persona < len(row) else ""),
            tipo_tramite=tipo_tramite,
            expediente=exp_key,
            tipo_aa=_norm_text(row[col_tipo_aa]) if col_tipo_aa is not None and col_tipo_aa < len(row) else "",
            email=_norm_text(row[col_email]).lower() if col_email is not None and col_email < len(row) else "",
        )
        out.setdefault(exp_key, []).append(acto)
    return out


def _parse_sheet_por_radicado(ws, tipo: str, col_numero: int, col_dia: int, col_mes: int, col_anio: int,
                              col_radicado: int, col_expediente: int, col_cedula: int, col_tipo_persona: int,
                              col_nombres: list, col_juridica: int, col_email: int,
                              col_tipo_tramite: int, col_tipo_aa: int) -> dict:
    """Indice 'NUMERO DE RADICADO' (2026-IE-XXXXXX) -> list[ActoPorExpediente].
    Las filas de continuacion (sin numero: mas destinatarios del MISMO acto)
    heredan el numero y la fecha de la fila principal."""
    import re as _re
    out: dict = {}
    current_key: Optional[str] = None
    current_fecha: Optional[str] = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row is None:
            continue
        def celda(c):
            return row[c] if c is not None and c < len(row) else None
        key = _numero_key(celda(col_numero))
        if key is not None:
            current_key = key
            current_fecha = _fecha_dia_mes_anio(celda(col_dia), celda(col_mes), celda(col_anio))
        if current_key is None:
            continue
        rad = _norm_text(celda(col_radicado)).upper()
        if not _re.fullmatch(r"\d{4}-IE-\d+", rad):
            continue
        juridica = _norm_text(celda(col_juridica))
        nombre = juridica or _nombre_completo(*(celda(c) for c in col_nombres))
        out.setdefault(rad, []).append(ActoPorExpediente(
            tipo=tipo, numero=current_key, fecha=current_fecha, nombre=nombre,
            cedula=_norm_text(celda(col_cedula)), tipo_persona=_norm_text(celda(col_tipo_persona)),
            expediente=_norm_text(celda(col_expediente)).upper(), radicado_interno=rad,
            tipo_tramite=_norm_text(celda(col_tipo_tramite)), tipo_aa=_norm_text(celda(col_tipo_aa)),
            email=_norm_text(celda(col_email)).lower(),
        ))
    return out


def _parse_sheet_notificaciones(ws, tipo: str, col_numero: int, col_email: int,
                                col_fecha_notif: int = 41, col_radicado_notif: int = 42) -> dict:
    """(tipo, numero) -> [NotificacionElectronica] (filas de continuacion heredan el numero).
    Columnas 41/42 confirmadas en el encabezado real de Cuadro_2026 (3), ambas hojas."""
    import datetime as _dt
    import re as _re
    out: dict = {}
    current_key: Optional[str] = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row is None:
            continue
        def celda(c):
            return row[c] if c is not None and c < len(row) else None
        key = _numero_key(celda(col_numero))
        if key is not None:
            current_key = key
        if current_key is None:
            continue
        m = _re.search(r"(\d{4})\s*-\s*EE\s*-\s*(\d+)", _norm_text(celda(col_radicado_notif)).upper())
        if not m:
            continue
        f = celda(col_fecha_notif)
        fecha = f.strftime("%d/%m/%Y") if isinstance(f, (_dt.datetime, _dt.date)) else None
        out.setdefault((tipo, current_key), []).append(NotificacionElectronica(
            fecha=fecha, radicado=f"{m.group(1)}-EE-{m.group(2)}", email=_norm_text(celda(col_email)).lower()))
    return out


def _parse_sheet(
    ws,
    col_numero: int,
    col_tipo_persona: int,
    col_nombre_juridica: int,
    col_cargo: int,
    col_email: int,
) -> dict:
    out: dict = {}
    current_key: Optional[str] = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row is None:
            continue
        raw_num = row[col_numero] if col_numero < len(row) else None
        key = _numero_key(raw_num)
        if key is not None:
            current_key = key
        if current_key is None:
            continue
        notificado = NotificadoEsperado(
            tipo_persona=_norm_text(row[col_tipo_persona] if col_tipo_persona < len(row) else ""),
            nombre_juridica=_norm_text(row[col_nombre_juridica] if col_nombre_juridica < len(row) else ""),
            cargo=_norm_text(row[col_cargo] if col_cargo < len(row) else ""),
            direccion_electronica=_norm_text(row[col_email] if col_email < len(row) else ""),
        )
        out.setdefault(current_key, []).append(notificado)
    return out


@functools.lru_cache(maxsize=2)
def _load_cached(path: str, mtime: float) -> CuadroIndex:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws_res = wb["RESOLUCIONES"]
        ws_aut = wb["AUTOS"]
    except KeyError as exc:
        wb.close()
        raise CuadroError(
            f"El archivo no tiene las hojas esperadas (RESOLUCIONES/AUTOS): {exc}"
        )

    # Indices de columna confirmados sobre el encabezado real de Cuadro_2026.
    resoluciones = _parse_sheet(
        ws_res, col_numero=3, col_tipo_persona=5, col_nombre_juridica=12, col_cargo=13, col_email=19
    )
    autos = _parse_sheet(
        ws_aut, col_numero=3, col_tipo_persona=6, col_nombre_juridica=13, col_cargo=14, col_email=20
    )

    # Indice adicional por Expediente EE-XXXXXX (columna 'NUMERO DE SOLICITUD
    # DE PROCESO'), verificado contra peticiones y respuestas reales.
    por_expediente_res = _parse_sheet_por_expediente(
        ws_res, tipo="Resolucion", col_numero=3, col_dia=0, col_mes=1, col_anio=2,
        col_expediente=25, col_cedula=7, col_tipo_persona=5, col_nombres=[8, 9, 10, 11],
        col_tipo_tramite=22, col_tipo_aa=23, col_email=19,
    )
    por_expediente_aut = _parse_sheet_por_expediente(
        ws_aut, tipo="Auto", col_numero=3, col_dia=0, col_mes=1, col_anio=2,
        col_expediente=26, col_cedula=8, col_tipo_persona=6, col_nombres=[9, 10, 11, 12],
        col_tipo_tramite=23, col_tipo_aa=24, col_email=20,
    )
    por_expediente = por_expediente_res
    for k, v in por_expediente_aut.items():
        por_expediente.setdefault(k, []).extend(v)

    # Indice por 'NUMERO DE RADICADO' (comunicacion interna que pidio la
    # notificacion): columna 28 en RESOLUCIONES y 29 en AUTOS (encabezado real).
    por_radicado = _parse_sheet_por_radicado(
        ws_res, tipo="Resolucion", col_numero=3, col_dia=0, col_mes=1, col_anio=2, col_radicado=28,
        col_expediente=25, col_cedula=7, col_tipo_persona=5, col_nombres=[8, 9, 10, 11], col_juridica=12,
        col_email=19, col_tipo_tramite=22, col_tipo_aa=23,
    )
    for k, v in _parse_sheet_por_radicado(
        ws_aut, tipo="Auto", col_numero=3, col_dia=0, col_mes=1, col_anio=2, col_radicado=29,
        col_expediente=26, col_cedula=8, col_tipo_persona=6, col_nombres=[9, 10, 11, 12], col_juridica=13,
        col_email=20, col_tipo_tramite=23, col_tipo_aa=24,
    ).items():
        por_radicado.setdefault(k, []).extend(v)

    notificaciones = _parse_sheet_notificaciones(ws_res, "Resolucion", col_numero=3, col_email=19)
    notificaciones.update(_parse_sheet_notificaciones(ws_aut, "Auto", col_numero=3, col_email=20))

    wb.close()
    return CuadroIndex(resoluciones=resoluciones, autos=autos, por_expediente=por_expediente,
                       por_radicado_interno=por_radicado, notificaciones=notificaciones)


def load_cuadro(path: str | Path) -> CuadroIndex:
    """Carga (con cache por ruta+fecha de modificacion, para no releer un
    archivo de ~9MB en cada expediente) el indice de notificados esperados
    desde Cuadro_2026. Lanza CuadroError si el archivo no existe o no tiene
    la estructura esperada."""
    p = Path(path)
    if not p.exists():
        raise CuadroError(f"No se encontro el archivo: {p}")
    mtime = p.stat().st_mtime
    return _load_cached(str(p), mtime)


def con_cuadro_anterior(principal: CuadroIndex, anterior: Optional[CuadroIndex]) -> CuadroIndex:
    """Suma al indice POR EXPEDIENTE los actos del Cuadro del año anterior
    (Cuadro_2025): hay peticiones de 2026 sobre expedientes resueltos en 2025
    (p.ej. 2025-EE-148605 -> Resolución 20211 del 10/10/2025). Los indices por
    NUMERO se dejan solo con el principal: la numeracion se reinicia cada año
    y mezclarlos confundiria actos distintos con el mismo numero."""
    if anterior is None:
        return principal
    por_expediente = {k: list(v) for k, v in principal.por_expediente.items()}
    for k, v in anterior.por_expediente.items():
        existentes = por_expediente.setdefault(k, [])
        claves = {(a.tipo, a.numero, a.fecha) for a in existentes}
        existentes.extend(a for a in v if (a.tipo, a.numero, a.fecha) not in claves)
    por_radicado = {k: list(v) for k, v in principal.por_radicado_interno.items()}
    for k, v in anterior.por_radicado_interno.items():
        por_radicado.setdefault(k, list(v))
    return CuadroIndex(resoluciones=principal.resoluciones, autos=principal.autos, por_expediente=por_expediente,
                       por_radicado_interno=por_radicado,
                       notificaciones=getattr(principal, "notificaciones", None) or {})

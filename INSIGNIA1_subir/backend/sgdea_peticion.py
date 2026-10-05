"""
Lector de la PETICION entrante (el PDF que llega radicado en SGDEA y que hay
que responder mediante un Memorando respuesta).

Que resuelve este modulo:

1. A quien va dirigida la respuesta (el "destinatario"): el nombre, cargo y
   subdireccion de quien FIRMA la peticion. Se lee del bloque de firma al
   final del documento, que siempre sigue el mismo patron:

       Cordialmente,
       @FirmaDigitalTMS@
       <NOMBRE COMPLETO>
       <CARGO>
       <SUBDIRECCION>

2. De donde sale el numero de "Expediente EE-XXXXXX" que aparece en el
   cuadro de una respuesta masiva. NO se genera ni se busca en ningun lado
   del pipeline 4-72 (ni en Cuadro_2026, ni en las Actas/Acuses): sale
   directamente de la propia tabla de anexos que trae la peticion, con
   columnas [Nombre, Cedula, Expediente, Numero de Resolucion/Auto].
   Se confirmo leyendo la peticion real del radicado 2026-IE-034750 con
   pdfplumber (pypdf mezcla el texto de la tabla sin espacios y no sirve
   para esto).

Lo que la tabla de anexos SI trae para cada fila, y lo que falta:
  - Nombre, Cedula, Expediente: siempre completos.
  - Numero de acto: viene en dos formatos distintos segun el tipo:
      * Resolucion: "020128_2026" -> tipo=Resolucion, numero=20128 (se le
        quitan los ceros a la izquierda), pero SIN fecha.
      * Auto: "Auto de 01 de septiembre de 2026" -> tipo=Auto,
        numero=<no aplica>, fecha=01/09/2026 (la fecha SI viene incluida).
  - Para las filas de Resolucion, la fecha no esta en este PDF: hay que
    cruzarla con lo que el pipeline 4-72 ya proceso para ese mismo
    numero (ver backend/sgdea_carta.py), y si no se encuentra, se deja en
    blanco y se marca como advertencia -- nunca se inventa una fecha.

IMPORTANTE (corregido por Andres, caso real 2026-IE-035142): la tabla de
anexos de arriba es el formato de las peticiones MASIVAS, pero segun
Andres esas son la EXCEPCION -- la MAYORIA de las peticiones llegan
individuales, en texto corrido dentro del cuerpo de la carta, sin ninguna
tabla. Ejemplo real (caso 2026-IE-035142): "...solicitamos su
colaboración encaminada a remitirnos copia del Auto de Archivo emitido en
el expediente 2025-EE-104761, a nombre de LINA ISABEL CASTAÑO CARDENAS,
así como la constancia de su notificación...". Por eso
`extraer_anexos_solicitados` primero intenta tablas (para las peticiones
masivas que sí las traen) y, si no encuentra ninguna, cae a un modo de
lectura de PROSA LIBRE (`_extraer_anexos_prosa`) que busca, por cada
mencion de un numero de expediente en el texto, el nombre del titular
("a nombre de <NOMBRE>") y a que tipo de acto se refiere (frases como
"Resolución No. NNNNN", "Auto No. NNNNN", "Auto de fecha DD de MES de
AAAA", o el caso especial "Auto de Archivo" -- este ultimo no trae numero
propio en la peticion, se identifica en el Cuadro solo por tipo +
expediente). Al no ser un formato tan rigido como la tabla, cuando no se
reconoce el tipo de acto o no aparece "a nombre de ..." se marca como
advertencia en vez de adivinar -- igual que con la tabla, nunca se inventa
un dato que no está en el texto. Esta parte del extractor solo se probo,
por ahora, contra el texto exacto leido a mano del caso 2026-IE-035142 (no
contra el PDF real en bytes, que Andres todavia no ha subido) -- falta
confirmar contra mas peticiones reales en prosa para afinar los patrones.

Este modulo no toca SGDEA ni el navegador: solo lee un PDF local con
pdfplumber (que reconstruye tablas mucho mejor que pypdf/extractor.py) y
devuelve datos estructurados.
"""
from __future__ import annotations

import dataclasses
import re
import unicodedata
from pathlib import Path
from typing import Optional

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

# "020128_2026" -> grupo numerico + año (Resolucion)
_RE_RESOLUCION = re.compile(r"^(\d+)_(\d{4})$")
# "Auto de 01 de septiembre de 2026" / "Auto de 5 de agosto de 2026" (Auto)
_RE_AUTO = re.compile(
    r"^Auto\s+de\s+(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+de\s+(\d{4})$",
    re.IGNORECASE,
)
_RE_RADICADO = re.compile(r"Radicado\s+No\.?\s*\n?\s*([0-9A-Za-z\-]+)")
_RE_EXPEDIENTE = re.compile(r"\d{4}-[A-Z]{2}-\d+")
# En PROSA solo cuentan los expedientes 'EE'. Evidencia (28-sep, 11
# peticiones reales): el texto tambien trae el radicado de la propia
# peticion ('2026-IE-035688', en el encabezado) y radicados de recursos
# ('2026-ER-0336194'); tomarlos como anexos hacia que TODA peticion pareciera
# masiva y el caso se quedara sin su PDF adjunto.
_RE_EXPEDIENTE_EE = re.compile(r"\b(?:\d{4}-EE-\d+|CNV-\d{4}-\d+)\b")
# 1-oct (2026-IE-036987): expedientes ANTIGUOS 'CNV-2019-0004045' (formato de
# antes de 2020) y el EE escrito con guiones dobles ('2021--EE--255254').
_RE_EE_GUIONES = re.compile(r"(\d{4})\s*-{1,3}\s*EE\s*-{1,3}\s*(\d+)")
_RE_CNV = re.compile(r"\bCNV\s*-\s*(\d{4})\s*-\s*(\d+)", re.IGNORECASE)


def normalizar_expedientes(texto: str) -> str:
    """'2021--EE--255254' -> '2021-EE-255254'; 'cnv - 2019 - 0004045' -> 'CNV-2019-0004045'."""
    texto = _RE_EE_GUIONES.sub(r"\1-EE-\2", texto or "")
    return _RE_CNV.sub(lambda m: f"CNV-{m.group(1)}-{m.group(2)}", texto)


def anio_expediente(expediente: str) -> Optional[int]:
    """Año del expediente: '2021-EE-255254' -> 2021; 'CNV-2019-0004045' -> 2019."""
    m = re.match(r"^(\d{4})-EE-|^CNV-(\d{4})-", (expediente or "").strip().upper())
    return int(m.group(1) or m.group(2)) if m else None

# --- patrones para peticiones individuales en PROSA (sin tabla) ---
# "a nombre de LINA ISABEL CASTAÑO CARDENAS, así como..." -> el nombre en
# mayusculas hasta la siguiente coma/punto/"así"/"para".
_RE_A_NOMBRE_DE = re.compile(
    r"a\s+nombre\s+de(?:l|\s+la|\s+el)?\s+(?:(?:señora?|ciudadan[oa])\s+)?"
    r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ.\s]+?)(?=\s*[,.;:–—-]|\s+así\b|\s+para\b|\s+[Cc]aso\b|\s+identificad|\s+con\b|\s*$)"
)
# Listas con viñetas: "2024-EE-098297 — NOMBRE APELLIDO" /
# "2026-EE-000001 - NOMBRE APELLIDO – CC. 10000000"
_RE_EXPEDIENTE_GUION_NOMBRE = re.compile(
    r"(\d{4}-EE-\d+|CNV-\d{4}-\d+)\s*[—–-]\s*(?:(?:Convalidante|Titular|Solicitante|Ciudadan[oa])\s*:\s*)?"
    r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ.]+(?:[ \t]+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ.]+)*(?:\s*\n\s*[A-ZÁÉÍÓÚÑ]{2,}(?:[ \t]+[A-ZÁÉÍÓÚÑ]{2,})*)?)"
    r"(?=\s*[—–-]|\s+CC\b|\s*\n|\s*$)"
)
# caso especial: "el Auto de Archivo" no trae numero propio en la peticion
_RE_PROSA_AUTO_ARCHIVO = re.compile(r"Auto\s+de\s+Archivo", re.IGNORECASE)
# "Auto de fecha 01 de septiembre de 2026" (variante en prosa del formato
# de tabla "Auto de 01 de septiembre de 2026")
_RE_PROSA_AUTO_FECHA = re.compile(
    r"Auto\s+de\s+fecha\s+(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+de\s+(\d{4})",
    re.IGNORECASE,
)
# "Resolución No. 12345" / "Resolución 12345" / "Resolución Nro. 12345"
_RE_PROSA_RESOLUCION_NUM = re.compile(
    r"Resoluci[oó]n\s*(?:No\.?|Nro\.?|N°|número)?\s*(\d+)", re.IGNORECASE
)
# "Auto No. 456" / "Auto 456" -- se revisa DESPUES de Auto de Archivo/fecha
_RE_PROSA_AUTO_NUM = re.compile(
    r"Auto\s*(?:No\.?|Nro\.?|N°|número)?\s*(\d+)", re.IGNORECASE
)


def _norm_cell(v) -> str:
    """Las celdas de pdfplumber traen saltos de linea internos cuando el
    contenido ocupa mas de una linea dentro de la celda (nombres largos,
    cedulas con puntos). Se normaliza a una sola linea con espacios."""
    if v is None:
        return ""
    text = str(v).replace("\n", " ").strip()
    while "  " in text:
        text = text.replace("  ", " ")
    return text


def _parse_fecha_espanol(dia: str, mes_texto: str, anio: str) -> Optional[str]:
    """'01', 'septiembre', '2026' -> '01/09/2026' (mismo formato dd/mm/aaaa
    que usa extractor.py). None si el mes no se reconoce."""
    mes_num = _MESES.get(mes_texto.strip().lower())
    if mes_num is None:
        return None
    try:
        dia_num = int(dia)
    except ValueError:
        return None
    return f"{dia_num:02d}/{mes_num:02d}/{anio}"


@dataclasses.dataclass
class AnexoSolicitado:
    """Una fila de la tabla de anexos de la peticion: un acto administrativo
    (Resolucion o Auto) sobre el que se pide respuesta."""
    nombre: str
    cedula: str
    expediente: str          # ej. "2025-EE-331829"
    tipo: str                # "Resolucion" | "Auto" | "Desconocido"
    numero: str               # numero del acto, sin ceros a la izquierda ("" si tipo=Auto)
    fecha: Optional[str]      # dd/mm/aaaa; solo se conoce aqui para tipo=Auto
    texto_original: str       # el texto crudo de la 4a columna, para trazabilidad
    warnings: list = dataclasses.field(default_factory=list)
    # "Apelación" / "Reposición" si la peticion pide expresamente la
    # resolucion de ese recurso (p.ej. 2026-IE-035664: "resoluciones de
    # apelación correspondientes a los siguientes expedientes"). Sirve para
    # elegir entre varios actos del mismo expediente en el Cuadro.
    recurso: str = ""
    # Año del acto: el de '011897_2024' o el de la fecha del Auto. Andres
    # (29-sep, 2026-IE-036696): todo lo ANTERIOR A 2025 se le pide a Magda.
    anio: Optional[int] = None


@dataclasses.dataclass
class Destinatario:
    """A quien va dirigida la respuesta: quien firma la peticion."""
    nombre: str
    cargo: str
    subdireccion: str
    # True si el nombre tambien aparece en la casilla 'Aprobó' del documento.
    confirmado: bool = False
    # Deliberadamente NO se intenta adivinar "Doctor"/"Doctora": eso lo
    # decide Andres al leer el nombre (ver diseño, Fase 3). Inventar un
    # genero a partir del nombre puede fallar y no hay forma de verificarlo
    # aqui.


@dataclasses.dataclass
class PeticionInfo:
    radicado: Optional[str]
    destinatario: Optional[Destinatario]
    anexos: list  # list[AnexoSolicitado]
    warnings: list = dataclasses.field(default_factory=list)
    # Peticiones de PRUEBAS / CONSTANCIAS DE ENTREGA de comunicaciones masivas
    # (caso 2026-IE-036323): no traen tabla de actos sino los radicados
    # internos (2026-IE-XXXXXX) con los que se pidio notificar. Los actos se
    # ubican en el Cuadro por su columna 'NUMERO DE RADICADO'.
    radicados_internos: list = dataclasses.field(default_factory=list)
    # 1-oct: cuantos casos pide la peticion en su lista (viñetas/numerales o
    # filas de la tabla), y cuales vienen repetidos. None = no hay lista.
    casos_en_lista: Optional[int] = None
    duplicados: list = dataclasses.field(default_factory=list)

    @property
    def por_radicados_internos(self) -> bool:
        return bool(self.radicados_internos) and not self.anexos

    @property
    def es_masiva(self) -> bool:
        return len(self.anexos) > 1 or self.por_radicados_internos


def _extraer_tipo_numero_fecha(texto_col4: str) -> tuple[str, str, Optional[str], list]:
    """Interpreta la 4a columna de una fila de anexos. Devuelve
    (tipo, numero, fecha, warnings)."""
    texto = texto_col4.strip()
    warnings: list = []

    m = _RE_RESOLUCION.match(texto)
    if m:
        digitos, _anio = m.groups()
        numero = str(int(digitos))  # quita ceros a la izquierda
        return "Resolucion", numero, None, warnings

    m = _RE_AUTO.match(texto)
    if m:
        dia, mes_texto, anio = m.groups()
        fecha = _parse_fecha_espanol(dia, mes_texto, anio)
        if fecha is None:
            warnings.append(f"No se pudo interpretar el mes en '{texto}'")
        return "Auto", "", fecha, warnings

    warnings.append(f"Formato de numero de acto no reconocido: '{texto}'")
    return "Desconocido", texto, None, warnings


def _extraer_tipo_numero_fecha_prosa(fragmento: str) -> tuple[str, str, Optional[str], list]:
    """Version de `_extraer_tipo_numero_fecha` para texto corrido (prosa),
    no para la 4a columna de una tabla. Prueba, de lo mas especifico a lo
    mas generico, las frases conocidas en las que suele venir el tipo de
    acto en una peticion individual. Nunca adivina: si no reconoce nada,
    devuelve "Desconocido" con una advertencia."""
    warnings: list = []

    if _RE_PROSA_AUTO_ARCHIVO.search(fragmento):
        # "el Auto de Archivo": no trae numero propio en la peticion: se
        # identifica en el Cuadro por tipo (+ expediente) unicamente, igual
        # que cuando el tipo se sabe pero el numero/fecha no.
        return "Auto", "", None, warnings

    m = _RE_PROSA_AUTO_FECHA.search(fragmento)
    if m:
        dia, mes_texto, anio = m.groups()
        fecha = _parse_fecha_espanol(dia, mes_texto, anio)
        if fecha is None:
            warnings.append(f"No se pudo interpretar el mes en '{fragmento.strip()}'")
        return "Auto", "", fecha, warnings

    m = _RE_PROSA_RESOLUCION_NUM.search(fragmento)
    if m:
        return "Resolucion", str(int(m.group(1))), None, warnings

    m = _RE_PROSA_AUTO_NUM.search(fragmento)
    if m:
        return "Auto", str(int(m.group(1))), None, warnings

    warnings.append(
        f"No se reconocio a que tipo de acto (Resolución/Auto) se refiere: "
        f"'{fragmento.strip()}'"
    )
    return "Desconocido", "", None, warnings


def _extraer_anexos_prosa(texto: str) -> list[AnexoSolicitado]:
    """Extrae anexos de una peticion INDIVIDUAL escrita en texto corrido,
    sin tabla -- el formato mas comun segun Andres (las tablas son la
    excepcion, no la regla). Por cada numero de expediente mencionado en el
    texto, junta la informacion (nombre, tipo, numero, fecha) de TODOS los
    fragmentos donde aparece ese mismo expediente -- una peticion suele
    mencionarlo mas de una vez (en el "Asunto:" y otra vez en el cuerpo), y
    cada mencion puede traer una parte distinta del dato (p. ej. el Asunto
    dice el tipo de acto pero el cuerpo trae el "a nombre de ..."). Nunca
    se mezclan datos de dos expedientes distintos entre si."""
    # Un numero de expediente partido entre dos lineas ("2026-EE-\n088887")
    # se vuelve a unir; los fragmentos son ORACIONES (no lineas): el tipo de
    # acto y el expediente suelen quedar en lineas distintas de la misma
    # oracion (caso real 2026-IE-035688). "No. 2026-EE-..." no parte la
    # oracion porque despues del punto viene un numero.
    texto = re.sub(r"(\d{4}-EE-)\s*\n\s*(\d+)", r"\1\2", texto)
    texto = re.sub(r"(\d{4}-)\s*\n\s*(EE-\d+)", r"\1\2", texto)
    texto = normalizar_expedientes(texto)
    nombres_viñeta = {m.group(1): _norm_cell(m.group(2)) for m in _RE_EXPEDIENTE_GUION_NOMBRE.finditer(texto)}
    fragmentos = [
        f.replace("\n", " ")
        for f in re.split(r"(?<=\.)\s+(?=[A-ZÁÉÍÓÚÑ¿•])|\n\s*(?=[•\-–—]\s|\d{4}-EE-)", texto)
    ]

    info_por_expediente: dict = {}
    orden: list = []
    for fragmento in fragmentos:
        for m in _RE_EXPEDIENTE_EE.finditer(fragmento):
            expediente = m.group(0)
            if expediente not in info_por_expediente:
                info_por_expediente[expediente] = {
                    "tipo": "Desconocido",
                    "numero": "",
                    "fecha": None,
                    "nombre": "",
                    "warnings": [],
                    "fragmentos": [],
                }
                orden.append(expediente)
            info = info_por_expediente[expediente]
            info["fragmentos"].append(fragmento.strip())

            tipo, numero, fecha, warns_tipo = _extraer_tipo_numero_fecha_prosa(fragmento)
            if tipo != "Desconocido" and info["tipo"] == "Desconocido":
                info["tipo"], info["numero"], info["fecha"] = tipo, numero, fecha
            elif tipo != "Desconocido" and tipo != info["tipo"]:
                info["warnings"].append(
                    f"El expediente {expediente} aparece asociado a mas de un "
                    f"tipo de acto en el texto ('{info['tipo']}' y '{tipo}'); "
                    f"se conservo el primero -- revisar a mano"
                )

            nombre_m = _RE_A_NOMBRE_DE.search(fragmento)
            if expediente in nombres_viñeta and not info["nombre"]:
                info["nombre"] = nombres_viñeta[expediente]
            elif nombre_m and not info["nombre"]:
                info["nombre"] = _norm_cell(nombre_m.group(1))

    if not orden:
        # Sin ningun expediente EE: la peticion pide el acto por su NUMERO
        # (caso real 2026-IE-036295: "copia de la Resolución 021685 del 06 de
        # agosto de 2026"). Se deja el expediente vacio; resolver_actos lo
        # busca en el Cuadro por tipo + numero.
        plano = " ".join(texto.split())
        vistos: set = set()
        filas_num: list[AnexoSolicitado] = []
        for m in re.finditer(
            r"Resoluci[oó]n\s*(?:No\.?|Nro\.?|N°|número)?\s*(\d{3,})(?:\s+del?\s+(\d{1,2})\s+de\s+([A-Za-záéíóú]+)\s+de\s+(\d{4}))?",
            plano, re.IGNORECASE,
        ):
            numero = str(int(m.group(1)))
            if numero in vistos:
                continue
            vistos.add(numero)
            fecha = _parse_fecha_espanol(m.group(2), m.group(3), m.group(4)) if m.group(2) else None
            filas_num.append(AnexoSolicitado(
                nombre="", cedula="", expediente="", tipo="Resolucion", numero=numero, fecha=fecha,
                texto_original=m.group(0), warnings=[],
            ))
        # 29-sep-2026 (v1.5.10), evidencia 2026-IE-036741: la peticion pide
        # "1. Auto de fecha 25 de agosto de 2026 ..." y "2. Resolución No. 017766
        # del 03 de julio de 2026" sin expediente EE; solo se leia la Resolucion
        # (log: "1 acto(s) solicitado(s)"), y la respuesta habria salido sin el
        # Auto. Ahora el Auto tambien se lista; sin expediente ni numero el Cuadro
        # no lo puede ubicar con certeza, asi que queda como "no identificado"
        # (aviso para Andres) -- nunca se adivina ni se omite en silencio.
        fechas_auto: set = set()
        for m in _RE_PROSA_AUTO_FECHA.finditer(plano):
            fecha = _parse_fecha_espanol(m.group(1), m.group(2), m.group(3))
            if fecha is None or fecha in fechas_auto:
                continue
            fechas_auto.add(fecha)
            filas_num.append(AnexoSolicitado(
                nombre="", cedula="", expediente="", tipo="Auto", numero="", fecha=fecha,
                texto_original=m.group(0),
                warnings=[f"Auto del {fecha} pedido sin expediente ni número: ubicarlo a mano en el Cuadro"],
            ))
        return filas_num

    filas: list[AnexoSolicitado] = []
    for expediente in orden:
        info = info_por_expediente[expediente]
        if expediente in nombres_viñeta and not info["nombre"]:
            info["nombre"] = nombres_viñeta[expediente]
        warns = list(info["warnings"])
        if not info["nombre"]:
            warns.append(
                f"No se encontro 'a nombre de <NOMBRE>' para el expediente "
                f"{expediente}; la peticion puede identificar al titular de "
                f"otra forma -- revisar a mano"
            )
        if info["tipo"] == "Desconocido":
            warns.append(
                f"No se reconocio a que tipo de acto (Resolución/Auto) se "
                f"refiere el expediente {expediente} -- revisar a mano"
            )
        filas.append(
            AnexoSolicitado(
                nombre=info["nombre"],
                cedula="",  # las peticiones en prosa normalmente no traen cedula
                expediente=expediente,
                tipo=info["tipo"],
                numero=info["numero"],
                fecha=info["fecha"],
                texto_original=" / ".join(info["fragmentos"]),
                warnings=warns,
            )
        )
    # 1-oct (2026-IE-036987): la peticion trae expedientes Y, en otra lista,
    # resoluciones pedidas solo por su numero ("• Resolución N° 1156 del 30 de
    # abril de 2026."). Esa viñeta no tiene expediente y se perdia EN SILENCIO
    # (el caso llego a revision sin ella). Ahora cada viñeta/numeral con una
    # Resolucion sin expediente tambien es un anexo; el Cuadro la ubica por
    # numero (+ fecha) y, si no calza, queda como aviso (no se adivina).
    ya = {(f.tipo, f.numero) for f in filas if f.numero}
    for fragmento in fragmentos:
        f = fragmento.strip()
        if not re.match(r"^(?:[•▪●]|[\-–—]\s|\d{1,2}[.)]\s)", f) or _RE_EXPEDIENTE_EE.search(f):
            continue
        for m in re.finditer(
            r"Resoluci[oó]n\s*(?:No\.?|Nro\.?|N°|N\.°|número)?\s*0*(\d{3,})"
            r"(?:\s+del?\s+(\d{1,2})\s+de\s+([A-Za-záéíóú]+)\s+de\s+(\d{4}))?",
            f, re.IGNORECASE,
        ):
            numero = str(int(m.group(1)))
            if ("Resolucion", numero) in ya:
                continue
            ya.add(("Resolucion", numero))
            fecha = _parse_fecha_espanol(m.group(2), m.group(3), m.group(4)) if m.group(2) else None
            filas.append(AnexoSolicitado(
                nombre="", cedula="", expediente="", tipo="Resolucion", numero=numero, fecha=fecha,
                texto_original=f, warnings=[],
            ))
    return filas


# Formatos de tabla vistos el 29-sep (casos 2026-IE-036658 y 036693):
#   'Resolución No.' | 'Proceso de convalidación' | 'convalidante'
#       '24431de4deseptiembrede2026' | '2025-EE-174755' | 'EDNA PRIMITIVA ...'
#   cedula | expediente | '024289_2026' o 'Auto de 01 de septiembre de 2026'
# (3 columnas y sin espacios): se ubica cada dato por su FORMA, no por su
# posicion.
_RE_NUM_Y_FECHA = re.compile(
    r"^0*(\d{2,6})\s*del?\s*(\d{1,2})\s*de\s*([A-Za-zÁÉÍÓÚáéíóúñÑ]+?)\s*(?:de|del)?\s*(\d{4})$", re.IGNORECASE)
_RE_AUTO_PEGADO = re.compile(
    r"^Auto\s*de\s*(\d{1,2})\s*de\s*([A-Za-zÁÉÍÓÚáéíóúñÑ]+?)\s*de\s*(\d{4})$", re.IGNORECASE)


def _acto_de_celda(celda: str, encabezado: str) -> Optional[tuple]:
    """(tipo, numero, fecha) si la celda describe un acto; None si no."""
    t = re.sub(r"\s+", " ", celda or "").strip()
    if not t:
        return None
    m = re.match(r"^0*(\d+)\s*_\s*(\d{4})$", t)
    if m:
        return "Resolucion", str(int(m.group(1))), None
    m = _RE_AUTO_PEGADO.match(t)
    if m:
        return "Auto", "", _parse_fecha_espanol(m.group(1), m.group(2), m.group(3))
    m = _RE_NUM_Y_FECHA.match(t)
    if m:
        fecha = _parse_fecha_espanol(m.group(2), m.group(3), m.group(4))
        tipo = "Auto" if "auto" in encabezado and "resoluc" not in encabezado else "Resolucion"
        return tipo, str(int(m.group(1))), fecha
    return None


# 30-sep (2026-IE-036778/036779): la celda del expediente viene partida en
# dos lineas ('2025-EE-\n232206' -> '2025-EE- 232206') y la del acto a veces
# sin el año ('24431 de 4 de septiembre\nde'): se une el expediente y el acto
# se acepta con numero aunque la fecha quede incompleta (el Cuadro lo ubica
# por expediente + numero; la fecha sale del Cuadro).
_RE_EE_PARTIDO = re.compile(r"(\d{4}-EE-)\s+(\d)")
_RE_NUM_FECHA_SIN_ANIO = re.compile(
    r"^0*(\d{2,6})\s*del?\s*(\d{1,2})\s*de\s*([A-Za-zÁÉÍÓÚáéíóúñÑ]+?)(?:\s*(?:de|del))?\s*$", re.IGNORECASE)


def _fila_generica(row: list, encabezado: str) -> Optional[AnexoSolicitado]:
    celdas = [_RE_EE_PARTIDO.sub(r"\1\2", _norm_cell(c)) for c in row]
    exp = next((c for c in celdas if _RE_EXPEDIENTE_EE.fullmatch(c.replace("‐", "-"))), None)
    if exp is None:
        return None
    acto = None
    for c in celdas:
        if c != exp:
            acto = _acto_de_celda(c, encabezado)
            if acto:
                break
    nombre = next((c for c in celdas if c != exp and re.search(r"[A-Za-zÁÉÍÓÚÑ]{3}", c)
                   and _acto_de_celda(c, encabezado) is None and not re.match(r"^[A-Z]?\d", c)), "")
    if acto is None:
        # 2-oct (2026-IE-037292): numero y fecha en celdas separadas
        # ['2026-EE-045984', 'JORGE LUIS RUEDA CANO', '24557', '8/09/2026']
        i_f = next((i for i, c in enumerate(celdas) if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", c)), None)
        fch = celdas[i_f] if i_f is not None else None
        num = celdas[i_f - 1] if i_f and re.fullmatch(r"0*\d{3,6}", celdas[i_f - 1]) else None
        if num and fch:
            d, m_, a_ = fch.split("/")
            tipo_sep = "Auto" if "auto" in encabezado and "resoluc" not in encabezado else "Resolucion"
            acto = (tipo_sep, str(int(num)), f"{int(d):02d}/{int(m_):02d}/{a_}")
    warns = [] if acto else [f"No se reconocio el acto en la fila {celdas!r}"]
    if acto is None:
        for c in celdas:
            m = _RE_NUM_FECHA_SIN_ANIO.match(c) if c != exp else None
            if m and m.group(3).strip().lower() in _MESES:
                tipo_sa = "Auto" if "auto" in encabezado and "resoluc" not in encabezado else "Resolucion"
                acto = (tipo_sa, str(int(m.group(1))), None)
                warns = [f"'{c}': la fecha viene sin año -- se toma la del Cuadro (ubicado por expediente y número)"]
                break
    cedula = next((c for c in celdas if re.fullmatch(r"[A-Z]?\d{5,12}", c.replace(".", ""))
                   and not (acto and acto[1] and c.lstrip("0") == acto[1])), "")
    tipo, numero, fecha = acto or ("Desconocido", "", None)
    return AnexoSolicitado(nombre=nombre, cedula=cedula, expediente=exp.replace("‐", "-"), tipo=tipo,
                           numero=numero, fecha=fecha, texto_original=" | ".join(celdas), warnings=warns)


def extraer_anexos_solicitados(pdf_path: str | Path) -> list[AnexoSolicitado]:
    return extraer_anexos_y_conteo(pdf_path)[0]


_RE_ITEM_LISTA = re.compile(r"^\s*(?:[•▪●◦]|[\-–—]\s|\d{1,2}[.)]\s)")
_RE_REF_ACTO = re.compile(
    r"(\d{4}-EE-\d+|CNV-\d{4}-\d+)|Resoluci[oó]n\s*(?:No\.?|Nro\.?|N°|N\.°|número)?\s*0*(\d{3,})"
    r"|(Auto\s+(?:No\.?\s*|N°\s*)?\d+|Auto\s+de\s+(?:fecha\s+)?\d{1,2}\s+de\s+[A-Za-záéíóú]+\s+de\s+\d{4})",
    re.IGNORECASE,
)


def _clave_anexo(a) -> tuple:
    return ((a.expediente or "").upper(), a.tipo if a.numero or a.fecha else "", a.numero or "", a.fecha or "")


def _conteo_prosa(texto: str) -> tuple:
    """(casos en la lista, [duplicados]). Cada viñeta/numeral que nombra un
    expediente o un acto es UN caso pedido (2026-IE-036987: 5 viñetas). Una
    viñeta repetida (mismo expediente o misma resolucion) es un duplicado."""
    texto = normalizar_expedientes(re.sub(r"(\d{4}-+)\s*\n\s*(-*EE-)", r"\1\2", texto))
    texto = re.sub(r"(\d{4}-EE-)\s*\n\s*(\d+)", r"\1\2", texto)
    items, actual = [], None
    for linea in texto.splitlines():
        # 2026-IE-036040: una linea de la lista vino sin su guion ("2026-EE-187943 - ANDREA ...")
        if _RE_ITEM_LISTA.match(linea) or re.match(r"^\s*(?:\d{4}-EE-\d+|CNV-\d{4}-\d+)\b", linea):
            if actual is not None:
                items.append(actual)
            actual = linea
        elif actual is not None and linea.strip():
            # continuacion de la viñeta (nombre partido en dos lineas); un parrafo
            # nuevo (empieza con mayuscula seguida de minusculas y no es nombre) la cierra
            if re.match(r"^\s*[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,}\s+[a-záéíóúñ]", linea):
                items.append(actual)
                actual = None
            else:
                actual += " " + linea.strip()
    if actual is not None:
        items.append(actual)
    refs = []
    for it in items:
        m = _RE_REF_ACTO.search(it)
        if not m:
            continue
        if m.group(1):
            refs.append(m.group(1).upper())
        elif m.group(2):
            refs.append(f"Resolución {int(m.group(2))}")
        else:
            refs.append(" ".join(m.group(3).split()).capitalize())
    vistos, dup = set(), []
    for r in refs:
        if r in vistos and r not in dup:
            dup.append(r)
        vistos.add(r)
    return len(refs), dup


def extraer_anexos_y_conteo(pdf_path: str | Path) -> tuple:
    """(anexos sin repetir, casos pedidos en la lista, [duplicados]).
    1-oct (Andres): en las masivas se cuenta EXACTO lo que la peticion pide por
    lista y se detectan duplicados; la tabla de la respuesta debe tener esa
    misma cantidad."""
    filas, n_lista, duplicados = _extraer_anexos_crudo(pdf_path)
    unicos, vistos = [], set()
    for f in filas:
        k = _clave_anexo(f)
        if k in vistos and any(k):
            etiqueta = f.expediente or f"{f.tipo} {f.numero or f.fecha}"
            if etiqueta not in duplicados:
                duplicados.append(etiqueta)
            continue
        vistos.add(k)
        unicos.append(f)
    return unicos, n_lista, duplicados


def _extraer_anexos_crudo(pdf_path: str | Path) -> tuple:
    """Lee, con pdfplumber, los anexos de la peticion: una fila por cada
    Resolucion/Auto sobre el que se pide respuesta.

    Primero intenta encontrar una TABLA (formato de las peticiones
    masivas -- ver docstring del modulo). Si no encuentra ninguna fila por
    esa via, cae a `_extraer_anexos_prosa` sobre el texto completo del PDF
    -- el formato mas comun, segun Andres, para peticiones individuales."""
    import pdfplumber

    filas: list[AnexoSolicitado] = []
    texto_paginas: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            for tabla in page.extract_tables() or []:
                encabezado = " ".join(_norm_cell(c) for c in (tabla[0] if tabla else []) if c).lower()
                encabezado = unicodedata.normalize("NFKD", encabezado).encode("ascii", "ignore").decode()
                for row in tabla:
                    if not row:
                        continue
                    if len(row) < 4 or not _RE_EXPEDIENTE.match(_norm_cell(row[2])):
                        generica = _fila_generica(row, encabezado)
                        if generica is not None:
                            filas.append(generica)
                        continue
                    nombre = _norm_cell(row[0])
                    cedula = _norm_cell(row[1])
                    expediente = _norm_cell(row[2])
                    col4 = _norm_cell(row[3])
                    if not nombre or not _RE_EXPEDIENTE.match(expediente):
                        # fila de encabezado u otra cosa que no es un anexo real
                        continue
                    tipo, numero, fecha, warns = _extraer_tipo_numero_fecha(col4)
                    filas.append(
                        AnexoSolicitado(
                            nombre=nombre,
                            cedula=cedula,
                            expediente=expediente,
                            tipo=tipo,
                            numero=numero,
                            fecha=fecha,
                            texto_original=col4,
                            warnings=warns,
                        )
                    )
            texto_paginas.append(page.extract_text() or "")

    n_lista, duplicados = (len(filas), []) if filas else (None, [])
    if not filas:
        filas = _extraer_anexos_prosa("\n".join(texto_paginas))
        n_lista, duplicados = _conteo_prosa("\n".join(texto_paginas))
        if not n_lista:
            n_lista = None     # sin lista (peticion en prosa corrida): no se cuenta
    plano = " ".join(" ".join(texto_paginas).split()).lower()
    recurso = ""
    # Solo cuando se pide LA RESOLUCION del recurso ("resoluciones de
    # apelación"), no cuando solo se menciona un recurso en tramite.
    if re.search(r"resoluci[oó]n(?:es)?\s+(?:de\s+|del\s+recurso\s+de\s+)?apelaci[oó]n", plano):
        recurso = "Apelación"
    elif re.search(r"resoluci[oó]n(?:es)?\s+(?:de\s+|del\s+recurso\s+de\s+)?reposici[oó]n", plano):
        recurso = "Reposición"
    for f in filas:
        f.recurso = recurso
        f.anio = _anio_del_acto(f)
    return filas, n_lista, duplicados


def _anio_del_acto(anexo) -> Optional[int]:
    m = re.search(r"(?<!\d)0*\d{1,6}\s*_\s*(\d{4})(?!\d)", anexo.texto_original or "")
    if m:
        return int(m.group(1))
    if anexo.fecha and re.fullmatch(r"\d{2}/\d{2}/\d{4}", anexo.fecha):
        return int(anexo.fecha[-4:])
    return None


# Lineas que NO son parte del bloque del firmante (sello de firma digital,
# pie y encabezado de pagina). Se comparan sin espacios porque pdfplumber a
# veces los pega ('MinisteriodeEducaciónNacional Página1de2').
_RUIDO_FIRMA = re.compile(
    r"^(cordialmente|atentamente|@firma|firmadodigitalmente|ministeriodeeducaci[oó]nnacional|paravalidar|"
    r"documentoescanee|direcci[oó]n:calle|conmutador|l[ií]neagratuita|gd-ft|_{5,}|radicadono|\d{4}-ie-\d+|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{2}/\d{4}|elabor[oó]|revis[oó]|aprob[oó])",
    re.IGNORECASE,
)
_FIN_BLOQUE_FIRMA = re.compile(r"^(folios|anexos|nombre\s*anexos|elabor[oó])\b", re.IGNORECASE)
_RE_NOMBRE_PERSONA = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'. ]+$")


def _compacto(t: str) -> str:
    return re.sub(r"\s+", "", t or "").upper()


def extraer_destinatario(pdf_path: str | Path) -> Optional[Destinatario]:
    """Quien FIRMA la peticion: nombre, cargo y dependencia, leidos del
    bloque que queda entre el ULTIMO 'Cordialmente' y 'Folios:'/'Elaboró'
    (en todo el documento, porque la firma puede caer en la pagina 2).

    Evidencia (28-sep, peticiones reales): la version anterior tomaba la
    linea siguiente a 'Cordialmente' y fallaba cuando la peticion repite
    'Cordialmente,' (2026-IE-036323 -> nombre 'Cordialmente,') o cuando la
    firma cae en la pagina siguiente (2026-IE-036040 -> la raya del pie de
    pagina). Ahora se saltan el sello de firma digital y los pies/encabezados
    de pagina, y el nombre se CONFIRMA contra la casilla 'Aprobó' del mismo
    documento. Si el nombre no parece un nombre de persona, devuelve None
    (no se adivina)."""
    import pdfplumber

    with pdfplumber.open(str(pdf_path)) as pdf:
        texto = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    idx_cord = [i for i, l in enumerate(lineas) if l.lower().startswith("cordialmente") or l.lower().startswith("atentamente")]
    if not idx_cord:
        # 29-sep-2026 (v1.5.10), evidencia insignia_run.log 15:36 y 15:48:
        # 2026-IE-036741 -> "peticion leida -- firma None". La peticion cierra
        # con "Sin otro particular, se suscribe," (sin 'Cordialmente') y el
        # bloque de firma quedaba sin ancla. Respaldo: el sello
        # '@FirmaDigitalTMS@' (exacto, no el '...QR@' del encabezado) va
        # siempre justo antes del nombre de quien firma. Se toma el ULTIMO.
        idx_cord = [i for i, l in enumerate(lineas) if _compacto(l) == "@FIRMADIGITALTMS@"]
    if not idx_cord:
        return None
    bloque: list = []
    for l in lineas[idx_cord[-1] + 1:]:
        if _FIN_BLOQUE_FIRMA.match(l):
            break
        if _RUIDO_FIRMA.match(_compacto(l).lower()) or _RUIDO_FIRMA.match(l):
            continue
        bloque.append(l)
    if len(bloque) < 2:
        return None
    nombre = " ".join(bloque[0].split())
    if not _RE_NOMBRE_PERSONA.match(nombre) or len(nombre.split()) < 2 or len(nombre.split()) > 7:
        return None
    cargo = bloque[1]
    # La dependencia puede ocupar 2 lineas; "Folios: 1" a veces queda pegado
    # como un "1" al final ('...de la Calidad1').
    subdireccion = re.sub(r"\d+$", "", " ".join(bloque[2:4])).strip()
    resto = "\n".join(lineas[idx_cord[-1]:])
    confirmado = bool(re.search(r"aprob[oó]", resto, re.IGNORECASE)) and _compacto(nombre) in _compacto(
        resto[re.search(r"aprob[oó]", resto, re.IGNORECASE).start():] if re.search(r"aprob[oó]", resto, re.IGNORECASE) else ""
    )
    return Destinatario(nombre=nombre, cargo=cargo, subdireccion=subdireccion, confirmado=confirmado)


def extraer_radicado(pdf_path: str | Path) -> Optional[str]:
    """Numero de radicado de la peticion misma (ej. '2026-IE-034750'),
    tal como aparece impreso en el propio PDF."""
    import pdfplumber

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            texto = page.extract_text() or ""
            m = _RE_RADICADO.search(texto)
            if m:
                return m.group(1).strip()
    return None


_RE_PRUEBAS_ENTREGA = re.compile(r"(pruebas?|constancias?)\s+(o\s+constancias?\s+)?de\s+entrega", re.IGNORECASE)
_RE_RADICADO_IE = re.compile(r"(\d{4})\s*-\s*IE\s*-\s*(\d{5,7})", re.IGNORECASE)


def extraer_radicados_internos(pdf_path: str | Path, radicado_propio: Optional[str]) -> list:
    """Si la peticion pide pruebas/constancias de ENTREGA, devuelve los
    radicados internos (2026-IE-XXXXXX) que menciona, en orden y sin repetir,
    sin el radicado de la propia peticion. Tolera el numero partido en dos
    lineas ('2026-IE-\n031304', visto en 2026-IE-036323). [] si no aplica."""
    import pdfplumber
    with pdfplumber.open(str(pdf_path)) as pdf:
        texto = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    if not _RE_PRUEBAS_ENTREGA.search(texto):
        return []
    propio = (radicado_propio or "").upper()
    vistos: list = []
    for m in _RE_RADICADO_IE.finditer(texto):
        rad = f"{m.group(1)}-IE-{m.group(2)}"
        if rad.upper() != propio and rad not in vistos:
            vistos.append(rad)
    return vistos


def leer_peticion(pdf_path: str | Path) -> PeticionInfo:
    """Punto de entrada principal: lee una peticion PDF completa y devuelve
    todo lo necesario para armar la respuesta (destinatario + anexos)."""
    warnings: list = []

    radicado = extraer_radicado(pdf_path)
    if radicado is None:
        warnings.append("No se pudo leer el numero de radicado de la peticion")

    destinatario = extraer_destinatario(pdf_path)
    if destinatario is None:
        warnings.append(
            "No se pudo leer el bloque de firma (destinatario) de la peticion"
        )

    anexos, casos_en_lista, duplicados = extraer_anexos_y_conteo(pdf_path)
    if duplicados:
        warnings.append(f"La petición repite {len(duplicados)} caso(s) en su lista: {', '.join(duplicados)} "
                        "-- cada uno va UNA sola vez en la respuesta.")
    if casos_en_lista and casos_en_lista - len(duplicados) != len(anexos):
        warnings.append(f"CONTEO: la petición lista {casos_en_lista} caso(s)"
                        + (f" ({casos_en_lista - len(duplicados)} sin repetir)" if duplicados else "")
                        + f" y se identificaron {len(anexos)} -- revisa cuál falta o sobra antes de aprobar.")
    radicados_internos = [] if anexos else extraer_radicados_internos(pdf_path, radicado)
    if not anexos and not radicados_internos:
        warnings.append(
            "No se encontro una tabla de anexos en la peticion: puede ser una "
            "peticion individual sin tabla, o el formato del PDF cambio"
        )
    for anexo in anexos:
        warnings.extend(f"[{anexo.expediente}] {w}" for w in anexo.warnings)

    return PeticionInfo(
        radicado=radicado,
        destinatario=destinatario,
        anexos=anexos,
        warnings=warnings,
        radicados_internos=radicados_internos,
        casos_en_lista=casos_en_lista,
        duplicados=duplicados,
    )

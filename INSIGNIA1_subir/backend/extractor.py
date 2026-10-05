"""
Extractor de expedientes a partir de un ZIP descargado del Portal de Acuses 4-72
(o de un ZIP equivalente descargado a mano de otro portal, ver backend/local_zip.py).

Estructura observada (validada con varios casos reales):

    ZIP
     |-- FolderContents.txt              (indica cual .eml es el "bueno",
     |                                     ver nota abajo)
     `-- RegisteredReceipt_<ID>_....eml  (correo "Recibo:" -- wrapper)
          `-- Htmlreceipt.pdf             (el "Acuse de Recibido Certificado")
               `-- <hash>.eml             (embebido dentro del PDF: el correo
                                            ORIGINAL enviado al destinatario)
                    |-- R_<numero>_<ddmmaaaa>.pdf   (Resolucion)   o
                    |-- AA_<numero>_<ddmmaaaa>.pdf  (Auto)
                    `-- A<ticket>_..._<ddmmaaaa>.pdf (Acta de notificacion)

El extractor camina recursivamente por eml -> adjuntos -> (si un adjunto PDF
trae a su vez un eml embebido) -> eml, hasta encontrar el correo original con
los dos adjuntos reales.

Nota sobre "RegisteredReceipt_<ID>_....eml": cuando el destinatario abrio el
acuse varias veces (o el sistema reintento el envio), el ZIP puede traer
VARIAS copias de este archivo (una por evento/fecha), pero solo UNA trae
realmente el PDF con el correo original adentro -- las demas son recibos de
lectura vacios (solo DeliveryReceipt.xml + HtmlReceipt.htm, sin el PDF).
FolderContents.txt indica cual es la correcta; ver _find_top_eml_candidates.

--------------------------------------------------------------------------
Expedientes con VARIOS notificados/comunicados (mismo Acto Administrativo)
--------------------------------------------------------------------------
Un mismo numero de Resolucion/Auto puede tener mas de una persona notificada
(por ejemplo: el titular via notificacion personal + varios funcionarios via
comunicacion). Cada notificacion genera su PROPIO acuse (su propio ZIP), pero
todos comparten el mismo documento principal (Resolucion/Auto).

Por eso la extraccion se separa en dos pasos:

  1. extract_acuse(zip_bytes) -> Acuse
     Procesa UN acuse (un ZIP) y devuelve sus piezas sueltas (documento
     principal, acta, acuse de entrega) sin fusionarlas todavia.

  2. merge_acuses(acuses) -> Expediente
     Recibe uno o varios Acuse que YA se determino que pertenecen al mismo
     Acto Administrativo (mismo tipo + numero) y arma el expediente final en
     el orden acordado:
         1. Documento principal (Resolucion/Auto)      -- una sola vez
         2. Acta de notificacion/comunicacion #1
         3. Acuse de entrega #1 (mismo nombre/correo que el acta #1)
         4. Acta #2 (el siguiente cronologicamente)
         5. Acuse #2
         ... y asi sucesivamente, en orden cronologico de envio.

  process_zip(zip_bytes) -> Expediente sigue existiendo para el caso simple
  (un solo notificado): es un atajo equivalente a
  merge_acuses([extract_acuse(zip_bytes)]).

Quien llama a esto (main.py) es responsable de decidir QUE acuses van juntos:
normalmente agrupando por (tipo, numero) despues de llamar extract_acuse()
sobre todo el lote.
"""
from __future__ import annotations

import dataclasses
import io
import re
import zipfile
from datetime import datetime
from email import policy, utils as email_utils
from email.parser import BytesParser
from typing import Optional

from pypdf import PdfReader, PdfWriter

# Nombre real -> (tipo legible, requiere numero en el nombre final)
_MAIN_DOC_RE = re.compile(r"^(R|AA)_(\d+)_(\d{2})(\d{2})(\d{4})\.pdf$", re.IGNORECASE)
_ACTA_RE = re.compile(r"^A\d+_.*\.pdf$", re.IGNORECASE)
# 30-sep (acuse 'AUTO 1471 DEL 25 DE JUN 2026.pdf', 2026-IE-036693): otro formato
# de notificacion -- el correo "Comunicación de respuesta (2026-EE-242886)" trae
# el Auto como 'AA_019455_25062026.pdf_2026-EE-242886.pdf' (con el radicado EE
# pegado al final) y, en vez del Acta 'A<ticket>_...', la carta de notificacion
# '2026-EE-242886-Correspondencia de salida-16523379.pdf_2026-EE-242886.pdf'.
# Se quita ese sufijo y la carta hace de Acta.
_SUFIJO_RADICADO_RE = re.compile(r"(\.pdf)_[^\\/]*?\.pdf$", re.IGNORECASE)
_CORRESPONDENCIA_RE = re.compile(r"correspondencia\s*de\s*salida|correspondenciasalida", re.IGNORECASE)


def _nombre_real(fn: str) -> str:
    return _SUFIJO_RADICADO_RE.sub(r"\1", (fn or "").strip())
_MONTH_ES = {
    "ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AGO": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DIC": "12",
}
_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]')


class ExtractionError(Exception):
    """El ZIP/PDF no tiene la estructura esperada."""


@dataclasses.dataclass
class Acuse:
    """Un acuse individual (una sola persona notificada/comunicada), ya
    extraido de su ZIP pero SIN fusionar todavia con otros acuses del mismo
    Acto Administrativo."""
    tipo: str                      # "Resolucion" | "Auto" | "Desconocido"
    numero: str
    fecha: str                     # fecha del acto, dd/mm/aaaa
    nombre_titular: str
    destinatario_email: str
    asunto_original: str
    ticket: str
    fecha_envio: Optional[datetime]  # para poder ordenar cronologicamente
    main_doc_bytes: bytes
    main_doc_filename: str
    acta_bytes: bytes
    acta_filename: str
    acuse_bytes: Optional[bytes]
    acuse_filename: Optional[str]
    warnings: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Expediente:
    tipo: str                  # "Resolucion" | "Auto" | "Desconocido"
    numero: str                # numero interno tal como aparece en el archivo
    fecha: str                 # dd/mm/aaaa
    nombre_titular: str        # extraido del Acta (o varios, separados por "; ")
    destinatario_email: str    # campo "To" del correo original (o varios)
    asunto_original: str
    ticket: str                # el [NNNNNN] del asunto, si esta presente
    final_filename: str        # nombre sugerido, ya sanitizado, con .pdf
    pdf_bytes: bytes           # PDF final ya combinado
    n_notificados: int = 1     # cuantos Acuse se fusionaron en este expediente
    warnings: list[str] = dataclasses.field(default_factory=list)


def _sanitize_filename(name: str) -> str:
    name = _INVALID_FS_CHARS.sub("", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name


def _get_pdf_embedded_eml(pdf_bytes: bytes) -> Optional[bytes]:
    """Si el PDF trae un archivo .eml embebido (adjunto tipo RPost), lo devuelve."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception:
        return None
    attachments = getattr(reader, "attachments", None)
    if not attachments:
        return None
    for _key, blobs in attachments.items():
        for blob in blobs:
            if blob[:5] in (b"Retur", b"Deliv", b"Recei") or b"\nSubject:" in blob[:4000] or b"\nFrom:" in blob[:2000]:
                return blob
    # si no se pudo reconocer por contenido, devolver el primero disponible
    for _key, blobs in attachments.items():
        if blobs:
            return blobs[0]
    return None


def _parse_eml_date(msg) -> Optional[datetime]:
    raw = msg["date"]
    if not raw:
        return None
    try:
        dt = email_utils.parsedate_to_datetime(raw)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _walk_eml(eml_bytes: bytes, depth: int = 0, max_depth: int = 4) -> Optional[dict]:
    """Busca recursivamente el correo original con los adjuntos reales.

    Devuelve dict con: subject, to, main_doc (filename, bytes),
    acta (filename, bytes), acuse_bytes, acuse_filename, fecha_envio.
    """
    if depth > max_depth:
        return None

    msg = BytesParser(policy=policy.default).parse(io.BytesIO(eml_bytes))
    subject = msg["subject"] or ""
    to = msg["to"] or ""
    fecha_envio = _parse_eml_date(msg)

    parts = []
    for part in msg.walk():
        fn = part.get_filename()
        if not fn:
            continue
        data = part.get_payload(decode=True) or b""
        parts.append((fn, data))

    main_doc = None
    acta = None
    carta = None
    for fn, data in parts:
        real = _nombre_real(fn)
        if _MAIN_DOC_RE.match(real):
            main_doc = (real, data)
        elif _ACTA_RE.match(real):
            acta = (real, data)
        elif carta is None and real.lower().endswith(".pdf") and _CORRESPONDENCIA_RE.search(real):
            carta = (real, data)
    if main_doc and acta is None and carta is not None:
        acta = carta

    if main_doc and acta:
        return {
            "subject": subject,
            "to": to,
            "main_doc": main_doc,
            "acta": acta,
            "acuse_bytes": None,
            "acuse_filename": None,
            "fecha_envio": fecha_envio,
        }

    # No encontrados directamente: buscar un adjunto PDF que traiga un eml
    # embebido (el "Acuse de Recibido Certificado") y recursar dentro de el.
    for fn, data in parts:
        if not fn.lower().endswith(".pdf"):
            continue
        nested_eml = _get_pdf_embedded_eml(data)
        if not nested_eml:
            continue
        result = _walk_eml(nested_eml, depth + 1, max_depth)
        if result:
            result["acuse_bytes"] = data
            result["acuse_filename"] = fn
            # la fecha que importa para ordenar cronologicamente es la del
            # correo ORIGINAL (el interno), no la del recibo-wrapper externo
            if result.get("fecha_envio") is None:
                result["fecha_envio"] = fecha_envio
            return result

    return None


def _find_top_eml_candidates(zip_bytes: bytes) -> list[bytes]:
    """Devuelve los .eml de nivel superior del ZIP, en orden de preferencia.

    Cuando un mismo acuse se abrio/reintento varias veces, RPost genera VARIOS
    archivos "RegisteredReceipt_<ID>_<fecha>.eml" (uno por cada evento), pero
    normalmente solo UNO de ellos trae el PDF con el correo original adentro
    (los demas son recibos de lectura sin adjuntos utiles: solo
    DeliveryReceipt.xml + HtmlReceipt.htm). El propio ZIP suele traer
    "FolderContents.txt" con una linea "RegisteredReceipt||<archivo.eml>" que
    indica exactamente cual es el correcto -- se usa como primer criterio.
    Como respaldo (por si ese archivo no viene o no coincide con ninguno de
    los .eml presentes), se ordena por tamano descendente, ya que el .eml con
    el PDF real adentro siempre pesa bastante mas que los recibos vacios; y de
    todas formas se devuelven TODOS los candidatos para que quien llama pueda
    intentarlos en orden hasta que alguno funcione."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        eml_infos = [i for i in zf.infolist() if i.filename.lower().endswith(".eml")]
        if not eml_infos:
            raise ExtractionError(
                "El ZIP no contiene ningun archivo .eml (estructura inesperada)."
            )

        preferred_name = None
        try:
            contents = zf.read("FolderContents.txt").decode("utf-8", errors="ignore")
            eml_name_set = {i.filename for i in eml_infos}
            for line in contents.splitlines():
                line = line.strip()
                if "||" not in line:
                    continue
                _label, _, fname = line.partition("||")
                fname = fname.strip()
                if fname in eml_name_set:
                    preferred_name = fname
                    break
        except KeyError:
            pass
        except Exception:
            pass

        def sort_key(info):
            is_preferred = 0 if info.filename == preferred_name else 1
            is_registered_receipt = 0 if "registeredreceipt" in info.filename.lower() else 1
            return (is_preferred, is_registered_receipt, -info.file_size, info.filename)

        eml_infos.sort(key=sort_key)
        return [zf.read(info.filename) for info in eml_infos]


def _extract_titular_name(acta_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(acta_bytes))
        text = reader.pages[0].extract_text() or ""
    except Exception:
        return ""

    match = re.search(r"Se[ñn]or\(a\)\s*\n+\s*([^\n]+)", text, re.IGNORECASE)
    if not match:
        # carta 'Correspondencia de salida' (30-sep): "Señora\nMARCELA PATRICIA LUGO FLORES"
        match = re.search(r"^\s*Se[ñn]or(?:a)?\s*$\n+\s*([^\n]+)", text, re.IGNORECASE | re.MULTILINE)
    if not match:
        return ""
    name = re.sub(r"\s+", " ", match.group(1)).strip()
    return name


def _parse_main_doc_filename(filename: str) -> tuple[str, str, str]:
    """Devuelve (tipo, numero, fecha dd/mm/aaaa) a partir del nombre del archivo."""
    m = _MAIN_DOC_RE.match(filename)
    if not m:
        return "Desconocido", "", ""
    prefix, numero, dd, mm, yyyy = m.groups()
    tipo = "Resolucion" if prefix.upper() == "R" else "Auto"
    fecha = f"{dd}/{mm}/{yyyy}"
    return tipo, numero, fecha


def _extract_ticket(subject: str) -> str:
    m = re.match(r"^\s*\[(\d+)\]", subject)
    return m.group(1) if m else ""


def _build_final_filename(tipo: str, numero: str, fecha: str, nombre: str) -> str:
    """nombre debe venir SIEMPRE como un unico nombre (nunca varios unidos
    con ';'): quien llama decide cual es ese unico nombre -- el del titular
    cuando hay un solo notificado, o el de la institucion/el del primer
    notificado cronologico cuando hay varios (ver merge_acuses)."""
    if tipo == "Resolucion":
        year = fecha.split("/")[-1] if fecha else ""
        # CONFIRMADO (Andres, 2026-09-23): el numero de resolucion no debe
        # llevar ceros a la izquierda en el nombre final (ej. el archivo
        # origen puede traer "R_020513_..." pero el nombre final debe ser
        # "2026_20513.pdf", no "2026_020513.pdf"). Se le quitan los ceros
        # a la izquierda; si el numero fuera solo ceros (caso raro/vacio),
        # se deja tal cual para no perder informacion.
        numero_final = numero.lstrip("0") or numero
        base = f"{year}_{numero_final}" if year else numero_final
    elif tipo == "Auto":
        if fecha:
            dd, mm, yyyy = fecha.split("/")
            fecha_txt = f"{dd} {mm} {yyyy}"
        else:
            fecha_txt = ""
        if nombre:
            base = f"AUTO {fecha_txt} {nombre}".strip()
        elif numero:
            base = f"AUTO {fecha_txt} {numero}".strip()
        else:
            base = f"AUTO {fecha_txt}".strip()
    else:
        base = f"EXPEDIENTE_{numero or 'SIN_NUMERO'}"
    return _sanitize_filename(base) + ".pdf"


def _merge_pdfs(order: list[bytes]) -> bytes:
    writer = PdfWriter()
    for pdf_bytes in order:
        if not pdf_bytes:
            continue
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
        except Exception:
            continue
        for page in reader.pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _acuse_from_eml_result(
    result: dict,
    fallback_acuse_bytes: Optional[bytes] = None,
    fallback_acuse_filename: Optional[str] = None,
) -> Acuse:
    """Construye un Acuse a partir del dict que devuelve _walk_eml (o uno
    armado a mano, ver extract_acuse_from_pdf). Factorizado para que tanto
    extract_acuse (flujo del portal, via ZIP) como extract_acuse_from_pdf
    (flujo de PDFs sueltos descargados a mano) construyan el mismo objeto
    de la misma manera."""
    warnings: list[str] = []

    main_fn, main_bytes = result["main_doc"]
    acta_fn, acta_bytes = result["acta"]
    acuse_bytes = result.get("acuse_bytes") or fallback_acuse_bytes
    acuse_filename = result.get("acuse_filename") or fallback_acuse_filename
    if acuse_bytes is None:
        warnings.append(
            "No se pudo identificar el PDF del acuse de entrega; el expediente "
            "final solo incluye el acto administrativo y el acta."
        )

    tipo, numero, fecha = _parse_main_doc_filename(main_fn)
    nombre_titular = _extract_titular_name(acta_bytes)
    if not nombre_titular:
        warnings.append("No se pudo extraer el nombre del titular desde el Acta.")

    subject = result.get("subject", "")

    return Acuse(
        tipo=tipo,
        numero=numero,
        fecha=fecha,
        nombre_titular=nombre_titular,
        destinatario_email=result.get("to", ""),
        asunto_original=subject,
        ticket=_extract_ticket(subject),
        fecha_envio=result.get("fecha_envio"),
        main_doc_bytes=main_bytes,
        main_doc_filename=main_fn,
        acta_bytes=acta_bytes,
        acta_filename=acta_fn,
        acuse_bytes=acuse_bytes,
        acuse_filename=acuse_filename,
        warnings=warnings,
    )


def extract_acuse(zip_bytes: bytes) -> Acuse:
    """Procesa UN acuse (un ZIP descargado del portal 4-72) y devuelve sus
    piezas sueltas, sin fusionarlas todavia con otros acuses del mismo Acto
    Administrativo.

    Cuando el ZIP trae varios .eml de nivel superior (ver
    _find_top_eml_candidates), se intenta con cada uno -- en orden de
    preferencia -- hasta que alguno arroje los adjuntos esperados; no basta
    con el primero de la lista porque, en la practica, algunos de esos .eml
    son recibos de lectura sin el correo original (y por lo tanto sin el
    Resolucion/Auto + Acta) adentro."""
    candidates = _find_top_eml_candidates(zip_bytes)
    result = None
    for top_eml in candidates:
        result = _walk_eml(top_eml)
        if result is not None:
            break
    if result is None:
        raise ExtractionError(
            "No se encontraron los adjuntos esperados (Resolucion/Auto + Acta) "
            "dentro del ZIP. Puede tratarse de un formato de acuse distinto."
        )
    return _acuse_from_eml_result(result)


def _get_pdf_named_attachments(pdf_bytes: bytes) -> dict[str, bytes]:
    """Devuelve {nombre_archivo: bytes} de TODOS los adjuntos embebidos en
    un PDF (a diferencia de _get_pdf_embedded_eml, que busca especificamente
    uno que parezca un .eml)."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception:
        return {}
    attachments = getattr(reader, "attachments", None)
    if not attachments:
        return {}
    out: dict[str, bytes] = {}
    for key, blobs in attachments.items():
        for i, blob in enumerate(blobs):
            name = key if i == 0 else f"{key} ({i})"
            out[name] = blob
    return out


def extract_acuse_from_pdf(pdf_bytes: bytes, filename: str = "") -> Acuse:
    """Procesa UN acuse descargado MANUALMENTE como un PDF suelto (sin ZIP
    ni la cadena de correos .eml del portal 4-72 de por medio) -- el caso
    del "otro portal" que exige captcha, del que los acuses se descargan
    uno por uno como PDF.

    Se intentan, en orden, las estructuras mas probables (sin necesitar
    saber de antemano cual usa ese portal):

      1. El propio PDF trae embebidos, como adjuntos, el documento del
         Acto Administrativo (R_.../AA_...) y el Acta (A<ticket>_...) --
         es decir, el acuse "trae adentro los otros dos archivos", como se
         describio.
      2. El propio PDF trae embebido un .eml (la misma estructura que
         Htmlreceipt.pdf en el flujo del portal 4-72, solo que sin el
         correo "wrapper" externo que en ese flujo lo envuelve) -- se
         camina ese eml igual que en extract_acuse.

    Si ninguna de las dos aplica, se lanza ExtractionError con un mensaje
    claro (no generico) para poder ajustar la deteccion con un ejemplo real
    en vez de adivinar a ciegas.
    """
    filename = filename or "acuse.pdf"

    named = _get_pdf_named_attachments(pdf_bytes)
    main_item = None
    acta_item = None
    for name, data in named.items():
        real = _nombre_real(name)
        if main_item is None and _MAIN_DOC_RE.match(real):
            main_item = (real, data)
        elif acta_item is None and _ACTA_RE.match(real):
            acta_item = (real, data)

    if main_item and acta_item:
        result = {
            "subject": "",
            "to": "",
            "main_doc": main_item,
            "acta": acta_item,
            "acuse_bytes": pdf_bytes,
            "acuse_filename": filename,
            "fecha_envio": None,
        }
        return _acuse_from_eml_result(result)

    nested_eml = _get_pdf_embedded_eml(pdf_bytes)
    if nested_eml:
        result = _walk_eml(nested_eml)
        if result:
            return _acuse_from_eml_result(
                result, fallback_acuse_bytes=pdf_bytes, fallback_acuse_filename=filename
            )

    adjuntos_hallados = ", ".join(named.keys()) if named else "ninguno"
    raise ExtractionError(
        f"No se pudo reconocer la estructura de '{filename}': no trae embebidos el "
        f"Acto Administrativo + Acta (adjuntos hallados: {adjuntos_hallados}), ni un "
        "correo (.eml) con esos adjuntos adentro. Si este archivo SI es un acuse "
        "valido, comparte un ejemplo para ajustar la deteccion."
    )


def _persona_key(a: "Acuse") -> tuple[str, str]:
    """Clave para comparar si dos Acuse son de LA MISMA persona: mismo
    nombre (normalizado) Y mismo correo (normalizado). Si a cualquiera de
    los dos le falta el dato, se devuelve una clave vacia -- en ese caso
    nunca se considera "la misma persona" que otro (mejor de mas que
    fusionar por error dos notificados distintos)."""
    name = re.sub(r"\s+", " ", (a.nombre_titular or "").strip().lower())
    email = (a.destinatario_email or "").strip().lower()
    if not name or not email:
        return ("", "")
    return (name, email)


def _dedupe_same_person(acuses: list["Acuse"]) -> tuple[list["Acuse"], int]:
    """Colapsa acuses que correspondan a LA MISMA persona (mismo nombre Y
    mismo correo) a uno solo -- el caso tipico es el mismo acuse
    descargado/guardado dos veces (p.ej. "archivo.pdf" y "archivo (1).pdf").
    Eso NO es un notificado adicional y no debe duplicar paginas en el
    expediente final. Dos acuses de personas realmente distintas para el
    mismo acto (distinto nombre y/o distinto correo) nunca se tocan aqui.

    Devuelve (lista_deduplicada, cuantos_se_omitieron)."""
    vistos: set[tuple[str, str]] = set()
    out: list[Acuse] = []
    omitidos = 0
    for a in acuses:
        key = _persona_key(a)
        if key != ("", "") and key in vistos:
            omitidos += 1
            continue
        if key != ("", ""):
            vistos.add(key)
        out.append(a)
    return out, omitidos


def merge_acuses(acuses: list["Acuse"], cuadro_index=None) -> Expediente:
    """Combina uno o varios Acuse del MISMO Acto Administrativo (mismo
    tipo + numero) en un unico Expediente, en el orden:

        1. Documento principal (Resolucion/Auto)      -- una sola vez
        2. Acta #1 (la mas antigua cronologicamente) + Acuse #1
        3. Acta #2 + Acuse #2
        ... etc.

    Quien llama decide que acuses van juntos (normalmente: mismo tipo+numero
    tras procesar todo un lote con extract_acuse). No se valida aqui que
    todos compartan tipo/numero; si vienen mezclados se respeta el orden
    cronologico igual, pero el numero/nombre final sale del primero.

    Nombre usado en el archivo final:
      - Un solo notificado: el nombre extraido de su Acta (como siempre).
      - Varios notificados de un Auto: NUNCA se concatenan nombres ni se
        cae al numero. Se usa el nombre de la institucion (persona
        juridica) cuando `cuadro_index` (backend.cuadro_lookup.CuadroIndex,
        opcional) identifica una para este acto -- por ejemplo, un Auto de
        investigacion notificado a la persona natural investigada y
        comunicado ademas al representante legal de una universidad: el
        archivo debe llevar el nombre de la universidad, no el del
        representante. Si no hay cuadro_index o no identifica ninguna
        institucion, se usa simplemente el nombre del primer notificado
        cronologico (nunca varios).
      - Varios notificados de una Resolucion: no aplica (el nombre no forma
        parte del patron de archivo de Resolucion), pero igual se calcula
        para el reporte.
    """
    if not acuses:
        raise ValueError("merge_acuses() requiere al menos un Acuse.")

    acuses_sorted = sorted(
        acuses, key=lambda a: a.fecha_envio or datetime.max
    )
    acuses_sorted, duplicados_omitidos = _dedupe_same_person(acuses_sorted)
    first = acuses_sorted[0]

    order: list[bytes] = [first.main_doc_bytes]
    warnings: list[str] = []
    nombres: list[str] = []
    correos: list[str] = []

    if duplicados_omitidos:
        warnings.append(
            f"Se detecto{'n' if duplicados_omitidos > 1 else ''} {duplicados_omitidos} "
            "notificacion(es) duplicada(s) (mismo nombre y mismo correo que otra ya "
            "incluida, probablemente el mismo acuse guardado dos veces); no se repitieron "
            "en el expediente."
        )

    for a in acuses_sorted:
        order.append(a.acta_bytes)
        if a.acuse_bytes:
            order.append(a.acuse_bytes)
        warnings.extend(a.warnings)
        if a.nombre_titular and a.nombre_titular not in nombres:
            nombres.append(a.nombre_titular)
        if a.destinatario_email and a.destinatario_email not in correos:
            correos.append(a.destinatario_email)

    merged = _merge_pdfs(order)
    nombre_reporte = "; ".join(nombres)  # para el Excel: se listan todos

    if len(acuses_sorted) > 1:
        nombre_institucion = None
        if cuadro_index is not None:
            try:
                nombre_institucion = cuadro_index.nombre_institucion(first.tipo, first.numero)
            except Exception:
                nombre_institucion = None
        nombre_archivo = nombre_institucion or first.nombre_titular
    else:
        nombre_archivo = first.nombre_titular

    final_filename = _build_final_filename(first.tipo, first.numero, first.fecha, nombre_archivo)

    return Expediente(
        tipo=first.tipo,
        numero=first.numero,
        fecha=first.fecha,
        nombre_titular=nombre_reporte,
        destinatario_email="; ".join(correos),
        asunto_original=first.asunto_original,
        ticket=first.ticket,
        final_filename=final_filename,
        pdf_bytes=merged,
        n_notificados=len(acuses_sorted),
        warnings=warnings,
    )


def process_zip(zip_bytes: bytes) -> Expediente:
    """Punto de entrada para el caso simple: un solo acuse (un solo
    notificado) por ZIP. Equivalente a merge_acuses([extract_acuse(...)])."""
    return merge_acuses([extract_acuse(zip_bytes)])

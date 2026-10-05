"""
Carpeta del caso en Descargas (Andres, 1-oct-2026, caso 2026-IE-036987).

Cuando un caso pide actos que Insignia no puede bajar sola (expedientes
anteriores a 2025, que se le piden a Magda), Andres reune TODOS los PDF de la
respuesta en una carpeta de Descargas con el numero del caso:

    Descargas\\2026-IE-036987\\
        2026_1156.pdf  2026_16269.pdf  2026_25958.pdf           (de Insignia / portal)
        RES 6192 DE 2020.pdf  RES 25057 DE 2021.pdf  ...        (de Magda)

Esa carpeta MANDA: cada PDF se identifica por su CONTENIDO (encabezado
"RESOLUCIÓN No. 011841 23 JUN 2022", expediente y titular del texto), va en
el ZIP con el nombre de siempre ('2022_11841.pdf') y en la tabla de la
respuesta (Tipo de AA | Numero | Fecha | Expediente), en el orden de la
peticion. Nunca se adivina: un PDF que no se pueda identificar, o cuyo
numero no coincida con el de su nombre de archivo, detiene el caso con el
nombre del archivo. Lo que no calza con la peticion (otra fecha, otro
expediente del mismo titular) va, pero queda como aviso para revisar.
"""
from __future__ import annotations

import dataclasses
import re
import unicodedata
from pathlib import Path
from typing import Optional

_MESES = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8,
          "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12}
_RE_ENCABEZADO = re.compile(r"(\d{6,12})(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|SET|OCT|NOV|DIC)(\d{4})")
_RE_EXP = re.compile(r"\b(?:\d{4}-EE-\d+|CNV-\d{4}-\d+)\b")
_RE_NUM_NOMBRE = [
    re.compile(r"^(?:RES(?:OLUCI[OÓ]N)?|R)[\s._-]*(?:No\.?\s*)?0*(\d{2,6})\s*(?:DE|DEL|_)\s*(\d{4})", re.I),  # RES 6192 DE 2020
    re.compile(r"^(\d{4})_0*(\d{2,6})(?:\D|$)"),                                                             # 2026_1156
]
_RE_TITULAR = re.compile(
    r"(?:\bQue\s+(?:el\s+señor\s+|la\s+señora\s+)?|\bseñora?\s+)"
    r"([A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){1,5})\s*,?\s*(?:ciudadan|quien|identificad)"
)


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip().upper()


@dataclasses.dataclass
class DocCaso:
    ruta: Path
    tipo: str            # "Resolucion" | "Auto"
    numero: str          # sin ceros a la izquierda
    fecha: str           # dd/mm/aaaa
    expediente: str
    titular: str = ""
    recurso: str = ""    # "Apelación" | "Reposición" | ""
    avisos: list = dataclasses.field(default_factory=list)

    @property
    def anio(self) -> int:
        return int(self.fecha[-4:])


def carpeta_del_caso(carpetas_base: list, radicado: str) -> Optional[Path]:
    """Descargas\\<radicado>\\ (la mas reciente si hay varias con ese numero)."""
    rad = (radicado or "").strip().upper()
    if not rad:
        return None
    hallazgos = []
    for base in carpetas_base:
        base = Path(base)
        if not base.is_dir():
            continue
        try:
            for d in base.iterdir():
                if d.is_dir() and re.search(rf"(?<![\dA-Z]){re.escape(rad)}(?!\d)", d.name.upper()):
                    if any(f.suffix.lower() == ".pdf" for f in d.iterdir() if f.is_file()):
                        hallazgos.append(d)
        except OSError:
            continue
    return max(hallazgos, key=lambda d: d.stat().st_mtime) if hallazgos else None


def pdfs(carpeta: Path) -> list:
    try:
        return sorted(f for f in Path(carpeta).iterdir()
                      if f.is_file() and f.suffix.lower() == ".pdf" and not f.name.startswith("~$"))
    except OSError:
        return []


def mas_nuevo(carpeta: Path) -> float:
    return max((f.stat().st_mtime for f in pdfs(carpeta)), default=0.0)


def _texto(ruta: Path, paginas: int = 4) -> list:
    import pdfplumber
    with pdfplumber.open(str(ruta)) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages[:paginas]]


def _numero_del_nombre(nombre: str) -> Optional[tuple]:
    base = Path(nombre).stem.strip()
    m = _RE_NUM_NOMBRE[0].match(base)
    if m:
        return str(int(m.group(1))), int(m.group(2))
    m = _RE_NUM_NOMBRE[1].match(base)
    if m:
        return str(int(m.group(2))), int(m.group(1))
    return None


def _encabezado(texto_p1: str, numero_nombre: Optional[str]) -> Optional[tuple]:
    """(numero, dd/mm/aaaa) del encabezado 'RESOLUCIÓN No. 011841 23 JUN 2022'.
    Los escaneos traen los digitos separados ('00 6 1 9 2 2 0 ABR 2020'): se
    compacta el texto y se separa numero (6 digitos) y dia."""
    compacto = re.sub(r"\s+", "", _norm(texto_p1))
    for m in _RE_ENCABEZADO.finditer(compacto):
        digitos, mes, anio = m.group(1), _MESES[m.group(2)], int(m.group(3))
        if not 2000 <= anio <= 2100:
            continue
        opciones = []
        for k in (2, 1):
            num, dia = digitos[:-k], digitos[-k:]
            if len(num) >= 6:
                num = num[-6:]
            if 1 <= int(dia) <= 31 and len(num) == 6:
                opciones.append((str(int(num)), f"{int(dia):02d}/{mes:02d}/{anio}"))
        if numero_nombre:
            opciones = [o for o in opciones if o[0] == numero_nombre] or opciones[:0]
        elif len(digitos) not in (7, 8):
            opciones = []          # basura antes del numero: no se adivina
        if opciones:
            return opciones[0]
    return None


def identificar(ruta: Path) -> tuple:
    """(DocCaso | None, motivo)."""
    ruta = Path(ruta)
    try:
        paginas = _texto(ruta)
    except Exception as exc:  # noqa: BLE001
        return None, f"{ruta.name}: no se pudo leer ({type(exc).__name__})"
    if not paginas or not paginas[0].strip():
        return None, f"{ruta.name}: no tiene texto legible (¿escaneo sin OCR?)"
    p1 = _norm(paginas[0])
    tipo = "Resolucion" if "RESOLUCION" in p1[:600] else "Auto" if re.search(r"\bAUTO\b", p1[:600]) else ""
    if tipo != "Resolucion":
        # Los Autos no traen numero propio en el encabezado (se citan por fecha y
        # titular): esta carpeta solo identifica Resoluciones por ahora.
        return None, f"{ruta.name}: no se reconoce como Resolución (encabezado 'RESOLUCIÓN No. ...')"
    del_nombre = _numero_del_nombre(ruta.name)
    enc = _encabezado(paginas[0], del_nombre[0] if del_nombre else None)
    if enc is None:
        if del_nombre:
            return None, (f"{ruta.name}: el nombre dice Resolución {del_nombre[0]} de {del_nombre[1]} pero el "
                          "encabezado del PDF no trae ese número -- revisa el archivo")
        return None, f"{ruta.name}: no se pudo leer el número y la fecha del encabezado"
    numero, fecha = enc
    avisos = []
    if del_nombre and del_nombre[1] != int(fecha[-4:]):
        avisos.append(f"{ruta.name}: el nombre dice {del_nombre[1]} y el acto es del {fecha}")
    plano = "\n".join(paginas)
    plano = re.sub(r"(\d{4}-EE-)\s*\n\s*(\d+)", r"\1\2", plano)
    plano = re.sub(r"(\d{4})\s*-{1,3}\s*EE\s*-{1,3}\s*(\d+)", r"\1-EE-\2", plano)
    plano = re.sub(r"\bCNV\s*-\s*(\d{4})\s*-\s*(\d+)", r"CNV-\1-\2", plano, flags=re.I)
    m = _RE_EXP.search(plano.upper())
    expediente = m.group(0) if m else ""
    if not expediente:
        avisos.append(f"Resolución {numero} del {fecha}: no se encontró el expediente en el texto")
    t = _RE_TITULAR.search(" ".join(plano.split()))
    titular = _norm(t.group(1)) if t else ""
    titulo = _norm(" ".join(paginas[0].split()))[:1500]
    recurso = ("Apelación" if "RECURSO DE APELACION" in titulo else
               "Reposición" if "RECURSO DE REPOSICION" in titulo else "")
    return DocCaso(ruta=ruta, tipo="Resolucion", numero=numero, fecha=fecha, expediente=expediente,
                   titular=titular, recurso=recurso, avisos=avisos), ""


def leer(carpeta: Path) -> tuple:
    """([DocCaso], [problemas]). Un mismo acto en dos archivos se toma una vez."""
    docs, problemas, vistos = [], [], {}
    for f in pdfs(carpeta):
        doc, motivo = identificar(f)
        if doc is None:
            problemas.append(motivo)
            continue
        clave = (doc.tipo, doc.numero, doc.fecha)
        if clave in vistos:
            # el mas grande (el expediente completo) gana
            if f.stat().st_size > vistos[clave].ruta.stat().st_size:
                docs[docs.index(vistos[clave])] = doc
                vistos[clave] = doc
            continue
        vistos[clave] = doc
        docs.append(doc)
    return docs, problemas


def _es_del_anexo(doc: DocCaso, anexo) -> str:
    """'' si no; si si, por que ('expediente' | 'numero' | 'titular')."""
    if anexo.expediente and doc.expediente and doc.expediente.upper() == anexo.expediente.upper():
        return "expediente"
    if getattr(anexo, "tipo", "") == doc.tipo and anexo.numero and str(int(anexo.numero)) == doc.numero:
        return "numero"
    if anexo.nombre and doc.titular and _norm(anexo.nombre) == doc.titular:
        return "titular"
    return ""


def relacionar(docs: list, anexos: list) -> tuple:
    """Ordena los documentos segun la peticion y arma los avisos.
    (docs_ordenados, avisos, anexos_sin_documento)."""
    usados, orden, avisos, sin_doc = set(), [], [], []
    por_anexo = []
    for anexo in anexos:
        mios = [d for d in docs if id(d) not in usados and _es_del_anexo(d, anexo)]
        mios.sort(key=lambda d: (d.anio, d.fecha[3:5], d.fecha[:2]))
        for d in mios:
            usados.add(id(d))
            via = _es_del_anexo(d, anexo)
            if via == "numero" and anexo.fecha and anexo.fecha != d.fecha:
                avisos.append(f"Resolución {d.numero}: la petición dice del {anexo.fecha} y el acto es del {d.fecha} "
                              f"(exp. {d.expediente or '-'}{', ' + d.titular if d.titular else ''}) -- confirma que es la pedida")
            if via == "titular":
                avisos.append(f"Resolución {d.numero} del {d.fecha} es del expediente {d.expediente or '-'}, no del pedido "
                              f"({anexo.expediente}); va porque es del mismo titular ({d.titular}) -- confirma que va")
        if not mios:
            sin_doc.append(anexo)
        por_anexo.append(mios)
        orden += mios
    resto = [d for d in docs if id(d) not in usados]
    for d in resto:
        avisos.append(f"Resolución {d.numero} del {d.fecha} (exp. {d.expediente or '-'}) estaba en la carpeta del caso "
                      "pero la petición no la menciona -- va en la respuesta; confirma")
    orden += sorted(resto, key=lambda d: (d.anio, d.fecha[3:5], d.fecha[:2]))
    for d in orden:
        avisos.extend(d.avisos)
    return orden, avisos, sin_doc


def fila_tabla(doc: DocCaso) -> list:
    from backend.sgdea_carta import _TIPO_LABEL, _fecha_tabla
    return [_TIPO_LABEL.get(doc.tipo, "Acto"), doc.numero, _fecha_tabla(doc.fecha), doc.expediente]


def nombre_final(doc: DocCaso) -> str:
    from backend.extractor import _build_final_filename
    return _build_final_filename(doc.tipo, doc.numero, doc.fecha, doc.titular)


def _orden_fecha(d: DocCaso) -> tuple:
    return (d.anio, d.fecha[3:5], d.fecha[:2])


def asignar(docs: list, actos: list) -> tuple:
    """Un documento de la carpeta por cada caso pedido (Andres, 1-oct: la tabla
    lleva EXACTAMENTE los casos que pide la peticion).

    actos: [sgdea_carta.ActoResuelto] en el orden de la peticion (ubicados o no).
    Devuelve (actos_finales, avisos, pendientes, problemas):
      - actos_finales: cada acto; los que se toman de la carpeta quedan
        emparejados y con `archivo_carpeta`.
      - pendientes: los que no tienen acto en el Cuadro NI documento en la carpeta.
      - problemas: la carpeta trae varias resoluciones posibles y la peticion no
        dice cual (no se adivina).
    Los PDF de la carpeta que no son de ningun caso pedido NO van (se avisa)."""
    import dataclasses as _dc
    usados: set = set()
    finales, avisos, pendientes, problemas = [], [], [], []

    def tomar(acto, d, extra_avisos):
        usados.add(id(d))
        anexo = acto.anexo
        if not anexo.expediente and d.expediente:
            anexo.expediente = d.expediente
        if not anexo.nombre and d.titular:
            anexo.nombre = d.titular
        avisos.extend(extra_avisos + d.avisos)
        return _dc.replace(acto, tipo_final=d.tipo, numero_final=d.numero, fecha_final=d.fecha,
                           nombre_titular_cuadro=acto.nombre_titular_cuadro or d.titular or anexo.nombre,
                           emparejado=True, pedir_a_magda=False, archivo_carpeta=str(d.ruta))

    for acto in actos:
        anexo = acto.anexo
        libres = [d for d in docs if id(d) not in usados]
        if acto.emparejado:
            mismo = [d for d in libres if d.tipo == acto.tipo_final and d.numero == str(int(acto.numero_final or 0))
                     and (not acto.fecha_final or d.fecha == acto.fecha_final)]
            finales.append(tomar(acto, mismo[0], []) if mismo else acto)
            continue
        if anexo.numero:
            cands = [d for d in libres if d.tipo == (anexo.tipo if anexo.tipo != "Desconocido" else d.tipo)
                     and d.numero == str(int(anexo.numero))]
        else:
            cands = [d for d in libres if _es_del_anexo(d, anexo)]
        recurso = getattr(anexo, "recurso", "") or ""
        elegido, notas = None, []
        if len(cands) == 1:
            elegido = cands[0]
        elif len(cands) > 1 and recurso:
            del_recurso = [d for d in cands if d.recurso == recurso]
            if len(del_recurso) == 1:
                elegido = del_recurso[0]
        if elegido is None and cands:
            problemas.append(
                f"{_describir(anexo)}: la carpeta del caso trae {len(cands)} resoluciones posibles ("
                + ", ".join(f"{d.numero} del {d.fecha}" for d in sorted(cands, key=_orden_fecha))
                + ") y la petición no dice cuál -- deja solo la que va")
            finales.append(acto)
            continue
        if elegido is None:
            pendientes.append(acto)
            finales.append(acto)
            continue
        if anexo.fecha and anexo.fecha != elegido.fecha:
            notas.append(f"Resolución {elegido.numero}: la petición dice del {anexo.fecha} y el PDF es del "
                         f"{elegido.fecha} ({elegido.titular or 'sin titular'}, exp. {elegido.expediente or '-'}) "
                         "-- confirma que es la pedida")
        if recurso and elegido.recurso != recurso:
            notas.append(f"Resolución {elegido.numero} del {elegido.fecha}: la petición pide la del recurso de "
                         f"{recurso.lower()} y esta resuelve "
                         + (f"un recurso de {elegido.recurso.lower()}" if elegido.recurso else "la solicitud")
                         + " -- confirma que es la pedida")
        if anexo.expediente and elegido.expediente and anexo.expediente.upper() != elegido.expediente.upper():
            notas.append(f"Resolución {elegido.numero}: es del expediente {elegido.expediente}, la petición dice "
                         f"{anexo.expediente} -- confirma")
        finales.append(tomar(acto, elegido, notas))

    sobran = sorted((d for d in docs if id(d) not in usados), key=_orden_fecha)
    if sobran:
        avisos.append("En la carpeta del caso pero NO pedidas (no van en la respuesta): "
                      + "; ".join(f"Resolución {d.numero} del {d.fecha} (exp. {d.expediente or '-'}"
                                  + (f", {d.recurso.lower()}" if d.recurso else "") + ")" for d in sobran))
    return finales, avisos, pendientes, problemas


def _describir(anexo) -> str:
    if anexo.numero:
        return f"Resolución {anexo.numero}" + (f" del {anexo.fecha}" if anexo.fecha else "")
    return f"Expediente {anexo.expediente or '-'}" + (f" ({anexo.nombre})" if anexo.nombre else "")

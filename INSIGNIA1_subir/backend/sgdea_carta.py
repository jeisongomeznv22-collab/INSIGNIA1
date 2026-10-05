"""
Generador del CUERPO de la carta (Memorando respuesta) a partir de:
  1. Lo que ya extrajo backend/sgdea_peticion.py de la peticion (destinatario,
     radicado, tabla de anexos solicitados: expediente + lo que cada fila
     traiga ademas -- nombre, cedula, tipo de acto, numero/fecha parcial).
  2. Cuadro_2026/2025 (backend/cuadro_lookup.py), que es la fuente de
     verdad: cada Expediente EE-XXXXXX que allega el peticionario se busca
     ahi (columna 'NUMERO DE SOLICITUD DE PROCESO') y de ahi sale el tipo,
     numero oficial, fecha y nombre completo del acto -- asi es como Andres
     individualiza esto a diario, y es la misma logica que ya usa
     cuadro_lookup.py para otras partes del programa.
  3. Opcionalmente, lo que el pipeline 4-72 ya descargo para ese lote (una
     lista de expedientes/archivos con tipo, numero y el nombre de archivo
     final que ya arma extractor.py) -- esto solo se usa para saber que PDF
     adjuntar, una vez el acto ya esta identificado via el Cuadro.

Plantilla confirmada leyendo dos respuestas YA APROBADAS que Andres
compartio como muestra (2026-IE-035468, individual, y 2026-IE-035561,
masiva) -- el texto fijo de abajo se copio literal de esos PDFs, no se
inventa nada:

    Para: {Doctor|Doctora}
    {NOMBRE DESTINATARIO}
    {CARGO}
    {SUBDIRECCION}

    Eje tematico: SOLICITUDES INTERNAS GENERALES
    Asunto:Respuesta a Radicado {radicado_peticion}

    Cordial Saludo, Doctora {dos primeros nombres}:   (mujer)
    Cordial Saludo, Doctor {dos apellidos}:            (hombre)

    <cuerpo: parrafo individual, o parrafo + tabla si es masiva>

    Cordialmente,

El bloque de firma (@FirmaDigitalTMS@ + nombre/cargo/subdireccion de quien
aprueba) y la fila Elaboro/Reviso/Aprobo los pone el propio SGDEA segun el
usuario que este operando la sesion -- este modulo NO los genera.

Como se individualiza cada acto (corregido con la explicacion de Andres:
el criterio real es por Expediente contra el Cuadro, no por nombre contra
el reporte del 472 -- probado contra el Cuadro_2026 real y la respuesta ya
aprobada 2026-IE-035561, fila por fila: 65 de 74 filas comparables salen
identicas a la carta ya aprobada; las 9 restantes son expedientes que
todavia no aparecen en el Cuadro_2026 exportado -- casos reales, no
fallas del cruce -- y quedan marcados con advertencia en vez de
completarse con datos inventados):

  1. Cada anexo de la peticion ya trae su Expediente EE-XXXXXX -> se busca
     en Cuadro_2026/2025 (RESOLUCIONES + AUTOS, columna 'NUMERO DE
     SOLICITUD DE PROCESO'). Ahi esta el numero oficial del acto, la fecha
     y el nombre completo -- no hace falta ni inventar ni cruzar con nada
     mas para la gran mayoria de los casos.
  2. La mayoria de los expedientes traen un unico acto en el Cuadro, pero
     no siempre (se verificaron casos reales con 2-3 actos para el mismo
     expediente, ej. una Resolucion inicial y otra posterior para la misma
     persona). Cuando pasa esto, se usa el "criterio compuesto" que
     describe Andres: lo que la propia peticion ademas traiga (tipo de
     acto + numero, o tipo + fecha) para desempatar. Si no alcanza para
     desempatar con certeza, no se elige ninguno -- se marca para revision
     manual, nunca se adivina.
  3. Lo que la peticion trae directamente (numero para Resolucion via
     '020128_2026', fecha para Auto via 'Auto de 01 de septiembre de
     2026') se usa TAMBIEN como verificacion cruzada contra lo que dice el
     Cuadro, y se reporta cualquier discrepancia (se encontraron algunas
     reales en los datos de prueba -- diferencias de un dia, un numero
     transpuesto -- que hay que revisar, no descartar el emparejamiento).
  4. El nombre de archivo a adjuntar (individual) sale de cruzar tipo+numero
     ya resueltos contra lo que el 472 efectivamente ya proceso para ese
     lote -- ahi si el cruce es deterministico porque tipo+numero ya se
     conocen con certeza gracias al paso 1.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from backend.cuadro_lookup import CuadroIndex
from backend.sgdea_peticion import AnexoSolicitado, PeticionInfo, anio_expediente

_TIPO_LABEL = {"Resolucion": "Resolución", "Auto": "Auto", "Desconocido": "Acto"}
# concordancia de genero: "el Auto" (masculino) vs "la Resolución" (femenino)
_TIPO_ARTICULO = {"Resolucion": "de la", "Auto": "del", "Desconocido": "del"}

_MESES_INV = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre",
    12: "diciembre",
}


def _fecha_tabla(fecha: str) -> str:
    """'05/03/2026' -> '5/03/2026': formato de la columna Fecha en la
    respuesta masiva aprobada (caso 2026-IE-035664, captura de Andres
    28-sep: '19/06/2026', '6/08/2026', '2/09/2026', '5/03/2026'). Si no
    tiene formato dd/mm/aaaa se devuelve tal cual."""
    partes = (fecha or "").split("/")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        return fecha or ""
    dd, mm, aaaa = partes
    return f"{int(dd)}/{mm.zfill(2)}/{aaaa}"


def _fecha_a_texto(fecha: str) -> str:
    """'30/07/2026' -> '30 de julio de 2026' (estilo del parrafo individual
    ya aprobado: 'el Auto de Archivo del 29 de julio de 2026'). Si no se
    puede interpretar se devuelve tal cual."""
    partes = (fecha or "").split("/")
    if len(partes) != 3:
        return fecha or ""
    dd, mm, aaaa = partes
    if not (dd.isdigit() and mm.isdigit() and aaaa.isdigit()):
        return fecha or ""
    mes_nombre = _MESES_INV.get(int(mm))
    if mes_nombre is None:
        return fecha or ""
    return f"{int(dd)} de {mes_nombre} de {aaaa}"


def _numero_key(v) -> str:
    """Mismo criterio que cuadro_lookup._numero_key: quita ceros a la
    izquierda para poder comparar '020128' con '20128' o con 20128 (int)."""
    if v is None or v == "":
        return ""
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        s = str(v).strip()
        return s.lstrip("0") or "0"


def _nombre_saludo(nombre_completo: str, tratamiento: str) -> tuple[str, Optional[str]]:
    """Regla de Andres (28-sep): a una MUJER se la saluda con sus dos
    primeros nombres ('Doctora Martha Elena'); a un HOMBRE con sus dos
    apellidos ('Doctor Ibarra Consuegra', caso 2026-IE-035664).
    Devuelve (texto, aviso). Con 3 palabras no se sabe si el hombre tiene
    dos nombres o dos apellidos: se usan las 2 ultimas y se avisa."""
    if tratamiento != "Doctor":
        return _nombre_pila(nombre_completo), None
    palabras = [p.capitalize() for p in (nombre_completo or "").strip().split() if p]
    if len(palabras) >= 4:
        return " ".join(palabras[-2:]), None
    if len(palabras) == 3:
        texto = " ".join(palabras[-2:])
        return texto, (f"Saludo: '{nombre_completo}' tiene 3 palabras -- se uso '{texto}' como apellidos; "
                       "revisar que sean sus dos apellidos.")
    return " ".join(palabras), f"Saludo: no se pudieron separar los apellidos de '{nombre_completo}' -- revisar."


def _articulo_ciudadano(nombre: str) -> tuple[str, Optional[str]]:
    """'del señor' / 'de la señora' segun el nombre del ciudadano (pedido de
    Andres 28-sep). Si el nombre no permite saberlo con seguridad se deja
    'de' y se avisa (no se adivina)."""
    trat, confiable = inferir_tratamiento(nombre)
    if confiable and trat == "Doctora":
        return "de la señora", None
    if confiable and trat == "Doctor":
        return "del señor", None
    return "de", f"No se pudo saber si '{nombre}' es señor o señora -- completar 'a nombre del señor/de la señora' a mano."


def _nombre_pila(nombre_completo: str) -> str:
    """'ANA MARIA GÓMEZ DÍAZ' -> 'Ana María' (las dos primeras
    palabras, tal como se ve en la muestra real: 'Cordial Saludo, Doctora
    Martha Elena:'). Heuristica simple; si el nombre trae menos de 2
    palabras se usa lo que haya."""
    palabras = [p.capitalize() for p in nombre_completo.strip().split() if p]
    return " ".join(palabras[:2]) if palabras else nombre_completo


# ----------------------------------------------------------------------
# Inferencia automatica de Tratamiento (Doctor/Doctora) -- pedido explicito
# de Andres (sesion 2026-09-24): "la leeras [la peticion] y conforme a...
# quien firma dicha peticion, si es hombre o mujer, llenaras los campos".
# ANTES esto SIEMPRE lo elegia Andres a mano (ver comentario historico en
# Carta.tratamiento/generar_carta mas abajo, que ya no aplica tal cual);
# ahora se infiere del primer nombre de pila de dest.nombre (el firmante de
# la peticion, ver docstring de sgdea_peticion.py) contra un diccionario de
# nombres comunes en Colombia + una regla de terminacion como respaldo.
#
# Es deliberadamente conservador: si el nombre no aparece en el diccionario
# Y la terminacion no es una de las claramente marcadas (mismo criterio que
# el resto del modulo: "nunca se inventa un dato que no se puede sostener"),
# NO elige nada -- devuelve confiable=False para que quien llama (main.py)
# se detenga y pida a Andres que elija el mismo, en vez de arriesgar un
# "Doctor"/"Doctora" equivocado en una comunicacion oficial real.
_NOMBRES_FEMENINOS = {
    "maria", "martha", "marta", "luz", "diana", "sandra", "claudia", "patricia",
    "andrea", "paola", "carolina", "lina", "natalia", "adriana", "monica",
    "gloria", "rocio", "ximena", "alejandra", "catalina", "juliana", "camila",
    "valentina", "laura", "daniela", "angela", "liliana", "sonia", "yolanda",
    "ana", "carmen", "rosa", "elena", "beatriz", "cristina", "esperanza",
    "consuelo", "amparo", "gladys", "nubia", "fanny", "myriam", "mirian",
    "olga", "stella", "estela", "ines", "isabel", "leonor", "lucia", "lucía",
    "yaneth", "yesenia", "johana", "jenny", "sara", "sofia", "sofía", "alba",
    "flor", "nelly", "nohora", "nora", "piedad", "pilar", "ruth", "teresa",
    "viviana", "yolima", "zoraida", "ivonne", "yvonne", "milena", "marcela",
    "ivon", "edna", "erika", "érika", "eliana", "diva", "diveith", "yeimy",
    "kelly", "vanessa", "tatiana", "mayerly", "leidy", "deisy", "yuliana",
    "ingrid", "astrid", "jimena", "fabiola", "ester", "esther", "yenny",
    # 30-sep (2026-IE-036540: 'YANNETH ALVAREZ ALVAREZ' quedo sin 'de la señora'):
    "yanneth", "yanet", "yannet", "janeth", "janet", "jannet", "lizeth", "liseth", "lisseth",
    "yamileth", "yamile", "yamiled", "elizabeth", "lisbeth", "nancy", "mery", "ruby", "doris",
    "marleny", "arleth", "yuly", "yudy", "yurany", "maryuri", "nidia", "miriam", "carmenza",
    "miurika", "edith", "judith", "yazmin", "jazmin", "yasmin", "belen", "belén",
    "eliannys", "elianys",
}
_NOMBRES_MASCULINOS = {
    "jose", "josé", "juan", "carlos", "luis", "jorge", "andres", "andrés",
    "alejandro", "fernando", "javier", "diego", "miguel", "rafael", "julio",
    "ricardo", "eduardo", "francisco", "manuel", "pedro", "roberto", "victor",
    "víctor", "cesar", "césar", "oscar", "óscar", "sergio", "alberto",
    "german", "germán", "gustavo", "hernan", "hernán", "hector", "héctor",
    "ivan", "iván", "jaime", "jairo", "mauricio", "nelson", "orlando",
    "armando", "camilo", "daniel", "david", "elkin", "enrique", "felipe",
    "gabriel", "guillermo", "harold", "henry", "jhon", "john", "jonathan",
    "leonardo", "marco", "marcos", "martin", "martín", "norberto", "omar",
    "pablo", "rodrigo", "santiago", "wilson", "yesid", "alfonso", "alfredo",
    "antonio", "arturo", "cristian", "cristián", "edgar", "edison", "efrain",
    "efraín", "elias", "elías", "erick", "erik", "ernesto", "esteban",
    "fabian", "fabián", "gerardo", "gonzalo", "hugo", "isaac", "jeison",
    "jeisson", "jhonny", "leandro", "leonel", "mario", "nestor", "néstor",
    "raul", "raúl", "rene", "renato", "rene", "reinaldo", "walter", "william",
    "yeison", "yesith",
    "eleazar", "eliecer", "eliécer", "eliseo", "octavio",   # 30-sep (036830)
}
# Terminaciones sin excepciones conocidas relevantes en nombres colombianos
# comunes -- respaldo SOLO si el primer nombre no esta en ninguna lista de
# arriba.
_TERMINACIONES_FEMENINAS = ("a", "ina", "ela", "isa")
_TERMINACIONES_MASCULINAS = ("o", "or", "el", "án", "an")


def inferir_tratamiento(nombre_completo: str) -> tuple[Optional[str], bool]:
    """Devuelve (tratamiento, confiable). tratamiento es "Doctor"/"Doctora"
    o None si no se pudo inferir nada. confiable=False significa "no
    arriesgar, pedir a Andres que elija manualmente" -- puede pasar con
    tratamiento=None (no se encontro nada usable) o, en teoria, si en el
    futuro se agrega una señal de baja confianza junto con un valor.

    Deliberadamente NO usa ningun servicio externo (el .exe empaquetado no
    siempre tiene red) -- solo el diccionario de arriba + una regla de
    terminacion muy conservadora."""
    palabras = [p for p in (nombre_completo or "").strip().split() if p]
    if not palabras:
        return None, False
    primer_nombre = palabras[0].lower()
    # normaliza tildes basicas para comparar contra el diccionario (que ya
    # trae ambas variantes donde aplica, pero por si acaso)
    if primer_nombre in _NOMBRES_FEMENINOS:
        return "Doctora", True
    if primer_nombre in _NOMBRES_MASCULINOS:
        return "Doctor", True
    if primer_nombre.endswith(_TERMINACIONES_FEMENINAS):
        return "Doctora", True
    if primer_nombre.endswith(_TERMINACIONES_MASCULINAS):
        return "Doctor", True
    return None, False


@dataclasses.dataclass
class ActoResuelto:
    """Un anexo de la peticion ya individualizado (o no) contra el Cuadro."""
    anexo: AnexoSolicitado
    tipo_final: str                       # tipo segun el Cuadro (mas confiable que anexo.tipo si esa fila venia dañada)
    numero_final: str
    fecha_final: str
    nombre_titular_cuadro: Optional[str]  # nombre tal como lo tiene el Cuadro, para trazabilidad
    archivo_final: Optional[str]          # final_filename que ya arma extractor.py, si se paso el reporte 472
    emparejado: bool
    es_archivo: bool = False              # True si el Cuadro marca el tramite como "Auto de Archivo"
                                           # (confirmado por Andres: se cita SOLO por fecha, sin numero interno)
    warnings: list = dataclasses.field(default_factory=list)
    email: str = ""                       # correo de la persona notificada (Cuadro) -- para ubicar el acuse
    pedir_a_magda: bool = False           # acto anterior a 2025: se le pide a Magda (no se busca aqui)
    # 1-oct (2026-IE-036987): PDF tomado de la carpeta del caso en Descargas
    # (Descargas\<radicado>\, ver backend/carpeta_caso.py): va tal cual al adjunto.
    archivo_carpeta: Optional[str] = None


@dataclasses.dataclass
class Carta:
    tratamiento: str            # "Doctor" | "Doctora" -- SIEMPRE la decide Andres, nunca se adivina
    destinatario_nombre: str
    destinatario_cargo: str
    destinatario_subdireccion: str
    nombre_pila: str
    radicado_peticion: str
    asunto: str
    saludo: str
    cuerpo_parrafo: str
    tabla: Optional[list]       # list[[Expediente, Tipo de AA, Numero, Fecha]] si es masiva
    adjunto_nombre: str
    es_masiva: bool
    warnings: list = dataclasses.field(default_factory=list)
    # Encabezado de la tabla masiva; None = el aprobado en 2026-IE-035664
    # (Tipo de AA | Numero | Fecha | Expediente).
    tabla_encabezado: Optional[list] = None
    tabla_formato: Optional[dict] = None   # ver FORMATO_TABLA_* (None = FORMATO_TABLA_MASIVA)


def _elegir_candidato(anexo: AnexoSolicitado, candidatos: list) -> tuple:
    """Cuando un Expediente trae mas de un acto en el Cuadro, desempata con
    el 'criterio compuesto' que describe Andres: lo que la peticion ademas
    traiga (tipo+numero para Resolucion, tipo+fecha para Auto), y si no,
    solo el tipo. Si ni con eso queda un unico candidato, no se elige
    ninguno -- nunca se adivina entre varios actos posibles."""
    # Filas de continuacion del MISMO acto (otro destinatario, sin fecha en el
    # Cuadro) no son otro acto: 2026-IE-036695, Res. 24898 salia 2 veces.
    con_fecha = {(c.tipo, c.numero) for c in candidatos if c.fecha}
    vistos: set = set()
    depurados = []
    for c in candidatos:
        if not c.fecha and (c.tipo, c.numero) in con_fecha:
            continue  # fila de continuacion de un acto que ya esta con su fecha
        clave = (c.tipo, c.numero, c.fecha)
        if clave not in vistos:
            vistos.add(clave)
            depurados.append(c)
    candidatos = depurados or candidatos
    if len(candidatos) == 1:
        return candidatos[0], []

    warns = [
        f"El expediente {anexo.expediente} tiene {len(candidatos)} actos "
        f"distintos en el Cuadro_2026/2025; se intenta desambiguar con lo "
        f"que trae la peticion"
    ]

    if anexo.tipo == "Resolucion" and anexo.numero:
        filtrados = [c for c in candidatos if c.tipo == "Resolucion" and c.numero == anexo.numero]
        if len(filtrados) > 1 and anexo.fecha:
            # La numeracion se reinicia cada año (Cuadro_2025 + Cuadro_2026):
            # la fecha que trae la peticion desempata.
            filtrados = [c for c in filtrados if c.fecha == anexo.fecha]
        if len(filtrados) == 1:
            return filtrados[0], warns

    if anexo.tipo == "Auto" and anexo.fecha:
        filtrados = [c for c in candidatos if c.tipo == "Auto" and c.fecha == anexo.fecha]
        if len(filtrados) == 1:
            return filtrados[0], warns

    if anexo.tipo in ("Resolucion", "Auto"):
        filtrados = [c for c in candidatos if c.tipo == anexo.tipo]
        if len(filtrados) == 1:
            return filtrados[0], warns

    # La peticion pide expresamente la resolucion de un RECURSO (evidencia:
    # 2026-IE-035664 "resoluciones de apelación"; respuesta aprobada de
    # Andres con 16269 / 21818 / 24208, todas 'Recurso de Apelación').
    recurso = getattr(anexo, "recurso", "")
    if recurso:
        clave = recurso.lower().replace("ó", "o")[:6]  # 'apelac' / 'reposi'
        filtrados = [c for c in candidatos if clave in getattr(c, "tipo_aa", "").lower().replace("ó", "o")]
        if len(filtrados) == 1:
            warns.append(f"Se eligio el acto del recurso de {recurso} (lo pide la peticion).")
            return filtrados[0], warns

    warns.append(
        "No se pudo desambiguar con certeza entre los actos candidatos; "
        "revisar manualmente cual corresponde"
    )
    return None, warns


ANIO_MINIMO_CUADRO = 2025   # lo anterior se le pide a Magda (Andres, 29-sep)


def _sin_continuaciones(candidatos: list) -> list:
    con_fecha = {(c.tipo, c.numero) for c in candidatos if c.fecha}
    vistos, out = set(), []
    for c in candidatos:
        if not c.fecha and (c.tipo, c.numero) in con_fecha:
            continue
        clave = (c.tipo, c.numero, c.fecha)
        if clave not in vistos:
            vistos.add(clave)
            out.append(c)
    return out


def _calzan_con_peticion(anexo: AnexoSolicitado, candidatos: list) -> list:
    """Solo los actos del Cuadro que coinciden con TODO lo que la peticion
    trae: tipo; numero (y año, '024195_2026') en Resoluciones; fecha en Autos."""
    out = []
    anio = getattr(anexo, "anio", None)
    for c in candidatos:
        if c.tipo != anexo.tipo:
            continue
        if anexo.tipo == "Resolucion" and anexo.numero:
            if c.numero != _numero_key(anexo.numero):
                continue
            if anio and c.fecha and not c.fecha.endswith(str(anio)):
                continue
        if anexo.fecha and c.fecha and c.fecha != anexo.fecha:
            continue
        if anexo.tipo == "Auto" and anexo.fecha and not c.fecha:
            continue
        out.append(c)
    return _sin_continuaciones(out)


def _casi_igual(anexo: AnexoSolicitado, c) -> bool:
    """Resoluciones: los digitos del numero pedido aparecen en orden dentro
    del numero del Cuadro (o al reves). Autos: fechas a 3 dias o menos."""
    if anexo.tipo == "Resolucion" and anexo.numero:
        a, b = _numero_key(anexo.numero), c.numero or ""
        corto, largo = (a, b) if len(a) <= len(b) else (b, a)
        it = iter(largo)
        if len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1:
            return True     # un digito cambiado (2026-IE-037292: 23422 por 23423)
        return len(largo) - len(corto) <= 1 and all(ch in it for ch in corto)
    if anexo.tipo == "Auto" and anexo.fecha and c.fecha:
        import datetime as _dt
        try:
            d1 = _dt.datetime.strptime(anexo.fecha, "%d/%m/%Y")
            d2 = _dt.datetime.strptime(c.fecha, "%d/%m/%Y")
        except ValueError:
            return False
        return abs((d1 - d2).days) <= 3
    return False


def _ubicar_en_cuadro(anexo: AnexoSolicitado, cuadro: CuadroIndex) -> tuple:
    """(acto | None, avisos). Si la peticion trae tipo + numero/fecha (formato
    tabla: cedula | expediente | '002070_2026' o 'Auto de 17 de septiembre de
    2026'), se exige que calce TODO; primero por expediente y, si ahi no esta,
    por cedula. Nunca se toma un acto distinto al pedido (29-sep: el
    '011897_2024' se estaba cruzando con la Res. 6897 de 2025)."""
    import re as _re
    warns: list = []
    if anexo.expediente:
        candidatos = cuadro.buscar_por_expediente(anexo.expediente)
    else:
        candidatos = cuadro.buscar_por_numero(anexo.tipo, anexo.numero)
    especifico = anexo.tipo in ("Resolucion", "Auto") and (anexo.numero or anexo.fecha)
    if not especifico:
        if not candidatos:
            return None, [f"El expediente {anexo.expediente} no aparece en Cuadro_2026/2025 "
                          f"(nombre en la peticion: '{anexo.nombre}')"]
        return _elegir_candidato(anexo, candidatos)

    ced = _re.sub(r"\D", "", anexo.cedula or "")
    calzan = _calzan_con_peticion(anexo, candidatos)
    via = "expediente"
    if not calzan and ced:
        calzan = _calzan_con_peticion(anexo, cuadro.buscar_por_cedula(ced))
        via = "cedula"
    if len(calzan) > 1 and ced:
        por_ced = [c for c in calzan if _re.sub(r"\D", "", c.cedula or "") == ced]
        if len(por_ced) == 1:
            calzan = por_ced
    if len(calzan) > 1:
        recurso = getattr(anexo, "recurso", "")
        if recurso:
            clave = recurso.lower().replace("ó", "o")[:6]
            filtrados = [c for c in calzan if clave in getattr(c, "tipo_aa", "").lower().replace("ó", "o")]
            if len(filtrados) == 1:
                calzan = filtrados
    tolerado = None
    if not calzan and not ced and anexo.expediente and anexo.numero:
        # 2-oct (2026-IE-037292): la peticion no trae cedula; el expediente tiene UN
        # solo acto de ese tipo y su numero difiere en un digito ('23422' por 23423).
        unicos = [c for c in _sin_continuaciones(candidatos) if c.tipo == anexo.tipo]
        if len(unicos) == 1 and _casi_igual(anexo, unicos[0]) and \
                (not anexo.fecha or not unicos[0].fecha or unicos[0].fecha == anexo.fecha):
            tolerado = unicos[0]
    if not calzan and ced and anexo.expediente:
        # Mismo expediente Y misma cedula, mismo tipo y año, y UNA sola opcion:
        # es ese acto aunque la peticion traiga el numero con un digito de
        # menos ('01409_2026' por 14091, '00946_2026' por 9646) o la fecha del
        # Auto corrida un dia (18/09 por 17/09). Evidencia 29-sep: 036694/036695.
        anio = getattr(anexo, "anio", None)
        tol = [c for c in _sin_continuaciones(candidatos)
               if c.tipo == anexo.tipo and _re.sub(r"\D", "", c.cedula or "") == ced
               and (anio is None or (c.fecha or "").endswith(str(anio)))]
        tol = [c for c in tol if _casi_igual(anexo, c)]
        if len(tol) == 1:
            tolerado = tol[0]
    desc = (f"{_TIPO_LABEL.get(anexo.tipo, 'Acto')} "
            + (f"{anexo.numero}" if anexo.numero else f"del {anexo.fecha}")
            + f" (expediente {anexo.expediente}, cédula {anexo.cedula or '-'})")
    if not calzan and tolerado is not None:
        dato = (f"el número de la petición ({anexo.numero}) es distinto al del Cuadro ({tolerado.numero})"
                if anexo.tipo == "Resolucion" else
                f"la fecha de la petición ({anexo.fecha}) es distinta a la del Cuadro ({tolerado.fecha})")
        por = "expediente y cédula coinciden" if ced else "el expediente coincide (y la fecha)"
        return tolerado, [f"{desc}: {dato}; se tomó el del Cuadro porque {por} y es el "
                          "único acto de ese tipo -- revisar."]
    if not calzan:
        if anexo.tipo == "Resolucion" and anexo.numero and not anexo.expediente:
            # 2026-IE-036987: 'Resolución N° 1156 del 30 de abril de 2026'; en el
            # Cuadro la 1156 es del 20/01/2026. Se dice cual hay, no se elige.
            otros = _sin_continuaciones(cuadro.buscar_por_numero("Resolucion", anexo.numero))
            if otros:
                return None, [f"{desc}: la petición dice del {anexo.fecha or '?'} y en el Cuadro la Resolución "
                              f"{anexo.numero} es " + "; ".join(f"del {c.fecha} ({c.nombre}, exp. {c.expediente})"
                                                                for c in otros[:3])
                              + " -- confirma cuál es (si dejas el PDF en la carpeta del caso, se usa ese)."]
        return None, [f"{desc}: no aparece en el Cuadro con esos datos (ni por expediente ni por cédula)."]
    if len(calzan) > 1:
        return None, [f"{desc}: hay {len(calzan)} actos en el Cuadro con esos datos -- no se adivina."]
    elegido = calzan[0]
    if via == "cedula":
        warns.append(f"{desc}: ubicado en el Cuadro por la cédula (allá figura con el expediente {elegido.expediente}).")
    elif ced and elegido.cedula and _re.sub(r"\D", "", elegido.cedula) != ced:
        warns.append(f"{desc}: la cédula del Cuadro ({elegido.cedula}) no es igual a la de la petición -- revisar.")
    return elegido, warns


def _buscar_archivo_472(tipo: str, numero: str, expedientes_472: list[dict]) -> Optional[str]:
    """Una vez tipo+numero ya se conocen con certeza (via el Cuadro), busca
    en lo que el 472 ya proceso el nombre de archivo final a adjuntar.
    Cruce deterministico por tipo+numero, no por nombre."""
    key = _numero_key(numero)
    for exp in expedientes_472:
        if exp.get("tipo") == tipo and _numero_key(exp.get("numero")) == key:
            return exp.get("archivo")
    return None


# ------------------------------------------------------------------
# FORMATOS DE LAS TABLAS de las respuestas masivas (parametros guardados a
# pedido de Andres, 29-sep). Cada formato dice columnas, alineacion por
# columna, color del encabezado, tamaño de letra, ancho y formato de fecha.
# ------------------------------------------------------------------
# Masiva por expedientes -- respuesta aprobada 2026-IE-035664 (captura 28-sep).
FORMATO_TABLA_MASIVA = {
    "nombre": "masiva",
    "encabezado": ["Tipo de AA", "Numero", "Fecha", "Expediente"],
    "alineacion": ["center", "center", "center", "left"],
    "fondo_encabezado": "#1F3864",
    "fuente": "Verdana",
    "fuente_pt": 9,
    "fuente_pt_columna": {3: 8},
    "anchos_px": None,
    "fecha": "d/mm/aaaa",        # '6/08/2026'
}
# Pruebas de entrega por radicado interno -- cuadro que Andres pego en
# 2026-IE-036323 (captura 29-sep): 'Radicado Interno | No. Resolución |
# Fecha', encabezado azul marino con letra blanca en negrilla, radicado y
# fecha a la izquierda, numero centrado, fechas '20/08/2026'.
FORMATO_TABLA_RADICADOS = {
    "nombre": "radicados",
    "encabezado": ["Radicado Interno", "No. Resolución", "Fecha"],
    "alineacion": ["left", "center", "left"],
    "fondo_encabezado": "#000080",
    "fuente": "Verdana",
    "fuente_pt": 9,
    "fuente_pt_columna": {},
    "anchos_px": [125, 110, 115],
    "fecha": "dd/mm/aaaa",       # '20/08/2026'
}
# Si en una respuesta por radicados hay Autos mezclados con Resoluciones.
FORMATO_TABLA_RADICADOS_MIXTA = dict(
    FORMATO_TABLA_RADICADOS, nombre="radicados_mixta",
    encabezado=["Radicado Interno", "Tipo de AA", "Número", "Fecha"],
    alineacion=["left", "center", "center", "left"], anchos_px=[125, 90, 80, 115],
)
ENCABEZADO_TABLA_RADICADOS = FORMATO_TABLA_RADICADOS["encabezado"]


def resolver_actos_por_radicado(peticion: PeticionInfo, cuadro: CuadroIndex) -> list:
    """Peticion de PRUEBAS DE ENTREGA (caso 2026-IE-036323, metodo de Andres):
    cada radicado interno que cita la peticion se busca en la columna
    'NUMERO DE RADICADO' del Cuadro; cada Resolucion/Auto que aparezca es un
    acto a responder (en el orden de la peticion, y dentro de cada radicado
    por numero). El 'expediente' de la tabla es el radicado interno."""
    resultados: list = []
    for rad in peticion.radicados_internos:
        actos = sorted(cuadro.buscar_por_radicado_interno(rad), key=lambda a: (a.tipo, int(a.numero or 0)))
        for a in actos:
            anexo = AnexoSolicitado(
                nombre=a.nombre, cedula=a.cedula, expediente=rad, tipo=a.tipo, numero=a.numero,
                fecha=a.fecha, texto_original=f"{a.tipo} {a.numero} (radicado interno {rad})",
            )
            resultados.append(ActoResuelto(
                anexo=anexo, tipo_final=a.tipo, numero_final=a.numero, fecha_final=a.fecha or "",
                nombre_titular_cuadro=a.nombre, archivo_final=None, emparejado=bool(a.fecha),
                es_archivo=a.es_archivo, warnings=[] if a.fecha else [f"{a.tipo} {a.numero}: el Cuadro no trae su fecha"],
                email=a.email,
            ))
    return resultados


def resolver_actos(
    peticion: PeticionInfo,
    cuadro: CuadroIndex,
    expedientes_472: Optional[list[dict]] = None,
) -> list[ActoResuelto]:
    """Individualiza cada anexo solicitado en la peticion contra
    Cuadro_2026/2025 (cuadro), buscando por Expediente EE-XXXXXX -- el
    mismo criterio que Andres usa a diario. expedientes_472 (opcional:
    dicts con 'tipo','numero','archivo', misma convencion de excel_io.py)
    solo se usa para saber que PDF ya descargado adjuntar."""
    if getattr(peticion, "por_radicados_internos", False):
        return resolver_actos_por_radicado(peticion, cuadro)
    expedientes_472 = expedientes_472 or []
    resultados: list[ActoResuelto] = []

    for anexo in peticion.anexos:
        warns = list(anexo.warnings)
        anio = getattr(anexo, "anio", None)
        if anio and anio < ANIO_MINIMO_CUADRO:
            # Andres (29-sep, 2026-IE-036696): lo anterior a 2025 se le pide a
            # Magda; el resto del caso sigue.
            etiqueta = f"{_TIPO_LABEL.get(anexo.tipo, 'Acto')} {anexo.numero or ''}".strip()
            warns.append(f"{etiqueta} de {anio} (expediente {anexo.expediente}, cédula {anexo.cedula or '-'}): "
                         "anterior a 2025 -- PEDIR A MAGDA.")
            resultados.append(ActoResuelto(
                anexo=anexo, tipo_final=anexo.tipo, numero_final=anexo.numero, fecha_final=anexo.fecha or "",
                nombre_titular_cuadro=None, archivo_final=None, emparejado=False, warnings=warns,
                pedir_a_magda=True,
            ))
            continue

        elegido, warns_ubicar = _ubicar_en_cuadro(anexo, cuadro)
        anio_exp = anio_expediente(anexo.expediente)
        if elegido is None and anio_exp and anio_exp < ANIO_MINIMO_CUADRO:
            # Andres (1-oct, 2026-IE-036987): si el EXPEDIENTE es anterior a 2025
            # sus actos no estan en los Cuadros 2025/2026 -> alerta: PEDIR A MAGDA
            # (2021-EE-255254, CNV-2019-0004045). Los PDF que ella mande se dejan
            # en Descargas\<radicado>\ y Insignia los toma de ahi.
            warns.append(f"Expediente {anexo.expediente} ({anexo.nombre or 'sin nombre en la petición'}) es de "
                         f"{anio_exp}, anterior a 2025 -- PEDIR A MAGDA.")
            resultados.append(ActoResuelto(
                anexo=anexo, tipo_final=anexo.tipo, numero_final=anexo.numero, fecha_final=anexo.fecha or "",
                nombre_titular_cuadro=None, archivo_final=None, emparejado=False, warnings=warns,
                pedir_a_magda=True,
            ))
            continue
        warns.extend(warns_ubicar)
        if elegido is None:
            resultados.append(
                ActoResuelto(
                    anexo=anexo,
                    tipo_final=anexo.tipo,
                    numero_final=anexo.numero,
                    fecha_final=anexo.fecha or "",
                    nombre_titular_cuadro=None,
                    archivo_final=None,
                    emparejado=False,
                    warnings=warns,
                )
            )
            continue

        if not anexo.expediente and elegido.expediente:
            anexo.expediente = elegido.expediente
            warns.append(f"Expediente {elegido.expediente} tomado del Cuadro (la peticion solo trae el numero del acto).")
        if not anexo.nombre and elegido.nombre:
            anexo.nombre = elegido.nombre

        # verificaciones cruzadas contra lo que la propia peticion trae
        if anexo.tipo == "Resolucion" and anexo.numero and _numero_key(anexo.numero) != elegido.numero:
            warns.append(
                f"El numero de Resolucion en la peticion ({anexo.numero}) no coincide "
                f"con el del Cuadro ({elegido.numero}) para '{anexo.nombre}'"
            )
        if anexo.tipo == "Auto" and anexo.fecha and anexo.fecha != elegido.fecha:
            warns.append(
                f"La fecha del Auto en la peticion ({anexo.fecha}) no coincide con la "
                f"del Cuadro ({elegido.fecha}) para '{anexo.nombre}'"
            )

        archivo_final = _buscar_archivo_472(elegido.tipo, elegido.numero, expedientes_472)
        if archivo_final is None and expedientes_472:
            warns.append(
                f"No se encontro en el reporte 4-72 el archivo ya procesado para "
                f"{elegido.tipo} {elegido.numero} (expediente {anexo.expediente})"
            )

        resultados.append(
            ActoResuelto(
                anexo=anexo,
                tipo_final=elegido.tipo,
                numero_final=elegido.numero,
                fecha_final=elegido.fecha or "",
                nombre_titular_cuadro=elegido.nombre,
                archivo_final=archivo_final,
                emparejado=True,
                es_archivo=elegido.es_archivo,
                warnings=warns,
                email=getattr(elegido, "email", ""),
            )
        )
    return resultados


def _describir_acto(a) -> str:
    x = a.anexo
    if not x.numero and not x.fecha:
        crudo = [c for c in (x.texto_original or "").split(" | ")
                 if c and c != x.expediente and c != x.nombre and c != x.cedula]
        return (f"actos del expediente {x.expediente or '-'}"
                + (f" ({x.nombre})" if x.nombre else "")
                + (f" [la petición dice '{crudo[-1]}']" if crudo and len(crudo[-1]) <= 40 and " | " in (x.texto_original or "") else "")
                + (f" -- resolución del recurso de {x.recurso.lower()}" if getattr(x, "recurso", "") else ""))
    cuerpo =f"{_TIPO_LABEL.get(x.tipo, 'Acto')} " + (f"{x.numero}" if x.numero else f"del {x.fecha or '?'}")
    if getattr(x, "anio", None) and x.numero:
        cuerpo += f" de {x.anio}"
    return f"{cuerpo} (exp. {x.expediente or '-'}, C.C. {x.cedula or '-'})"


def generar_carta(
    peticion: PeticionInfo,
    cuadro: CuadroIndex,
    tratamiento: str,
    expedientes_472: Optional[list[dict]] = None,
    zip_filename: Optional[str] = None,
    actos_resueltos: Optional[list] = None,
) -> Carta:
    """Arma la Carta (destinatario + asunto + saludo + cuerpo + adjunto)
    lista para copiar al editor de SGDEA.

    cuadro: CuadroIndex de backend.cuadro_lookup.load_cuadro(...) -- es la
    fuente de verdad para individualizar cada acto por su Expediente.
    tratamiento: "Doctor" o "Doctora" -- lo decide Andres al leer el nombre
    del destinatario (ver nota en sgdea_peticion.Destinatario); este modulo
    nunca lo adivina.
    expedientes_472: opcional, lo que el pipeline 4-72 ya proceso para este
    lote (para saber que PDF adjuntar en el caso individual).
    zip_filename: nombre del zip a adjuntar en el caso masiva (por
    convencion observada: '{radicado_peticion}.zip'); si no se pasa, se usa
    esa convencion por defecto.
    """
    if tratamiento not in ("Doctor", "Doctora"):
        raise ValueError("tratamiento debe ser 'Doctor' o 'Doctora' (lo decide Andres)")

    warnings = list(peticion.warnings)
    dest = peticion.destinatario
    if dest is None:
        raise ValueError(
            "No hay destinatario extraido de la peticion; no se puede armar la carta"
        )

    radicado_peticion = peticion.radicado or ""
    if not radicado_peticion:
        warnings.append("No se pudo leer el radicado de la peticion; revisar 'Asunto' manualmente")

    nombre_pila, aviso_saludo = _nombre_saludo(dest.nombre, tratamiento)
    if aviso_saludo:
        warnings.append(aviso_saludo)
    asunto = f"Respuesta a Radicado {radicado_peticion}"
    saludo = f"Cordial Saludo, {tratamiento} {nombre_pila}:"

    actos = list(actos_resueltos) if actos_resueltos is not None else resolver_actos(peticion, cuadro, expedientes_472)
    for a in actos:
        warnings.extend(f"[{a.anexo.expediente}] {w}" for w in a.warnings)
    if peticion.es_masiva:
        # Andres (29-sep, 2026-IE-036696): se avanza con los actos que SI se
        # ubicaron; los anteriores a 2025 se piden a Magda y los que no estan
        # en el Cuadro quedan listados para revisar. No van en la tabla.
        magda = [a for a in actos if a.pedir_a_magda]
        no_ubicados = [a for a in actos if not a.emparejado and not a.pedir_a_magda]
        if magda:
            warnings.append("PEDIR A MAGDA (anteriores a 2025, no van en esta respuesta): "
                            + "; ".join(_describir_acto(a) for a in magda))
        if no_ubicados:
            warnings.append("NO UBICADOS en el Cuadro (no van en esta respuesta; revisar o actualizar el Cuadro): "
                            + "; ".join(_describir_acto(a) for a in no_ubicados))
        actos = [a for a in actos if a.emparejado]
        if not actos and not getattr(peticion, "por_radicados_internos", False):
            raise ValueError("ninguno de los actos solicitados se pudo ubicar en el Cuadro"
                             + (" (los anteriores a 2025 se piden a Magda)" if magda else ""))

    tabla_encabezado = None
    tabla_formato = None
    if getattr(peticion, "por_radicados_internos", False):
        solo_resoluciones = all(a.tipo_final == "Resolucion" for a in actos)
        tabla_formato = dict(FORMATO_TABLA_RADICADOS if solo_resoluciones else FORMATO_TABLA_RADICADOS_MIXTA)
        tabla_encabezado = list(tabla_formato["encabezado"])
        con_actos = {a.anexo.expediente for a in actos}
        for rad in peticion.radicados_internos:
            if rad not in con_actos:
                warnings.append(
                    f"El radicado interno {rad} no tiene ningún acto en el Cuadro (columna 'NUMERO DE RADICADO') "
                    "-- no va en la tabla; revisa si hay que mencionarlo en la respuesta."
                )
        if not actos:
            raise ValueError("ninguno de los radicados internos de la peticion tiene actos en el Cuadro")

    if peticion.es_masiva:
        cuerpo_parrafo = (
            f"De manera atenta y en respuesta a la comunicación interna "
            f"{radicado_peticion}, se remite copia y constancia de notificación de "
            f"los siguientes Actos Administrativos, para lo de su competencia."
        )
        # Columnas y formato de la respuesta masiva aprobada (caso
        # 2026-IE-035664): Tipo de AA | Numero | Fecha | Expediente.
        if tabla_formato and tabla_formato["nombre"] == "radicados":
            tabla = [[a.anexo.expediente, a.numero_final, a.fecha_final] for a in actos]
        elif tabla_formato:
            tabla = [[a.anexo.expediente, _TIPO_LABEL.get(a.tipo_final, "Acto"), a.numero_final, a.fecha_final]
                     for a in actos]
        else:
            tabla = [
                [
                    _TIPO_LABEL.get(a.tipo_final, "Acto"),
                    a.numero_final,
                    _fecha_tabla(a.fecha_final),
                    a.anexo.expediente,
                ]
                for a in actos
            ]
        adjunto_nombre = zip_filename or (f"{radicado_peticion}.zip" if radicado_peticion else "")
        if not adjunto_nombre:
            warnings.append("No se pudo determinar el nombre del zip a adjuntar")
    else:
        if not actos:
            raise ValueError("La peticion no trae ningun anexo/acto identificado")
        a = actos[0]
        tipo_label = _TIPO_LABEL.get(a.tipo_final, "Acto")
        articulo = _TIPO_ARTICULO.get(a.tipo_final, "del")
        if a.es_archivo:
            # Confirmado por Andres (caso real 2025-EE-104761, Auto de
            # Archivo No. 2336): se cita SOLO por fecha, sin el numero
            # interno del Cuadro -- igual que en la plantilla ya aprobada
            # ("del Auto de Archivo del <fecha>").
            descripcion_acto = f"{tipo_label} de Archivo del {_fecha_a_texto(a.fecha_final)}"
        else:
            descripcion_acto = f"{tipo_label} No. {a.numero_final} del {_fecha_a_texto(a.fecha_final)}"
        # Redaccion del video de Andres (25-sep, caso 2026-IE-035690): "...del
        # 03 de julio de 2026 a nombre del señor CARLOS GUSTAVO CAICEDO ROJAS,
        # emitido en el expediente ..." (sin coma antes de 'a nombre').
        # 30-sep (Andres): sin "del señor"/"de la señora" -- siempre
        # "a nombre de <NOMBRE>" (ya no se infiere ni se avisa).
        cuerpo_parrafo = (
            f"De manera atenta y en respuesta a la comunicación interna "
            f"{radicado_peticion}, se remite copia y constancia de notificación "
            f"{articulo} {descripcion_acto} "
            f"a nombre de {a.anexo.nombre}, emitido en el expediente "
            f"{a.anexo.expediente}, para lo de su competencia."
        )
        if not a.emparejado:
            warnings.append(
                "El acto no se pudo emparejar con certeza contra el Cuadro: "
                "revisar si corresponde citarlo 'de Archivo' (sin numero) o "
                "con su numero antes de pegar."
            )
        tabla = None
        adjunto_nombre = a.archivo_final or ""
        if not adjunto_nombre:
            warnings.append(
                f"No se encontro el nombre de archivo final para '{a.anexo.nombre}'; "
                "revisar manualmente cual PDF adjuntar"
            )

    return Carta(
        tratamiento=tratamiento,
        destinatario_nombre=dest.nombre,
        destinatario_cargo=dest.cargo,
        destinatario_subdireccion=dest.subdireccion,
        nombre_pila=nombre_pila,
        radicado_peticion=radicado_peticion,
        asunto=asunto,
        saludo=saludo,
        cuerpo_parrafo=cuerpo_parrafo,
        tabla=tabla,
        adjunto_nombre=adjunto_nombre,
        es_masiva=peticion.es_masiva,
        warnings=warnings,
        tabla_encabezado=tabla_encabezado,
        tabla_formato=tabla_formato,
    )

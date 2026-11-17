"""Búsqueda de duplicados y comparación de playlists.

Las canciones llegan como {"titulo": str, "artista": str}. Como YouTube y
Spotify escriben los nombres distinto ("Canción (Official Video)" contra
"Canción", "Bad Bunny - Topic" contra "Bad Bunny"), antes de comparar se
limpian títulos y artistas.
"""

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y con espacios colapsados."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.lower().split())


# ---------------------------------------------------------------- duplicados

def buscar_duplicados(canciones: list[dict]) -> list[dict]:
    """Agrupa por título+artista normalizados y devuelve las canciones que se repiten."""
    grupos: dict[tuple[str, str], dict] = {}

    for c in canciones:
        clave = (normalizar(c["titulo"]), normalizar(c["artista"]))
        grupo = grupos.setdefault(clave, {"Título": c["titulo"], "Artista": c["artista"], "Repeticiones": 0})
        grupo["Repeticiones"] += 1

    duplicados = [g for g in grupos.values() if g["Repeticiones"] > 1]
    duplicados.sort(key=lambda g: (normalizar(g["Título"]), normalizar(g["Artista"])))
    return duplicados


# ---------------------------------------------------------------- comparación

_ENTRE_PARENTESIS = re.compile(r"[(\[{].*?[)\]}]")
_FEAT = re.compile(r"\s(?:feat|ft|featuring)\b.*$")
_RELLENO = re.compile(
    r"\b(?:official|oficial)\b(?:\s+(?:music|musical))?(?:\s+(?:video|audio|lyric video|visualizer|videoclip))?"
    r"|\bvideo\s+oficial\b|\baudio\s+oficial\b|\blyrics?\b|\bletra\b|\bvisualizer\b|\bhd\b|\b4k\b"
)
_NO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")
_SUFIJOS_CANAL = re.compile(r"(?:\s*-\s*topic|vevo|\bofficial\b|\boficial\b)\s*$")


def _limpiar_titulo(titulo: str) -> str:
    t = normalizar(titulo)
    t = _ENTRE_PARENTESIS.sub(" ", t)
    t = t.split("|")[0]
    t = _FEAT.sub("", t)
    t = _RELLENO.sub(" ", t)
    return " ".join(_NO_ALFANUMERICO.sub(" ", t).split())


def _limpiar_artista(nombre: str) -> str:
    a = normalizar(nombre)
    a = _SUFIJOS_CANAL.sub("", a)
    return _NO_ALFANUMERICO.sub("", a)  # sin espacios: "Bad Bunny" y "BadBunnyPR" se pueden comparar


@dataclass
class _Cancion:
    original: dict
    claves: set[str]       # posibles títulos limpios
    artistas: list[str]    # artistas limpios, sin espacios
    texto: str             # artistas + título, sin espacios, para buscar coincidencias
    palabras: frozenset    # palabras del título completo, para la comparación aproximada


def _preparar(c: dict) -> _Cancion:
    titulo = c["titulo"] or ""
    claves = {_limpiar_titulo(titulo)}
    # En YouTube muchos videos se llaman "Artista - Canción": se prueban ambas partes.
    sin_parentesis = _ENTRE_PARENTESIS.sub(" ", titulo)
    if " - " in sin_parentesis:
        for parte in sin_parentesis.split(" - ", 1):
            claves.add(_limpiar_titulo(parte))
    claves.discard("")

    artistas = [a for a in (_limpiar_artista(x) for x in re.split(r",|&| x ", c["artista"] or "", flags=re.IGNORECASE)) if a]
    texto = "".join(artistas) + _NO_ALFANUMERICO.sub("", normalizar(titulo))
    palabras = frozenset(_NO_ALFANUMERICO.sub(" ", _RELLENO.sub(" ", _ENTRE_PARENTESIS.sub(" ", normalizar(titulo)))).split())
    return _Cancion(c, claves, artistas, texto, palabras)


def _mismo_artista(a: _Cancion, b: _Cancion) -> bool:
    if not a.artistas or not b.artistas:
        return True  # sin información de artista, basta con el título
    return (any(len(x) >= 3 and x in b.texto for x in a.artistas)
            or any(len(x) >= 3 and x in a.texto for x in b.artistas))


@dataclass
class _Indice:
    por_titulo: dict[str, list[_Cancion]]
    por_artista: dict[str, list[_Cancion]]


def _indexar(canciones: list[_Cancion]) -> _Indice:
    por_titulo, por_artista = defaultdict(list), defaultdict(list)
    for c in canciones:
        for clave in c.claves:
            por_titulo[clave].append(c)
        for artista in c.artistas:
            por_artista[artista].append(c)
    return _Indice(por_titulo, por_artista)


def _parecidas(a: frozenset, b: frozenset) -> bool:
    """Títulos que comparten la mayoría de sus palabras (al menos 3)."""
    comunes = len(a & b)
    return comunes >= 3 and comunes / len(a | b) >= 0.7


def _esta_en(c: _Cancion, indice: _Indice) -> bool:
    # 1) Mismo título limpio y artista compatible.
    if any(_mismo_artista(c, otra) for clave in c.claves for otra in indice.por_titulo.get(clave, [])):
        return True
    # 2) Título parecido entre canciones del mismo artista
    #    (p. ej. "Shakira || BZRP Music Sessions #53" contra "Shakira: Bzrp Music Sessions, Vol. 53").
    return any(_parecidas(c.palabras, otra.palabras) for artista in c.artistas for otra in indice.por_artista.get(artista, []))


def _sin_repetir(canciones: list[_Cancion]) -> list[dict]:
    vistas, resultado = set(), []
    for c in canciones:
        clave = (min(c.claves, default=""), tuple(c.artistas))
        if clave not in vistas:
            vistas.add(clave)
            resultado.append({"Título": c.original["titulo"], "Artista": c.original["artista"]})
    return resultado


def comparar(lista_a: list[dict], lista_b: list[dict]) -> dict:
    """Devuelve qué canciones de A faltan en B, cuáles de B faltan en A y cuántas comparten."""
    a = [_preparar(c) for c in lista_a]
    b = [_preparar(c) for c in lista_b]
    indice_a, indice_b = _indexar(a), _indexar(b)

    faltan_en_b = [c for c in a if not _esta_en(c, indice_b)]
    faltan_en_a = [c for c in b if not _esta_en(c, indice_a)]
    en_comun = len(_sin_repetir([c for c in a if _esta_en(c, indice_b)]))

    return {
        "faltan_en_b": _sin_repetir(faltan_en_b),
        "faltan_en_a": _sin_repetir(faltan_en_a),
        "en_comun": en_comun,
    }

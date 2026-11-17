import logging
import os
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from ytmusicapi import YTMusic

logger = logging.getLogger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory="templates")
ytmusic = YTMusic()  # No requiere login porque solo va a LEER playlists públicas/deslistadas


def extraer_playlist_id(url: str) -> str:
    """Obtiene el parámetro 'list' de una URL; si no lo hay, asume que ya es un ID."""
    parametros = parse_qs(urlparse(url).query)
    return parametros.get("list", [url])[0].strip()


def normalizar(texto: str) -> str:
    """Texto en minúsculas y con espacios colapsados, para comparar canciones."""
    return " ".join(texto.lower().split())


def buscar_duplicados(tracks: list[dict]) -> list[dict]:
    """Agrupa las canciones por título+artista normalizados y devuelve las que se repiten."""
    grupos: dict[tuple[str, str], dict] = {}

    for track in tracks:
        titulo = track.get("title") or "Desconocido"
        artistas = track.get("artists") or []
        artista = ", ".join(a["name"] for a in artistas if a and a.get("name"))

        # Se compara por título y artista normalizados: así se detecta tanto el
        # mismo video repetido como versiones distintas subidas con el mismo nombre.
        clave = (normalizar(titulo), normalizar(artista))
        grupo = grupos.setdefault(clave, {"Título": titulo, "Artista": artista, "Repeticiones": 0})
        grupo["Repeticiones"] += 1

    duplicados = [g for g in grupos.values() if g["Repeticiones"] > 1]
    duplicados.sort(key=lambda g: (normalizar(g["Título"]), normalizar(g["Artista"])))
    return duplicados


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


# Función síncrona a propósito: FastAPI la ejecuta en un hilo aparte, así una
# playlist grande no bloquea al servidor mientras ytmusicapi descarga los datos.
@app.post("/analizar")
def analizar(url: str = Form(...)):
    playlist_id = extraer_playlist_id(url.strip())
    if not playlist_id:
        return JSONResponse(status_code=400, content={"error": "Ingresa la URL de una playlist."})

    try:
        playlist = ytmusic.get_playlist(playlist_id, limit=None)
    except Exception:
        logger.exception("Error al obtener la playlist %s", playlist_id)
        return JSONResponse(
            status_code=400,
            content={"error": "No se pudo acceder a la playlist. Verifica que sea pública o deslistada."},
        )

    tracks = playlist.get("tracks") or []
    return {"duplicados": buscar_duplicados(tracks), "total": len(tracks)}


if __name__ == "__main__":
    import uvicorn

    # Recarga automática solo en desarrollo: DEV=1 python main.py
    uvicorn.run("main:app", reload=os.getenv("DEV") == "1")

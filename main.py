import logging
import os
import time
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from ytmusicapi import YTMusic

from analisis import buscar_duplicados, comparar

logger = logging.getLogger(__name__)

# Link de donaciones. Se puede cambiar con la variable DONACIONES_URL (vacía = sin botón).
DONACIONES_URL = os.getenv("DONACIONES_URL", "https://ko-fi.com/carwhite01").strip()
if DONACIONES_URL and not DONACIONES_URL.startswith("https://"):
    logger.warning("DONACIONES_URL debe empezar con https://; se ignora el botón de donaciones.")
    DONACIONES_URL = ""

app = FastAPI()
templates = Jinja2Templates(directory="templates")
ytmusic = YTMusic()  # No requiere login porque solo va a LEER playlists públicas/deslistadas


class ErrorPlaylist(Exception):
    """Error con un mensaje listo para mostrarse al usuario."""


def extraer_playlist_id(url: str) -> str:
    """Obtiene el parámetro 'list' de una URL de YouTube; si no lo hay, asume que ya es un ID."""
    parametros = parse_qs(urlparse(url).query)
    return parametros.get("list", [url])[0].strip()


def obtener_youtube(url: str) -> tuple[str, list[dict]]:
    playlist_id = extraer_playlist_id(url)
    if not playlist_id:
        raise ErrorPlaylist("Ingresa la URL de una playlist.")
    # A veces YouTube responde vacío por un momento: se intenta una segunda vez.
    for intento in (1, 2):
        try:
            playlist = ytmusic.get_playlist(playlist_id, limit=None)
            break
        except Exception as e:
            if intento == 2:
                logger.exception("Error al obtener la playlist %s", playlist_id)
                raise ErrorPlaylist(
                    "No se pudo acceder a la playlist de YouTube. Verifica que sea pública o deslistada."
                ) from e
            time.sleep(1)

    canciones = []
    for track in playlist.get("tracks") or []:
        artistas = track.get("artists") or []
        canciones.append({
            "titulo": track.get("title") or "Desconocido",
            "artista": ", ".join(a["name"] for a in artistas if a and a.get("name")),
        })
    return playlist.get("title") or "Playlist de YouTube", canciones


def respuesta_error(e: ErrorPlaylist) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"donaciones_url": DONACIONES_URL})


# Las rutas son síncronas a propósito: FastAPI las ejecuta en un hilo aparte, así
# una playlist grande no bloquea al servidor mientras se descargan los datos.
@app.post("/analizar")
def analizar(url: str = Form(...)):
    try:
        _, canciones = obtener_youtube(url.strip())
    except ErrorPlaylist as e:
        return respuesta_error(e)
    return {"duplicados": buscar_duplicados(canciones), "total": len(canciones)}


@app.post("/comparar")
def comparar_playlists(url_a: str = Form(...), url_b: str = Form(...)):
    try:
        nombre_a, canciones_a = obtener_youtube(url_a.strip())
        if extraer_playlist_id(url_a.strip()) == extraer_playlist_id(url_b.strip()):
            nombre_b, canciones_b = nombre_a, canciones_a  # misma playlist: no se descarga dos veces
        else:
            nombre_b, canciones_b = obtener_youtube(url_b.strip())
    except ErrorPlaylist as e:
        return respuesta_error(e)

    return {
        "a": {"nombre": nombre_a, "total": len(canciones_a)},
        "b": {"nombre": nombre_b, "total": len(canciones_b)},
        **comparar(canciones_a, canciones_b),
    }


if __name__ == "__main__":
    import uvicorn

    # Recarga automática solo en desarrollo: DEV=1 python main.py
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=os.getenv("DEV") == "1")

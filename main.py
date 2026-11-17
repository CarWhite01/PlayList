import logging
import os
import secrets
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from ytmusicapi import YTMusic

import spotify
from analisis import buscar_duplicados, comparar

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    logger.warning("SECRET_KEY no está definida: las sesiones de Spotify se perderán al reiniciar el servidor.")
    SECRET_KEY = secrets.token_urlsafe(32)

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=spotify.REDIRECT_URI.startswith("https://"),
)
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
    try:
        playlist = ytmusic.get_playlist(playlist_id, limit=None)
    except Exception as e:
        logger.exception("Error al obtener la playlist %s", playlist_id)
        raise ErrorPlaylist(
            "No se pudo acceder a la playlist de YouTube. Verifica que sea pública o deslistada."
        ) from e

    canciones = []
    for track in playlist.get("tracks") or []:
        artistas = track.get("artists") or []
        canciones.append({
            "titulo": track.get("title") or "Desconocido",
            "artista": ", ".join(a["name"] for a in artistas if a and a.get("name")),
        })
    return playlist.get("title") or "Playlist de YouTube", canciones


def obtener_playlist(request: Request, url: str) -> tuple[str, list[dict]]:
    """Detecta si la URL es de Spotify o de YouTube y devuelve (nombre, canciones)."""
    url = url.strip()
    if "spotify" in url.lower():
        if not spotify.configurado():
            raise ErrorPlaylist("Este servidor no tiene configurado Spotify.")
        return spotify.obtener_playlist(request.session, url)
    return obtener_youtube(url)


def respuesta_error(e: Exception) -> JSONResponse:
    if isinstance(e, spotify.SpotifyNoConectado):
        return JSONResponse(status_code=401, content={"error": str(e), "spotify_login": True})
    return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={
        "spotify_configurado": spotify.configurado(),
        "spotify_conectado": spotify.conectado(request.session),
        "spotify_estado": request.query_params.get("spotify"),
    })


# Las rutas son síncronas a propósito: FastAPI las ejecuta en un hilo aparte, así
# una playlist grande no bloquea al servidor mientras se descargan los datos.
@app.post("/analizar")
def analizar(request: Request, url: str = Form(...)):
    try:
        _, canciones = obtener_playlist(request, url)
    except (ErrorPlaylist, spotify.ErrorSpotify) as e:
        return respuesta_error(e)
    return {"duplicados": buscar_duplicados(canciones), "total": len(canciones)}


@app.post("/comparar")
def comparar_playlists(request: Request, url_a: str = Form(...), url_b: str = Form(...)):
    try:
        nombre_a, canciones_a = obtener_playlist(request, url_a)
        nombre_b, canciones_b = obtener_playlist(request, url_b)
    except (ErrorPlaylist, spotify.ErrorSpotify) as e:
        return respuesta_error(e)

    return {
        "a": {"nombre": nombre_a, "total": len(canciones_a)},
        "b": {"nombre": nombre_b, "total": len(canciones_b)},
        **comparar(canciones_a, canciones_b),
    }


@app.get("/spotify/login")
def spotify_login(request: Request):
    if not spotify.configurado():
        return RedirectResponse("/?spotify=no-configurado", status_code=303)
    return RedirectResponse(spotify.url_login(request.session), status_code=303)


@app.get("/spotify/callback")
def spotify_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return RedirectResponse("/?spotify=cancelado", status_code=303)
    try:
        spotify.completar_login(request.session, code, state)
    except spotify.ErrorSpotify:
        logger.exception("Falló el inicio de sesión con Spotify")
        return RedirectResponse("/?spotify=error", status_code=303)
    return RedirectResponse("/?spotify=conectado", status_code=303)


@app.post("/spotify/logout")
def spotify_logout(request: Request):
    spotify.cerrar_sesion(request.session)
    return RedirectResponse("/", status_code=303)


if __name__ == "__main__":
    import uvicorn

    # Recarga automática solo en desarrollo: DEV=1 python main.py
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=os.getenv("DEV") == "1")

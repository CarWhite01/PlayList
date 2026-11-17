from urllib.parse import parse_qs, urlparse

import pytest
from types import SimpleNamespace
from fastapi.testclient import TestClient

import main
import spotify


class Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data
        self.ok = 200 <= status < 300

    def json(self):
        return self._data


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(spotify, "CLIENT_ID", "id-de-prueba")
    llamadas = []

    def post(url, data, timeout):
        llamadas.append(("POST", data["grant_type"]))
        return Resp(200, {"access_token": "tok", "refresh_token": "ref", "expires_in": 3600})

    def get(url, params=None, timeout=None, headers=None):
        llamadas.append(("GET", url))
        assert headers["Authorization"] == "Bearer tok"
        if url.endswith("/playlists/privada/items"):
            return Resp(403, {})
        if url.endswith("/playlists/abc"):
            return Resp(200, {"name": "Mi Spotify"})
        if url.endswith("/playlists/abc/items"):
            return Resp(200, {"items": [
                {"item": {"name": "Me Porto Bonito", "artists": [{"name": "Bad Bunny"}]}, "track": True},
                {"track": {"name": "Formato viejo", "artists": [{"name": "X"}]}},
                {"item": None},
            ], "next": "https://api.spotify.com/v1/playlists/abc/items?offset=50&limit=50"})
        if "offset=50" in url:
            return Resp(200, {"items": [{"item": {"name": "Me Porto Bonito", "artists": [{"name": "Bad Bunny"}]}}], "next": None})
        if url.endswith("/playlists/privada"):
            return Resp(200, {"name": "Ajena"})
        raise AssertionError(url)

    monkeypatch.setattr(spotify.requests, "post", post)
    monkeypatch.setattr(spotify.requests, "get", get)
    return TestClient(main.app), llamadas


def login(c):
    r = c.get("/spotify/login", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["id-de-prueba"]
    r = c.get(f"/spotify/callback?code=c0de&state={q['state'][0]}", follow_redirects=False)
    assert r.headers["location"] == "/?spotify=conectado"


def test_sin_login_pide_conectar(cliente):
    c, _ = cliente
    r = c.post("/analizar", data={"url": "https://open.spotify.com/playlist/abc"})
    assert r.status_code == 401 and r.json()["spotify_login"] is True


def test_state_invalido_no_conecta(cliente):
    c, _ = cliente
    c.get("/spotify/login", follow_redirects=False)
    r = c.get("/spotify/callback?code=x&state=otro", follow_redirects=False)
    assert r.headers["location"] == "/?spotify=error"
    assert "Spotify conectado" not in c.get("/").text


def test_login_lee_playlist_paginada_y_logout(cliente):
    c, llamadas = cliente
    login(c)
    assert "Spotify conectado" in c.get("/").text

    r = c.post("/analizar", data={"url": "https://open.spotify.com/intl-es/playlist/abc?si=1"})
    assert r.json() == {"duplicados": [{"Título": "Me Porto Bonito", "Artista": "Bad Bunny", "Repeticiones": 2}], "total": 3}

    r = c.post("/analizar", data={"url": "spotify:playlist:privada"})
    assert r.status_code == 400 and "tuyas o colaborativas" in r.json()["error"]

    c.post("/spotify/logout")
    assert c.post("/analizar", data={"url": "https://open.spotify.com/playlist/abc"}).status_code == 401


def test_refresca_token_vencido(cliente, monkeypatch):
    c, llamadas = cliente
    login(c)
    monkeypatch.setattr(spotify, "time", SimpleNamespace(time=lambda: 10**12))
    c.post("/analizar", data={"url": "https://open.spotify.com/playlist/abc"})
    assert ("POST", "refresh_token") in llamadas


def test_comparar_mezcla_youtube_y_spotify(cliente, monkeypatch):
    c, _ = cliente
    login(c)
    monkeypatch.setattr(main.ytmusic, "get_playlist", lambda pid, limit: {"title": "Mi YouTube", "tracks": [
        {"title": "Bad Bunny - Me Porto Bonito (Official Video)", "artists": [{"name": "BadBunnyVEVO"}]},
        {"title": "Solo en YouTube", "artists": None},
    ]})
    r = c.post("/comparar", data={"url_a": "https://music.youtube.com/playlist?list=PL1",
                                  "url_b": "https://open.spotify.com/playlist/abc"}).json()
    assert r["a"] == {"nombre": "Mi YouTube", "total": 2}
    assert r["b"] == {"nombre": "Mi Spotify", "total": 3}
    assert r["en_comun"] == 1
    assert [x["Título"] for x in r["faltan_en_b"]] == ["Solo en YouTube"]
    assert [x["Título"] for x in r["faltan_en_a"]] == ["Formato viejo"]

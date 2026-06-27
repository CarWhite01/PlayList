from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from ytmusicapi import YTMusic
import pandas as pd
import re

app = FastAPI()
templates = Jinja2Templates(directory="templates")
ytmusic = YTMusic()  # No requiere login porque solo va a LEER playlists públicas/deslistadas

def extraer_playlist_id(url: str) -> str:
    # Busca el patrón 'list=ID_DE_LA_PLAYLIST' en la URL
    match = re.search(r"list=([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else url

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
   return templates.TemplateResponse(request=request, name="index.html")

@app.post("/analizar")
async def analizar(url: str = Form(...)):
    playlist_id = extraer_playlist_id(url.strip())
    
    try:
        playlist = ytmusic.get_playlist(playlist_id, limit=3000)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"No se pudo acceder a la playlist. Verifica que sea pública o deslistada."})

    tracks = playlist.get('tracks', [])
    if not tracks:
        return JSONResponse(content={"duplicados": [], "total": 0})

    datos_canciones = []
    for track in tracks:
        datos_canciones.append({
            'Título': track.get('title', 'Desconocido'),
            'Artista': ", ".join([a['name'] for a in track.get('artists', []) if 'name' in a])
        })
        
    df = pd.DataFrame(datos_canciones)
    df['Filtro_Titulo'] = df['Título'].str.lower().str.strip()
    df['Filtro_Artista'] = df['Artista'].str.lower().str.strip()
    
    # Encontrar duplicados reales
    duplicados_df = df[df.duplicated(subset=['Filtro_Titulo', 'Filtro_Artista'], keep=False)]
    
    if duplicados_df.empty:
        return JSONResponse(content={"duplicados": [], "total": len(df)})
        
    # Agrupar y contar cuántas veces se repiten
    conteo = duplicados_df.groupby(['Título', 'Artista']).size().reset_index(name='Repeticiones')
    conteo = conteo.sort_values(by=['Título', 'Artista'])
    
    # Convertir a formato lista de diccionarios para enviarlo a la web
    lista_duplicados = conteo.to_dict(orient='records')
    
    return JSONResponse(content={"duplicados": lista_duplicados, "total": len(df)})

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("main:app", reload=True)
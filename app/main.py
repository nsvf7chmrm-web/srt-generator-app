from pathlib import Path
import shutil
import uuid

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse

from app.pipeline import generate_srt


app = FastAPI(title="SRT Generator")


BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
TEMPLATE_PATH = BASE_DIR / "templates" / "index.html"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse)
def home():
    return TEMPLATE_PATH.read_text(encoding="utf-8")


@app.post("/generate", response_class=HTMLResponse)
async def generate(
    file: UploadFile = File(...),
    language: str = Form("es"),
    audio_profile: str = Form("old_film"),
):
    job_id = str(uuid.uuid4())

    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    original_stem = Path(file.filename or "video").stem

    video_path = UPLOAD_DIR / f"{job_id}{suffix}"
    output_dir = OUTPUT_DIR / job_id

    with video_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    srt_path = generate_srt(
        video_path=video_path,
        output_dir=output_dir,
        language=language,
        audio_profile=audio_profile,
    )

    if not srt_path.exists():
        return HTMLResponse(
            "<h2>Error: no se generó el archivo SRT.</h2>",
            status_code=500,
        )

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="UTF-8">
      <title>SRT listo</title>
    </head>
    <body style="font-family: Arial; background:#0f172a; color:#e2e8f0; display:flex; justify-content:center; align-items:center; min-height:100vh; margin:0;">
      <div style="background:#1e293b; padding:32px; border-radius:14px; text-align:center; width:420px;">
        <h2>✅ SRT generado correctamente</h2>
        <p>Tu archivo está listo para descargar.</p>
        <a href="/download/{job_id}/{original_stem}"
           style="display:inline-block; margin-top:18px; padding:14px 24px; background:#3b82f6; color:white; text-decoration:none; border-radius:8px; font-weight:bold;">
          Descargar SRT
        </a>
        <br><br>
        <a href="/" style="color:#93c5fd;">Procesar otro video</a>
      </div>
    </body>
    </html>
    """)


@app.get("/download/{job_id}/{original_stem}")
def download(job_id: str, original_stem: str):
    output_dir = OUTPUT_DIR / job_id
    srt_path = output_dir / "output.srt"

    if not srt_path.exists():
        return HTMLResponse(
            "<h2>Error: no encontré el archivo SRT.</h2>",
            status_code=404,
        )

    return FileResponse(
        path=srt_path,
        media_type="application/x-subrip",
        filename=f"{original_stem}.srt",
    )
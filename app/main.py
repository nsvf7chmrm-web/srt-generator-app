from pathlib import Path
import shutil
import uuid
import threading
import traceback

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

from app.pipeline import generate_srt
from app.translate import translate_srt_file


app = FastAPI(title="Subtitle Studio")

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
TEMPLATE_PATH = BASE_DIR / "templates" / "index.html"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

JOBS = {}


@app.get("/", response_class=HTMLResponse)
def home():
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def run_generate_job(job_id, video_path, output_dir, language, audio_profile):
    try:
        JOBS[job_id]["status"] = "processing"
        JOBS[job_id]["message"] = "Procesando video..."

        srt_path = generate_srt(
            video_path=video_path,
            output_dir=output_dir,
            language=language,
            audio_profile=audio_profile,
        )

        if not srt_path.exists():
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["message"] = "No se generó el archivo SRT."
            return

        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["message"] = "SRT generado correctamente."
        JOBS[job_id]["download_url"] = f"/download/{job_id}/{JOBS[job_id]['original_stem']}"

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["message"] = str(e)
        JOBS[job_id]["traceback"] = traceback.format_exc()
        print(JOBS[job_id]["traceback"])


def run_translate_job(
    job_id,
    input_srt_path,
    output_dir,
    source_language,
    target_language,
):
    try:
        JOBS[job_id]["status"] = "processing"
        JOBS[job_id]["message"] = "Traduciendo subtítulos..."

        translated_path = translate_srt_file(
            input_path=input_srt_path,
            source_lang=source_language,
            target_lang=target_language,
            output_dir=output_dir,
            chunk_size=20,
        )

        if not translated_path.exists():
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["message"] = "No se generó el archivo traducido."
            return

        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["message"] = "SRT traducido correctamente."
        JOBS[job_id]["download_url"] = (
            f"/download-translated/{job_id}/{translated_path.name}"
        )

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["message"] = str(e)
        JOBS[job_id]["traceback"] = traceback.format_exc()
        print(JOBS[job_id]["traceback"])


def processing_page(job_id: str, title: str, initial_message: str) -> HTMLResponse:
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="UTF-8">
      <title>{title}</title>
      <style>
        body {{
          font-family: Arial;
          background:#0f172a;
          color:#e2e8f0;
          display:flex;
          justify-content:center;
          align-items:center;
          min-height:100vh;
          margin:0;
        }}
        .card {{
          background:#1e293b;
          padding:32px;
          border-radius:14px;
          text-align:center;
          width:520px;
        }}
        .bar {{
          width:100%;
          height:14px;
          background:#334155;
          border-radius:8px;
          overflow:hidden;
          margin-top:20px;
        }}
        .fill {{
          width:20%;
          height:100%;
          background:#3b82f6;
          animation:pulse 1.2s infinite alternate;
        }}
        @keyframes pulse {{
          from {{ width:20%; }}
          to {{ width:90%; }}
        }}
        a {{
          color:#93c5fd;
        }}
      </style>
    </head>
    <body>
      <div class="card">
        <h2>{title}</h2>
        <p id="message">{initial_message}</p>
        <div class="bar"><div class="fill"></div></div>
        <p style="font-size:13px;color:#94a3b8;">Puedes dejar esta ventana abierta.</p>
        <div id="result"></div>
      </div>

      <script>
        async function checkStatus() {{
          const response = await fetch("/status/{job_id}");
          const data = await response.json();

          document.getElementById("message").innerText = data.message || data.status;

          if (data.status === "done") {{
            document.getElementById("result").innerHTML =
              `<br><a href="${{data.download_url}}" style="display:inline-block;padding:14px 24px;background:#3b82f6;color:white;text-decoration:none;border-radius:8px;font-weight:bold;">Descargar SRT</a><br><br><a href="/">Volver al inicio</a>`;
            return;
          }}

          if (data.status === "error") {{
            document.getElementById("result").innerHTML =
              `<br><p style="color:#fca5a5;">Error: ${{data.message}}</p><br><a href="/">Volver al inicio</a>`;
            return;
          }}

          setTimeout(checkStatus, 3000);
        }}

        checkStatus();
      </script>
    </body>
    </html>
    """)


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
    output_dir.mkdir(parents=True, exist_ok=True)

    with video_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    JOBS[job_id] = {
        "status": "queued",
        "message": "Trabajo recibido.",
        "original_stem": original_stem,
        "download_url": None,
    }

    thread = threading.Thread(
        target=run_generate_job,
        args=(job_id, video_path, output_dir, language, audio_profile),
        daemon=True,
    )
    thread.start()

    return processing_page(
        job_id=job_id,
        title="🎬 Procesando video",
        initial_message="Tu archivo fue recibido. Generando SRT...",
    )


@app.post("/translate-srt", response_class=HTMLResponse)
async def translate_srt(
    srt_file: UploadFile = File(...),
    source_language: str = Form("es"),
    target_language: str = Form("en"),
    instructions: str = Form(""),
):
    job_id = str(uuid.uuid4())

    original_stem = Path(srt_file.filename or "subtitles").stem
    input_srt_path = UPLOAD_DIR / f"{job_id}_{original_stem}.srt"
    output_dir = OUTPUT_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    with input_srt_path.open("wb") as buffer:
        shutil.copyfileobj(srt_file.file, buffer)

    JOBS[job_id] = {
        "status": "queued",
        "message": "Trabajo recibido.",
        "original_stem": original_stem,
        "download_url": None,
    }

    thread = threading.Thread(
        target=run_translate_job,
        args=(
            job_id,
            input_srt_path,
            output_dir,
            source_language,
            target_language,
        ),
        daemon=True,
    )
    thread.start()

    return processing_page(
        job_id=job_id,
        title="🌍 Traduciendo SRT",
        initial_message="Tu archivo fue recibido. Traduciendo subtítulos...",
    )


@app.get("/status/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)

    if not job:
        return JSONResponse(
            {"status": "not_found", "message": "No encontré ese trabajo."},
            status_code=404,
        )

    return job


@app.get("/download/{job_id}/{original_stem}")
def download(job_id: str, original_stem: str):
    srt_path = OUTPUT_DIR / job_id / "output.srt"

    if not srt_path.exists():
        return HTMLResponse("<h2>Error: no encontré el archivo SRT.</h2>", status_code=404)

    return FileResponse(
        path=srt_path,
        media_type="application/x-subrip",
        filename=f"{original_stem}.srt",
    )


@app.get("/download-translated/{job_id}/{filename}")
def download_translated(job_id: str, filename: str):
    srt_path = OUTPUT_DIR / job_id / filename

    if not srt_path.exists():
        return HTMLResponse("<h2>Error: no encontré el archivo traducido.</h2>", status_code=404)

    return FileResponse(
        path=srt_path,
        media_type="application/x-subrip",
        filename=filename,
    )
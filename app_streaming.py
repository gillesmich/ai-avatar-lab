# WAV2LIP Backend Flask - version HLS streaming progressif
# Stratégie : TTS audio découpé en chunks 5s → Wav2Lip par chunk → segments HLS .ts
# Le client commence à lire dès le 1er segment, sans attendre la fin.

import os
import uuid
import base64
import threading
import subprocess
import traceback
import time
import math
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response, stream_with_context, send_file, send_from_directory
from openai import OpenAI

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "")
WAV2LIP_DIR      = Path(os.environ.get("WAV2LIP_DIR",     str(BASE_DIR / "Wav2Lip")))
CHECKPOINT       = WAV2LIP_DIR / os.environ.get("CHECKPOINT", "wav2lip_onnx_models/wav2lip_gan.onnx")
HOST             = os.environ.get("HOST",           "0.0.0.0")
PORT             = int(os.environ.get("PORT",       "5001"))
FLASK_ENV        = os.environ.get("FLASK_ENV",      "production")
GPT_MODEL        = os.environ.get("GPT_MODEL",      "gpt-4o")
TTS_MODEL        = os.environ.get("TTS_MODEL",      "tts-1")
WHISPER_LANG     = os.environ.get("WHISPER_LANG",   "fr")
INFERENCE_SCRIPT = os.environ.get("INFERENCE_SCRIPT","inference_streaming.py")
CHUNK_DURATION   = int(os.environ.get("CHUNK_DURATION", "5"))   # secondes par segment HLS

UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
STREAM_DIR = BASE_DIR / "streams"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
STREAM_DIR.mkdir(exist_ok=True)

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY manquant dans .env")

app = Flask(__name__)
oai = OpenAI(api_key=OPENAI_API_KEY)

tasks = {}


# ──────────────────────────────────────────────────────────────────────────────
# ROUTES STATIQUES
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file(str(BASE_DIR / "index.html"))

@app.route("/health.ico")
@app.route("/favicon.ico")
def health():
    return "", 204


# ──────────────────────────────────────────────────────────────────────────────
# AVATAR UPLOAD
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/avatar", methods=["POST"])
def upload_avatar():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "no file"}), 400
    avatar_id = str(uuid.uuid4())
    ext  = Path(file.filename).suffix.lower() or ".jpg"
    dest = UPLOAD_DIR / ("avatar_" + avatar_id + ext)
    file.save(dest)
    print("[avatar] saved: " + str(dest), flush=True)
    return jsonify({"avatar_id": avatar_id})


# ──────────────────────────────────────────────────────────────────────────────
# LANCEMENT PIPELINE
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/process/start", methods=["POST"])
def process_start():
    body       = request.get_json(force=True)
    avatar_id  = body.get("avatar_id", "").strip()
    audio_b64  = body.get("audio",     "").strip()
    sys_prompt = body.get("system_prompt", "Tu es un assistant sympathique.")
    voice_id   = body.get("voice_id",  "alloy")

    if not avatar_id or not audio_b64:
        return jsonify({"error": "avatar_id + audio requis"}), 400

    paths = list(UPLOAD_DIR.glob("avatar_" + avatar_id + ".*"))
    if not paths:
        return jsonify({"error": "avatar introuvable"}), 404

    task_id    = str(uuid.uuid4())
    stream_dir = STREAM_DIR / task_id
    stream_dir.mkdir(exist_ok=True)

    tasks[task_id] = {
        "status"      : "pending",
        "progress"    : 0,
        "message"     : "En file d'attente...",
        "video_url"   : None,
        # URL HLS : disponible dès le 1er segment
        "hls_url"     : f"/api/hls/{task_id}/playlist.m3u8",
        "segments_ready": 0,        # nb segments déjà disponibles
        "segments_total": 0,        # nb segments total (connu après split audio)
        "transcript"  : None,
        "response"    : None,
        "error"       : None,
        "_output_path": None,
        "_stream_dir" : str(stream_dir),
        "_logs"       : [],
    }

    print("[start] task=" + task_id, flush=True)

    t = threading.Thread(
        target=run_pipeline,
        args=(task_id, paths[0], audio_b64, sys_prompt, voice_id, stream_dir),
        daemon=True
    )
    t.start()

    return jsonify({"task_id": task_id})


# ──────────────────────────────────────────────────────────────────────────────
# STATUS
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/process/status/<task_id>")
def process_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "task inconnue"}), 404
    return jsonify({k: v for k, v in task.items() if not k.startswith("_")})


@app.route("/api/debug/<task_id>")
def debug_task(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "task inconnue"}), 404
    return jsonify(task)


# ──────────────────────────────────────────────────────────────────────────────
# HLS ENDPOINTS  (streaming progressif pendant génération)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/hls/<task_id>/playlist.m3u8")
def hls_playlist(task_id):
    """Playlist HLS dynamique - met à jour en live pendant la génération."""
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "task inconnue"}), 404

    stream_dir = Path(task["_stream_dir"])
    segments   = sorted(stream_dir.glob("segment_*.ts"))
    is_done    = task["status"] in ("completed", "failed")

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{CHUNK_DURATION + 1}",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]

    for seg in segments:
        # Récupère la vraie durée depuis le fichier .dur si présent, sinon CHUNK_DURATION
        dur_file = stream_dir / (seg.stem + ".dur")
        duration = dur_file.read_text().strip() if dur_file.exists() else str(float(CHUNK_DURATION))
        lines.append(f"#EXTINF:{duration},")
        lines.append(f"/api/hls/{task_id}/{seg.name}")

    if is_done:
        lines.append("#EXT-X-ENDLIST")

    playlist = "\n".join(lines) + "\n"

    response = Response(playlist, mimetype="application/vnd.apple.mpegurl")
    # Pas de cache pour que le player recharge la playlist
    response.headers["Cache-Control"] = "no-cache, no-store"
    return response


@app.route("/api/hls/<task_id>/<path:filename>")
def hls_segment(task_id, filename):
    """Sert un segment .ts HLS."""
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "task inconnue"}), 404

    if ".." in filename or not filename.endswith(".ts"):
        return jsonify({"error": "fichier invalide"}), 400

    stream_dir = Path(task["_stream_dir"])
    seg_path   = stream_dir / filename

    if not seg_path.exists():
        return jsonify({"error": "segment introuvable"}), 404

    return send_file(str(seg_path), mimetype="video/mp2t")


# ──────────────────────────────────────────────────────────────────────────────
# VIDEO FINALE (MP4 complet, disponible après completion)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/stream/<task_id>")
def stream_video(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "task inconnue"}), 404
    if task["status"] != "completed" or not task.get("_output_path"):
        return jsonify({"error": "pas encore pret"}), 202

    video_path = Path(task["_output_path"])
    if not video_path.exists():
        return jsonify({"error": "fichier introuvable"}), 404

    file_size    = video_path.stat().st_size
    range_header = request.headers.get("Range")
    chunk_size   = 65536

    if range_header:
        byte_start, byte_end = _parse_range(range_header, file_size)
        length = byte_end - byte_start + 1

        def gen_partial():
            with open(video_path, "rb") as f:
                f.seek(byte_start)
                rem = length
                while rem > 0:
                    data = f.read(min(chunk_size, rem))
                    if not data:
                        break
                    rem -= len(data)
                    yield data

        return Response(
            stream_with_context(gen_partial()), status=206,
            headers={
                "Content-Range" : f"bytes {byte_start}-{byte_end}/{file_size}",
                "Accept-Ranges" : "bytes",
                "Content-Length": str(length),
                "Content-Type"  : "video/mp4",
            }
        )

    def gen_full():
        with open(video_path, "rb") as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                yield data

    return Response(
        stream_with_context(gen_full()), status=200,
        headers={
            "Content-Length": str(file_size),
            "Content-Type"  : "video/mp4",
            "Accept-Ranges" : "bytes",
        }
    )


# ──────────────────────────────────────────────────────────────────────────────
# TEST / DEBUG
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/test")
def test_pipeline():
    r = {}
    try:
        ret = subprocess.run(["ffmpeg", "-version"], capture_output=True)
        r["ffmpeg"] = "OK" if ret.returncode == 0 else "KO"
    except Exception as e:
        r["ffmpeg"] = "KO: " + str(e)
    r["wav2lip_dir"]  = str(WAV2LIP_DIR)  + (" OK" if WAV2LIP_DIR.exists() else " INTROUVABLE")
    r["checkpoint"]   = str(CHECKPOINT)   + (" OK" if CHECKPOINT.exists()  else " INTROUVABLE")
    r["inference_py"] = str(WAV2LIP_DIR / INFERENCE_SCRIPT) + \
                        (" OK" if (WAV2LIP_DIR / INFERENCE_SCRIPT).exists() else " INTROUVABLE")
    r["openai_key"]   = "OK (len=" + str(len(OPENAI_API_KEY)) + ")" if OPENAI_API_KEY else "MANQUANTE"
    r["chunk_dur_s"]  = CHUNK_DURATION
    try:
        models = oai.models.list()
        r["openai_api"] = "OK (" + str(len(list(models))) + " models)"
    except Exception as e:
        r["openai_api"] = "KO: " + str(e)[:100]
    r["uploads_dir"] = str(UPLOAD_DIR) + (" OK" if UPLOAD_DIR.exists() else " KO")
    r["outputs_dir"] = str(OUTPUT_DIR) + (" OK" if OUTPUT_DIR.exists() else " KO")
    r["streams_dir"] = str(STREAM_DIR) + (" OK" if STREAM_DIR.exists() else " KO")
    return jsonify(r)


@app.route("/api/inference-args")
def inference_args():
    try:
        ret = subprocess.run(
            ["python", INFERENCE_SCRIPT, "--help"],
            cwd=str(WAV2LIP_DIR),
            capture_output=True, text=True, timeout=15
        )
        return jsonify({
            "returncode": ret.returncode,
            "help": ret.stdout + ret.stderr,
            "cmd": "python " + INFERENCE_SCRIPT + " --help (cwd=" + str(WAV2LIP_DIR) + ")"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────────────────────────────────────
# PIPELINE WORKER
# ──────────────────────────────────────────────────────────────────────────────

def plog(task_id, msg):
    print("[" + task_id[:8] + "] " + msg, flush=True)
    if task_id in tasks:
        tasks[task_id].setdefault("_logs", []).append(msg)


def _set(task, progress, message):
    task["progress"] = progress
    task["message"]  = message


def run_pipeline(task_id, avatar_path, audio_b64, sys_prompt, voice_id, stream_dir):
    task = tasks[task_id]
    task["status"] = "running"

    audio_webm = UPLOAD_DIR / ("input_" + task_id + ".webm")
    audio_wav  = UPLOAD_DIR / ("input_" + task_id + ".wav")
    tts_mp3    = UPLOAD_DIR / ("tts_"   + task_id + ".mp3")
    tts_wav    = UPLOAD_DIR / ("tts_"   + task_id + ".wav")
    output_mp4 = OUTPUT_DIR / ("result_" + task_id + ".mp4")

    try:
        # ── ÉTAPE 1 : décode audio entrée ──────────────────────────────────
        _set(task, 5, "Décodage audio...")
        plog(task_id, "STEP 1 - decode base64")
        audio_webm.write_bytes(base64.b64decode(audio_b64))

        # ── ÉTAPE 2 : conversion webm → wav ───────────────────────────────
        _set(task, 10, "Conversion audio...")
        plog(task_id, "STEP 2 - ffmpeg webm->wav")
        _ffmpeg(audio_webm, audio_wav)

        # ── ÉTAPE 3 : Whisper ─────────────────────────────────────────────
        _set(task, 20, "Transcription Whisper...")
        plog(task_id, "STEP 3 - Whisper")
        transcript = _whisper(audio_wav)
        task["transcript"] = transcript
        plog(task_id, "  transcript: " + transcript[:80])

        # ── ÉTAPE 4 : GPT ─────────────────────────────────────────────────
        _set(task, 35, "Génération réponse IA...")
        plog(task_id, "STEP 4 - GPT")
        ai_resp = _chat(sys_prompt, transcript)
        task["response"] = ai_resp
        plog(task_id, "  réponse: " + ai_resp[:80])

        # ── ÉTAPE 5 : TTS ─────────────────────────────────────────────────
        _set(task, 50, "Synthèse vocale...")
        plog(task_id, "STEP 5 - TTS " + voice_id)
        _tts(ai_resp, voice_id, tts_mp3)

        # ── ÉTAPE 6 : mp3 → wav ───────────────────────────────────────────
        _set(task, 60, "Préparation Wav2Lip...")
        plog(task_id, "STEP 6 - ffmpeg mp3->wav")
        _ffmpeg(tts_mp3, tts_wav)

        # ── ÉTAPE 7 : split audio en chunks ───────────────────────────────
        _set(task, 62, f"Découpage audio en segments de {CHUNK_DURATION}s...")
        plog(task_id, "STEP 7 - split audio")
        chunks = _split_audio(tts_wav, stream_dir)
        task["segments_total"] = len(chunks)
        plog(task_id, f"  {len(chunks)} segments créés")

        # ── ÉTAPE 8 : Wav2Lip par chunk → segments HLS ────────────────────
        _set(task, 65, f"Génération vidéo HLS (0/{len(chunks)})...")
        plog(task_id, "STEP 8 - Wav2Lip par chunk")

        ts_segments = []
        for i, chunk_wav in enumerate(chunks):
            chunk_mp4 = stream_dir / f"chunk_{i:03d}.mp4"
            chunk_ts  = stream_dir / f"segment_{i:03d}.ts"

            plog(task_id, f"  chunk {i+1}/{len(chunks)}: wav2lip...")
            _wav2lip_chunk(avatar_path, chunk_wav, chunk_mp4, task_id)

            plog(task_id, f"  chunk {i+1}/{len(chunks)}: mp4->ts...")
            dur = _mp4_to_ts(chunk_mp4, chunk_ts)

            # Sauvegarde la durée réelle pour la playlist
            (stream_dir / f"segment_{i:03d}.dur").write_text(f"{dur:.3f}")

            ts_segments.append(chunk_ts)
            task["segments_ready"] = i + 1

            progress = 65 + int(30 * (i + 1) / len(chunks))
            _set(task, progress, f"HLS streaming {i+1}/{len(chunks)} segments prêts...")
            plog(task_id, f"  segment {i+1} disponible pour lecture")

        # ── ÉTAPE 9 : concaténation en MP4 final ──────────────────────────
        _set(task, 96, "Concaténation MP4 finale...")
        plog(task_id, "STEP 9 - concat final MP4")
        _concat_segments(ts_segments, output_mp4)

        task["_output_path"] = str(output_mp4)
        task["video_url"]    = "/api/stream/" + task_id
        task["progress"]     = 100
        task["message"]      = "Vidéo prête !"
        task["status"]       = "completed"
        plog(task_id, "COMPLETED")

    except Exception as e:
        task["status"]  = "failed"
        task["message"] = "Erreur pipeline"
        task["error"]   = str(e)
        plog(task_id, "ERREUR: " + str(e))
        print(traceback.format_exc(), flush=True)

    finally:
        for f in [audio_webm, audio_wav, tts_mp3, tts_wav]:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _ffmpeg(src, dst):
    ret = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), str(dst)],
        capture_output=True
    )
    if ret.returncode != 0:
        raise RuntimeError("ffmpeg: " + ret.stderr.decode()[:400])


def _whisper(wav_path):
    with open(wav_path, "rb") as f:
        resp = oai.audio.transcriptions.create(
            model="whisper-1", file=f, language=WHISPER_LANG
        )
    return resp.text


def _chat(sys_prompt, user_text):
    resp = oai.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user",   "content": user_text},
        ],
        max_tokens=300,
    )
    return resp.choices[0].message.content.strip()


def _tts(text, voice, dest):
    resp = oai.audio.speech.create(model=TTS_MODEL, voice=voice, input=text)
    dest.write_bytes(resp.content)


def _split_audio(wav_path, out_dir, chunk_dur=None):
    """Découpe un WAV en segments de chunk_dur secondes.
    Retourne la liste ordonnée des fichiers wav créés."""
    if chunk_dur is None:
        chunk_dur = CHUNK_DURATION

    # Durée totale
    ret = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(wav_path)],
        capture_output=True, text=True
    )
    total = float(ret.stdout.strip() or "0")
    if total == 0:
        raise RuntimeError("Impossible de lire la durée du fichier TTS")

    n_chunks = max(1, math.ceil(total / chunk_dur))

    chunks = []
    for i in range(n_chunks):
        start  = i * chunk_dur
        out    = out_dir / f"audio_{i:03d}.wav"
        cmd    = [
            "ffmpeg", "-y",
            "-i", str(wav_path),
            "-ss", str(start),
            "-t",  str(chunk_dur),
            "-acodec", "pcm_s16le",
            str(out)
        ]
        ret = subprocess.run(cmd, capture_output=True)
        if ret.returncode != 0:
            raise RuntimeError("split audio: " + ret.stderr.decode()[:300])
        if out.exists() and out.stat().st_size > 1000:
            chunks.append(out)

    return chunks


def _wav2lip_chunk(face, audio, output, task_id):
    """Appelle Wav2Lip sur un chunk audio. Même qualité que la version backup."""
    cmd = [
        "python", INFERENCE_SCRIPT,
        "--checkpoint_path", str(CHECKPOINT),
        "--face",            str(face),
        "--audio",           str(audio),
        "--outfile",         str(output),
        "--resize_factor",   "1",
        "--hq_output",
        "--enhancer",        "gfpgan",
        "--blending",        "8",
        "--sharpen",
    ]
    ret = subprocess.run(
        cmd,
        cwd=str(WAV2LIP_DIR),
        capture_output=True,
        text=True
    )
    for line in (ret.stdout + ret.stderr).splitlines():
        if line.strip():
            plog(task_id, "[w2l] " + line)

    if ret.returncode != 0:
        raise RuntimeError("Wav2Lip chunk: " + ret.stderr[-600:])
    if not output.exists():
        raise RuntimeError("Wav2Lip chunk: fichier de sortie introuvable")


def _mp4_to_ts(mp4_path, ts_path):
    """Convertit un MP4 en segment MPEG-TS pour HLS.
    Retourne la durée réelle du segment en secondes."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(mp4_path),
        "-c",   "copy",          # pas de ré-encodage → qualité maximale
        "-bsf:v", "h264_mp4toannexb",
        "-f",   "mpegts",
        str(ts_path)
    ]
    ret = subprocess.run(cmd, capture_output=True)
    if ret.returncode != 0:
        raise RuntimeError("mp4->ts: " + ret.stderr.decode()[:300])

    # Durée réelle
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(ts_path)],
        capture_output=True, text=True
    )
    try:
        return float(probe.stdout.strip())
    except ValueError:
        return float(CHUNK_DURATION)


def _concat_segments(ts_list, output_mp4):
    """Concatène les segments .ts en un MP4 final propre via ffmpeg concat."""
    if not ts_list:
        raise RuntimeError("Aucun segment à concaténer")

    # Fichier liste concat
    concat_txt = ts_list[0].parent / "concat_list.txt"
    lines = [f"file '{str(ts)}'\n" for ts in ts_list]
    concat_txt.write_text("".join(lines))

    cmd = [
        "ffmpeg", "-y",
        "-f",     "concat",
        "-safe",  "0",
        "-i",     str(concat_txt),
        "-c",     "copy",
        str(output_mp4)
    ]
    ret = subprocess.run(cmd, capture_output=True)
    if ret.returncode != 0:
        raise RuntimeError("concat: " + ret.stderr.decode()[:300])
    if not output_mp4.exists():
        raise RuntimeError("MP4 final introuvable après concat")


def _parse_range(range_header, file_size):
    try:
        parts = range_header.replace("bytes=", "").split("-")
        start = int(parts[0]) if parts[0] else 0
        end   = int(parts[1]) if parts[1] else file_size - 1
    except Exception:
        start, end = 0, file_size - 1
    return start, min(end, file_size - 1)


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    debug = FLASK_ENV == "development"
    print(f"WAV2LIP HLS STREAMING -> http://{HOST}:{PORT} [{'dev' if debug else 'prod'}]", flush=True)
    print(f"  Chunk duration : {CHUNK_DURATION}s par segment HLS", flush=True)
    app.run(host=HOST, port=PORT, debug=debug, threaded=True)

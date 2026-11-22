import os, json, re, subprocess, requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import yt_dlp
import google.generativeai as genai

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
os.makedirs("clips", exist_ok=True)
app.mount("/clips", StaticFiles(directory="clips"), name="clips")

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
PROXY_URL = os.environ.get("PROXY_URL", "").strip()

class VideoRequest(BaseModel):
    youtube_url: str

class PublishRequest(BaseModel):
    video_url: str = ""
    clip_url: str = ""
    title: str
    description: str = ""
    hashtags: list[str] = []
    oauth_token: str

def get_ydl_opts():
    c = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if c:
        with open("cookies.txt", "w", encoding="utf-8") as f:
            f.write(c)
    opts = {"quiet": True, "no_warnings": True, "nocheckcertificate": True, "extractor_args": {"youtube": {"player_client": ["tv", "web"]}}}
    if os.path.exists("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"
    if PROXY_URL:
        opts["proxy"] = PROXY_URL
    return opts

@app.get("/")
def home():
    return {"status": "ClipEraser Engine Live", "proxy_active": bool(PROXY_URL), "cookies_active": bool(os.environ.get("YOUTUBE_COOKIES", "").strip())}

@app.post("/api/clip")
async def create_clips(req: VideoRequest):
    try:
        for f in os.listdir("."):
            if f.startswith("sub.") and f.endswith(".json3"):
                os.remove(f)

        sub_opts = get_ydl_opts()
        sub_opts.update({"skip_download": True, "writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["en", "hi", "en-US"], "subtitlesformat": "json3", "outtmpl": "sub"})
        with yt_dlp.YoutubeDL(sub_opts) as ydl:
            ydl.download([req.youtube_url])

        sub_files = [f for f in os.listdir(".") if f.startswith("sub.") and f.endswith(".json3")]
        if not sub_files:
            raise HTTPException(status_code=400, detail="Is video me subtitles nahi mile.")

        with open(sub_files, "r", encoding="utf-8") as f:
            data = json.load(f)

        segs = []
        for ev in data.get("events", []):
            if "segs" in ev and "tStartMs" in ev:
                txt = "".join([s.get("utf8", "") for s in ev["segs"]]).strip().replace("\n", " ")
                if txt:
                    segs.append({"start": ev["tStartMs"] / 1000.0, "dur": ev.get("dDurationMs", 2000) / 1000.0, "text": txt})

        transcript = "\n".join([f"[{s['start']:.1f}s]: {s['text']}" for s in segs])
        prompt = f"Pick top 5 viral 30-55s clips from this transcript. Return ONLY valid JSON array: [{{\"title\": \"Hook Title\", \"start\": 15.0, \"end\": 55.0, \"virality_score\": 96}}]\nTranscript:\n{transcript[:100000]}"

        raw = ""
        for m in ["gemini-2.5-flash", "gemini-1.5-flash"]:
            try:
                raw = genai.GenerativeModel(m).generate_content(prompt).text
                break
            except Exception:
                continue

        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise HTTPException(status_code=500, detail="AI response error, dubara try karein.")
        clips = json.loads(match.group(0))

        results = []
        for idx, c in enumerate(clips):
            st, et = float(c["start"]), float(c["end"])
            dur = max(10.0, et - st)
            out_file = f"clips/clip_{idx+1}.mp4"
            if os.path.exists(out_file):
                os.remove(out_file)

            dl_opts = get_ydl_opts()
            dl_opts.update({"merge_output_format": "mp4", "outtmpl": f"clips/raw_{idx+1}.%(ext)s", "download_ranges": yt_dlp.utils.download_range_func(None, [(st, et)]), "force_keyframes_at_cuts": True})
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                ydl.download([req.youtube_url])

            dl_files = [f"clips/{f}" for f in os.listdir("clips") if f.startswith(f"raw_{idx+1}")]
            if not dl_files:
                continue
            raw_in = dl_files

            subprocess.run(["ffmpeg", "-y", "-i", raw_in, "-vf", "crop=ih*(9/16):ih,scale=720:1280", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(raw_in):
                os.remove(raw_in)

            if os.path.exists(out_file):
                results.append({"id": idx + 1, "title": c["title"], "virality_score": c.get("virality_score", 95), "duration": f"{int(dur)}s", "video_url": f"/clips/clip_{idx+1}.mp4"})

        if not results:
            raise HTTPException(status_code=500, detail="Clips render nahi ho payin.")
        return {"status": "success", "clips": results}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/publish/youtube")
async def publish_youtube(req: PublishRequest):
    return {"status": "error", "detail": "YouTube OAuth token required"}

@app.post("/api/publish/instagram")
async def publish_instagram(req: PublishRequest):
    return {"status": "error", "detail": "Instagram Business token required"}
# END OF CODE

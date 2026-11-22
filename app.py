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

class VideoRequest(BaseModel):
    youtube_url: str

class PublishRequest(BaseModel):
    video_url: str = ""
    clip_url: str = ""
    title: str
    description: str = ""
    hashtags: list[str] = []
    oauth_token: str

@app.get("/")
def home():
    return {"status": "ClipEraser Engine Live", "mode": "Android-VR-Bypass"}

@app.post("/api/clip")
async def create_clips(req: VideoRequest):
    try:
        # 1. Android VR & iOS Client ban kar direct YouTube se Audio + Video lena (No Bot Block, No Cookies Needed!)
        if os.path.exists("temp_audio.m4a"):
            os.remove("temp_audio.m4a")

        audio_opts = {
            "format": "bestaudio/best",
            "outtmpl": "temp_audio.m4a",
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android_vr", "ios", "tv_embedded"]
                }
            }
        }
        with yt_dlp.YoutubeDL(audio_opts) as ydl:
            ydl.download([req.youtube_url])

        if not os.path.exists("temp_audio.m4a"):
            raise HTTPException(status_code=500, detail="Audio download fail hua.")

        # 2. Audio ko chhota (2MB MP3) karke Gemini AI ko sunwana
        if os.path.exists("small.mp3"):
            os.remove("small.mp3")
        subprocess.run(["ffmpeg", "-y", "-i", "temp_audio.m4a", "-t", "3600", "-ar", "16000", "-ac", "1", "-b:a", "24k", "small.mp3"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove("temp_audio.m4a")

        uploaded = genai.upload_file("small.mp3")
        prompt = "Listen to this audio and pick the top 5 most viral, engaging 30-to-55 second moments for YouTube Shorts/Reels. Return ONLY a valid JSON array: [{\"title\": \"Catchy Viral Title\", \"start\": 15.0, \"end\": 55.0, \"virality_score\": 96}]"

        raw = ""
        for m in ["gemini-2.5-flash", "gemini-1.5-flash"]:
            try:
                raw = genai.GenerativeModel(m).generate_content([uploaded, prompt]).text
                break
            except Exception:
                continue

        if os.path.exists("small.mp3"):
            os.remove("small.mp3")

        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise HTTPException(status_code=500, detail="AI viral clips nahi chun paya, dubara try karein.")
        clips = json.loads(match.group(0))

        # 3. Sirf chune hue 40-40 sec ke tukde Android_VR client se download karke 9:16 banana
        results = []
        for idx, c in enumerate(clips):
            st, et = float(c["start"]), float(c["end"])
            dur = max(10.0, et - st)
            out_file = f"clips/clip_{idx+1}.mp4"
            if os.path.exists(out_file):
                os.remove(out_file)

            vid_opts = {
                "format": "best[height<=720]/best",
                "outtmpl": f"clips/raw_{idx+1}.%(ext)s",
                "download_ranges": yt_dlp.utils.download_range_func(None, [(st, et)]),
                "force_keyframes_at_cuts": True,
                "quiet": True,
                "no_warnings": True,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["android_vr", "ios", "tv_embedded"]
                    }
                }
            }
            with yt_dlp.YoutubeDL(vid_opts) as ydl:
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
    return {"status": "error", "detail": "Valid YouTube OAuth Token required"}

@app.post("/api/publish/instagram")
async def publish_instagram(req: PublishRequest):
    return {"status": "error", "detail": "Valid Instagram Graph Token required"}
# END OF CODE

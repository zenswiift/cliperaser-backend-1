import os, json, re, subprocess, requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import google.generativeai as genai

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
os.makedirs("clips", exist_ok=True)
app.mount("/clips", StaticFiles(directory="clips"), name="clips")

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

class VideoRequest(BaseModel):
    youtube_url: str

@app.get("/")
def home():
    return {"status": "ClipEraser Engine Live", "mode": "Gemini-Audio-Direct"}

def get_cobalt_stream(youtube_url: str, audio_only: bool = False):
    instances = ["https://cobalt.tools", "https://kwiatekmiki.com", "https://timelessnesses.me"]
    payload = {"url": youtube_url, "videoQuality": "720"}
    if audio_only:
        payload["downloadMode"] = "audio"
        payload["audioFormat"] = "mp3"
    for api_url in instances:
        try:
            r = requests.post(api_url, headers={"Accept": "application/json", "Content-Type": "application/json"}, json=payload, timeout=20)
            if r.status_code == 200 and r.json().get("url"):
                return r.json().get("url")
        except Exception:
            continue
    return None

@app.post("/api/clip")
async def create_clips(req: VideoRequest):
    try:
        # 1. Cobalt se Audio aur Video stream lena (No YouTube Block!)
        audio_url = get_cobalt_stream(req.youtube_url, audio_only=True)
        video_url = get_cobalt_stream(req.youtube_url, audio_only=False)
        if not video_url:
            raise HTTPException(status_code=500, detail="Video stream fetch nahi ho paya, dubara try karein.")

        # 2. Low-size Audio download (sirf 2-3MB) taaki Gemini khud sun kar viral clips chune
        if os.path.exists("temp_audio.mp3"):
            os.remove("temp_audio.mp3")
        subprocess.run(["ffmpeg", "-y", "-i", audio_url or video_url, "-t", "1800", "-ar", "16000", "-ac", "1", "-b:a", "24k", "temp_audio.mp3"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if not os.path.exists("temp_audio.mp3"):
            raise HTTPException(status_code=500, detail="Audio extract nahi ho paya.")

        # 3. Gemini AI se direct Audio sunwa kar Top 5 Viral Moments nikalna
        uploaded_audio = genai.upload_file("temp_audio.mp3")
        prompt = "Listen to this audio carefully and pick the top 5 most viral, high-retention 30-to-55 second moments for YouTube Shorts/Reels. Return ONLY a valid JSON array with exact start and end seconds: [{\"title\": \"Catchy Viral Title\", \"start\": 15.0, \"end\": 55.0, \"virality_score\": 96}]"

        raw = ""
        for m in ["gemini-2.5-flash", "gemini-1.5-flash"]:
            try:
                raw = genai.GenerativeModel(m).generate_content([uploaded_audio, prompt]).text
                break
            except Exception:
                continue

        if os.path.exists("temp_audio.mp3"):
            os.remove("temp_audio.mp3")

        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise HTTPException(status_code=500, detail="AI viral clips nahi chun paya, dubara try karein.")
        clips = json.loads(match.group(0))

        # 4. FFmpeg se direct video stream se 9:16 clips kaatna
        results = []
        for idx, c in enumerate(clips):
            st, et = float(c["start"]), float(c["end"])
            dur = max(10.0, et - st)
            out_file = f"clips/clip_{idx+1}.mp4"
            if os.path.exists(out_file):
                os.remove(out_file)

            subprocess.run(["ffmpeg", "-y", "-ss", str(st), "-i", video_url, "-t", str(dur), "-vf", "crop=ih*(9/16):ih,scale=720:1280", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if os.path.exists(out_file):
                results.append({"id": idx + 1, "title": c["title"], "virality_score": c.get("virality_score", 95), "duration": f"{int(dur)}s", "video_url": f"/clips/clip_{idx+1}.mp4"})

        if not results:
            raise HTTPException(status_code=500, detail="Clips render nahi ho payin.")
        return {"status": "success", "clips": results}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# END OF CODE

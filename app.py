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

def get_vid_id(url: str):
    m = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
    return m.group(1) if m else None

@app.get("/")
def home():
    return {"status": "ClipEraser Engine Live", "mode": "Cobalt-Unblockable"}

@app.post("/api/clip")
async def create_clips(req: VideoRequest):
    try:
        vid = get_vid_id(req.youtube_url)
        if not vid:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")

        # 1. Free Transcript via Tactiq/Public API (No YouTube IP Block)
        t_res = requests.post("https://tactiq.io", json={"videoUrl": req.youtube_url, "langCode": "en"}, timeout=20)
        if t_res.status_code != 200 or not t_res.json().get("captions"):
            t_res = requests.post("https://tactiq.io", json={"videoUrl": req.youtube_url, "langCode": "hi"}, timeout=20)
        
        captions = t_res.json().get("captions", []) if t_res.status_code == 200 else []
        if not captions:
            raise HTTPException(status_code=400, detail="Is video ka transcript nahi mila (kisi aur video se try karein).")

        transcript = "\n".join([f"[{float(c['start']):.1f}s]: {c['text']}" for c in captions])

        # 2. Gemini AI se Top 5 Viral Clips
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
            raise HTTPException(status_code=500, detail="AI response error.")
        clips = json.loads(match.group(0))

        # 3. Direct Stream URL via Cobalt API (Bypasses YouTube Bot Block 100%)
        c_res = requests.post("https://cobalt.tools", headers={"Accept": "application/json", "Content-Type": "application/json"}, json={"url": req.youtube_url, "videoQuality": "720"}, timeout=25).json()
        stream_url = c_res.get("url")
        if not stream_url:
            raise HTTPException(status_code=500, detail=f"Video stream fetch nahi ho paya: {c_res}")

        # 4. FFmpeg se direct stream se 9:16 clips kaatna (Bina poora video download kiye!)
        results = []
        for idx, c in enumerate(clips):
            st, et = float(c["start"]), float(c["end"])
            dur = max(10.0, et - st)
            out_file = f"clips/clip_{idx+1}.mp4"
            if os.path.exists(out_file):
                os.remove(out_file)

            subprocess.run(["ffmpeg", "-y", "-ss", str(st), "-i", stream_url, "-t", str(dur), "-vf", "crop=ih*(9/16):ih,scale=720:1280", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

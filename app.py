import os, json, re, subprocess, requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import yt_dlp
import google.generativeai as genai

app = FastAPI(title="ClipEraser Bulletproof Server")
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

def format_srt_time(seconds: float):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def get_ydl_base_opts():
    cookie_data = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if cookie_data:
        with open("cookies.txt", "w", encoding="utf-8") as f:
            f.write(cookie_data)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "extractor_args": {"youtube": {"player_client": ["tv", "web"]}}
    }
    if os.path.exists("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"
    if PROXY_URL:
        opts["proxy"] = PROXY_URL
    return opts

@app.get("/")
def home():
    return {
        "status": "ClipEraser Engine Live",
        "proxy_active": bool(PROXY_URL),
        "cookies_active": bool(os.environ.get("YOUTUBE_COOKIES", "").strip())
    }

@app.post("/api/clip")
async def create_clips(req: VideoRequest):
    try:
        for f in os.listdir("."):
            if f.startswith("sub.") and f.endswith(".json3"):
                os.remove(f)

        sub_opts = get_ydl_base_opts()
        sub_opts.update({
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en", "hi", "en-US", "en-GB"],
            "subtitlesformat": "json3",
            "outtmpl": "sub"
        })
        with yt_dlp.YoutubeDL(sub_opts) as ydl:
            ydl.download([req.youtube_url])

        sub_files = [f for f in os.listdir(".") if f.startswith("sub.") and f.endswith(".json3")]
        if not sub_files:
            raise HTTPException(status_code=400, detail="Is video me koi subtitles/captions uplabdh nahi hain.")

        with open(sub_files, "r", encoding="utf-8") as f:
            data = json.load(f)

        seg_list = []
        for ev in data.get("events", []):
            if "segs" in ev and "tStartMs" in ev:
                start_s = ev["tStartMs"] / 1000.0
                dur_s = ev.get("dDurationMs", 2000) / 1000.0
                text = "".join([s.get("utf8", "") for s in ev["segs"]]).strip().replace("\n", " ")
                if text:
                    seg_list.append({"start": start_s, "duration": dur_s, "text": text})

        if not seg_list:
            raise HTTPException(status_code=400, detail="Video transcript khali nikla.")

        transcript = "\n".join([f"[{s['start']:.1f}s]: {s['text']}" for s in seg_list])

        prompt = f"""
        You are an expert viral Shorts editor. Pick the top 5 most engaging 30-to-55 second clips from this transcript.
        Return ONLY a valid JSON array with no markdown:
        [{{"title": "Catchy Hook Title", "start": 15.0, "end": 55.0, "virality_score": 96}}]
        Transcript:
        {transcript[:100000]}
        """
        raw = ""
        for m_name in ["gemini-2.5-flash", "gemini-1.5-flash"]:
            try:
                model = genai.GenerativeModel(m_name)
                res = model.generate_content(prompt)
                raw = res.text
                break
            except Exception:
                continue

        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            raise HTTPException(status_code=500, detail="AI viral clips ka format samajh nahi paya, dubara try karein.")
        clips = json.loads(json_match.group(0))

        results = []
        for idx, c in enumerate(clips):
            start_t = float(c["start"])
            end_t = float(c["end"])
            dur = max(10.0, end_t - start_t)
            raw_part = f"clips/raw_{idx+1}.mp4"
            srt_file = f"clips/sub_{idx+1}.srt"
            out_file = f"clips/clip_{idx+1}.mp4"

            for f in [raw_part, srt_file, out_file]:
                if os.path.exists(f):
                    os.remove(f)

            # Bina strict format filter ke download (apne aap best available format uthayega)
            dl_opts = get_ydl_base_opts()
            dl_opts.update({
                "merge_output_format": "mp4",
                "outtmpl": f"clips/raw_{idx+1}.%(ext)s",
                "download_ranges": yt_dlp.utils.download_range_func(None, [(start_t, end_t)]),
                "force_keyframes_at_cuts": True
            })
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                ydl.download([req.youtube_url])

            downloaded = [f"clips/{f}" for f in os.listdir("clips") if f.startswith(f"raw_{idx+1}")]
            if not downloaded:
                continue
            actual_raw = downloaded

            has_subs = False
            with open(srt_file, "w", encoding="utf-8") as f:
                sub_idx = 1
                for s in seg_list:
                    s_end = s["start"] + s["duration"]
                    if s_end >= start_t and s["start"] <= end_t:
                        st = max(0.0, s["start"] - start_t)
                        et = min(dur, s_end - start_t)
                        if et > st:
                            f.write(f"{sub_idx}\n{format_srt_time(st)} --> {format_srt_time(et)}\n{s['text'].upper()}\n\n")
                            sub_idx += 1
                            has_subs = True

            vf_with_subs = f"crop=ih*(9/16):ih,scale=720:1280,subtitles={srt_file}:force_style='FontName=Arial,FontSize=18,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=55'"
            vf_clean = "crop=ih*(9/16):ih,scale=720:1280"

            res_ff = subprocess.run([
                "ffmpeg", "-y", "-i", actual_raw, "-vf", vf_with_subs if has_subs else vf_clean,
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out_file
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if res_ff.returncode != 0 or not os.path.exists(out_file):
                subprocess.run([
                    "ffmpeg", "-y", "-i", actual_raw, "-vf", vf_clean,
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out_file
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if os.path.exists(actual_raw):
                os.remove(actual_raw)

            if os.path.exists(out_file):
                results.append({
                    "id": idx + 1,
                    "title": c["title"],
                    "virality_score": c.get("virality_score", 95),
                    "duration": f"{int(dur)}s",
                    "video_url": f"/clips/clip_{idx+1}.mp4"
                })

        if not results:
            raise HTTPException(status_code=500, detail="Video segments render nahi ho paye.")

        return {"status": "success", "clips": results}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/publish/youtube")
async def publish_youtube(req: PublishRequest):
    try:
        filename = (req.clip_url or req.video_url).split("/")[-1]
        file_path = f"clips/{filename}"
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Clip file server par nahi mili.")
        tags_str = " ".join([f"#{t.lstrip('#')}" for t in req.hashtags])
        metadata = {
            "snippet": {
                "title": f"{req.title} #Shorts",
                "description": f"{req.description}\n\n{tags_str}".strip(),
                "categoryId": "22"
            },
            "status": {"privacyStatus": "public"}
        }
        headers = {"Authorization": f"Bearer {req.oauth_token}"}
        init_res = requests.post(
            "https://googleapis.com",
            headers={**headers, "Content-Type": "application/json"},
            json=metadata
        )
        if init_res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"YouTube Auth Error: {init_res.text}")
        upload_url = init_res.headers["Location"]
        with open(file_path, "rb") as f:
            up_res = requests.put(upload_url, headers={"Content-Type": "video/mp4"}, data=f)
        return {"status": "published", "youtube_id": up_res.json().get("id")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"YouTube Publish Error: {str(e)}")

@app.post("/api/publish/instagram")
async def publish_instagram(req: PublishRequest):
    try:
        full_video_url = req.clip_url or req.video_url
        tags_str = " ".join([f"#{t.lstrip('#')}" for t in req.hashtags])
        me_res = requests.get(f"https://facebook.com{req.oauth_token}").json()
        page_id = me_res["data"]["id"]
        ig_res = requests.get(f"https://facebook.com{page_id}?fields=instagram_business_account&access_token={req.oauth_token}").json()
        ig_user_id = ig_res["instagram_business_account"]["id"]


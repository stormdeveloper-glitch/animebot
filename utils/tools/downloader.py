import os
import yt_dlp
from aiogram import types

DOWNLOAD_PATH = "downloads"
os.makedirs(DOWNLOAD_PATH, exist_ok=True)


def download_video(url):
    ydl_opts = {
        "outtmpl": f"{DOWNLOAD_PATH}/%(title).80s.%(ext)s",
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "geo_bypass_country": "GB",
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)

        if not path.endswith(".mp4"):
            path = path.rsplit(".", 1)[0] + ".mp4"

        return path


def download_audio(url):
    ydl_opts = {
        "outtmpl": f"{DOWNLOAD_PATH}/%(title).80s.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "http_headers": {"User-Agent": "Mozilla/5.0"},
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192"
        }]
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        return path.rsplit(".", 1)[0] + ".mp3"


def safe_download(func, url, retries=3):
    for _ in range(retries):
        try:
            return func(url)
        except:
            continue
    return None


async def handle(message: types.Message):
    text = message.text.strip()

    if not text.startswith("http"):
        await message.answer("❌ Link yubor")
        return

    await message.answer("⏬ Yuklanmoqda...")

    # avval video urinamiz
    video_path = safe_download(download_video, text)

    try:
        if video_path and os.path.exists(video_path):
            size = os.path.getsize(video_path) / (1024 * 1024)

            with open(video_path, "rb") as f:
                if size <= 50:
                    await message.answer_video(f)
                else:
                    await message.answer_document(f)
            return
    except:
        pass

    # fallback audio
    audio_path = safe_download(download_audio, text)

    if audio_path and os.path.exists(audio_path):
        try:
            with open(audio_path, "rb") as f:
                await message.answer_audio(f)
            return
        except:
            pass

    await message.answer("❌ Yuklab bo'lmadi")

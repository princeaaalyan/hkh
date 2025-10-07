import telebot
from telebot import types
import yt_dlp
import time
import os
import threading
import requests
import zipfile

API_TOKEN = '8472719783:AAH5EGILySllh1p0qfEsk9FVvxcG4icDJiU'
OWNER_USERNAME = 'Hz_REFLEX'

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML")

# Path for cookies file
COOKIES_FILE = "cookies.txt"

QUALITY_LABELS = {
    "144": "144p",
    "240": "240p",
    "360": "360p",
    "480": "480p",
    "720": "720p HD",
    "1080": "1080p FHD",
    "1440": "1440p QHD",
    "2160": "2160p 4K",
}

user_states = {}

def get_human_readable_size(size_bytes):
    if not size_bytes:
        return "Unknown size"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"

def main_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎬 YT Video", callback_data="yt_video"),
        types.InlineKeyboardButton("🎞️ YT Shorts", callback_data="yt_shorts"),
        types.InlineKeyboardButton("🎵 YT MP3", callback_data="yt_mp3"),
        types.InlineKeyboardButton("📃 Playlist", callback_data="yt_playlist"),
        types.InlineKeyboardButton("👤 Owner", url=f"https://t.me/{OWNER_USERNAME}")
    )
    return markup

def clear_user_state(chat_id):
    if chat_id in user_states:
        del user_states[chat_id]

def get_ydl_opts_base():
    """Base yt-dlp options with cookies support"""
    opts = {
        'quiet': True,
        'no_warnings': False,
    }
    
    # Add cookies if file exists
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE
        print("✅ Using cookies.txt for authentication")
    else:
        print("⚠️ cookies.txt not found - proceeding without authentication")
    
    return opts

@bot.message_handler(commands=['start'])
def start_cmd(message):
    desc = (
        "👋 <b>Welcome to YouTube Downloader Bot!</b>\n\n"
        "Here's what I can do for you:\n"
        "🎬 Download YouTube videos (up to 4K)\n"
        "🎞 Download YouTube Shorts\n"
        "🎵 Extract & send YouTube MP3 audio\n"
        "📃 Download full YouTube Playlists (video or mp3)\n\n"
        "Just select an option below and send me the link!\n"
        "⚡ <i>All files are deleted after sending.</i>"
    )
    bot.send_message(message.chat.id, desc, reply_markup=main_menu())

@bot.callback_query_handler(func=lambda c: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    data = call.data

    if data in ["yt_video", "yt_shorts"]:
        user_states[chat_id] = {"mode": data}
        bot.send_message(chat_id, f"📎 Please send me the <b>{data.replace('yt_', '').replace('_', ' ').title()}</b> YouTube link:")
        bot.answer_callback_query(call.id)

    elif data == "yt_mp3":
        user_states[chat_id] = {"mode": "yt_mp3"}
        bot.send_message(chat_id, "📎 Please send me the <b>MP3</b> YouTube link:")
        bot.answer_callback_query(call.id)

    elif data == "yt_playlist":
        user_states[chat_id] = {"mode": "playlist_choose"}
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🎬 Video", callback_data="playlist_video"),
            types.InlineKeyboardButton("🎵 MP3", callback_data="playlist_mp3"),
            types.InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        )
        bot.edit_message_text("Choose playlist download format:", chat_id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif data in ["playlist_video", "playlist_mp3"]:
        user_states[chat_id]["playlist_format"] = "mp4" if data == "playlist_video" else "mp3"
        user_states[chat_id]["mode"] = "playlist_wait_link"
        bot.send_message(chat_id, "📎 Send the playlist link now:")
        bot.answer_callback_query(call.id)

    elif data.startswith("quality_"):
        quality = data.split("_")[1]
        state = user_states.get(chat_id)
        if not state:
            bot.answer_callback_query(call.id, "Session expired, please start again.")
            return

        state["quality"] = quality
        bot.answer_callback_query(call.id)
        threading.Thread(target=start_download, args=(chat_id, state)).start()
        clear_user_state(chat_id)

    elif data == "cancel":
        clear_user_state(chat_id)
        bot.edit_message_text("❌ Operation cancelled.", chat_id, call.message.message_id)
        bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get("mode") in ["yt_video", "yt_shorts"])
def receive_link_video(message):
    chat_id = message.chat.id
    url = message.text.strip()
    state = user_states.get(chat_id)
    if not state:
        bot.send_message(chat_id, "⚠️ Something went wrong, please try again.")
        return
    mode = state["mode"]
    user_states[chat_id]["url"] = url

    progress_msg = bot.send_message(chat_id, "🔍 Searching Video...")
    try:
        ydl_opts = get_ydl_opts_base()
        ydl_opts.update({'skip_download': True})
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        bot.edit_message_text("📦 Data Fetched!", chat_id, progress_msg.message_id)

        formats = []
        for f in info['formats']:
            if f.get('vcodec') != 'none':
                formats.append(f)

        qualities = {}
        for f in formats:
            height = f.get('height') or 0
            if height >= 144 and height <= 2160:
                size = f.get('filesize') or f.get('filesize_approx')
                if height not in qualities or (size and qualities[height] is None):
                    qualities[height] = size

        if not qualities:
            bot.edit_message_text("⚠️ No suitable quality found.", chat_id, progress_msg.message_id)
            clear_user_state(chat_id)
            return

        markup = types.InlineKeyboardMarkup(row_width=3)
        for q in sorted(qualities.keys()):
            label = QUALITY_LABELS.get(str(q), f"{q}p")
            size = get_human_readable_size(qualities[q])
            markup.add(types.InlineKeyboardButton(f"{label} ({size})", callback_data=f"quality_{q}"))

        bot.edit_message_text("Select quality:", chat_id, progress_msg.message_id, reply_markup=markup)

    except Exception as e:
        bot.edit_message_text(f"❌ Error fetching video info: {str(e)}", chat_id, progress_msg.message_id)
        clear_user_state(chat_id)

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get("mode") == "yt_mp3")
def receive_link_mp3(message):
    chat_id = message.chat.id
    url = message.text.strip()
    state = user_states.get(chat_id)
    if not state:
        bot.send_message(chat_id, "⚠️ Something went wrong, please try again.")
        return
    user_states[chat_id]["url"] = url
    threading.Thread(target=start_download_mp3, args=(chat_id, url)).start()
    clear_user_state(chat_id)

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get("mode") == "playlist_wait_link")
def receive_playlist_link(message):
    chat_id = message.chat.id
    url = message.text.strip()
    state = user_states.get(chat_id)
    if not state:
        bot.send_message(chat_id, "⚠️ Something went wrong, please try again.")
        return
    user_states[chat_id]["url"] = url
    threading.Thread(target=start_download, args=(chat_id, state)).start()
    clear_user_state(chat_id)

def start_download_mp3(chat_id, url):
    progress_msg = bot.send_message(chat_id, "🔍 Searching Video...")
    
    ydl_opts = get_ydl_opts_base()
    ydl_opts.update({
        'format': 'bestaudio/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'noplaylist': True,
        'progress_hooks': [lambda d: download_hook(d, bot, chat_id, progress_msg)],
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    })
    
    try:
        bot.edit_message_text("📦 Data Fetched!", chat_id, progress_msg.message_id)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            file_path = file_path.rsplit('.', 1)[0] + ".mp3"
            # Simulate upload progress
            for percent in range(0, 101, 10):
                bot.edit_message_text(f"⏫ Uploading... {percent}%", chat_id, progress_msg.message_id)
                time.sleep(0.1)
            send_media(chat_id, file_path, info, "yt_mp3")
            bot.edit_message_text("✅ Done!", chat_id, progress_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Error during MP3 download: {str(e)}", chat_id, progress_msg.message_id)

def download_hook(d, bot, chat_id, progress_msg):
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '0%').strip()
        bot.edit_message_text(f"⬇️ Downloading... {percent}", chat_id, progress_msg.message_id)
    elif d['status'] == 'finished':
        bot.edit_message_text("🎵 Converting to MP3...", chat_id, progress_msg.message_id)

def start_download(chat_id, state):
    url = state.get("url")
    quality = state.get("quality")
    mode = state.get("mode")
    playlist_format = state.get("playlist_format", None)

    progress_msg = bot.send_message(chat_id, "🔍 Searching Video...")

    def video_download_hook(d):
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '0%').strip()
            bot.edit_message_text(f"⬇️ Downloading... {percent}", chat_id, progress_msg.message_id)
        elif d['status'] == 'finished':
            bot.edit_message_text("🎬 Finalizing Video...", chat_id, progress_msg.message_id)

    def playlist_download_hook(d):
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '0%').strip()
            bot.edit_message_text(f"⬇️ Downloading playlist... {percent}", chat_id, progress_msg.message_id)
        elif d['status'] == 'finished':
            bot.edit_message_text("🎬 Finalizing Playlist...", chat_id, progress_msg.message_id)

    try:
        bot.edit_message_text("📦 Data Fetched!", chat_id, progress_msg.message_id)
        if playlist_format:
            send_playlist(chat_id, url, playlist_format, progress_msg, playlist_download_hook)
            return

        ydl_opts = get_ydl_opts_base()
        ydl_opts.update({
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'noplaylist': True,
            'merge_output_format': 'mp4',
            'format': 'bestvideo+bestaudio/best',
            'progress_hooks': [video_download_hook]
        })

        if (mode in ["yt_video", "yt_shorts"]) or (playlist_format == "mp4"):
            if quality:
                ydl_opts['format'] = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best[height<={quality}]"
            ydl_opts['merge_output_format'] = 'mp4'
            ydl_opts['outtmpl'] = 'downloads/%(title)s.%(ext)s'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            if (mode in ["yt_video", "yt_shorts"]) and not file_path.endswith('.mp4'):
                possible_mp4 = file_path.rsplit('.', 1)[0] + ".mp4"
                if os.path.exists(possible_mp4):
                    file_path = possible_mp4
            for percent in range(0, 101, 10):
                bot.edit_message_text(f"⏫ Uploading... {percent}%", chat_id, progress_msg.message_id)
                time.sleep(0.1)
            send_media(chat_id, file_path, info, mode)
            bot.edit_message_text("✅ Done!", chat_id, progress_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Error during download: {str(e)}", chat_id, progress_msg.message_id)

def send_media(chat_id, file_path, info, mode):
    title = info.get('title', 'No Title')
    duration = info.get('duration', 0)
    uploader = info.get('uploader', 'Unknown')
    thumbnail_url = info.get('thumbnail')
    duration_str = time.strftime('%H:%M:%S', time.gmtime(duration))

    caption = (f"🎬 <b>{title}</b>\n"
               f"⏱ Duration: {duration_str}\n"
               f"👤 Uploader: {uploader}\n"
               f"🔗 <a href='{info.get('webpage_url', '')}'>Watch on YouTube</a>")

    thumbnail_file = None
    if thumbnail_url:
        try:
            thumb_resp = requests.get(thumbnail_url)
            thumbnail_file = f"downloads/thumb_{chat_id}.jpg"
            with open(thumbnail_file, "wb") as f:
                f.write(thumb_resp.content)
        except Exception:
            thumbnail_file = None

    try:
        if mode == "yt_mp3":
            with open(file_path, 'rb') as audio:
                bot.send_audio(chat_id, audio, caption=caption, parse_mode='HTML', thumb=thumbnail_file)
        else:
            with open(file_path, 'rb') as video:
                bot.send_video(chat_id, video, caption=caption, parse_mode='HTML', thumb=thumbnail_file, supports_streaming=True)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error sending media: {str(e)}")
    finally:
        # Cleanup files
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            if thumbnail_file and os.path.exists(thumbnail_file):
                os.remove(thumbnail_file)
        except Exception as e:
            print(f"Warning: Could not delete files: {e}")

def send_playlist(chat_id, url, fmt, progress_msg, playlist_download_hook):
    bot.edit_message_text("🔍 Searching Playlist...", chat_id, progress_msg.message_id)

    ydl_opts = get_ydl_opts_base()
    ydl_opts.update({
        'outtmpl': 'downloads/%(playlist_title)s/%(title)s.%(ext)s',
        'ignoreerrors': True,
        'format': 'bestaudio/best' if fmt == "mp3" else 'bestvideo+bestaudio/best',
        'yesplaylist': True,
        'noplaylist': False,
        'merge_output_format': 'mp4' if fmt == "mp4" else None,
        'progress_hooks': [playlist_download_hook]
    })

    if fmt == "mp3":
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        playlist_title = info.get('title', 'playlist').replace('/', '_').replace('\\', '_')
        playlist_dir = f"downloads/{playlist_title}"

        if not os.path.exists(playlist_dir):
            bot.edit_message_text("❌ Playlist download failed or empty.", chat_id, progress_msg.message_id)
            return

        zip_filename = f"{playlist_dir}.zip"
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(playlist_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, arcname=file)
                    
        for percent in range(0, 101, 10):
            bot.edit_message_text(f"⏫ Uploading... {percent}%", chat_id, progress_msg.message_id)
            time.sleep(0.1)
            
        with open(zip_filename, 'rb') as f:
            bot.send_document(chat_id, f, caption=f"📀 Playlist: <b>{playlist_title}</b>", parse_mode='HTML')

        # Cleanup
        for root, dirs, files in os.walk(playlist_dir, topdown=False):
            for file in files:
                os.remove(os.path.join(root, file))
            for dir in dirs:
                os.rmdir(os.path.join(root, dir))
        if os.path.exists(playlist_dir):
            os.rmdir(playlist_dir)
        if os.path.exists(zip_filename):
            os.remove(zip_filename)
            
        bot.edit_message_text("✅ Done!", chat_id, progress_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Error downloading playlist: {str(e)}", chat_id, progress_msg.message_id)

def setup_environment():
    """Setup required directories and check dependencies"""
    # Create downloads directory
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
        print("✅ Created downloads directory")
    
    # Check if cookies.txt exists
    if os.path.exists(COOKIES_FILE):
        print("✅ cookies.txt found - authentication enabled")
    else:
        print("⚠️ cookies.txt not found - some age-restricted content may not be accessible")
    
    # Check for FFmpeg
    try:
        import subprocess
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ FFmpeg is available")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ FFmpeg not found. Audio conversion may not work properly.")
        print("Install FFmpeg on Ubuntu: sudo apt update && sudo apt install ffmpeg")

if __name__ == "__main__":
    print("🚀 Starting YouTube Downloader Bot...")
    setup_environment()
    print("✅ Bot is ready and polling...")
    bot.infinity_polling()

import os
import logging
import asyncio
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode, ChatAction
import re
from datetime import timedelta
import shutil

# إعداد السجلات
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# رمز البوت
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("❌ يجب تعيين متغير BOT_TOKEN!")

# مجلد التحميلات
DOWNLOAD_FOLDER = '/tmp/downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# ذاكرة مؤقتة
video_cache = {}

# حد أقصى لحجم الملف (2GB)
MAX_FILE_SIZE = 2000 * 1024 * 1024


def clean_filename(filename):
    """تنظيف اسم الملف"""
    return re.sub(r'[^\w\s-]', '', filename)[:100]


def format_duration(seconds):
    """تنسيق المدة"""
    if not seconds:
        return "غير معروف"
    return str(timedelta(seconds=int(seconds)))


def format_views(count):
    """تنسيق عدد المشاهدات"""
    if not count:
        return "0"
    if count >= 1_000_000:
        return f"{count/1_000_000:.1f}M"
    elif count >= 1_000:
        return f"{count/1_000:.1f}K"
    return str(count)


class YouTubeDownloader:
    """معالج تحميل يوتيوب"""
    
    @staticmethod
    def extract_info(url):
        """استخراج معلومات الفيديو"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'socket_timeout': 30,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # استخراج الصيغ
                formats = info.get('formats', [])
                video_qualities = {}
                
                # فلترة الصيغ المناسبة
                for f in formats:
                    height = f.get('height')
                    vcodec = f.get('vcodec', 'none')
                    acodec = f.get('acodec', 'none')
                    
                    # فيديو + صوت
                    if height and vcodec != 'none' and acodec != 'none':
                        if height not in video_qualities or f.get('fps', 0) > video_qualities[height].get('fps', 0):
                            video_qualities[height] = f
                
                return {
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail'),
                    'uploader': info.get('uploader', 'Unknown'),
                    'views': info.get('view_count', 0),
                    'description': (info.get('description') or '')[:150],
                    'url': url,
                    'qualities': sorted(video_qualities.keys(), reverse=True),
                }
                
        except Exception as e:
            logger.error(f"خطأ في استخراج المعلومات: {e}")
            return None
    
    @staticmethod
    async def download(url, quality='best', format_type='mp4', progress_msg=None):
        """تحميل الفيديو"""
        filename = f"{DOWNLOAD_FOLDER}/{clean_filename(str(hash(url)))}"
        
        ydl_opts = {
            'format': 'bestaudio/best' if quality == 'audio' else f'best[height<={quality}][ext=mp4]/best[height<={quality}]',
            'outtmpl': f'{filename}.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'retries': 3,
        }
        
        # خيارات الصوت
        if format_type == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            ydl_opts['prefer_ffmpeg'] = True
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # التحميل
                info = ydl.extract_info(url, download=True)
                
                # العثور على الملف
                downloaded_file = None
                for file in os.listdir(DOWNLOAD_FOLDER):
                    if file.startswith(clean_filename(str(hash(url)))):
                        downloaded_file = os.path.join(DOWNLOAD_FOLDER, file)
                        break
                
                if downloaded_file and os.path.exists(downloaded_file):
                    return downloaded_file, info.get('title', 'video')
                    
                return None, None
                
        except Exception as e:
            logger.error(f"خطأ في التحميل: {e}")
            return None, None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start"""
    welcome = """
🎬 **أهلاً بك في بوت تحميل يوتيوب الاحترافي!**

━━━━━━━━━━━━━━━━━━━━
✨ **المميزات:**
✅ تحميل بجودات متعددة
✅ تحويل إلى MP3
✅ سريع وآمن 100%
✅ دعم الفيديوهات الطويلة

━━━━━━━━━━━━━━━━━━━━
📝 **طريقة الاستخدام:**

1️⃣ أرسل رابط يوتيوب
2️⃣ اختر الجودة المطلوبة  
3️⃣ انتظر التحميل

━━━━━━━━━━━━━━━━━━━━
💡 **مثال:**
`https://youtu.be/xxxxx`

🚀 **ابدأ الآن!**
    """
    
    keyboard = [
        [
            InlineKeyboardButton("📖 دليل الاستخدام", callback_data="help"),
            InlineKeyboardButton("ℹ️ معلومات", callback_data="about")
        ]
    ]
    
    await update.message.reply_text(
        welcome,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل"""
    text = update.message.text
    user_id = update.effective_user.id
    
    # فحص رابط يوتيوب
    youtube_pattern = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    
    if not re.search(youtube_pattern, text):
        await update.message.reply_text(
            "❌ **رابط غير صحيح!**\n\n"
            "الرجاء إرسال رابط يوتيوب صحيح.\n\n"
            "مثال:\n"
            "`https://youtube.com/watch?v=xxxxx`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # رسالة المعالجة
    await update.message.reply_chat_action(ChatAction.TYPING)
    status_msg = await update.message.reply_text(
        "🔍 **جاري تحليل الرابط...**\n"
        "⏳ الرجاء الانتظار...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        # استخراج المعلومات
        info = YouTubeDownloader.extract_info(text)
        
        if not info:
            await status_msg.edit_text(
                "❌ **فشل في جلب معلومات الفيديو!**\n\n"
                "تأكد من:\n"
                "• صحة الرابط\n"
                "• الفيديو غير محذوف\n"
                "• الفيديو غير خاص"
            )
            return
        
        # حفظ في الذاكرة المؤقتة
        video_cache[user_id] = info
        
        # رسالة المعلومات
        info_text = f"""
🎬 **{info['title']}**

👤 القناة: `{info['uploader']}`
⏱ المدة: `{format_duration(info['duration'])}`
👁 المشاهدات: `{format_views(info['views'])}`

📝 {info['description']}

━━━━━━━━━━━━━━━━━━━━
**اختر الجودة المطلوبة:**
        """
        
        # بناء لوحة الأزرار
        keyboard = []
        
        # أزرار الجودة
        qualities = info['qualities'][:8]  # أول 8 جودات
        row = []
        for i, q in enumerate(qualities):
            row.append(InlineKeyboardButton(f"📹 {q}p", callback_data=f"dl_{q}_mp4"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        # أزرار الصوت
        keyboard.append([
            InlineKeyboardButton("🎵 MP3 صوت فقط", callback_data="dl_audio_mp3")
        ])
        
        # زر الإلغاء
        keyboard.append([
            InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
        ])
        
        # حذف رسالة الحالة وإرسال المعلومات
        await status_msg.delete()
        
        if info['thumbnail']:
            try:
                await update.message.reply_photo(
                    photo=info['thumbnail'],
                    caption=info_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except:
                await update.message.reply_text(
                    info_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            await update.message.reply_text(
                info_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    except Exception as e:
        logger.error(f"خطأ في معالجة الرابط: {e}")
        await status_msg.edit_text(
            f"❌ **حدث خطأ!**\n\n"
            f"`{str(e)}`\n\n"
            f"حاول مرة أخرى.",
            parse_mode=ParseMode.MARKDOWN
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    # زر الإلغاء
    if data == "cancel":
        await query.message.delete()
        if user_id in video_cache:
            del video_cache[user_id]
        return
    
    # زر المساعدة
    if data == "help":
        help_text = """
📖 **دليل الاستخدام التفصيلي**

━━━━━━━━━━━━━━━━━━━━
**1️⃣ كيفية التحميل:**

• انسخ رابط فيديو يوتيوب
• أرسله للبوت
• اختر الجودة
• انتظر التحميل

━━━━━━━━━━━━━━━━━━━━
**2️⃣ الجودات المتاحة:**

📹 144p - 1080p (فيديو)
🎵 MP3 (صوت فقط)

━━━━━━━━━━━━━━━━━━━━
**3️⃣ ملاحظات مهمة:**

⚠️ الحد الأقصى: 2GB
⏱ قد يستغرق وقتاً
🔒 آمن 100%

━━━━━━━━━━━━━━━━━━━━
💬 للدعم: /start
        """
        await query.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
        return
    
    # زر المعلومات
    if data == "about":
        about_text = """
ℹ️ **معلومات البوت**

━━━━━━━━━━━━━━━━━━━━
🤖 **بوت تحميل يوتيوب**
📌 الإصدار: 2.1.0
⚡️ المحرك: yt-dlp

━━━━━━━━━━━━━━━━━━━━
🔧 **التقنيات:**
• Python 3.11
• python-telegram-bot
• yt-dlp

━━━━━━━━━━━━━━━━━━━━
💝 شكراً لاستخدامك البوت!
        """
        await query.message.reply_text(about_text, parse_mode=ParseMode.MARKDOWN)
        return
    
    # معالجة التحميل
    if data.startswith("dl_"):
        parts = data.split("_")
        quality = parts[1]
        format_type = parts[2]
        
        # التحقق من وجود البيانات
        if user_id not in video_cache:
            await query.message.reply_text(
                "❌ **انتهت الجلسة!**\n\n"
                "الرجاء إرسال الرابط مرة أخرى.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        info = video_cache[user_id]
        
        # رسالة التحميل
        download_msg = await query.message.reply_text(
            f"⬇️ **جاري التحميل...**\n\n"
            f"📹 الجودة: `{quality}`\n"
            f"📦 الصيغة: `{format_type.upper()}`\n\n"
            f"⏳ قد يستغرق بضع دقائق...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        try:
            # التحميل
            file_path, title = await YouTubeDownloader.download(
                info['url'],
                quality,
                format_type,
                download_msg
            )
            
            if not file_path or not os.path.exists(file_path):
                await download_msg.edit_text(
                    "❌ **فشل التحميل!**\n\n"
                    "حاول مرة أخرى أو جرب جودة أخرى.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # فحص الحجم
            file_size = os.path.getsize(file_path)
            if file_size > MAX_FILE_SIZE:
                os.remove(file_path)
                await download_msg.edit_text(
                    "❌ **الملف كبير جداً!**\n\n"
                    f"الحجم: `{file_size/(1024*1024):.1f} MB`\n"
                    f"الحد الأقصى: `2000 MB`\n\n"
                    "جرب جودة أقل.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # الرفع
            await download_msg.edit_text(
                f"📤 **جاري الرفع...**\n\n"
                f"📦 الحجم: `{file_size/(1024*1024):.1f} MB`\n"
                f"⏳ الرجاء الانتظار...",
                parse_mode=ParseMode.MARKDOWN
            )
            
            caption = f"✅ **{title}**\n\n📹 {quality} • {format_type.upper()}"
            
            # إرسال الملف
            with open(file_path, 'rb') as f:
                if format_type == 'mp3':
                    await query.message.reply_audio(
                        audio=f,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        title=title,
                        performer=info['uploader']
                    )
                else:
                    await query.message.reply_video(
                        video=f,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        supports_streaming=True,
                        width=1280,
                        height=720
                    )
            
            # تنظيف
            await download_msg.delete()
            os.remove(file_path)
            
            if user_id in video_cache:
                del video_cache[user_id]
                
        except Exception as e:
            logger.error(f"خطأ في التحميل: {e}")
            await download_msg.edit_text(
                f"❌ **حدث خطأ!**\n\n"
                f"`{str(e)}`\n\n"
                f"حاول مرة أخرى.",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # حذف الملف إن وجد
            if 'file_path' in locals() and file_path and os.path.exists(file_path):
                os.remove(file_path)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأخطاء"""
    logger.error(f"خطأ: {context.error}", exc_info=context.error)


def main():
    """الدالة الرئيسية"""
    logger.info("🚀 بدء تشغيل البوت...")
    
    # بناء التطبيق
    app = Application.builder().token(TOKEN).build()
    
    # المعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)
    
    # التشغيل
    logger.info("✅ البوت يعمل!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    main()

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
from telegram.constants import ParseMode
import re
from datetime import timedelta

# إعداد السجلات
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# رمز البوت من المتغيرات البيئية
TOKEN = os.getenv('BOT_TOKEN')

# مجلد مؤقت للتحميلات
DOWNLOAD_FOLDER = 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# قاموس لتخزين معلومات الفيديوهات مؤقتاً
video_info_cache = {}


class YouTubeDownloader:
    """فئة لمعالجة تحميلات يوتيوب"""
    
    @staticmethod
    def get_video_info(url):
        """الحصول على معلومات الفيديو"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # استخراج الجودات المتاحة
                formats = info.get('formats', [])
                video_formats = {}
                audio_formats = []
                
                for f in formats:
                    if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                        height = f.get('height')
                        if height and height not in video_formats:
                            video_formats[height] = f
                    elif f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                        audio_formats.append(f)
                
                return {
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'uploader': info.get('uploader', 'Unknown'),
                    'view_count': info.get('view_count', 0),
                    'description': info.get('description', '')[:200],
                    'formats': video_formats,
                    'audio_formats': audio_formats,
                    'url': url
                }
        except Exception as e:
            logger.error(f"خطأ في الحصول على معلومات الفيديو: {e}")
            return None
    
    @staticmethod
    async def download_video(url, quality, format_type, progress_callback=None):
        """تحميل الفيديو بجودة وصيغة محددة"""
        filename = f"{DOWNLOAD_FOLDER}/{hash(url)}_{quality}.{format_type}"
        
        ydl_opts = {
            'format': f'best[height<={quality}]' if quality != 'audio' else 'bestaudio',
            'outtmpl': filename,
            'quiet': True,
            'no_warnings': True,
        }
        
        if format_type == 'mp3':
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
                # العثور على الملف المحمل
                for file in os.listdir(DOWNLOAD_FOLDER):
                    if file.startswith(str(hash(url))):
                        return os.path.join(DOWNLOAD_FOLDER, file)
                        
                return filename
        except Exception as e:
            logger.error(f"خطأ في التحميل: {e}")
            return None


def format_duration(seconds):
    """تنسيق المدة الزمنية"""
    return str(timedelta(seconds=seconds))


def format_number(num):
    """تنسيق الأرقام"""
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    return str(num)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر البدء"""
    welcome_message = """
🎬 **مرحباً بك في بوت تحميل فيديوهات يوتيوب!**

📌 **المميزات:**
✅ تحميل بجودات مختلفة (144p - 1080p)
✅ تحميل صوت MP3
✅ دعم صيغ متعددة (MP4, MKV)
✅ معاينة معلومات الفيديو
✅ سريع وآمن

📝 **كيفية الاستخدام:**
1️⃣ أرسل رابط فيديو يوتيوب
2️⃣ اختر الجودة والصيغة المطلوبة
3️⃣ انتظر التحميل والإرسال

💡 مثال:
`https://www.youtube.com/watch?v=xxxxx`

🚀 ابدأ الآن بإرسال رابط الفيديو!
    """
    
    keyboard = [
        [InlineKeyboardButton("📖 المساعدة", callback_data="help"),
         InlineKeyboardButton("ℹ️ حول", callback_data="about")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_message,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رابط يوتيوب"""
    url = update.message.text
    user_id = update.effective_user.id
    
    # التحقق من صحة الرابط
    youtube_regex = r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
    if not re.match(youtube_regex, url):
        await update.message.reply_text(
            "❌ الرجاء إرسال رابط يوتيوب صحيح!"
        )
        return
    
    # إرسال رسالة انتظار
    processing_msg = await update.message.reply_text(
        "⏳ جاري معالجة الرابط...\n🔍 جلب معلومات الفيديو..."
    )
    
    # الحصول على معلومات الفيديو
    video_info = YouTubeDownloader.get_video_info(url)
    
    if not video_info:
        await processing_msg.edit_text(
            "❌ فشل في الحصول على معلومات الفيديو!\n"
            "تأكد من صحة الرابط وحاول مرة أخرى."
        )
        return
    
    # حفظ المعلومات مؤقتاً
    video_info_cache[user_id] = video_info
    
    # إنشاء رسالة المعلومات
    info_message = f"""
🎬 **{video_info['title']}**

👤 **القناة:** {video_info['uploader']}
⏱ **المدة:** {format_duration(video_info['duration'])}
👁 **المشاهدات:** {format_number(video_info['view_count'])}

📝 **الوصف:**
{video_info['description']}...

✨ **اختر الجودة والصيغة المطلوبة:**
    """
    
    # إنشاء لوحة الأزرار
    keyboard = []
    
    # أزرار جودة الفيديو
    quality_buttons = []
    available_qualities = sorted(video_info['formats'].keys(), reverse=True)
    
    for i, quality in enumerate(available_qualities[:6]):  # حد أقصى 6 جودات
        quality_buttons.append(
            InlineKeyboardButton(
                f"📹 {quality}p",
                callback_data=f"quality_{quality}_mp4"
            )
        )
        if (i + 1) % 2 == 0:
            keyboard.append(quality_buttons)
            quality_buttons = []
    
    if quality_buttons:
        keyboard.append(quality_buttons)
    
    # أزرار الصوت
    keyboard.append([
        InlineKeyboardButton("🎵 MP3 Audio", callback_data="quality_audio_mp3"),
        InlineKeyboardButton("🎼 M4A Audio", callback_data="quality_audio_m4a")
    ])
    
    # زر الإلغاء
    keyboard.append([
        InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # إرسال الصورة المصغرة مع المعلومات
    try:
        await processing_msg.delete()
        if video_info['thumbnail']:
            await update.message.reply_photo(
                photo=video_info['thumbnail'],
                caption=info_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                info_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"خطأ في إرسال المعلومات: {e}")
        await update.message.reply_text(
            info_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة ضغطات الأزرار"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data == "cancel":
        await query.message.delete()
        await query.message.reply_text("❌ تم الإلغاء!")
        if user_id in video_info_cache:
            del video_info_cache[user_id]
        return
    
    if data == "help":
        help_text = """
📖 **دليل الاستخدام:**

1️⃣ **إرسال الرابط:**
   أرسل رابط فيديو يوتيوب مباشرة

2️⃣ **اختيار الجودة:**
   - 144p - 1080p للفيديو
   - MP3/M4A للصوت فقط

3️⃣ **التحميل:**
   سيتم تحميل الفيديو وإرساله لك تلقائياً

⚠️ **ملاحظات:**
- الحد الأقصى للملف: 2GB
- قد يستغرق التحميل بعض الوقت
- الفيديوهات الطويلة تحتاج وقت أطول

💬 للدعم: @YourSupportChannel
        """
        await query.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
        return
    
    if data == "about":
        about_text = """
ℹ️ **حول البوت:**

🤖 **بوت تحميل يوتيوب الاحترافي**
📌 الإصدار: 2.0.0
⚡️ محرك التحميل: yt-dlp

👨‍💻 **المطور:** Your Name
🔗 **القناة:** @YourChannel

💝 **شكراً لاستخدامك البوت!**
        """
        await query.message.reply_text(about_text, parse_mode=ParseMode.MARKDOWN)
        return
    
    if data.startswith("quality_"):
        parts = data.split("_")
        quality = parts[1]
        format_type = parts[2]
        
        if user_id not in video_info_cache:
            await query.message.reply_text(
                "❌ انتهت صلاحية الجلسة. الرجاء إرسال الرابط مرة أخرى."
            )
            return
        
        video_info = video_info_cache[user_id]
        
        # رسالة التحميل
        download_msg = await query.message.reply_text(
            f"⬇️ جاري التحميل...\n"
            f"📹 الجودة: {quality}\n"
            f"📦 الصيغة: {format_type.upper()}\n\n"
            f"⏳ الرجاء الانتظار..."
        )
        
        try:
            # تحميل الفيديو
            file_path = await YouTubeDownloader.download_video(
                video_info['url'],
                quality,
                format_type
            )
            
            if not file_path or not os.path.exists(file_path):
                await download_msg.edit_text(
                    "❌ فشل التحميل! حاول مرة أخرى."
                )
                return
            
            # التحقق من حجم الملف
            file_size = os.path.getsize(file_path)
            if file_size > 2000 * 1024 * 1024:  # 2GB
                await download_msg.edit_text(
                    "❌ حجم الملف كبير جداً (أكثر من 2GB)!\n"
                    "جرب جودة أقل."
                )
                os.remove(file_path)
                return
            
            await download_msg.edit_text(
                "📤 جاري رفع الملف...\n"
                "⏳ قد يستغرق هذا بعض الوقت..."
            )
            
            # إرسال الملف
            caption = f"✅ **{video_info['title']}**\n\n📹 {quality} | {format_type.upper()}"
            
            with open(file_path, 'rb') as file:
                if format_type in ['mp3', 'm4a']:
                    await query.message.reply_audio(
                        audio=file,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        title=video_info['title'],
                        performer=video_info['uploader']
                    )
                else:
                    await query.message.reply_video(
                        video=file,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        supports_streaming=True
                    )
            
            await download_msg.delete()
            
            # حذف الملف المؤقت
            os.remove(file_path)
            
            # حذف من الذاكرة المؤقتة
            if user_id in video_info_cache:
                del video_info_cache[user_id]
                
        except Exception as e:
            logger.error(f"خطأ في معالجة التحميل: {e}")
            await download_msg.edit_text(
                f"❌ حدث خطأ أثناء المعالجة!\n"
                f"الخطأ: {str(e)}\n\n"
                f"حاول مرة أخرى أو اختر جودة مختلفة."
            )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأخطاء العام"""
    logger.error(f"حدث خطأ: {context.error}")
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ حدث خطأ غير متوقع!\n"
                "الرجاء المحاولة مرة أخرى لاحقاً."
            )
    except Exception as e:
        logger.error(f"خطأ في معالج الأخطاء: {e}")


def main():
    """الدالة الرئيسية"""
    if not TOKEN:
        logger.error("BOT_TOKEN غير محدد!")
        return
    
    # إنشاء التطبيق
    application = Application.builder().token(TOKEN).build()
    
    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # معالج الأخطاء
    application.add_error_handler(error_handler)
    
    # بدء البوت
    logger.info("البوت يعمل الآن...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

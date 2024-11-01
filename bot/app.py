import logging
import asyncio
from pathlib import Path
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    filters
)
import time
import shutil
from telegram.constants import ParseMode, ChatAction
from bot import config
from bot.database import Database, DownloadStatus
from bot.download import download_video, is_valid_url, DownloadError, get_platform
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# Initialize database and logger
db = Database()
logger = logging.getLogger(__name__)

# Rate limiting and concurrency controls
user_download_counts = defaultdict(int)
user_download_times = defaultdict(float)
user_semaphores = defaultdict(lambda: asyncio.Semaphore(3))

# Constants
# Constants
MAX_FILE_SIZE_MB = 4000
REGULAR_FILE_SIZE_MB = 50  # Changed from REGULAR_FILE_SIZE to REGULAR_FILE_SIZE_MB
RATE_LIMIT_PERIOD = 60  # seconds
MAX_REQUESTS_PER_PERIOD = 5

# Message Templates
MESSAGES = {
    "help": """<b>🤖 Bot Commands</b>

📍 <b>Available Commands:</b>
• /start – Start the bot 🚀
• /help – Show this help message ℹ️
• /cancel - Cancel current download ⚠️
• /stats - View your download statistics 📊

📥 <b>How to use:</b>
Simply send a video URL from YouTube, TikTok, or Instagram!

⚡ <b>Features:</b>
• Fast downloads
• High quality videos
• Multiple platform support
• Progress tracking

⚠️ Note: Please be patient while downloading large videos.""",
    
    "error": "🤖 Oops! Something went wrong! Let me fix that for you 🔧\nPlease try again in a few moments 🙏",
    "rate_limit": "⏳ Whoa there! You're moving too fast!\nPlease wait {wait_time} seconds before your next request 🚦",
    "invalid_url": "🔍 Hmm... That doesn't look like a valid URL.\nPlease send a valid YouTube, TikTok, or Instagram link! 🎥",
    "download_start": """⚡ Starting your download...

📥 URL: {url}
🎯 Platform: {platform}
⚙️ Quality: Best available""",
    
    "upload_progress": "📤 Almost there! Uploading your video...",
    "success": """✨ Download successful!

📊 Stats:
🎥 Size: {size:.1f} MB
⚡ Platform: {platform}
🎯 Quality: Best available

Enjoy your video! 🎉""",
    "cancel_success": "🛑 Download cancelled successfully!",
    "no_active_download": "🤔 No active download to cancel.",
    "too_large": "⚠️ Video is too large! Maximum size is {max_size}MB 📦"
}

async def update_user_stats(user_id: int, chat_id: int, success: bool = True, platform: str = None):
    """Update user statistics"""
    try:
        current_time = datetime.now(timezone.utc)
        
        # Update user's main stats
        update_dict = {
            "last_interaction": current_time,
            f"total_{platform}_downloads": 1 if success else 0
        } if platform else {"last_interaction": current_time}
        
        inc_dict = {
            "total_requests": 1,
            "successful_downloads": 1 if success else 0,
            "failed_downloads": 0 if success else 1
        }

        db.user_collection.update_one(
            {"user_id": user_id},
            {
                "$set": update_dict,
                "$inc": inc_dict
            }
        )

        # Update daily stats
        today = datetime.combine(current_time.date(), datetime.min.time())
        daily_stats = {
            "daily_requests": 1,
            "successful_requests": 1 if success else 0,
            "failed_requests": 0 if success else 1
        }
        if platform:
            daily_stats[f"{platform}_downloads"] = 1 if success else 0

        db.user_stats_collection.update_one(
            {
                "user_id": user_id,
                "date": today
            },
            {
                "$inc": daily_stats,
                "$set": {"last_request_date": current_time}
            },
            upsert=True
        )

    except Exception as e:
        logger.error(f"Error updating user stats: {str(e)}", exc_info=True)

async def get_user_stats(user_id: int) -> str:
    """Get formatted user statistics"""
    try:
        # Get user document for basic info
        user_doc = db.user_collection.find_one({"user_id": user_id})
        if not user_doc:
            return "❌ User not found"
        
        # Get today's stats
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_stats = db.user_stats_collection.find_one({
            "user_id": user_id,
            "date": today_start
        }) or {}
        
        # Calculate total data downloaded
        total_data = sum(
            stats.get("total_data_downloaded", 0)
            for stats in db.user_stats_collection.find({"user_id": user_id})
        )

        return f"""📊 <b>Your Statistics</b>

📥 Total Downloads: {user_doc.get('successful_downloads', 0)}
❌ Failed Downloads: {user_doc.get('failed_downloads', 0)}
💾 Total Data: {total_data / (1024*1024):.1f} MB
🕐 Member Since: {user_doc.get('first_seen', datetime.now()).strftime('%Y-%m-%d')}

Today's Activity:
📊 Requests: {today_stats.get('daily_requests', 0)}
✅ Successful: {today_stats.get('successful_requests', 0)}
❌ Failed: {today_stats.get('failed_requests', 0)}"""
    except Exception as e:
        logger.error(f"Error getting user stats: {str(e)}", exc_info=True)
        return "❌ Could not fetch statistics"

async def start_handle(update: Update, context: CallbackContext):
    """Handle /start command"""
    try:
        user = update.message.from_user
        await register_user(update, context, user)
        await update.message.reply_text(
            MESSAGES["help"],
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error in start_handle: {str(e)}", exc_info=True)
        await update.message.reply_text(MESSAGES["error"])

async def help_handle(update: Update, context: CallbackContext):
    """Handle /help command"""
    try:
        await update.message.reply_text(
            MESSAGES["help"],
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error in help_handle: {str(e)}", exc_info=True)
        await update.message.reply_text(MESSAGES["error"])

async def stats_handle(update: Update, context: CallbackContext):
    """Handle /stats command"""
    try:
        stats_message = await get_user_stats(update.message.from_user.id)
        await update.message.reply_text(
            stats_message,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error in stats_handle: {str(e)}", exc_info=True)
        await update.message.reply_text(MESSAGES["error"])

async def cancel_handle(update: Update, context: CallbackContext):
    """Handle /cancel command"""
    try:
        if context.user_data.get('downloading'):
            context.user_data['cancel_download'] = True
            context.user_data['downloading'] = False
            await update.message.reply_text(MESSAGES["cancel_success"])
        else:
            await update.message.reply_text(MESSAGES["no_active_download"])
    except Exception as e:
        logger.error(f"Error in cancel_handle: {str(e)}", exc_info=True)
        await update.message.reply_text(MESSAGES["error"])

async def register_user(update: Update, context: CallbackContext, user):
    """Register new user if not exists"""
    try:
        if not db.check_if_user_exists(user.id):
            db.add_new_user(
                user.id,
                update.message.chat_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
    except Exception as e:
        logger.error(f"Error registering user: {str(e)}", exc_info=True)

async def check_rate_limit(user_id: int) -> bool:
    """Check if user has exceeded rate limit"""
    current_time = time.time()
    if current_time - user_download_times[user_id] > RATE_LIMIT_PERIOD:
        user_download_counts[user_id] = 0
        user_download_times[user_id] = current_time

    if user_download_counts[user_id] >= MAX_REQUESTS_PER_PERIOD:
        return False
    
    user_download_counts[user_id] += 1
    return True

async def process_video_url(update: Update, context: CallbackContext):
    """Process video download requests"""
    user = update.message.from_user
    url = update.message.text.strip()
    file_path = None
    output_dir = None
    request_id = None

    # Check if user has Telegram Premium
    is_premium = getattr(user, 'is_premium', False)
    file_size_limit = MAX_FILE_SIZE_MB if is_premium else REGULAR_FILE_SIZE_MB

    if not is_valid_url(url):
        await update.message.reply_text(MESSAGES["invalid_url"])
        return

    if not await check_rate_limit(user.id):
        wait_time = int(RATE_LIMIT_PERIOD - (time.time() - user_download_times[user.id]))
        await update.message.reply_text(
            MESSAGES["rate_limit"].format(wait_time=wait_time)
        )
        return

    status_message = None
    context.user_data['downloading'] = True
    context.user_data['cancel_download'] = False
    
    async with user_semaphores[user.id]:
        try:
            platform = get_platform(url)
            request_id = db.create_download_request(
                user.id,
                url,
                media_type='video',
                platform=platform
            )
            
            status_message = await update.message.reply_text(
                MESSAGES["download_start"].format(url=url, platform=platform)
            )
            
            await update.message.chat.send_action(action=ChatAction.UPLOAD_VIDEO)

            output_dir = Path(config.download_dir) / str(user.id)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            file_path, file_size = await asyncio.to_thread(
                download_video,
                url,
                str(output_dir)
            )

            if context.user_data.get('cancel_download'):
                raise DownloadError("Download cancelled by user")

            file_path = Path(file_path)
            if not file_path.exists():
                raise FileNotFoundError("File not found after download")

            file_size_mb = file_size / (1024 * 1024)
            if file_size_mb > file_size_limit:
                raise ValueError(
                    f"⚠️ Video is too large! Maximum size is {file_size_limit}MB 📦\n"
                    f"{'Consider getting Telegram Premium to download larger files!' if not is_premium else ''}"
                )

            await status_message.edit_text(MESSAGES["upload_progress"])
            
            with open(file_path, 'rb') as file:
                try:
                    await update.message.reply_video(
                        video=file,
                        caption=MESSAGES["success"].format(
                            size=file_size_mb,
                            platform=platform
                        ),
                        supports_streaming=True
                    )
                except Exception as e:
                    logger.error(f"Error sending as video: {str(e)}")
                    # If video fails, try sending as document
                    file.seek(0)
                    await update.message.reply_document(
                        document=file,
                        caption=MESSAGES["success"].format(
                            size=file_size_mb,
                            platform=platform
                        )
                    )
            
            # Update database and stats
            db.update_download_status(
                request_id,
                status=DownloadStatus.COMPLETED,
                file_size=file_size,
                download_path=str(file_path)
            )
            
            await update_user_stats(user.id, update.message.chat_id, success=True, platform=platform)
            db.mark_video_as_sent(user.id, str(file_path))

        except Exception as e:
            logger.error(f"Error for user {user.id}: {str(e)}", exc_info=True)
            if status_message:
                await status_message.edit_text(str(e) if "Video is too large" in str(e) else MESSAGES["error"])
            if request_id:
                db.update_download_status(
                    request_id, 
                    status=DownloadStatus.FAILED, 
                    error_message=str(e)
                )
            await update_user_stats(user.id, update.message.chat_id, success=False, platform=platform if 'platform' in locals() else None)
        finally:
            context.user_data['downloading'] = False
            # Cleanup
            try:
                if file_path and file_path.exists():
                    file_path.unlink()
                if output_dir and output_dir.exists() and not any(output_dir.iterdir()):
                    output_dir.rmdir()
            except Exception as e:
                logger.error(f"Cleanup error: {str(e)}", exc_info=True)

async def periodic_cleanup():
    """Periodic cleanup of old data"""
    while True:
        try:
            logger.info("Starting periodic data cleanup...")
            deleted_count = db.cleanup_old_data(days_old=30)
            logger.info(f"Cleanup completed. Removed {deleted_count} old records.")
            await asyncio.sleep(24 * 60 * 60)  # Wait 24 hours before next cleanup
        except Exception as e:
            logger.error(f"Error in data cleanup: {str(e)}", exc_info=True)
            await asyncio.sleep(60 * 60)  # Retry in 1 hour if error occurs

def schedule_cleanup(application):
    """Schedule the cleanup task"""
    async def cleanup_wrapper(context: CallbackContext):
        try:
            asyncio.create_task(periodic_cleanup())
        except Exception as e:
            logger.error(f"Error in cleanup scheduler: {str(e)}", exc_info=True)

    # Schedule the cleanup task
    application.job_queue.run_once(cleanup_wrapper, when=0)

def run_bot():
    """Initialize and run the bot"""
    # Configure logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
        handlers=[
            logging.FileHandler("bot.log"),
            logging.StreamHandler()
        ]
    )

    # Build application
    application = (
        ApplicationBuilder()
        .token(config.telegram_token)
        .concurrent_updates(True)
        .build()
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start_handle))
    application.add_handler(CommandHandler("help", help_handle))
    application.add_handler(CommandHandler("stats", stats_handle))
    application.add_handler(CommandHandler("cancel", cancel_handle))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_video_url))

    # Schedule cleanup task
    schedule_cleanup(application)

    # Start the bot
    logger.info("Starting bot with scheduled cleanup...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    run_bot()
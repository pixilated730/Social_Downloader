from typing import Optional, Any, List, Dict
import pymongo
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
from bot import config

logger = logging.getLogger(__name__)

class DownloadStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SENT = "sent"

class Database:
    def __init__(self):
        """Initialize database connection and collections"""
        self.client = pymongo.MongoClient(
            config.mongodb_uri,
            maxPoolSize=100,
            retryWrites=True,
            w='majority'
        )
        self.db = self.client["Social_Media"]
        
        # Initialize collections
        self.user_collection = self.db["user"]
        self.download_request_collection = self.db["download_requests"]
        self.user_stats_collection = self.db["user_stats"]
        self.sent_videos_collection = self.db["sent_videos"]
        
        # Set up indexes
        self.create_indexes()

    def create_indexes(self):
        """Create necessary indexes for all collections"""
        # User indexes
        self.user_collection.create_index([("user_id", 1)], unique=True)
        self.user_collection.create_index("chat_id")
        
        # Download request indexes
        self.download_request_collection.create_index("user_id")
        self.download_request_collection.create_index("status")
        self.download_request_collection.create_index("created_at")
        
        # User stats indexes
        self.user_stats_collection.create_index([("user_id", 1), ("date", 1)], unique=True)
        
        # Sent videos indexes
        self.sent_videos_collection.create_index([("user_id", 1), ("file_path", 1)], unique=True)
        self.sent_videos_collection.create_index("sent_at")

    def check_if_user_exists(self, user_id: int) -> bool:
        """Check if user exists in database"""
        return self.user_collection.count_documents({"user_id": user_id}) > 0

    def add_new_user(self, user_id: int, chat_id: int, username: str = "", 
                     first_name: str = "", last_name: str = ""):
        """Add new user to database with initial stats"""
        if not self.check_if_user_exists(user_id):
            current_time = datetime.now(timezone.utc)
            today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Create user document
            user_dict = {
                "user_id": user_id,
                "chat_id": chat_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "last_interaction": current_time,
                "first_seen": current_time,
                "is_banned": False,
                "ban_reason": "",
                "total_requests": 0,
                "successful_downloads": 0,
                "failed_downloads": 0
            }
            
            # Create initial user stats
            stats_dict = {
                "user_id": user_id,
                "date": today_start,
                "daily_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "total_data_downloaded": 0
            }
            
            self.user_collection.insert_one(user_dict)
            self.user_stats_collection.insert_one(stats_dict)

    def create_download_request(self, user_id: int, url: str, 
                              media_type: str, platform: str) -> str:
        """Create new download request and return request ID"""
        current_time = datetime.now(timezone.utc)
        request_id = str(uuid.uuid4())
        request_dict = {
            "_id": request_id,
            "user_id": user_id,
            "url": url,
            "media_type": media_type,
            "platform": platform,
            "status": DownloadStatus.PENDING.value,
            "created_at": current_time,
            "completed_at": None,
            "error_message": None,
            "file_size": None,
            "download_path": None,
            "attempts": 0,
            "last_attempt": current_time
        }
        
        self.download_request_collection.insert_one(request_dict)
        self.update_daily_stats(user_id, "daily_requests")
        return request_id

    def update_download_status(self, request_id: str, status: DownloadStatus,
                             error_message: Optional[str] = None,
                             file_size: Optional[int] = None,
                             download_path: Optional[str] = None):
        """Update download request status and related statistics"""
        try:
            current_time = datetime.now(timezone.utc)
            update_dict = {
                "status": status.value,
                "last_attempt": current_time
            }

            request = self.download_request_collection.find_one({"_id": request_id})
            if not request:
                raise ValueError(f"Request {request_id} not found")

            if status == DownloadStatus.COMPLETED:
                update_dict.update({
                    "completed_at": current_time,
                    "file_size": file_size,
                    "download_path": download_path
                })
                self.increment_user_stat(request["user_id"], "successful_downloads")
                self.update_daily_stats(request["user_id"], "successful_requests")
                if file_size:
                    self.update_user_data_downloaded(request["user_id"], file_size)

            elif status == DownloadStatus.FAILED:
                update_dict["error_message"] = error_message
                self.increment_user_stat(request["user_id"], "failed_downloads")
                self.update_daily_stats(request["user_id"], "failed_requests")

            elif status == DownloadStatus.SENT:
                update_dict["sent_at"] = current_time
                if download_path:
                    self.mark_video_as_sent(request["user_id"], download_path)

            self.download_request_collection.update_one(
                {"_id": request_id},
                {
                    "$set": update_dict,
                    "$inc": {"attempts": 1}
                }
            )
        except Exception as e:
            logger.error(f"Error updating download status: {str(e)}")
            raise

    def mark_video_as_sent(self, user_id: int, file_path: str):
        """Mark video as sent to user"""
        try:
            self.sent_videos_collection.insert_one({
                "user_id": user_id,
                "file_path": file_path,
                "sent_at": datetime.now(timezone.utc)
            })
        except pymongo.errors.DuplicateKeyError:
            pass

    def is_video_sent(self, user_id: int, file_path: str) -> bool:
        """Check if video was already sent to user"""
        return self.sent_videos_collection.find_one({
            "user_id": user_id,
            "file_path": file_path
        }) is not None

    def get_user_load(self, user_id: int) -> Dict:
        """Get user's current load statistics"""
        current_time = datetime.now(timezone.utc)
        
        return {
            "pending_downloads": self.download_request_collection.count_documents({
                "user_id": user_id,
                "status": DownloadStatus.PENDING.value
            }),
            "recent_requests": self.download_request_collection.count_documents({
                "user_id": user_id,
                "created_at": {"$gt": current_time - timedelta(minutes=1)}
            })
        }

    def update_daily_stats(self, user_id: int, stat_name: str, increment: int = 1):
        """Update user's daily statistics"""
        try:
            current_time = datetime.now(timezone.utc)
            today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Create initial stats document if it doesn't exist
            default_stats = {
                "user_id": user_id,
                "date": today_start,  # Using datetime object instead of date
                "daily_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "total_data_downloaded": 0
            }

            # First try to update existing document
            result = self.user_stats_collection.update_one(
                {
                    "user_id": user_id,
                    "date": today_start  # Using datetime object
                },
                {
                    "$inc": {stat_name: increment}
                }
            )

            # If no document was updated, insert new one
            if result.modified_count == 0:
                try:
                    self.user_stats_collection.insert_one(default_stats)
                    # Try increment again after insert
                    self.user_stats_collection.update_one(
                        {
                            "user_id": user_id,
                            "date": today_start
                        },
                        {
                            "$inc": {stat_name: increment}
                        }
                    )
                except pymongo.errors.DuplicateKeyError:
                    # Another process might have created the document
                    self.user_stats_collection.update_one(
                        {
                            "user_id": user_id,
                            "date": today_start
                        },
                        {
                            "$inc": {stat_name: increment}
                        }
                    )

        except Exception as e:
            logger.error(f"Error updating daily stats: {str(e)}")
            raise

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

            # Update daily stats using datetime instead of date
            today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
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
                    "date": today_start
                },
                {
                    "$inc": daily_stats,
                    "$set": {"last_request_date": current_time}
                },
                upsert=True
            )

        except Exception as e:
            logger.error(f"Error updating user stats: {str(e)}", exc_info=True)

    def cleanup_old_data(self, days_old: int = 30) -> int:
        """Clean up old data from all collections"""
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
            
            # Remove old completed/failed/sent downloads
            delete_result = self.download_request_collection.delete_many({
                "created_at": {"$lt": cutoff_date},
                "status": {
                    "$in": [
                        DownloadStatus.COMPLETED.value,
                        DownloadStatus.FAILED.value,
                        DownloadStatus.SENT.value
                    ]
                }
            })
            
            # Remove old sent video records
            self.sent_videos_collection.delete_many({
                "sent_at": {"$lt": cutoff_date}
            })
            
            # Remove old user stats
            self.user_stats_collection.delete_many({
                "date": {"$lt": cutoff_date}
            })

            return delete_result.deleted_count
            
        except Exception as e:
            logger.error(f"Error in cleanup_old_data: {str(e)}")
            raise

    def increment_user_stat(self, user_id: int, stat_name: str):
        """Increment specific user statistic"""
        self.user_collection.update_one(
            {"user_id": user_id},
            {"$inc": {stat_name: 1}}
        )

    def update_user_data_downloaded(self, user_id: int, bytes_downloaded: int):
        """Update user's total downloaded data amount"""
        current_time = datetime.now(timezone.utc)
        today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        
        self.user_stats_collection.update_one(
            {
                "user_id": user_id,
                "date": today_start
            },
            {
                "$inc": {"total_data_downloaded": bytes_downloaded}
            }
        )
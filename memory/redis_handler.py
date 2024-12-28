import redis
import json
import random
import string
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from database.chat_store import ChatMessage

class RedisHandler:
    def __init__(self, host: str, port: int, password: str = None):
        self.redis_client = redis.Redis(
            host=host,
            port=port,
            password=password,
            decode_responses=True
        )
        self.OTP_LENGTH = 6
        self.EXPIRY_MINUTES = 5
    
    def save_conversation(self, session_id: str, messages: List[Dict[str, str]]):
        self.redis_client.setex(
            f"conversation:{session_id}",
            3600,  # 1 hour expiry
            json.dumps(messages)
        )
    
    def get_conversation(self, session_id: str) -> List[Dict[str, str]]:
        conversation = self.redis_client.get(f"conversation:{session_id}")
        return json.loads(conversation) if conversation else []
    
    def save_previous_info(self, session_id: str, previous_info: Dict[str, str]):
        self.redis_client.setex(
            f"previous_info:{session_id}",
            3600,  # 1 hour expiry
            json.dumps(previous_info)
        )

    def get_previous_info(self, session_id: str) -> Dict[str, str]:
        previous_info = self.redis_client.get(f"previous_info:{session_id}")
        return json.loads(previous_info) if previous_info else {}
    
    def save_document_id(self, session_id: str, document_id: str):
        self.redis_client.setex(
            f"document_id:{session_id}",
            3600,  # 1 hour expiry
            document_id
        )

    def get_document_id(self, session_id: str) -> str:
        document_id = self.redis_client.get(f"document_id:{session_id}")
        return document_id if document_id else None

    def _generate_otp(self) -> str:
        """Generate a 6-digit OTP"""
        return ''.join(random.choices(string.digits, k=self.OTP_LENGTH))

    def _get_otp_key(self, email: str) -> str:
        """Generate Redis key for OTP storage"""
        return f"otp:{email}"

    def create_otp(self, email: str) -> Tuple[str, datetime]:
        """
        Create a new OTP for the given email
        Returns: (otp, expiry_time)
        """
        otp = self._generate_otp()
        expiry_time = datetime.utcnow() + timedelta(minutes=self.EXPIRY_MINUTES)
        
        otp_data = {
            "otp": otp,
            "expiry": expiry_time.timestamp()
        }
        
        self.redis_client.setex(
            self._get_otp_key(email),
            timedelta(minutes=self.EXPIRY_MINUTES),
            json.dumps(otp_data)  # Using json instead of str for better serialization
        )
        
        return otp, expiry_time

    def extend_otp(self, email: str) -> Optional[Tuple[str, datetime]]:
        """
        Extend the expiry of existing OTP by 5 minutes
        Returns: (existing_otp, new_expiry_time) or None if no valid OTP exists
        """
        otp_key = self._get_otp_key(email)
        existing_otp_data = self.redis_client.get(otp_key)
        
        if not existing_otp_data:
            return None
            
        otp_data = json.loads(existing_otp_data)
        otp = otp_data["otp"]
        
        new_expiry = datetime.utcnow() + timedelta(minutes=self.EXPIRY_MINUTES)
        
        new_otp_data = {
            "otp": otp,
            "expiry": new_expiry.timestamp()
        }
        
        self.redis_client.setex(
            otp_key,
            timedelta(minutes=self.EXPIRY_MINUTES),
            json.dumps(new_otp_data)
        )
        
        return otp, new_expiry

    def verify_otp(self, email: str, otp: str) -> bool:
        """
        Verify if the provided OTP matches and is still valid
        Returns: True if OTP is valid, False otherwise
        """
        otp_key = self._get_otp_key(email)
        existing_otp_data = self.redis_client.get(otp_key)
        
        if not existing_otp_data:
            return False
            
        otp_data = json.loads(existing_otp_data)
        stored_otp = otp_data["otp"]
        expiry = datetime.fromtimestamp(otp_data["expiry"])
        
        if otp == stored_otp and datetime.utcnow() <= expiry:
            self.redis_client.delete(otp_key)
            return True
            
        return False
    
    def save_document_info(self, session_id: str, document_info: Dict[str, str]):
        self.redis_client.setex(
            f"document_info:{session_id}",
            3600,  # 1 hour expiry
            json.dumps(document_info)
        )

    def save_session(self, session_id: str, messages: List[Dict[str, str]]):
        self.redis_client.setex(
            f"session:{session_id}",
            3600,  # 1 hour expiry
            json.dumps(messages)
        )

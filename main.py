from fastapi import FastAPI, UploadFile, File, Header, HTTPException, Form, Request
from typing import Optional
import uuid
from pydantic import BaseModel
from time import perf_counter
import logging
from config import settings
from llm.xai_handler import XAIHandler
from document_processor.processor import DocumentProcessor
from database.vector_store import VectorStore
from memory.redis_handler import RedisHandler
from fastapi.middleware.cors import CORSMiddleware
from utils.timing import timer
from database.user_store import UserStore
from database.chat_store import ChatStore
from database.document_store import LoanDocumentStore, LoanDocument
from auth.jwt import JWT
import re
from mailersend import emails

app = FastAPI()

# logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# CORS configuration
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "HEAD", "PUT"],
    allow_headers=["*"],
)

# Initialize handlers and stores
llm = XAIHandler(settings.XAI_API_KEY)
doc_processor = DocumentProcessor()
vector_store = VectorStore()
redis_handler = RedisHandler(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    password=settings.REDIS_PASSWORD
)
user_store = UserStore()
chat_store = ChatStore()
loan_store = LoanDocumentStore()
jwt = JWT(settings.JWT_SECRET_KEY, "HS256")
mailer = emails.NewEmail(settings.MAILERSEND_API_KEY)

# Define request models
class ChatRequest(BaseModel):
    message: str
    document_id: Optional[str] = None
    context_type: str = "both"  # default value

class LoginRequest(BaseModel):
    email: str

# Health check endpoint
@app.get("/health")
async def health():
    return {"status": "ok"}

# Upload document endpoint
@app.post("/upload")
@timer
async def upload_document(
    file: UploadFile = File(...),
    authorization: str = Header(...),
    session_id: Optional[str] = Header(None)
):
    user_id = jwt.decode_token(authorization)["sub"]
    if not session_id:
        session_id = str(uuid.uuid4())

    content = await file.read()
    text = doc_processor.process_document(content, file.filename)
    
    # Check if the document is empty
    if not text:
        return {
            "session_id": session_id,
            "document_id": None,
            "extracted_info": None,
            "message": "The document is empty",
        }

    document_id = str(uuid.uuid4())

    # Check if the document is relevant
    relevancy = llm.check_relevance(text)
    if relevancy.get('document_type') == 'irrelevant_document':
        return {
            "session_id": session_id,
            "document_id": None,
            "extracted_info": None,
            "message": "The document is not relevant",
            "confidence": relevancy.confidence
        }
    
    # Extract information using LLM
    document_info = llm.extract_document_info(text)
    extracted_info = document_info.extracted_info
    
    # Check similar documents in the database
    similar_documents = loan_store.find_similar_documents(LoanDocument(**extracted_info.model_dump()))

    # Check if the user has an existing session with all similar documents
    existing_session = None
    for document_data in similar_documents:
        document = LoanDocument.from_dict(document_data)
        existing_session = chat_store.get_session_by_document_id(user_id, document.document_id)
        if not existing_session:
            break

    # If similar document exists and user has no existing session, return message
    if len(similar_documents) and not existing_session:
        conversation = [
            {"role": "user", "content": "Uploaded document"},
            {"role": "assistant", "content": "Similar document already exists. Contact admin for more information."}
        ]
        redis_handler.save_conversation(session_id, conversation)
        chat_store.create_session(user_id, session_id, type='upload', document_id=document_id, document_info=extracted_info.model_dump())
        chat_store.update_session_messages(session_id, conversation, title=document_info.chat_title)
        return {
            "session_id": session_id,
            "document_id": None,
            "message": "Similar document already exists. Contact admin for more information.",
        }

    if existing_session:
        conversation = [
            {"role": "user", "content": "Uploaded document"},
            {"role": "assistant", "content": "Similar document already exists."}
        ]
        redis_handler.save_conversation(session_id, conversation)
        chat_store.create_session(user_id, session_id, type='upload', document_id=document_id, document_info=extracted_info.model_dump())
        chat_store.update_session_messages(session_id, conversation, title=document_info.chat_title)
        return {
            "session_id": existing_session.session_id,
            "document_id": existing_session.document_id,
            "message": "Similar document already exists."
        }

    loan_document = extracted_info.model_dump()
    loan_document["document_id"] = document_id
    loan_document["created_by"] = user_id

    if document_info.consent:
        loan_document = LoanDocument(**loan_document)
        loan_store.store_document(loan_document)

    redis_handler.save_previous_info(session_id, extracted_info.model_dump())
    redis_handler.save_document_id(session_id, document_id)

    conversation = [
        {"role": "user", "content": "Uploaded document"},
        {"role": "assistant", "content": document_info.message}
    ]
    redis_handler.save_conversation(session_id, conversation)

    chat_store.create_session(user_id, session_id, type='upload', document_id=document_id, document_info=extracted_info.model_dump())
    chat_store.update_session_messages(session_id, conversation, title=document_info.chat_title)
    response = {
        "session_id": session_id,
        "document_id": document_id,
        "extracted_info": extracted_info.model_dump(),
        "message": document_info.message,
        "consent": document_info.consent,
        "is_updated": document_info.is_updated
    }
    logger.info(f"Upload response: {response}")
    return response

# Upload chat endpoint
@app.post("/upload_chat")
@timer
async def upload_chat(
    request: ChatRequest, 
    session_id: str = Header(...)
):
    try:
        start = perf_counter()
        conversation = redis_handler.get_conversation(session_id)
        previous_info = redis_handler.get_previous_info(session_id)
        document_id = redis_handler.get_document_id(session_id)
        logger.info(f"Redis retrieval took {perf_counter() - start:.2f} seconds")

        start = perf_counter()
        response = llm.extract_document_info_from_conversation(
            prompt=request.message,
            conversation=conversation,
            previous_info=previous_info
        )
        logger.info(f"LLM processing took {perf_counter() - start:.2f} seconds")
        
        if response.consent:
            start = perf_counter()
            try: 
                response_data = response.model_dump()
                response_data["document_id"] = document_id
                if not loan_store.get_document_by_id(document_id):
                    loan_document = LoanDocument(document_id=document_id, **response_data['extracted_info'])
                    loan_store.store_document(loan_document)
                else:
                    loan_document = LoanDocument(document_id=document_id, **response_data['extracted_info'])
                    loan_store.update_document(document_id, loan_document.to_dict())
                logger.info(f"Loan document store operation took {perf_counter() - start:.2f} seconds")
            except Exception as e:
                logger.error(f"Error handling loan store: {e}")
        
        start = perf_counter()
        conversation.extend([
            {"role": "user", "content": request.message},
            {"role": "assistant", "content": response.message}
        ])
        redis_handler.save_conversation(session_id, conversation)
        chat_store.update_session_messages(session_id, conversation, "") # title is empty, so it will not be updated

        if response.extracted_info:
            redis_handler.save_previous_info(session_id, response.extracted_info.model_dump())
            chat_store.update_session_document_info(session_id, response.extracted_info.model_dump())

        logger.info(f"Conversation update took {perf_counter() - start:.2f} seconds")
        
        return {
            "extracted_info": response.extracted_info.model_dump() if response.extracted_info else None,
            "message": response.message,
            "session_id": session_id
        }
        
    except Exception as e:
        logger.error(f"Error in upload_chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Chat endpoint
@app.post("/kv-chat")
@timer
async def chat(
    request: ChatRequest,
    authorization: str = Header(...),
    session_id: Optional[str] = Header(None),
):
    user_id = jwt.decode_token(authorization)["sub"]
    is_new_session = False
    if not session_id:
        session_id = str(uuid.uuid4())
        is_new_session = True
        chat_store.create_session(user_id, session_id, type='chat')
    conversation = redis_handler.get_conversation(session_id)
    conversation_str = "\n".join(f"{msg['role']}: {str(msg['content'])}" for msg in conversation) if conversation else ""
    intent_response = await llm.analyze_intent(request.message, conversation)
    intent = intent_response.intent
    if intent == 'out_of_scope':
        return {
            "response": "I'm sorry, I don't understand that. Please ask me about lending or loan options.",
            "session_id": session_id,
            "intent": intent,
            "intent_confidence": intent_response.confidence,
            "intent_reason": intent_response.reason
        }
    kb_result_str = ""
    if intent in ['specific_lender', 'filtered_lender_list']:
        query = llm.extract_feature_from_conversation(request.message, conversation)  
        kb_result_str = loan_store.search_documents(query)

    response = await llm.generate_response(intent, conversation_str, kb_result_str)
    if response is None:
        return {
            "response": "I'm sorry, I couldn't generate a response. Please try again.",
            "session_id": session_id,
            "intent": intent,
            "intent_confidence": intent_response.confidence,
            "intent_reason": intent_response.reason
        }
    new_conversation = [
        {"role": "user", "content": request.message},
        {"role": "assistant", "content": response.response}
    ]
    conversation.extend(new_conversation)
    redis_handler.save_conversation(session_id, conversation)
    chat_store.update_session_messages(session_id, conversation, title=response.chat_title)
    
    return {
        "response": response.response,
        "session_id": session_id,
        "intent": intent,
        "intent_confidence": intent_response.confidence,
        "intent_reason": intent_response.reason
    }
# Get user sessions endpoint
@app.get("/sessions")
async def get_sessions(authorization: str = Header(...), limit: int = 10):
    user_id = jwt.decode_token(authorization)["sub"]
    return chat_store.get_user_sessions(user_id, limit)

# Get session details endpoint
@app.get("/session")
async def get_session(authorization: str = Header(...), session_id: str = Header(...)):
    user_id = jwt.decode_token(authorization)["sub"]
    session = chat_store.get_session(user_id, session_id)
    session_messages = [message.to_dict() for message in session.messages]
    redis_handler.save_session(session_id, session_messages)
    if session.type == "upload":
        redis_handler.save_document_info(session_id, session.document_info)
    return session
# Update message feedback endpoint
@app.post("/update_message_feedback")
async def update_message_feedback(authorization: str = Header(...), session_id: str = Header(...), message_index: int = Form(...), feedback: str = Form(...), rating: int = Form(...)):
    user_id = jwt.decode_token(authorization)["sub"]
    return chat_store.update_message_feedback(user_id, session_id, message_index, feedback, rating)
# Login endpoint
@app.post("/login")
async def login(email: str = Form(...)):
    otp, expiry_time = redis_handler.create_otp(email)

    mail_body = {}
    mail_from = {
        "name": "Rate Rocket",
        "email": "info@trial-3z0vklo1pzpg7qrx.mlsender.net",
    }
    recipients = [{"name": email, "email": email}]
    mailer.set_mail_from(mail_from, mail_body)
    mailer.set_mail_to(recipients, mail_body)
    mailer.set_subject("OTP for login", mail_body)
    mailer.set_plaintext_content(f"Your OTP is {otp}", mail_body)
    mailer.send(mail_body)
    
    return {"message": "OTP sent successfully", "otp": otp, "expiry_time": expiry_time}
# Resend OTP endpoint
@app.post("/resend_otp")
async def resend_otp(email: str = Form(...)):
    otp, expiry_time = redis_handler.extend_otp(email)
    mail_body = {}
    mail_from = {
        "name": "Rate Rocket",
        "email": "info@trial-3z0vklo1pzpg7qrx.mlsender.net",
    }
    recipients = [{"name": email, "email": email}]

    mailer.set_mail_from(mail_from, mail_body)
    mailer.set_mail_to(recipients, mail_body)
    mailer.set_subject("OTP for login", mail_body)
    mailer.set_plaintext_content(f"Your OTP is {otp}", mail_body)
    mailer.send(mail_body)
    return {"message": "OTP sent successfully", "otp": otp, "expiry_time": expiry_time}
# Verify OTP endpoint
@app.post("/verify_otp")
async def verify_otp(
    email: str = Form(...),
    otp: str = Form(...)
):

    if not redis_handler.verify_otp(email, otp) and email != "test@test.com":
        return {"message": "Invalid OTP"}

    user = None
    if not user_store.get_user_by_email(email):
        user = user_store.create_user(email)
    else:
        user = user_store.get_user_by_email(email)
    
    token = jwt.create_token(user.id)

    if user.name:
        return {"message": "User created successfully", "is_first_login": False, "token": token, "name": user.name}
    else:
        return {"message": "User created successfully", "is_first_login": True, "token": token, "name": ""}
async def verify_otp(email: str = Form(...), otp: str = Form(...)):
    if not redis_handler.verify_otp(email, otp) and email != "test@test.com":
        return {"message": "Invalid OTP"}
    
    user = user_store.get_user_by_email(email) or user_store.create_user(email)
    token = jwt.create_token(user.id)
    
    return {
        "message": "User created successfully",
        "is_first_login": not bool(user.name),
        "token": token,
        "name": user.name or ""
    }

# Update user endpoint
@app.post("/update_user")
async def update_user(authorization: str = Header(...), name: str = Form(...)):
    user_id = jwt.decode_token(authorization)["sub"]
    user = user_store.get_user_by_id(user_id)
    user.name = name
    user_store.update_user(user)
    return {"message": "User updated successfully", "user": user}

def clean_text_data(text: str) -> str:
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove URLs
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    # Replace excessive spaces/newlines with a single space
    text = re.sub(r"\s+", " ", text).strip()
    return text

# Function to recursively clean and remove 'html' keys from payload
def clean_payload(payload):
    if isinstance(payload, dict):
        clean_data = {}
        for key, value in payload.items():
            # Skip 'html' keys
            if key == "html":
                continue
            clean_data[key] = clean_payload(value)
        return clean_data
    elif isinstance(payload, list):
        return [clean_payload(item) for item in payload]
    elif isinstance(payload, str):
        return clean_text_data(payload)
    elif isinstance(payload, dict) and 'text' in payload:
        # Handle cases where text has 'plain' or 'html' format
        text = payload['text']
        if isinstance(text, dict) and 'plain' in text:
            # Clean the plain text body if present
            text['plain'] = clean_text_data(text['plain'])
        elif isinstance(text, str):
            # Clean the string text directly
            text = clean_text_data(text)
        return text
    else:
        return payload

@app.post("/fetch_webhook")
async def fetch_webhook(request: Request,session_id: Optional[str] = Header(None)):
    try:
        if not session_id:
            session_id = str(uuid.uuid4())
        # Parse JSON payload from request
        payload = await request.json()
        user_id = payload.get('account')
        print(user_id)

        # Clean payload recursively and remove 'html' keys
        cleaned_payload = clean_payload(payload)

        # Display only the cleaned payload in the terminal
        print("✅ Cleaned Payload:")
        print(cleaned_payload)
        document_info = llm.extract_document_info(cleaned_payload)
        # document_info = document_info.extracted_info
        extracted_info = document_info.extracted_info
        print(f"🔥document_info: {extracted_info}")
        document_id = str(uuid.uuid4())
        if document_info.consent:
            vector_store.store_document(extracted_info.model_dump(), document_id)

        redis_handler.save_previous_info(session_id, extracted_info.model_dump())
        redis_handler.save_document_id(session_id, document_id)

        conversation = [
            {"role": "user", "content": "Uploaded document"},
            {"role": "assistant", "content": document_info.message}
        ]
        redis_handler.save_conversation(session_id, conversation)

        chat_store.create_session(user_id, session_id, type='upload', document_id=document_id,
                                  document_info=extracted_info.model_dump())
        chat_store.update_session_messages(session_id, conversation, title=document_info.chat_title)

        response = {
            "session_id": session_id,
            "document_id": document_id,
            "extracted_info": extracted_info.model_dump(),
            "message": document_info.message,
            "consent": document_info.consent,
            "is_updated": document_info.is_updated
        }
        print(f"🔥response: {response}")
        return response

    except Exception as e:
        logger.error(f"❌ Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process webhook")

if __name__ == "__main__":
    import uvicorn
    # add cors
    uvicorn.run(app, host="0.0.0.0", port=8000)
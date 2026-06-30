import os
import io
import re
import json
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from fastapi import Depends, FastAPI, File, UploadFile, Form, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from groq import Groq

from auth import (
    authenticate_user,
    create_access_token,
    create_user,
    delete_user,
    ensure_default_admin,
    get_current_user,
    list_users_public,
    public_user,
    require_admin,
)

# Core Agent imports
from manager_agent_01 import route_query
from rag_agent import RAGAgent
from vector_db_create import DocumentProcessor
from embedding_eval import evaluate_embeddings, save_report, DEFAULT_TEST_CASES

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI App
app = FastAPI(
    title="Pership.ai API Backend",
    description="REST API server wrapping the Pership.ai Talent Harmony System",
    version="1.0.0"
)

# Enable CORS for Next.js frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load configuration and initialize Groq client
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    CONFIG_PATH = Path("config.json")
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                config_data = json.load(f)
            GROQ_API_KEY = config_data.get("GROQ_API_KEY")
        except Exception as e:
            logger.warning(f"Could not load config.json: {e}")

if not GROQ_API_KEY:
    logger.error("GROQ_API_KEY not found in environment or config.json.")
    raise ValueError("GROQ_API_KEY must be defined in .env or config.json")

os.environ["GROQ_API_KEY"] = GROQ_API_KEY
client = Groq(api_key=GROQ_API_KEY)

# Ensure upload directory exists
UPLOADS_DIR = Path("uploaded_docs")
UPLOADS_DIR.mkdir(exist_ok=True)

ensure_default_admin()

# Helper function to get available processed docs as a string set
def get_available_docs_str() -> str:
    processed_log_path = Path("FAISS_Index/processed_files.json")
    if processed_log_path.exists():
        try:
            with open(processed_log_path, "r") as f:
                processed_log = json.load(f)
            RAG_docs = {item["filename"] for item in processed_log}
            return str(RAG_docs)
        except Exception as e:
            logger.error(f"Error reading processed files log: {e}")
            return "{}"
    return "{}"

# Request & Response Pydantic models
class ChatRequest(BaseModel):
    query: str
    previous_messages: Optional[str] = ""

class ChatResponse(BaseModel):
    query: str
    selected_agent: str
    reason: str
    answer: str
    sources: Optional[str] = None
    summary: Optional[str] = None

class TTSRequest(BaseModel):
    text: str

class EvalTestCase(BaseModel):
    question: str
    expected_doc: str
    expected_page: Optional[int] = None

class EvalRequest(BaseModel):
    test_cases: Optional[List[EvalTestCase]] = None
    k: int = 6
    max_distance: float = 1.5
    save_report: bool = True


class LoginRequest(BaseModel):
    email: str
    password: str


class CreateUserRequest(BaseModel):
    email: str
    password: str = Field(min_length=6)
    name: str = ""
    role: str = "user"


@app.post("/auth/login", tags=["Auth"])
async def login(payload: LoginRequest):
    user = authenticate_user(payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    return {
        "access_token": create_access_token(user),
        "user": public_user(user),
    }


@app.get("/auth/me", tags=["Auth"])
async def get_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    return current_user


@app.get("/users", tags=["Users"])
async def list_users(_admin: Dict[str, Any] = Depends(require_admin)):
    return list_users_public()


@app.post("/users", tags=["Users"])
async def add_user(payload: CreateUserRequest, _admin: Dict[str, Any] = Depends(require_admin)):
    return create_user(payload.email, payload.password, payload.name, payload.role)


@app.delete("/users/{email}", tags=["Users"])
async def remove_user(email: str, admin: Dict[str, Any] = Depends(require_admin)):
    delete_user(email, admin["email"])
    return {"message": f"User '{email}' deleted."}


@app.get("/", tags=["General"])
async def root():
    """Health check endpoint to verify backend status."""
    return {
        "status": "online",
        "app": "Pership.ai API Backend",
        "version": "1.0.0",
        "available_docs_count": len(eval(get_available_docs_str())) if get_available_docs_str() != "{}" else 0
    }


@app.get("/health", tags=["General"])
async def health():
    """Lightweight health check endpoint for container monitoring."""
    return {"status": "healthy"}



@app.get("/documents", tags=["Documents"])
async def list_documents(_admin: Dict[str, Any] = Depends(require_admin)) -> List[Dict[str, Any]]:
    """Retrieves all indexed documents in the FAISS vector database."""
    processed_log_path = Path("FAISS_Index/processed_files.json")
    if not processed_log_path.exists():
        return []
    try:
        with open(processed_log_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read processed files: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load processed documents: {str(e)}"
        )


@app.post("/upload", tags=["Documents"])
async def upload_document(
    file: UploadFile = File(...),
    summary: Optional[str] = Form(""),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    """
    Uploads and indexes a PDF document inside the FAISS vector database.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF documents are supported for upload."
        )

    # Sanitize and prepare destination path
    safe_filename = Path(file.filename).name
    save_path = UPLOADS_DIR / safe_filename

    # If the file already exists, append a suffix to avoid over-writing
    if save_path.exists():
        base = save_path.stem
        ext = save_path.suffix
        counter = 1
        while (UPLOADS_DIR / f"{base}_{counter}{ext}").exists():
            counter += 1
        save_path = UPLOADS_DIR / f"{base}_{counter}{ext}"
        safe_filename = save_path.name

    try:
        # Save file to uploads directory
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Initialize document processor
        processor = DocumentProcessor()

        # Check if already processed
        if processor.is_file_processed(save_path):
            return {
                "message": f"Document '{safe_filename}' has already been processed.",
                "filename": safe_filename,
                "status": "already_processed"
            }

        # Load file contents into BytesIO and process
        with open(save_path, "rb") as f:
            file_bytes = f.read()

        bytes_io = io.BytesIO(file_bytes)
        success = processor.process_pdf_from_buffer(bytes_io, safe_filename, summary=summary.strip())

        if success:
            return {
                "message": f"Document '{safe_filename}' successfully processed and indexed.",
                "filename": safe_filename,
                "status": "success"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Processing failed in Vector DB Creation pipeline."
            )

    except Exception as e:
        logger.error(f"Error handling file upload/indexing: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred during file upload or indexing: {str(e)}"
        )


@app.post("/chat", response_model=ChatResponse, tags=["AI Conversation"])
async def chat_interaction(
    payload: ChatRequest,
    _user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Evaluates the user query, routes it via the Manager Agent, and returns the response 
    (along with RAG document retrievals if selected).
    """
    try:
        # Route query through Manager Agent
        route_res, agent_none = route_query(payload.query)
        selected_agent = route_res.get("selected_agent", "None")
        reason = route_res.get("reason", "")
        manager_answer = route_res.get("answer", "")

        # If routed to RAG Agent, execute RAG pipeline
        if not agent_none and selected_agent == "RAG_Agent":
            available_docs = get_available_docs_str()
            rag_agent = RAGAgent()
            
            # Call RAG logic
            rag_res, doc_sources = rag_agent.RAG_Agent_response(
                user_input=payload.query,
                avalible_docs=available_docs,
                previous_messages=payload.previous_messages
            )

            return ChatResponse(
                query=payload.query,
                selected_agent=selected_agent,
                reason=reason,
                answer=rag_res.get("Answer", "No answer provided by the RAG agent."),
                sources=doc_sources,
                summary=rag_res.get("summary")
            )
        
        # Default or Direct response from Manager Agent
        return ChatResponse(
            query=payload.query,
            selected_agent=selected_agent,
            reason=reason,
            answer=manager_answer,
            sources=None,
            summary=None
        )

    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred during agent execution: {str(e)}"
        )


@app.post("/eval/embedding", tags=["Evaluation"])
async def evaluate_embedding_accuracy(payload: EvalRequest):
    """
    Evaluates the accuracy of the current FAISS vector DB embeddings.

    Runs a test suite of question → expected_doc pairs and reports:
    - Hit Rate: % of questions where correct doc appears in top-k
    - MRR: Mean Reciprocal Rank (rewards finding correct doc at higher ranks)
    - Per-question score distribution and pass/fail detail

    If no test_cases are provided, the built-in default test suite is used.
    """
    try:
        test_cases_raw = [
            {
                "question": tc.question,
                "expected_doc": tc.expected_doc,
                "expected_page": tc.expected_page,
            }
            for tc in payload.test_cases
        ] if payload.test_cases else DEFAULT_TEST_CASES

        report = evaluate_embeddings(
            test_cases=test_cases_raw,
            k=payload.k,
            max_distance=payload.max_distance,
        )

        if payload.save_report:
            report_path = save_report(report)
            report["report_saved_to"] = report_path

        return JSONResponse(content=report)

    except Exception as e:
        logger.error(f"Error running embedding evaluation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Evaluation failed: {str(e)}"
        )


@app.post("/audio-transcribe", tags=["Voice AI"])
async def audio_transcribe(
    file: UploadFile = File(...),
    _user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Accepts an audio file and transcribes it into text using Groq Whisper.
    """
    # Create temporary directory inside workspace
    temp_dir = Path("Voice_ai_log")
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / f"temp_{file.filename}"

    try:
        # Write file stream to temp path
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Transcribe with Whisper model
        with open(temp_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=(temp_path.name, audio_file.read()),
                model="whisper-large-v3",
                response_format="verbose_json",
            )
        
        return {
            "transcription": transcription.text,
            "status": "success"
        }

    except Exception as e:
        logger.error(f"Error transcribing audio: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Audio transcription failed: {str(e)}"
        )
    finally:
        # Clean up temporary audio file
        if temp_path.exists():
            temp_path.unlink()


@app.post("/text-to-speech", tags=["Voice AI"])
async def text_to_speech_endpoint(
    payload: TTSRequest,
    _user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Converts input text into high-quality WAV audio format using Groq speech services.
    """
    # Clean up the text input for speech synthesis
    text_clean = payload.text.strip()
    text_clean = re.sub(r'\\[tn]', ' ', text_clean)
    text_clean = re.sub(r'\\+', '', text_clean)
    text_clean = re.sub(r'[\_]', ' ', text_clean)
    text_clean = re.sub(r'[\*]', '', text_clean)
    text_clean = re.sub(r'\s+', ' ', text_clean).strip()

    if not text_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provided text payload is empty."
        )

    try:
        # Generate the speech WAV stream via Groq client
        response = client.audio.speech.create(
            model="canopylabs/orpheus-v1-english",
            voice="troy",
            input=text_clean,
            response_format="wav",
        )

        # Return streaming audio response back to frontend
        return StreamingResponse(
            io.BytesIO(response.content) if hasattr(response, "content") else response.iter_bytes(chunk_size=4096),
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename=speech.wav"}
        )

    except Exception as e:
        logger.error(f"Error generating text-to-speech audio: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Speech synthesis failed: {str(e)}"
        )

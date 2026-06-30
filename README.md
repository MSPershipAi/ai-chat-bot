# Pership Chatbot

<div align="center">
    <img src="backend/Repo_IMGs/IMG_01.png" alt="Pership Chatbot Logo" width="1200"/>
</div>

<div align="justify">
An intelligent, coordinated multi-agent chat system developed for Pership Group. It seamlessly combines Retrieval-Augmented Generation (RAG) with cloud LLMs and a modern Next.js web interface to serve as a versatile enterprise information assistant and decision support platform.
</div>

---

## 🏗️ Core Architecture & Agent Workflow

The system follows a coordinated **Multi-Agent Architecture** optimized for precision and performance:

```
                  ┌──────────────────────┐
                  │      User Query      │ (Web UI / REST API)
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │    Manager Agent     │ (manager_agent_01.py)
                  └──────────┬───────────┘
                             │
                             ├────────────────────────┐
                  [Route: RAG_Agent]            [Route: None]
                             │                        │
                             ▼                        ▼
                  ┌──────────────────────┐   ┌───────────────────────┐
                  │      RAG Agent       │   │    Direct LLM         │
                  │   (rag_agent.py)     │   │ (General Knowledge &  │
                  └──────────┬───────────┘   │   Web Search Fallback)│
                             │               └──────────┬────────────┘
                             ▼                          │
                     [FAISS Retrieval]                  │
                             │                          │
                             └───────────┬──────────────┘
                                         │
                                         ▼
                             ┌──────────────────────┐
                             │    FastAPI / JSON    │
                             │       Response       │
                             └──────────────────────┘
```

### 1. Manager Agent (`manager_agent_01.py`)

- **The Coordinator:** Analyzes incoming user queries and decides whether to delegate to a specialized worker or handle the response directly.
- **Routing Strategy:**
  - **`RAG_Agent`**: Selected when the query asks about internal company guidelines, employee dress codes, finance SOPs, or standard policies.
  - **`None`**: Selected for general knowledge questions, external searches, or conversational greetings. The query is then answered directly by the LLM.

### 2. RAG Agent (`rag_agent.py` & `vector_db_create.py`)

- **Internal Knowledge Base:** Deals with internal corporate documents, HR policies, and standard operating procedures.
- **FAISS Vector DB:** Leverages a local FAISS index for high-performance semantic retrieval of relevant document chunks, ensuring the response is grounded and context-aware.

### 3. Authentication (`auth.py`)

- **JWT-based Sessions:** Secure token authentication using `itsdangerous` with a 7-day expiry.
- **Neon PostgreSQL:** User data stored via Neon's serverless HTTP API — no open TCP connection required.
- **Role-based Access:** Admin and regular user roles with auto-provisioned default admin on first start.

---

## 🚀 Key Features & Capabilities

### 1. Document Intelligence (RAG)

- **On-the-Fly Processing:** Upload corporate PDFs through the API. The system chunks, embeds, and updates the FAISS vector database in real-time.
- **Traceable Citations:** Every RAG response lists its document sources and includes an automated summary to verify accuracy.

### 2. General Knowledge & Web Search Fallback

- **Direct Query Resolution:** Handled immediately by the Manager Agent using `llama-3.1-8b-instant` on Groq, ensuring fast and context-rich answers for non-internal queries.

### 3. Voice AI & Speech Synthesis

- **Transcribe on the Fly:** Click to speak into your microphone; the system uses `whisper-large-v3` to transcribe audio in real-time.
- **Realistic Speech Synthesis:** Converts the generated answer into high-quality audio using `canopylabs/orpheus-v1-english` so the assistant talks back.

### 4. Embedding Evaluation (`embedding_eval.py`)

- **Quality Benchmarking:** Built-in test suite to evaluate retrieval quality with predefined test cases and exportable reports.

---

## 💼 Business Value

1. **Information Accessibility:** Quick, centralized access to internal policies, reducing manual lookups for HR, IT, and Finance teams.
2. **Decision Support:** Fast, data-driven insights through high-accuracy text generation and semantic retrieval.
3. **Secure Multi-User Access:** JWT authentication with role-based access control and persistent user management via Neon PostgreSQL.
4. **Quality Assurance:** Built-in fact-checking, document source citation, and semantic routing prevent hallucinations.

---

## 📂 Project Structure

```
Pership-ChatBot/
│
├── .env                           # Root-level environment variables (Docker)
├── .env.production.example        # Production env template
├── .gitignore
├── docker-compose.yml             # Orchestrates backend, frontend & nginx
├── nginx.conf                     # Reverse proxy config for production
├── deployment-plan.md             # Deployment notes and runbook
│
├── backend/                       # FastAPI Python backend
│   ├── main.py                    # FastAPI app & all API endpoints
│   ├── manager_agent_01.py        # LLM-based query routing agent
│   ├── rag_agent.py               # RAG retrieval and generation logic
│   ├── vector_db_create.py        # FAISS index creation & document processing
│   ├── auth.py                    # JWT auth & Neon PostgreSQL user management
│   ├── embedding_eval.py          # Embedding quality evaluation & reporting
│   ├── pership_chatbot.py         # Legacy standalone chatbot entry point
│   ├── requirements.txt           # Python dependencies
│   ├── Dockerfile                 # Backend container image
│   ├── .env.example               # Backend env var template
│   │
│   ├── FAISS_Index/               # Persisted vector database files
│   │   ├── index.faiss
│   │   ├── index.pkl
│   │   └── processed_files.json   # Tracks indexed documents
│   │
│   ├── uploaded_docs/             # Permanent internal PDF storage
│   ├── temp_uploaded_docs/        # Temporary staging for uploads
│   ├── Voice_ai_log/              # Temporary voice/speech recordings
│   └── Repo_IMGs/                 # README and marketing images
│
└── frontend/                      # Next.js 16 TypeScript frontend
    ├── app/
    │   ├── layout.tsx             # Root layout & metadata
    │   ├── page.tsx               # Main chat interface
    │   ├── globals.css            # Global styles
    │   ├── login/
    │   │   └── page.tsx           # Login page
    │   ├── dashboard/
    │   │   └── page.tsx           # Analytics dashboard
    │   └── users/
    │       └── page.tsx           # User management (admin)
    │
    ├── components/
    │   ├── auth-guard.tsx         # Route protection component
    │   ├── theme-provider.tsx     # Dark/light theme provider
    │   ├── theme-toggle.tsx       # Theme toggle UI control
    │   └── ui/                    # shadcn/ui component library
    │
    ├── lib/                       # Shared utilities & helpers
    ├── public/                    # Static assets
    ├── package.json               # Node dependencies
    ├── next.config.ts
    ├── tsconfig.json
    ├── Dockerfile                 # Frontend container image
    └── .env.example               # Frontend env var template
```

---

## 🛠️ Setup & Installation

### Prerequisites

- Python 3.11+
- Node.js 18+
- A [Groq](https://console.groq.com) API key
- A [Neon](https://neon.tech) PostgreSQL database (for user management)

---

### Option A — Local Development

#### 1. Clone the Repository

```bash
git clone https://github.com/pership/Pership-ChatBot.git
cd Pership-ChatBot
```

#### 2. Configure the Backend

```bash
cd backend
cp .env.example .env
```

Edit `backend/.env` and fill in your values:

```env
GROQ_API_KEY=your_groq_api_key_here
AUTH_SECRET=change-this-to-a-long-random-secret
ADMIN_EMAIL=chat@pership.com
ADMIN_PASSWORD=change-this-admin-password
DATABASE_URL=postgresql://user:password@host/neondb?sslmode=require
```

#### 3. Install Backend Dependencies

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

#### 4. Run the Backend API

```bash
.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

#### 5. Configure the Frontend

```bash
cd ../frontend
cp .env.example .env
```

Edit `frontend/.env`:

```env
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

#### 6. Install Frontend Dependencies & Run

```bash
npm install
npm run dev
```

The web UI will be available at `http://localhost:3000`.

---

### Option B — Docker Compose (Recommended for Production)

#### 1. Configure Root Environment

```bash
cp .env.production.example .env
```

Edit `.env` with your production credentials (Groq key, JWT secret, DB URL, admin credentials, and the public API URL).

#### 2. Build & Start All Services

```bash
docker compose up -d --build
```

This starts three containers:

- **`pership-chatbot-backend`** — FastAPI on port 8000
- **`pership-chatbot-frontend`** — Next.js on port 3000
- **`pership-chatbot-nginx`** — Nginx reverse proxy on ports 80 / 443

#### 3. Stop Services

```bash
docker compose down
```

---

## 🎯 Usage & Example Queries

Once the backend and frontend are running, log in at `http://localhost:3000/login` and start chatting:

1. **Internal Policy Queries (Routed to `RAG_Agent`):**
   - _"What is the dress code policy for employees?"_
   - _"Explain the mobile phone allowance policy guidelines."_
   - _"What are the finance SOPs for expense approvals?"_

2. **General Knowledge & Conversational Queries (Answered directly):**
   - _"What's the current market salary trend for ML Engineers?"_
   - _"Hello! How can you help me today?"_

---

## 🔑 API Endpoints (Key Routes)

| Method   | Endpoint                | Description                                   |
| -------- | ----------------------- | --------------------------------------------- |
| `POST`   | `/api/login`            | Authenticate and receive a session token      |
| `POST`   | `/api/chat`             | Send a message; returns routed agent response |
| `POST`   | `/api/upload-doc`       | Upload a PDF to the RAG knowledge base        |
| `GET`    | `/api/documents`        | List all indexed documents                    |
| `DELETE` | `/api/documents/{name}` | Remove a document from the index              |
| `GET`    | `/api/users`            | List all users (admin only)                   |
| `POST`   | `/api/users`            | Create a new user (admin only)                |
| `DELETE` | `/api/users/{email}`    | Delete a user (admin only)                    |
| `GET`    | `/health`               | Backend health check                          |

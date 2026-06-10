# Junior CAO

This project is a feature-focused Assistant Chat Overlay application consisting of a FastAPI backend and a Next.js frontend.

## Project Structure

```text
Junior CAO/
├── backend/          # FastAPI backend service
│   ├── app/          # Application source code
│   ├── Dockerfile    # Docker configuration for backend
│   └── requirements.txt
├── frontend/         # Next.js frontend application
│   ├── app/          # Next.js app router structure
│   ├── components/   # React components
│   └── package.json
└── README.md         # Main project documentation
```

## Backend Setup

1. **Navigate to backend**:
   ```bash
   cd backend
   ```

2. **Set up virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   Copy `.env.example` to `.env` and fill in your OpenRouter API key and other configurations:
   ```bash
   cp .env.example .env
   ```

4. **Run the Backend Development Server**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   Or run with Docker:
   ```bash
   docker build -t junior-cao-backend .
   docker run -p 8000:8000 --env-file .env junior-cao-backend
   ```

## Frontend Setup

1. **Navigate to frontend**:
   ```bash
   cd frontend
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

3. **Run the Frontend Development Server**:
   ```bash
   npm run dev
   ```

---

## Local Development and Traces

This project utilizes `traces` for Git integration. To initialize or configure git hooks locally:
```bash
traces setup git
```

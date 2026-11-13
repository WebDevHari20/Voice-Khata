# Deployment Guide: Render (Backend) & Vercel (Frontend)

This guide walks you through deploying the **Voice Khata** backend to Render and frontend to Vercel.

---

## 1. Deploy Backend to Render

### Option A: Using Blueprint (Automatic)
1. Go to [Render Dashboard](https://dashboard.render.com/) -> **New +** -> **Blueprint**.
2. Connect your GitHub repository: `WebDevHari20/Voice-Khata`.
3. Render will detect `render.yaml` automatically and configure the Python web service.
4. Under Environment Variables, add:
   - `GNANI_API_KEY`: Your valid Gnani API key (if you have active Prisma/Timbre credits).
5. Click **Apply**.

### Option B: Manual Web Service
1. In Render, select **New +** -> **Web Service**.
2. Connect your repository.
3. Configure settings:
   - **Name**: `voice-khata-backend`
   - **Language**: `Python 3`
   - **Root Directory**: Leave blank (root) OR enter `backend`
   - **Build Command**: `pip install -r backend/requirements.txt` (or `pip install -r requirements.txt`)
   - **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` (or `uvicorn main:app --host 0.0.0.0 --port $PORT` if Root Directory is `backend`)
4. Environment Variables:
   - `PYTHON_VERSION`: `3.12.0`
   - `GNANI_API_KEY`: (optional, your Gnani key)
   - `GNANI_PRISMA_URL`: `wss://api.vachana.ai/stt/v3/stream`
   - `GNANI_TIMBRE_URL`: `https://api.vachana.ai/api/v1/tts/inference`
5. Click **Create Web Service**.
6. Copy your Render backend URL (e.g. `https://voice-khata-backend.onrender.com`).

---

## 2. Deploy Frontend to Vercel

1. Go to [Vercel Dashboard](https://vercel.com/) -> **Add New...** -> **Project**.
2. Import `Voice-Khata`.
3. Configure Project:
   - **Framework Preset**: Vite
   - **Root Directory**: `frontend` (or leave default root, as `vercel.json` handles both)
4. **Environment Variables**:
   - Add `VITE_API_BASE`:
     ```
     https://your-render-backend.onrender.com
     ```
     *(Make sure it uses `https://` and has NO trailing slash)*.
5. Click **Deploy**.

---

## 3. Speech Recognition & Prisma STT 401 Error

- If you see:
  `Prisma connection failed: server rejected WebSocket connection: HTTP 401`
  This means the Gnani/Vachana STT key has expired, reached quota, or is unauthorized.
- **Automatic Fallback**: Voice Khata now includes built-in browser speech recognition (Hindi / Hinglish / English) that works 100% free with no API key needed on Chrome and Edge.
- You can also toggle the voice engine directly using the switch beneath the microphone: **"Switch to Browser Speech"** / **"Use Prisma STT"**.

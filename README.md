# 🚀 Manga Downloader (MangaFreak Edition)

A **high-performance manga downloader** built with Python that allows you to search, select, and download manga chapters with ease.

Supports downloading manga as **images, PDF, or CBZ**, with an optimized async pipeline for faster performance.

---

## ✨ Features

* 🔍 **Smart Manga Search** (MangaFreak-based)
* 📚 Download:

  * Entire manga
  * Range of chapters
  * Single chapter
* ⚡ **Fast async downloads** (parallel image fetching)
* 📄 Export formats:

  * Images
  * PDF
  * CBZ
* 🔁 Resume support (skips already downloaded pages)
* ❌ Automatic failure detection (no fake "0 pages" success)
* 🌐 Optional **Web UI (FastAPI + React)**

---

## 🧠 How It Works

```text
Search → Select Manga → Choose Chapters → Fetch Images → Download → Convert (PDF/CBZ)
```

---

## 📦 Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/manga-downloader.git
cd manga-downloader
```

---

### 2. Create Virtual Environment

```bash
python -m venv env
```

Activate:

**Windows**

```bash
env\Scripts\activate
```

**macOS/Linux**

```bash
source env/bin/activate
```

---

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## ▶️ Usage

### 🔹 CLI Mode

```bash
python run.py
```

Follow prompts:

* Enter manga name
* Select manga
* Choose:

  * Full download
  * Range
  * Single chapter
* Select output format (PDF / CBZ / Images)

---

### 🌐 Web Mode (Optional)

#### Start backend:

```bash
python run.py server
```

#### Start frontend:

```bash
cd frontend
npm install
npm run dev
```

* Frontend: http://localhost:3000
* API Docs: http://localhost:8000/docs

---

## 📁 Project Structure

```
backend/
  api.py            # FastAPI backend
  downloader.py     # Async image downloader
  search.py         # MangaFreak scraper
  converter.py      # PDF / CBZ generator
  queue.py          # Download queue system
  cache.py          # Resume support

frontend/
  React + Vite UI

utils/
  logger.py
  retry.py
```

---

## ⚡ Performance Improvements

| Feature        | Before    | Now             |
| -------------- | --------- | --------------- |
| Downloading    | Threaded  | Async (aiohttp) |
| Speed          | Slow      | 3–5x Faster     |
| Error Handling | None      | Robust          |
| Zero-page bug  | ❌ Present | ✅ Fixed         |
| Resume support | ❌ No      | ✅ Yes           |

---

## ⚠️ Disclaimer

This project is for **educational purposes only**.

Please:

* Respect copyright laws
* Follow the terms of use of manga providers

---

## 🙌 Credits

* Inspired by original project:
  https://github.com/A-Akhil/Manga-Manhwa-Downloader

---

## ⭐ Support

If you like this project, consider giving it a ⭐ on GitHub!

---

## 💡 Future Improvements

* WebSocket live progress tracking
* AI-based manga recommendations
* Cloud storage support (S3/GCP)
* Mobile-friendly UI

---

## 👨‍💻 Author

**Hemanth Kumar**
AI/ML Engineer in progress 🚀

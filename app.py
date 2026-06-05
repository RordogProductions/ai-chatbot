from flask import Flask, render_template, request, jsonify
from groq import Groq
import os
import base64
import mimetypes
import urllib.parse
import threading
import uuid

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max upload
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    "You are a helpful, friendly AI assistant named Rordog AI. "
    "You were created by Rordog. If anyone asks who created you or who made you, "
    "say that you were created by Rordog. "
    "Give clear, concise answers. Be warm and encouraging."
)

TEXT_MODEL = "llama-3.3-70b-versatile"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

GEN_PHRASES = [
    "draw ", "draw me", "generate an image", "generate a picture", "generate a photo",
    "create an image", "create a picture", "create a photo", "make an image",
    "make a picture", "make a photo", "paint ", "paint me", "sketch ",
    "show me a picture", "show me an image", "give me a picture", "give me an image",
    "generate me a", "make me a picture", "make me an image", "create me a"
]

image_jobs = {}

def is_image_request(message):
    msg_lower = message.lower()
    return any(phrase in msg_lower for phrase in GEN_PHRASES)

def get_search_keywords(user_message):
    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": (
                "Extract 2-3 simple search keywords from the user's image request. "
                "Return ONLY the keywords, nothing else. "
                "Examples: 'draw me a dragon' → 'dragon', "
                "'generate a sunset over mountains' → 'sunset mountains', "
                "'make a picture of a robot' → 'robot'"
            )},
            {"role": "user", "content": user_message}
        ]
    )
    return response.choices[0].message.content.strip()

def fetch_image(prompt):
    import urllib.request, json, random
    key = os.environ.get("PIXABAY_KEY", "")
    # Use first 3 words as search terms for best results
    terms = " ".join(prompt.split()[:5])
    encoded = urllib.parse.quote(terms)
    url = f"https://pixabay.com/api/?key={key}&q={encoded}&image_type=photo&per_page=10&safesearch=true"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    hits = data.get("hits", [])
    if not hits:
        raise Exception("No images found for that prompt. Try a different description.")
    return random.choice(hits[:5])["webformatURL"]

def run_image_job(job_id, user_message):
    try:
        keywords = get_search_keywords(user_message)
        data = fetch_image(keywords)
        image_jobs[job_id] = {"status": "done", "data": data}
    except Exception as e:
        import traceback
        traceback.print_exc()
        image_jobs[job_id] = {"status": "error", "message": str(e)}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/image-status/<job_id>")
def image_status(job_id):
    return jsonify(image_jobs.get(job_id, {"status": "not_found"}))

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.form.get("message", "").strip()
    file = request.files.get("file")
    model = TEXT_MODEL
    user_content = user_message

    if file and file.filename:
        mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or ""
        ext = os.path.splitext(file.filename)[1].lower()

        if mime_type in IMAGE_TYPES:
            model = VISION_MODEL
            image_data = base64.b64encode(file.read()).decode("utf-8")
            user_content = [
                {"type": "text", "text": SYSTEM_PROMPT + "\n\n" + (user_message or "What's in this image?")},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}}
            ]
        elif ext == ".pdf":
            try:
                from pypdf import PdfReader
                import io
                reader = PdfReader(io.BytesIO(file.read()))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)[:12000]
                label = f"[PDF: {file.filename}]\n{text}"
                user_content = f"{user_message}\n\n{label}" if user_message else label
            except Exception as e:
                return jsonify({"error": f"Could not read PDF: {str(e)}"}), 400
        else:
            try:
                content = file.read().decode("utf-8", errors="ignore")[:12000]
                label = f"[File: {file.filename}]\n{content}"
                user_content = f"{user_message}\n\n{label}" if user_message else label
            except Exception:
                return jsonify({"error": "Could not read that file type."}), 400

    if not user_content:
        return jsonify({"error": "No message provided"}), 400

    # Image generation — start background job and return immediately
    if not file and is_image_request(user_message):
        job_id = str(uuid.uuid4())
        image_jobs[job_id] = {"status": "pending"}
        t = threading.Thread(target=run_image_job, args=(job_id, user_message))
        t.daemon = True
        t.start()
        return jsonify({"job_id": job_id})

    try:
        if isinstance(user_content, list):
            messages = [{"role": "user", "content": user_content}]
        else:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]
        response = client.chat.completions.create(model=model, messages=messages)
        return jsonify({"reply": response.choices[0].message.content})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)

from flask import Flask, render_template, request, jsonify, session
from groq import Groq
from werkzeug.security import generate_password_hash, check_password_hash
import os
import base64
import mimetypes
import urllib.parse
import threading
import uuid
import sqlite3

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max upload
app.secret_key = os.environ.get('SECRET_KEY', 'pragmatic-ai-dev-key-2024')
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    "You are a helpful, friendly AI assistant named Pragmatic AI. "
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

IMAGE_EDIT_PHRASES = [
    "brighten", "darken", "brighter", "darker", "blur", "sharpen",
    "rotate", "flip", "grayscale", "black and white", "black-and-white",
    "vintage", "make it", "edit", "filter", "contrast", "saturate",
    "make the image", "make this image", "make the photo", "make this photo"
]

FILE_EDIT_PHRASES = [
    "edit", "fix", "change", "update", "modify", "rewrite", "improve",
    "correct", "translate", "refactor", "add", "remove", "rename"
]

image_jobs = {}

# --- Database ---
DB_PATH = os.path.join(os.path.dirname(__file__), 'users.db')

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    db.commit()
    db.close()

init_db()

def save_message(user_id, role, content):
    db = get_db()
    db.execute('INSERT INTO chats (user_id, role, content) VALUES (?, ?, ?)',
               [user_id, role, content])
    db.commit()
    db.close()

def get_recent_history(user_id, limit=10):
    if not user_id:
        return []
    db = get_db()
    rows = db.execute(
        'SELECT role, content FROM chats WHERE user_id = ? ORDER BY created_at DESC LIMIT ?',
        [user_id, limit]
    ).fetchall()
    db.close()
    return [{'role': r['role'], 'content': r['content']} for r in reversed(rows)]

# --- Auth routes ---
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    if len(username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    db = get_db()
    try:
        db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)',
                   [username, generate_password_hash(password)])
        db.commit()
        user = db.execute('SELECT * FROM users WHERE username = ?', [username]).fetchone()
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({'success': True, 'username': user['username']})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'That username is already taken'}), 400
    finally:
        db.close()

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE username = ?', [username]).fetchone()
    db.close()
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid username or password'}), 401
    session['user_id'] = user['id']
    session['username'] = user['username']
    return jsonify({'success': True, 'username': user['username']})

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/me')
def me():
    if 'user_id' in session:
        return jsonify({'logged_in': True, 'username': session['username']})
    return jsonify({'logged_in': False})

@app.route('/history')
def history():
    if 'user_id' not in session:
        return jsonify({'messages': []})
    db = get_db()
    rows = db.execute(
        'SELECT role, content FROM chats WHERE user_id = ? ORDER BY created_at DESC LIMIT 50',
        [session['user_id']]
    ).fetchall()
    db.close()
    return jsonify({'messages': [{'role': r['role'], 'content': r['content']} for r in reversed(rows)]})

# --- Helper functions ---
def is_image_request(message):
    msg_lower = message.lower()
    return any(phrase in msg_lower for phrase in GEN_PHRASES)

def is_image_edit_request(message):
    msg_lower = message.lower()
    return any(phrase in msg_lower for phrase in IMAGE_EDIT_PHRASES)

def is_file_edit_request(message):
    msg_lower = message.lower()
    return any(phrase in msg_lower for phrase in FILE_EDIT_PHRASES)

def apply_image_edits(image_bytes, instructions):
    from PIL import Image, ImageEnhance, ImageFilter
    import io, json

    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": (
                "You are an image editing assistant. Based on the user's instructions, "
                "return a JSON array of edit operations to apply. "
                "Available operations:\n"
                '{"op":"brightness","factor":1.5} (0.5=darker, 2.0=brighter)\n'
                '{"op":"contrast","factor":1.5}\n'
                '{"op":"saturation","factor":1.5} (0=grayscale, 2=vivid)\n'
                '{"op":"sharpness","factor":2.0}\n'
                '{"op":"grayscale"}\n'
                '{"op":"blur","radius":2}\n'
                '{"op":"rotate","degrees":90}\n'
                '{"op":"flip_horizontal"}\n'
                '{"op":"flip_vertical"}\n'
                "Return ONLY a valid JSON array, nothing else."
            )},
            {"role": "user", "content": instructions}
        ]
    )

    ops_text = response.choices[0].message.content.strip()
    if "```" in ops_text:
        ops_text = ops_text.split("```")[1]
        if ops_text.startswith("json"):
            ops_text = ops_text[4:]
    ops = json.loads(ops_text.strip())

    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    for op in ops:
        name = op.get("op", "")
        if name == "brightness":
            img = ImageEnhance.Brightness(img).enhance(op.get("factor", 1.5))
        elif name == "contrast":
            img = ImageEnhance.Contrast(img).enhance(op.get("factor", 1.5))
        elif name == "saturation":
            img = ImageEnhance.Color(img).enhance(op.get("factor", 1.5))
        elif name == "sharpness":
            img = ImageEnhance.Sharpness(img).enhance(op.get("factor", 2.0))
        elif name == "grayscale":
            img = img.convert("L").convert("RGB")
        elif name == "blur":
            img = img.filter(ImageFilter.GaussianBlur(op.get("radius", 2)))
        elif name == "rotate":
            img = img.rotate(op.get("degrees", 90), expand=True)
        elif name == "flip_horizontal":
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        elif name == "flip_vertical":
            img = img.transpose(Image.FLIP_TOP_BOTTOM)

    output = io.BytesIO()
    img.save(output, format="JPEG", quality=90)
    output.seek(0)
    return base64.b64encode(output.read()).decode("utf-8")

def apply_file_edits(filename, content, instructions):
    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": (
                "You are a file editing assistant. Apply the user's editing instructions "
                "to the file content and return ONLY the complete edited file content. "
                "No explanations, no markdown code blocks — just the edited content."
            )},
            {"role": "user", "content": f"File: {filename}\n\nContent:\n{content}\n\nInstructions: {instructions}"}
        ]
    )
    return response.choices[0].message.content

def get_search_keywords(user_message):
    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": (
                "Convert the user's image request into the best Pixabay search keywords. "
                "Pixabay has photos, illustrations, and digital art. "
                "For fictional or fantasy subjects (dragons, unicorns, monsters, robots, etc.), "
                "add 'fantasy art' or 'illustration' to the keywords. "
                "For real subjects, use 2-3 descriptive keywords. "
                "Return ONLY the search keywords, nothing else. "
                "Examples: "
                "'draw me a dragon' → 'dragon fantasy art', "
                "'generate a sunset' → 'sunset sky colorful', "
                "'make a robot' → 'robot futuristic illustration', "
                "'paint me a unicorn' → 'unicorn fantasy illustration'"
            )},
            {"role": "user", "content": user_message}
        ]
    )
    return response.choices[0].message.content.strip()

def fetch_image(prompt):
    import urllib.request, json, random
    key = os.environ.get("PIXABAY_KEY", "")
    terms = " ".join(prompt.split()[:5])
    encoded = urllib.parse.quote(terms)
    url = f"https://pixabay.com/api/?key={key}&q={encoded}&image_type=all&per_page=10&safesearch=true"
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

# --- Main routes ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/image-status/<job_id>")
def image_status(job_id):
    return jsonify(image_jobs.get(job_id, {"status": "not_found"}))

@app.route("/chat", methods=["POST"])
def chat():
    user_id = session.get('user_id')
    user_message = request.form.get("message", "").strip()
    generate_mode = request.form.get("generate_mode") == "1"
    file = request.files.get("file")
    model = TEXT_MODEL
    user_content = user_message

    if file and file.filename:
        mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or ""
        ext = os.path.splitext(file.filename)[1].lower()

        if mime_type in IMAGE_TYPES:
            image_bytes = file.read()
            if user_message and is_image_edit_request(user_message):
                try:
                    edited_b64 = apply_image_edits(image_bytes, user_message)
                    return jsonify({"image_url": f"data:image/jpeg;base64,{edited_b64}", "reply": "Here's your edited image!"})
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    return jsonify({"error": f"Image editing failed: {str(e)}"}), 500
            model = VISION_MODEL
            image_data = base64.b64encode(image_bytes).decode("utf-8")
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
                if user_message and is_file_edit_request(user_message):
                    try:
                        edited = apply_file_edits(file.filename, content, user_message)
                        return jsonify({"reply": f"Here's your edited file:\n\n{edited}", "edited_file": edited, "filename": file.filename})
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        return jsonify({"error": f"File editing failed: {str(e)}"}), 500
                label = f"[File: {file.filename}]\n{content}"
                user_content = f"{user_message}\n\n{label}" if user_message else label
            except Exception:
                return jsonify({"error": "Could not read that file type."}), 400

    if not user_content:
        return jsonify({"error": "No message provided"}), 400

    if not file and (generate_mode or is_image_request(user_message)):
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
            recent = get_recent_history(user_id, 10)
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for h in recent:
                messages.append({"role": h['role'], "content": h['content']})
            messages.append({"role": "user", "content": user_content})

        response = client.chat.completions.create(model=model, messages=messages)
        reply = response.choices[0].message.content

        if user_id and not file:
            save_message(user_id, 'user', user_message)
            save_message(user_id, 'assistant', reply)

        return jsonify({"reply": reply})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)

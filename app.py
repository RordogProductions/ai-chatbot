 from flask import Flask, render_template, request, jsonify
  from groq import Groq
  import os
  import base64
  import mimetypes

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

  @app.route("/")
  def index():
      return render_template("index.html")

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

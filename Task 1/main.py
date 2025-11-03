from flask import Flask, request, jsonify, render_template
import requests
import sqlite3
import time
import os

app = Flask(__name__, template_folder="templates", static_folder="static")

# --- Конфигурация ---
YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
MODEL_NAME = "yandexgpt-lite"
DB_FILE = "chat_history.db"
YANDEX_API_KEY = os.getenv("YC_API_KEY")
YC_API_FOLDER_ID = os.getenv("YC_API_FOLDER_ID")

if not YANDEX_API_KEY:
    raise RuntimeError("Не найден YC_API_KEY в переменных окружения")
if not YC_API_FOLDER_ID:
    raise RuntimeError("Не найден YC_API_FOLDER_ID в переменных окружения")


# --- Инициализация БД ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS dialogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            created REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dialog_id INTEGER,
            role TEXT,
            content TEXT,
            ts REAL,
            FOREIGN KEY(dialog_id) REFERENCES dialogs(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()


init_db()


def get_db():
    return sqlite3.connect(DB_FILE)


# --- Диалоги ---
@app.route("/dialogs", methods=["GET"])
def get_dialogs():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name FROM dialogs ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return jsonify([{"id": i, "name": n} for i, n in rows])


@app.route("/dialogs", methods=["POST"])
def create_dialog():
    data = request.json
    name = data.get("name", f"Новый диалог {int(time.time())}")
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO dialogs (name, created) VALUES (?, ?)", (name, time.time()))
    dialog_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": dialog_id, "name": name})


@app.route("/dialogs/<int:dialog_id>", methods=["DELETE"])
def delete_dialog(dialog_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM dialogs WHERE id=?", (dialog_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


@app.route("/dialogs/<int:dialog_id>", methods=["PUT"])
def rename_dialog(dialog_id):
    data = request.json
    name = data.get("name", "")
    if not name:
        return jsonify({"error": "name is required"}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE dialogs SET name=? WHERE id=?", (name, dialog_id))
    conn.commit()
    conn.close()
    return jsonify({"id": dialog_id, "name": name})


# --- Сообщения ---
def save_message(dialog_id, role, content):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO messages (dialog_id, role, content, ts) VALUES (?, ?, ?, ?)",
              (dialog_id, role, content, time.time()))
    conn.commit()
    conn.close()


def get_history(dialog_id, limit=50):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE dialog_id=? ORDER BY id DESC LIMIT ?",
              (dialog_id, limit))
    rows = c.fetchall()
    conn.close()
    return [{"role": r, "content": c} for r, c in rows[::-1]]


@app.route("/dialogs/<int:dialog_id>/messages", methods=["GET"])
def history(dialog_id):
    return jsonify(get_history(dialog_id))


@app.route("/dialogs/<int:dialog_id>/chat", methods=["POST"])
def chat(dialog_id):
    data = request.json
    user_message = data.get("message", "")

    if not user_message:
        return jsonify({"error": "message is required"}), 400

    save_message(dialog_id, "user", user_message)
    history = get_history(dialog_id)

    # --- Формирование prompt для Yandex GPT ---
    text_context = "\n".join(
        f"{m['role']}: {m['content']}" for m in history
    ) + f"\nuser: {user_message}\nassistant:"

    payload = {
        "modelUri": f"gpt://{YC_API_FOLDER_ID}/{MODEL_NAME}",
        "completionOptions": {
            "temperature": 0.7,
            "maxTokens": 800,
            "stream": False
        },
        "messages": [
            {"role": "system", "text": "Ты — умный и дружелюбный ассистент."},
            {"role": "user", "text": text_context}
        ]
    }

    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "Content-Type": "application/json"
    }

    r = requests.post(YANDEX_GPT_URL, headers=headers, json=payload)

    if r.status_code != 200:
        return jsonify({"error": "Yandex GPT request failed", "details": r.text}), 500

    response_json = r.json()
    assistant_reply = response_json["result"]["alternatives"][0]["message"]["text"]

    save_message(dialog_id, "assistant", assistant_reply)

    return jsonify({"reply": assistant_reply})


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5556, debug=True)

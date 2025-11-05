from flask import Flask, render_template, request, jsonify
import requests
import os
import json
import re

app = Flask(__name__)

YANDEX_API_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YC_API_FOLDER_ID = os.getenv("YC_API_FOLDER_ID")
YC_API_KEY = os.getenv("YC_API_KEY")
MODEL_NAME = "yandexgpt-lite"

sessions = {}


def build_prompt(context: str, player_action: str):
    return f"""
Ты рассказчик текстового квеста в жанре приключений.

Формат ответа — строго JSON:
{{
  "text": "Продолжение истории",
  "options": ["вариант1", "вариант2", "вариант3"]
}}

Контекст:
{context}

Действие игрока: {player_action}
"""


def generate_story(prompt: str):
    headers = {
        "Authorization": f"Api-Key {YC_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "modelUri": f"gpt://{YC_API_FOLDER_ID}/{MODEL_NAME}",
        "completionOptions": {"stream": False, "temperature": 0.8, "maxTokens": 300},
        "messages": [{"role": "user", "text": prompt}],
    }

    response = requests.post(YANDEX_API_URL, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    text = data["result"]["alternatives"][0]["message"]["text"]
    return text


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/continue", methods=["POST"])
def continue_story():
    data = request.json
    session_id = data.get("session_id")
    action = data.get("player_action", "")

    if session_id not in sessions:
        sessions[session_id] = {
            "context": "Ты просыпаешься в незнакомой комнате. Свет тусклый, воздух пахнет сыростью."
        }

    context = sessions[session_id]["context"]
    prompt = build_prompt(context, action)

    try:
        llm_response = generate_story(prompt)
        print("[DEBUG] llm_response =", llm_response)

        # --- 💡 Попробуем аккуратно извлечь JSON ---
        match = re.search(r"\{.*\}", llm_response, re.DOTALL)
        if not match:
            raise ValueError("JSON not found in LLM response")

        json_text = match.group(0).strip()

        # Попробуем загрузить как есть
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError:
            # Попробуем почистить странные кавычки/переносы
            cleaned = json_text.replace("\n", "").replace("\r", "")
            parsed = json.loads(cleaned)

        # --- обновляем контекст ---
        sessions[session_id]["context"] += f"\nИгрок: {action}\nСистема: {parsed['text']}"

        return jsonify(parsed)

    except Exception as e:
        print("Ошибка при генерации:", e)
        return jsonify({
            "text": "Произошла ошибка при обработке ответа рассказчика.",
            "options": ["Повторить", "Закончить игру"]
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

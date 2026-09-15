import os
import json
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

# читает файл .env и кладёт его переменные в окружение, чтобы os.getenv их видел
load_dotenv()

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # получатель теперь настраивается через .env, а не зашит в коде

RSS_URL = "https://openai.com/news/rss.xml"

# скачиваем RSS-ленту, это просто текст в формате XML
response = requests.get(RSS_URL)

# разбираем XML на дерево тегов, чтобы можно было искать в нём по имени тега
root = ET.fromstring(response.text)

# ".//item" значит "найди первый тег <item> где угодно внутри дерева"
first_item = root.find(".//item")
title = first_item.find("title").text
link = first_item.find("link").text

message_text = f"{title}\n{link}"

send_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

data = {
    "chat_id": CHAT_ID,
    "text": message_text,
    # отключает разворачивание карточки-превью со ссылкой (картинка/заголовок сайта)
    "link_preview_options": json.dumps({"is_disabled": True})
}

result = requests.post(send_url, data=data)

if result.status_code == 200:
    print("Отправлено:", message_text)
else:
    print("Ошибка:", result.status_code, result.text)

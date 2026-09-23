import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
import time
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from deep_translator.exceptions import TooManyRequests
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SOURCES = {
    "OpenAI": "https://openai.com/news/rss.xml",
    "GitHub Changelog": "https://github.blog/changelog/feed/",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
}

SENT_LINKS_FILE = "sent_links.txt"
MAX_MESSAGE_LENGTH = 4096
FOOTER_RESERVE = 300

MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def format_date_ru(d):
    return f"{d.day} {MONTHS_RU[d.month - 1]}"


def clean_link(link):
    parts = urlsplit(link)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


_translator_executor = ThreadPoolExecutor(max_workers=4)


def _translate_once(title):
    return GoogleTranslator(source="auto", target="ru").translate(title)


def translate_title(title):
    for attempt in range(3):
        future = _translator_executor.submit(_translate_once, title)
        try:
            result = future.result(timeout=10)
        except TooManyRequests:
            time.sleep(2)
            continue
        except Exception:
            return title

        time.sleep(0.3)
        return result

    return title


def load_sent_links():
    if not os.path.exists(SENT_LINKS_FILE):
        print(f"Файл {SENT_LINKS_FILE} не найден, считаем что новостей ещё не отправляли")
        return set()
    with open(SENT_LINKS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def append_sent_links(links):
    with open(SENT_LINKS_FILE, "a", encoding="utf-8") as f:
        for link in links:
            f.write(link + "\n")


def parse_date(item):
    for tag in ("pubDate", "published", "updated"):
        el = item.find(tag)
        if el is not None and el.text:
            try:
                return parsedate_to_datetime(el.text)
            except (TypeError, ValueError):
                pass
    return None


def fetch_source(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except (requests.RequestException, ET.ParseError):
        return None

    news = []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        if title_el is None or link_el is None:
            continue
        news.append({
            "title": title_el.text,
            "link": link_el.text,
            "clean_link": clean_link(link_el.text),
            "date": parse_date(item),
        })
    return news


def collect_news(sent_links):
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    dated_news = []
    undated_news = []
    failed_sources = []
    seen_links = set()
    already_sent_count = 0

    for name, url in SOURCES.items():
        items = fetch_source(url)
        if items is None:
            failed_sources.append(name)
            continue

        for item in items:
            is_within_week = item["date"] is None or item["date"] >= week_ago
            if not is_within_week:
                continue

            if item["clean_link"] in sent_links or item["clean_link"] in seen_links:
                already_sent_count += 1
                continue

            if item["date"] is None:
                item["title"] = translate_title(item["title"])
                undated_news.append(item)
            else:
                item["title"] = translate_title(item["title"])
                dated_news.append(item)
            seen_links.add(item["clean_link"])

    dated_news.sort(key=lambda n: n["date"], reverse=True)
    return dated_news, undated_news, failed_sources, already_sent_count


def build_message(dated_news, undated_news):
    lines = []
    included_links = []
    skipped_count = 0
    last_date = None

    for item in dated_news:
        item_date = item["date"].date()
        pieces = []
        if item_date != last_date:
            pieces.append(format_date_ru(item_date))
        pieces.append(f"{item['title']}\n{item['link']}")

        candidate = "\n\n".join(lines + pieces)
        if len(candidate) > MAX_MESSAGE_LENGTH - FOOTER_RESERVE:
            skipped_count += 1
            continue

        lines.extend(pieces)
        included_links.append(item["clean_link"])
        last_date = item_date

    if undated_news:
        header_added = False
        for item in undated_news:
            pieces = []
            if not header_added:
                pieces.append("Дата не определена")
            pieces.append(f"{item['title']}\n{item['link']}")

            candidate = "\n\n".join(lines + pieces)
            if len(candidate) > MAX_MESSAGE_LENGTH - FOOTER_RESERVE:
                skipped_count += 1
                continue

            lines.extend(pieces)
            included_links.append(item["clean_link"])
            header_added = True

    text = "\n\n".join(lines)
    return text, included_links, skipped_count


def empty_digest_message(failed_sources, already_sent_count):
    if failed_sources:
        return "Не удалось проверить новости на этой неделе: часть источников не ответила."
    if already_sent_count:
        return "Новых новостей нет — всё, что вышло на этой неделе, уже было в прошлых дайджестах."
    return "На этой неделе новостей не было."


def send_message(text):
    send_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text,
        "link_preview_options": json.dumps({"is_disabled": True}),
    }
    return requests.post(send_url, data=data)


def main():
    sent_links = load_sent_links()
    dated_news, undated_news, failed_sources, already_sent_count = collect_news(sent_links)

    if not dated_news and not undated_news:
        message_text = empty_digest_message(failed_sources, already_sent_count)
        included_links = []
    else:
        message_text, included_links, skipped_count = build_message(dated_news, undated_news)
        if skipped_count:
            message_text += f"\n\nЕщё {skipped_count} новостей не поместилось."

    for name in failed_sources:
        message_text += f"\n\nИсточник {name} не ответил на этой неделе."

    result = send_message(message_text)

    if result.status_code == 200:
        print("Отправлено:", message_text)
        append_sent_links(included_links)
    else:
        print("Ошибка:", result.status_code, result.text)


if __name__ == "__main__":
    main()

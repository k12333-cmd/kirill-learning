import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bot


def _make_item(title, link, date=None):
    return {
        "title": title,
        "link": link,
        "clean_link": bot.clean_link(link),
        "date": date,
    }


def test_clean_link_strips_query_params():
    assert bot.clean_link("https://example.com/news?utm_source=x&utm_medium=y") == "https://example.com/news"
    assert bot.clean_link("https://example.com/news") == "https://example.com/news"


def test_load_sent_links_missing_file(tmp_path, monkeypatch, capsys):
    missing_file = tmp_path / "sent_links.txt"
    monkeypatch.setattr(bot, "SENT_LINKS_FILE", str(missing_file))

    result = bot.load_sent_links()

    assert result == set()
    assert "не найден" in capsys.readouterr().out


def test_load_sent_links_existing_file(tmp_path, monkeypatch):
    existing_file = tmp_path / "sent_links.txt"
    existing_file.write_text("https://a.com/1\nhttps://a.com/2\n", encoding="utf-8")
    monkeypatch.setattr(bot, "SENT_LINKS_FILE", str(existing_file))

    result = bot.load_sent_links()

    assert result == {"https://a.com/1", "https://a.com/2"}


def test_append_sent_links(tmp_path, monkeypatch):
    file_path = tmp_path / "sent_links.txt"
    monkeypatch.setattr(bot, "SENT_LINKS_FILE", str(file_path))

    bot.append_sent_links(["https://a.com/1", "https://a.com/2"])

    assert file_path.read_text(encoding="utf-8").splitlines() == [
        "https://a.com/1",
        "https://a.com/2",
    ]


def test_build_message_groups_by_date_and_marks_undated():
    day1 = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)

    dated = [
        _make_item("Новость 1", "https://a.com/1", day1),
        _make_item("Новость 2", "https://a.com/2", day1),
        _make_item("Новость 3", "https://a.com/3", day2),
    ]
    undated = [
        _make_item("Новость без даты", "https://a.com/4"),
    ]

    text, included_links, skipped_count = bot.build_message(dated, undated)

    assert skipped_count == 0
    assert text.count(bot.format_date_ru(day1.date())) == 1
    assert text.count(bot.format_date_ru(day2.date())) == 1
    assert text.count("Дата не определена") == 1
    assert included_links == [
        "https://a.com/1",
        "https://a.com/2",
        "https://a.com/3",
        "https://a.com/4",
    ]


def test_build_message_respects_length_limit():
    long_title = "Очень длинный заголовок новости " * 20
    day = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
    dated = [_make_item(f"{long_title} {i}", f"https://a.com/{i}", day) for i in range(30)]

    text, included_links, skipped_count = bot.build_message(dated, [])

    assert len(text) <= bot.MAX_MESSAGE_LENGTH
    assert skipped_count > 0
    assert len(included_links) < 30


def test_parse_date_valid_and_missing():
    import xml.etree.ElementTree as ET

    item_with_date = ET.fromstring("<item><pubDate>Fri, 18 Sep 2026 10:00:00 GMT</pubDate></item>")
    item_without_date = ET.fromstring("<item></item>")

    assert bot.parse_date(item_with_date) is not None
    assert bot.parse_date(item_without_date) is None


def test_fetch_source_returns_none_on_request_error(monkeypatch):
    def fake_get(*args, **kwargs):
        raise bot.requests.RequestException("boom")

    monkeypatch.setattr(bot.requests, "get", fake_get)

    assert bot.fetch_source("https://example.com/rss.xml") is None


def test_collect_news_skips_already_sent_links(monkeypatch):
    day = datetime.now(timezone.utc) - timedelta(days=1)

    def fake_fetch_source(url):
        return [
            _make_item("Уже отправленная новость", "https://a.com/old?utm_source=x", day),
            _make_item("Новая новость", "https://a.com/new", day),
        ]

    monkeypatch.setattr(bot, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(bot, "translate_title", lambda title: title)

    sent_links = {"https://a.com/old"}

    dated_news, undated_news, failed_sources = bot.collect_news(sent_links)

    links = [item["clean_link"] for item in dated_news]
    assert "https://a.com/old" not in links
    assert "https://a.com/new" in links
    assert failed_sources == []


def test_collect_news_reports_failed_source(monkeypatch):
    def fake_fetch_source(url):
        if "openai" in url:
            return None
        return []

    monkeypatch.setattr(bot, "fetch_source", fake_fetch_source)

    dated_news, undated_news, failed_sources = bot.collect_news(set())

    assert "OpenAI" in failed_sources
    assert dated_news == []
    assert undated_news == []

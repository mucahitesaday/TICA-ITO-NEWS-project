"""
pipeline/gpt/daily_sector_summary.py
Sorumlu: Esad Ay

Görev:
  process.py bittikten sonra çalışır.
  Bugünün haberlerini sektöre göre gruplar.
  Her sektör için GPT-4o-mini ile günlük sektör özeti üretir.
  daily_summaries tablosuna yazar.
  GPT'ye ulaşılamazsa o sektör atlanır, veritabanına yazılmaz.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """
Sen İstanbul Ticaret Gazetesi için günlük sektör özeti yazan Türkçe ekonomi editörüsün.

Görevin:
Aynı sektördeki bugünkü haberleri okuyup günlük sektör özeti üretmek.

Kurallar:
- Sadece JSON döndür.
- bullet_points tam 3 madde olmalı.
- Her madde "• " ile başlamalı.
- headline tek cümle olmalı.
- Gereksiz süslü dil kullanma.
- Haberde olmayan bilgi ekleme.
- Sentiment / duygu analizi yapma.

JSON formatı:
{
  "bullet_points": ["• Madde 1", "• Madde 2", "• Madde 3"],
  "headline": "Günün en önemli gelişmesi tek cümle."
}
"""


def validate_env() -> None:
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_KEY")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")

    if missing:
        raise RuntimeError(f"Eksik env değişkenleri: {', '.join(missing)}")


def get_clients():
    validate_env()
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return supabase_client, openai_client


def get_todays_articles_by_sector(client) -> dict[str, list[dict[str, Any]]]:
    """Bugünün haberlerini sektöre göre grupla."""
    today = datetime.now(timezone.utc).date().isoformat()

    result = (
        client.table("articles")
        .select("id, title, summary, sector, sentiment_score_bert, scraped_at")
        .not_.is_("sector", "null")
        .gte("scraped_at", today)
        .execute()
    )

    grouped: dict[str, list[dict[str, Any]]] = {}

    for article in result.data or []:
        sector = article.get("sector") or "diger"
        grouped.setdefault(sector, []).append(article)

    return grouped


def _safe_json_loads(text: str) -> dict[str, Any]:
    text = text.strip()

    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1:
        text = text[start:end + 1]

    return json.loads(text)


def _normalize_bullets(value: Any) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip().lstrip("•").strip() for item in value]
    else:
        raw = str(value or "")
        items = [
            line.strip().lstrip("•").strip()
            for line in raw.splitlines()
            if line.strip()
        ]

    items = [item for item in items if item]

    if len(items) < 3:
        items = (items + ["Sektörde gün içindeki gelişmeler takip edildi."] * 3)[:3]
    else:
        items = items[:3]

    return [f"• {item}" for item in items]


def _calculate_avg_sentiment(articles: list[dict[str, Any]]) -> float | None:
    scores = [
        article.get("sentiment_score_bert")
        for article in articles
        if article.get("sentiment_score_bert") is not None
    ]

    if not scores:
        return None

    return sum(float(score) for score in scores) / len(scores)


def summarize_sector(sector: str, articles: list[dict[str, Any]], openai_client: OpenAI) -> dict[str, Any] | None:
    """
    Bir sektörün günlük özetini üretir.
    GPT'ye ulaşılamazsa None döner — sektör atlanır.
    """
    article_lines = []

    for article in articles:
        title = article.get("title") or "Başlıksız"
        summary = article.get("summary") or ""
        article_lines.append(f"- Başlık: {title}\n  Özet: {summary}")

    articles_text = "\n\n".join(article_lines)[:16000]

    user_prompt = f"""
Sektör:
{sector}

Bugünkü haberler:
{articles_text}
"""

    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        content = response.choices[0].message.content or "{}"
        data = _safe_json_loads(content)

        bullet_points = _normalize_bullets(data.get("bullet_points", []))
        headline = str(data.get("headline") or bullet_points[0].lstrip("•").strip()).strip()

        return {
            "bullet_points": bullet_points,
            "headline": headline,
            "article_count": len(articles),
            "avg_sentiment": _calculate_avg_sentiment(articles),
        }

    except Exception as exc:
        logger.exception("Günlük sektör özeti hatası. sector=%s error=%s", sector, exc)
        return None


def run_daily_sector_summary() -> int:
    """
    Pipeline ana fonksiyonu.
    Bugünkü haberleri sektöre göre gruplar,
    her sektör için günlük özet üretir,
    daily_summaries tablosuna upsert eder.
    GPT'ye ulaşılamazsa o sektör atlanır.
    """
    supabase_client, openai_client = get_clients()
    today = datetime.now(timezone.utc).date().isoformat()

    grouped = get_todays_articles_by_sector(supabase_client)
    logger.info("%s sektör için günlük özet üretilecek.", len(grouped))

    processed_count = 0

    for sector, articles in grouped.items():
        if not articles:
            continue

        logger.info("Sektör özeti üretiliyor: sector=%s article_count=%s", sector, len(articles))

        result = summarize_sector(sector, articles, openai_client)

        if result is None:
            logger.warning("Sektör özeti atlanıyor (GPT hatası): %s", sector)
            continue

        supabase_client.table("daily_summaries").upsert({
            "sector": sector,
            "summary_date": today,
            "bullet_points": result["bullet_points"],
            "headline": result["headline"],
            "article_count": result["article_count"],
            "avg_sentiment": result["avg_sentiment"],
        }, on_conflict="sector,summary_date").execute()

        processed_count += 1
        logger.info("OK: sector=%s", sector)

    logger.info("Günlük sektör özeti tamamlandı. İşlenen sektör: %s", processed_count)
    return processed_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_daily_sector_summary()
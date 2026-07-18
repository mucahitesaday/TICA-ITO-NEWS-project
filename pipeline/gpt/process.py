"""
pipeline/gpt/process.py
Sorumlu: Esad Ay

Görev:
  Bugün scraper'ın çektiği haberleri GPT-4o-mini'ye göndererek
  sektör + 3 maddelik haber özeti üretir.
  Sonuçları articles tablosundaki sector ve summary kolonlarına yazar.
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

SECTORS = [
    "finans", "teknoloji", "enerji", "dis-ticaret-lojistik",
    "spor", "egitim", "tarim-gida", "otomotiv", "turizm-seyahat",
    "saglik", "insaat-gayrimenkul", "cevre-afet",
    "jeopolitik-dis-politika", "sanayi-savunma", "diger"
]

SYSTEM_PROMPT = f"""
Sen İstanbul Ticaret Gazetesi için çalışan Türkçe ekonomi editörüsün.

Görevin:
1. Haberi aşağıdaki sektörlerden sadece birine sınıflandır.
2. Haberi tam 3 kısa Türkçe maddeyle özetle.

Sektörler:
{", ".join(SECTORS)}

Kurallar:
- Sadece JSON döndür.
- sector değeri yalnızca listedeki slug değerlerinden biri olmalı.
- summary string olmalı.
- summary içinde tam 3 madde olmalı.
- Her madde "• " ile başlamalı.
- Sentiment / duygu analizi yapma.
- Haberde olmayan bilgi ekleme.

JSON formatı:
{{
  "sector": "finans",
  "summary": "• Madde 1\\n• Madde 2\\n• Madde 3"
}}
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


def get_unprocessed(client) -> list[dict[str, Any]]:
    """Sector'ü boş olan tüm haberleri getir."""
    result = (
        client.table("articles")
        .select("id, title, full_text, summary, scraped_at")
        .is_("sector", "null")
        .execute()
    )

    return result.data or []


def _safe_json_loads(text: str) -> dict[str, Any]:
    """Model cevabını güvenli şekilde JSON'a çevirir."""
    text = text.strip()

    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1:
        text = text[start:end + 1]

    return json.loads(text)


def _normalize_summary(summary: Any) -> str:
    """Summary alanını 3 bullet string formatına getirir."""
    if isinstance(summary, list):
        items = [str(item).strip().lstrip("•").strip() for item in summary]
    else:
        raw = str(summary or "")
        items = [
            line.strip().lstrip("•").strip()
            for line in raw.splitlines()
            if line.strip()
        ]

    items = [item for item in items if item]

    if len(items) < 3:
        items = (items + ["Haberin detayları takip ediliyor."] * 3)[:3]
    else:
        items = items[:3]

    return "\n".join(f"• {item}" for item in items)


def process_article(article: dict[str, Any], openai_client: OpenAI) -> dict[str, str] | None:
    """
    Tek haber için GPT-4o-mini çağrısı yapar.
    Başarısız olursa None döner — haber işlenmeden geçilir.
    """
    title = article.get("title") or ""
    full_text = article.get("full_text") or ""
    old_summary = article.get("summary") or ""

    text = full_text if full_text.strip() else old_summary
    text = text[:12000]

    user_prompt = f"""
Başlık:
{title}

Haber metni:
{text}
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

        sector = str(data.get("sector", "diger")).strip().lower()
        if sector not in SECTORS:
            sector = "diger"

        summary = _normalize_summary(data.get("summary", ""))

        return {
            "sector": sector,
            "summary": summary,
        }

    except Exception as exc:
        logger.exception("GPT haber işleme hatası. article_id=%s error=%s", article.get("id"), exc)
        return None


def run_classification() -> int:
    """
    Pipeline ana fonksiyonu.
    Bugünkü işlenmemiş haberleri alır, GPT ile sector + summary üretir,
    articles tablosunu günceller.
    GPT'ye ulaşılamazsa haber atlanır, alanlar boş kalır.
    """
    supabase_client, openai_client = get_clients()

    articles = get_unprocessed(supabase_client)
    logger.info("%s haber GPT ile işlenecek.", len(articles))

    processed_count = 0

    for article in articles:
        article_id = article.get("id")
        title = article.get("title") or "Başlıksız"

        logger.info("İşleniyor: id=%s title=%s", article_id, title)

        result = process_article(article, openai_client)

        if result is None:
            logger.warning("Atlanıyor (GPT hatası): id=%s", article_id)
            continue

        supabase_client.table("articles").update({
            "sector": result["sector"],
            "summary": result["summary"],
        }).eq("id", article_id).execute()

        processed_count += 1
        logger.info("OK: id=%s sector=%s", article_id, result["sector"])

    logger.info("GPT process tamamlandı. İşlenen haber: %s", processed_count)
    return processed_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_classification()
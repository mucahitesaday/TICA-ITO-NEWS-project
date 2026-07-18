# TICA — İTO News GPT Pipeline

İstanbul Ticaret Gazetesi haber projesi kapsamında geliştirilen GPT tabanlı
haber sınıflandırma ve günlük sektör özeti pipeline'ıdır.

Bu repoda Esad Ay tarafından geliştirilen `pipeline/gpt` görevleri yer alır.
Uygulamalar Supabase üzerindeki haber kayıtlarını işler ve OpenAI modeli
aracılığıyla yapılandırılmış Türkçe özetler üretir.

## Geliştirilen görevler

### 1. Haber sınıflandırma ve özetleme

`pipeline/gpt/process.py` dosyası:

- `articles` tablosundan sektörü henüz belirlenmemiş haberleri getirir.
- Haber başlığını ve tam metnini GPT modeline gönderir.
- Haberi tanımlı sektörlerden yalnızca biriyle sınıflandırır.
- Haber içeriğinden tam üç maddelik Türkçe özet üretir.
- Üretilen `sector` ve `summary` alanlarını Supabase'e kaydeder.
- Model çağrısı başarısız olduğunda ilgili haberi atlar ve pipeline'ın kalan
  kayıtlarla çalışmaya devam etmesini sağlar.

Kullanılan sektörler arasında finans, teknoloji, enerji, dış ticaret ve
lojistik, tarım ve gıda, otomotiv, turizm, sağlık, inşaat, sanayi ve savunma
gibi başlıklar bulunur.

### 2. Günlük sektör özeti

`pipeline/gpt/daily_sector_summary.py` dosyası, `process.py` tamamlandıktan
sonra çalıştırılır:

- O gün işlenmiş haberleri sektörlerine göre gruplandırır.
- Her sektör için haber başlıkları ve özetlerinden ortak bir günlük özet üretir.
- Her sektör için üç önemli madde ve tek cümlelik ana gelişme hazırlar.
- Haber sayısını ve mevcut sentiment skorlarının ortalamasını hesaplar.
- Sonuçları `daily_summaries` tablosuna ekler veya günceller.
- Aynı sektör ve tarih için tekrar çalıştırıldığında `upsert` kullanarak
  yinelenen kayıt oluşmasını önler.

## Pipeline akışı

```text
Supabase articles
       |
       v
process.py
  - sektör sınıflandırma
  - üç maddelik haber özeti
       |
       v
Güncellenmiş articles
       |
       v
daily_sector_summary.py
  - sektör bazında gruplama
  - günlük sektör özeti
       |
       v
Supabase daily_summaries
```

## Proje yapısı

```text
TICA-ITO-NEWS-project/
├── pipeline/
│   └── gpt/
│       ├── process.py
│       └── daily_sector_summary.py
├── .env.example
├── requirements.txt
└── README.md
```

## Kurulum

Repoyu klonlayın ve proje klasörüne geçin:

```bash
git clone https://github.com/mucahitesaday/TICA-ITO-NEWS-project.git
cd TICA-ITO-NEWS-project
```

Sanal ortam oluşturun:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Bağımlılıkları yükleyin:

```bash
python -m pip install -r requirements.txt
```

`.env.example` dosyasını `.env` adıyla kopyalayıp gerekli anahtarları girin.
Gerçek API anahtarları repoya yüklenmemelidir.

## Ortam değişkenleri

| Değişken | Açıklama |
|---|---|
| `SUPABASE_URL` | Supabase proje adresi |
| `SUPABASE_KEY` | Supabase erişim anahtarı |
| `OPENAI_API_KEY` | OpenAI API anahtarı |
| `OPENAI_MODEL` | Kullanılacak model; varsayılan `gpt-4o-mini` |

## Çalıştırma

Önce haberleri sınıflandırıp özetleyin:

```bash
python pipeline/gpt/process.py
```

Ardından günlük sektör özetlerini üretin:

```bash
python pipeline/gpt/daily_sector_summary.py
```

## Güvenilirlik önlemleri

- Eksik ortam değişkenleri başlangıçta doğrulanır.
- Modelden yalnızca JSON yanıt istenir.
- Kod bloğu içinde gelen JSON yanıtları güvenli biçimde ayıklanır.
- Geçersiz sektör değerleri `diger` kategorisine dönüştürülür.
- Özetlerin üç maddelik yapısı normalize edilir.
- Başarısız model çağrıları loglanır ve diğer kayıtların işlenmesini engellemez.
- Günlük sonuçlarda sektör ve tarih çifti için `upsert` kullanılır.

## Not

Pipeline'ın çalışabilmesi için Supabase tarafında `articles` ve
`daily_summaries` tablolarının beklenen kolonlarla tanımlanmış olması gerekir.
API anahtarları ve diğer gizli bilgiler yalnızca yerel `.env` dosyasında
tutulmalıdır.

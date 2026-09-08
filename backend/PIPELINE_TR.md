# Nötron haber hattı

Proje ana klasöründen çalıştır:

```bash
python3 -m pip install -r backend/requirements.txt
python3 backend/run_pipeline.py
```

Mevcut `backend/.env` dosyanı koru. Yoksa `backend/.env.example` dosyasını
`backend/.env` adıyla kopyalayıp Supabase URL, sunucu yazma anahtarı ve OpenAI
anahtarını gir. Bu dosyayı paylaşma veya Git'e ekleme.

Sıra sabittir:

1. `rss_fetcher.py`
2. `clustering_news_enriched.py`
3. `update_event_popularity_v02.py`
4. `generate_event_deep_dives.py`

Puanlar: P=20, R=5, Q=1, S=3. Her katkının puanı kendi zamanından başlayarak
6 saatte yarıya iner. İki medya grubuna ulaşma bonusu yalnızca bir kez verilir;
aynı makaleler veya aynı kişinin tekrarlanan işlemleri yeniden puan kazandırmaz.
Kurallar ve zamanlayıcı kurulumu `backend/POPULARITY.md` dosyasında açıklanır.

Olumlu, nötr ve olumsuz haberler eşit şekilde değerlendirilir; problem şartı yoktur.
Popülerlik önce araştırma sırasını belirler. Son adım, hazır analiz ve sayısal
veriye sahip, en az iki güncel kaynağı bulunan olayları görünür yapar. Son
36 saatin dışındaki haberler gündemde gösterilmez; eski kayıtlar silinmez.
Güncel puanı en az 5 olan uygun olayların ilk 3'ü Gündem'de, diğerleri hemen
sonrasındaki Other Events sekmesinde gösterilir.

GitHub Actions dosyası Türkiye saatiyle 00:17, 06:17, 12:17 ve 18:17 için hazırdır.
Ancak yalnızca siteyi yayınlamak bu görevi başlatmaz: Nötron GitHub deposunda
workflow ve üç Actions secret ayarlanmalı, ilk çalışma elle doğrulanmalıdır.
GitHub deposu: `eren-bardak/notron`. Pipeline dosyalarının main dalına ilk yüklenmesi
çalışmayı otomatik başlatır. Eksik secret varsa görev veri işlemeden durur.

Script başarılı sayılmadan terminalde kaynak/haber sayıları, derin analiz
sonuçları ve `ready_visible_events` değerini kontrol et. Sıfır olay, yeni olay
olmadığı veya kaynak/kalite koşullarını geçen dosya bulunmadığı anlamına gelebilir.

Bu güncellemenin çalışma ortamında `SUPABASE_KEY` ve `OPENAI_API_KEY` mevcut
olmadığından gerçek haber çekimi ve veritabanına katkı yazımı doğrulanamadı.

Haber akışında yapay örnek olaylar yoktur. Gerçek olaylarda katılımcı yanıtları ve
yorumları varsayılan olarak gösterilir. İsteğe bağlı, açıkça etiketli örnek görünüm
20 temsili yanıtla grafikleri denemek içindir; veritabanına yazılmaz ve puan kazanmaz.
Gerçek katkıları doğrulanmış hesabınla yayınla. Writer yorumları Writer rolü gerektirir.

Web dosyalarını mevcut projenin üzerine koy; `backend/.env`, iOS URL Scheme ve
yerel Capacitor ayarlarını değiştirme. Supabase şemasının önceki Nötron
migrasyonlarını içermesi gerekir. Bu paket uzak veritabanında SQL çalıştırmaz.

"""Source-checked editorial correction for a specifically reviewed occurrence."""
from .models import BinaryQuestion, Chart


# Editorial drafts for the existing occurrences, still checked against research.
TRADEOFF_DRAFTS = {
    75: ("Üsküdar", "Üsküdar’da hızlı karar mı, daha geniş uzlaşma mı?"),
    76: ("Antalya", "Aksu’da yangını önlemek mi, müdahaleyi güçlendirmek mi?"),
    77: ("Atlas Çağlayan", "Atlas davası: çocuk cezalarında caydırıcılık mı, topluma dönüş mü?"),
    81: ("137", "Operasyonda İstanbul’a daha çok kaynak mı, dört ile eşit kaynak mı?"),
    82: ("Elazığ", "Karakoçan’da yangın önleminde zorunluluk mu, teşvik mi?"),
    84: ("Avcılar", "Avcılar’da ağır araçlara geçiş sınırı mı, daha sık denetim mi?"),
    85: ("kantin", "İstanbul kantinlerinde düşük tavan fiyat mı, esnek fiyat mı?"),
    86: ("Galatasaray", "Galatasaray Sporting’e karşı hücumu mu, savunma güvenliğini mi öne almalı?"),
    87: ("cenaze", "Mladić cenazesine tepkide sert mesaj mı, geniş ortaklık mı öne çıkmalı?"),
}


def event_tradeoff(research):
    event_id = research.get("event_id") if isinstance(research, dict) else research.event_id
    title = research.get("event_title", "") if isinstance(research, dict) else research.event_title
    draft = TRADEOFF_DRAFTS.get(event_id)
    return draft[1] if draft and draft[0].casefold() in title.casefold() else None


def curate_known_event(research, analysis):
    if research.event_id != 75 or "Üsküdar" not in research.event_title:
        return
    sources = {
        "https://www.aa.com.tr/tr/gundem/uskudar-belediye-baskan-vekilligine-ak-partili-dundar-ziya-gultekin-secildi-/4050704",
        "https://www.dha.com.tr/gundem/uskudar-belediyesi-baskan-vekili-dundar-ziya-gultekin-oldu-2941169",
        "https://medyascope.tv/2026/09/08/uskudar-belediyesi-akpye-gecti/",
    }
    for series in research.numeric_series:
        if series.source_url.rstrip("/") not in {url.rstrip("/") for url in sources}:
            continue
        winner = next((p for p in series.points if p.value == 23 and "gültekin" in (p.label + " " + p.group).casefold()), None)
        other = next((p for p in series.points if p.value == 19 and "çetinkaya" in (p.label + " " + p.group).casefold()), None)
        if winner is None or other is None:
            continue
        analysis.charts = [Chart(
            chart_type="comparison", title="Üsküdar başkanvekilliği: son tur oyları",
            unit=series.unit, x_label="Aday", y_label="Oy", points=[winner, other],
            insight="Son turdaki 23–19 oy dağılımı bu seçimin desteğini gösterir. Sonraki belediye kararlarında aynı desteğin süreceği bu sonuçtan kesinleşmez.",
            source_urls=[series.source_url],
        )]
        analysis.binary_questions = [BinaryQuestion(
            id="q1", question_type="metric",
            question="Üsküdar’da hangisi ağır basmalı: hızlı karar mı, geniş uzlaşma mı?",
            data_anchor="Son turda Gültekin 23, Çetinkaya 19 oy aldı. Tek oylama, sonraki kararlarda aynı desteğin süreceğini kanıtlamaz.",
            choice_labels={"yes": "Hızlı karar almak", "no": "Geniş uzlaşma aramak", "unsure": "Karara göre değişir"},
            why_it_matters="Karar hızı ile daha geniş katılım arasındaki tercihi tartmak için.",
        )]
        return

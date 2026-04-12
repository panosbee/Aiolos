"""
XDART-Φ — RSS Feed Catalog

435+ curated RSS feeds ported from WorldMonitor (AGPL-3.0, research use OK).
Organised by category with source tier, region, propaganda risk, and state affiliation.

Source tier system:
  Tier 1: Wire services, official government sources (Reuters, AP, BBC, DOD)
  Tier 2: Major established outlets (CNN, NYT, The Guardian, Al Jazeera)
  Tier 3: Specialised/niche outlets (Defense One, Breaking Defense, War Zone)
  Tier 4: Aggregators and blogs (Google News, individual analyst blogs)

Propaganda risk:
  high:   State-controlled media, known to push government narratives
  medium: State-affiliated or known editorial bias toward specific governments
  low:    Independent journalism with editorial standards
"""

from typing import TypedDict


class FeedEntry(TypedDict, total=False):
    name: str
    url: str
    tier: int       # 1-4
    region: str     # ISO-like region code
    category: str   # politics, middleeast, defense, etc.
    propaganda_risk: str  # low, medium, high
    state_affiliated: str  # country code or empty


# ── Propaganda Risk Profiles ──
# Determines how much weight filter.py gives each source

SOURCE_PROPAGANDA_RISK: dict[str, dict] = {
    # HIGH risk — State-controlled media
    "Xinhua":      {"risk": "high", "state": "CN", "note": "Official CCP news agency"},
    "TASS":        {"risk": "high", "state": "RU", "note": "Russian state news agency"},
    "RT":          {"risk": "high", "state": "RU", "note": "Russian state media, banned in EU"},
    "RT Russia":   {"risk": "high", "state": "RU", "note": "Russian state media"},
    "Sputnik":     {"risk": "high", "state": "RU", "note": "Russian state media"},
    "CGTN":        {"risk": "high", "state": "CN", "note": "Chinese state broadcaster"},
    "Press TV":    {"risk": "high", "state": "IR", "note": "Iranian state media"},
    "KCNA":        {"risk": "high", "state": "KP", "note": "North Korean state media"},
    "Fars News":   {"risk": "high", "state": "IR", "note": "Iranian semi-state agency"},

    # MEDIUM risk — State-affiliated or known bias
    "Al Jazeera":        {"risk": "medium", "state": "QA", "note": "Qatari state-funded"},
    "Al Arabiya":        {"risk": "medium", "state": "SA", "note": "Saudi-owned"},
    "TRT World":         {"risk": "medium", "state": "TR", "note": "Turkish state broadcaster"},
    "France 24":         {"risk": "medium", "state": "FR", "note": "French state-funded"},
    "DW News":           {"risk": "medium", "state": "DE", "note": "German state-funded"},
    "Voice of America":  {"risk": "medium", "state": "US", "note": "US government-funded"},
    "Kyiv Independent":  {"risk": "medium", "state": "",   "note": "Pro-Ukraine perspective"},
    "Moscow Times":      {"risk": "medium", "state": "",   "note": "Anti-Kremlin independent"},
    "NHK World":         {"risk": "medium", "state": "JP", "note": "Japanese public broadcaster"},

    # LOW risk — Independent with editorial standards
    "Reuters":       {"risk": "low", "state": "", "note": "Wire service"},
    "AP News":       {"risk": "low", "state": "", "note": "Wire service, nonprofit"},
    "AFP":           {"risk": "low", "state": "", "note": "Wire service"},
    "BBC World":     {"risk": "low", "state": "", "note": "Public broadcaster"},
    "BBC Middle East": {"risk": "low", "state": "", "note": "Public broadcaster"},
    "Guardian World": {"risk": "low", "state": "", "note": "Center-left, Scott Trust"},
    "Financial Times": {"risk": "low", "state": "", "note": "Business focus"},
    "Bellingcat":    {"risk": "low", "state": "", "note": "Open-source investigations"},
    "CNBC":          {"risk": "low", "state": "", "note": "Business news"},
    "Bloomberg":     {"risk": "low", "state": "", "note": "Financial wire service"},
}


def get_propaganda_risk(source_name: str) -> dict:
    """Return propaganda risk profile for a source (default: low)."""
    return SOURCE_PROPAGANDA_RISK.get(source_name, {"risk": "low", "state": "", "note": ""})


# ── Source Type Classification ──

SOURCE_TYPE_MAP: dict[str, str] = {
    # Wire services — fastest, most authoritative
    "Reuters": "wire", "Reuters World": "wire", "Reuters Business": "wire",
    "AP News": "wire", "AFP": "wire", "Bloomberg": "wire",
    "ANSA": "wire", "Xinhua": "wire", "TASS": "wire",
    # Government & international org
    "White House": "gov", "State Dept": "gov", "Pentagon": "gov",
    "UN News": "gov", "CISA": "gov", "IAEA": "gov", "WHO": "gov", "UNHCR": "gov",
    "Federal Reserve": "gov", "SEC": "gov", "CDC": "gov",
    # Intel/defense specialty
    "Defense One": "intel", "Breaking Defense": "intel", "The War Zone": "intel",
    "Defense News": "intel", "Janes": "intel", "Military Times": "intel",
    "USNI News": "intel", "Bellingcat": "intel", "Foreign Policy": "intel",
    "Foreign Affairs": "intel", "CSIS": "intel", "RAND": "intel",
    "Brookings": "intel", "Carnegie": "intel", "Atlantic Council": "intel",
    # Mainstream
    "BBC World": "mainstream", "BBC Middle East": "mainstream",
    "Guardian World": "mainstream", "Al Jazeera": "mainstream",
    "CNN World": "mainstream", "NPR News": "mainstream",
    # Market/Finance
    "CNBC": "market", "MarketWatch": "market", "Financial Times": "market",
    "Yahoo Finance": "market",
}


def get_source_type(source_name: str) -> str:
    """Return source type: wire, gov, intel, mainstream, market, tech, other."""
    return SOURCE_TYPE_MAP.get(source_name, "other")


# ── RSS Feed Catalog ──
# Curated from WorldMonitor (435+ feeds across 15+ categories)
# Each entry: {"name": str, "url": str, "tier": 1-4, "region": str, "category": str}
# URLs use Google News RSS proxy where direct feeds are blocked from cloud IPs

RSS_CATALOG: list[FeedEntry] = [
    # ━━━ POLITICS / WORLD NEWS ━━━
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
     "tier": 1, "region": "UK", "category": "politics"},
    {"name": "Guardian World", "url": "https://www.theguardian.com/world/rss",
     "tier": 1, "region": "UK", "category": "politics"},
    {"name": "AP News", "url": "https://news.google.com/rss/search?q=site:apnews.com&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "US", "category": "politics"},
    {"name": "Reuters World", "url": "https://news.google.com/rss/search?q=site:reuters.com+world&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "MULTI", "category": "politics"},
    {"name": "CNN World", "url": "https://news.google.com/rss/search?q=site:cnn.com+world+news+when:1d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "US", "category": "politics"},

    # ━━━ US NEWS ━━━
    {"name": "NPR News", "url": "https://feeds.npr.org/1001/rss.xml",
     "tier": 2, "region": "US", "category": "us"},
    {"name": "PBS NewsHour", "url": "https://www.pbs.org/newshour/feeds/rss/headlines",
     "tier": 2, "region": "US", "category": "us"},
    {"name": "Politico", "url": "https://rss.politico.com/politics-news.xml",
     "tier": 2, "region": "US", "category": "us"},
    {"name": "Axios", "url": "https://api.axios.com/feed/",
     "tier": 2, "region": "US", "category": "us"},
    {"name": "Wall Street Journal", "url": "https://feeds.content.dowjones.io/public/rss/RSSUSnews",
     "tier": 1, "region": "US", "category": "us"},

    # ━━━ EUROPE ━━━
    {"name": "France 24", "url": "https://www.france24.com/en/rss",
     "tier": 2, "region": "EU", "category": "europe"},
    {"name": "EuroNews", "url": "https://www.euronews.com/rss?format=xml",
     "tier": 2, "region": "EU", "category": "europe"},
    {"name": "DW News", "url": "https://rss.dw.com/xml/rss-en-all",
     "tier": 2, "region": "EU", "category": "europe"},
    {"name": "Le Monde", "url": "https://www.lemonde.fr/en/rss/une.xml",
     "tier": 2, "region": "EU", "category": "europe"},
    {"name": "Tagesschau", "url": "https://www.tagesschau.de/xml/rss2/",
     "tier": 2, "region": "EU", "category": "europe"},
    {"name": "Der Spiegel", "url": "https://www.spiegel.de/schlagzeilen/tops/index.rss",
     "tier": 2, "region": "EU", "category": "europe"},
    {"name": "ANSA", "url": "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml",
     "tier": 1, "region": "EU", "category": "europe"},
    {"name": "NOS Nieuws", "url": "https://feeds.nos.nl/nosnieuwsalgemeen",
     "tier": 2, "region": "EU", "category": "europe"},
    {"name": "SVT Nyheter", "url": "https://www.svt.se/nyheter/rss.xml",
     "tier": 2, "region": "EU", "category": "europe"},
    # Greek
    {"name": "Kathimerini", "url": "https://news.google.com/rss/search?q=site:kathimerini.gr+when:2d&hl=el&gl=GR&ceid=GR:el",
     "tier": 2, "region": "EU", "category": "europe"},
    {"name": "Naftemporiki", "url": "https://www.naftemporiki.gr/feed/",
     "tier": 2, "region": "EU", "category": "europe"},
    # Turkey
    {"name": "Hurriyet", "url": "https://www.hurriyet.com.tr/rss/anasayfa",
     "tier": 3, "region": "EU", "category": "europe"},
    # Poland
    {"name": "TVN24", "url": "https://tvn24.pl/swiat.xml",
     "tier": 2, "region": "EU", "category": "europe"},
    # Russia/Ukraine independent
    {"name": "BBC Russian", "url": "https://feeds.bbci.co.uk/russian/rss.xml",
     "tier": 2, "region": "RU", "category": "europe"},
    {"name": "Meduza", "url": "https://meduza.io/rss/all",
     "tier": 2, "region": "RU", "category": "europe"},
    {"name": "TASS", "url": "https://news.google.com/rss/search?q=site:tass.com+OR+TASS+Russia+when:1d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "RU", "category": "europe"},
    {"name": "RT", "url": "https://www.rt.com/rss/",
     "tier": 3, "region": "RU", "category": "europe"},
    {"name": "Kyiv Independent", "url": "https://news.google.com/rss/search?q=site:kyivindependent.com+when:3d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "EU", "category": "europe"},
    {"name": "Moscow Times", "url": "https://www.themoscowtimes.com/rss/news",
     "tier": 2, "region": "RU", "category": "europe"},

    # ━━━ MIDDLE EAST ━━━
    {"name": "BBC Middle East", "url": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
     "tier": 1, "region": "ME", "category": "middleeast"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml",
     "tier": 2, "region": "ME", "category": "middleeast"},
    {"name": "Al Arabiya", "url": "https://news.google.com/rss/search?q=site:english.alarabiya.net+when:2d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "ME", "category": "middleeast"},
    {"name": "Guardian ME", "url": "https://www.theguardian.com/world/middleeast/rss",
     "tier": 2, "region": "ME", "category": "middleeast"},
    {"name": "Iran International", "url": "https://news.google.com/rss/search?q=site:iranintl.com+when:2d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "ME", "category": "middleeast"},
    {"name": "Fars News", "url": "https://news.google.com/rss/search?q=site:farsnews.ir+when:2d&hl=en-US&gl=US&ceid=US:en",
     "tier": 3, "region": "ME", "category": "middleeast"},
    {"name": "Haaretz", "url": "https://news.google.com/rss/search?q=site:haaretz.com+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "ME", "category": "middleeast"},
    {"name": "Arab News", "url": "https://news.google.com/rss/search?q=site:arabnews.com+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "ME", "category": "middleeast"},
    {"name": "The National", "url": "https://news.google.com/rss/search?q=site:thenationalnews.com+when:2d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "ME", "category": "middleeast"},
    {"name": "Asharq Business", "url": "https://asharqbusiness.com/rss.xml",
     "tier": 2, "region": "ME", "category": "middleeast"},
    {"name": "Rudaw", "url": "https://news.google.com/rss/search?q=site:rudaw.net+when:7d&hl=en&gl=US&ceid=US:en",
     "tier": 3, "region": "ME", "category": "middleeast"},

    # ━━━ ASIA-PACIFIC ━━━
    {"name": "BBC Asia", "url": "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
     "tier": 1, "region": "JP", "category": "asia"},
    {"name": "The Diplomat", "url": "https://thediplomat.com/feed/",
     "tier": 2, "region": "JP", "category": "asia"},
    {"name": "South China Morning Post", "url": "https://www.scmp.com/rss/91/feed/",
     "tier": 2, "region": "CN", "category": "asia"},
    {"name": "Reuters Asia", "url": "https://news.google.com/rss/search?q=site:reuters.com+(China+OR+Japan+OR+Taiwan+OR+Korea)+when:3d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "MULTI", "category": "asia"},
    {"name": "Xinhua", "url": "https://news.google.com/rss/search?q=site:xinhuanet.com+OR+Xinhua+when:1d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "CN", "category": "asia"},
    {"name": "Nikkei Asia", "url": "https://news.google.com/rss/search?q=site:asia.nikkei.com+when:3d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "JP", "category": "asia"},
    {"name": "The Hindu", "url": "https://www.thehindu.com/news/national/feeder/default.rss",
     "tier": 2, "region": "IN", "category": "asia"},
    {"name": "Indian Express", "url": "https://indianexpress.com/section/india/feed/",
     "tier": 2, "region": "IN", "category": "asia"},
    {"name": "CNA", "url": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml",
     "tier": 2, "region": "MULTI", "category": "asia"},
    {"name": "NHK World", "url": "https://www3.nhk.or.jp/rss/news/cat0.xml",
     "tier": 2, "region": "JP", "category": "asia"},

    # ━━━ AFRICA ━━━
    {"name": "BBC Africa", "url": "https://feeds.bbci.co.uk/news/world/africa/rss.xml",
     "tier": 1, "region": "AF", "category": "africa"},
    {"name": "News24", "url": "https://feeds.news24.com/articles/news24/TopStories/rss",
     "tier": 2, "region": "AF", "category": "africa"},
    {"name": "Africa News", "url": "https://news.google.com/rss/search?q=(Africa+OR+Nigeria+OR+Kenya+OR+South+Africa+OR+Ethiopia)+when:2d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "AF", "category": "africa"},
    {"name": "Sahel Crisis", "url": "https://news.google.com/rss/search?q=(Sahel+OR+Mali+OR+Niger+OR+Burkina+Faso+OR+Wagner)+when:3d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "AF", "category": "africa"},
    {"name": "Premium Times", "url": "https://www.premiumtimesng.com/feed",
     "tier": 3, "region": "AF", "category": "africa"},
    {"name": "Channels TV", "url": "https://www.channelstv.com/feed/",
     "tier": 3, "region": "AF", "category": "africa"},

    # ━━━ LATIN AMERICA ━━━
    {"name": "BBC Latin America", "url": "https://feeds.bbci.co.uk/news/world/latin_america/rss.xml",
     "tier": 1, "region": "LATAM", "category": "latam"},
    {"name": "Reuters LatAm", "url": "https://news.google.com/rss/search?q=site:reuters.com+(Brazil+OR+Mexico+OR+Argentina)+when:3d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "LATAM", "category": "latam"},
    {"name": "Guardian Americas", "url": "https://www.theguardian.com/world/americas/rss",
     "tier": 2, "region": "LATAM", "category": "latam"},
    {"name": "InSight Crime", "url": "https://insightcrime.org/feed/",
     "tier": 2, "region": "LATAM", "category": "latam"},
    {"name": "Mexico News Daily", "url": "https://mexiconewsdaily.com/feed/",
     "tier": 3, "region": "LATAM", "category": "latam"},
    {"name": "Infobae Americas", "url": "https://www.infobae.com/arc/outboundfeeds/rss/",
     "tier": 2, "region": "LATAM", "category": "latam"},

    # ━━━ ENERGY ━━━
    {"name": "Oil & Gas", "url": "https://news.google.com/rss/search?q=(oil+price+OR+OPEC+OR+natural+gas+OR+pipeline+OR+LNG)+when:2d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "MULTI", "category": "energy"},
    {"name": "Nuclear Energy", "url": "https://news.google.com/rss/search?q=(nuclear+energy+OR+nuclear+power+OR+uranium+OR+IAEA)+when:3d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "MULTI", "category": "energy"},
    {"name": "Reuters Energy", "url": "https://news.google.com/rss/search?q=site:reuters.com+(oil+OR+gas+OR+energy+OR+OPEC)+when:3d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "MULTI", "category": "energy"},
    {"name": "Mining & Resources", "url": "https://news.google.com/rss/search?q=(lithium+OR+rare+earth+OR+cobalt+OR+mining)+when:3d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "MULTI", "category": "energy"},
    {"name": "OilPrice.com", "url": "https://oilprice.com/rss/main",
     "tier": 3, "region": "MULTI", "category": "energy"},

    # ━━━ FINANCE ━━━
    {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
     "tier": 2, "region": "US", "category": "finance"},
    {"name": "MarketWatch", "url": "https://news.google.com/rss/search?q=site:marketwatch.com+markets+when:1d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "US", "category": "finance"},
    {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex",
     "tier": 2, "region": "US", "category": "finance"},
    {"name": "Financial Times", "url": "https://www.ft.com/rss/home",
     "tier": 1, "region": "UK", "category": "finance"},
    {"name": "Reuters Business", "url": "https://news.google.com/rss/search?q=site:reuters.com+business+markets&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "MULTI", "category": "finance"},
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
     "tier": 2, "region": "MULTI", "category": "finance"},
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss",
     "tier": 2, "region": "MULTI", "category": "finance"},

    # ━━━ FINANCE — Earnings & Corporate ━━━
    {"name": "Seeking Alpha Market News", "url": "https://seekingalpha.com/market_currents.xml",
     "tier": 2, "region": "US", "category": "finance"},
    {"name": "Zacks Earnings", "url": "https://www.zacks.com/feeds/?type=earnings",
     "tier": 2, "region": "US", "category": "finance"},
    {"name": "Bloomberg Markets", "url": "https://news.google.com/rss/search?q=site:bloomberg.com+markets+when:1d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "MULTI", "category": "finance"},
    {"name": "Wall Street Journal Markets", "url": "https://news.google.com/rss/search?q=site:wsj.com+markets+when:1d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "US", "category": "finance"},
    {"name": "Barron's", "url": "https://news.google.com/rss/search?q=site:barrons.com+when:1d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "US", "category": "finance"},

    # ━━━ FINANCE — Central Banks & Monetary Policy ━━━
    {"name": "Fed FOMC Statements", "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
     "tier": 1, "region": "US", "category": "finance"},
    {"name": "Fed Speeches", "url": "https://www.federalreserve.gov/feeds/speeches.xml",
     "tier": 1, "region": "US", "category": "finance"},
    {"name": "ECB Press Releases", "url": "https://www.ecb.europa.eu/rss/press.html",
     "tier": 1, "region": "EU", "category": "finance"},
    {"name": "Bank of England", "url": "https://news.google.com/rss/search?q=site:bankofengland.co.uk+OR+%22Bank+of+England%22+monetary+policy+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "UK", "category": "finance"},
    {"name": "Bank of Japan", "url": "https://news.google.com/rss/search?q=%22Bank+of+Japan%22+OR+BOJ+monetary+policy+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "ASIA", "category": "finance"},
    {"name": "BIS Research", "url": "https://www.bis.org/doclist/all_research.rss",
     "tier": 1, "region": "MULTI", "category": "finance"},
    {"name": "IMF Blog", "url": "https://www.imf.org/en/Blogs/rss",
     "tier": 1, "region": "MULTI", "category": "finance"},

    # ━━━ FINANCE — Sovereign Debt & Macro ━━━
    {"name": "Fitch Ratings", "url": "https://news.google.com/rss/search?q=site:fitchratings.com+OR+%22Fitch+Ratings%22+sovereign+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "MULTI", "category": "finance"},
    {"name": "Moody's Ratings", "url": "https://news.google.com/rss/search?q=%22Moody%27s%22+sovereign+rating+credit+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "MULTI", "category": "finance"},
    {"name": "S&P Global Ratings", "url": "https://news.google.com/rss/search?q=%22S%26P+Global%22+sovereign+rating+credit+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "MULTI", "category": "finance"},
    {"name": "World Bank Economy", "url": "https://news.google.com/rss/search?q=site:worldbank.org+economy+debt+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "MULTI", "category": "finance"},

    # ━━━ GOVERNMENT / OFFICIAL ━━━
    {"name": "White House", "url": "https://news.google.com/rss/search?q=site:whitehouse.gov&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "US", "category": "gov"},
    {"name": "State Dept", "url": "https://news.google.com/rss/search?q=site:state.gov+OR+State+Department&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "US", "category": "gov"},
    {"name": "Pentagon", "url": "https://news.google.com/rss/search?q=site:defense.gov+OR+Pentagon&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "US", "category": "gov"},
    {"name": "UN News", "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
     "tier": 1, "region": "MULTI", "category": "gov"},
    {"name": "CISA", "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
     "tier": 1, "region": "US", "category": "gov"},
    {"name": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml",
     "tier": 1, "region": "US", "category": "gov"},
    {"name": "SEC", "url": "https://www.sec.gov/news/pressreleases.rss",
     "tier": 1, "region": "US", "category": "gov"},

    # ━━━ CRISIS / HUMANITARIAN ━━━
    {"name": "CrisisWatch", "url": "https://www.crisisgroup.org/rss",
     "tier": 2, "region": "MULTI", "category": "crisis"},
    {"name": "IAEA", "url": "https://www.iaea.org/feeds/topnews",
     "tier": 1, "region": "MULTI", "category": "crisis"},
    {"name": "WHO", "url": "https://www.who.int/rss-feeds/news-english.xml",
     "tier": 1, "region": "MULTI", "category": "crisis"},
    {"name": "UNHCR", "url": "https://news.google.com/rss/search?q=site:unhcr.org+OR+UNHCR+refugees+when:3d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "MULTI", "category": "crisis"},

    # ━━━ TECH / AI ━━━
    {"name": "Hacker News", "url": "https://hnrss.org/frontpage",
     "tier": 3, "region": "US", "category": "tech"},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/technology-lab",
     "tier": 2, "region": "US", "category": "tech"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml",
     "tier": 2, "region": "US", "category": "tech"},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/",
     "tier": 2, "region": "US", "category": "tech"},
    {"name": "AI News", "url": "https://news.google.com/rss/search?q=(OpenAI+OR+Anthropic+OR+Google+AI+OR+large+language+model+OR+ChatGPT)+when:2d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "MULTI", "category": "tech"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/",
     "tier": 2, "region": "US", "category": "tech"},
    {"name": "ArXiv AI", "url": "https://export.arxiv.org/rss/cs.AI",
     "tier": 2, "region": "MULTI", "category": "tech"},

    # ━━━ THINK TANKS & INTEL ━━━
    {"name": "Foreign Policy", "url": "https://foreignpolicy.com/feed/",
     "tier": 2, "region": "US", "category": "thinktanks"},
    {"name": "Atlantic Council", "url": "https://www.atlanticcouncil.org/feed/",
     "tier": 2, "region": "US", "category": "thinktanks"},
    {"name": "Foreign Affairs", "url": "https://www.foreignaffairs.com/rss.xml",
     "tier": 1, "region": "US", "category": "thinktanks"},
    {"name": "CSIS", "url": "https://news.google.com/rss/search?q=site:csis.org+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "US", "category": "thinktanks"},
    {"name": "RAND", "url": "https://www.rand.org/pubs/articles.xml",
     "tier": 2, "region": "US", "category": "thinktanks"},
    {"name": "Brookings", "url": "https://news.google.com/rss/search?q=site:brookings.edu+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "US", "category": "thinktanks"},
    {"name": "Carnegie", "url": "https://news.google.com/rss/search?q=site:carnegieendowment.org+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "US", "category": "thinktanks"},
    {"name": "War on the Rocks", "url": "https://warontherocks.com/feed",
     "tier": 2, "region": "US", "category": "thinktanks"},
    {"name": "Responsible Statecraft", "url": "https://responsiblestatecraft.org/feed/",
     "tier": 2, "region": "US", "category": "thinktanks"},
    {"name": "RUSI", "url": "https://news.google.com/rss/search?q=site:rusi.org+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "UK", "category": "thinktanks"},
    {"name": "Jamestown", "url": "https://jamestown.org/feed/",
     "tier": 2, "region": "US", "category": "thinktanks"},

    # ━━━ DEFENSE / MILITARY ━━━
    {"name": "Defense One", "url": "https://www.defenseone.com/rss/all/",
     "tier": 2, "region": "US", "category": "defense"},
    {"name": "The War Zone", "url": "https://www.twz.com/feed",
     "tier": 2, "region": "US", "category": "defense"},
    {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
     "tier": 2, "region": "US", "category": "defense"},
    {"name": "Janes", "url": "https://news.google.com/rss/search?q=site:janes.com+when:3d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "UK", "category": "defense"},
    {"name": "Military Times", "url": "https://www.militarytimes.com/arc/outboundfeeds/rss/?outputType=xml",
     "tier": 2, "region": "US", "category": "defense"},
    {"name": "Task & Purpose", "url": "https://taskandpurpose.com/feed/",
     "tier": 2, "region": "US", "category": "defense"},
    {"name": "USNI News", "url": "https://news.google.com/rss/search?q=site:news.usni.org+when:3d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "US", "category": "defense"},
    {"name": "gCaptain", "url": "https://gcaptain.com/feed/",
     "tier": 3, "region": "US", "category": "defense"},
    {"name": "Oryx OSINT", "url": "https://www.oryxspioenkop.com/feeds/posts/default?alt=rss",
     "tier": 2, "region": "EU", "category": "defense"},
    {"name": "UK MOD", "url": "https://www.gov.uk/government/organisations/ministry-of-defence.atom",
     "tier": 1, "region": "UK", "category": "defense"},

    # ━━━ NUCLEAR & ARMS CONTROL ━━━
    {"name": "Arms Control Assn", "url": "https://news.google.com/rss/search?q=site:armscontrol.org+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "US", "category": "nuclear"},
    {"name": "Bulletin of Atomic Scientists", "url": "https://news.google.com/rss/search?q=site:thebulletin.org+when:7d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "US", "category": "nuclear"},

    # ━━━ OSINT & CYBER ━━━
    {"name": "Bellingcat", "url": "https://news.google.com/rss/search?q=site:bellingcat.com+when:30d&hl=en-US&gl=US&ceid=US:en",
     "tier": 2, "region": "MULTI", "category": "osint"},
    {"name": "Krebs Security", "url": "https://krebsonsecurity.com/feed/",
     "tier": 2, "region": "US", "category": "cyber"},
    {"name": "Ransomware.live", "url": "https://www.ransomware.live/rss.xml",
     "tier": 3, "region": "MULTI", "category": "cyber"},

    # ━━━ FOOD SECURITY & ECONOMIC INTEL ━━━
    {"name": "FAO News", "url": "https://www.fao.org/feeds/fao-newsroom-rss",
     "tier": 1, "region": "MULTI", "category": "economic"},
    {"name": "FAO GIEWS", "url": "https://news.google.com/rss/search?q=site:fao.org+GIEWS+food+security+when:30d&hl=en-US&gl=US&ceid=US:en",
     "tier": 1, "region": "MULTI", "category": "economic"},
]

# ── Alert Keywords ──
# Triggers high-salience classification (ported from WorldMonitor)

ALERT_KEYWORDS = [
    "war", "invasion", "military", "nuclear", "sanctions", "missile",
    "airstrike", "drone strike", "troops deployed", "armed conflict",
    "bombing", "casualties", "ceasefire", "peace treaty", "nato", "coup",
    "martial law", "assassination", "terrorist", "terror attack",
    "cyber attack", "hostage", "evacuation order",
]

# Patterns that indicate non-alert content (lifestyle, entertainment, etc.)
ALERT_EXCLUSIONS = [
    "protein", "couples", "relationship", "dating", "diet", "fitness",
    "recipe", "cooking", "shopping", "fashion", "celebrity", "movie",
    "tv show", "sports", "game", "concert", "festival", "wedding",
    "vacation", "travel tips", "life hack", "self-care", "wellness",
]


# ── Headline Importance Scoring ──
# Multi-signal keyword scoring (ported from WorldMonitor algorithms.mdx)

HEADLINE_SCORE_CATEGORIES = {
    "violence": {
        "base": 100, "per_match": 25,
        "keywords": ["killed", "dead", "death", "shot", "casualty", "massacre",
                      "crackdown", "execution", "beheading", "bombing"],
    },
    "military": {
        "base": 80, "per_match": 20,
        "keywords": ["war", "invasion", "airstrike", "missile", "troops",
                      "combat", "fleet", "deployment", "artillery", "drone strike"],
    },
    "unrest": {
        "base": 40, "per_match": 15,
        "keywords": ["protest", "uprising", "riot", "demonstration", "revolution",
                      "coup", "strike", "unrest", "civil disobedience"],
    },
    "flashpoint": {
        "base": 0, "per_match": 20,
        "keywords": ["iran", "russia", "china", "taiwan", "ukraine", "israel",
                      "gaza", "north korea", "syria", "yemen", "hamas",
                      "hezbollah", "nato", "kremlin"],
    },
    "crisis": {
        "base": 0, "per_match": 10,
        "keywords": ["sanctions", "escalation", "breaking", "urgent",
                      "humanitarian", "emergency", "collapse", "default"],
    },
    "financial_systemic": {
        "base": 60, "per_match": 15,
        "keywords": ["rate cut", "rate hike", "fomc", "quantitative easing",
                      "bank run", "credit crisis", "debt ceiling", "yield curve",
                      "sovereign default", "currency crisis", "capital flight",
                      "bailout", "systemic risk", "contagion", "liquidity crisis"],
    },
    "financial_signal": {
        "base": 0, "per_match": 10,
        "keywords": ["earnings surprise", "fed", "central bank", "treasury",
                      "downgrade", "upgrade", "recession", "inflation",
                      "deflation", "stagflation", "bond market", "credit spread"],
    },
}

# Demotion keywords — reduce score for pure corporate/celebrity noise
# NOTE: financial terms (earnings, stock, revenue, etc.) were removed
# after financial expansion — they are now signal, not noise.
DEMOTION_KEYWORDS = [
    "ceo", "startup", "ipo", "celebrity", "influencer",
    "lifestyle", "entertainment", "gossip", "viral",
]


def score_headline(headline: str) -> int:
    """Score a headline by geopolitical significance (0-500+).

    Uses multi-signal keyword scoring from WorldMonitor.
    Higher scores = more geopolitically significant.
    """
    text = headline.lower()
    total = 0

    for category in HEADLINE_SCORE_CATEGORIES.values():
        matches = sum(1 for kw in category["keywords"] if kw in text)
        if matches > 0:
            total += category["base"] + (matches * category["per_match"])

    # Demotion for corporate noise
    demotions = sum(1 for kw in DEMOTION_KEYWORDS if kw in text)
    total -= demotions * 15

    return max(0, total)


def get_feeds_by_category(category: str) -> list[FeedEntry]:
    """Return all feeds for a specific category."""
    return [f for f in RSS_CATALOG if f.get("category") == category]


def get_all_categories() -> list[str]:
    """Return all unique feed categories."""
    return sorted(set(f.get("category", "") for f in RSS_CATALOG))

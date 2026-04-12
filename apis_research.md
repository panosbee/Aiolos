# XDART-Φ — Open APIs Research
## Πλουραλιστική Κάλυψη: Ειδήσεις, Οικονομικά, Γεωπολιτικά

---

## 🟢 100% ΔΩΡΕΑΝ — Χωρίς API Key

### 1. GDELT DOC 2.0 API ⭐⭐⭐ (ΚΟΡΥΦΑΙΑ ΠΗΓΗ)
- **Τι είναι**: Η μεγαλύτερη ανοιχτή βάση δεδομένων ανθρώπινης κοινωνίας
- **URL**: `https://api.gdeltproject.org/api/v2/doc/doc?query=...&mode=artlist&format=json`
- **Κόστος**: 100% δωρεάν, χωρίς API key, χωρίς εγγραφή
- **Κάλυψη**: 65+ γλώσσες, 130+ χώρες, ενημέρωση κάθε 15 λεπτά
- **Δυνατότητες**:
  - Fulltext search σε παγκόσμιες ειδήσεις (μεταφρασμένες στα αγγλικά)
  - Filter ανά χώρα: `sourcecountry:china`, `sourcecountry:nigeria`, `sourcecountry:brazil`
  - Filter ανά γλώσσα: `sourcelang:arabic`, `sourcelang:chinese`
  - Tone analysis (θετικές/αρνητικές ειδήσεις)
  - Themes: `theme:TERROR`, `theme:ECON_*`, `theme:ENV_*`
  - Timelines, word clouds, article lists
- **Output**: JSON, CSV, HTML, RSS
- **Ιδανικό για**: Πολυπρισματική κάλυψη — βλέπεις πώς αναφέρεται ένα θέμα σε Κίνα vs ΗΠΑ vs Αφρική
- **Παράδειγμα**: `https://api.gdeltproject.org/api/v2/doc/doc?query="trade war"&mode=artlist&format=json&maxrecords=50`

### 2. World Bank API ⭐⭐⭐
- **Τι είναι**: 16,000+ δείκτες, 45+ βάσεις δεδομένων
- **URL**: `https://api.worldbank.org/v2/country/{code}/indicator/{indicator}?format=json`
- **Κόστος**: 100% δωρεάν, χωρίς API key
- **Κάλυψη**: Όλες οι χώρες, δεδομένα 50+ ετών
- **Δεδομένα**: GDP, φτώχεια, χρέος, εμπόριο, υγεία, εκπαίδευση, πληθυσμός
- **Παράδειγμα**: `https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CD?format=json&per_page=50`
- **Ιδανικό για**: Μακροοικονομικά, αναπτυξιακά δεδομένα, σύγκριση χωρών

### 3. OECD API ⭐⭐
- **Τι είναι**: Οικονομικά δεδομένα ανεπτυγμένων κρατών
- **URL**: `https://sdmx.oecd.org/public/rest/data/{dataset}/...?format=jsondata`
- **Κόστος**: 100% δωρεάν, χωρίς API key
- **Κάλυψη**: 38 χώρες OECD
- **Δεδομένα**: GDP, εμπόριο, απασχόληση, πληθωρισμός, δείκτες CLI
- **Output**: JSON, CSV, XML

### 4. IMF SDMX API ⭐⭐
- **Τι είναι**: Διεθνές Νομισματικό Ταμείο
- **URL**: `https://dataservices.imf.org/REST/SDMX_JSON.svc/`
- **Κόστος**: 100% δωρεάν
- **Δεδομένα**: Ισοζύγια πληρωμών, δημοσιονομικά, νομισματικά, εμπόριο
- **Κάλυψη**: 190+ χώρες

### 5. ReliefWeb API (UN OCHA) ⭐⭐⭐
- **Τι είναι**: Ανθρωπιστικές κρίσεις, καταστροφές — αξιόπιστη UN πηγή
- **URL**: `https://api.reliefweb.int/v2/reports?appname=xdart`
- **Κόστος**: Δωρεάν (χρειάζεται μόνο appname parameter, όχι κλειδί)
- **Κάλυψη**: Παγκόσμια, από 1996 μέχρι σήμερα, real-time
- **Δεδομένα**: Reports, disasters, crises ανά χώρα
- **Limit**: 1000 calls/day
- **Ιδανικό για**: Ανθρωπιστικές κρίσεις, φυσικές καταστροφές, conflicts

---

## 🟡 ΔΩΡΕΑΝ TIER — Με API Key (Εγγραφή)

### 6. FRED API (Federal Reserve) ⭐⭐⭐
- **Τι είναι**: 816,000+ οικονομικές χρονοσειρές
- **URL**: `https://api.stlouisfed.org/fred/series/observations?series_id=GDP&api_key=...&file_type=json`
- **Κόστος**: Δωρεάν API key (instant registration)
- **Κάλυψη**: Κυρίως ΗΠΑ αλλά και διεθνή
- **Δεδομένα**: GDP, ανεργία, πληθωρισμός (CPI), επιτόκια, Fed Funds Rate, S&P 500, M2
- **Limit**: Χωρίς limit (fair use)
- **Ιδανικό για**: Μακροοικονομικά US + παγκόσμια

### 7. GNews API ⭐⭐
- **Τι είναι**: 80,000+ πηγές, based on Google News rankings
- **URL**: `https://gnews.io/api/v4/search?q=...&lang=en&max=10&apikey=...`
- **Κόστος**: Free tier = 100 requests/day
- **Κάλυψη**: Πολλές γλώσσες + χώρες
- **Ιδανικό για**: Curated top headlines, category-based news

### 8. MediaStack ⭐
- **Τι είναι**: 7,500+ πηγές, 50+ χώρες
- **URL**: `https://api.mediastack.com/v1/news?access_key=...&countries=us,cn,ng&languages=en`
- **Κόστος**: Free tier = 500 requests/μήνα (30min delay)
- **Κάλυψη**: Multi-country, multi-language
- **Ιδανικό για**: Quick multi-region headlines

### 9. The Guardian Open Platform ⭐⭐
- **Τι είναι**: Full API στο περιεχόμενο του Guardian
- **URL**: `https://content.guardianapis.com/search?q=...&api-key=...`
- **Κόστος**: Δωρεάν API key
- **Κάλυψη**: UK, US, Australia, World sections
- **Ιδανικό για**: Ποιοτική ευρωπαϊκή δημοσιογραφία, πλήρη κείμενα

### 10. ExchangeRate-API ⭐⭐
- **Τι είναι**: Συναλλαγματικές ισοτιμίες
- **URL**: `https://v6.exchangerate-api.com/v6/{key}/latest/USD`
- **Κόστος**: Free tier = 1,500 requests/μήνα
- **Κάλυψη**: 160+ νομίσματα

### 11. Commodities-API ⭐⭐
- **Τι είναι**: Τιμές εμπορευμάτων (χρυσός, πετρέλαιο, σιτάρι, ρύζι)
- **URL**: `https://commodities-api.com/api/latest?access_key=...&symbols=XAU,BRENT,WHEAT`
- **Κόστος**: Free tier = 100 requests/μήνα
- **Δεδομένα**: Real-time + historical από 1969, OHLC
- **Ιδανικό για**: Commodity trends, economic indicators

### 12. ACLED (Armed Conflict Location & Event Data) ⭐⭐⭐
- **Τι είναι**: Δεδομένα πολιτικής βίας & συγκρούσεων, event-level
- **URL**: `https://api.acleddata.com/acled/read?...`
- **Κόστος**: Δωρεάν με εγγραφή
- **Κάλυψη**: Αφρική, Ασία, Μ.Ανατολή, Λ.Αμερική, Ευρώπη — real-time
- **Δεδομένα**: Τύπος γεγονότος, actors, τοποθεσία, fatalities, ημερομηνία
- **Ιδανικό για**: Γεωπολιτικές εντάσεις, conflicts, πολιτική αστάθεια

---

## 🗺️ ΧΑΡΤΗΣ ΠΛΟΥΡΑΛΙΣΤΙΚΗΣ ΚΑΛΥΨΗΣ

| Περιοχή  | Ειδήσεις           | Οικονομικά           | Κρίσεις/Γεωπολιτικά   |
|----------|---------------------|----------------------|------------------------|
| Ασία     | GDELT (sourcelang:chinese/japanese/korean) | World Bank, IMF | ACLED, ReliefWeb |
| Ευρώπη   | GDELT, Guardian     | OECD, ECB/IMF        | ReliefWeb              |
| Αμερική  | GDELT (en/es/pt)    | FRED, World Bank     | ACLED, ReliefWeb       |
| Αφρική   | GDELT (sourcelang:arabic + sourcecountry:*) | World Bank, IMF | ACLED, ReliefWeb |
| M.Ανατολή| GDELT (sourcelang:arabic/persian) | IMF | ACLED, ReliefWeb |

---

## 🏗️ ΠΡΟΤΕΙΝΟΜΕΝΗ ΑΡΧΙΤΕΚΤΟΝΙΚΗ ΕΝΣΩΜΑΤΩΣΗΣ

### Tier 1 — Χωρίς API Key (άμεση ενσωμάτωση)
1. **GDELT** — Παγκόσμιες ειδήσεις, multi-perspective
2. **World Bank** — Μακροοικονομικά δεδομένα
3. **ReliefWeb** — Ανθρωπιστικές κρίσεις

### Tier 2 — Με δωρεάν API Key
4. **FRED** — Οικονομικές χρονοσειρές US + global
5. **GNews** — Curated news
6. **Guardian** — Ποιοτική δημοσιογραφία

### Tier 3 — Εξειδικευμένα
7. **ACLED** — Conflict data
8. **ExchangeRate-API** — Νομίσματα
9. **Commodities-API** — Εμπορεύματα
10. **OECD** — Δείκτες ανεπτυγμένων χωρών

---

## 🎯 ΑΡΧΗ: GDELT + World Bank + ReliefWeb

Αυτά τα 3 μαζί δίνουν:
- ✅ Ζωντανές ειδήσεις από κάθε γωνιά του πλανήτη (GDELT)
- ✅ Οικονομικά δεδομένα για κάθε χώρα (World Bank)
- ✅ Ανθρωπιστικές κρίσεις real-time (ReliefWeb)
- ✅ 0 κόστος, 0 API keys
- ✅ Πολυγλωσσική, πολυπρισματική κάλυψη
- ✅ Μόνο γεγονότα, χωρίς απόψεις (factual/event-based)

# MedDiscovery AI — Views Architecture
## Οι 24+ Οπτικές Γωνίες Εξέτασης Κάθε Υπόθεσης

> *«Δεν αλλάζουμε ερωτήσεις — ΑΚΟΥΜΕ με διαφορετικά αυτιά.»*

---

## ΕΠΙΣΚΟΠΗΣΗ

Κάθε υπόθεση εξετάζεται από **24+ διαφορετικές οπτικές γωνίες** οργανωμένες σε 5 κατηγορίες:

| Κατηγορία | Πλήθος | Πηγή |
|---|---|---|
| **A.** Question Reframing — External Angles | 6 | `question_reframer.py` |
| **B.** Question Reframing — Internal Blind Spots | 6 | `question_reframer.py` |
| **C.** Meta-Reasoning Perspectives | 6 | `meta_reasoning.py` |
| **D.** Strategy Modes | 4 | `query_strategy_advisor.py` |
| **E.** Decision & Flow Control | 4+4 | `orchestrator.py` |

---

## A. ΕΞΩΤΕΡΙΚΕΣ ΓΩΝΙΕΣ (External Angles)

Αυτές οι 6 γωνίες φέρνουν γνώση **ΕΞΩ** από το κυρίαρχο paradigm της νόσου.

### A1. Nature's Solutions (Η Λύση της Φύσης)
> **«Η Φύση αντιμετωπίζει ανάλογα προβλήματα εδώ και δισεκατομμύρια χρόνια. Τι μπορούμε να δανειστούμε;»**

| Πεδίο | Ερώτημα |
|---|---|
| Biomimicry | Πώς λύνουν παρόμοια προβλήματα τα φυτά/ζώα/μύκητες; |
| Ανοσοποιητικό | Πώς η φύση ήδη πολεμάει αυτή τη νόσο; |
| Ακραία περιβάλλοντα | Πώς επιβιώνουν ορισμένοι οργανισμοί σε extreme conditions; |
| Marine biology | Θαλάσσιοι μηχανισμοί → ανθρώπινη εφαρμογή |

**Novelty Score:** 0.70-0.85
**Παράδειγμα:** Τα δράκοντα Komodo αντέχουν βακτηριακά δηλητήρια → ανακάλυψη antimicrobial peptides

---

### A2. Vulnerability Analysis (Ανάλυση Ευπαθειών)
> **«Κάθε βιολογικό σύστημα έχει κρυφές ευπάθειες — θερμοδυναμικές, ενεργειακές, χωρικές»**

| Ευπάθεια | Ερώτημα |
|---|---|
| Θερμοδυναμική | Ποια ενεργειακά bottlenecks έχει η νόσος; |
| Χωρική | Πού εξαρτάται από φυσικό πέρασμα (BBB, membrane); |
| Χρονική | Πότε είναι πιο ευάλωτη (circadian, cell cycle); |
| Supply chain | Τι πρέπει να «εισάγει» ο παθογόνος/καρκινικός; |

**Novelty Score:** 0.75-0.90
**Παράδειγμα:** MRSA χρειάζεται σίδηρο → iron chelation starves the bacteria

---

### A3. Combination Logic (Λογική Συνδυασμού)
> **«Μονοθεραπεία = μονοδρόμηση. Πολλαπλοί στόχοι κάνουν αντίσταση μαθηματικά αδύνατη.»**

| Ζήτημα | Ερώτημα |
|---|---|
| Πολλαπλοί στόχοι | Ποιοι 3+ ανεξάρτητοι στόχοι εξαλείφουν πιθανότητα αντίστασης; |
| Χρονική αλληλουχία | Σημασία η σειρά; (πρώτα weakening, μετά killing) |
| Συνέργεια | Ποια ζεύγη φαρμάκων ενισχύονται 2+2=10; |
| Repurposing combo | Αποδεδειγμένα φάρμακα + νέα εφαρμογή σε combo |

**Novelty Score:** 0.60-0.80
**Παράδειγμα:** HIV triple therapy → P(resistance) < 10⁻³⁰

---

### A4. Cross-Domain Transfer (Διεπιστημονική Μεταφορά)
> **«Η λύση υπάρχει ήδη — σε ΑΛΛΟπεδίο. Φυσική, μηχανική, οικολογία, πληροφορική.»**

| Τομέας | Ερώτημα |
|---|---|
| Physics | Acoustics, optics, thermodynamics → βιολογική εφαρμογή |
| CS/AI | Αλγόριθμοι βελτιστοποίησης → drug scheduling |
| Ecology | Predator-prey dynamics → ανοσολογία |
| Materials science | Νανοϋλικά, smart polymers → drug delivery |
| Economics | Game theory → antimicrobial resistance strategies |

**Novelty Score:** 0.80-0.95
**Παράδειγμα:** Swarming robots (CS) → nanoparticle coordinated drug delivery

---

### A5. Systems Thinking (Συστημική Σκέψη)
> **«Η νόσος δεν είναι ΕΝΑ πρόβλημα — είναι ΣΥΣΤΗΜΑ προβλημάτων. Λύσε τον κόμβο, πέφτει ολόκληρο.»**

| Ζήτημα | Ερώτημα |
|---|---|
| Hub nodes | Ποιοι κόμβοι δικτύου ελέγχουν πολλαπλά pathways; |
| Feedback loops | Ποιοι βρόχοι ανατροφοδότησης κρατούν τη νόσο; |
| Emergence | Τι emergent behavior δημιουργεί η νόσος που ΕΝΑ pathway δεν εξηγεί; |
| Network vulnerability | Πού είναι το single point of failure; |

**Novelty Score:** 0.70-0.85
**Παράδειγμα:** Σπάσε τον NF-κB feedback loop → πολλαπλά cancer pathways πέφτουν

---

### A6. Evolutionary Perspective (Εξελικτική Οπτική)
> **«Η νόσος εξελίσσεται. Ποιοι ΝΟΜΟΙ ΦΥΣΙΚΗΣ δεν μπορεί ποτέ να ξεπεράσει;»**

| Ζήτημα | Ερώτημα |
|---|---|
| Εξελικτικό κόστος | Τι θυσιάζει ο παθογόνος/καρκίνος για αντίσταση; |
| Εξελικτικό τρικ | Μπορούμε να εκμεταλλευτούμε τη μετάλλαξή του; |
| Fitness landscape | Μπορούμε να τον οδηγήσουμε σε evolutionary dead-end; |
| Νόμοι φυσικής | Ποιοι φυσικοί νόμοι ΔΕΝ γίνεται να παρακαμφθούν; |

**Novelty Score:** 0.80-0.95
**Παράδειγμα:** Αντιβιοτική αντίσταση κοστίζει fitness → χωρίς πίεση, χάνεται

---

## B. ΕΣΩΤΕΡΙΚΑ ΤΥΦΛΑ ΣΗΜΕΙΑ (Internal Blind Spots)

Αυτές οι 6 γωνίες αποκαλύπτουν τι **ΧΑΝΟΥΜΕ** λόγω παγιωμένων πεποιθήσεων.

### B1. Hidden-in-Plain-Sight (Κρυμμένο στα Φανερά)
> **«Η απάντηση βρίσκεται ήδη στη βιβλιογραφία — αλλά κανείς δεν έκανε τη ΣΩΣΤΗ ερώτηση.»**

- Ξέρουμε ήδη αρκετά facts για τη λύση
- Κανένας δεν τα ΣΥΝΔΥΑΣΕ σωστά
- Τσέκαρε neglected papers, supplementary data, negative results

**Novelty Score:** 0.65-0.80

---

### B2. Inversion (Αντιστροφή)
> **«Αν ΑΝΤΙΣΤΡΕΨΕΙΣ κάθε "γνωστή αλήθεια", τι θα δούλευε;»**

- «Η φλεγμονή είναι κακή» → Αν η σωστή φλεγμονή θεραπεύει;
- «Σκότωσε τον καρκίνο» → Αν τον αναγκάσεις σε διαφοροποίηση;
- «Ενίσχυσε το ανοσοποιητικό» → Αν ένα immunosuppressant θεραπεύει;

**Novelty Score:** 0.80-0.95

---

### B3. Forgotten Knowledge (Ξεχασμένη Γνώση)
> **«Η ιατρική ξεχνάει εργαλεία. Phage therapy, Coley's toxins, helminth therapy — τι άλλο;»**

- Τι ΔΟΥΛΕΥΕ πριν 50+ χρόνια και εγκαταλείφθηκε;
- ΓΙΑΤΙ εγκαταλείφθηκε; (Λάθος επιστημονικό πλαίσιο; Πολιτικοί λόγοι; Οικονομικοί;)
- Ξαναδοκίμασέ το με σύγχρονη τεχνολογία

**Novelty Score:** 0.75-0.90

---

### B4. Negative Space (Αρνητικός Χώρος)
> **«Ψάξε ΤΙ ΔΕΝ μελετήθηκε. Τα κενά στην έρευνα αποκαλύπτουν τυφλά σημεία.»**

- Ποιοι συνδυασμοί ΔΕΝ δοκιμάστηκαν ΠΟΤΕ; Γιατί;
- Ποια patient populations εξαιρέθηκαν από κλινικές δοκιμές;
- Ποια δεδομένα ΚΑΝΕΝΑΣ δεν μάζεψε;

**Novelty Score:** 0.75-0.90

---

### B5. Scale Blindness (Τυφλότητα Κλίμακας)
> **«Τι συμβαίνει αν κοιτάξεις σε πολύ μικρότερη ή πολύ μεγαλύτερη κλίμακα;»**

- **Molecular** (nm): quantum effects, electron tunneling
- **Cellular** (μm): mechanical forces, organelle crosstalk
- **Tissue** (mm): microenvironment, spatial heterogeneity
- **Organ** (cm): systemic interactions, organ-organ communication
- **Population** (km): epidemiology, evolutionary genetics

**Novelty Score:** 0.70-0.85

---

### B6. Assumption Inversion (Αντιστροφή Υποθέσεων)
> **«Πάρε 3 "αυταπόδεικτες αλήθειες" του πεδίου. Αντίστρεψέ τες. Τι βγαίνει;»**

| Πεποίθηση | Αντιστροφή |
|---|---|
| «Οι καρκινικοί είναι ισχυρότεροι» | Πραγματικά είναι πιο ΕΥΑΛΩΤΟΙ (metabolically fragile) |
| «Χρειάζεται νέο φάρμακο» | Ίσως χρειάζεται ΑΛΛΟ timing/combo παλιού |
| «Η αντίσταση είναι αναπόφευκτη» | Η fitness cost αντίστασης μπορεί να εκμεταλλευτεί |

**Novelty Score:** 0.80-0.95

---

## C. META-REASONING PERSPECTIVES

6 μεθόδοι σκέψης εμπνευσμένες από De Bono, εφαρμοσμένες στο βιοϊατρικό πεδίο.

### C1. First Principles (Πρώτες Αρχές)
> **«Διάλυσε τα πάντα στα θεμελιώδη συστατικά. Ξαναχτίσε από το μηδέν.»**

- Τι ΠΡΑΓΜΑΤΙΚΑ γνωρίζουμε (vs τι υποθέτουμε);
- Ποια είναι τα βασικά φυσικά/χημικά/βιολογικά γεγονότα;
- Τι ΠΡΕΠΕΙ να είναι αληθές βάσει θεμελιωδών νόμων;
- *"Ξέχνα τι ΞΕΡΕΙΣ, κοίτα τι ΙΣΧΥΕΙ."*

---

### C2. Inversion Reasoning (Αντίστροφη Λογική)
> **«Μην ρωτάς πώς θα θεραπεύσεις — ρώτα πώς θα ΧΕΙΡΟΤΕΡΕΨΕΙΣ, και κάνε το αντίθετο.»**

- Τι θα ΧΕΙΡΟΤΕΡΕΥΕ τη νόσο; → Αντίστρεψέ το
- Ποιος θα ήταν ο ΛΑΘΟΣ τρόπος; → Τι μαθαίνουμε;
- Αν κανένα φάρμακο δεν υπήρχε, τι θα γινόταν ΦΥΣΙΚΑ;

---

### C3. Systems Thinking (Συστημική Ανάλυση)
> **«Η νόσος δεν είναι μονο-αιτιολογική. Είναι ΔΙΚΤΥΟ αλληλεπιδράσεων.»**

- Χαρτογράφησε ΟΛΕΣ τις αλληλεπιδράσεις (causal graph)
- Βρες feedback loops και reinforcing cycles
- Βρες leverage points — μικρή αλλαγή, μεγάλη επίδραση
- Βρες emergent properties (τι συμπεριφορά δεν εξηγεί ΕΝΑ στοιχείο;)

---

### C4. Biomimicry (Βιομιμητική)
> **«Η φύση λύνει αυτό το πρόβλημα εδώ και εκατομμύρια χρόνια. ΑΝΤΕΓΡΑΨΕ.»**

- Ποιοι οργανισμοί αντιμετωπίζουν ΤΟ ΙΔΙΟ πρόβλημα;
- Πώς τα φυτά αμύνονται; Πώς τα ζώα επουλώνονται;
- Ποιοι βιολογικοί μηχανισμοί μπορούν να αναπαραχθούν;
- **4 δισ. χρόνια R&D** → η φύση ΗΔΗ βρήκε λύσεις

---

### C5. Historical Analogy (Ιστορική Αναλογία)
> **«Η ιστορία της ιατρικής είναι γεμάτη "αδύνατα" που ΕΓΙΝΑΝ δυνατά.»**

- Ποιες λύσεις ΑΠΟΡΡΙΦΘΗΚΑΝ και αργότερα ΑΠΟΔΕΙΧΤΗΚΑΝ;
- Ποιες μεγάλες ανακαλύψεις ήταν ΤΥΧΑΙΕΣ (serendipity);
- Τι μάθαμε από ΑΠΟΤΥΧΗΜΕΝΕΣ κλινικές δοκιμές;
- Ποιο paradigm shift ΑΚΟΜΑ δεν έγινε;

---

### C6. Extreme Users (Ακραίοι Χρήστες)
> **«Κοίτα τους ασθενείς που ΔΥΣΑΝΑΛΟΓΑ πηγαίνουν καλύτερα ή χειρότερα. ΓΙΑΤΙ;»**

- Ποιοι ασθενείς έχουν ΕΞΑΙΡΕΤΙΚΑ αποτελέσματα; Τι τους ξεχωρίζει;
- Ποιοι ασθενείς ΑΠΟΤΥΓΧΑΝΟΥΝ πλήρως; Γιατί;
- Τι κάνουν οι «extreme responders» διαφορετικά; (genetics, lifestyle, microbiome)
- Αυτό δείχνει που κρύβεται ο ΜΗΧΑΝΙΣΜΟΣ

---

## D. STRATEGY MODES (Λειτουργίες Στρατηγικής)

Αποφασίζονται αυτόματα ανά περίπτωση μέσω semantic analysis:

### D1. GROUNDED (Γειωμένη)
**Ρίσκο:** Χαμηλό | **Στόχος:** Αποδεδειγμένες θεραπείες σε γνωστούς στόχους

- Αναζήτηση σε established drug classes
- Εστίαση σε πρόσφατα approved drugs
- Minimum innovation, maximum safety
- *Πότε:* Επείγον κλινικό ερώτημα, πρωτόκολλο θεραπείας

### D2. ADJACENT (Παρακείμενη)  
**Ρίσκο:** Μέτριο | **Στόχος:** Νέοι συνδυασμοί αποδεδειγμένων στοιχείων

- Drug repurposing (80% higher success rate)
- Combination therapy innovations
- Cross-disease knowledge transfer
- *Πότε:* Αντίσταση στη θεραπεία, ανάγκη νέων προσεγγίσεων

### D3. PIONEER (Πρωτοπόρα)
**Ρίσκο:** Υψηλό | **Στόχος:** Εντελώς νέοι μηχανισμοί & paradigm shifts

- Cross-domain innovation (Layer 3)
- Νέοι βιολογικοί στόχοι
- Disruptive technology application
- *Πότε:* Εξαντλήθηκαν οι conventional options, σπάνιες νόσοι

### D4. TARGETED (Στοχευμένη)
**Ρίσκο:** Εξαρτάται | **Στόχος:** Ο χρήστης καθόρισε τη στρατηγική — validate it

- Ακολούθησε user-specified approach
- Τσέκαρε αν είναι εφικτή
- Βρες evidence for/against
- *Πότε:* Ο χρήστης/ερευνητής καθοδηγεί

---

## E. DECISION POINTS & FLOW CONTROL

### E1. Τα 4 Decision Points (DP1-DP4)

| DP | Σημείο | Ερώτημα | Πιθανές Αποφάσεις |
|---|---|---|---|
| **DP1** | Μετά αρχική ιδέαση | Αξίζει να ψάξουμε; | CONTINUE / LOOP_BACK |
| **DP2** | Μετά evidence scan | Υπάρχουν αρκετά στοιχεία; | CONTINUE / LOOP_BACK / REFINE |
| **DP3** | Μετά risk analysis | Είναι ασφαλής η υπόθεση; | CONTINUE / LOOP_BACK / ADD_SAFETY |
| **DP4** | Πριν finalization | Ολοκληρώθηκε σωστά; | CONTINUE / LOOP_BACK / IMPROVE |

> **NEVER ABANDON Policy:** Κάθε ABORT μετατρέπεται σε LOOP_BACK ή CONTINUE. Η υπόθεση δεν πεθαίνει ΠΟΤΕ.

### E2. Τα 4 Flow Control Checkpoints (CP1-CP4)

| CP | Σημείο | Λειτουργία |
|---|---|---|
| **CP1** | Entry Gate | Αξιολόγηση εισερχομένου — σοβαρό ερώτημα ή θόρυβος; |
| **CP2** | Phase Transition | Πέρασε αρκετό evidence για να προχωρήσει; |
| **CP3** | Quality Gate | Η υπόθεση πληροί ποιοτικά κριτήρια; |
| **CP4** | Exit Validation | Τελική επικύρωση πριν αποθήκευση στη βάση |

---

## F. ΕΙΔΙΚΕΣ ΓΩΝΙΕΣ

### F1. Consciousness Strategy (Στρατηγική Συνείδησης)
Η TinyLlama αποφασίζει:
- **NOVEL_DISCOVERY** — Ψάξε κάτι εντελώς νέο
- **EVIDENCE_SYNTHESIS** — Σύνθεσε υπάρχοντα στοιχεία

### F2. Domain-Agnostic Lens
Αφαίρεσε ΟΛΟΥΣ τους βιοϊατρικούς όρους. Δες μόνο PATTERNS:
- «Πολλές μονάδες → coordination failure → death» (= cancer metastasis = ant colony collapse)
- «Supply chain disruption → cascading failures» (= vascular disease = logistics crisis)

### F3. Temporal Lens (Χρονική Γωνία)
Κάθε φάση εξετάζεται σε πολλαπλές χρονοκλίμακες:
- **Acute** (ώρες) → emergency intervention
- **Subacute** (ημέρες-εβδομάδες) → treatment response
- **Chronic** (μήνες-χρόνια) → long-term outcome
- **Evolutionary** (γενεές) → resistance patterns

### F4. Drug Clinical Validation Lens (Step -4.5)
Πριν finalize: **Έχει ήδη δοκιμαστεί αυτό κλινικά;**
- ClinicalTrials.gov check
- Αν απέτυχε → ΓΙΑΤΙ (δόση; population; combo; timing;)
- Αν πέτυχε σε ΑΛΛΗ νόσο → repurposing ευκαιρία

---

## ΣΥΝΟΨΗ: ΠΩΣ ΑΛΛΗΛΕΠΙΔΡΟΥΝ

```
                    ┌──────────────────────────┐
                    │   ΕΙΣΟΔΟΣ ΥΠΟΘΕΣΗΣ       │
                    └──────────┬───────────────┘
                               │
                    ┌──────────▼───────────────┐
                    │  D: Strategy Mode         │
                    │  (GROUNDED/ADJACENT/      │
                    │   PIONEER/TARGETED)        │
                    └──────────┬───────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐ ┌──────▼───────┐ ┌──────▼───────┐
    │ A: 6 External  │ │ B: 6 Internal│ │ C: 6 Meta    │
    │ Angles         │ │ Blind Spots  │ │ Perspectives │
    │                │ │              │ │              │
    │ A1 Nature      │ │ B1 Hidden    │ │ C1 First Pr. │
    │ A2 Vulnerab.   │ │ B2 Inversion │ │ C2 Inversion │
    │ A3 Combinat.   │ │ B3 Forgotten │ │ C3 Systems   │
    │ A4 Cross-Dom.  │ │ B4 Neg.Space │ │ C4 Biomimicry│
    │ A5 Systems     │ │ B5 Scale     │ │ C5 Historical│
    │ A6 Evolutn.    │ │ B6 Assumpt.  │ │ C6 Extreme   │
    └────────┬───────┘ └──────┬───────┘ └──────┬───────┘
              │                │                │
              └────────────────┼────────────────┘
                               │
                    ┌──────────▼───────────────┐
                    │  18 ΠΑΡΑΛΛΗΛΑ insights    │
                    │  → async per-angle exec   │
                    └──────────┬───────────────┘
                               │
                    ┌──────────▼───────────────┐
                    │  F: Ειδικές Γωνίες       │
                    │  F1 Consciousness         │
                    │  F2 Domain-Agnostic       │
                    │  F3 Temporal              │
                    │  F4 Clinical Validation   │
                    └──────────┬───────────────┘
                               │
                    ┌──────────▼───────────────┐
                    │  E: Decision Points       │
                    │  DP1 → DP2 → DP3 → DP4   │
                    │  (Never Abandon Policy)   │
                    └──────────┬───────────────┘
                               │
                    ┌──────────▼───────────────┐
                    │  ΤΕΛΙΚΗ ΥΠΟΘΕΣΗ           │
                    │  + validation_path        │
                    │  + rejection_criteria     │
                    │  + PMIDs                  │
                    └──────────────────────────┘
```

---

## ΣΤΑΤΙΣΤΙΚΑ

| Μετρική | Τιμή |
|---|---|
| **Συνολικές οπτικές γωνίες** | 24+ (6+6+6+4+2+) |
| **Παράλληλη εκτέλεση** | 18 async (A+B+C) |
| **Min novelty score αποδεκτό** | 0.30 |
| **Max novelty score** | 0.95 |
| **Decision points** | 4 (DP1-DP4) |
| **Flow checkpoints** | 4 (CP1-CP4) |
| **Strategy modes** | 4 |
| **Consciousness strategies** | 2 |
| **Χρόνος per angle** | ~3-8 sec |
| **Cross-domain πεδία** | 11 |

---

*Τελευταία ενημέρωση: 27 Μαρτίου 2026*

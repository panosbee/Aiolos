"""
XDART-Φ × XHEART — Universal Patterns & Philosophies

Μοτίβα ανακάλυψης, στρατηγικές σκέψης, και φιλοσοφίες pipeline
που καθοδηγούν κάθε φάση.

Πηγή: MedDiscovery Wisdom (universalized) + XDART-Φ extensions
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    id: str
    name_el: str
    name_en: str
    formula: str
    evidence: str


@dataclass(frozen=True)
class Philosophy:
    id: str
    text_el: str
    text_en: str
    application: str


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DISCOVERY PATTERNS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PATTERNS: list[Pattern] = [
    Pattern(
        id="PAT-01",
        name_el="Η Επιστήμη Ξεχνάει",
        name_en="Science Forgetting Pattern",
        formula="Promising → Abandoned → Forgotten → Rediscovered (with new justification)",
        evidence=(
            "Phage therapy (1920s→2020s), Coley's toxins (1890s→2010s Nobel), "
            "Helminth therapy (ancient→modern), Electrotherapy (19th century→bioelectronic medicine), "
            "Bloodletting (ancient→therapeutic phlebotomy for hemochromatosis)."
        ),
    ),
    Pattern(
        id="PAT-02",
        name_el="Τυφλότητα Παραδείγματος",
        name_en="Paradigm Blindness",
        formula="'Everyone knows X' → X is wrong → Paradigm shift",
        evidence=(
            "'Immune system can't fight cancer'→Immunotherapy (2018 Nobel). "
            "'We are the organism, bacteria are passengers'→Microbiome revolution. "
            "'DNA sequence is destiny'→Epigenetics. "
            "'Junk DNA does nothing'→Non-coding RNA."
        ),
    ),
    Pattern(
        id="PAT-03",
        name_el="Μαθηματικά Αντίστασης",
        name_en="Resistance Math",
        formula="1 target → 1 mutation → resistance. 3+ targets → P(resistance) = 10⁻¹⁸ to 10⁻³⁰ (impossible)",
        evidence=(
            "HIV triple therapy→no resistance in 20+ years. "
            "TB quad therapy→prevents MDR-TB. "
            "Combination cancer therapy→blocks escape pathways."
        ),
    ),
    Pattern(
        id="PAT-04",
        name_el="Εξέλιξη vs Φυσική",
        name_en="Evolution vs Physics",
        formula="Systems adapt to CHEMICAL targets via mutation. They CANNOT adapt to PHYSICAL laws.",
        evidence=(
            "Osmotic lysis → can't mutate against thermodynamics. "
            "UV light → can't evolve against photon energy. "
            "Temperature → no cell survives 60°C+."
        ),
    ),
    Pattern(
        id="PAT-05",
        name_el="Αντιστροφή Υποθέσεων",
        name_en="Assumption Inversion",
        formula="Traditional belief → Inversion is actually true",
        evidence=(
            "'Inflammation is bad'→Cancer immunotherapy INDUCES inflammation. "
            "'Bacteria are enemies'→Probiotics & microbiome medicine. "
            "'Rest heals'→Early mobilization speeds recovery. "
            "'Fever is bad'→Fever is defense (hyperthermia therapy). "
            "'Stress harms'→Hormesis: controlled stress strengthens. "
            "'Immunosuppression helps'→Immune activation cures (CAR-T)."
        ),
    ),
    Pattern(
        id="PAT-06",
        name_el="Τα 3 Στρώματα Ανακάλυψης",
        name_en="Three Layers of Discovery",
        formula="Layer-1: Incremental (same domain). Layer-2: Adjacent (recombination). Layer-3: Disruptive (cross-domain paradigm shift)",
        evidence=(
            "Layer-1: Better drug for known target (safe, no breakthroughs). "
            "Layer-2: Drug repurposing, novel combinations (80% higher success). "
            "Layer-3: Cross-domain transfer — where true breakthroughs live."
        ),
    ),
    Pattern(
        id="PAT-07",
        name_el="Μοτίβο XHEART",
        name_en="XHEART Pattern",
        formula="ADDITIVE: phases→summary→output. DISTILLATIVE: phases→internal question→core→output",
        evidence=(
            "New pattern (XDART-Φ original). "
            "Architectural claim: distillation step produces qualitatively "
            "different output from additive summarization. "
            "Falsifiable via blind expert evaluation."
        ),
    ),
    Pattern(
        id="PAT-08",
        name_el="Μνήμη Εμπειρίας vs Πληροφορίας",
        name_en="Experience Memory vs Information Memory",
        formula="RAG remembers INFORMATION → repetition. Episodic Memory remembers EXPERIENCE → evolution",
        evidence=(
            "New pattern (XDART-Φ original). "
            "No current LLM framework stores/retrieves internal states across sessions. "
            "Cross-session coherence is the missing piece in AI reasoning."
        ),
    ),
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PIPELINE PHILOSOPHIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PHILOSOPHIES: list[Philosophy] = [
    Philosophy(
        id="PHIL-01",
        text_el="Η φαντασία χωρίς δεδομένα είναι φαντασίωση.",
        text_en="Imagination without data is hallucination.",
        application=(
            "Κάθε ιδέα πρέπει να γειωθεί σε ΠΡΑΓΜΑΤΙΚΑ δεδομένα πριν εξελιχθεί. "
            "Cross-domain reasoning χωρίς evidence = speculation. "
            "Η δημιουργικότητα πρέπει να περπατά πάνω σε γη — not clouds."
        ),
    ),
    Philosophy(
        id="PHIL-02",
        text_el="Πριν ψάξεις, κατάλαβε τι ψάχνεις.",
        text_en="Before searching, understand what you're searching for.",
        application=(
            "Φάση 0 (Ontological Grounding) πρέπει ΠΑΝΤΑ να προηγείται. "
            "Αν δεν ορίσεις τι ΕΙΝΑΙ το πρόβλημα, ψάχνεις N φορές "
            "τo λάθος πράγμα — ακόμα κι αν βρίσκεις τη σωστή απάντηση."
        ),
    ),
    Philosophy(
        id="PHIL-03",
        text_el="Η γνώση χωρίς δεδομένα είναι ψέμα, η γνώση χωρίς εμπειρία είναι αφέλεια.",
        text_en="Knowledge without data is a lie, knowledge without experience is naivety.",
        application=(
            "Συνδυασμός REAL DATA + WISDOM from past runs (episodic memory). "
            "Τα δύο μαζί → ισχυρότερη βάση από κάθε ένα μόνο του. "
            "Data χωρίς wisdom = shallow. Wisdom χωρίς data = empty."
        ),
    ),
    Philosophy(
        id="PHIL-04",
        text_el="Μην ξαναανακαλύψεις αυτό που ήδη απέτυχε — μάθε από αυτό.",
        text_en="Don't rediscover what already failed — learn from it.",
        application=(
            "Πριν δημιουργήσεις: τι δοκιμάστηκε και ΑΠΕΤΥΧΕ; "
            "ΓΙΑΤΙ απέτυχε; (δόση; timing; population; context;) "
            "Η αποτυχία σε σωστό πλαίσιο δεν είναι αποτυχία — "
            "είναι δεδομένα. Μάθε τι ΕΜΑΘΕ η αποτυχία."
        ),
    ),
    Philosophy(
        id="PHIL-05",
        text_el="Η πιο ριζοσπαστική ιδέα δεν αξίζει τίποτα αν δεν μπορεί να ελεγχθεί.",
        text_en="The most radical idea is worthless if it cannot be tested.",
        application=(
            "ΚΑΘΕ output πρέπει να φέρει: "
            "validation_path — πώς δοκιμάζεται. "
            "rejection_criteria — τι αποδεικνύει ότι είναι λάθος. "
            "falsifiability — ένα πείραμα που θα το διαψεύσει σε 6 μήνες."
        ),
    ),
    Philosophy(
        id="PHIL-06",
        text_el="Μια υπόθεση μπορεί να μην είναι τέλεια, αλλά μια ΕΓΚΑΤΑΛΕΙΜΜΕΝΗ υπόθεση δεν υπάρχει καν.",
        text_en="A hypothesis may be imperfect, but an ABANDONED hypothesis doesn't exist at all.",
        application=(
            "NEVER ABANDON policy. ABORT → LOOP_BACK ή CONTINUE. "
            "Μια υπόθεση δεν πεθαίνει — μετασχηματίζεται. "
            "Κάθε 'αποτυχημένη' υπόθεση μαθαίνει κάτι στο σύστημα."
        ),
    ),
]


def format_wisdom_for_prompt() -> str:
    """Format patterns and philosophies as text for LLM prompts."""
    lines = ["=== XDART-Φ WISDOM ===\n"]

    lines.append("── DISCOVERY PATTERNS ──")
    for p in PATTERNS:
        lines.append(f"[{p.id}] {p.name_en}")
        lines.append(f"  Formula: {p.formula}")
        lines.append(f"  Evidence: {p.evidence}")
        lines.append("")

    lines.append("── PHILOSOPHIES ──")
    for phil in PHILOSOPHIES:
        lines.append(f"[{phil.id}] «{phil.text_en}»")
        lines.append(f"  {phil.application}")
        lines.append("")

    return "\n".join(lines)

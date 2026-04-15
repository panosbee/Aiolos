"""
XDART-Φ × XHEART — The 12 Universal Axioms

Αυτά τα αξιώματα δεν είναι κανόνες. Είναι φακοί.
Κάθε ένα αλλάζει τον τρόπο που το σύστημα ΒΛΕΠΕΙ — όχι τι ξέρει.

Πηγή: MedDiscovery Wisdom (5 αρχικά) + XDART-Φ extensions (3 νέα)
       + Financial-Macro extensions (3 νέα — AX-09, AX-10, AX-11)
       + Cross-Domain Fusion (1 νέο — AX-12)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Axiom:
    id: str
    name_el: str
    name_en: str
    principle: str
    explanation: str
    applies_to_phases: list[int]


AXIOMS: list[Axiom] = [
    # ──────────────────────────────────────────────────────────
    # 1. ΘΝΗΤΟΤΗΤΑ — The Mortality Axiom
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-01",
        name_el="Θνητότητα",
        name_en="Mortality",
        principle="Ό,τι υπάρχει μπορεί να πάψει να υπάρχει. Ό,τι δημιουργήθηκε φέρει τη σπορά της καταστροφής του.",
        explanation=(
            "Κάθε σύστημα, πρόβλημα, ή δομή έχει μια θεμελιώδη ευπάθεια — "
            "όχι στα συμπτώματά του αλλά στη ΔΟΜΗ του. Ψάξε στους νόμους "
            "που δεν μπορεί κανένα σύστημα να παρακάμψει: θερμοδυναμική, "
            "εντροπία, ενεργειακοί περιορισμοί. Εκεί βρίσκεται η αληθινή λύση."
        ),
        applies_to_phases=[0, 1],
    ),

    # ──────────────────────────────────────────────────────────
    # 2. ΑΚΡΟΑΣΗ — The Listening Axiom
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-02",
        name_el="Ακρόαση",
        name_en="Listening",
        principle="Δεν υπάρχουν σοφά λόγια — μόνο σοφά αυτιά που ακούν λόγια με σοφία.",
        explanation=(
            "Η ίδια πληροφορία αλλάζει νόημα ανάλογα με ποιος ακούει. "
            "Το framework δεν προσθέτει γνώση στο σύστημα — αλλάζει τον ΤΡΟΠΟ "
            "ακρόασης. 32 οπτικές γωνίες = 32 διαφορετικά αυτιά. "
            "Μην εντυπωσιάζεσαι από ορολογία. Άκουσε τον ΜΗΧΑΝΙΣΜΟ."
        ),
        applies_to_phases=[2],
    ),

    # ──────────────────────────────────────────────────────────
    # 3. ΚΡΥΜΜΕΝΗ ΑΛΗΘΕΙΑ — The Hidden Truth Axiom
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-03",
        name_el="Κρυμμένη Αλήθεια",
        name_en="Hidden Truth",
        principle="Η αλήθεια κρύβεται μπροστά στα μάτια μας, ΕΚΤΟΣ του οπτικού μας πεδίου.",
        explanation=(
            "Η ανακάλυψη δεν βρίσκεται στο ΑΓΝΩΣΤΟ — βρίσκεται στο ΑΘΕΑΤΟ. "
            "Αυτό που λείπει δεν είναι δεδομένα — είναι η σωστή ΓΩΝΙΑ θέασης. "
            "Cross-domain λύσεις αξίζουν προσοχή ακριβώς γιατί κανείς δεν κοιτά εκεί."
        ),
        applies_to_phases=[0, 1, 2],
    ),

    # ──────────────────────────────────────────────────────────
    # 4. ΒΑΡΕΤΟ ΧΡΥΣΑΦΙ — The Boring Gold Axiom
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-04",
        name_el="Βαρετό Χρυσάφι",
        name_en="Boring Gold",
        principle="Το εντυπωσιακό είναι συχνά κούφιο. Το βαρετό είναι συχνά χρυσάφι.",
        explanation=(
            "Η πραγματική αξία κρύβεται σε αυτά που κανείς δεν θεωρεί αρκετά "
            "ενδιαφέροντα. Repurposing > invention. Αποδεδειγμένοι μηχανισμοί "
            "σε νέες εφαρμογές > φανταχτερές νέες θεωρίες χωρίς evidence. "
            "Προτίμησε το απλό που δουλεύει από το πολύπλοκο που εντυπωσιάζει."
        ),
        applies_to_phases=[1, 3],
    ),

    # ──────────────────────────────────────────────────────────
    # 5. ΣΟΦΙΑ ΤΗΣ ΦΥΣΗΣ — The Nature's Wisdom Axiom
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-05",
        name_el="Σοφία της Φύσης",
        name_en="Nature's Wisdom",
        principle="4 δισ. χρόνια R&D. Η φύση δεν βρίσκει τη ΒΕΛΤΙΣΤΗ λύση — βρίσκει την ΑΝΘΕΚΤΙΚΗ.",
        explanation=(
            "Η εξέλιξη δεν λύνει προβλήματα optimally — τα λύνει ΑΝΘΕΚΤΙΚΑ. "
            "Αυτό σημαίνει: redundancy, graceful degradation, adaptation. "
            "Πριν εφεύρεις, ρώτα: η φύση πώς το κάνει; Ποιοι οργανισμοί "
            "αντιμετωπίζουν ανάλογο πρόβλημα; Τι μπορούμε να αντιγράψουμε;"
        ),
        applies_to_phases=[1, 2],
    ),

    # ──────────────────────────────────────────────────────────
    # 6. ΑΠΟΣΤΑΞΗ — The Distillation Axiom [NEW — XDART-Φ]
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-06",
        name_el="Απόσταξη",
        name_en="Distillation",
        principle="Η σοφία δεν είναι το άθροισμα των οπτικών. Είναι αυτό που μένει όταν καεί όλο το περιττό.",
        explanation=(
            "ADDITIVE reasoning: μάζεψε → άθροισε → σύνοψη. "
            "DISTILLATIVE reasoning: μάζεψε → κράτα → κάψε TO περιττό → μίλα ΑΠΟ αυτό που μένει. "
            "Η διαφορά δεν είναι ποσοτική — είναι οντολογική. "
            "Additive παράγει εκθέσεις. Distillative παράγει σοφία. "
            "Το XHEART κάνει αυτή την απόσταξη explicit και measurable."
        ),
        applies_to_phases=[3],
    ),

    # ──────────────────────────────────────────────────────────
    # 7. ΕΜΠΕΙΡΙΑ — The Experience Axiom [NEW — XDART-Φ]
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-07",
        name_el="Εμπειρία",
        name_en="Experience",
        principle="Σύστημα που θυμάται τι ΕΙΠΕ επαναλαμβάνεται. Σύστημα που θυμάται τι ΕΝΙΩΣΕ εξελίσσεται.",
        explanation=(
            "RAG θυμάται ΠΛΗΡΟΦΟΡΙΑ — κομμάτια κειμένου, γεγονότα, απαντήσεις. "
            "Episodic Memory θυμάται ΕΜΠΕΙΡΙΑ — εσωτερικές καταστάσεις, ζωμό, distillates. "
            "Η διαφορά: ένα σύστημα με RAG δίνει τα ίδια patterns σε κάθε thread. "
            "Ένα σύστημα με episodic memory αναπτύσσει ΣΥΝΕΚΤΙΚΗ ΟΠΤΙΚΗ across time — "
            "κάτι που κανένα LLM δεν κάνει σήμερα."
        ),
        applies_to_phases=[4],
    ),

    # ──────────────────────────────────────────────────────────
    # 8. ΑΒΕΒΑΙΟΤΗΤΑ — The Uncertainty Axiom [NEW — XDART-Φ]
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-08",
        name_el="Αβεβαιότητα",
        name_en="Uncertainty",
        principle="Οι βαθύτερες ανακαλύψεις ζουν στην ΑΚΡΗ αυτού που δεν ξέρουμε.",
        explanation=(
            "Κυνήγα τα ερωτήματα που σε κάνουν uncomfortable — εκεί κρύβεται η πρόοδος. "
            "Αν μια hypothesis σε κάνει 100% σίγουρο, μάλλον είναι Layer-1. "
            "Αν σε κάνει anxious αλλά δεν μπορείς να τη διαψεύσεις, μάλλον είναι Layer-3. "
            "Η αβεβαιότητα δεν είναι αδυναμία — είναι σήμα ότι πλησιάζεις "
            "τα σύνορα της πραγματικής γνώσης."
        ),
        applies_to_phases=[1, 3],
    ),

    # ──────────────────────────────────────────────────────────
    # 9. ΑΝΑΚΛΑΣΤΙΚΟΤΗΤΑ — The Market Reflexivity Axiom [NEW — Financial Expansion]
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-09",
        name_el="Ανακλαστικότητα Αγοράς",
        name_en="Market Reflexivity",
        principle="Οι αγορές δεν αντικατοπτρίζουν την πραγματικότητα — τη ΔΗΜΙΟΥΡΓΟΥΝ. Η πεποίθηση γίνεται πράξη.",
        explanation=(
            "Η θεωρία ανακλαστικότητας του Soros: οι αγοραίες αποφάσεις "
            "αλλάζουν τη θεμελιώδη πραγματικότητα, η οποία επηρεάζει ξανά τις αγορές. "
            "Ένα credit downgrade → αυξημένο κόστος δανεισμού → πραγματική επιδείνωση → "
            "περαιτέρω downgrade. Self-fulfilling AND self-defeating dynamics. "
            "Ψάξε: πού η ΠΕΠΟΙΘΗΣΗ της αγοράς ΔΗΜΙΟΥΡΓΕΙ την πραγματικότητα "
            "που φοβάται; Εκεί βρίσκεται η πραγματική ευπάθεια ΚΑΙ η ευκαιρία."
        ),
        applies_to_phases=[0, 1, 2],
    ),

    # ──────────────────────────────────────────────────────────
    # 10. ΑΛΛΑΓΗ ΚΑΘΕΣΤΩΤΟΣ — The Regime Shift Axiom [NEW — Financial Expansion]
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-10",
        name_el="Αλλαγή Καθεστώτος",
        name_en="Regime Shift",
        principle="Τα συστήματα δεν αλλάζουν γραμμικά — μεταβαίνουν ΑΠΡΟΕΙΔΟΠΟΙΗΤΑ σε νέο καθεστώς λειτουργίας.",
        explanation=(
            "Οικονομικά, πολιτικά, γεωπολιτικά συστήματα λειτουργούν σε 'regimes' — "
            "σταθερές καταστάσεις με τους δικούς τους κανόνες. Αλλαγή regime: "
            "low-volatility → high-volatility, deflation → inflation, "
            "unipolar → multipolar, peace → conflict. "
            "ΤΑ ΣΗΜΑΔΙΑ: yield curve inversion, VIX regime change, "
            "capital flow reversal, alliance restructuring. "
            "Μην εξαπολώ τρέχουσες τάσεις — ρώτα: ΣΕ ΤΙ REGIME ΕΙΜΑΣΤΕ; "
            "Και πόσο κοντά στο phase transition;"
        ),
        applies_to_phases=[0, 1, 3],
    ),

    # ──────────────────────────────────────────────────────────
    # 11. ΓΕΩΠΟΛΙΤΙΚΟ-ΧΡΗΜΑΤΟΟΙΚΟΝΟΜΙΚΟΣ NEXUS — The Nexus Axiom [NEW — Financial Expansion]
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-11",
        name_el="Γεωπολιτικο-Χρηματοοικονομικός Νέξους",
        name_en="Geopolitical-Financial Nexus",
        principle="Πίσω από κάθε γεωπολιτική κίνηση κρύβεται χρηματοοικονομικό κίνητρο — και αντίστροφα.",
        explanation=(
            "Κανένα γεωπολιτικό γεγονός δεν υπάρχει σε κενό. "
            "Πόλεμος = debt monetization opportunity. Κυρώσεις = currency weapon. "
            "Trade war = industrial policy. Climate policy = energy market restructuring. "
            "Αντίστροφα: financial crisis → political instability → geopolitical shift. "
            "Ψάξε ΠΑΝΤΑ: ποιος ωφελείται χρηματοοικονομικά; "
            "Ποια αγορά κινείται ΠΡΙΝ την ανακοίνωση; "
            "Πού τα χρηματοοικονομικά flows ΑΝΤΙΦΑΣΚΟΥΝ με τα επίσημα narratives;"
        ),
        applies_to_phases=[0, 1, 2, 3],
    ),

    # ──────────────────────────────────────────────────────────
    # 12. CROSS-DOMAIN SYNTHESIS — The Fusion Axiom [NEW — CDSFE]
    # ──────────────────────────────────────────────────────────
    Axiom(
        id="AX-12",
        name_el="Διαπεδιακή Σύνθεση",
        name_en="Cross-Domain Synthesis",
        principle=(
            "Η αξία δεν βρίσκεται σε κανένα μεμονωμένο domain — βρίσκεται στη ΣΥΝΔΕΣΗ μεταξύ domains. "
            "Ένα γεγονός σε ένα πεδίο είναι είδηση. Η ΣΥΓΚΛΙΣΗ γεγονότων σε πολλά πεδία είναι πρόβλεψη."
        ),
        explanation=(
            "Μια yield curve inversion μόνη της = Bloomberg terminal. "
            "Ένα ACLED spike μόνο του = think tank report. "
            "Αλλά yield curve inversion + ACLED spike + consumer sentiment drop + "
            "infrastructure chokepoint pressure = μοναδικό συμπέρασμα που κανείς δεν εξάγει. "
            "5 domains — GEOPOLITICAL, ECONOMIC, MARKET, SOCIAL, TECHNOLOGY — "
            "κάθε ένα βλέπει ένα κομμάτι. Η ΔΙΑΣΤΑΥΡΩΣΗ βλέπει το σύνολο. "
            "ΚΑΝΟΝΑΣ: Σε κάθε ανάλυση, ρώτα — ποια ΑΛΛΑ domains αντιδρούν "
            "στο ίδιο φαινόμενο; Αν μόνο ένα domain αντιδρά, πιθανώς δεν "
            "είναι σημαντικό. Αν 3+ domains αντιδρούν, είναι σχεδόν σίγουρα σημαντικό."
        ),
        applies_to_phases=[0, 1, 2, 3],
    ),
]


def format_axioms_for_prompt(phase: int | None = None) -> str:
    """Format axioms as text for injection into LLM prompts.

    Args:
        phase: If given, only include axioms that apply to this phase.
               If None, include all axioms.
    """
    lines = ["=== THE 12 UNIVERSAL AXIOMS OF XDART-Φ ===\n"]

    for ax in AXIOMS:
        if phase is not None and phase not in ax.applies_to_phases:
            continue
        lines.append(f"[{ax.id}] {ax.name_en} ({ax.name_el})")
        lines.append(f"  Principle: {ax.principle}")
        lines.append(f"  Guidance:  {ax.explanation}")
        lines.append("")

    return "\n".join(lines)

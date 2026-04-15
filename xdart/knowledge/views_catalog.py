"""
XDART-Φ × XHEART — Universal Views Catalog

32 οπτικές γωνίες σε 6 κατηγορίες.
Κάθε πρόβλημα δεν εξετάζεται και από τις 32 — το σύστημα επιλέγει
τις πιο σχετικές (8-18) ανάλογα με το πρόβλημα.

Πηγή: MedDiscovery Views (24) μετασχηματισμένες σε domain-agnostic
+ 8 νέες epistemological γωνίες ειδικά για XDART-Φ.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class View:
    id: str
    category: str
    name_el: str
    name_en: str
    question: str
    method: str
    novelty_range: tuple[float, float] = (0.5, 0.8)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CATEGORY A — External Angles (Εξωτερικές Γωνίες)
# Φέρνουν γνώση ΕΞΩ από το κυρίαρχο paradigm
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EXTERNAL_ANGLES = [
    View(
        id="A1", category="A",
        name_el="Αναλογία Προηγούμενου",
        name_en="Precedent Analogy",
        question="Πώς η φύση, η ιστορία, ή άλλο σύστημα έχει ΗΔΗ λύσει ανάλογο πρόβλημα;",
        method=(
            "Biomimicry, historical precedent, cross-system analogy. "
            "Ψάξε λύσεις σε: φυσικά συστήματα, ιστορικές κρίσεις, "
            "engineering solutions, biological adaptations. "
            "4 δισ. χρόνια R&D — η φύση ΗΔΗ βρήκε λύσεις."
        ),
        novelty_range=(0.70, 0.85),
    ),
    View(
        id="A2", category="A",
        name_el="Χαρτογράφηση Ευπαθειών",
        name_en="Vulnerability Mapping",
        question="Ποιες είναι οι δομικές ευπάθειες αυτού του συστήματος/προβλήματος;",
        method=(
            "Θερμοδυναμικά bottlenecks, χωρικοί περιορισμοί, "
            "χρονικά παράθυρα ευπάθειας, εξαρτήσεις supply chain. "
            "Κάθε σύστημα εξαρτάται από κάτι που δεν μπορεί "
            "να αλλάξει — εκεί είναι η ευπάθεια."
        ),
        novelty_range=(0.75, 0.90),
    ),
    View(
        id="A3", category="A",
        name_el="Λογική Συνδυασμού",
        name_en="Combinatorial Logic",
        question="Μπορούν πολλαπλές ανεξάρτητες παρεμβάσεις να δημιουργήσουν μη-γραμμικά αποτελέσματα;",
        method=(
            "Μονο-παρέμβαση → αντίσταση/αποτυχία. "
            "3+ ανεξάρτητες → P(αντίσταση) = μαθηματικά αδύνατη. "
            "Ψάξε: σειρά (sequencing), συνέργεια, "
            "repurposing γνωστών εργαλείων σε νέους συνδυασμούς."
        ),
        novelty_range=(0.60, 0.80),
    ),
    View(
        id="A4", category="A",
        name_el="Διεπιστημονική Μεταφορά",
        name_en="Cross-Domain Transfer",
        question="Τι λύσεις υπάρχουν ΗΔΗ σε εντελώς άσχετα πεδία;",
        method=(
            "Physics → biology, CS → sociology, ecology → economics, "
            "engineering → psychology. "
            "Βιολογική Αδυναμία × Αρχή από Άλλο Πεδίο = Νέα Λύση. "
            "Ψάξε σε: Φυσική, CS, Οικολογία, Υλικά, Μηχανική, "
            "Μαθηματικά, Χημεία, Αστρονομία, Οικονομικά, AI."
        ),
        novelty_range=(0.80, 0.95),
    ),
    View(
        id="A5", category="A",
        name_el="Δυναμική Συστημάτων",
        name_en="Systems Dynamics",
        question="Τι emergent behavior δημιουργεί η ΔΟΜΗ του συστήματος;",
        method=(
            "Hub nodes, feedback loops, reinforcing cycles, "
            "leverage points, single points of failure. "
            "Η νόσος/πρόβλημα δεν είναι ΕΝΑ πράγμα - "
            "είναι ΔΙΚΤΥΟ αλληλεπιδράσεων. Σπάσε τον σωστό κόμβο."
        ),
        novelty_range=(0.70, 0.85),
    ),
    View(
        id="A6", category="A",
        name_el="Εξελικτική Πίεση",
        name_en="Evolutionary Pressure",
        question="Πώς θα ΠΡΟΣΑΡΜΟΣΤΕΙ αυτό σε οποιαδήποτε λύση; Τι δεν μπορεί να ξεπεράσει;",
        method=(
            "Εξελικτικό κόστος: τι θυσιάζεται για προσαρμογή; "
            "Fitness landscape: μπορούμε να το οδηγήσουμε σε dead-end; "
            "Νόμοι φυσικής: τι ΔΕΝ γίνεται να παρακαμφθεί ποτέ; "
            "Evolution adapts to chemistry. It CANNOT adapt to physics."
        ),
        novelty_range=(0.80, 0.95),
    ),
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CATEGORY B — Internal Blind Spots (Εσωτερικά Τυφλά Σημεία)
# Αποκαλύπτουν τι ΧΑΝΟΥΜΕ λόγω παγιωμένων πεποιθήσεων
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BLIND_SPOTS = [
    View(
        id="B1", category="B",
        name_el="Κρυμμένο στα Φανερά",
        name_en="Hidden in Plain Sight",
        question="Τι ΞΕΡΟΥΜΕ ΗΔΗ αλλά κανείς δεν ΣΥΝΔΥΑΣΕ σωστά;",
        method=(
            "Η απάντηση μπορεί να βρίσκεται ΗΔΗ στα δεδομένα. "
            "Τσέκαρε neglected data, supplementary evidence, "
            "negative results που κανείς δεν ακολούθησε. "
            "Μήπως η σωστή ερώτηση δεν τέθηκε ποτέ;"
        ),
        novelty_range=(0.65, 0.80),
    ),
    View(
        id="B2", category="B",
        name_el="Πλήρης Αντιστροφή",
        name_en="Full Inversion",
        question="Αν ΑΝΤΙΣΤΡΕΨΕΙΣ κάθε 'γνωστή αλήθεια', τι θα δούλευε;",
        method=(
            "Πάρε κάθε assumption και κάνε το 180°. "
            "'Η φλεγμονή είναι κακή' → αν η σωστή φλεγμονή θεραπεύει; "
            "'Αύξησε τους πόρους' → αν η μείωση λύνει το πρόβλημα; "
            "'Πολεμά τον εχθρό' → αν τον κάνεις σύμμαχο;"
        ),
        novelty_range=(0.80, 0.95),
    ),
    View(
        id="B3", category="B",
        name_el="Ξεχασμένη Γνώση",
        name_en="Forgotten Knowledge",
        question="Τι ΔΟΥΛΕΥΕ πριν 50+ χρόνια και εγκαταλείφθηκε; ΓΙΑΤΙ;",
        method=(
            "Pattern: Promising → Abandoned → Forgotten → Rediscovered. "
            "Λόγοι εγκατάλειψης: λάθος πλαίσιο; πολιτικοί/οικονομικοί λόγοι; "
            "Τεχνολογικοί περιορισμοί που τώρα ΔΕΝ υπάρχουν; "
            "Ξαναδοκίμασέ το με σύγχρονα εργαλεία."
        ),
        novelty_range=(0.75, 0.90),
    ),
    View(
        id="B4", category="B",
        name_el="Αρνητικός Χώρος",
        name_en="Negative Space",
        question="Τι ΔΕΝ μελετήθηκε ΠΟΤΕ; Ποια κενά αποκαλύπτουν τυφλά σημεία;",
        method=(
            "Ποιοι συνδυασμοί δεν δοκιμάστηκαν και γιατί; "
            "Ποιες ομάδες/μεταβλητές εξαιρέθηκαν; "
            "Ποια δεδομένα ΚΑΝΕΝΑΣ δεν μάζεψε; "
            "Τα κενά στην έρευνα αποκαλύπτουν λάθος υποθέσεις."
        ),
        novelty_range=(0.75, 0.90),
    ),
    View(
        id="B5", category="B",
        name_el="Τυφλότητα Κλίμακας",
        name_en="Scale Blindness",
        question="Τι εμφανίζεται σε ραδικά ΜΙΚΡΟΤΕΡΗ ή ΜΕΓΑΛΥΤΕΡΗ κλίμακα;",
        method=(
            "Quantum → Molecular → Cellular → Organism → System → Population → Civilization. "
            "Κάθε κλίμακα αποκαλύπτει φαινόμενα αόρατα στις άλλες. "
            "Αν κολλήσεις σε μία κλίμακα, χάνεις emergent properties."
        ),
        novelty_range=(0.70, 0.85),
    ),
    View(
        id="B6", category="B",
        name_el="Έλεγχος Υποθέσεων",
        name_en="Assumption Audit",
        question="Ποιες 3 'αυταπόδεικτες αλήθειες' του πεδίου είναι στην πραγματικότητα πεποιθήσεις;",
        method=(
            "Paradigm Blindness: 'Ξέραμε' ότι X → αποδείχτηκε ΛΑΘΟΣ. "
            "Πάρε 3 θεμελιώδεις υποθέσεις. Αντίστρεψέ τες. "
            "Αν η αντιστροφή δεν είναι αμέσως γελοία, "
            "τότε η αρχική υπόθεση αξίζει αμφισβήτηση."
        ),
        novelty_range=(0.80, 0.95),
    ),
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CATEGORY C — Meta-Reasoning (Μετα-Σκέψη)
# 6 τρόποι σκέψης εμπνευσμένοι από De Bono, universalized
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

META_REASONING = [
    View(
        id="C1", category="C",
        name_el="Πρώτες Αρχές",
        name_en="First Principles",
        question="Τι ΠΡΑΓΜΑΤΙΚΑ γνωρίζουμε vs τι υποθέτουμε; Ξαναχτίσε από τo μηδέν.",
        method=(
            "Διάλυσε τα πάντα στα θεμελιώδη συστατικά. "
            "Ξέχνα τι ΞΕΡΕΙΣ — κοίτα τι ΙΣΧΥΕΙ. "
            "Ποιοι είναι οι αναμφισβήτητοι φυσικοί/λογικοί/μαθηματικοί νόμοι; "
            "Ξαναχτίσε ΜΟΝΟ πάνω σε αυτά."
        ),
        novelty_range=(0.60, 0.85),
    ),
    View(
        id="C2", category="C",
        name_el="Αντίστροφη Λογική",
        name_en="Inverse Reasoning",
        question="Πώς θα ΧΕΙΡΟΤΕΡΕΥΕΣ αυτό; Κάνε το αντίθετο.",
        method=(
            "Inversion: αντί να ρωτάς πώς λύνεται, ρώτα πώς ΧΕΙΡΟΤΕΡΕΥΕΙ. "
            "Lista τις 5 ενέργειες που θα χειροτέρευαν σίγουρα. "
            "Αντίστρεψέ τες. "
            "Αυτό συχνά αποκαλύπτει λύσεις αόρατες με forward reasoning."
        ),
        novelty_range=(0.70, 0.90),
    ),
    View(
        id="C3", category="C",
        name_el="Αιτιακό Δίκτυο",
        name_en="Causal Network Mapping",
        question="Ποιο είναι το causal graph; Πού είναι τα leverage points;",
        method=(
            "Χαρτογράφησε ΟΛΕΣ τις αλληλεπιδράσεις. "
            "Βρες feedback loops (reinforcing & balancing). "
            "Βρες leverage points — μικρή αλλαγή, μεγάλη επίδραση. "
            "Βρες emergent properties — συμπεριφορά που ΕΝΑ node δεν εξηγεί."
        ),
        novelty_range=(0.65, 0.85),
    ),
    View(
        id="C4", category="C",
        name_el="Φυσική Αναλογία",
        name_en="Natural Analogy",
        question="Ποιοι φυσικοί/βιολογικοί μηχανισμοί αντιμετωπίζουν ΤΟ ΙΔΙΟ πρόβλημα;",
        method=(
            "4 δισ. χρόνια εξέλιξης = η μεγαλύτερη βάση δεδομένων λύσεων. "
            "Πώς αμύνονται τα φυτά; Πώς επιβιώνουν σε extreme conditions; "
            "Πώς λύνουν coordination problems τα σμήνη; "
            "Τι βιολογικοί μηχανισμοί μπορούν να αναπαραχθούν;"
        ),
        novelty_range=(0.75, 0.90),
    ),
    View(
        id="C5", category="C",
        name_el="Ιστορικό Μοτίβο",
        name_en="Historical Pattern",
        question="Πότε στην ιστορία κάτι 'αδύνατο' αποδείχτηκε δυνατό; Τι μοτίβο ακολουθεί;",
        method=(
            "Serendipity, failed experiments → discoveries. "
            "Τι ΑΠΟΡΡΙΦΘΗΚΕ και αργότερα ΑΠΟΔΕΙΧΤΗΚΕ σωστό; "
            "Τι paradigm shift ΑΚΟΜΑ δεν έγινε στο πεδίο σου; "
            "Pattern: αρχική απόρριψη → μη-mainstream champions → delayed recognition."
        ),
        novelty_range=(0.70, 0.85),
    ),
    View(
        id="C6", category="C",
        name_el="Ακραίες Περιπτώσεις",
        name_en="Extreme Cases",
        question="Τι κάνουν ΔΙΑΦΟΡΕΤΙΚΑ αυτοί που ΔΥΣΑΝΑΛΟΓΑ πετυχαίνουν ή αποτυγχάνουν;",
        method=(
            "Outliers αποκαλύπτουν τον κρυμμένο μηχανισμό. "
            "Extreme responders: Τι τους ξεχωρίζει; Genetics, context, timing; "
            "Extreme failures: Τι πήγε τόσο στραβά; "
            "Η μέση τιμή κρύβει — τα άκρα αποκαλύπτουν."
        ),
        novelty_range=(0.75, 0.90),
    ),
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CATEGORY D — Epistemological Lenses [NEW — XDART-Φ]
# Φιλοσοφικές γωνίες θέασης — η μοναδική συνεισφορά του XDART-Φ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EPISTEMOLOGICAL_LENSES = [
    View(
        id="D1", category="D",
        name_el="Οντολογικός Φακός",
        name_en="Ontological Lens",
        question="Τι ΕΙΝΑΙ αυτό στην πιο abstract μορφή του, αν αφαιρέσεις ΟΛΗ την ορολογία;",
        method=(
            "Αν αφαιρέσεις κάθε domain-specific λέξη, τι μένει; "
            "Ποια ΚΑΤΗΓΟΡΙΑ ΥΠΑΡΞΗΣ είναι αυτό; "
            "Είναι σύστημα; Διαδικασία; Σχέση; Μετάβαση φάσης; "
            "Ο τρόπος που ΟΝΟΜΑΖΕΙΣ κάτι καθορίζει τι ΒΛΕΠΕΙΣ."
        ),
        novelty_range=(0.75, 0.95),
    ),
    View(
        id="D2", category="D",
        name_el="Τελεολογικός Φακός",
        name_en="Teleological Lens",
        question="Τι ΣΚΟΠΟ εξυπηρετεί αυτό; Τι προσπαθεί ΤΟ ΣΥΣΤΗΜΑ να πετύχει;",
        method=(
            "Μην κοιτάς τι ΤΟ ΠΡΟΒΛΗΜΑ κάνει — κοίτα τι ΤΟ ΣΥΣΤΗΜΑ θέλει. "
            "Τελεολογία: ο σκοπός εξηγεί τη δομή. "
            "Η ασθένεια δεν 'θέλει' να σε σκοτώσει — "
            "η αντίσταση δεν 'θέλει' να αλλάξει — τι πραγματικά βελτιστοποιεί;"
        ),
        novelty_range=(0.70, 0.90),
    ),
    View(
        id="D3", category="D",
        name_el="Φαινομενολογικός Φακός",
        name_en="Phenomenological Lens",
        question="Πώς ΒΙΩΝΕΤΑΙ αυτό από τους εμπλεκόμενους; Τι εμπειρία δημιουργεί;",
        method=(
            "Μην κοιτάς μόνο τους αριθμούς — κοίτα την ΕΜΠΕΙΡΙΑ. "
            "Πώς το βιώνει ο ασθενής/χρήστης/πολίτης; "
            "Τι ΝΟΗΜΑ δίνει σε αυτό; "
            "Η βιωμένη εμπειρία αποκαλύπτει dimensions αόρατες στα data."
        ),
        novelty_range=(0.65, 0.85),
    ),
    View(
        id="D4", category="D",
        name_el="Διαλεκτικός Φακός",
        name_en="Dialectical Lens",
        question="Ποια είναι η Θέση, η Αντίθεση, και η Σύνθεση αυτού;",
        method=(
            "Thesis: η κυρίαρχη άποψη / η πρώτη σου σκέψη. "
            "Antithesis: ο ΙΣΧΥΡΟΤΕΡΟΣ λόγος που είναι λάθος. "
            "Synthesis: τι ΜΕΝΕΙ αληθινό μετά τη σύγκρουση; "
            "Αν δεν υπάρχει synthesis → η θέση είναι speculation."
        ),
        novelty_range=(0.70, 0.90),
    ),
    View(
        id="D5", category="D",
        name_el="Ερμηνευτικός Φακός",
        name_en="Hermeneutic Lens",
        question="Πώς ερμηνεύουν ΔΙΑΦΟΡΕΤΙΚΟΙ παρατηρητές το ίδιο φαινόμενο;",
        method=(
            "Ο φυσικός βλέπει ενέργεια, ο βιολόγος σύστημα, "
            "ο μηχανικός πρόβλημα control, ο φιλόσοφος οντολογία. "
            "ΚΑΜΙΑ ερμηνεία δεν είναι 'λάθος' — κάθε μία φωτίζει "
            "διαφορετικά κομμάτια. Σύνθεσε τις ερμηνείες."
        ),
        novelty_range=(0.75, 0.90),
    ),
    View(
        id="D6", category="D",
        name_el="Πραγματιστικός Φακός",
        name_en="Pragmatic Lens",
        question="Τι δουλεύει ΣΤΗΝ ΠΡΑΞΗ ανεξάρτητα από τη θεωρία;",
        method=(
            "Ξέχνα τις θεωρίες. Τι παρατηρείται ΕΜΠΕΙΡΙΚΑ; "
            "Τι λειτουργεί χωρίς κανένας να ξέρει γιατί; "
            "Η λαϊκή σοφία, η κλινική εμπειρία, τα folk heuristics — "
            "συχνά δουλεύουν ΠΡΙΝ τα εξηγήσει η επιστήμη."
        ),
        novelty_range=(0.60, 0.80),
    ),
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CATEGORY E — Temporal & Scale Lenses
# Πολλαπλές χρονοκλίμακες ταυτόχρονα
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TEMPORAL_LENSES = [
    View(
        id="E1", category="E",
        name_el="Micro-Χρονική",
        name_en="Micro-Temporal",
        question="Τι συμβαίνει σε διάστημα δευτερολέπτων/λεπτών; Ποια μεταβατικά φαινόμενα χάνουμε;",
        method=(
            "Acute phase transitions, cascading failures, "
            "chain reactions, initial conditions sensitivity. "
            "Τα πιο κρίσιμα events συχνά γίνονται σε msec."
        ),
        novelty_range=(0.60, 0.80),
    ),
    View(
        id="E2", category="E",
        name_el="Meso-Χρονική",
        name_en="Meso-Temporal",
        question="Τι pattern εμφανίζεται σε ημέρες/μήνες; Ποιοι κύκλοι υπάρχουν;",
        method=(
            "Response curves, adaptation cycles, "
            "circadian / seasonal / business patterns. "
            "Τι αλλάζει αν αλλάξεις ΠΟΤΕ παρεμβαίνεις;"
        ),
        novelty_range=(0.55, 0.75),
    ),
    View(
        id="E3", category="E",
        name_el="Macro-Χρονική",
        name_en="Macro-Temporal",
        question="Τι trend φαίνεται σε χρόνια/δεκαετίες; Τι paradigm shifts έρχονται;",
        method=(
            "Long-term trajectories, S-curves, "
            "institutional memory/forgetting, generational shifts. "
            "Τι θα θεωρείται γελοίο σε 20 χρόνια;"
        ),
        novelty_range=(0.65, 0.85),
    ),
    View(
        id="E4", category="E",
        name_el="Εξελικτική-Χρονική",
        name_en="Evolutionary-Temporal",
        question="Σε χρόνο γενεών/εποχών, τι εξελικτική πίεση ασκείται; Τι patterns αναδύονται;",
        method=(
            "Evolutionary fitness, adaptation vs extinction, "
            "co-evolution, Red Queen dynamics. "
            "Μακροπρόθεσμα, μόνο η antifragility επιβιώνει."
        ),
        novelty_range=(0.70, 0.90),
    ),
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CATEGORY F — Cross-Domain Pattern Recognition [NEW — XDART-Φ]
# Αναγνώριση isomorphisms μεταξύ πεδίων
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PATTERN_RECOGNITION = [
    View(
        id="F1", category="F",
        name_el="Domain-Agnostic Μοτίβο",
        name_en="Domain-Agnostic Pattern",
        question="Αν ΑΦΑΙΡΕΣΕΙΣ ΟΛΗ την ορολογία, ποιο ΔΟΜΙΚΟ μοτίβο βλέπεις;",
        method=(
            "Strip all terminology. See only STRUCTURE. "
            "'Πολλές μονάδες → coordination failure → death' = "
            "cancer metastasis = ant colony collapse = organizational failure. "
            "'Supply chain disruption → cascading failures' = "
            "vascular disease = logistics crisis = internet outage."
        ),
        novelty_range=(0.80, 0.95),
    ),
    View(
        id="F2", category="F",
        name_el="Ανίχνευση Ισομορφισμού",
        name_en="Isomorphism Detection",
        question="Ποια ΑΛΛΑ προβλήματα έχουν ΑΚΡΙΒΩΣ ΤΟ ΙΔΙΟ ΣΧΗΜΑ;",
        method=(
            "f(D_source) ≅ g(D_target). "
            "Ψάξε structural isomorphisms — "
            "όχι surface similarity αλλά ΜΗΧΑΝΙΣΤΙΚΗ identity. "
            "Αν δύο προβλήματα έχουν ίδιο σχήμα, η λύση ΜΕΤΑΦΕΡΕΤΑΙ."
        ),
        novelty_range=(0.85, 0.95),
    ),
    View(
        id="F3", category="F",
        name_el="Μεταφορά Μοτίβου Αποτυχίας",
        name_en="Failure Pattern Transfer",
        question="Τι αποτυχίες σε ΑΛΛΑ πεδία μοιάζουν δομικά με αυτό το πρόβλημα;",
        method=(
            "Η αποτυχία σε ένα domain = προειδοποίηση σε άλλο. "
            "Αν X απέτυχε στο domain A λόγω μηχανισμού M, "
            "και ο μηχανισμός M υπάρχει στο domain B → ΚΙΝΔΥΝΟΣ. "
            "Μάθε από τις αποτυχίες ΑΛΛΩΝ πεδίων."
        ),
        novelty_range=(0.70, 0.85),
    ),
    View(
        id="F4", category="F",
        name_el="Μεταφορά Μοτίβου Λύσης",
        name_en="Solution Pattern Transfer",
        question="Τι λύσεις σε ΑΛΛΑ πεδία μπορούν να εφαρμοστούν ΕΔΩ μέσω structural mapping;",
        method=(
            "Η λύση υπάρχει ΗΔΗ — σε ΑΛΛΟ πεδίο. "
            "Map: Source solution → structural abstraction → target application. "
            "Η μεταφορά δυσκολεύει: constraints differ, context differs. "
            "Test: τι ΣΠΑΕΙ όταν μεταφέρεις; Εκεί είναι η αληθινή δουλειά."
        ),
        novelty_range=(0.80, 0.95),
    ),
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CATEGORY G — Financial-Macro Lenses (Χρηματο-Μακροοικονομικοί Φακοί)
# Σύνδεση γεωπολιτικών γεγονότων με αγορές, νομίσματα, χρέος
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FINANCIAL_MACRO_LENSES = [
    View(
        id="G1", category="G",
        name_el="Μακρο-Χρηματοοικονομική Σύζευξη",
        name_en="Macro-Financial Coupling",
        question="Πώς αυτό το γεωπολιτικό γεγονός μεταφράζεται σε χρηματοοικονομικό σήμα — και πόσο γρήγορα;",
        method=(
            "Κάθε γεωπολιτικό γεγονός παράγει χρηματοοικονομικό κύμα. "
            "Εντόπισε: 1) Μηχανισμό μετάδοσης (sanctions → trade → FX → bonds), "
            "2) Χρονική καθυστέρηση (instant shock vs slow burn), "
            "3) Ασυμμετρία (upside vs downside risk), "
            "4) Αγορές που δεν έχουν αντιδράσει ΑΚΟΜΑ (mispriced risk). "
            "Η αγορά που ΔΕΝ κινείται ενώ θα ΕΠΡΕΠΕ — εκεί είναι η πληροφορία."
        ),
        novelty_range=(0.70, 0.90),
    ),
    View(
        id="G2", category="G",
        name_el="Νομισματική Πίεση",
        name_en="Currency Stress",
        question="Ποια νομίσματα δέχονται πίεση και τι αποκαλύπτει για υποκείμενες γεωπολιτικές τάσεις;",
        method=(
            "Τα νομίσματα είναι τα πρώτα θύματα γεωπολιτικής αστάθειας. "
            "Ανάλυσε: 1) Capital flight patterns (ποιος φεύγει πρώτος), "
            "2) Carry trade unwinding (σημάδια de-risking), "
            "3) Central bank defense κόστος (reserves burn rate), "
            "4) Ασυμφωνία μεταξύ επίσημου rate και black market rate. "
            "Ένα νόμισμα σε κρίση = ένας λαός σε κρίση. Δες ΠΟΙΟΣ πληρώνει."
        ),
        novelty_range=(0.75, 0.90),
    ),
    View(
        id="G3", category="G",
        name_el="Εφοδιαστική Αλυσίδα Πρώτων Υλών",
        name_en="Commodity Supply Chain",
        question="Πώς αυτή η κατάσταση επηρεάζει τις κρίσιμες εφοδιαστικές αλυσίδες πρώτων υλών;",
        method=(
            "Οι πρώτες ύλες είναι η φυσική θεμελίωση της γεωπολιτικής. "
            "Χαρτογράφησε: 1) Chokepoints (Hormuz, Malacca, Suez), "
            "2) Concentration risk (ποιος ελέγχει τι — λίθιο, σπάνιες γαίες, grain), "
            "3) Substitution difficulty (πόσο εύκολα αντικαθίστανται), "
            "4) Inventory buffer days (πόσο χρόνο αντέχει η αγορά χωρίς supply). "
            "Ένα commodity shock = geopolitical leverage. Ποιος το κρατά;"
        ),
        novelty_range=(0.70, 0.85),
    ),
    View(
        id="G4", category="G",
        name_el="Δυναμική Κρατικού Χρέους",
        name_en="Sovereign Debt Dynamics",
        question="Πώς μεταβάλλεται η βιωσιμότητα χρέους και τι σηματοδοτεί για πολιτικές αποφάσεις;",
        method=(
            "Sovereign debt = η βασική μεταβλητή μεταξύ οικονομίας και πολιτικής. "
            "Ανάλυσε: 1) Debt-to-GDP trajectories (acceleration = danger), "
            "2) Yield spread widening (αγορά δεν εμπιστεύεται κράτος), "
            "3) Refinancing walls (πότε ΠΡΕΠΕΙ να δανειστεί ξανά), "
            "4) Rating agency signals (downgrade watches). "
            "Χώρα με unsustainable debt = χώρα με περιορισμένες γεωπολιτικές επιλογές."
        ),
        novelty_range=(0.75, 0.90),
    ),
    View(
        id="G5", category="G",
        name_el="Απόκλιση Αγοραίου Sentiment",
        name_en="Market Sentiment Divergence",
        question="Πού υπάρχει ασυμφωνία μεταξύ αγοραίου sentiment και πραγματικότητας — και γιατί;",
        method=(
            "Η αγορά δεν είναι πάντα αποτελεσματική — ειδικά σε γεωπολιτικά shocks. "
            "Εντόπισε: 1) VIX vs actual risk (complacent market = danger), "
            "2) Credit spreads vs equity index (divergence = hidden stress), "
            "3) Safe haven flows vs risk appetite indicators, "
            "4) Insider selling vs public narrative (smart money moves first). "
            "Όπου η ΑΓΟΡΑ λέει ένα πράγμα και η ΠΡΑΓΜΑΤΙΚΟΤΗΤΑ άλλο — "
            "κάποιος κάνει λάθος. Βρες ποιος."
        ),
        novelty_range=(0.80, 0.95),
    ),
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Complete catalog
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VIEWS_CATALOG: list[View] = (
    EXTERNAL_ANGLES
    + BLIND_SPOTS
    + META_REASONING
    + EPISTEMOLOGICAL_LENSES
    + TEMPORAL_LENSES
    + PATTERN_RECOGNITION
    + FINANCIAL_MACRO_LENSES
)

CATEGORY_DESCRIPTIONS = {
    "A": "External Angles — Φέρνουν γνώση ΕΞΩ από το κυρίαρχο paradigm",
    "B": "Internal Blind Spots — Αποκαλύπτουν τι ΧΑΝΟΥΜΕ λόγω πεποιθήσεων",
    "C": "Meta-Reasoning — Εργαλεία σκέψης cross-domain",
    "D": "Epistemological Lenses — Φιλοσοφικές γωνίες θέασης (XDART-Φ exclusive)",
    "E": "Temporal & Scale — Πολλαπλές χρονοκλίμακες ταυτόχρονα",
    "F": "Pattern Recognition — Αναγνώριση isomorphisms μεταξύ πεδίων (XDART-Φ exclusive)",
    "G": "Financial-Macro Lenses — Σύνδεση γεωπολιτικών γεγονότων με αγορές, χρέος, νομίσματα",
}


def format_views_for_prompt(max_views: int | None = None, categories: list[str] | None = None) -> str:
    """Format the views catalog as text for injection into LLM prompts.

    Args:
        max_views: Max views to select from this set.
        categories: If given, only include views from these category IDs (e.g. ["A", "F"]).
    """
    if categories:
        views_subset = [v for v in VIEWS_CATALOG if v.category in categories]
        cat_subset = {k: v for k, v in CATEGORY_DESCRIPTIONS.items() if k in categories}
    else:
        views_subset = VIEWS_CATALOG
        cat_subset = CATEGORY_DESCRIPTIONS

    lines = [
        "=== XDART-Φ VIEWS CATALOG ===",
        f"Total views in this set: {len(views_subset)} across {len(cat_subset)} categories\n",
    ]

    for cat_id, cat_desc in cat_subset.items():
        lines.append(f"── {cat_desc} ──")
        cat_views = [v for v in views_subset if v.category == cat_id]
        for v in cat_views:
            lines.append(f"  [{v.id}] {v.name_en} ({v.name_el})")
            lines.append(f"      Question: {v.question}")
            lines.append(f"      Method: {v.method}")
            lines.append("")

    if max_views:
        lines.append(f"\nINSTRUCTION: Select the {max_views} most relevant views for the given problem.")
    else:
        lines.append("\nINSTRUCTION: Select 3-6 most relevant views for the given problem.")

    return "\n".join(lines)


# ── View Groups for Phase 2 multi-call ──
# Financial views (G) are distributed across groups so they get EQUAL
# weight in synthesis — not isolated in a tiny 4th group.
VIEW_GROUPS = {
    "structure_financial": {
        "label": "Structure, Scale & Financial Coupling",
        "categories": ["A", "F", "G"],
        "description": "External angles + cross-domain pattern recognition + financial-macro coupling",
    },
    "blindspots_meta": {
        "label": "Blind Spots & Meta-Reasoning",
        "categories": ["B", "C"],
        "description": "Hidden assumptions + reasoning tools",
    },
    "epistemic_temporal": {
        "label": "Epistemology & Temporal",
        "categories": ["D", "E"],
        "description": "Philosophical lenses + multi-timescale analysis",
    },
}

"""
XDART-Φ × XHEART — Historical Knowledge Base

Structured analyses of key historical inflection points.
Each event is stored as a structured dict with:
  - Conditions that existed (searchable by structural match)
  - What happened (escalation path, outcome)
  - What analysts missed at the time
  - Transferable lessons

These are NOT trivia. Each entry is a reasoning anchor:
the system uses them to say "Η ιστορία λέει ότι όταν
υπάρχουν αυτές οι συνθήκες, τότε..."

The KB is loaded into a Qdrant collection for vector search
and also available for condition-based structured matching.

«Ο σοφός δεν προβλέπει — αναγνωρίζει μοτίβα.»
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HISTORICAL EVENTS — Structured Knowledge Base
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HISTORICAL_EVENTS: list[dict] = [
    # ── WARS & MILITARY ESCALATION ──
    {
        "id": "july_crisis_1914",
        "event": "July Crisis & WWI Onset",
        "period": "1914-06 to 1914-08",
        "category": "war_escalation",
        "structural_conditions": [
            "alliance_cascade", "mobilization_speed_pressure",
            "honor_politics", "miscalculated_deterrence",
            "information_delay", "cross_theater_coupling",
            "imperial_competition", "arms_race",
        ],
        "key_actors": ["Austria-Hungary", "Serbia", "Russia", "Germany", "France", "UK"],
        "trigger": "Assassination of Archduke Franz Ferdinand → Austro-Hungarian ultimatum → Russian mobilization → alliance activation cascade",
        "escalation_path": "Local assassination → bilateral ultimatum → Russian partial mobilization → German full mobilization → alliance cascade → continental war in 5 weeks",
        "outcome": "4-year total war, 20M dead, 4 empires collapsed (Ottoman, Austro-Hungarian, Russian, German), redrew entire world map",
        "what_analysts_missed": "Everyone assumed the crisis would be localized like previous Balkan crises. The key miss: mobilization timetables had compressed decision time below diplomatic response time. Military logic overtook political control.",
        "key_lesson": "When alliance obligations + mobilization speed + honor culture compress decision windows below diplomatic cycle time, local crises cascade into systemic war",
        "transferable_pattern": "Speed of commitment outrunning speed of diplomacy. Defensive preparations indistinguishable from offensive ones. Each actor's rational protective action triggers the next actor's protective action → spiral.",
        "relevance_tags": ["alliance_ambiguity", "cascade_escalation", "mobilization_pressure", "honor_politics", "compressed_decision_time"],
    },
    {
        "id": "munich_1938",
        "event": "Munich Agreement & Appeasement Failure",
        "period": "1938-09 to 1939-09",
        "category": "deterrence_failure",
        "structural_conditions": [
            "deterrence_failure", "appeasement_logic",
            "domestic_war_aversion", "revisionist_power",
            "alliance_credibility_erosion", "intelligence_failure",
            "institutional_weakness",
        ],
        "key_actors": ["Nazi Germany", "UK", "France", "Czechoslovakia", "Italy"],
        "trigger": "Hitler's demand for Sudetenland → Chamberlain's concession at Munich → emboldened further aggression",
        "escalation_path": "Territorial demand → diplomatic appeasement → credibility collapse → further demands → invasion of Poland → WW2",
        "outcome": "12 months from Munich to WW2. Appeasement emboldened aggression, destroyed alliance credibility, left smaller allies defenseless",
        "what_analysts_missed": "Chamberlain correctly identified public war aversion and genuine German grievances, but catastrophically misread Hitler's strategic calculus. Appeasement can work against rational status-quo actors; it fails against actors whose goals expand with every concession.",
        "key_lesson": "Deterrence failure happens not through weakness alone but through revealed preference for peace at any cost. Concessions signal that further aggression has no ceiling.",
        "transferable_pattern": "When a revisionist actor sees that defensive actors prefer short-term stability over confrontation, each concession raises the next demand. The cost of confrontation rises with each delay.",
        "relevance_tags": ["deterrence_failure", "appeasement", "revisionist_power", "alliance_credibility", "escalation_through_concession"],
    },
    {
        "id": "cuban_missile_crisis_1962",
        "event": "Cuban Missile Crisis",
        "period": "1962-10",
        "category": "brinkmanship_resolution",
        "structural_conditions": [
            "nuclear_brinkmanship", "direct_superpower_confrontation",
            "backchannel_diplomacy", "domestic_political_pressure",
            "intelligence_asymmetry", "compressed_decision_time",
        ],
        "key_actors": ["USA (Kennedy)", "USSR (Khrushchev)", "Cuba (Castro)"],
        "trigger": "Soviet missile deployment in Cuba → US naval blockade → 13-day standoff",
        "escalation_path": "Secret deployment → U2 discovery → blockade → military readiness → backchannel negotiation → mutual face-saving deal",
        "outcome": "Resolved without war. Both sides made quiet concessions. Led to hotline agreement, atmospheric test ban, and period of détente",
        "what_analysts_missed": "Multiple near-misses that weren't known until decades later (Vasili Arkhipov preventing nuclear torpedo launch, SAC unauthorized actions). The margin was thinner than leaders or public knew.",
        "key_lesson": "Nuclear crises can be resolved when both sides have backchannel communication, face-saving exits, and leaders who actively resist hawkish advisers. But the margin for error is measured in individual decisions, not institutional design.",
        "transferable_pattern": "Brinkmanship succeeds when both sides can privately retreat while publicly maintaining strength. Fails when backchannels are absent, face-saving is impossible, or decision-makers are captured by military logic.",
        "relevance_tags": ["nuclear_brinkmanship", "backchannel_diplomacy", "face_saving", "near_miss", "compressed_decision_time"],
    },
    {
        "id": "oil_crisis_1973",
        "event": "1973 Oil Crisis (OPEC Embargo)",
        "period": "1973-10 to 1974-03",
        "category": "economic_weaponization",
        "structural_conditions": [
            "energy_chokepoint_weaponization", "supply_chain_dependence",
            "geopolitical_commodity_coupling", "domestic_economic_vulnerability",
            "alliance_stress_from_economic_shock",
        ],
        "key_actors": ["OAPEC/Saudi Arabia", "USA", "Israel", "Western Europe", "Japan"],
        "trigger": "Yom Kippur War → OAPEC oil embargo against US and allies supporting Israel",
        "escalation_path": "Regional war → energy weapon deployed → oil price 4x → stagflation in West → alliance stress → strategic realignment",
        "outcome": "Oil price quadrupled. Global recession. Fundamental restructuring of energy politics. Long-term: petrodollar system, energy diversification efforts, Middle East as permanent strategic concern",
        "what_analysts_missed": "The degree to which Western economies had become structurally dependent on cheap Middle Eastern oil. Intelligence focused on military balances, not supply chain cascading.",
        "key_lesson": "Chokepoint dependence converts regional conflicts into global economic crises. The weapon isn't missiles — it's the infrastructure everyone takes for granted.",
        "transferable_pattern": "When critical supply chains flow through politically contested chokepoints, regional conflicts acquire automatic global escalation potential through economic transmission, not military action.",
        "relevance_tags": ["energy_weaponization", "chokepoint_dependence", "economic_cascade", "supply_chain_fragility", "alliance_stress"],
    },
    # ── FINANCIAL & ECONOMIC CRISES ──
    {
        "id": "great_depression_1929",
        "event": "Great Depression (1929-1933)",
        "period": "1929-10 to 1933",
        "category": "financial_contagion",
        "structural_conditions": [
            "speculative_excess", "leverage_buildup",
            "bank_interconnection", "policy_failure_procyclical",
            "gold_standard_constraint", "international_contagion",
            "protectionist_response",
        ],
        "key_actors": ["USA", "UK", "Germany", "France", "Federal Reserve"],
        "trigger": "Wall Street crash October 1929 → bank runs → credit contraction → global contagion",
        "escalation_path": "Asset bubble burst → bank failures → credit freeze → deflation → unemployment → trade war (Smoot-Hawley) → international contagion → political extremism",
        "outcome": "GDP fell 30% in US. Unemployment 25%. Enabled rise of fascism in Europe. Took WW2 spending to fully recover.",
        "what_analysts_missed": "The Fed tightened when it should have loosened. Smoot-Hawley tariffs turned a domestic crash into a global depression. Liquidationist ideology ('let the rot clear out') deepened and prolonged the crisis.",
        "key_lesson": "Financial crises become catastrophic when policy responses are procyclical (tightening during contraction) and protectionist (beggar-thy-neighbor tariffs). The policy response matters more than the initial shock.",
        "transferable_pattern": "Leveraged interconnected systems fail in cascades. The critical variable is not the trigger but whether institutional responses dampen or amplify. Tariffs and monetary tightening during contraction = amplification.",
        "relevance_tags": ["financial_contagion", "leverage_crisis", "policy_failure", "protectionism", "tariff_war", "deflationary_spiral"],
    },
    {
        "id": "asian_crisis_1997",
        "event": "Asian Financial Crisis",
        "period": "1997-07 to 1998",
        "category": "financial_contagion",
        "structural_conditions": [
            "currency_peg_fragility", "hot_money_dependence",
            "current_account_deficits", "moral_hazard",
            "contagion_through_sentiment", "imf_conditionality_backlash",
        ],
        "key_actors": ["Thailand", "Indonesia", "South Korea", "Malaysia", "IMF", "USA"],
        "trigger": "Thai baht collapse → regional currency contagion → capital flight",
        "escalation_path": "One currency breaks → investors reassess → regional flight → IMF bailouts with harsh conditions → social crisis → political upheaval",
        "outcome": "GDP collapsed 10-15% in affected countries. Indonesia: Suharto fell. IMF conditionality created lasting anti-Western sentiment. Led to Asian FX reserve buildup that contributed to 2008 crisis.",
        "what_analysts_missed": "The speed of sentiment contagion. Countries with different fundamentals were treated as identical because investors used 'Asian basket' heuristics. IMF austerity deepened the contraction.",
        "key_lesson": "Financial contagion doesn't require real economic linkage — shared investor categories and sentiment heuristics are sufficient. The cure (forced austerity during crisis) can be worse than the disease.",
        "transferable_pattern": "When investors use category heuristics ('emerging markets,' 'Asian economies'), distress in one member contaminates the entire category regardless of fundamentals. Fire-sale dynamics become self-fulfilling.",
        "relevance_tags": ["financial_contagion", "sentiment_cascade", "currency_crisis", "institutional_response_failure", "category_heuristic"],
    },
    {
        "id": "gfc_2008",
        "event": "Global Financial Crisis (2008)",
        "period": "2007-08 to 2009",
        "category": "systemic_risk",
        "structural_conditions": [
            "systemic_interconnection", "hidden_leverage",
            "rating_agency_failure", "regulatory_capture",
            "too_big_to_fail", "moral_hazard", "complexity_opacity",
        ],
        "key_actors": ["Lehman Brothers", "AIG", "Federal Reserve", "US Treasury", "European banks"],
        "trigger": "Subprime mortgage defaults → CDO/CDS cascade → Lehman bankruptcy → global credit freeze",
        "escalation_path": "Housing bubble → subprime defaults → CDO losses → counterparty fear → Lehman collapse → global credit freeze → recession → sovereign debt crisis (Europe)",
        "outcome": "Global recession, $22T in lost wealth, unemployment doubled. Led to: QE era, European sovereign debt crisis, populist backlash, Occupy/Tea Party",
        "what_analysts_missed": "The system's own risk models were blind to correlated failure. AAA-rated instruments were toxic. Interconnection through derivatives meant one firm's failure could freeze the entire system.",
        "key_lesson": "When complexity hides risk, and when institutions are too interconnected to fail individually but too correlated to survive collectively, the system is in a metastable state — any shock of sufficient size triggers phase transition.",
        "transferable_pattern": "Metastable systems: appear stable until they aren't. The warning signs are in the structure (hidden leverage, correlated positions, complexity that defeats oversight), not in the triggers.",
        "relevance_tags": ["systemic_risk", "hidden_leverage", "complexity_opacity", "too_big_to_fail", "metastable_system"],
    },
    # ── EMPIRE & STATE COLLAPSE ──
    {
        "id": "soviet_collapse_1991",
        "event": "Soviet Union Collapse",
        "period": "1989-11 to 1991-12",
        "category": "imperial_overstretch",
        "structural_conditions": [
            "imperial_overstretch", "legitimacy_erosion",
            "economic_stagnation", "reform_paradox",
            "information_revolution", "peripheral_nationalism",
            "military_industrial_drain",
        ],
        "key_actors": ["USSR/Gorbachev", "USA/Bush", "Baltic states", "Ukraine", "Eastern Europe"],
        "trigger": "Gorbachev's glasnost/perestroika → unintended liberation of suppressed tensions → cascade of independence declarations",
        "escalation_path": "Reform attempt → information opening → peripheral demands → loss of control → cascade failure → dissolution",
        "outcome": "Largest peacetime empire dissolution in history. 15 new states. End of bipolar world. Left Russia with lasting revanchist grievance.",
        "what_analysts_missed": "Almost everyone (CIA included) expected gradual decline, not sudden collapse. The critical insight: legitimacy is a threshold function, not a gradient. Below the threshold, collapse is sudden and self-reinforcing.",
        "key_lesson": "Imperial systems can endure enormous strain as long as the narrative of inevitability holds. Once that narrative cracks, dissolution can happen faster than anyone predicts. Reform can accelerate collapse.",
        "transferable_pattern": "Legitimacy collapse is nonlinear: the system absorbs stress until a threshold, then the same stress that was absorbed now cascades. The paradox: the reforms designed to save the system can be what breaks the narrative of inevitability.",
        "relevance_tags": ["imperial_overstretch", "legitimacy_collapse", "reform_paradox", "cascade_dissolution", "nonlinear_transition"],
    },
    {
        "id": "arab_spring_2011",
        "event": "Arab Spring",
        "period": "2010-12 to 2012",
        "category": "cascade_revolution",
        "structural_conditions": [
            "legitimacy_deficit", "youth_unemployment",
            "information_technology_amplifier", "food_price_shock",
            "cross_border_demonstration_effect", "security_apparatus_fracture",
        ],
        "key_actors": ["Tunisia", "Egypt", "Libya", "Syria", "Bahrain", "Yemen"],
        "trigger": "Mohamed Bouazizi self-immolation (Tunisia) → protest cascade across Arab world",
        "escalation_path": "Individual act → social media amplification → mass protests → regime responses (concession/repression) → cascade to neighbors → each country's internal fractures determine outcome",
        "outcome": "Tunisia: democratic transition. Egypt: revolution → counter-revolution. Libya: state collapse. Syria: civil war + foreign intervention. Bahrain/Saudi: repressed. Yemen: civil war.",
        "what_analysts_missed": "Same structural conditions, wildly different outcomes. The variable was not whether revolution occurred but what institutional structure caught the pieces. States with functional armies had coups; states with tribal armies had civil wars; states with professional military allowed transition.",
        "key_lesson": "Cascade revolutions spread through demonstration effect and shared grievance, but outcomes depend on local institutional depth. The revolution is the easy part — what matters is what structure exists to receive power.",
        "transferable_pattern": "Shared structural stress + information amplification → synchronized grievance activation. But the same trigger produces democracy, authoritarianism, or state collapse depending on institutional depth and military structure.",
        "relevance_tags": ["cascade_revolution", "demonstration_effect", "legitimacy_crisis", "information_amplification", "institutional_depth"],
    },
    # ── PANDEMIC & SYSTEMIC SHOCK ──
    {
        "id": "covid_2020",
        "event": "COVID-19 Pandemic Response",
        "period": "2020-01 to 2022",
        "category": "systemic_shock",
        "structural_conditions": [
            "pandemic_governance_failure", "supply_chain_fragility",
            "information_disorder", "state_capacity_variation",
            "inequality_amplification", "international_coordination_failure",
        ],
        "key_actors": ["China", "USA", "EU", "WHO", "pharmaceutical companies"],
        "trigger": "Novel coronavirus emergence → global pandemic",
        "escalation_path": "Local outbreak → delayed international response → global pandemic → lockdowns → supply chain disruption → economic crisis → vaccine inequality → lasting institutional damage",
        "outcome": "7M+ official deaths (likely 15-25M excess). $12T+ in fiscal response. Accelerated remote work, digital transformation. Deepened inequality. Demonstrated vast state capacity variation. Fueled populism and institutional distrust.",
        "what_analysts_missed": "Pre-pandemic simulations existed but were ignored. The critical failure was not lack of warning but lack of political will to act on early signals. Information disorder turned public health into a political battlefield.",
        "key_lesson": "Known risks that are structurally addressed in plans but not politically funded or maintained might as well be unknown. The binding constraint on systemic risk response is political will, not technical knowledge.",
        "transferable_pattern": "Systemic shocks that are predictable in type (not timing) are under-prepared because the political cost of preparation exceeds the perceived immediate benefit. When the shock arrives, response is determined by pre-existing state capacity and social trust, not crisis-time improvisation.",
        "relevance_tags": ["pandemic_governance", "state_capacity", "information_disorder", "supply_chain_fragility", "coordination_failure"],
    },
    # ── TECHNOLOGY & SOCIETY DISRUPTIONS ──
    {
        "id": "printing_press_1450",
        "event": "Gutenberg Printing Press & Reformation",
        "period": "1450 to 1555",
        "category": "information_revolution",
        "structural_conditions": [
            "information_technology_disruption", "institutional_legitimacy_erosion",
            "narrative_monopoly_breakdown", "decentralized_knowledge_production",
            "elite_backlash", "social_fragmentation",
        ],
        "key_actors": ["Catholic Church", "Martin Luther", "European monarchies", "merchant class"],
        "trigger": "Printing press → mass literacy → Luther's 95 Theses spread → Reformation → wars of religion",
        "escalation_path": "New technology → information democratization → challenge to institutional monopoly on truth → fragmentation → violence → new equilibrium after 100+ years",
        "outcome": "Reformation, Counter-Reformation, 150 years of religious wars (30 Years War killed 1/3 of Germany), eventually religious tolerance, nation-state system (Westphalia 1648)",
        "what_analysts_missed": "The Church saw printing as a tool, not a threat. By the time they tried to control it, the information ecosystem had already decentralized beyond control.",
        "key_lesson": "When a new information technology breaks an institution's monopoly on truth, the transition period is measured in generations, not years, and involves significant violence before a new equilibrium emerges.",
        "transferable_pattern": "Information technology disruptions don't just spread knowledge — they destroy the authority of gatekeepers. The transition from old information order to new one is always longer and more violent than optimists predict.",
        "relevance_tags": ["information_revolution", "institutional_legitimacy", "truth_monopoly_breakdown", "social_fragmentation", "technological_disruption"],
    },
    {
        "id": "industrial_revolution_1780",
        "event": "First Industrial Revolution & Social Upheaval",
        "period": "1780 to 1850",
        "category": "technological_disruption",
        "structural_conditions": [
            "labor_displacement", "urbanization_shock",
            "inequality_explosion", "institutional_lag",
            "new_class_formation", "environmental_degradation",
        ],
        "key_actors": ["UK", "Factory owners", "Working class", "Luddites", "Chartists"],
        "trigger": "Mechanization of textile production → factory system → mass urbanization",
        "escalation_path": "Technology → labor displacement → urbanization → squalor → social unrest → reform movements → eventually: labor laws, public health, democracy expansion (50-70 year lag)",
        "outcome": "Massive wealth creation alongside massive human suffering. Took 2-3 generations for institutions to adapt. Created the modern class structure. Child labor, 16-hour workdays, pollution — until reform caught up.",
        "what_analysts_missed": "Optimists focused on aggregate wealth growth. Pessimists focused on immediate suffering. Both missed the key variable: institutional adaptation speed. The technology was neither good nor bad — the 50-70 year institutional lag determined who suffered.",
        "key_lesson": "Technological revolutions create wealth and suffering simultaneously. The critical variable is how fast institutions adapt to redistribute benefits and contain harms. Lag = suffering.",
        "transferable_pattern": "Technology changes faster than institutions. The gap between technological capability and institutional capacity to govern it is where human suffering concentrates. This gap typically lasts 2-3 generations.",
        "relevance_tags": ["technological_disruption", "labor_displacement", "institutional_lag", "inequality", "adaptation_speed"],
    },
    # ── GEOPOLITICAL TRANSITIONS ──
    {
        "id": "thucydides_trap_athens_sparta",
        "event": "Peloponnesian War (Thucydides Trap)",
        "period": "-431 to -404",
        "category": "power_transition",
        "structural_conditions": [
            "rising_power_vs_established_power", "alliance_entanglement",
            "honor_fear_interest", "miscalculated_war_duration",
            "democratic_vs_oligarchic_friction",
        ],
        "key_actors": ["Athens", "Sparta", "Corinth", "Persian Empire"],
        "trigger": "Rising Athenian power → Spartan fear → peripheral conflicts (Corcyra, Potidaea) → war",
        "escalation_path": "Power shift → fear → peripheral proxy conflicts → alliance pressure → direct confrontation → 27-year war neither side planned",
        "outcome": "Athens defeated after 27 years. Both powers permanently weakened. Eventual Macedonian/Roman dominance.",
        "what_analysts_missed": "Both sides expected a short war. Thucydides: 'It was the rise of Athens and the fear that this inspired in Sparta that made war inevitable.' But it wasn't inevitable — it was the failure to manage the transition.",
        "key_lesson": "When a rising power threatens to displace an established power, the structural tension creates a risk of war even when neither side wants it. The danger multiplies when peripheral allies drag great powers into commitments.",
        "transferable_pattern": "Rising power dynamics create structural tension. War often starts through peripheral entanglements, not direct confrontation. Both sides expect short wars and get long ones.",
        "relevance_tags": ["power_transition", "thucydides_trap", "alliance_entanglement", "peripheral_escalation", "structural_tension"],
    },
    {
        "id": "ukraine_invasion_2022",
        "event": "Russia's Invasion of Ukraine",
        "period": "2022-02 to present",
        "category": "modern_great_power_war",
        "structural_conditions": [
            "revisionist_power", "imperial_nostalgia",
            "nato_expansion_grievance", "deterrence_ambiguity",
            "information_warfare", "economic_interdependence_weaponized",
            "nuclear_shadow",
        ],
        "key_actors": ["Russia (Putin)", "Ukraine (Zelensky)", "USA/NATO", "EU", "China"],
        "trigger": "Russian military buildup → invasion despite Western warnings → Ukrainian resistance → Western sanctions/aid",
        "escalation_path": "Buildup → invasion → failed blitzkrieg → grinding war → economic warfare → energy weaponization → nuclear rhetoric → frozen/attritional conflict",
        "outcome": "Ongoing. Demonstrated: European security architecture broken. Energy weaponization (Nord Stream). Information warfare at scale. Nuclear deterrence constrains but doesn't prevent sub-nuclear aggression.",
        "what_analysts_missed": "Many dismissed invasion warnings because 'Putin is rational' and invasion seemed economically irrational. The miss: rationality is relative to the actor's reference frame. Imperial restoration was more valuable to Putin than economic cost.",
        "key_lesson": "Deterrence works only when the deterree shares your cost-benefit calculus. If the adversary values something you consider irrational (imperial glory, historical narrative, regime survival), your deterrence model is wrong.",
        "transferable_pattern": "When deterrence relies on economic rationality but the adversary operates on a different utility function (regime survival, historical destiny), rational signals are misread in both directions.",
        "relevance_tags": ["revisionist_power", "deterrence_failure", "energy_weaponization", "nuclear_shadow", "information_warfare", "imperial_nostalgia"],
    },
    # ── TRADE & ECONOMIC WARFARE ──
    {
        "id": "smoot_hawley_1930",
        "event": "Smoot-Hawley Tariff Act & Trade War",
        "period": "1930-06",
        "category": "trade_war",
        "structural_conditions": [
            "protectionist_impulse", "economic_downturn",
            "domestic_political_pressure", "retaliation_cascade",
            "international_cooperation_collapse",
        ],
        "key_actors": ["USA (Hoover)", "European trading partners", "US Congress"],
        "trigger": "1929 crash → protectionist political pressure → 20,000+ tariffs raised → retaliation",
        "escalation_path": "Economic downturn → domestic industry lobbying → sweeping tariffs → trading partner retaliation → trade volume collapse 65% → depression deepened",
        "outcome": "Global trade fell 65% in 3 years. Deepened and globalized the Depression. Led to 1934 Reciprocal Trade Agreements Act and eventually GATT/WTO.",
        "what_analysts_missed": "1,028 economists signed a letter warning against the act. Congress passed it anyway. The lesson: sound analysis loses to concentrated domestic political pressure in downturns.",
        "key_lesson": "Tariffs in a downturn trigger retaliation cascades that shrink the total pie. The political logic (protect domestic industry) is individually rational but collectively catastrophic.",
        "transferable_pattern": "Economic distress → protectionist pressure → tariff escalation → retaliation → trade collapse → deeper economic distress. The cycle is self-reinforcing once started.",
        "relevance_tags": ["trade_war", "tariff_cascade", "protectionism", "retaliation_spiral", "economic_nationalism"],
    },
    {
        "id": "plaza_accord_1985",
        "event": "Plaza Accord & Currency Warfare",
        "period": "1985-09",
        "category": "economic_coordination",
        "structural_conditions": [
            "trade_imbalance", "currency_manipulation_accusation",
            "cooperative_multilateral_solution", "japan_bubble_seeds",
        ],
        "key_actors": ["USA (Reagan/Baker)", "Japan", "West Germany", "France", "UK"],
        "trigger": "US trade deficit ballooning → pressure on Japan → coordinated G5 intervention to weaken USD",
        "escalation_path": "Trade imbalance → political pressure → multilateral agreement → managed depreciation → BUT: Japan's response (loose monetary policy) inflated asset bubble → 1989 crash → 'Lost Decades'",
        "outcome": "Temporarily fixed US trade deficit. But Japan's accommodative monetary policy created massive asset bubble, which burst in 1989 and led to decades of stagnation.",
        "what_analysts_missed": "The deal 'worked' in the short term but created the conditions for Japan's lost decades. Coordinated currency management can solve trade imbalances but transfers the stress to asset prices and monetary policy.",
        "key_lesson": "International economic coordination can solve immediate problems but create larger ones if the adjustment mechanism is monetary easing that inflates asset bubbles.",
        "transferable_pattern": "Trade imbalances resolved through currency adjustment often shift the problem from trade to asset prices. The adjustment creates winners and losers, and the losers may suffer for decades.",
        "relevance_tags": ["trade_imbalance", "currency_coordination", "unintended_consequences", "asset_bubble", "economic_coordination"],
    },
    # ── INFORMATION & SOCIETY ──
    {
        "id": "weimar_hyperinflation_1923",
        "event": "Weimar Hyperinflation",
        "period": "1921 to 1923",
        "category": "monetary_collapse",
        "structural_conditions": [
            "war_reparation_debt", "money_printing",
            "political_instability", "social_trust_erosion",
            "middle_class_destruction", "extremism_fuel",
        ],
        "key_actors": ["Weimar Germany", "France", "Allied powers", "Reichsbank"],
        "trigger": "War reparations + French occupation of Ruhr → Germany prints money → hyperinflation",
        "escalation_path": "Debt burden → money printing → price spiral → savings wiped out → middle class radicalized → brief stabilization → Great Depression → Nazi rise",
        "outcome": "Mark went from 4.2/USD to 4.2 trillion/USD. Middle class savings destroyed. Created deep distrust of institutions that Nazis exploited a decade later.",
        "what_analysts_missed": "Hyperinflation was 'solved' in 1924 (Rentenmark). But the psychological damage — middle class feeling of betrayal by institutions — was permanent and created fertile ground for extremism.",
        "key_lesson": "Monetary collapse doesn't just destroy savings — it destroys institutional trust. The political consequences appear years or decades later, long after the 'technical' fix.",
        "transferable_pattern": "When institutions destroy the savings of the middle class (through inflation, financial crisis, or policy failure), the political radicalization that follows is not immediate but inevitable. The lag conceals the causal link.",
        "relevance_tags": ["monetary_collapse", "institutional_trust_erosion", "middle_class_destruction", "delayed_radicalization", "extremism_fuel"],
    },
    # ── MODERN SECURITY ──
    {
        "id": "911_response_2001",
        "event": "9/11 & Security Overreaction",
        "period": "2001-09 to 2003",
        "category": "security_overreaction",
        "structural_conditions": [
            "shock_trauma_response", "threat_inflation",
            "institutional_overreaction", "civil_liberties_erosion",
            "intelligence_failure", "war_of_choice",
        ],
        "key_actors": ["USA (Bush)", "Al-Qaeda", "Iraq", "UK (Blair)", "NATO"],
        "trigger": "9/11 terrorist attacks → War on Terror → Afghanistan → Iraq",
        "escalation_path": "Terrorist attack → national trauma → threat inflation → Afghanistan (justified) → Iraq (war of choice based on false intelligence) → 20-year occupation → $8T spent → institutional credibility damaged",
        "outcome": "Two decades of war. $8T cost. 900,000+ deaths. ISIS (unintended consequence of Iraq). Erosion of US credibility and domestic trust in institutions. Surveillance state expansion.",
        "what_analysts_missed": "The overreaction was more costly than the attack. Iraq War was chosen, not necessary. The threat was inflated by institutional incentives (intelligence agencies, defense industry, political calculation). The cure was worse than the disease.",
        "key_lesson": "Traumatic shocks create political environments where overreaction is rewarded and restraint is punished. The second-order effects of the response often exceed the first-order effects of the original shock.",
        "transferable_pattern": "Shock → threat inflation → institutional overreaction → second-order costs exceeding original damage. This pattern recurs because the political incentives during crisis favor action over restraint.",
        "relevance_tags": ["security_overreaction", "threat_inflation", "institutional_overreaction", "war_of_choice", "second_order_effects"],
    },
    {
        "id": "suez_crisis_1956",
        "event": "Suez Crisis — Imperial Decline Moment",
        "period": "1956-10 to 1956-11",
        "category": "power_transition",
        "structural_conditions": [
            "imperial_decline", "superpower_realignment",
            "regional_nationalism", "alliance_humiliation",
            "miscalculated_great_power_support",
        ],
        "key_actors": ["UK", "France", "Israel", "Egypt (Nasser)", "USA (Eisenhower)", "USSR"],
        "trigger": "Nasser nationalizes Suez Canal → Anglo-French-Israeli invasion → US/USSR pressure forces withdrawal",
        "escalation_path": "Nationalization → military operation → superpower opposition → humiliating withdrawal → permanent British decline",
        "outcome": "UK and France forced to withdraw. Definitively ended British imperial pretensions. Shifted Middle East power dynamics. Demonstrated that old powers could no longer act without superpower approval.",
        "what_analysts_missed": "UK/France assumed the US would at minimum stay neutral. They fundamentally misread the post-WWII power structure. The era of independent European great-power military action was already over.",
        "key_lesson": "Declining powers frequently misread the new power structure. The moment of humiliation is when the gap between self-image and reality becomes undeniable.",
        "transferable_pattern": "When established powers attempt to exercise old prerogatives in a new power structure, they often discover — publicly and painfully — that the structure has already shifted.",
        "relevance_tags": ["imperial_decline", "power_transition", "miscalculated_support", "humiliation_moment", "structural_shift"],
    },
    {
        "id": "marshall_plan_1947",
        "event": "Marshall Plan — Strategic Reconstruction",
        "period": "1947-06 to 1952",
        "category": "strategic_cooperation",
        "structural_conditions": [
            "post_war_reconstruction", "ideological_competition",
            "economic_statecraft", "institutional_building",
            "strategic_generosity",
        ],
        "key_actors": ["USA (Marshall/Truman)", "Western Europe", "USSR"],
        "trigger": "Post-WWII European devastation → fear of communist expansion → US economic reconstruction program",
        "escalation_path": "War devastation → economic collapse risk → communist party growth → US strategic aid → European recovery → Western alliance consolidation → Cold War bifurcation",
        "outcome": "European GDP surpassed pre-war levels by 1952. Created conditions for European integration (later EU). Consolidated Western alliance. Most successful strategic investment in history.",
        "what_analysts_missed": "Many critics called it a giveaway. It was actually the highest-ROI strategic investment ever: $13B (≈$150B today) bought 40 years of European alliance, markets, and stability.",
        "key_lesson": "Strategic generosity at moments of systemic stress can be the most rational investment. The alternative — European collapse into communism — would have cost orders of magnitude more.",
        "transferable_pattern": "Post-crisis reconstruction that is both generous and strategically designed can build lasting institutional architecture. But it requires political will to invest heavily before the returns are visible.",
        "relevance_tags": ["strategic_cooperation", "economic_statecraft", "institutional_building", "post_crisis_reconstruction", "strategic_generosity"],
    },
    {
        "id": "bretton_woods_collapse_1971",
        "event": "Nixon Shock / Bretton Woods Collapse",
        "period": "1971-08",
        "category": "monetary_regime_change",
        "structural_conditions": [
            "unsustainable_peg", "gold_drain",
            "imperial_overstretch_fiscal", "unilateral_action",
            "regime_transition", "trust_rupture",
        ],
        "key_actors": ["USA (Nixon)", "France (de Gaulle)", "Japan", "West Germany"],
        "trigger": "US gold reserves depleting → France demanding gold conversion → Nixon unilaterally suspends convertibility",
        "escalation_path": "Fiscal strain (Vietnam + Great Society) → gold drain → unilateral suspension → end of fixed exchange rates → floating currencies → petrodollar replacement system",
        "outcome": "End of gold standard. Floating exchange rates. Dollar hegemony maintained through petrodollar system. Increased financial volatility. Enabled modern monetary policy flexibility.",
        "what_analysts_missed": "The system didn't collapse — it was deliberately dismantled by its creator when the costs of maintaining it exceeded the benefits. A superpower can rewrite the rules if no one can stop them.",
        "key_lesson": "Monetary regimes are not natural laws — they are political agreements that survive as long as the dominant power finds them useful. When they don't, the dominant power changes them unilaterally.",
        "transferable_pattern": "International economic architectures are maintained by the hegemon as long as they serve the hegemon's interests. Transitions are often unilateral, sudden, and reshuffled to the hegemon's advantage.",
        "relevance_tags": ["monetary_regime_change", "hegemonic_privilege", "unilateral_action", "regime_transition", "imperial_overstretch"],
    },
]


def get_all_events() -> list[dict]:
    """Return all historical events in the knowledge base."""
    return HISTORICAL_EVENTS


def search_by_conditions(conditions: list[str], min_match: int = 2) -> list[dict]:
    """Search events by structural conditions.

    Returns events that match at least `min_match` conditions,
    sorted by match count (descending).
    """
    results = []
    for event in HISTORICAL_EVENTS:
        event_conditions = set(event.get("structural_conditions", []))
        event_tags = set(event.get("relevance_tags", []))
        all_matchable = event_conditions | event_tags

        # Count matches
        query_set = set(conditions)
        matches = all_matchable & query_set
        if len(matches) >= min_match:
            results.append({
                **event,
                "_match_count": len(matches),
                "_matched_conditions": list(matches),
            })

    results.sort(key=lambda x: x["_match_count"], reverse=True)
    return results


def get_event_by_id(event_id: str) -> dict | None:
    """Get a specific event by ID."""
    for event in HISTORICAL_EVENTS:
        if event["id"] == event_id:
            return event
    return None


def get_all_condition_tags() -> set[str]:
    """Return all unique condition and relevance tags across all events."""
    tags = set()
    for event in HISTORICAL_EVENTS:
        tags.update(event.get("structural_conditions", []))
        tags.update(event.get("relevance_tags", []))
    return tags


def format_event_for_prompt(event: dict, include_full: bool = True) -> str:
    """Format a historical event for injection into an LLM prompt."""
    lines = [
        f"═══ {event['event']} ({event['period']}) ═══",
        f"Category: {event['category']}",
        f"Structural conditions: {', '.join(event['structural_conditions'])}",
        f"Key actors: {', '.join(event['key_actors'])}",
        f"Trigger: {event['trigger']}",
    ]
    if include_full:
        lines.extend([
            f"Escalation path: {event['escalation_path']}",
            f"Outcome: {event['outcome']}",
            f"What analysts missed: {event['what_analysts_missed']}",
            f"Key lesson: {event['key_lesson']}",
            f"Transferable pattern: {event['transferable_pattern']}",
        ])
    return "\n".join(lines)

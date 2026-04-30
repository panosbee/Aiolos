
const API_BASE = window.location.origin;
let isRunning = false;
let timerInterval = null;
let timerStart = 0;
let _lastAnalysisData = null; // stored for PDF export
let _deferredProactiveAlerts = []; // kept for legacy compat β€” queue now handles ordering

// β”€β”€ Health check β”€β”€
async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/xdart/health`);
    const data = await res.json();
    document.getElementById('healthDot').className = 'health-dot ok';
    document.getElementById('healthText').textContent = `${data.model} | ${data.memories} memories`;
  } catch {
    document.getElementById('healthDot').className = 'health-dot';
    document.getElementById('healthText').textContent = 'Disconnected';
  }
}
checkHealth();
setInterval(checkHealth, 15000);

// β”€β”€ Voice system init β”€β”€
_initVoice();

// β”€β”€ Timer β”€β”€
function startTimer() {
  timerStart = Date.now();
  const el = document.getElementById('timerDisplay');
  el.style.display = 'block';
  timerInterval = setInterval(() => {
    const s = ((Date.now() - timerStart) / 1000).toFixed(1);
    el.textContent = `β± ${s}s`;
  }, 100);
}
function stopTimer(total) {
  clearInterval(timerInterval);
  document.getElementById('timerDisplay').textContent = `β± ${total}s total`;
}

// β”€β”€ Reset progress pips β”€β”€
function resetPips() {
  ['pip-wakeup','pip-phase0','pip-phase1','pip-phase2','pip-scenarios','pip-tribunal','pip-quantum','pip-actions','pip-phase3','pip-historical','pip-strategic','pip-bets','pip-phase4'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.className = 'dot';
  });
  ['conn-w0','conn-01','conn-12','conn-2s','conn-st','conn-tq','conn-qa','conn-a3','conn-3h','conn-hs','conn-sb','conn-b4'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.className = 'phase-connector';
  });
}

function markPipActive(phaseKey) {
  const pipIds = ['pip-wakeup','pip-phase0','pip-phase1','pip-phase2','pip-scenarios','pip-tribunal','pip-quantum','pip-actions','pip-phase3','pip-historical','pip-strategic','pip-bets','pip-phase4'];
  const connIds = ['conn-w0','conn-01','conn-12','conn-2s','conn-st','conn-tq','conn-qa','conn-a3','conn-3h','conn-hs','conn-sb','conn-b4'];
  const idx = {
    'wakeup_complete':0, 'phase0_ontology':1, 'phase1_xdart':2, 'phase2_views':3,
    'phase2_5_scenarios':4, 'phase2_7_simulations':4, 'phase2_9_tribunal':5,
    'phase2_91_quantum':6, 'phase2_95_actions':7, 'phase3_xheart':8, 'phase3_5_historical':9,
    'phase3_7_strategic':10, 'phase3_9_bets':11, 'phase4_memory':12
  }[phaseKey];
  if (idx === undefined) return;
  // Mark previous as done
  for (let i = 0; i < idx; i++) {
    const el = document.getElementById(pipIds[i]);
    if (el) el.className = 'dot done';
  }
  // Mark connectors
  for (let i = 0; i < idx; i++) {
    const el = connIds[i] ? document.getElementById(connIds[i]) : null;
    if (el) el.className = 'phase-connector done';
  }
  // Current active
  const activeEl = document.getElementById(pipIds[idx]);
  if (activeEl) activeEl.className = 'dot active';
}

function markAllPipsDone() {
  ['pip-wakeup','pip-phase0','pip-phase1','pip-phase2','pip-scenarios','pip-tribunal','pip-quantum','pip-actions','pip-phase3','pip-historical','pip-strategic','pip-bets','pip-phase4'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.className = 'dot done';
  });
  ['conn-w0','conn-01','conn-12','conn-2s','conn-st','conn-tq','conn-qa','conn-a3','conn-3h','conn-hs','conn-sb','conn-b4'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.className = 'phase-connector done';
  });
}

// β”€β”€ Build phase cards β”€β”€
function buildPhase0Card(data, elapsed) {
  return `
  <div class="phase-card phase0">
    <div class="phase-card-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
      <div class="phase-card-title"><span class="icon">Ξ¦</span><h3>Phase 0 β€” Ontological Grounding</h3></div>
      <span class="phase-card-time">${elapsed}s</span>
    </div>
    <div class="phase-card-body">
      <div class="kv-row"><div class="kv-label">Ontological Nature</div><div class="kv-value">${esc(data.ontological_nature)}</div></div>
      <div class="kv-row"><div class="kv-label">Teleological Purpose</div><div class="kv-value">${esc(data.teleological_purpose)}</div></div>
      <div class="kv-row"><div class="kv-label">Causal Analysis</div><div class="kv-value">${esc(data.causal_analysis)}</div></div>
      <div class="kv-row"><div class="kv-label">Epistemological Check</div><div class="kv-value">${esc(data.epistemological_check)}</div></div>
      <div class="kv-row"><div class="kv-label">Reframed Problem</div><div class="kv-value" style="color:var(--gold);font-weight:600">${esc(data.reframed_problem)}</div></div>
    </div>
  </div>`;
}

function buildPhase1Card(data, elapsed) {
  let rows = '';
  (data.domains || []).forEach(d => {
    const cls = d.strength === 'STRONG' ? 'strength-strong' : d.strength === 'WEAK' ? 'strength-weak' : 'strength-none';
    rows += `<tr>
      <td style="font-weight:600">${esc(d.domain)}</td>
      <td class="${cls}">${d.strength}</td>
      <td style="text-align:center">${d.distance}</td>
      <td style="text-align:center">${d.specificity}</td>
      <td>${esc(d.hypothesis)}</td>
    </tr>`;
  });
  const layerCls = data.layer === 'Layer-3' ? 'layer-3' : data.layer === 'Layer-2' ? 'layer-2' : 'layer-1';

  let l3html = '';
  if (data.layer_3_hypothesis) {
    l3html = `<div style="margin-top:12px;padding:10px 14px;background:#2a1515;border-left:3px solid var(--red);border-radius:4px;font-size:13px;">
      <strong style="color:var(--red)">Layer-3 Hypothesis:</strong> ${esc(data.layer_3_hypothesis)}
    </div>`;
  }

  return `
  <div class="phase-card phase1">
    <div class="phase-card-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
      <div class="phase-card-title"><span class="icon">01</span><h3>Phase 1 β€” XDART-Ξ¦ Cross-Domain</h3></div>
      <div style="display:flex;align-items:center;gap:10px;">
        <span class="layer-badge ${layerCls}">${esc(data.layer)}</span>
        <span class="phase-card-time">${elapsed}s</span>
      </div>
    </div>
    <div class="phase-card-body">
      <table class="domain-table">
        <thead><tr><th>Domain</th><th>Strength</th><th>Dist</th><th>Spec</th><th>Transfer Hypothesis</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="kv-row" style="margin-top:12px">
        <div class="kv-label">Structural Formula</div>
        <div class="kv-value" style="font-family:var(--mono);font-size:13px">${esc(data.structural_formula || '')}</div>
      </div>
      ${l3html}
    </div>
  </div>`;
}

function buildPhase2Card(data, elapsed) {
  let views = '';
  (data.views || []).forEach(v => {
    views += `<div class="view-card">
      <div class="view-card-header">
        <span class="view-card-id">[${esc(v.id)}] ${esc(v.category)}</span>
        <span class="view-card-name">${esc(v.name)}</span>
      </div>
      <p>${esc(v.insight)}</p>
      <p class="reveals">β†’ Reveals: ${esc(v.reveals)}</p>
    </div>`;
  });

  let convergent = '';
  (data.convergent || []).forEach(p => { convergent += `<span class="chip convergent">${esc(p)}</span>`; });
  let divergent = '';
  (data.divergent || []).forEach(p => { divergent += `<span class="chip divergent">${esc(p)}</span>`; });

  return `
  <div class="phase-card phase2">
    <div class="phase-card-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
      <div class="phase-card-title"><span class="icon">02</span><h3>Phase 2 β€” Multiple Views (${(data.views||[]).length} applied)</h3></div>
      <span class="phase-card-time">${elapsed}s</span>
    </div>
    <div class="phase-card-body">
      ${views}
      ${convergent ? `<div style="margin-top:12px"><strong style="color:var(--green);font-size:12px;text-transform:uppercase">Convergent Patterns</strong><div class="chip-list">${convergent}</div></div>` : ''}
      ${divergent ? `<div style="margin-top:12px"><strong style="color:#c0a040;font-size:12px;text-transform:uppercase">Divergent Insights</strong><div class="chip-list">${divergent}</div></div>` : ''}
      <div class="kv-row" style="margin-top:12px"><div class="kv-label">Dominant Pattern</div><div class="kv-value" style="font-weight:600">${esc(data.dominant || '')}</div></div>
    </div>
  </div>`;
}

function buildScenarioGenesisCard(data, elapsed) {
  const names = Array.isArray(data.names) ? data.names : [];
  let scenarioList = '';
  names.forEach((n, i) => {
    scenarioList += `<div style="margin-bottom:6px;padding:6px 12px;background:rgba(255,171,64,0.08);border-radius:6px;border-left:2px solid #ffab40;font-size:13px;color:var(--text-secondary)">
      <strong style="color:#ffab40">${i + 1}.</strong> ${esc(n)}
    </div>`;
  });
  return `
  <div class="phase-card" style="border-left:3px solid #ffab40">
    <div class="phase-card-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
      <div class="phase-card-title"><span class="icon" style="color:#ffab40">β΅</span><h3>Phase 2.5 β€” Scenario Genesis (${data.count || 0} scenarios)</h3></div>
      <span class="phase-card-time">${elapsed}s</span>
    </div>
    <div class="phase-card-body">
      ${scenarioList}
      ${data.logic ? `<div style="margin-top:10px;font-size:12px;color:var(--text-dim);font-style:italic">${esc(data.logic)}</div>` : ''}
    </div>
  </div>`;
}

function buildSimulationCard(data, elapsed) {
  return `
  <div class="phase-card" style="border-left:3px solid #ff8a65">
    <div class="phase-card-header">
      <div class="phase-card-title"><span class="icon" style="color:#ff8a65">β©</span><h3>Phase 2.7 β€” Scenario Simulation (${data.count || 0} simulated)</h3></div>
      <span class="phase-card-time">${elapsed}s</span>
    </div>
    <div class="phase-card-body">
      ${data.summary ? `<div style="font-size:13px;color:var(--text-secondary);line-height:1.6">${esc(data.summary)}</div>` : '<div style="font-size:12px;color:var(--text-dim)">Forward-projection simulations completed.</div>'}
    </div>
  </div>`;
}

function buildTribunalCard(data, elapsed) {
  const convergence = Array.isArray(data.convergence_points) ? data.convergence_points : [];
  let convergenceHtml = '';
  convergence.slice(0, 5).forEach(p => {
    convergenceHtml += `<span class="chip convergent">${esc(p)}</span>`;
  });
  return `
  <div class="phase-card" style="border-left:3px solid #ef5350">
    <div class="phase-card-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
      <div class="phase-card-title"><span class="icon" style="color:#ef5350">β–</span><h3>Phase 2.9 β€” Scenario Tribunal</h3></div>
      <span class="phase-card-time">${elapsed}s</span>
    </div>
    <div class="phase-card-body">
      <div style="margin-bottom:14px;padding:12px;background:rgba(239,83,80,0.08);border-radius:8px;border-left:3px solid #ef5350">
        <div style="font-size:11px;color:var(--text-dim);text-transform:uppercase;margin-bottom:4px">Dominant Scenario</div>
        <div style="font-size:16px;font-weight:700;color:#ef5350">${esc(data.dominant || '?')}</div>
        <div style="font-size:12px;color:var(--text-dim);margin-top:2px">Score: ${typeof data.dominant_score === 'number' ? data.dominant_score.toFixed(2) : '?'} | Alternatives: ${data.alternatives || 0}</div>
      </div>
      ${convergenceHtml ? `<div style="margin-bottom:10px"><strong style="color:#ef5350;font-size:12px;text-transform:uppercase">Convergence Points</strong><div class="chip-list" style="margin-top:6px">${convergenceHtml}</div></div>` : ''}
      ${data.synthesis ? `<div style="font-size:13px;color:var(--text-secondary);line-height:1.6;border-left:2px solid rgba(239,83,80,0.3);padding-left:12px">${esc(data.synthesis)}</div>` : ''}
    </div>
  </div>`;
}

function buildQuantumCard(data, elapsed) {
  const qDom = data.quantum_dominant || 'β€”';
  const qProb = typeof data.quantum_probability === 'number' ? (data.quantum_probability * 100).toFixed(1) : '?';
  const cDom = data.classical_dominant || 'β€”';
  const shifted = data.observer_shifted;
  const iCount = data.interference_count || 0;
  const basis = data.measurement_basis || 'β€”';
  const narrative = data.quantum_narrative || '';
  const hidden = Array.isArray(data.hidden_signals) ? data.hidden_signals : [];
  const entClusters = Array.isArray(data.entanglement_clusters) ? data.entanglement_clusters : [];
  const collapsed = data.collapsed_probabilities || {};

  // Build probability bars
  let probBarsHtml = '';
  const sortedProbs = Object.entries(collapsed).sort((a, b) => b[1] - a[1]);
  for (const [name, prob] of sortedProbs) {
    const pct = (prob * 100).toFixed(1);
    const isQuantumDom = name === qDom;
    const barColor = isQuantumDom ? '#7c4dff' : 'rgba(124,77,255,0.35)';
    probBarsHtml += `
    <div style="margin-bottom:6px">
      <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:2px">
        <span style="color:${isQuantumDom ? '#b388ff' : 'var(--text-dim)'};font-weight:${isQuantumDom ? '700' : '400'}">${esc(name)}${isQuantumDom ? ' β—' : ''}</span>
        <span style="color:var(--text-dim);font-family:var(--mono)">${pct}%</span>
      </div>
      <div style="height:6px;background:var(--surface2);border-radius:3px;overflow:hidden">
        <div style="height:100%;width:${pct}%;background:${barColor};border-radius:3px;transition:width 0.6s ease"></div>
      </div>
    </div>`;
  }

  // Hidden signals
  let hiddenHtml = '';
  if (hidden.length) {
    hiddenHtml = `<div style="margin-top:14px">
      <div style="font-size:11px;color:#b388ff;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">β΅ Hidden Signals (${hidden.length})</div>
      <div class="chip-list">${hidden.map(s => `<span class="chip" style="border-color:#7c4dff;color:#b388ff;font-size:11px">${esc(typeof s === 'string' ? s : s.signal || s.name || JSON.stringify(s))}</span>`).join('')}</div>
    </div>`;
  }

  // Entanglement clusters
  let entHtml = '';
  if (entClusters.length) {
    entHtml = `<div style="margin-top:14px">
      <div style="font-size:11px;color:#b388ff;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">π”— Entanglement Clusters (${entClusters.length})</div>
      <div class="chip-list">${entClusters.map(c => `<span class="chip" style="border-color:#651fff;color:#ea80fc">${esc(typeof c === 'string' ? c : c.shared_condition || c.name || JSON.stringify(c))}</span>`).join('')}</div>
    </div>`;
  }

  // Observer shift banner
  const shiftBanner = shifted
    ? `<div style="margin-bottom:14px;padding:10px 14px;background:rgba(124,77,255,0.12);border-radius:8px;border:1px solid rgba(124,77,255,0.3);display:flex;align-items:center;gap:10px">
        <span style="font-size:20px">π”®</span>
        <div>
          <div style="font-size:12px;color:#b388ff;font-weight:700;text-transform:uppercase">Observer Effect Detected</div>
          <div style="font-size:12px;color:var(--text-dim);margin-top:2px">Quantum measurement shifted dominance from <strong style="color:#ef5350">${esc(cDom)}</strong> β†’ <strong style="color:#7c4dff">${esc(qDom)}</strong></div>
        </div>
      </div>`
    : `<div style="margin-bottom:14px;padding:10px 14px;background:rgba(124,77,255,0.06);border-radius:8px;border:1px dashed rgba(124,77,255,0.2);display:flex;align-items:center;gap:10px">
        <span style="font-size:16px;opacity:0.5">π“</span>
        <div style="font-size:12px;color:var(--text-dim)">Classical dominant <strong style="color:var(--text)">${esc(cDom)}</strong> confirmed β€” no observer shift</div>
      </div>`;

  return `
  <div class="phase-card quantum" style="border-left:3px solid #7c4dff">
    <div class="phase-card-header" onclick="this.nextElementSibling.classList.toggle('collapsed')" style="background:linear-gradient(135deg,#12121a,#1a1230)">
      <div class="phase-card-title"><span class="icon" style="color:#7c4dff">β›</span><h3>Phase 2.91 β€” Quantum Scenario Engine</h3></div>
      <div style="display:flex;align-items:center;gap:10px">
        <span style="font-size:11px;padding:2px 10px;border-radius:10px;background:rgba(124,77,255,0.12);color:#b388ff;font-weight:600">${iCount} interference Β· ${hidden.length} hidden</span>
        <span class="phase-card-time">${elapsed}s</span>
      </div>
    </div>
    <div class="phase-card-body">
      ${shiftBanner}
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">
        <div style="padding:12px;background:rgba(124,77,255,0.08);border-radius:8px;border-left:3px solid #7c4dff">
          <div style="font-size:11px;color:var(--text-dim);text-transform:uppercase;margin-bottom:4px">Quantum Dominant</div>
          <div style="font-size:15px;font-weight:700;color:#b388ff">${esc(qDom)}</div>
          <div style="font-size:12px;color:var(--text-dim);margin-top:2px">P = ${qProb}%</div>
        </div>
        <div style="padding:12px;background:var(--surface2);border-radius:8px;border-left:3px solid var(--border)">
          <div style="font-size:11px;color:var(--text-dim);text-transform:uppercase;margin-bottom:4px">Measurement Basis</div>
          <div style="font-size:13px;font-weight:600;color:var(--text)">${esc(basis)}</div>
          <div style="font-size:12px;color:var(--text-dim);margin-top:2px">${iCount} interference patterns</div>
        </div>
      </div>
      ${sortedProbs.length ? `<div style="margin-bottom:14px"><div style="font-size:11px;color:#b388ff;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">Collapsed Probabilities</div>${probBarsHtml}</div>` : ''}
      ${hiddenHtml}
      ${entHtml}
      ${narrative ? `<div style="margin-top:14px;font-size:13px;color:var(--text-secondary);line-height:1.7;border-left:2px solid rgba(124,77,255,0.3);padding-left:12px">${esc(narrative)}</div>` : ''}
    </div>
  </div>`;
}

function buildActionsCard(data, elapsed) {
  const robustMoves = Array.isArray(data.robust_moves) ? data.robust_moves : [];
  const playbooks = Array.isArray(data.scenario_playbooks) ? data.scenario_playbooks : [];
  const clientRole = data.client_role || '';

  let robustHtml = '';
  for (const rm of robustMoves) {
    const scenarios = Array.isArray(rm.appears_in_scenarios) ? rm.appears_in_scenarios : [];
    robustHtml += `
    <div class="robust-move">
      <div class="rm-action">${esc(rm.action)}</div>
      <div class="rm-meta">
        <span style="color:#4caf50;font-weight:600">β± ${esc(rm.urgency || 'N/A')}</span>
        <span>Appears in: ${scenarios.map(s => esc(s)).join(', ')}</span>
      </div>
      ${rm.reasoning ? `<div style="font-size:12px;color:var(--text-dim);margin-top:4px">${esc(rm.reasoning)}</div>` : ''}
    </div>`;
  }

  let playbookHtml = '';
  for (const pb of playbooks) {
    const actions = Array.isArray(pb.actions) ? pb.actions : [];
    let actionsHtml = '';
    for (const a of actions) {
      actionsHtml += `
      <div class="playbook-action">
        <div class="pa-seq">${a.sequence || '?'}</div>
        <div class="pa-body">
          <div class="pa-text">${esc(a.action)}</div>
          <div class="pa-meta">
            β± ${esc(a.deadline || '?')}${a.mechanism ? ` Β· ${esc(a.mechanism)}` : ''}${a.depends_on ? ` Β· depends: ${esc(a.depends_on)}` : ''}
          </div>
        </div>
      </div>`;
    }
    const prob = typeof pb.scenario_probability === 'number' ? (pb.scenario_probability * 100).toFixed(0) + '%' : '?';
    playbookHtml += `
    <div class="playbook-card">
      <div class="pb-header">
        <div class="pb-name">${esc(pb.scenario_name || pb.scenario_id)}</div>
        <div class="pb-prob">P = ${prob}</div>
      </div>
      ${pb.rationale ? `<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px;font-style:italic">${esc(pb.rationale)}</div>` : ''}
      ${actionsHtml}
    </div>`;
  }

  return `
  <div class="phase-card" style="border-left:3px solid #4caf50">
    <div class="phase-card-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
      <div class="phase-card-title"><span class="icon" style="color:#4caf50">π―</span><h3>Phase 2.95 β€” Scenario-Action Mapping</h3></div>
      <div style="display:flex;align-items:center;gap:10px">
        ${clientRole ? `<span style="font-size:11px;color:var(--text-dim)">For: ${esc(clientRole)}</span>` : ''}
        <span style="font-size:11px;padding:2px 10px;border-radius:10px;background:rgba(76,175,80,0.12);color:#4caf50;font-weight:600">${robustMoves.length} robust Β· ${playbooks.length} playbooks</span>
        <span class="phase-card-time">${elapsed}s</span>
      </div>
    </div>
    <div class="phase-card-body">
      ${robustMoves.length ? `
        <div style="margin-bottom:16px">
          <div style="font-size:13px;font-weight:700;color:#4caf50;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.5px">β“ Do These Regardless of Scenario</div>
          ${robustHtml}
        </div>` : ''}
      ${playbooks.length ? `
        <div>
          <div style="font-size:13px;font-weight:700;color:#ffab40;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.5px">Scenario-Specific Playbooks</div>
          ${playbookHtml}
        </div>` : ''}
    </div>
  </div>`;
}

function buildPhase3Card(data, elapsed) {
  const synthCls = data.has_synthesis ? 'has-synthesis' : 'no-synthesis';
  const synthText = data.has_synthesis
    ? 'β“ Synthesis survived β€” Layer-3 confirmed'
    : 'β  No synthesis β€” speculation only';
  return `
  <div class="phase-card phase3">
    <div class="phase-card-header">
      <div class="phase-card-title"><span class="icon" style="color:var(--red)">β™¥</span><h3>Phase 3 β€” XHEART Distillation</h3></div>
      <span class="phase-card-time">${elapsed}s</span>
    </div>
    <div class="phase-card-body">
      <div class="xheart-internal">
        <div class="heart">β™¥</div>
        <p>Internal affective distillation processed.<br>The XHEART state shapes the output but is never shown.</p>
        <p class="xheart-status ${synthCls}">${synthText}</p>
      </div>
    </div>
  </div>`;
}

function buildExpansionCard(data, elapsed) {
  return `
  <div class="phase-card" style="border-left:3px solid #b388ff">
    <div class="phase-card-header">
      <div class="phase-card-title"><span class="icon" style="color:#b388ff">β³</span><h3>Self-Generated Layer: ${esc(data.layer_name)}</h3></div>
      <span class="phase-card-time">${elapsed}s</span>
    </div>
    <div class="phase-card-body">
      <div style="margin-bottom:10px;font-size:12px;color:var(--text-dim)">
        Type: <strong style="color:#b388ff">${esc(data.layer_type)}</strong> β€” XHEART detected a gap and invented a new reasoning layer
      </div>
      <div style="margin-bottom:10px">
        <strong>Gap detected:</strong><br>
        <span style="color:var(--text-secondary)">${esc(data.gap_description)}</span>
      </div>
      <div>
        <strong>Key insight:</strong><br>
        <span style="color:var(--text-primary)">${esc(data.key_insight)}</span>
      </div>
    </div>
  </div>`;
}

function buildHistoricalCard(data, elapsed) {
  const verdict = (typeof data.verdict === 'object' && data.verdict) ? data.verdict : {};
  const analyses = Array.isArray(data.parallel_analyses) ? data.parallel_analyses : [];
  const conditions = Array.isArray(data.structural_conditions) ? data.structural_conditions : [];

  let parallelsHtml = '';
  for (const a of analyses.slice(0, 4)) {
    if (a.error) continue;
    const confidence = typeof a.confidence === 'number' ? (a.confidence * 100).toFixed(0) + '%' : '?';
    const insights = (a.transfer_insights || []).slice(0, 2).map(i => esc(i)).join('<br>');
    parallelsHtml += `
      <div style="margin-bottom:10px;padding:8px 12px;background:rgba(255,152,0,0.06);border-radius:6px;border-left:2px solid #ff9800">
        <strong style="color:#ff9800">${esc(a.event_name || '?')}</strong>
        <span style="color:var(--text-dim);font-size:11px;margin-left:8px">${esc(a.event_period || '')}</span>
        <span style="color:var(--text-dim);font-size:11px;margin-left:8px">confidence: ${confidence}</span>
        ${insights ? `<div style="margin-top:4px;font-size:12px;color:var(--text-secondary)">β†’ ${insights}</div>` : ''}
      </div>`;
  }

  return `
  <div class="phase-card" style="border-left:3px solid #ff9800">
    <div class="phase-card-header">
      <div class="phase-card-title"><span class="icon" style="color:#ff9800">π“</span><h3>Phase 3.5 β€” Historical Resonance</h3></div>
      <span class="phase-card-time">${elapsed}s</span>
    </div>
    <div class="phase-card-body">
      <div style="margin-bottom:10px;font-size:12px;color:var(--text-dim)">
        Conditions: ${conditions.length} | Parallels: ${data.parallels_found || 0}
      </div>
      ${parallelsHtml}
      ${verdict.historical_warning ? `<div style="margin-top:12px;padding:10px;background:rgba(255,152,0,0.1);border-radius:6px">
        <strong style="color:#ff9800">β  Historical Warning:</strong><br>
        <span style="color:var(--text-primary);font-size:13px">${esc(verdict.historical_warning)}</span>
      </div>` : ''}
      ${verdict.pattern_beneath ? `<div style="margin-top:8px;font-size:13px;color:var(--text-secondary)">
        <strong>Pattern beneath:</strong> ${esc(verdict.pattern_beneath)}
      </div>` : ''}
    </div>
  </div>`;
}

function buildStrategicCard(data, elapsed) {
  const assessment = data.strategic_assessment || '';
  const decisions = Array.isArray(data.decision_points) ? data.decision_points : [];
  const confidence = (typeof data.confidence_calibration === 'object' && data.confidence_calibration) ? data.confidence_calibration : {};
  const historicalWarning = data.historical_warning || '';
  const riskMatrix = (typeof data.risk_opportunity_matrix === 'object' && data.risk_opportunity_matrix) ? data.risk_opportunity_matrix : {};
  const risks = Array.isArray(riskMatrix.risks) ? riskMatrix.risks : (Array.isArray(data.risk_opportunity_matrix) ? data.risk_opportunity_matrix : []);
  const opportunities = Array.isArray(riskMatrix.opportunities) ? riskMatrix.opportunities : [];

  // New fields: immediate_actions + contingency_summaries
  const immediateActions = Array.isArray(data.immediate_actions) ? data.immediate_actions : [];
  const contingencySummaries = Array.isArray(data.contingency_summaries) ? data.contingency_summaries : [];

  // Legacy fields (still support old format)
  const watchSignals = Array.isArray(data.what_to_watch) ? data.what_to_watch : [];
  const recs = (typeof data.recommendations_by_role === 'object' && data.recommendations_by_role) ? data.recommendations_by_role : {};

  let decisionsHtml = '';
  for (const d of decisions.slice(0, 5)) {
    const decision = typeof d === 'object' ? (d.decision || d.description || d.what || JSON.stringify(d)) : String(d);
    const deadline = typeof d === 'object' && d.deadline_description ? `<span style="color:var(--text-dim);font-size:11px;margin-left:6px">β± ${esc(d.deadline_description)}</span>` : '';
    decisionsHtml += `<li style="margin-bottom:6px;color:var(--text-secondary)">${esc(decision)}${deadline}</li>`;
  }

  // Immediate Actions (robust moves synthesis from Phase 2.95)
  let immediateHtml = '';
  for (const a of immediateActions.slice(0, 8)) {
    const txt = typeof a === 'object' ? (a.action || a.description || JSON.stringify(a)) : String(a);
    const urgency = typeof a === 'object' && a.urgency ? `<span style="color:#4caf50;font-size:11px;margin-left:6px">β± ${esc(a.urgency)}</span>` : '';
    immediateHtml += `<li style="margin-bottom:6px;color:var(--text-secondary)">${esc(txt)}${urgency}</li>`;
  }

  // Contingency Summaries (per-scenario one-liners)
  let contingencyHtml = '';
  for (const c of contingencySummaries.slice(0, 6)) {
    const scenario = typeof c === 'object' ? (c.scenario || c.scenario_name || '') : '';
    const summary = typeof c === 'object' ? (c.summary || c.action || JSON.stringify(c)) : String(c);
    contingencyHtml += `<div style="margin-bottom:6px;padding:4px 10px;border-left:2px solid #ffab40;font-size:12px">
      ${scenario ? `<strong style="color:#ffab40;font-size:11px">${esc(scenario)}:</strong> ` : ''}
      <span style="color:var(--text-secondary)">${esc(summary)}</span>
    </div>`;
  }

  let riskHtml = '';
  for (const r of risks.slice(0, 4)) {
    const label = typeof r === 'object' ? (r.item || r.risk || r.label || JSON.stringify(r)) : String(r);
    riskHtml += `<div style="margin-bottom:4px;padding:4px 10px;border-left:2px solid #ff5252;font-size:12px;color:var(--text-secondary)">β  ${esc(label)}</div>`;
  }
  for (const o of opportunities.slice(0, 3)) {
    const label = typeof o === 'object' ? (o.item || o.opportunity || o.label || JSON.stringify(o)) : String(o);
    riskHtml += `<div style="margin-bottom:4px;padding:4px 10px;border-left:2px solid #69f0ae;font-size:12px;color:var(--text-secondary)">β¦ ${esc(label)}</div>`;
  }

  // Legacy: what_to_watch + recommendations_by_role
  let watchHtml = '';
  for (const w of watchSignals.slice(0, 5)) {
    const signal = typeof w === 'object' ? (w.signal || w.indicator || w.description || JSON.stringify(w)) : String(w);
    watchHtml += `<li style="margin-bottom:4px;color:var(--text-secondary)">${esc(signal)}</li>`;
  }
  let recsHtml = '';
  for (const [role, advice] of Object.entries(recs)) {
    const advStr = typeof advice === 'string' ? advice : (Array.isArray(advice) ? advice.join('; ') : JSON.stringify(advice));
    recsHtml += `<div style="margin-bottom:6px"><strong style="color:#e040fb;font-size:11px;text-transform:uppercase">${esc(role)}</strong><div style="font-size:12px;color:var(--text-secondary);padding-left:10px">${esc(advStr)}</div></div>`;
  }

  const confPercent = typeof confidence.overall_confidence === 'number' ? (confidence.overall_confidence * 100).toFixed(0) + '%' : '?';

  return `
  <div class="phase-card" style="border-left:3px solid #e040fb">
    <div class="phase-card-header">
      <div class="phase-card-title"><span class="icon" style="color:#e040fb">π―</span><h3>Phase 3.7 β€” Strategic Foresight</h3></div>
      <div style="display:flex;align-items:center;gap:10px">
        <span style="font-size:11px;color:var(--text-dim)">Confidence: ${confPercent}</span>
        <span class="phase-card-time">${elapsed}s</span>
      </div>
    </div>
    <div class="phase-card-body">
      ${assessment ? `<div style="margin-bottom:14px;font-size:14px;color:var(--text-primary);line-height:1.5">${esc(assessment)}</div>` : ''}
      ${immediateHtml ? `<div style="margin-bottom:12px"><strong style="color:#4caf50;font-size:12px">IMMEDIATE ACTIONS</strong><ul style="margin:6px 0;padding-left:18px">${immediateHtml}</ul></div>` : ''}
      ${contingencyHtml ? `<div style="margin-bottom:12px"><strong style="color:#ffab40;font-size:12px">CONTINGENCY SUMMARIES</strong><div style="margin-top:6px">${contingencyHtml}</div></div>` : ''}
      ${decisionsHtml ? `<div style="margin-bottom:12px"><strong style="color:#e040fb;font-size:12px">DECISION POINTS</strong><ul style="margin:6px 0;padding-left:18px">${decisionsHtml}</ul></div>` : ''}
      ${riskHtml ? `<div style="margin-bottom:12px"><strong style="color:#e040fb;font-size:12px">RISK / OPPORTUNITY</strong><div style="margin-top:6px">${riskHtml}</div></div>` : ''}
      ${watchHtml ? `<div style="margin-bottom:12px"><strong style="color:#e040fb;font-size:12px">WHAT TO WATCH</strong><ul style="margin:6px 0;padding-left:18px">${watchHtml}</ul></div>` : ''}
      ${recsHtml ? `<div style="margin-bottom:12px"><strong style="color:#e040fb;font-size:12px">RECOMMENDATIONS</strong><div style="margin-top:6px">${recsHtml}</div></div>` : ''}
      ${historicalWarning ? `<div style="padding:10px;background:rgba(224,64,251,0.08);border-radius:6px">
        <strong style="color:#e040fb;font-size:12px">HISTORICAL WARNING</strong><br>
        <span style="font-size:13px;color:var(--text-secondary)">${esc(historicalWarning)}</span>
      </div>` : ''}
    </div>
  </div>`;
}

function buildBetsCard(data, elapsed) {
  const triggers = Array.isArray(data.decision_triggers) ? data.decision_triggers : [];
  const bets = Array.isArray(data.bets) ? data.bets : [];
  const metaPrediction = data.meta_prediction || '';
  const prophetConfidence = typeof data.prophet_confidence === 'number' ? (data.prophet_confidence * 100).toFixed(0) + '%' : '?';
  const prophetReasoning = data.prophet_reasoning || '';

  // Decision Triggers
  let triggersHtml = '';
  for (const t of triggers) {
    const conditions = Array.isArray(t.conditions) ? t.conditions : [];
    let condHtml = '';
    for (const c of conditions) {
      condHtml += `
      <div class="trigger-condition">
        <span class="tc-signal-icon">IF</span>
        <span class="tc-signal">${esc(c.signal || '?')}</span>
        ${c.check_method ? `<span class="tc-check">[${esc(c.check_method)}]</span>` : ''}
      </div>`;
    }

    triggersHtml += `
    <div class="trigger-card">
      <div class="tc-header">
        <span class="tc-id">${esc(t.trigger_id || '')}</span>
        <span class="tc-action-label">${esc(t.threshold || 'all')} conditions</span>
      </div>
      ${condHtml}
      <div class="trigger-then">
        <div class="tt-label">Then β†’</div>
        <div class="tt-scenario">Scenario: <strong>${esc(t.activates_scenario || '?')}</strong></div>
        <div class="tt-playbook">Execute: ${esc(t.activates_playbook || '?')}</div>
        ${t.time_to_act ? `<div class="tt-time">β± Time to act: ${esc(t.time_to_act)}</div>` : ''}
        ${t.false_positive_risk ? `<div class="tt-risk">β  False positive: ${esc(t.false_positive_risk)}</div>` : ''}
      </div>
    </div>`;
  }

  // Prophetic Bets (retained for Brier scoring)
  let betsHtml = '';
  for (const bet of bets) {
    const stmt = bet.statement || '?';
    const deadline = bet.deadline || '?';
    const conf = typeof bet.confidence === 'number' ? (bet.confidence * 100).toFixed(0) + '%' : '?';
    const mechanism = bet.mechanism || '';
    const evidence = bet.evidence_base || '';
    const novelty = bet.novelty || 'MEDIUM';
    const tracking = bet.tracking_signal || '';
    const betId = bet.bet_id || '';

    const noveltyColor = novelty === 'HIGH' ? '#ff5252' : novelty === 'LOW' ? '#78909c' : '#ffab40';
    const noveltyBg = novelty === 'HIGH' ? 'rgba(255,82,82,0.1)' : novelty === 'LOW' ? 'rgba(120,144,156,0.1)' : 'rgba(255,171,64,0.1)';

    betsHtml += `
    <div style="margin-bottom:14px;padding:12px;background:rgba(255,215,0,0.04);border-radius:8px;border:1px solid rgba(255,215,0,0.15)">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
        <div style="font-size:14px;color:var(--text-primary);font-weight:600;flex:1;line-height:1.4">${esc(stmt)}</div>
        <span style="font-size:10px;padding:2px 8px;border-radius:10px;background:${noveltyBg};color:${noveltyColor};font-weight:600;white-space:nowrap;margin-left:10px">${esc(novelty)}</span>
      </div>
      <div style="display:flex;gap:14px;margin-bottom:8px;flex-wrap:wrap">
        <span style="font-size:11px;color:#ffd740;font-weight:600">β± ${esc(deadline)}</span>
        <span style="font-size:11px;color:var(--text-dim)">Confidence: ${conf}</span>
        ${betId ? `<span style="font-size:11px;color:var(--text-dim)">${esc(betId)}</span>` : ''}
      </div>
      ${mechanism ? `<div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px"><strong style="color:#ffd740;font-size:11px">MECHANISM:</strong> ${esc(mechanism)}</div>` : ''}
      ${evidence ? `<div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px"><strong style="color:#ffd740;font-size:11px">EVIDENCE:</strong> ${esc(evidence)}</div>` : ''}
      ${tracking ? `<div style="font-size:12px;color:var(--text-secondary)"><strong style="color:#ffd740;font-size:11px">TRACKING SIGNAL:</strong> ${esc(tracking)}</div>` : ''}
    </div>`;
  }

  return `
  <div class="phase-card" style="border-left:3px solid #ff9800">
    <div class="phase-card-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
      <div class="phase-card-title"><span class="icon" style="color:#ff9800">β΅</span><h3>Phase 3.9 β€” Decision Triggers</h3></div>
      <div style="display:flex;align-items:center;gap:10px">
        <span style="font-size:11px;color:var(--text-dim)">Prophet confidence: ${prophetConfidence}</span>
        <span style="font-size:11px;padding:2px 10px;border-radius:10px;background:rgba(255,152,0,0.12);color:#ff9800;font-weight:600">${triggers.length} triggers Β· ${bets.length} bets</span>
        <span class="phase-card-time">${elapsed}s</span>
      </div>
    </div>
    <div class="phase-card-body">
      ${triggers.length ? `
        <div style="margin-bottom:18px">
          <div style="font-size:13px;font-weight:700;color:#ff9800;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.5px">Decision Triggers β€” If/Then Rules</div>
          ${triggersHtml}
        </div>` : ''}
      ${bets.length ? `
        <div>
          <div style="font-size:13px;font-weight:700;color:#ffd740;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.5px">Prophetic Bets (Brier-tracked)</div>
          ${betsHtml}
        </div>` : ''}
      ${metaPrediction ? `<div style="padding:12px;background:rgba(255,215,64,0.08);border-radius:6px;margin-top:10px">
        <strong style="color:#ffd740;font-size:12px">META-PREDICTION</strong><br>
        <span style="font-size:13px;color:var(--text-primary);line-height:1.5">${esc(metaPrediction)}</span>
      </div>` : ''}
      ${prophetReasoning ? `<div style="margin-top:8px;font-size:12px;color:var(--text-dim);font-style:italic">${esc(prophetReasoning)}</div>` : ''}
    </div>
  </div>`;
}

function buildConceptsCard(data, elapsed) {
  const concepts = data.concepts || [];
  if (!concepts.length) return '';
  const items = concepts.map(c => `
    <div style="margin-bottom:10px;padding:8px 12px;background:rgba(0,230,118,0.06);border-radius:6px;border-left:2px solid #00e676">
      <strong style="color:#00e676">${esc(c.name)}</strong>
      <span style="color:var(--text-dim);font-size:11px;margin-left:8px">similarity: ${c.similarity}</span>
      <div style="margin-top:4px;font-size:13px;color:var(--text-secondary)">${esc(c.key_insight)}</div>
    </div>
  `).join('');
  return `
  <div class="phase-card" style="border-left:3px solid #00e676">
    <div class="phase-card-header">
      <div class="phase-card-title"><span class="icon" style="color:#00e676">π§ </span><h3>Concept Registry β€” ${concepts.length} concept${concepts.length > 1 ? 's' : ''} activated</h3></div>
      <span class="phase-card-time">${elapsed}s</span>
    </div>
    <div class="phase-card-body">
      <div style="margin-bottom:8px;font-size:12px;color:var(--text-dim)">
        These concepts were discovered in past reasoning runs and are now informing this analysis.
      </div>
      ${items}
    </div>
  </div>`;
}

function buildWorldContextCard(data, elapsed) {
  const evCount = data.events_count || 0;
  const indCount = data.indicators_count || 0;
  const sample = data.sample || '';
  return `
  <div class="phase-card" style="border-left:3px solid #26c6da">
    <div class="phase-card-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
      <div class="phase-card-title"><span class="icon" style="color:#26c6da">π</span><h3>Phase 0.35 β€” World Perception</h3></div>
      <div style="display:flex;align-items:center;gap:10px;">
        <span style="font-size:11px;padding:2px 10px;border-radius:10px;background:rgba(38,198,218,0.12);color:#26c6da;font-weight:600">${evCount} events Β· ${indCount} indicators</span>
        <span class="phase-card-time">${elapsed}s</span>
      </div>
    </div>
    <div class="phase-card-body">
      <div style="font-size:13px;color:var(--text);line-height:1.6;white-space:pre-wrap;max-height:200px;overflow-y:auto;font-family:var(--mono);font-size:12px;background:var(--surface2);padding:12px;border-radius:6px">${esc(sample)}</div>
      <div style="margin-top:8px;font-size:11px;color:var(--text-dim);text-align:center">
        Real-world context injected into Phase 0 β€” RSS, FRED, ECB, World Bank
      </div>
    </div>
  </div>`;
}

function buildWakeupCard(data, elapsed) {
  const tensions = data.active_tensions || 0;
  const changes = data.changes || 0;
  const concepts = data.concepts_owned || 0;
  const runs = data.immediate_runs || 0;
  const stance = data.epistemic_stance || '';
  return `
  <div class="phase-card wakeup">
    <div class="phase-card-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
      <div class="phase-card-title"><span class="icon" style="color:#00bcd4">β—‰</span><h3>Phase 0.0 β€” Identity Wakeup</h3></div>
      <div style="display:flex;align-items:center;gap:10px;">
        <span style="font-size:12px;color:#00bcd4;font-weight:600">v${data.version || 0}</span>
        <span class="phase-card-time">${elapsed}s</span>
      </div>
    </div>
    <div class="phase-card-body">
      <div style="margin-bottom:12px;font-size:14px;color:var(--text-bright);line-height:1.7;font-style:italic;border-left:3px solid #00bcd4;padding-left:14px;">
        ${esc(stance)}
      </div>
      <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:13px;">
        <span style="color:#00bcd4">β— ${concepts} concepts owned</span>
        <span style="color:#ff9800">β΅ ${tensions} active tensions</span>
        <span style="color:#b388ff">β†» ${changes} character changes</span>
        <span style="color:var(--text-dim)">π“ ${runs} recent runs in memory</span>
      </div>
    </div>
  </div>`;
}

function buildCharacterUpdatedCard(data, elapsed) {
  return `
  <div class="phase-card character">
    <div class="phase-card-header">
      <div class="phase-card-title"><span class="icon" style="color:#ff9800">β†»</span><h3>Phase 5b β€” Character Update</h3></div>
      <div style="display:flex;align-items:center;gap:10px;">
        <span style="font-size:12px;color:#ff9800;font-weight:600">v${data.version || '?'}</span>
        <span class="phase-card-time">${elapsed}s</span>
      </div>
    </div>
    <div class="phase-card-body">
      <div style="font-size:13px;color:var(--text-dim);text-align:center;padding:8px 0;">
        Character state rewritten β€” ${data.tensions || 0} active tensions, ${data.changes || 0} epistemic shifts recorded.
      </div>
    </div>
  </div>`;
}

function buildCoreChangeCard(data, elapsed) {
  const isApplied = data.applied === true;
  const statusColor = isApplied ? '#4caf50' : '#ff5252';
  const statusLabel = isApplied ? 'AUTO-APPLIED' : 'PROPOSED (not applied)';
  const statusIcon = isApplied ? 'β“' : 'β™';
  const borderColor = isApplied ? '#4caf50' : '#ff5252';
  const bgGradient = isApplied
    ? 'linear-gradient(135deg, #0a1a0a, var(--surface))'
    : 'linear-gradient(135deg, #1a0a0a, var(--surface))';
  return `
  <div class="phase-card" style="border-left:3px solid ${borderColor};border:1px solid ${borderColor};background:${bgGradient}">
    <div class="phase-card-header" onclick="this.nextElementSibling.classList.toggle('collapsed')" style="background:rgba(${isApplied ? '76,175,80' : '255,82,82'},0.08)">
      <div class="phase-card-title"><span class="icon" style="color:${statusColor}">${statusIcon}</span><h3>Core Change β€” ${statusLabel}</h3></div>
      <div style="display:flex;align-items:center;gap:10px;">
        <span style="font-size:11px;padding:2px 10px;border-radius:10px;background:rgba(${isApplied ? '76,175,80' : '255,82,82'},0.15);color:${statusColor};font-weight:600">${esc(data.change_type)}</span>
        <span class="phase-card-time">${elapsed}s</span>
      </div>
    </div>
    <div class="phase-card-body">
      <div class="kv-row"><div class="kv-label" style="color:${statusColor}">Target</div><div class="kv-value" style="font-family:var(--mono);font-size:13px">${esc(data.target)}</div></div>
      <div class="kv-row"><div class="kv-label" style="color:${statusColor}">Description</div><div class="kv-value">${esc(data.description)}</div></div>
      <div class="kv-row"><div class="kv-label" style="color:${statusColor}">Reasoning</div><div class="kv-value" style="font-style:italic">${esc(data.reasoning)}</div></div>
      ${data.applied_patch ? `<div class="kv-row"><div class="kv-label" style="color:#4caf50">Patch</div><div class="kv-value" style="font-size:12px;color:#4caf50">${esc(data.applied_patch)}</div></div>` : ''}
      <div style="margin-top:10px;font-size:11px;color:var(--text-dim);text-align:center">
        Entry ID: ${esc(data.change_id)} β€” ${isApplied ? 'applied to character_state.json' : 'logged to core_change_log.jsonl'}
      </div>
    </div>
  </div>`;
}

function buildEvolutionCard(data, elapsed) {
  return `
  <div class="phase-card" style="border-left:3px solid #69f0ae">
    <div class="phase-card-header">
      <div class="phase-card-title"><span class="icon" style="color:#69f0ae">π§¬</span><h3>Evolution β€” Tool Deployed</h3></div>
      <span class="phase-card-time">${elapsed}s</span>
    </div>
    <div class="phase-card-body">
      <div style="margin-bottom:8px;font-size:14px;color:#69f0ae;font-weight:600">${esc(data.tool_name || '?')}</div>
      ${data.purpose ? `<div style="font-size:13px;color:var(--text-secondary);margin-bottom:6px">${esc(data.purpose)}</div>` : ''}
      ${data.improvement ? `<div style="font-size:12px;color:var(--text-dim);font-style:italic">${esc(data.improvement)}</div>` : ''}
    </div>
  </div>`;
}

function buildFinalCard(data) {
  const layerCls = data.layer === 'Layer-3' ? 'layer-3' : data.layer === 'Layer-2' ? 'layer-2' : 'layer-1';

  // β”€β”€ Scenario-Action Mapping summary in final card β”€β”€
  let actionsHtml = '';
  const sa = data.scenario_actions;
  if (sa && (Array.isArray(sa.robust_moves) && sa.robust_moves.length)) {
    let movesHtml = '';
    for (const rm of sa.robust_moves.slice(0, 5)) {
      movesHtml += `
        <div style="margin-bottom:6px;padding:6px 10px;border-left:2px solid #4caf50;font-size:12px">
          <strong style="color:#4caf50">${esc(rm.action)}</strong>
          <span style="color:var(--text-dim);font-size:11px;margin-left:6px">β± ${esc(rm.urgency || '')}</span>
        </div>`;
    }
    const pbCount = Array.isArray(sa.scenario_playbooks) ? sa.scenario_playbooks.length : 0;
    actionsHtml = `
      <div style="margin-top:14px;padding:16px;background:rgba(76,175,80,0.05);border:1px solid rgba(76,175,80,0.2);border-radius:8px">
        <div style="font-size:14px;font-weight:700;color:#4caf50;margin-bottom:12px">π― Action Playbooks${sa.client_role ? ` <span style="font-size:11px;font-weight:400;color:var(--text-dim)">for: ${esc(sa.client_role)}</span>` : ''}</div>
        <div style="margin-bottom:8px"><strong style="color:#4caf50;font-size:12px">DO REGARDLESS:</strong></div>
        ${movesHtml}
        <div style="font-size:11px;color:var(--text-dim);margin-top:8px">${pbCount} scenario-specific playbooks available (see Phase 2.95 card above)</div>
      </div>`;
  }

  // β”€β”€ Strategic Foresight section β”€β”€
  let strategicHtml = '';
  const sf = data.strategic_foresight;
  if (sf && sf.strategic_assessment) {
    const decisions = Array.isArray(sf.decision_points) ? sf.decision_points : [];
    let decisionsHtml = '';
    for (const d of decisions.slice(0, 5)) {
      const txt = typeof d === 'object' ? (d.decision || d.description || d.what || JSON.stringify(d)) : String(d);
      decisionsHtml += `<li style="margin-bottom:4px;color:var(--text-secondary)">${esc(txt)}</li>`;
    }

    // New: immediate_actions
    const immediateActions = Array.isArray(sf.immediate_actions) ? sf.immediate_actions : [];
    let immediateHtml = '';
    for (const a of immediateActions.slice(0, 5)) {
      const txt = typeof a === 'object' ? (a.action || a.description || JSON.stringify(a)) : String(a);
      immediateHtml += `<li style="margin-bottom:4px;color:var(--text-secondary)">${esc(txt)}</li>`;
    }

    // New: contingency_summaries
    const contingencySummaries = Array.isArray(sf.contingency_summaries) ? sf.contingency_summaries : [];
    let contingencyHtml = '';
    for (const c of contingencySummaries.slice(0, 5)) {
      const scenario = typeof c === 'object' ? (c.scenario || c.scenario_name || '') : '';
      const summary = typeof c === 'object' ? (c.summary || c.action || JSON.stringify(c)) : String(c);
      contingencyHtml += `<div style="margin-bottom:4px;padding:4px 10px;border-left:2px solid #ffab40;font-size:12px">
        ${scenario ? `<strong style="color:#ffab40;font-size:11px">${esc(scenario)}:</strong> ` : ''}
        <span style="color:var(--text-secondary)">${esc(summary)}</span>
      </div>`;
    }

    // Legacy fields (backward compat)
    const watch = Array.isArray(sf.what_to_watch) ? sf.what_to_watch : [];
    let watchHtml = '';
    for (const w of watch.slice(0, 5)) {
      const txt = typeof w === 'object' ? (w.signal || w.indicator || w.description || JSON.stringify(w)) : String(w);
      watchHtml += `<li style="margin-bottom:4px;color:var(--text-secondary)">${esc(txt)}</li>`;
    }

    const riskMatrix = (typeof sf.risk_opportunity_matrix === 'object' && sf.risk_opportunity_matrix) ? sf.risk_opportunity_matrix : {};
    const risks = Array.isArray(riskMatrix.risks) ? riskMatrix.risks : (Array.isArray(sf.risk_opportunity_matrix) ? sf.risk_opportunity_matrix : []);
    const opportunities = Array.isArray(riskMatrix.opportunities) ? riskMatrix.opportunities : [];
    let riskHtml = '';
    for (const r of risks.slice(0, 4)) {
      const label = typeof r === 'object' ? (r.item || r.risk || r.label || JSON.stringify(r)) : String(r);
      riskHtml += `<div style="margin-bottom:4px;padding:4px 10px;border-left:2px solid #ff5252;font-size:12px;color:var(--text-secondary)">β  ${esc(label)}</div>`;
    }
    for (const o of opportunities.slice(0, 3)) {
      const label = typeof o === 'object' ? (o.item || o.opportunity || o.label || JSON.stringify(o)) : String(o);
      riskHtml += `<div style="margin-bottom:4px;padding:4px 10px;border-left:2px solid #69f0ae;font-size:12px;color:var(--text-secondary)">β¦ ${esc(label)}</div>`;
    }

    const confCal = (typeof sf.confidence_calibration === 'object' && sf.confidence_calibration) ? sf.confidence_calibration : {};
    const confP = typeof confCal.overall_confidence === 'number' ? (confCal.overall_confidence * 100).toFixed(0) + '%' : '';

    strategicHtml = `
      <div style="margin-top:20px;padding:16px;background:rgba(224,64,251,0.05);border:1px solid rgba(224,64,251,0.2);border-radius:8px">
        <div style="font-size:14px;font-weight:700;color:#e040fb;margin-bottom:12px">π― Strategic Foresight${confP ? ` <span style="font-size:11px;font-weight:400;color:var(--text-dim)">(confidence: ${confP})</span>` : ''}</div>
        <div style="font-size:13px;color:var(--text-primary);line-height:1.6;margin-bottom:14px">${esc(sf.strategic_assessment)}</div>
        ${immediateHtml ? `<div style="margin-bottom:12px"><strong style="color:#4caf50;font-size:12px">IMMEDIATE ACTIONS</strong><ul style="margin:6px 0;padding-left:18px">${immediateHtml}</ul></div>` : ''}
        ${contingencyHtml ? `<div style="margin-bottom:12px"><strong style="color:#ffab40;font-size:12px">CONTINGENCY SUMMARIES</strong><div style="margin-top:6px">${contingencyHtml}</div></div>` : ''}
        ${decisionsHtml ? `<div style="margin-bottom:12px"><strong style="color:#e040fb;font-size:12px">KEY DECISION POINTS</strong><ul style="margin:6px 0;padding-left:18px">${decisionsHtml}</ul></div>` : ''}
        ${riskHtml ? `<div style="margin-bottom:12px"><strong style="color:#e040fb;font-size:12px">RISK / OPPORTUNITY MATRIX</strong><div style="margin-top:6px">${riskHtml}</div></div>` : ''}
        ${watchHtml ? `<div style="margin-bottom:12px"><strong style="color:#e040fb;font-size:12px">WHAT TO WATCH</strong><ul style="margin:6px 0;padding-left:18px">${watchHtml}</ul></div>` : ''}
        ${sf.historical_warning ? `<div style="padding:10px;background:rgba(255,152,0,0.08);border-radius:6px;border-left:2px solid #ff9800"><strong style="color:#ff9800;font-size:12px">β  HISTORICAL WARNING</strong><div style="font-size:12px;color:var(--text-secondary);margin-top:4px">${esc(sf.historical_warning)}</div></div>` : ''}
      </div>`;
  }

  // β”€β”€ Historical summary β”€β”€
  let historicalSummary = '';
  const hr = data.historical_resonance;
  if (hr && hr.parallels_found) {
    const v = (typeof hr.verdict === 'object' && hr.verdict) ? hr.verdict : {};
    historicalSummary = `
      <div style="margin-top:14px;padding:12px;background:rgba(255,152,0,0.05);border:1px solid rgba(255,152,0,0.2);border-radius:8px">
        <div style="font-size:13px;font-weight:700;color:#ff9800;margin-bottom:8px">π“ Historical Resonance β€” ${hr.parallels_found} parallels${v.strongest_parallel ? ` Β· strongest: ${esc(v.strongest_parallel)}` : ''}</div>
        ${v.historical_consensus ? `<div style="font-size:12px;color:var(--text-secondary);line-height:1.5;margin-bottom:8px">${esc(v.historical_consensus)}</div>` : ''}
        ${v.historical_warning ? `<div style="font-size:12px;color:#ff9800;font-style:italic">${esc(v.historical_warning)}</div>` : ''}
      </div>`;
  }

  // β”€β”€ Decision Triggers + Bets β”€β”€
  let triggersAndBetsHtml = '';
  const dt = data.decision_triggers;
  if (dt) {
    const triggers = Array.isArray(dt.decision_triggers) ? dt.decision_triggers : [];
    const bets = Array.isArray(dt.bets) ? dt.bets : [];

    let trigItems = '';
    for (const t of triggers.slice(0, 4)) {
      const conds = Array.isArray(t.conditions) ? t.conditions.map(c => esc(c.signal || '?')).join(' + ') : '';
      trigItems += `
        <div style="margin-bottom:8px;padding:8px 10px;background:rgba(255,152,0,0.04);border-radius:6px;border-left:2px solid #ff9800">
          <div style="font-size:12px;color:var(--text)"><strong style="color:#ff9800">IF</strong> ${conds}</div>
          <div style="font-size:12px;color:var(--text-dim);margin-top:2px"><strong style="color:#4caf50">THEN</strong> β†’ ${esc(t.activates_scenario || '?')} β†’ ${esc(t.activates_playbook || '?')}${t.time_to_act ? ` <span style="color:#ff9800">β± ${esc(t.time_to_act)}</span>` : ''}</div>
        </div>`;
    }

    let betItems = '';
    for (const bet of bets.slice(0, 4)) {
      const stmt = bet.statement || '?';
      const deadline = bet.deadline || '?';
      const conf = typeof bet.confidence === 'number' ? (bet.confidence * 100).toFixed(0) + '%' : '?';
      const novelty = bet.novelty || 'MEDIUM';
      const noveltyColor = novelty === 'HIGH' ? '#ff5252' : novelty === 'LOW' ? '#78909c' : '#ffab40';
      betItems += `
        <div style="margin-bottom:10px;padding:10px;background:rgba(255,215,64,0.04);border-radius:6px;border-left:2px solid #ffd740">
          <div style="font-size:13px;color:var(--text-primary);font-weight:600;line-height:1.4;margin-bottom:4px">${esc(stmt)}</div>
          <div style="display:flex;gap:12px;font-size:11px;color:var(--text-dim)">
            <span style="color:#ffd740">β± ${esc(deadline)}</span>
            <span>Confidence: ${conf}</span>
            <span style="color:${noveltyColor}">${esc(novelty)}</span>
          </div>
        </div>`;
    }

    if (trigItems || betItems) {
      triggersAndBetsHtml = `
        <div style="margin-top:14px;padding:16px;background:rgba(255,152,0,0.05);border:1px solid rgba(255,152,0,0.2);border-radius:8px">
          ${trigItems ? `
            <div style="font-size:14px;font-weight:700;color:#ff9800;margin-bottom:12px">β΅ Decision Triggers β€” ${triggers.length} rules</div>
            ${trigItems}` : ''}
          ${betItems ? `
            <div style="font-size:14px;font-weight:700;color:#ffd740;margin-bottom:12px;${trigItems ? 'margin-top:16px;' : ''}">π”® Prophetic Bets β€” ${bets.length} predictions</div>
            ${betItems}` : ''}
          ${dt.meta_prediction ? `<div style="margin-top:10px;padding:10px;background:rgba(255,215,64,0.08);border-radius:6px"><strong style="color:#ffd740;font-size:12px">META-PREDICTION:</strong> <span style="font-size:13px;color:var(--text-primary)">${esc(dt.meta_prediction)}</span></div>` : ''}
        </div>`;
    }
  }

  return `
  <div class="phase-card final">
    <div class="phase-card-header" style="border-bottom-color:var(--gold)">
      <div class="phase-card-title"><span class="icon" style="color:var(--gold)">β—</span><h3>Final Output</h3></div>
      <div style="display:flex;align-items:center;gap:10px;">
        <span class="layer-badge ${layerCls}">${esc(data.layer)}</span>
        <span class="phase-card-time">${data.total_elapsed}s total</span>
      </div>
    </div>
    <div class="phase-card-body">
      <div class="final-output">${esc(data.final_output)}</div>
      <div class="falsifiability">
        <strong>Falsifiability:</strong><br>
        ${esc(data.falsifiability)}
      </div>
      ${actionsHtml}
      ${strategicHtml}
      ${historicalSummary}
      ${triggersAndBetsHtml}
      <div style="margin-top:16px;display:flex;flex-wrap:wrap;gap:8px;font-size:12px;color:var(--text-dim);align-items:center">
        <span>Domains: ${(data.domains_used||[]).join(', ')}</span>
        <span>|</span>
        <span>Views: ${(data.views_used||[]).length}</span>
        <span>|</span>
        <span>Memories: ${data.memory_count}</span>
        ${data.concept_count ? `<span>|</span><span style="color:#00e676">π§  Concepts: ${data.concept_count}</span>` : ''}
        ${data.expansion_triggered ? `<span>|</span><span style="color:#b388ff">β³ Expansion: ${esc(data.expansion_layer)}</span>` : ''}
        <span style="flex:1"></span>
        <button onclick="generatePDFReport()" style="padding:6px 16px;background:linear-gradient(135deg,#d4a843,#a07830);color:#0a0a0f;border:none;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;letter-spacing:0.5px">π“„ Executive Brief</button>
        <button onclick="generateDossierPDF()" style="padding:6px 16px;background:linear-gradient(135deg,#7b1fa2,#4a148c);color:#fff;border:none;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;letter-spacing:0.5px">π“‹ Full Dossier</button>
      </div>
    </div>
  </div>`;
}

// β”€β”€ Executive Brief Card (Phase 3.95) β”€β”€
function buildExecutiveBriefCard(data, elapsed) {
  let judgmentsHtml = '';
  for (const j of (data.key_judgments || []).slice(0, 6)) {
    judgmentsHtml += `<li style="margin-bottom:6px;color:var(--text-primary);font-size:13px;line-height:1.5">${esc(j)}</li>`;
  }
  let actionsHtml = '';
  for (const a of (data.recommended_actions || []).slice(0, 8)) {
    actionsHtml += `<li style="margin-bottom:6px;color:var(--text-primary);font-size:13px;line-height:1.5">${esc(a)}</li>`;
  }
  return `
  <div class="phase-card" style="border-left:3px solid #ffd740;background:rgba(255,215,64,0.03)">
    <div class="phase-card-header" style="border-bottom-color:rgba(255,215,64,0.3)">
      <div class="phase-card-title"><span class="icon" style="color:#ffd740">π“‹</span><h3>Executive Intelligence Brief</h3></div>
      <span class="phase-card-time">${elapsed}s</span>
    </div>
    <div class="phase-card-body">
      ${data.bottom_line ? `
      <div style="padding:14px 18px;background:rgba(255,215,64,0.08);border:1px solid rgba(255,215,64,0.25);border-radius:8px;margin-bottom:16px">
        <div style="font-size:11px;font-weight:700;color:#ffd740;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">BOTTOM LINE</div>
        <div style="font-size:14px;color:var(--text-primary);line-height:1.7">${esc(data.bottom_line)}</div>
      </div>` : ''}
      ${data.situation ? `
      <div style="margin-bottom:14px">
        <div style="font-size:12px;font-weight:700;color:#e040fb;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">SITUATION</div>
        <div style="font-size:13px;color:var(--text-secondary);line-height:1.6">${esc(data.situation).substring(0, 500)}${data.situation.length > 500 ? '...' : ''}</div>
      </div>` : ''}
      ${judgmentsHtml ? `
      <div style="margin-bottom:14px">
        <div style="font-size:12px;font-weight:700;color:#ffd740;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">KEY JUDGMENTS</div>
        <ol style="margin:0;padding-left:18px">${judgmentsHtml}</ol>
      </div>` : ''}
      ${actionsHtml ? `
      <div style="margin-bottom:14px">
        <div style="font-size:12px;font-weight:700;color:#4caf50;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">RECOMMENDED ACTIONS</div>
        <ol style="margin:0;padding-left:18px">${actionsHtml}</ol>
      </div>` : ''}
      ${data.critical_timeline ? `
      <div style="margin-bottom:14px">
        <div style="font-size:12px;font-weight:700;color:#ff9800;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">CRITICAL TIMELINE</div>
        <div style="font-size:13px;color:var(--text-secondary);line-height:1.6">${esc(data.critical_timeline).substring(0, 400)}${data.critical_timeline.length > 400 ? '...' : ''}</div>
      </div>` : ''}
      ${data.confidence_statement ? `
      <div style="font-size:11px;color:var(--text-dim);padding:8px 12px;background:rgba(255,255,255,0.02);border-radius:6px;margin-top:8px">${esc(data.confidence_statement)}</div>` : ''}
    </div>
  </div>`;
}

function esc(s) {
  if (!s) return '';
  const div = document.createElement('div');
  div.textContent = String(s);
  return div.innerHTML;
}

// β”€β”€ PDF Report Generator β”€β”€
function generatePDFReport() {
  const d = _lastAnalysisData;
  if (!d) { alert('No analysis data available.'); return; }

  const escPdf = (s) => {
    if (!s) return '';
    const el = document.createElement('div');
    el.textContent = String(s);
    return el.innerHTML;
  };

  const now = new Date().toLocaleString('en-GB', { dateStyle: 'long', timeStyle: 'short' });

  // β”€β”€ Strategic Foresight β”€β”€
  let strategicSection = '';
  const sf = d.strategic_foresight;
  if (sf && sf.strategic_assessment) {
    let dpHtml = '';
    for (const dp of (sf.decision_points || []).slice(0, 8)) {
      const txt = typeof dp === 'object' ? (dp.decision || dp.description || JSON.stringify(dp)) : String(dp);
      const dl = typeof dp === 'object' && dp.deadline_description ? ` β€” <em>${escPdf(dp.deadline_description)}</em>` : '';
      dpHtml += `<li>${escPdf(txt)}${dl}</li>`;
    }
    let iaHtml = '';
    for (const a of (sf.immediate_actions || []).slice(0, 8)) {
      const txt = typeof a === 'object' ? (a.action || a.description || JSON.stringify(a)) : String(a);
      iaHtml += `<li>${escPdf(txt)}</li>`;
    }
    let csHtml = '';
    for (const c of (sf.contingency_summaries || []).slice(0, 8)) {
      const scenario = typeof c === 'object' ? (c.scenario || c.scenario_name || '') : '';
      const summary = typeof c === 'object' ? (c.summary || c.action || JSON.stringify(c)) : String(c);
      csHtml += `<li>${scenario ? `<strong>${escPdf(scenario)}:</strong> ` : ''}${escPdf(summary)}</li>`;
    }
    const rm = (sf.risk_opportunity_matrix && typeof sf.risk_opportunity_matrix === 'object') ? sf.risk_opportunity_matrix : {};
    const risks = Array.isArray(rm.risks) ? rm.risks : [];
    const opps = Array.isArray(rm.opportunities) ? rm.opportunities : [];
    let rmHtml = '';
    for (const r of risks.slice(0, 6)) {
      const label = typeof r === 'object' ? (r.item || r.risk || JSON.stringify(r)) : String(r);
      rmHtml += `<li style="color:#c0392b">β  ${escPdf(label)}</li>`;
    }
    for (const o of opps.slice(0, 4)) {
      const label = typeof o === 'object' ? (o.item || o.opportunity || JSON.stringify(o)) : String(o);
      rmHtml += `<li style="color:#27ae60">β¦ ${escPdf(label)}</li>`;
    }
    const confCal = (sf.confidence_calibration && typeof sf.confidence_calibration === 'object') ? sf.confidence_calibration : {};
    const confPct = typeof confCal.overall_confidence === 'number' ? (confCal.overall_confidence * 100).toFixed(0) + '%' : '';

    strategicSection = `
      <div class="section">
        <h2>Strategic Foresight${confPct ? ` <span class="badge">${confPct} confidence</span>` : ''}</h2>
        <p>${escPdf(sf.strategic_assessment)}</p>
        ${iaHtml ? `<h3>Immediate Actions</h3><ul>${iaHtml}</ul>` : ''}
        ${csHtml ? `<h3>Contingency Summaries</h3><ul>${csHtml}</ul>` : ''}
        ${dpHtml ? `<h3>Key Decision Points</h3><ul>${dpHtml}</ul>` : ''}
        ${rmHtml ? `<h3>Risk / Opportunity Matrix</h3><ul>${rmHtml}</ul>` : ''}
        ${sf.historical_warning ? `<div class="warning-box"><strong>β  Historical Warning:</strong> ${escPdf(sf.historical_warning)}</div>` : ''}
      </div>`;
  }

  // β”€β”€ Action Playbooks β”€β”€
  let actionsSection = '';
  const sa = d.scenario_actions;
  if (sa) {
    let robustHtml = '';
    for (const rm of (sa.robust_moves || []).slice(0, 6)) {
      robustHtml += `<li><strong>${escPdf(rm.action)}</strong> <em>(${escPdf(rm.urgency || '')})</em>${rm.reasoning ? ` β€” ${escPdf(rm.reasoning)}` : ''}</li>`;
    }
    let pbHtml = '';
    for (const pb of (sa.scenario_playbooks || []).slice(0, 6)) {
      let aHtml = '';
      for (const a of (pb.actions || []).slice(0, 5)) {
        aHtml += `<li>${escPdf(a.action)}${a.deadline ? ` <em>(${escPdf(a.deadline)})</em>` : ''}</li>`;
      }
      const prob = typeof pb.scenario_probability === 'number' ? (pb.scenario_probability * 100).toFixed(0) + '%' : '';
      pbHtml += `<div class="playbook"><h4>${escPdf(pb.scenario_name)}${prob ? ` β€” ${prob}` : ''}</h4><ol>${aHtml}</ol></div>`;
    }
    actionsSection = `
      <div class="section">
        <h2>Action Playbooks${sa.client_role ? ` <span class="badge">for: ${escPdf(sa.client_role)}</span>` : ''}</h2>
        ${robustHtml ? `<h3>Do Regardless (Robust Moves)</h3><ul>${robustHtml}</ul>` : ''}
        ${pbHtml ? `<h3>Scenario-Specific Playbooks</h3>${pbHtml}` : ''}
      </div>`;
  }

  // β”€β”€ Historical Resonance β”€β”€
  let historicalSection = '';
  const hr = d.historical_resonance;
  if (hr && hr.parallels_found) {
    const v = (typeof hr.verdict === 'object' && hr.verdict) ? hr.verdict : {};
    historicalSection = `
      <div class="section">
        <h2>Historical Resonance β€” ${hr.parallels_found} parallels${v.strongest_parallel ? ` (strongest: ${escPdf(v.strongest_parallel)})` : ''}</h2>
        ${v.historical_consensus ? `<p>${escPdf(v.historical_consensus)}</p>` : ''}
        ${v.historical_warning ? `<div class="warning-box"><strong>β  Warning:</strong> ${escPdf(v.historical_warning)}</div>` : ''}
      </div>`;
  }

  // β”€β”€ Decision Triggers + Bets β”€β”€
  let triggersSection = '';
  const dt = d.decision_triggers;
  if (dt) {
    const triggers = Array.isArray(dt.decision_triggers) ? dt.decision_triggers : [];
    const bets = Array.isArray(dt.bets) ? dt.bets : [];
    let trigHtml = '';
    for (const t of triggers.slice(0, 6)) {
      const conds = Array.isArray(t.conditions) ? t.conditions.map(c => escPdf(c.signal || '?')).join(' + ') : '';
      trigHtml += `<tr><td><strong>IF</strong> ${conds}</td><td>${escPdf(t.activates_scenario || '')}</td><td>${escPdf(t.activates_playbook || '')}</td><td>${escPdf(t.time_to_act || '')}</td></tr>`;
    }
    let betHtml = '';
    for (const b of bets.slice(0, 6)) {
      const conf = typeof b.confidence === 'number' ? (b.confidence * 100).toFixed(0) + '%' : '';
      betHtml += `<tr><td>${escPdf(b.statement || '')}</td><td>${escPdf(b.deadline || '')}</td><td>${conf}</td><td>${escPdf(b.novelty || '')}</td></tr>`;
    }
    triggersSection = `
      <div class="section">
        <h2>Decision Triggers & Prophetic Bets</h2>
        ${trigHtml ? `<h3>Decision Triggers β€” ${triggers.length} rules</h3>
          <table><thead><tr><th>Condition</th><th>Scenario</th><th>Playbook</th><th>Time to Act</th></tr></thead><tbody>${trigHtml}</tbody></table>` : ''}
        ${betHtml ? `<h3>Prophetic Bets β€” ${bets.length} predictions</h3>
          <table><thead><tr><th>Prediction</th><th>Deadline</th><th>Confidence</th><th>Novelty</th></tr></thead><tbody>${betHtml}</tbody></table>` : ''}
        ${dt.meta_prediction ? `<div class="meta-prediction"><strong>META-PREDICTION:</strong> ${escPdf(dt.meta_prediction)}</div>` : ''}
      </div>`;
  }

  // β”€β”€ Build full HTML document β”€β”€
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>XDART-Ξ¦ Intelligence Briefing</title>
<style>
  @page { margin: 20mm 18mm; size: A4; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; color: #1a1a2e; line-height: 1.6; font-size: 11pt; }
  .header { text-align: center; border-bottom: 2px solid #d4a843; padding-bottom: 16px; margin-bottom: 24px; }
  .header h1 { font-size: 22pt; color: #1a1a2e; letter-spacing: 1px; margin-bottom: 4px; }
  .header .subtitle { font-size: 10pt; color: #666; }
  .header .meta { font-size: 9pt; color: #888; margin-top: 6px; }
  .executive-summary { background: #f8f6f0; border-left: 4px solid #d4a843; padding: 16px 20px; margin-bottom: 24px; border-radius: 0 6px 6px 0; }
  .executive-summary h2 { font-size: 13pt; color: #d4a843; margin-bottom: 8px; }
  .executive-summary p { font-size: 11pt; line-height: 1.7; }
  .section { margin-bottom: 22px; page-break-inside: avoid; }
  .section h2 { font-size: 13pt; color: #1a1a2e; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-bottom: 10px; }
  .section h3 { font-size: 11pt; color: #444; margin: 10px 0 6px; }
  .section h4 { font-size: 10pt; color: #555; margin: 8px 0 4px; }
  .section p { font-size: 10.5pt; line-height: 1.6; margin-bottom: 8px; }
  .section ul, .section ol { padding-left: 20px; font-size: 10.5pt; margin-bottom: 8px; }
  .section li { margin-bottom: 4px; }
  .badge { display: inline-block; background: #f0e6cc; color: #8b6914; font-size: 9pt; padding: 1px 8px; border-radius: 10px; font-weight: 600; vertical-align: middle; }
  .warning-box { background: #fff8e1; border-left: 3px solid #ff9800; padding: 10px 14px; margin: 10px 0; border-radius: 0 4px 4px 0; font-size: 10pt; }
  .meta-prediction { background: #fffde7; border: 1px solid #ffd740; padding: 10px 14px; margin: 10px 0; border-radius: 4px; font-size: 10.5pt; }
  .playbook { margin: 8px 0; padding: 8px 12px; background: #f9f9f9; border-radius: 4px; border-left: 3px solid #4caf50; }
  table { width: 100%; border-collapse: collapse; font-size: 10pt; margin: 6px 0; }
  th { background: #f0f0f0; text-align: left; padding: 6px 8px; border-bottom: 2px solid #ddd; font-weight: 700; }
  td { padding: 6px 8px; border-bottom: 1px solid #eee; vertical-align: top; }
  .footer { margin-top: 30px; padding-top: 12px; border-top: 1px solid #ddd; text-align: center; font-size: 8pt; color: #999; }
  .layer-tag { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 9pt; font-weight: 700; }
  .layer-tag.l3 { background: #e8d5f5; color: #7b1fa2; }
  .layer-tag.l2 { background: #dcedc8; color: #388e3c; }
  .layer-tag.l1 { background: #e3f2fd; color: #1565c0; }
  .falsifiability { background: #fafafa; border: 1px solid #e0e0e0; padding: 10px 14px; margin: 10px 0; border-radius: 4px; font-size: 10pt; font-style: italic; color: #555; }
  @media print { body { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }
</style>
</head>
<body>
  <div class="header">
    <h1>XDART-Ξ¦ Γ— XHEART</h1>
    <div class="subtitle">Strategic Intelligence Briefing</div>
    <div class="meta">${escPdf(now)} Β· <span class="layer-tag ${d.layer === 'Layer-3' ? 'l3' : d.layer === 'Layer-2' ? 'l2' : 'l1'}">${escPdf(d.layer)}</span> Β· ${escPdf(String(d.total_elapsed))}s Β· ${(d.domains_used||[]).length} domains Β· ${(d.views_used||[]).length} views Β· ${d.memory_count} memories</div>
  </div>

  <div class="executive-summary">
    <h2>Executive Summary</h2>
    <p><strong>Problem:</strong> ${escPdf(d.problem)}</p>
    <p><strong>Reframed:</strong> ${escPdf(d.reframed_problem)}</p>
  </div>

  ${d.executive_brief ? `
  <div class="section" style="background:#fffde7;border:2px solid #d4a843;padding:16px 20px;border-radius:8px;margin-bottom:24px">
    <h2 style="color:#d4a843;border-bottom:none">Executive Intelligence Brief</h2>
    <div style="background:#f8f6f0;border-left:4px solid #d4a843;padding:12px 16px;margin-bottom:16px;border-radius:0 6px 6px 0">
      <strong>BOTTOM LINE:</strong> ${escPdf(d.executive_brief.bottom_line)}
    </div>
    <h3>Situation</h3><p>${escPdf(d.executive_brief.situation)}</p>
    ${(d.executive_brief.key_judgments || []).length ? `<h3>Key Judgments</h3><ol>${d.executive_brief.key_judgments.map(j => '<li>' + escPdf(j) + '</li>').join('')}</ol>` : ''}
    ${d.executive_brief.scenarios_ranked ? `<h3>Scenario Outlook</h3><p>${escPdf(d.executive_brief.scenarios_ranked)}</p>` : ''}
    ${(d.executive_brief.recommended_actions || []).length ? `<h3>Recommended Actions</h3><ol>${d.executive_brief.recommended_actions.map(a => '<li>' + escPdf(a) + '</li>').join('')}</ol>` : ''}
    ${d.executive_brief.critical_timeline ? `<h3>Critical Timeline</h3><p>${escPdf(d.executive_brief.critical_timeline)}</p>` : ''}
    ${d.executive_brief.risks_and_contingencies ? `<h3>Risks & Contingencies</h3><p>${escPdf(d.executive_brief.risks_and_contingencies)}</p>` : ''}
    ${d.executive_brief.confidence_statement ? `<p style="font-size:9.5pt;color:#777;font-style:italic;margin-top:10px">${escPdf(d.executive_brief.confidence_statement)}</p>` : ''}
  </div>
  ` : ''}
  </div>

  <div class="section">
    <h2>Core Analysis</h2>
    <p>${escPdf(d.final_output)}</p>
    <div class="falsifiability"><strong>Falsifiability:</strong> ${escPdf(d.falsifiability)}</div>
    ${(d.convergent_patterns || []).length ? `<h3>Convergent Patterns</h3><ul>${(d.convergent_patterns||[]).map(p => '<li>' + escPdf(p) + '</li>').join('')}</ul>` : ''}
  </div>

  ${actionsSection}
  ${strategicSection}
  ${historicalSection}
  ${triggersSection}

  <div class="footer">
    XDART-Ξ¦ Γ— XHEART β€” Autonomous Strategic Intelligence Framework Β· Generated ${escPdf(now)}
  </div>
</body>
</html>`;

  // Open in new window for print-to-PDF
  const win = window.open('', '_blank', 'width=900,height=700');
  if (!win) { alert('Please allow popups to download the PDF report.'); return; }
  win.document.write(html);
  win.document.close();
  // Give the browser a moment to render, then trigger print
  setTimeout(() => win.print(), 400);
}

// β”€β”€ FULL INTELLIGENCE DOSSIER (all phases) β”€β”€
function generateDossierPDF() {
  const d = _lastAnalysisData;
  if (!d) { alert('No analysis data available.'); return; }

  const escPdf = (s) => {
    if (!s) return '';
    const el = document.createElement('div');
    el.textContent = String(s);
    return el.innerHTML;
  };
  const now = new Date().toLocaleString('en-GB', { dateStyle: 'long', timeStyle: 'short' });

  // β”€β”€ Β§0: Executive Brief β”€β”€
  let briefSection = '';
  const eb = d.executive_brief;
  if (eb) {
    let judgmentsHtml = '';
    for (const j of (eb.key_judgments || [])) {
      judgmentsHtml += `<li>${escPdf(j)}</li>`;
    }
    let actionsHtml = '';
    for (const a of (eb.recommended_actions || [])) {
      actionsHtml += `<li>${escPdf(a)}</li>`;
    }
    briefSection = `
      <div class="section executive-brief-box">
        <h2>Β§0 β€” Executive Intelligence Brief</h2>
        <div class="bottom-line"><strong>BOTTOM LINE:</strong> ${escPdf(eb.bottom_line)}</div>
        <h3>Situation</h3><p>${escPdf(eb.situation)}</p>
        ${judgmentsHtml ? `<h3>Key Judgments</h3><ol>${judgmentsHtml}</ol>` : ''}
        ${escPdf(eb.scenarios_ranked) ? `<h3>Scenario Outlook</h3><p>${escPdf(eb.scenarios_ranked)}</p>` : ''}
        ${actionsHtml ? `<h3>Recommended Actions</h3><ol>${actionsHtml}</ol>` : ''}
        ${eb.critical_timeline ? `<h3>Critical Timeline</h3><p>${escPdf(eb.critical_timeline)}</p>` : ''}
        ${eb.risks_and_contingencies ? `<h3>Risks & Contingencies</h3><p>${escPdf(eb.risks_and_contingencies)}</p>` : ''}
        ${eb.confidence_statement ? `<p class="confidence-stmt">${escPdf(eb.confidence_statement)}</p>` : ''}
      </div>
      <div style="page-break-after: always;"></div>`;
  }

  // β”€β”€ Β§1: Problem Reframing β”€β”€
  let ontologySection = '';
  const ont = d.dossier_ontology;
  if (ont) {
    ontologySection = `
      <div class="section">
        <h2>Β§1 β€” Problem Reframing</h2>
        <p><strong>Original Problem:</strong> ${escPdf(ont.original_problem)}</p>
        <p><strong>Reframed:</strong> ${escPdf(ont.reframed_problem)}</p>
        <h3>Ontological Nature</h3><p>${escPdf(ont.ontological_nature)}</p>
        <h3>Causal Analysis</h3><p>${escPdf(ont.causal_analysis)}</p>
        <h3>Teleological Purpose</h3><p>${escPdf(ont.teleological_purpose)}</p>
        <h3>Epistemological Check</h3><p>${escPdf(ont.epistemological_check)}</p>
      </div>`;
  }

  // β”€β”€ Β§2: Analytical Landscape β”€β”€
  let landscapeSection = '';
  const cd = d.dossier_cross_domain;
  const vw = d.dossier_views;
  if (cd || vw) {
    let domainsHtml = '';
    if (cd && cd.domains) {
      for (const dom of cd.domains.slice(0, 10)) {
        domainsHtml += `<tr><td><strong>${escPdf(dom.domain)}</strong></td><td>${escPdf(dom.core_mechanism)}</td><td>${escPdf(dom.transfer_hypothesis)}</td><td>${escPdf(dom.analogy_strength || '')}</td></tr>`;
      }
    }
    let viewsHtml = '';
    if (vw && vw.views) {
      for (const v of vw.views) {
        viewsHtml += `<tr><td><strong>${escPdf(v.view_name)}</strong></td><td>${escPdf(v.insight)}</td></tr>`;
      }
    }
    landscapeSection = `
      <div class="section">
        <h2>Β§2 β€” Analytical Landscape</h2>
        ${cd ? `
        <h3>Cross-Domain Analysis β€” ${(cd.domains || []).length} domains (${escPdf(cd.layer)})</h3>
        <p><strong>Structural Formula:</strong> ${escPdf(cd.structural_formula)}</p>
        <p><strong>Strongest Analogy:</strong> <em>${escPdf((cd.strongest_analogy || {}).domain)}</em> β€” ${escPdf((cd.strongest_analogy || {}).core_mechanism)}</p>
        ${cd.layer_3_hypothesis ? `<p><strong>Layer-3 Hypothesis:</strong> ${escPdf(cd.layer_3_hypothesis)}</p>` : ''}
        ${domainsHtml ? `<table class="domain-table"><thead><tr><th>Domain</th><th>Mechanism</th><th>Transfer Hypothesis</th><th>Strength</th></tr></thead><tbody>${domainsHtml}</tbody></table>` : ''}
        ` : ''}
        ${vw ? `
        <h3>Multi-View Analysis β€” ${(vw.views || []).length} analytical lenses</h3>
        <p><strong>Dominant Pattern:</strong> ${escPdf(vw.dominant_pattern)}</p>
        ${(vw.convergent_patterns || []).length ? `<h4>Convergent Patterns</h4><ul>${(vw.convergent_patterns || []).map(p => '<li>' + escPdf(p) + '</li>').join('')}</ul>` : ''}
        ${(vw.divergent_insights || []).length ? `<h4>Divergent Signals</h4><ul>${(vw.divergent_insights || []).map(p => '<li>' + escPdf(p) + '</li>').join('')}</ul>` : ''}
        ${viewsHtml ? `<table><thead><tr><th>View</th><th>Insight</th></tr></thead><tbody>${viewsHtml}</tbody></table>` : ''}
        ` : ''}
      </div>
      <div style="page-break-after: always;"></div>`;
  }

  // β”€β”€ Β§3: Scenario Architecture β”€β”€
  let scenarioSection = '';
  const sc = d.dossier_scenarios;
  const sim = d.dossier_simulations;
  const trib = d.dossier_tribunal;
  if (sc || trib) {
    // Scenario overview table
    let scenarioTableHtml = '';
    if (trib && trib.verdicts) {
      const sorted = [...trib.verdicts].sort((a, b) => b.final_score - a.final_score);
      for (const v of sorted) {
        const isDominant = v.scenario_name === trib.dominant_scenario;
        scenarioTableHtml += `<tr${isDominant ? ' style="background:#f8f6f0;font-weight:700"' : ''}>
          <td>${escPdf(v.scenario_name)}${isDominant ? ' β…' : ''}</td>
          <td>${v.final_score.toFixed(2)}</td>
          <td>${v.evidence_strength.toFixed(2)}</td>
          <td>${v.internal_consistency.toFixed(2)}</td>
          <td>${v.feasibility_rank}</td>
        </tr>`;
      }
    }

    // Per-scenario details
    let scenarioDetailsHtml = '';
    if (sc && sc.scenarios) {
      for (const s of sc.scenarios) {
        const simData = sim ? (sim.simulations || []).find(x => x.scenario_name === s.name) : null;
        const tribVerdict = trib ? (trib.verdicts || []).find(x => x.scenario_name === s.name) : null;
        let bpHtml = '';
        if (simData && simData.breakpoints) {
          for (const bp of simData.breakpoints) {
            const sevColor = bp.severity === 'FATAL' ? '#c0392b' : bp.severity === 'DEGRADING' ? '#e67e22' : '#7f8c8d';
            bpHtml += `<li><span style="color:${sevColor};font-weight:700">${escPdf(bp.severity)}</span> at ${escPdf(bp.at_step)}: ${escPdf(bp.reason)}</li>`;
          }
        }
        scenarioDetailsHtml += `
          <div class="scenario-detail">
            <h4>${escPdf(s.name)} ${typeof s.confidence === 'number' ? `<span class="badge">${(s.confidence * 100).toFixed(0)}% confidence</span>` : ''} ${tribVerdict ? `<span class="badge">score: ${tribVerdict.final_score.toFixed(2)}</span>` : ''}</h4>
            <p><strong>Timeline:</strong> ${escPdf(s.timeline)}</p>
            <p>${escPdf(s.narrative)}</p>
            <p><strong>Predicted Outcome:</strong> ${escPdf(s.predicted_outcome)}</p>
            <p class="falsifiability-inline"><strong>Falsifiability:</strong> ${escPdf(s.falsifiability)}</p>
            ${simData ? `
              <div class="sim-box">
                <h4>Forward Projection</h4>
                <p>${escPdf(simData.forward_projection)}</p>
                ${simData.stress_test_results && simData.stress_test_results.length ? `<h4>Stress Test Results</h4><ul>${simData.stress_test_results.map(st => '<li>' + escPdf(st) + '</li>').join('')}</ul>` : ''}
                ${bpHtml ? `<h4>Breakpoints</h4><ul>${bpHtml}</ul>` : ''}
                <p><strong>Robustness:</strong> ${(simData.robustness_score * 100).toFixed(0)}% Β· <strong>Revised Confidence:</strong> ${(simData.revised_confidence * 100).toFixed(0)}%</p>
                <p><em>${escPdf(simData.simulation_insight)}</em></p>
              </div>` : ''}
          </div>`;
      }
    }

    scenarioSection = `
      <div class="section">
        <h2>Β§3 β€” Scenario Architecture</h2>
        ${sc ? `<p><strong>Generation Logic:</strong> ${escPdf(sc.generation_logic)}</p>` : ''}
        ${scenarioTableHtml ? `
          <h3>Tribunal Scoring Matrix</h3>
          <table><thead><tr><th>Scenario</th><th>Final</th><th>Evidence</th><th>Consistency</th><th>Feasibility Rank</th></tr></thead><tbody>${scenarioTableHtml}</tbody></table>
          ${trib && trib.tribunal_synthesis ? `<p><strong>Tribunal Synthesis:</strong> ${escPdf(trib.tribunal_synthesis)}</p>` : ''}
          ${trib && trib.convergence_points && trib.convergence_points.length ? `<h4>Points of Convergence</h4><ul>${trib.convergence_points.map(p => '<li>' + escPdf(p) + '</li>').join('')}</ul>` : ''}
          ${trib && trib.divergence_points && trib.divergence_points.length ? `<h4>Points of Divergence</h4><ul>${trib.divergence_points.map(p => '<li>' + escPdf(p) + '</li>').join('')}</ul>` : ''}
        ` : ''}
        ${sim ? `<p><strong>Simulation Summary:</strong> ${escPdf(sim.simulation_summary)}</p>` : ''}
        ${scenarioDetailsHtml ? `<h3>Detailed Scenario Analysis</h3>${scenarioDetailsHtml}` : ''}
      </div>
      <div style="page-break-after: always;"></div>`;
  }

  // β”€β”€ Β§4: Strategic Foresight (existing) β”€β”€
  let strategicSection = '';
  const sf = d.strategic_foresight;
  if (sf && sf.strategic_assessment) {
    let dpHtml = '';
    for (const dp of (sf.decision_points || []).slice(0, 8)) {
      const txt = typeof dp === 'object' ? (dp.decision || dp.description || JSON.stringify(dp)) : String(dp);
      const dl = typeof dp === 'object' && dp.deadline_description ? ` β€” <em>${escPdf(dp.deadline_description)}</em>` : '';
      dpHtml += `<li>${escPdf(txt)}${dl}</li>`;
    }
    let iaHtml = '';
    for (const a of (sf.immediate_actions || []).slice(0, 8)) {
      const txt = typeof a === 'object' ? (a.action || a.description || JSON.stringify(a)) : String(a);
      iaHtml += `<li>${escPdf(txt)}</li>`;
    }
    let csHtml = '';
    for (const c of (sf.contingency_summaries || []).slice(0, 8)) {
      const scenario = typeof c === 'object' ? (c.scenario || c.scenario_name || '') : '';
      const summary = typeof c === 'object' ? (c.summary || c.action || JSON.stringify(c)) : String(c);
      csHtml += `<li>${scenario ? `<strong>${escPdf(scenario)}:</strong> ` : ''}${escPdf(summary)}</li>`;
    }
    const rm = (sf.risk_opportunity_matrix && typeof sf.risk_opportunity_matrix === 'object') ? sf.risk_opportunity_matrix : {};
    const risks = Array.isArray(rm.risks) ? rm.risks : [];
    const opps = Array.isArray(rm.opportunities) ? rm.opportunities : [];
    let rmHtml = '';
    for (const r of risks.slice(0, 6)) {
      const label = typeof r === 'object' ? (r.item || r.risk || JSON.stringify(r)) : String(r);
      rmHtml += `<li style="color:#c0392b">β  ${escPdf(label)}</li>`;
    }
    for (const o of opps.slice(0, 4)) {
      const label = typeof o === 'object' ? (o.item || o.opportunity || JSON.stringify(o)) : String(o);
      rmHtml += `<li style="color:#27ae60">β¦ ${escPdf(label)}</li>`;
    }
    const confCal = (sf.confidence_calibration && typeof sf.confidence_calibration === 'object') ? sf.confidence_calibration : {};
    const confPct = typeof confCal.overall_confidence === 'number' ? (confCal.overall_confidence * 100).toFixed(0) + '%' : '';
    strategicSection = `
      <div class="section">
        <h2>Β§4 β€” Strategic Foresight${confPct ? ` <span class="badge">${confPct} confidence</span>` : ''}</h2>
        <p>${escPdf(sf.strategic_assessment)}</p>
        ${iaHtml ? `<h3>Immediate Actions</h3><ul>${iaHtml}</ul>` : ''}
        ${csHtml ? `<h3>Contingency Summaries</h3><ul>${csHtml}</ul>` : ''}
        ${dpHtml ? `<h3>Key Decision Points</h3><ul>${dpHtml}</ul>` : ''}
        ${rmHtml ? `<h3>Risk / Opportunity Matrix</h3><ul>${rmHtml}</ul>` : ''}
        ${sf.historical_warning ? `<div class="warning-box"><strong>β  Historical Warning:</strong> ${escPdf(sf.historical_warning)}</div>` : ''}
      </div>`;
  }

  // β”€β”€ Β§5: Action Playbook β”€β”€
  let actionsSection = '';
  const sa = d.scenario_actions;
  if (sa) {
    let robustHtml = '';
    for (const rm of (sa.robust_moves || []).slice(0, 6)) {
      robustHtml += `<li><strong>${escPdf(rm.action)}</strong> <em>(${escPdf(rm.urgency || '')})</em>${rm.reasoning ? ` β€” ${escPdf(rm.reasoning)}` : ''}</li>`;
    }
    let pbHtml = '';
    for (const pb of (sa.scenario_playbooks || []).slice(0, 6)) {
      let aHtml = '';
      for (const a of (pb.actions || []).slice(0, 5)) {
        aHtml += `<li>${escPdf(a.action)}${a.deadline ? ` <em>(${escPdf(a.deadline)})</em>` : ''}</li>`;
      }
      const prob = typeof pb.scenario_probability === 'number' ? (pb.scenario_probability * 100).toFixed(0) + '%' : '';
      pbHtml += `<div class="playbook"><h4>${escPdf(pb.scenario_name)}${prob ? ` β€” ${prob}` : ''}</h4><ol>${aHtml}</ol></div>`;
    }
    actionsSection = `
      <div class="section">
        <h2>Β§5 β€” Action Playbook${sa.client_role ? ` <span class="badge">for: ${escPdf(sa.client_role)}</span>` : ''}</h2>
        ${robustHtml ? `<h3>Do Regardless (Robust Moves)</h3><ul>${robustHtml}</ul>` : ''}
        ${pbHtml ? `<h3>Scenario-Specific Playbooks</h3>${pbHtml}` : ''}
      </div>`;
  }

  // β”€β”€ Β§6: Historical Precedent β”€β”€
  let historicalSection = '';
  const hr = d.historical_resonance;
  if (hr && hr.parallels_found) {
    const v = (typeof hr.verdict === 'object' && hr.verdict) ? hr.verdict : {};
    let parallelsHtml = '';
    for (const pa of (hr.parallel_analyses || []).slice(0, 4)) {
      parallelsHtml += `
        <div class="parallel-box">
          <h4>${escPdf(pa.event_name)} (${escPdf(pa.event_period)}) ${typeof pa.structural_match_score === 'number' ? `<span class="badge">${(pa.structural_match_score * 100).toFixed(0)}% match</span>` : ''}</h4>
          ${(pa.transfer_insights || []).length ? `<p><strong>Insights:</strong> ${pa.transfer_insights.map(i => escPdf(i)).join('; ')}</p>` : ''}
          ${(pa.transfer_warnings || []).length ? `<p style="color:#c0392b"><strong>Warnings:</strong> ${pa.transfer_warnings.map(w => escPdf(w)).join('; ')}</p>` : ''}
        </div>`;
    }
    historicalSection = `
      <div class="section">
        <h2>Β§6 β€” Historical Precedent β€” ${hr.parallels_found} parallels${v.strongest_parallel ? ` (strongest: ${escPdf(v.strongest_parallel)})` : ''}</h2>
        ${v.historical_consensus ? `<p>${escPdf(v.historical_consensus)}</p>` : ''}
        ${parallelsHtml}
        ${v.pattern_beneath ? `<p><strong>Pattern Beneath:</strong> ${escPdf(v.pattern_beneath)}</p>` : ''}
        ${v.historical_warning ? `<div class="warning-box"><strong>β  Warning:</strong> ${escPdf(v.historical_warning)}</div>` : ''}
        ${(v.early_warning_signals || []).length ? `<h3>Early Warning Signals</h3><ul>${v.early_warning_signals.map(s => '<li>' + escPdf(s) + '</li>').join('')}</ul>` : ''}
      </div>`;
  }

  // β”€β”€ Β§7: Intelligence Signals β”€β”€
  let triggersSection = '';
  const dt = d.decision_triggers;
  if (dt) {
    const triggers = Array.isArray(dt.decision_triggers) ? dt.decision_triggers : [];
    const bets = Array.isArray(dt.bets) ? dt.bets : [];
    let trigHtml = '';
    for (const t of triggers.slice(0, 6)) {
      const conds = Array.isArray(t.conditions) ? t.conditions.map(c => escPdf(c.signal || '?')).join(' + ') : '';
      trigHtml += `<tr><td><strong>IF</strong> ${conds}</td><td>${escPdf(t.activates_scenario || '')}</td><td>${escPdf(t.activates_playbook || '')}</td><td>${escPdf(t.time_to_act || '')}</td></tr>`;
    }
    let betHtml = '';
    for (const b of bets.slice(0, 6)) {
      const conf = typeof b.confidence === 'number' ? (b.confidence * 100).toFixed(0) + '%' : '';
      betHtml += `<tr><td>${escPdf(b.statement || '')}</td><td>${escPdf(b.deadline || '')}</td><td>${conf}</td><td>${escPdf(b.novelty || '')}</td></tr>`;
    }
    triggersSection = `
      <div class="section">
        <h2>Β§7 β€” Intelligence Signals & Predictions</h2>
        ${trigHtml ? `<h3>Decision Triggers β€” ${triggers.length} rules</h3>
          <table><thead><tr><th>Condition</th><th>Scenario</th><th>Playbook</th><th>Time to Act</th></tr></thead><tbody>${trigHtml}</tbody></table>` : ''}
        ${betHtml ? `<h3>Prophetic Bets β€” ${bets.length} predictions</h3>
          <table><thead><tr><th>Prediction</th><th>Deadline</th><th>Confidence</th><th>Novelty</th></tr></thead><tbody>${betHtml}</tbody></table>` : ''}
        ${dt.meta_prediction ? `<div class="meta-prediction"><strong>META-PREDICTION:</strong> ${escPdf(dt.meta_prediction)}</div>` : ''}
      </div>`;
  }

  // β”€β”€ Β§8: Methodology & Confidence β”€β”€
  let methodSection = '';
  const confCalib = sf ? sf.confidence_calibration : null;
  methodSection = `
    <div class="section">
      <h2>Β§8 β€” Methodology & Confidence</h2>
      <table>
        <tbody>
          <tr><td><strong>Analytical Layer</strong></td><td>${escPdf(d.layer)}</td></tr>
          <tr><td><strong>Domains Analyzed</strong></td><td>${(d.domains_used || []).join(', ')}</td></tr>
          <tr><td><strong>Views Applied</strong></td><td>${(d.views_used || []).length} analytical lenses</td></tr>
          <tr><td><strong>Scenarios Generated</strong></td><td>${sc ? sc.scenarios.length : '?'}</td></tr>
          <tr><td><strong>Historical Parallels</strong></td><td>${hr ? hr.parallels_found : 0}</td></tr>
          <tr><td><strong>Memory Banks Consulted</strong></td><td>${d.memory_count || 0}</td></tr>
          <tr><td><strong>Concepts Active</strong></td><td>${d.concept_count || 0}</td></tr>
          <tr><td><strong>Pipeline Duration</strong></td><td>${d.total_elapsed}s</td></tr>
        </tbody>
      </table>
      <h3>Falsifiability Criteria</h3>
      <div class="falsifiability"><strong>What would disprove this assessment:</strong> ${escPdf(d.falsifiability)}</div>
      ${confCalib ? `
      <h3>Confidence Calibration</h3>
      <p>Overall confidence: ${typeof confCalib.overall_confidence === 'number' ? (confCalib.overall_confidence * 100).toFixed(0) + '%' : '?'}</p>
      ${confCalib.confidence_reasoning ? `<p>${escPdf(confCalib.confidence_reasoning)}</p>` : ''}
      ${confCalib.what_could_prove_me_wrong ? `<p><strong>What could prove me wrong:</strong> ${escPdf(confCalib.what_could_prove_me_wrong)}</p>` : ''}
      ${confCalib.biggest_blind_spot ? `<p><strong>Biggest blind spot:</strong> ${escPdf(confCalib.biggest_blind_spot)}</p>` : ''}
      ${confCalib.time_sensitivity ? `<p><strong>Time sensitivity:</strong> ${escPdf(confCalib.time_sensitivity)}</p>` : ''}
      ` : ''}
    </div>`;

  // β”€β”€ Build full dossier HTML β”€β”€
  const dossierHtml = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>XDART-Ξ¦ Intelligence Dossier</title>
<style>
  @page { margin: 18mm 16mm; size: A4; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; color: #1a1a2e; line-height: 1.6; font-size: 10.5pt; }
  .cover { text-align: center; padding: 60px 40px; border-bottom: 3px solid #d4a843; margin-bottom: 30px; page-break-after: always; }
  .cover h1 { font-size: 28pt; color: #1a1a2e; letter-spacing: 2px; margin-bottom: 8px; }
  .cover .subtitle { font-size: 14pt; color: #d4a843; font-weight: 300; margin-bottom: 20px; }
  .cover .classification { font-size: 12pt; color: #666; border: 1px solid #ddd; display: inline-block; padding: 4px 20px; border-radius: 4px; margin-bottom: 16px; }
  .cover .meta { font-size: 9pt; color: #999; margin-top: 12px; }
  .cover .problem-box { text-align: left; background: #f8f6f0; padding: 16px 24px; border-radius: 8px; margin-top: 30px; border-left: 4px solid #d4a843; }
  .cover .problem-box h3 { color: #d4a843; margin-bottom: 6px; font-size: 10pt; }
  .cover .problem-box p { font-size: 11pt; line-height: 1.7; }
  .toc { margin-bottom: 30px; page-break-after: always; }
  .toc h2 { font-size: 16pt; border-bottom: 2px solid #d4a843; padding-bottom: 6px; margin-bottom: 14px; }
  .toc li { font-size: 11pt; margin-bottom: 4px; color: #333; }
  .section { margin-bottom: 24px; page-break-inside: avoid; }
  .section h2 { font-size: 14pt; color: #1a1a2e; border-bottom: 2px solid #d4a843; padding-bottom: 4px; margin-bottom: 12px; }
  .section h3 { font-size: 11pt; color: #444; margin: 12px 0 6px; }
  .section h4 { font-size: 10pt; color: #555; margin: 10px 0 4px; }
  .section p { font-size: 10.5pt; line-height: 1.65; margin-bottom: 8px; }
  .section ul, .section ol { padding-left: 20px; font-size: 10.5pt; margin-bottom: 8px; }
  .section li { margin-bottom: 4px; }
  .executive-brief-box { background: #fffde7; border: 2px solid #d4a843; padding: 20px 24px; border-radius: 8px; }
  .bottom-line { background: #f8f6f0; border-left: 4px solid #d4a843; padding: 12px 16px; margin-bottom: 16px; font-size: 11pt; line-height: 1.7; border-radius: 0 6px 6px 0; }
  .badge { display: inline-block; background: #f0e6cc; color: #8b6914; font-size: 8.5pt; padding: 1px 8px; border-radius: 10px; font-weight: 600; vertical-align: middle; }
  .warning-box { background: #fff8e1; border-left: 3px solid #ff9800; padding: 10px 14px; margin: 10px 0; border-radius: 0 4px 4px 0; font-size: 10pt; }
  .meta-prediction { background: #fffde7; border: 1px solid #ffd740; padding: 10px 14px; margin: 10px 0; border-radius: 4px; font-size: 10.5pt; }
  .playbook { margin: 8px 0; padding: 8px 12px; background: #f9f9f9; border-radius: 4px; border-left: 3px solid #4caf50; }
  .scenario-detail { margin: 12px 0; padding: 12px 16px; background: #fafafa; border-radius: 6px; border: 1px solid #e8e8e8; page-break-inside: avoid; }
  .sim-box { margin-top: 8px; padding: 10px; background: #f5f0ff; border-left: 3px solid #7b1fa2; border-radius: 0 4px 4px 0; }
  .parallel-box { margin: 8px 0; padding: 10px 14px; background: #fff8f0; border-left: 3px solid #ff9800; border-radius: 0 4px 4px 0; }
  .falsifiability-inline { font-style: italic; color: #666; }
  .confidence-stmt { font-size: 9.5pt; color: #777; font-style: italic; margin-top: 10px; }
  .domain-table td:first-child { white-space: nowrap; }
  table { width: 100%; border-collapse: collapse; font-size: 9.5pt; margin: 6px 0; }
  th { background: #f0f0f0; text-align: left; padding: 5px 8px; border-bottom: 2px solid #ddd; font-weight: 700; }
  td { padding: 5px 8px; border-bottom: 1px solid #eee; vertical-align: top; }
  .footer { margin-top: 30px; padding-top: 12px; border-top: 1px solid #ddd; text-align: center; font-size: 8pt; color: #999; }
  .layer-tag { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 9pt; font-weight: 700; }
  .layer-tag.l3 { background: #e8d5f5; color: #7b1fa2; }
  .layer-tag.l2 { background: #dcedc8; color: #388e3c; }
  .layer-tag.l1 { background: #e3f2fd; color: #1565c0; }
  .falsifiability { background: #fafafa; border: 1px solid #e0e0e0; padding: 10px 14px; margin: 10px 0; border-radius: 4px; font-size: 10pt; font-style: italic; color: #555; }
  @media print { body { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }
</style>
</head>
<body>
  <div class="cover">
    <h1>XDART-Ξ¦</h1>
    <div class="subtitle">Intelligence Dossier</div>
    <div class="classification"><span class="layer-tag ${d.layer === 'Layer-3' ? 'l3' : d.layer === 'Layer-2' ? 'l2' : 'l1'}">${escPdf(d.layer)}</span></div>
    <div class="meta">${escPdf(now)} Β· ${(d.domains_used||[]).length} domains Β· ${(d.views_used||[]).length} views Β· ${d.memory_count} memories Β· ${d.total_elapsed}s pipeline</div>
    <div class="problem-box">
      <h3>SUBJECT</h3>
      <p>${escPdf(d.problem)}</p>
      <h3 style="margin-top:10px">REFRAMED</h3>
      <p>${escPdf(d.reframed_problem)}</p>
    </div>
  </div>

  <div class="toc">
    <h2>Table of Contents</h2>
    <ol>
      ${eb ? '<li><strong>Β§0 β€” Executive Intelligence Brief</strong> (condensed 1-2 pages)</li>' : ''}
      ${ont ? '<li>Β§1 β€” Problem Reframing (ontological analysis)</li>' : ''}
      ${cd || vw ? '<li>Β§2 β€” Analytical Landscape (cross-domain + 18 views)</li>' : ''}
      ${sc || trib ? '<li>Β§3 β€” Scenario Architecture (scenarios + simulations + tribunal)</li>' : ''}
      ${sf ? '<li>Β§4 β€” Strategic Foresight (decisions, risks, actions)</li>' : ''}
      ${sa ? '<li>Β§5 β€” Action Playbook (robust moves + playbooks)</li>' : ''}
      ${hr ? '<li>Β§6 β€” Historical Precedent (parallels + warnings)</li>' : ''}
      ${dt ? '<li>Β§7 β€” Intelligence Signals & Predictions</li>' : ''}
      <li>Β§8 β€” Methodology & Confidence</li>
    </ol>
  </div>

  ${briefSection}
  ${ontologySection}
  ${landscapeSection}
  ${scenarioSection}
  ${strategicSection}
  ${actionsSection}
  ${historicalSection}
  ${triggersSection}
  ${methodSection}

  <div class="footer">
    XDART-Ξ¦ Γ— XHEART β€” Autonomous Strategic Intelligence Framework Β· Intelligence Dossier Β· ${escPdf(now)}<br>
    <em>Β«Ξ’Ξ»Ξ­Ο€Ο‰ Ο„ΞΏΟ…Ο‚ Ξ±Ξ½Ξ­ΞΌΞΏΟ…Ο‚ Ο€ΟΞΉΞ½ Ο†Ο…ΟƒΞ®ΞΎΞΏΟ…Ξ½Β»</em>
  </div>
</body>
</html>`;

  const win = window.open('', '_blank', 'width=900,height=700');
  if (!win) { alert('Please allow popups to download the dossier.'); return; }
  win.document.write(dossierHtml);
  win.document.close();
  setTimeout(() => win.print(), 500);
}

// β”€β”€ Client Profile Helpers β”€β”€
let presetProfiles = {};

async function loadPresetProfiles() {
  try {
    const res = await fetch(`${API_BASE}/xdart/client-profiles`);
    const data = await res.json();
    presetProfiles = {};
    for (const p of data) {
      presetProfiles[p.id] = p;
    }
  } catch (e) { /* non-critical */ }
}
loadPresetProfiles();

function onProfileSelect() {
  const val = document.getElementById('profileSelect').value;
  const form = document.getElementById('customProfileForm');
  const btn = document.getElementById('btnProfileToggle');
  if (val === 'custom') {
    form.classList.add('visible');
    btn.classList.add('active');
  } else {
    form.classList.remove('visible');
    btn.classList.remove('active');
    // If a preset is selected, populate the custom form with its data
    if (val && presetProfiles[val]) {
      populateCustomForm(presetProfiles[val]);
    }
  }
}

function toggleProfileForm() {
  const form = document.getElementById('customProfileForm');
  const btn = document.getElementById('btnProfileToggle');
  const visible = form.classList.toggle('visible');
  btn.classList.toggle('active', visible);
  if (visible) {
    document.getElementById('profileSelect').value = 'custom';
  }
}

function populateCustomForm(profile) {
  document.getElementById('cpRole').value = profile.role || '';
  document.getElementById('cpDecisions').value = (profile.decisions_i_make || []).join('\n');
  document.getElementById('cpResources').value = (profile.resources_i_control || []).join('\n');
  document.getElementById('cpTimeHorizon').value = profile.time_horizon || '';
  document.getElementById('cpRiskTolerance').value = profile.risk_tolerance || '';
  document.getElementById('cpConstraints').value = (profile.constraints || []).join('\n');
  document.getElementById('cpStakeholders').value = (profile.stakeholders || []).join('\n');
}

function getClientProfile() {
  const selectVal = document.getElementById('profileSelect').value;
  if (!selectVal) return null;

  // If a preset is selected and the custom form is NOT open, use the preset directly
  if (selectVal !== 'custom' && !document.getElementById('customProfileForm').classList.contains('visible')) {
    const preset = presetProfiles[selectVal];
    if (preset) {
      return {
        role: preset.role,
        decisions_i_make: preset.decisions_i_make || [],
        resources_i_control: preset.resources_i_control || [],
        time_horizon: preset.time_horizon || '',
        risk_tolerance: preset.risk_tolerance || '',
        constraints: preset.constraints || [],
        stakeholders: preset.stakeholders || [],
      };
    }
  }

  // Build from custom form
  const role = document.getElementById('cpRole').value.trim();
  if (!role) return null;

  const splitLines = (val) => val.split('\n').map(s => s.trim()).filter(Boolean);
  return {
    role: role,
    decisions_i_make: splitLines(document.getElementById('cpDecisions').value),
    resources_i_control: splitLines(document.getElementById('cpResources').value),
    time_horizon: document.getElementById('cpTimeHorizon').value.trim(),
    risk_tolerance: document.getElementById('cpRiskTolerance').value.trim(),
    constraints: splitLines(document.getElementById('cpConstraints').value),
    stakeholders: splitLines(document.getElementById('cpStakeholders').value),
  };
}

// β”€β”€ Main analysis function β”€β”€
async function startAnalysis() {
  const problem = document.getElementById('problemInput').value.trim();
  if (!problem || isRunning) return;

  isRunning = true;
  document.getElementById('btnRun').disabled = true;
  document.getElementById('btnRun').textContent = 'Analyzing...';
  document.getElementById('btnChat').disabled = true;

  // Remove empty state
  const empty = document.getElementById('emptyState');
  if (empty) empty.remove();

  // Create turn container
  const turnDiv = document.createElement('div');
  turnDiv.className = 'turn';
  turnDiv.innerHTML = `<div class="turn-question"><div class="q-label">Question</div>${esc(problem)}</div>`;
  const resultsDiv = document.createElement('div');
  resultsDiv.className = 'results';
  turnDiv.appendChild(resultsDiv);
  document.getElementById('conversation').appendChild(turnDiv);

  // Show progress
  const progressBar = document.getElementById('progressBar');
  progressBar.style.display = 'flex';
  resetPips();
  startTimer();

  // Phase data accumulator
  const phaseCards = {};
  let lastPhase = null;

  try {
    // SSE via fetch + ReadableStream (POST with body)
    const response = await fetch(`${API_BASE}/xdart/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ problem, client_profile: getClientProfile() }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let eventType = null;
    let eventData = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Parse SSE events from buffer
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          // Concatenate multi-line data (SSE spec: multiple data: lines joined by \n)
          eventData += (eventData ? '\n' : '') + line.slice(5).trim();
        } else if (line.trim() === '' && eventType && eventData) {
          // Process complete event β€” wrapped in try/catch so one bad card doesn't kill the stream
          try {
            handleSSEEvent(eventType, eventData, resultsDiv);
          } catch (e) {
            console.error(`[SSE] Error handling event '${eventType}':`, e);
          }
          eventType = null;
          eventData = '';
        }
      }
    }

  } catch (err) {
    resultsDiv.innerHTML += `<div class="phase-card" style="border-left:3px solid var(--red)">
      <div class="phase-card-body" style="color:var(--red)">Error: ${esc(err.message)}</div>
    </div>`;
  }

  isRunning = false;
  document.getElementById('btnRun').disabled = false;
  document.getElementById('btnRun').textContent = 'Analyze β—';
  document.getElementById('btnChat').disabled = false;
  document.getElementById('problemInput').value = '';
  document.getElementById('problemInput').focus();
  checkHealth();
}

function handleSSEEvent(type, dataStr, container) {
  // Ignore keepalive heartbeats β€” they just prevent stream timeout
  if (type === 'heartbeat') return;

  let data;
  try { data = JSON.parse(dataStr); } catch { return; }

  if (type === 'phase') {
    markPipActive(data.phase);
    const elapsed = data.elapsed;

    if (data.phase === 'wakeup_complete' && data.data) {
      container.innerHTML += buildWakeupCard(data.data, elapsed);
    } else if (data.phase === 'phase0_ontology' && data.data) {
      container.innerHTML += buildPhase0Card(data.data, elapsed);
    } else if (data.phase === 'concepts_activated' && data.data) {
      container.innerHTML += buildConceptsCard(data.data, elapsed);
    } else if (data.phase === 'world_context' && data.data) {
      container.innerHTML += buildWorldContextCard(data.data, elapsed);
    } else if (data.phase === 'phase1_xdart' && data.data) {
      container.innerHTML += buildPhase1Card(data.data, elapsed);
    } else if (data.phase === 'phase2_views' && data.data) {
      container.innerHTML += buildPhase2Card(data.data, elapsed);
    } else if (data.phase === 'phase2_5_scenarios' && data.data) {
      container.innerHTML += buildScenarioGenesisCard(data.data, elapsed);
    } else if (data.phase === 'phase2_7_simulations' && data.data) {
      container.innerHTML += buildSimulationCard(data.data, elapsed);
    } else if (data.phase === 'phase2_9_tribunal' && data.data) {
      container.innerHTML += buildTribunalCard(data.data, elapsed);
    } else if (data.phase === 'phase2_91_quantum' && data.data) {
      container.innerHTML += buildQuantumCard(data.data, elapsed);
    } else if (data.phase === 'phase2_95_actions' && data.data) {
      container.innerHTML += buildActionsCard(data.data, elapsed);
    } else if (data.phase === 'phase3_xheart' && data.data) {
      container.innerHTML += buildPhase3Card(data.data, elapsed);
    } else if (data.phase === 'xheart_expansion' && data.data) {
      container.innerHTML += buildExpansionCard(data.data, elapsed);
    } else if (data.phase === 'phase3_5_historical' && data.data) {
      container.innerHTML += buildHistoricalCard(data.data, elapsed);
    } else if (data.phase === 'phase3_7_strategic' && data.data) {
      container.innerHTML += buildStrategicCard(data.data, elapsed);
    } else if (data.phase === 'phase3_9_bets' && data.data) {
      container.innerHTML += buildBetsCard(data.data, elapsed);
    } else if (data.phase === 'phase3_95_executive_brief' && data.data) {
      container.innerHTML += buildExecutiveBriefCard(data.data, elapsed);
    } else if (data.phase === 'character_updated' && data.data) {
      container.innerHTML += buildCharacterUpdatedCard(data.data, elapsed);
    } else if (data.phase === 'core_change_proposed' && data.data) {
      container.innerHTML += buildCoreChangeCard(data.data, elapsed);
    } else if (data.phase === 'evolution_deployed' && data.data) {
      container.innerHTML += buildEvolutionCard(data.data, elapsed);
    } else if (data.phase === 'phase4_memory') {
      markAllPipsDone();
    }

    // Auto-scroll
    container.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'end' });

  } else if (type === 'complete') {
    markAllPipsDone();
    stopTimer(data.total_elapsed);
    _lastAnalysisData = data; // store for PDF export
    container.innerHTML += buildFinalCard(data);
    container.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'end' });

  } else if (type === 'error') {
    stopTimer('?');
    container.innerHTML += `<div class="phase-card" style="border-left:3px solid var(--red)">
      <div class="phase-card-body" style="color:var(--red)">Pipeline error: ${esc(data.error)}</div>
    </div>`;
  }
}

// β”€β”€ Chat History & Chat Mode β”€β”€
let chatHistory = [];
let isChatting = false;

// β”€β”€ Serialized Chat Queue β”€β”€
// All proactive + user chat requests stream one at a time β€” no parallel SSE streams.
// When 3 proactive alerts fire at once, they queue up and play sequentially.
const _chatQueue = [];       // {type:'proactive'|'user', ...}
let _chatQueueBusy = false;

function _enqueueChatItem(item) {
  _chatQueue.push(item);
  _drainChatQueue();
}

function _drainChatQueue() {
  if (_chatQueueBusy || !_chatQueue.length) return;
  _chatQueueBusy = true;
  isChatting = true;

  const item = _chatQueue.shift();

  // Only lock the chat button when processing a USER message.
  // Proactive alerts should NOT block the user from typing.
  const lockInput = (item.type === 'user');
  if (lockInput) {
    document.getElementById('btnChat').disabled = true;
    document.getElementById('btnChat').textContent = '...';
  }
  document.getElementById('btnRun').disabled = true;

  if (_chatQueue.length > 0) {
    console.log(`[ChatQueue] Processing β€” ${_chatQueue.length} more item(s) waiting`);
  }

  const done = () => {
    _chatQueueBusy = false;
    if (_chatQueue.length === 0) {
      isChatting = false;
      document.getElementById('btnChat').disabled = false;
      document.getElementById('btnChat').textContent = 'Chat';
      if (!isRunning) document.getElementById('btnRun').disabled = false;
      document.getElementById('problemInput').focus();
    } else {
      // More items waiting β€” drain after a short pause for readability.
      // Re-enable chat button between items so user can always type.
      document.getElementById('btnChat').disabled = false;
      document.getElementById('btnChat').textContent = 'Chat';
      setTimeout(_drainChatQueue, 400);
    }
  };

  if (item.type === 'proactive') {
    _runInitiateProactiveChat(item.notif).finally(done);
  } else {
    _runSendChat(item.message).finally(done);
  }
}

// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
//  VOICE ENGINE β€” ElevenLabs TTS (WebSocket) + STT (Scribe v2)
//
//  Architecture:
//    TTS (primary): Browser WS β†’ Server proxy WS β†’ ElevenLabs REST streaming (eleven_v3 + pcm_24000)
//         Server buffers text, detects sentence boundaries, streams PCM audio back.
//         Best voice quality via v3 model. Sentence-level progressive audio.
//    TTS (fallback): Browser WS β†’ ElevenLabs WS directly (eleven_multilingual_v2 + pcm_24000)
//         Word-level streaming, lower quality than v3.
//    TTS (last resort): Browser β†’ /xdart/voice/tts β†’ MP3 blob β†’ Audio element.
//
//    STT: Browser MediaRecorder β†’ POST /xdart/voice/stt β†’ ElevenLabs Scribe v2
//         Recording is sent as webm/opus for transcription.
//
//  The API key is fetched from the backend at startup (not hardcoded).
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•

let _voiceAutoPlay = false;     // Auto-play TTS on Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ responses
let _voiceRecording = false;    // Currently recording mic
let _mediaRecorder = null;      // MediaRecorder instance
let _audioChunks = [];          // Recorded audio chunks

// β”€β”€ Voice Config (fetched from backend) β”€β”€
let _voiceCfg = null;           // {api_key, voice_id, model_tts, model_stt, tts_settings}
let _voiceEnabled = false;      // True once config is loaded and valid

// β”€β”€ TTS Streaming State β”€β”€
let _ttsWs = null;              // Current WebSocket connection (ONE per message)
let _ttsAudioCtx = null;        // AudioContext for playback
let _ttsGainNode = null;        // Master gain node β€” all sources route through this
let _ttsSources = [];           // ALL scheduled AudioBufferSourceNodes (for clean stop)
let _ttsSpeaking = false;       // True while TTS is active (WebSocket open or audio playing)
let _ttsNextPlayTime = 0;       // AudioContext time when last scheduled chunk finishes
let _ttsFirstChunk = false;     // Whether first audio chunk has been scheduled
let _ttsGen = 0;                // Generation counter β€” bumped on each new message/stop
let _ttsDoneResolve = null;     // Resolve function for end-of-stream waiting
let _ttsTotalBytes = 0;         // Total audio bytes received in current stream
let _ttsPendingText = '';       // Text buffered while WebSocket is still connecting
let _ttsEosPending = false;     // Whether endStreamingTTS was called before WS opened
const _ttsPlaybackRate = 1.0;   // Client-side playback rate (1.0 = no distortion; speed handled by ElevenLabs API)

// β”€β”€ Initialize Voice System β”€β”€
async function _initVoice() {
  try {
    const res = await fetch(`${API_BASE}/xdart/voice/config`);
    if (!res.ok) return;
    const cfg = await res.json();
    if (!cfg.enabled) {
      console.log('[Voice] Disabled:', cfg.reason);
      return;
    }
    _voiceCfg = cfg;
    _voiceEnabled = true;

    // Show voice buttons
    document.getElementById('btnMic').style.display = '';
    document.getElementById('btnVoiceToggle').style.display = '';

    console.log('[Voice] Initialized β€” model:', cfg.model_tts, 'voice:', cfg.voice_id);
  } catch (e) {
    console.warn('[Voice] Config fetch failed:', e);
  }
}

// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
// TTS: WebSocket Streaming (browser β†’ ElevenLabs β†’ AudioContext)
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•

function _ensureAudioContext() {
  if (!_ttsAudioCtx || _ttsAudioCtx.state === 'closed') {
    _ttsAudioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    console.log('[Voice/TTS] New AudioContext created, state:', _ttsAudioCtx.state, 'sampleRate:', _ttsAudioCtx.sampleRate);
  }
  if (_ttsAudioCtx.state === 'suspended') {
    _ttsAudioCtx.resume().then(() => {
      console.log('[Voice/TTS] AudioContext resumed β†’ state:', _ttsAudioCtx.state);
    }).catch(e => {
      console.warn('[Voice/TTS] AudioContext resume failed (need user gesture?):', e);
    });
  }
  return _ttsAudioCtx;
}

function _cleanTextForSpeech(text) {
  return text
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/#{1,6}\s+/g, '')
    .replace(/[-*]\s+/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/<[^>]+>/g, '')
    .trim();
}

/**
 * Strip internal directive tags from displayed text (client-side).
 * Handles: <VISUAL_ACTION>...</VISUAL_ACTION>, <MEMORY_STORE ... />,
 * <BAYESIAN_FUZZY_ENGINE>...</BAYESIAN_FUZZY_ENGINE>, and self-closing variants.
 * Used during streaming to hide tags before post-processing runs on server.
 */
function _stripInternalTags(text) {
  // Execution tags the LLM hallucinates: <run>, <run_web_agent>, <execute>, etc.
  text = text.replace(/<run(?:_\w+)?\b[^>]*>[\s\S]*?<\/run(?:_\w+)?\s*>/gi, '');
  text = text.replace(/<execute\b[^>]*>[\s\S]*?<\/execute\s*>/gi, '');
  text = text.replace(/<search\b[^>]*>[\s\S]*?<\/search\s*>/gi, '');
  text = text.replace(/<tool_call\b[^>]*>[\s\S]*?<\/tool_call\s*>/gi, '');
  text = text.replace(/<function_call\b[^>]*>[\s\S]*?<\/function_call\s*>/gi, '');
  // Block-style internal tags: <TAG>...</TAG>
  text = text.replace(/<VISUAL_ACTION\b[^>]*>[\s\S]*?<\/VISUAL_ACTION\s*>/gi, '');
  text = text.replace(/<MEMORY_STORE\b[^>]*>[\s\S]*?<\/MEMORY_STORE\s*>/gi, '');
  text = text.replace(/<BAYESIAN_FUZZY_ENGINE\b[^>]*>[\s\S]*?<\/BAYESIAN_FUZZY_ENGINE\s*>/gi, '');
  text = text.replace(/<MONGO_ACTION\b[^>]*>[\s\S]*?<\/MONGO_ACTION\s*>/gi, '');
  // Block-style shell_action with nested elements: <shell_action><command>...</command></shell_action>
  text = text.replace(/<shell_action\b[^>]*>[\s\S]*?<\/shell_action\s*>/gi, '');
  text = text.replace(/<SHELL_ACTION\b[^>]*>[\s\S]*?<\/SHELL_ACTION\s*>/gi, '');
  // Block-style spawn_agent: <spawn_agent>...</spawn_agent>
  text = text.replace(/<spawn_agent\b[^>]*>[\s\S]*?<\/spawn_agent\s*>/gi, '');
  text = text.replace(/<SPAWN_AGENT\b[^>]*>[\s\S]*?<\/SPAWN_AGENT\s*>/gi, '');
  // Self-closing tags: <TAG ... />
  text = text.replace(/<VISUAL_ACTION\s+[^>]*\/?>/gi, '');
  text = text.replace(/<MEMORY_STORE\s+[^>]*\/?>/gi, '');
  text = text.replace(/<BAYESIAN_FUZZY_ENGINE\s+[^>]*\/?>/gi, '');
  text = text.replace(/<SHELL_ACTION\s+[^>]*\/?>/gi, '');
  text = text.replace(/<SPAWN_AGENT\s+[^>]*\/?>/gi, '');
  text = text.replace(/<MONGO_ACTION\s+[^>]*\/?>/gi, '');
  // Incomplete block tags at end of stream (opening tag without closing)
  text = text.replace(/<run(?:_\w+)?\b[^>]*>[\s\S]*$/gi, '');
  text = text.replace(/<execute\b[^>]*>[\s\S]*$/gi, '');
  text = text.replace(/<VISUAL_ACTION\b[^>]*>[\s\S]*$/gi, '');
  text = text.replace(/<MEMORY_STORE\b[^>]*>[\s\S]*$/gi, '');
  text = text.replace(/<MONGO_ACTION\b[^>]*>[\s\S]*$/gi, '');
  text = text.replace(/<shell_action\b[^>]*>[\s\S]*$/gi, '');
  text = text.replace(/<SHELL_ACTION\b[^>]*>[\s\S]*$/gi, '');
  text = text.replace(/<spawn_agent\b[^>]*>[\s\S]*$/gi, '');
  text = text.replace(/<SPAWN_AGENT\b[^>]*>[\s\S]*$/gi, '');
  // Bracket-style hallucinated tags: [TAG: ...] β€” LLM uses wrong syntax, never executed
  text = text.replace(/\[(?:VISUAL_ACTION|MEMORY_STORE|SHELL_ACTION|SPAWN_AGENT|MONGO_ACTION|BAYESIAN_FUZZY_ENGINE)[:\s][^\]]*\]/gi, '');
  // Clean up multiple blank lines
  text = text.replace(/\n{3,}/g, '\n\n');
  return text.trim();
}

// β”€β”€ Streaming TTS: ONE WebSocket per message β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€
//
//  Flow:
//   1. startStreamingTTS() β€” opens WebSocket (server proxy or direct), sends BOS
//   2. feedStreamingTTS(chunk) β€” sends cleaned text chunks as they arrive
//   3. endStreamingTTS() β€” sends EOS, waits for all audio to finish
//   4. stopSpeaking() β€” kills everything immediately
//
//  Primary path (tts_proxy_ws=true):
//    Browser WS β†’ Our Server WS β†’ ElevenLabs REST streaming (eleven_v3)
//    Server detects sentence boundaries, streams PCM chunks back.
//    Best quality (v3), progressive audio, slight sentence-level latency.
//
//  Fallback path (tts_proxy_ws=false):
//    Browser WS β†’ ElevenLabs WS directly (eleven_multilingual_v2)
//    Word-level streaming, lower quality than v3.
//
//  Audio playback uses AudioContext with precise scheduling for gapless output.
//  All audio flows through a master GainNode for instant mute/stop.
// β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€β”€

/**
 * Open a WebSocket for streaming TTS (server proxy β†’ v3, or direct ElevenLabs).
 * Returns the generation number for this stream.
 * Call feedStreamingTTS(chunk) to send text, endStreamingTTS() when done.
 */
function startStreamingTTS() {
  if (!_voiceEnabled || !_voiceCfg) return 0;

  // Kill any previous stream
  _killTTSStream();

  const gen = ++_ttsGen;
  const ctx = _ensureAudioContext();
  const voiceId = _voiceCfg.voice_id;
  const modelId = _voiceCfg.model_tts_ws || _voiceCfg.model_tts;
  const apiKey = _voiceCfg.api_key;

  // Reset playback state
  _ttsSources = [];
  _ttsNextPlayTime = 0;
  _ttsFirstChunk = false;
  _ttsTotalBytes = 0;
  _ttsPendingText = '';
  _ttsEosPending = false;
  _ttsSpeaking = true;
  _ttsDoneResolve = null;
  _updateSpeakingIndicator(true);

  // Create master gain node for this stream
  _ttsGainNode = ctx.createGain();
  _ttsGainNode.connect(ctx.destination);

  // β”€β”€ Choose WebSocket target: server proxy (v3 quality) or direct ElevenLabs β”€β”€
  let wsUrl;
  const useProxy = !!_voiceCfg.tts_proxy_ws;
  if (useProxy) {
    // Server-side proxy: /xdart/voice/tts-stream β†’ ElevenLabs REST streaming (eleven_v3)
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsUrl = `${proto}//${location.host}/xdart/voice/tts-stream`;
  } else {
    // Direct ElevenLabs WebSocket (fallback, limited to multilingual_v2)
    wsUrl = `wss://api.elevenlabs.io/v1/text-to-speech/${voiceId}/stream-input?model_id=${encodeURIComponent(modelId)}&output_format=pcm_24000`;
  }

  const ws = new WebSocket(wsUrl);
  _ttsWs = ws;

  ws.onopen = () => {
    if (gen !== _ttsGen) { ws.close(); return; }
    // Send BOS (Beginning of Stream) with voice settings
    ws.send(JSON.stringify({
      text: ' ',
      voice_settings: {
        stability: _voiceCfg.tts_settings?.stability ?? 0.50,
        similarity_boost: _voiceCfg.tts_settings?.similarity_boost ?? 0.75,
        speed: _voiceCfg.tts_settings?.speed ?? 1.0,
      },
      xi_api_key: apiKey,
      generation_config: {
        chunk_length_schedule: [120, 160, 250, 290],
      },
    }));
    console.log(`[Voice/TTS] WebSocket opened for streaming (${useProxy ? 'server proxy β†’ v3' : 'direct ElevenLabs'})`);

    // Flush any text that arrived while WebSocket was connecting
    if (_ttsPendingText) {
      try {
        ws.send(JSON.stringify({ text: _ttsPendingText }));
        console.log('[Voice/TTS] Flushed %d chars of pending text', _ttsPendingText.length);
      } catch (e) {
        console.warn('[Voice/TTS] Pending text flush failed:', e);
      }
      _ttsPendingText = '';
    }
    // If EOS was requested while still connecting, send it now
    if (_ttsEosPending) {
      try {
        ws.send(JSON.stringify({ text: '' }));
        console.log('[Voice/TTS] Flushed pending EOS');
      } catch (e) {}
      _ttsEosPending = false;
    }
  };

  ws.onmessage = (event) => {
    if (gen !== _ttsGen) {
      console.warn('[Voice/TTS] Dropping message β€” gen mismatch: stream=%d, current=%d', gen, _ttsGen);
      return;
    }
    try {
      const msg = JSON.parse(event.data);

      if (msg.audio) {
        // Decode base64 PCM 24kHz 16-bit mono β†’ Float32
        const binaryStr = atob(msg.audio);
        const bytes = new Uint8Array(binaryStr.length);
        for (let i = 0; i < binaryStr.length; i++) {
          bytes[i] = binaryStr.charCodeAt(i);
        }
        _ttsTotalBytes += bytes.length;

        // Skip empty chunks
        if (bytes.length < 2) return;

        const samples = new Float32Array(bytes.length / 2);
        const view = new DataView(bytes.buffer);
        for (let i = 0; i < samples.length; i++) {
          samples[i] = view.getInt16(i * 2, true) / 32768;
        }

        // Ensure AudioContext is running (may have been suspended by browser policy)
        if (ctx.state === 'suspended') {
          console.warn('[Voice/TTS] AudioContext suspended β€” attempting resume');
          ctx.resume().then(() => {
            console.log('[Voice/TTS] AudioContext resumed successfully, state:', ctx.state);
          }).catch(e => {
            console.error('[Voice/TTS] AudioContext resume failed:', e);
          });
        }

        // Create AudioBuffer and schedule gapless playback
        const audioBuffer = ctx.createBuffer(1, samples.length, 24000);
        audioBuffer.getChannelData(0).set(samples);

        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.playbackRate.value = _ttsPlaybackRate;
        source.connect(_ttsGainNode);

        const now = ctx.currentTime;
        if (!_ttsFirstChunk) {
          _ttsNextPlayTime = now + 0.05;  // 50ms initial delay for AudioContext to settle
          _ttsFirstChunk = true;
          console.log('[Voice/TTS] First audio chunk: %d bytes, ctx.state=%s, sampleRate=%d',
                       bytes.length, ctx.state, ctx.sampleRate);
        }

        const startAt = Math.max(_ttsNextPlayTime, now);
        source.start(startAt);
        _ttsNextPlayTime = startAt + (audioBuffer.duration / _ttsPlaybackRate);

        _ttsSources.push(source);
      }

      if (msg.isFinal) {
        // All audio chunks received β€” wait for playback to finish
        const remainingMs = Math.max(0, (_ttsNextPlayTime - ctx.currentTime) * 1000) + 150;
        console.log('[Voice/TTS] isFinal received β€” totalBytes=%d, chunks=%d, ctx.state=%s, waitMs=%.0f',
                     _ttsTotalBytes, _ttsSources.length, ctx.state, remainingMs);
        setTimeout(() => {
          if (gen === _ttsGen) {
            _ttsSpeaking = false;
            _updateSpeakingIndicator(false);
          }
          if (_ttsDoneResolve) { _ttsDoneResolve(); _ttsDoneResolve = null; }
        }, remainingMs);
      }

      if (msg.error) {
        console.error('[Voice/TTS] Server error:', msg.error);
      }
    } catch (decodeErr) {
      console.warn('[Voice/TTS] Chunk decode error:', decodeErr);
    }
  };

  ws.onerror = (e) => {
    console.warn('[Voice/TTS] WebSocket error β€” readyState:', ws.readyState, 'url:', wsUrl.replace(/xi_api_key=[^&]+/, 'xi_api_key=***'));
  };

  ws.onclose = (e) => {
    if (e.code !== 1000) {
      console.warn('[Voice/TTS] WebSocket closed abnormally β€” code:', e.code, 'reason:', e.reason || '(none)');
    }
    if (_ttsWs === ws) _ttsWs = null;
    // If we got audio but never got isFinal, still wait for playback
    if (gen === _ttsGen && _ttsTotalBytes > 0 && _ttsSpeaking) {
      const ctx2 = _ttsAudioCtx;
      const remainingMs = ctx2 ? Math.max(0, (_ttsNextPlayTime - ctx2.currentTime) * 1000) + 150 : 0;
      setTimeout(() => {
        if (gen === _ttsGen) {
          _ttsSpeaking = false;
          _updateSpeakingIndicator(false);
        }
        if (_ttsDoneResolve) { _ttsDoneResolve(); _ttsDoneResolve = null; }
      }, remainingMs);
    } else if (_ttsDoneResolve) {
      _ttsDoneResolve();
      _ttsDoneResolve = null;
    }
  };

  // Safety timeout: 60s max per stream
  setTimeout(() => {
    if (gen === _ttsGen && _ttsWs === ws && ws.readyState === WebSocket.OPEN) {
      console.warn('[Voice/TTS] Safety timeout β€” closing WebSocket');
      try { ws.send(JSON.stringify({ text: '' })); } catch(e) {}
      setTimeout(() => { try { ws.close(); } catch(e) {} }, 2000);
    }
  }, 60000);

  return gen;
}

/**
 * Feed a text chunk into the open TTS WebSocket.
 * Called for each SSE streaming chunk (after cleaning).
 */
function feedStreamingTTS(text, gen) {
  if (!text || gen !== _ttsGen) return;
  if (!_ttsWs) return;

  const clean = _cleanTextForSpeech(text);
  if (!clean) return;

  if (_ttsWs.readyState === WebSocket.OPEN) {
    // WebSocket is open β€” send immediately
    try {
      _ttsWs.send(JSON.stringify({ text: clean + ' ' }));
    } catch (e) {
      console.warn('[Voice/TTS] Send failed:', e);
    }
  } else if (_ttsWs.readyState === WebSocket.CONNECTING) {
    // WebSocket still connecting β€” buffer text for flush on open
    _ttsPendingText += clean + ' ';
  } else {
    console.warn('[Voice/TTS] Cannot send β€” WS state:', _ttsWs.readyState);
  }
}

/**
 * Signal end of text stream β€” sends EOS to WebSocket.
 * Returns a Promise that resolves when all audio has finished playing.
 */
function endStreamingTTS(gen) {
  if (gen !== _ttsGen) return Promise.resolve();

  // Send EOS (empty string closes the generation)
  if (_ttsWs && _ttsWs.readyState === WebSocket.OPEN) {
    try {
      _ttsWs.send(JSON.stringify({ text: '' }));
    } catch (e) {
      console.warn('[Voice/TTS] EOS send failed:', e);
    }
  } else if (_ttsWs && _ttsWs.readyState === WebSocket.CONNECTING) {
    // WS still connecting β€” mark EOS as pending, will flush on open
    _ttsEosPending = true;
  }

  // Return promise that resolves when isFinal is received and audio finishes
  return new Promise((resolve) => {
    _ttsDoneResolve = resolve;
    // Safety: resolve after 15s even if isFinal never comes
    setTimeout(() => {
      if (_ttsDoneResolve === resolve) {
        _ttsDoneResolve = null;
        resolve();
      }
    }, 15000);
  });
}

/**
 * Speak a complete text block (non-streaming).
 * Used for fallback/non-streaming responses and autoSpeak.
 */
async function speakText(text) {
  if (!_voiceEnabled || !text || text.length < 2) return;

  const cleanText = _cleanTextForSpeech(text);
  if (cleanText.length < 2) return;
  const textToSend = cleanText.length > 5000 ? cleanText.substring(0, 5000) : cleanText;

  // Open a streaming TTS, feed the entire text, then close
  const gen = startStreamingTTS();
  if (!gen) return;

  // Wait for WebSocket to open (max 3s)
  let waited = 0;
  while ((!_ttsWs || _ttsWs.readyState !== WebSocket.OPEN) && waited < 3000) {
    await new Promise(r => setTimeout(r, 50));
    waited += 50;
    if (gen !== _ttsGen) return;
  }

  if (!_ttsWs || _ttsWs.readyState !== WebSocket.OPEN) {
    console.warn('[Voice/TTS] WebSocket failed to open, trying server proxy');
    try {
      await _speakViaServerProxy(textToSend);
    } catch (e) {
      console.warn('[Voice/TTS] Server proxy also failed:', e);
    }
    return;
  }

  // Feed entire text and close
  feedStreamingTTS(textToSend, gen);
  await endStreamingTTS(gen);
}

/**
 * Fallback TTS: Server-side proxy via /xdart/voice/tts.
 * Streams MP3 chunks and plays via Audio element.
 */
async function _speakViaServerProxy(text) {
  const res = await fetch(`${API_BASE}/xdart/voice/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });

  if (!res.ok) {
    throw new Error(`Server TTS error: ${res.status}`);
  }

  const reader = res.body.getReader();
  const chunks = [];
  while (true) {
    const { done, value } = await reader.read();
    if (value) chunks.push(value);
    if (done) break;
  }

  if (chunks.length === 0) return;

  const blob = new Blob(chunks, { type: 'audio/mpeg' });
  const audioUrl = URL.createObjectURL(blob);

  return new Promise((resolve) => {
    const audio = new Audio(audioUrl);
    audio.onended = () => { URL.revokeObjectURL(audioUrl); resolve(); };
    audio.onerror = () => { URL.revokeObjectURL(audioUrl); resolve(); };
    audio.play().catch(() => resolve());
  });
}

/**
 * Kill the current TTS stream β€” WebSocket + audio + state.
 */
function _killTTSStream() {
  if (_ttsWs) {
    try { _ttsWs.close(); } catch(e) {}
    _ttsWs = null;
  }
  _ttsPendingText = '';
  _ttsEosPending = false;
  for (const src of _ttsSources) {
    try { src.stop(); } catch(e) {}
  }
  _ttsSources = [];
  if (_ttsGainNode) {
    try { _ttsGainNode.disconnect(); } catch(e) {}
    _ttsGainNode = null;
  }
  if (_ttsDoneResolve) { _ttsDoneResolve(); _ttsDoneResolve = null; }
}

/**
 * Stop ALL TTS β€” kills the stream and resets state.
 * Used when a new message starts or user explicitly stops.
 */
function stopSpeaking() {
  _ttsGen++;
  _killTTSStream();
  _ttsSpeaking = false;
  _updateSpeakingIndicator(false);
}

/**
 * Visual indicator for speaking state.
 */
function _updateSpeakingIndicator(speaking) {
  const btn = document.getElementById('btnVoiceToggle');
  if (!btn) return;
  if (speaking) {
    btn.textContent = 'π”';
    btn.style.animation = 'pulse 1s infinite';
  } else if (_voiceAutoPlay) {
    btn.textContent = 'π”';
    btn.style.animation = '';
  } else {
    btn.textContent = 'π”‡';
    btn.style.animation = '';
  }
}


// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
// STT: Speech to Text (Mic β†’ ElevenLabs Scribe v2)
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•

async function toggleVoiceRecording() {
  if (_voiceRecording) {
    stopVoiceRecording();
  } else {
    startVoiceRecording();
  }
}

async function startVoiceRecording() {
  const btn = document.getElementById('btnMic');

  // Stop any playing TTS to avoid feedback
  stopSpeaking();

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        sampleRate: 16000,
      }
    });
    _audioChunks = [];
    _mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });

    _mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) _audioChunks.push(e.data);
    };

    _mediaRecorder.onstop = async () => {
      // Stop all tracks
      stream.getTracks().forEach(t => t.stop());

      const blob = new Blob(_audioChunks, { type: 'audio/webm' });
      _audioChunks = [];

      if (blob.size < 100) {
        console.warn('[Voice/STT] Recording too short');
        btn.textContent = 'π™';
        btn.disabled = false;
        _voiceRecording = false;
        btn.style.background = 'linear-gradient(135deg,#1b5e20,#2e7d32)';
        return;
      }

      btn.textContent = 'β³';
      btn.disabled = true;

      try {
        const formData = new FormData();
        formData.append('file', blob, 'recording.webm');

        const res = await fetch(`${API_BASE}/xdart/voice/stt`, {
          method: 'POST',
          body: formData,
        });

        if (!res.ok) {
          console.warn('[Voice/STT] Error:', res.status, await res.text());
          return;
        }

        const data = await res.json();
        if (data.text && data.text.trim()) {
          const input = document.getElementById('problemInput');
          const trimmed = data.text.trim();
          input.value = (input.value ? input.value + ' ' : '') + trimmed;
          input.focus();
          console.log('[Voice/STT] Transcribed:', trimmed.substring(0, 80), `(lang=${data.language}, conf=${data.language_probability})`);

          // Auto-send if the text looks like a complete sentence
          if (_voiceAutoPlay && /[.!?;]$/.test(trimmed)) {
            sendChat();
          }
        }
      } catch (err) {
        console.warn('[Voice/STT] Transcription failed:', err);
      } finally {
        btn.textContent = 'π™';
        btn.disabled = false;
        _voiceRecording = false;
        btn.style.background = 'linear-gradient(135deg,#1b5e20,#2e7d32)';
      }
    };

    _mediaRecorder.start(250); // collect data every 250ms for faster availability
    _voiceRecording = true;
    btn.textContent = 'βΉ';
    btn.style.background = 'linear-gradient(135deg,#b71c1c,#d32f2f)';
    btn.title = 'Recording... click to stop';
    console.log('[Voice/STT] Recording started');
  } catch (err) {
    console.warn('[Voice/STT] Mic access denied:', err);
    btn.textContent = 'π™';
    alert('Microphone access denied. Please allow microphone access in your browser settings.');
  }
}

function stopVoiceRecording() {
  if (_mediaRecorder && _mediaRecorder.state === 'recording') {
    _mediaRecorder.stop();
    console.log('[Voice/STT] Recording stopped, transcribing...');
  }
}


// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
// Voice Controls
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•

function toggleAutoVoice() {
  _voiceAutoPlay = !_voiceAutoPlay;
  const btn = document.getElementById('btnVoiceToggle');
  if (_voiceAutoPlay) {
    btn.textContent = 'π”';
    btn.style.opacity = '1';
    btn.title = 'Voice ON β€” Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ will speak (click to mute)';
    // Resume AudioContext (required after user gesture)
    _ensureAudioContext();
    console.log('[Voice] Auto-voice enabled');
  } else {
    btn.textContent = 'π”‡';
    btn.style.opacity = '0.5';
    btn.title = 'Voice OFF β€” click to enable Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ voice';
    stopSpeaking();
    console.log('[Voice] Auto-voice disabled');
  }
}

/**
 * Auto-speak helper β€” called after each Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ response.
 * Only speaks if auto-voice is enabled.
 */
function autoSpeak(text) {
  if (_voiceAutoPlay && _voiceEnabled && text) {
    // Stop any previous TTS before starting new message
    stopSpeaking();
    speakText(text);
  }
}

// β”€β”€ Public entry point: enqueue user message β”€β”€
function sendChat() {
  const message = document.getElementById('problemInput').value.trim();
  if (!message || isRunning) return;
  // Allow enqueue even if proactive chats are processing β€”
  // the queue serializes execution, user doesn't need to wait.
  document.getElementById('problemInput').value = '';

  // Remove empty state
  const empty = document.getElementById('emptyState');
  if (empty) empty.remove();

  // Show user message bubble IMMEDIATELY β€” don't wait for queue to drain.
  // This way the user sees their message even if a proactive analysis is still running.
  const conversation = document.getElementById('conversation');
  conversation.insertAdjacentHTML('beforeend', `
    <div class="chat-message chat-user" style="margin:8px 0;padding:10px 16px;background:rgba(255,255,255,0.04);border-radius:10px;border-left:3px solid var(--gold);max-width:85%">
      <div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">You</div>
      <div style="font-size:14px;color:var(--text-primary);line-height:1.5">${esc(message)}</div>
    </div>`);
  conversation.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'end' });

  _enqueueChatItem({ type: 'user', message });
}

async function _runSendChat(message) {
  // User message bubble is already shown by sendChat() β€” no need to add it again.
  const conversation = document.getElementById('conversation');

  // Add thinking indicator
  const thinkingId = 'chat-thinking-' + Date.now();
  conversation.insertAdjacentHTML('beforeend', `
    <div id="${thinkingId}" class="chat-message chat-thinking" style="margin:8px 0;padding:10px 16px;max-width:85%;margin-left:auto">
      <div style="font-size:12px;color:var(--text-dim);font-style:italic">Thinking...</div>
    </div>`);
  conversation.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'end' });

  // Prepare streaming response container
  const responseId = 'chat-stream-' + Date.now();
  let responseDiv = null;
  let responseTextEl = null;
  let streamedText = '';

  // β”€β”€ Stop any previous TTS and start streaming TTS for this message β”€β”€
  stopSpeaking();
  let myGen = 0;
  if (_voiceAutoPlay && _voiceEnabled) {
    myGen = startStreamingTTS();
  }

  try {
    // β•β•β• SSE Streaming Chat β•β•β•
    const res = await fetch(`${API_BASE}/xdart/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message,
        history: chatHistory.slice(-20),
      }),
    });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let sseBuffer = '';
    let gotDone = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      sseBuffer += decoder.decode(value, { stream: true });

      // Parse SSE events from buffer
      const lines = sseBuffer.split('\n');
      sseBuffer = lines.pop() || '';  // Keep incomplete line in buffer

      let currentEvent = 'message';
      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.substring(6).trim();
        } else if (line.startsWith('data:')) {
          const dataStr = line.substring(5).trim();
          if (!dataStr) continue;

          let data;
          try { data = JSON.parse(dataStr); } catch { continue; }

          // β”€β”€ Handle SSE events β”€β”€
          if (currentEvent === 'routing') {
            // Router decided β€” update thinking indicator
            const thinkEl = document.getElementById(thinkingId);
            if (thinkEl) {
              if (data.action === 'web_respond') {
                thinkEl.querySelector('div').textContent = 'π Searching web...';
              } else {
                thinkEl.querySelector('div').textContent = 'Generating...';
              }
            }
          }

          else if (currentEvent === 'pipeline') {
            // Pipeline redirect
            const thinkEl = document.getElementById(thinkingId);
            if (thinkEl) thinkEl.remove();

            chatHistory.push({ role: 'user', content: message });
            chatHistory.push({ role: 'assistant', content: `[PIPELINE TRIGGERED] ${data.reasoning || ''}` });

            conversation.insertAdjacentHTML('beforeend', `
              <div class="chat-message" style="margin:8px 0;padding:10px 16px;background:rgba(255,215,64,0.06);border-radius:10px;border-left:3px solid #ffd740;max-width:85%;margin-left:auto">
                <div style="font-size:11px;color:#ffd740;margin-bottom:4px">π”® Prophet Mode Activated</div>
                <div style="font-size:13px;color:var(--text-secondary);line-height:1.4">${esc(data.reasoning || '')}</div>
              </div>`);
            conversation.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'end' });

            // Pipeline redirect β€” release queue so it can drain, then start pipeline
            document.getElementById('problemInput').value = data.problem || message;
            startAnalysis();
            return;
          }

          else if (currentEvent === 'chunk') {
            // β”€β”€ Streaming text chunk β”€β”€
            const chunkText = data.text || '';
            streamedText += chunkText;

            // Create response bubble on first chunk
            if (!responseDiv) {
              const thinkEl = document.getElementById(thinkingId);
              if (thinkEl) thinkEl.remove();

              conversation.insertAdjacentHTML('beforeend', `
                <div id="${responseId}" class="chat-message chat-assistant" style="margin:8px 0;padding:12px 16px;background:rgba(100,181,246,0.06);border-radius:10px;border-left:3px solid #64b5f6;max-width:85%;margin-left:auto">
                  <div style="font-size:11px;color:#64b5f6;margin-bottom:4px">Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚</div>
                  <div id="${responseId}-text" style="font-size:14px;color:var(--text-primary);line-height:1.6;white-space:pre-wrap"></div>
                </div>`);
              responseDiv = document.getElementById(responseId);
              responseTextEl = document.getElementById(`${responseId}-text`);
            }

            // Strip internal tags before displaying (they'll be processed server-side on "done")
            responseTextEl.textContent = _stripInternalTags(streamedText);
            responseDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });

            // Feed CLEANED text chunk to streaming TTS
            const cleanChunk = _stripInternalTags(chunkText);
            if (cleanChunk && myGen) feedStreamingTTS(cleanChunk, myGen);
          }

          else if (currentEvent === 'done') {
            gotDone = true;
            const finalText = _stripInternalTags(data.full_text || streamedText);

            // Update with final cleaned text (post-processed: directives removed)
            if (responseTextEl) {
              responseTextEl.textContent = finalText;
            }

            chatHistory.push({ role: 'user', content: message });
            chatHistory.push({ role: 'assistant', content: finalText });

            // Signal end of streaming TTS
            if (myGen) endStreamingTTS(myGen);

            // Check if self-prompt was updated (async, non-blocking)
            checkSelfPromptUpdate(conversation);
          }

          else if (currentEvent === 'error') {
            console.error('[Chat/Stream] Server error:', data.message);
          }

          currentEvent = 'message';  // Reset for next event
        }
      }
      // Exit as soon as done event is processed β€” don't wait for TCP close
      if (gotDone) break;
    }

    // If no done event came, still clean up
    if (!gotDone && streamedText) {
      chatHistory.push({ role: 'user', content: message });
      chatHistory.push({ role: 'assistant', content: streamedText });
    }

    // Remove thinking indicator if still present
    const thinkEl = document.getElementById(thinkingId);
    if (thinkEl) thinkEl.remove();

  } catch (err) {
    const thinkEl = document.getElementById(thinkingId);
    if (thinkEl) thinkEl.remove();

    // Fallback: try non-streaming endpoint
    console.warn('[Chat] Stream failed, falling back to non-streaming:', err.message);
    try {
      const res = await fetch(`${API_BASE}/xdart/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, history: chatHistory.slice(-20) }),
      });
      const data = await res.json();

      const fallbackResponse = _stripInternalTags(data.response || '');
      chatHistory.push({ role: 'user', content: message });
      chatHistory.push({ role: 'assistant', content: fallbackResponse });

      conversation.insertAdjacentHTML('beforeend', `
        <div class="chat-message chat-assistant" style="margin:8px 0;padding:12px 16px;background:rgba(100,181,246,0.06);border-radius:10px;border-left:3px solid #64b5f6;max-width:85%;margin-left:auto">
          <div style="font-size:11px;color:#64b5f6;margin-bottom:4px">Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚</div>
          <div style="font-size:14px;color:var(--text-primary);line-height:1.6;white-space:pre-wrap">${esc(fallbackResponse)}</div>
        </div>`);

      autoSpeak(fallbackResponse);
    } catch (fallbackErr) {
      conversation.insertAdjacentHTML('beforeend', `
        <div class="chat-message" style="margin:8px 0;padding:10px 16px;border-left:3px solid var(--red);max-width:85%;margin-left:auto">
          <div style="font-size:13px;color:var(--red)">Chat error: ${esc(err.message)}</div>
        </div>`);
    }
  }

}

// β”€β”€ Keyboard shortcut β”€β”€
document.getElementById('problemInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
  if (e.key === 'Enter' && e.shiftKey && e.ctrlKey) {
    e.preventDefault();
    startAnalysis();
  }
});

// β”€β”€ Public entry point: enqueue proactive notification β”€β”€
function initiateProactiveChat(notif) {
  _enqueueChatItem({ type: 'proactive', notif });
}

async function _runInitiateProactiveChat(notif) {
  const conversation = document.getElementById('conversation');
  if (!conversation) return;

  // Remove empty state if present
  const empty = document.getElementById('emptyState');
  if (empty) empty.remove();

  const urgTag = notif.urgency === 'critical'
    ? 'β  CRITICAL'
    : 'β΅ IMPORTANT';

  // Show what was detected (system context bubble)
  conversation.insertAdjacentHTML('beforeend', `
    <div class="chat-message" style="margin:8px 0;padding:10px 16px;background:rgba(255,215,64,0.04);border-radius:10px;border-left:3px solid rgba(255,215,64,0.4);max-width:90%">
      <div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">π“΅ Pattern Detected Β· ${esc(urgTag)} Β· ${new Date().toLocaleTimeString()}</div>
      <div style="font-size:13px;color:var(--text-secondary);line-height:1.4">${esc(notif.headline || 'Emergent pattern detected')}</div>
      ${notif.reason ? `<div style="font-size:11px;color:var(--text-dim);margin-top:4px;font-style:italic">${esc(notif.reason)}</div>` : ''}
    </div>`);

  // Show thinking indicator
  const thinkingId = 'proactive-thinking-' + Date.now();
  conversation.insertAdjacentHTML('beforeend', `
    <div id="${thinkingId}" class="chat-message chat-thinking" style="margin:8px 0;padding:10px 16px;max-width:85%;margin-left:auto">
      <div style="font-size:12px;color:#64b5f6;font-style:italic">Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ is analyzing the pattern...</div>
    </div>`);
  conversation.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'end' });

  // Build a message for Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ with all the pattern data
  const isVisualArrival = notif.raw_data?.trigger === 'visual_perception_arrival'
    || notif.source === 'conversation_request' && (notif.headline || '').includes('Ξ­Ο†Ο„Ξ±ΟƒΞµ');

  const instruction = isVisualArrival
    ? 'Ξ§Ξ±ΞΉΟΞ­Ο„Ξ·ΟƒΞµ Ο†Ο…ΟƒΞΉΞΏΞ»ΞΏΞ³ΞΉΞΊΞ¬ Ξ±Ξ½Ξ¬Ξ»ΞΏΞ³Ξ± Ο„Ξ·Ξ½ ΟΟΞ± (ΞΊΞ±Ξ»Ξ·ΞΌΞ­ΟΞ±/ΞΊΞ±Ξ»Ξ·ΟƒΟ€Ξ­ΟΞ±/Ξ³ΞµΞΉΞ±). ΞΞ―Ξ»Ξ± ΟƒΟ„Ξ± ΞµΞ»Ξ»Ξ·Ξ½ΞΉΞΊΞ¬. Ξ‘Ξ½ ΟƒΟ„ΞΏ reason Ξ±Ξ½Ξ±Ο†Ξ­ΟΞµΟ„Ξ±ΞΉ ΞΊΞ¬Ο„ΞΉ Ο€ΞΏΟ… Ξ±Ξ½Ξ­Ξ»Ο…ΟƒΞµΟ‚ Ο€ΟΟΟƒΟ†Ξ±Ο„Ξ±, Ο€ΞµΟ‚ Ο„ΞΏΟ… Ο†Ο…ΟƒΞΉΞΊΞ¬: Β«Ξ²ΟΞ®ΞΊΞ± ΞΊΞ¬Ο„ΞΉ ΞµΞ½Ξ΄ΞΉΞ±Ο†Ξ­ΟΞΏΞ½Β» Ξ® Β«ΟƒΞΊΞ­Ο†Ο„Ξ·ΞΊΞ± ΞΊΞ¬Ο„ΞΉ Ο€ΞΏΟ… ΞΌΟ€ΞΏΟΞµΞ― Ξ½Ξ± ΟƒΞµ ΞµΞ½Ξ΄ΞΉΞ±Ο†Ξ­ΟΞµΞΉΒ». ΞΞ·Ξ½ ΞΊΞ¬Ξ½ΞµΞΉΟ‚ formal analysis β€” ΞΌΞ―Ξ»Ξ± ΟƒΞ±Ξ½ Ξ½Ξ± Ο„ΞΏΟ… Ξ»ΞµΟ‚ ΞΊΞ¬Ο„ΞΉ ΟƒΞµ ΞΊΞΏΟ…Ξ²Ξ­Ξ½Ο„Ξ±.'
    : 'Analyze this finding. Explain what you see, what it means strategically,\nand what Ξ Ξ¬Ξ½ΞΏΟ‚ should watch for. Be direct and analytical.';

  const proactiveMsg = [
    `[PROACTIVE ALERT β€” ${notif.urgency?.toUpperCase()}]`,
    `Headline: ${notif.headline || 'Unknown'}`,
    notif.summary ? `Summary: ${notif.summary}` : '',
    notif.reason ? `Reason: ${notif.reason}` : '',
    `Source: ${notif.source || 'pattern_accumulator'}`,
    '',
    instruction,
  ].filter(Boolean).join('\n');

  chatHistory.push({ role: 'user', content: proactiveMsg });

  // β”€β”€ Stop any previous TTS and start streaming TTS for proactive message β”€β”€
  stopSpeaking();
  let myGen = 0;
  if (_voiceAutoPlay && _voiceEnabled) {
    myGen = startStreamingTTS();
  }

  // Streaming response container
  const responseId = 'proactive-stream-' + Date.now();
  let responseDiv = null;
  let responseTextEl = null;
  let streamedText = '';

  try {
    // β•β•β• SSE Streaming (same as sendChat) β€” voice starts as text arrives β•β•β•
    const res = await fetch(`${API_BASE}/xdart/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: proactiveMsg,
        history: chatHistory.slice(-20),
        proactive: true,
      }),
    });

    if (!res.ok || !res.body) throw new Error(`Stream error: ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let sseBuffer = '';
    let currentEvent = 'message';
    let gotDone = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      sseBuffer += decoder.decode(value, { stream: true });

      const lines = sseBuffer.split('\n');
      sseBuffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.substring(6).trim();
          continue;
        }
        if (!line.startsWith('data:')) continue;

        let data;
        try { data = JSON.parse(line.substring(5).trim()); } catch { continue; }

        if (currentEvent === 'chunk') {
          const chunkText = data.text || '';
          streamedText += chunkText;

          // Create response bubble on first chunk
          if (!responseDiv) {
            const thinkEl = document.getElementById(thinkingId);
            if (thinkEl) thinkEl.remove();

            conversation.insertAdjacentHTML('beforeend', `
              <div id="${responseId}" class="chat-message chat-assistant" style="margin:8px 0;padding:12px 16px;background:rgba(100,181,246,0.06);border-radius:10px;border-left:3px solid #64b5f6;max-width:85%;margin-left:auto">
                <div style="font-size:11px;color:#64b5f6;margin-bottom:4px">Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ Β· Proactive Analysis</div>
                <div id="${responseId}-text" style="font-size:14px;color:var(--text-primary);line-height:1.6;white-space:pre-wrap"></div>
              </div>`);
            responseDiv = document.getElementById(responseId);
            responseTextEl = document.getElementById(`${responseId}-text`);
          }

          responseTextEl.textContent = _stripInternalTags(streamedText);
          responseDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });

          // Feed cleaned chunks to streaming TTS
          const cleanChunk = _stripInternalTags(chunkText);
          if (cleanChunk && myGen) feedStreamingTTS(cleanChunk, myGen);
        }

        else if (currentEvent === 'done') {
          gotDone = true;
          const finalText = _stripInternalTags(data.full_text || streamedText);
          if (responseTextEl) responseTextEl.textContent = finalText;

          chatHistory.push({ role: 'assistant', content: finalText });

          // Signal end of streaming TTS
          if (myGen) endStreamingTTS(myGen);
        }

        else if (currentEvent === 'pipeline') {
          // Proactive messages sometimes trigger pipeline β€” ignore for now
        }

        currentEvent = 'message';
      }
      // Exit as soon as done event is processed β€” don't wait for TCP close
      if (gotDone) break;
    }

    if (!gotDone && streamedText) {
      chatHistory.push({ role: 'assistant', content: streamedText });
    }

    // Remove thinking indicator if still present
    const thinkEl = document.getElementById(thinkingId);
    if (thinkEl) thinkEl.remove();

    console.log('[Proactive] Streaming conversation completed:', notif.headline);

  } catch (err) {
    // Fallback: non-streaming endpoint
    console.warn('[Proactive] Stream failed, falling back:', err.message);
    try {
      const res = await fetch(`${API_BASE}/xdart/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: proactiveMsg,
          history: chatHistory.slice(-20),
          proactive: true,
        }),
      });
      if (!res.ok) {
        const errText = await res.text().catch(() => `HTTP ${res.status}`);
        throw new Error(errText.substring(0, 120));
      }
      const data = await res.json();

      const thinkEl = document.getElementById(thinkingId);
      if (thinkEl) thinkEl.remove();

      const response = _stripInternalTags(data.response || data.reasoning || 'Could not analyze at this time.');
      chatHistory.push({ role: 'assistant', content: response });

      conversation.insertAdjacentHTML('beforeend', `
        <div class="chat-message chat-assistant" style="margin:8px 0;padding:12px 16px;background:rgba(100,181,246,0.06);border-radius:10px;border-left:3px solid #64b5f6;max-width:85%;margin-left:auto">
          <div style="font-size:11px;color:#64b5f6;margin-bottom:4px">Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ Β· Proactive Analysis</div>
          <div style="font-size:14px;color:var(--text-primary);line-height:1.6;white-space:pre-wrap">${esc(response)}</div>
        </div>`);
      conversation.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'end' });

      autoSpeak(response);
    } catch (fallbackErr) {
      const thinkEl = document.getElementById(thinkingId);
      if (thinkEl) thinkEl.remove();

      conversation.insertAdjacentHTML('beforeend', `
        <div class="chat-message" style="margin:8px 0;padding:10px 16px;border-left:3px solid var(--red);max-width:85%;margin-left:auto">
          <div style="font-size:13px;color:var(--red)">Proactive analysis failed: ${esc(fallbackErr.message)}</div>
        </div>`);
    }
  }
}

// β”€β”€ Self-Prompt Watcher β”€β”€
let lastKnownSelfPrompt = '';

async function checkSelfPromptUpdate(conversation) {
  try {
    // Wait a moment for the self-reflection to complete (it runs after the chat response)
    await new Promise(r => setTimeout(r, 8000));
    const res = await fetch(`${API_BASE}/xdart/self-prompt`);
    const data = await res.json();
    if (data.self_prompt && data.self_prompt !== lastKnownSelfPrompt) {
      lastKnownSelfPrompt = data.self_prompt;
      // Show subtle notification in chat
      conversation.insertAdjacentHTML('beforeend', `
        <div class="chat-message" style="margin:8px 0;padding:8px 14px;background:rgba(128,203,196,0.06);border-radius:8px;border-left:3px solid #80cbc4;max-width:85%;margin-left:auto">
          <div style="font-size:11px;color:#80cbc4;margin-bottom:2px">Self-Prompt Updated</div>
          <div style="font-size:12px;color:var(--text-dim);line-height:1.4">${esc(data.self_prompt.substring(0, 200))}${data.self_prompt.length > 200 ? '...' : ''}</div>
          <div style="font-size:10px;color:var(--text-dim);margin-top:4px;opacity:0.6">The AI rewrote its own identity description based on this conversation.</div>
        </div>`);
      conversation.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  } catch (e) { /* non-critical */ }
}

// Load initial self-prompt state
(async function() {
  try {
    const res = await fetch(`${API_BASE}/xdart/self-prompt`);
    const data = await res.json();
    lastKnownSelfPrompt = data.self_prompt || '';
  } catch (e) { /* ignore */ }
})();

// Load initial self-prompt state
(async function() {
  try {
    const res = await fetch(`${API_BASE}/xdart/self-prompt`);
    const data = await res.json();
    lastKnownSelfPrompt = data.self_prompt || '';
  } catch (e) { /* ignore */ }
})();

// β”€β”€ Self-Awareness Dashboard (Ξ±Ο…Ο„ΞΏΞ³Ξ½Ο‰ΟƒΞ―Ξ± / Ξ±Ο…Ο„ΞΏΞµΞΎΞ­Ξ»ΞΉΞΎΞ· / ΟƒΞΏΟ†Ξ―Ξ±) β”€β”€
let saOpen = false;
let activeSaTab = 'introspection';
let saData = { introspection: null, evolution: null, wisdom: null };

function toggleSelfAwareness() {
  saOpen = !saOpen;
  document.getElementById('saPanel').classList.toggle('open', saOpen);
  document.getElementById('saOverlay').classList.toggle('visible', saOpen);
  if (saOpen && !saData.introspection) loadSelfAwareness();
}

async function loadSelfAwareness() {
  const content = document.getElementById('saContent');
  content.innerHTML = '<div class="kb-loading"><div class="spinner"></div><br>Loading...</div>';
  try {
    const [introRes, evoRes, wisdomRes] = await Promise.all([
      fetch(`${API_BASE}/xdart/introspection`),
      fetch(`${API_BASE}/xdart/self-evolution`),
      fetch(`${API_BASE}/xdart/wisdom`),
    ]);
    saData.introspection = await introRes.json();
    saData.evolution = await evoRes.json();
    saData.wisdom = await wisdomRes.json();
    updateSaBadge();
    renderSaTab(activeSaTab);
  } catch (err) {
    content.innerHTML = `<div class="kb-empty">Cannot load self-awareness data.<br><span style="font-size:11px">${esc(err.message)}</span></div>`;
  }
}

function updateSaBadge() {
  const badge = document.getElementById('saCountBadge');
  const wi = saData.wisdom?.wisdom_index?.wisdom_index;
  if (wi != null) {
    badge.textContent = `${(wi * 100).toFixed(0)}%`;
  } else {
    const n = saData.introspection?.total_reports || 0;
    badge.textContent = n > 0 ? n : 'β€”';
  }
}

function switchSaTab(tab, btn) {
  activeSaTab = tab;
  document.querySelectorAll('#saPanel .kb-tab').forEach(t => t.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderSaTab(tab);
}

function renderSaTab(tab) {
  const c = document.getElementById('saContent');
  if (tab === 'introspection') renderIntrospectionTab(c);
  else if (tab === 'evolution') renderEvolutionTab(c);
  else if (tab === 'wisdom') renderWisdomTab(c);
}

function renderIntrospectionTab(c) {
  const d = saData.introspection;
  if (!d) { c.innerHTML = '<div class="kb-empty">No data</div>'; return; }

  let html = `<div style="padding:16px">
    <div style="display:flex;gap:12px;margin-bottom:16px">
      <div style="flex:1;background:rgba(128,203,196,0.06);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:24px;color:#80cbc4;font-weight:600">${d.avg_integrity.toFixed(2)}</div>
        <div style="font-size:11px;color:var(--text-dim)">Avg Integrity</div>
      </div>
      <div style="flex:1;background:rgba(128,203,196,0.06);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:24px;color:#80cbc4;font-weight:600">${d.total_reports}</div>
        <div style="font-size:11px;color:var(--text-dim)">Total Reports</div>
      </div>
      <div style="flex:1;background:rgba(128,203,196,0.06);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:24px;color:#e57373;font-weight:600">${d.failure_patterns.length}</div>
        <div style="font-size:11px;color:var(--text-dim)">Failure Patterns</div>
      </div>
    </div>`;

  if (d.failure_patterns.length > 0) {
    html += `<div style="margin-bottom:16px"><div style="font-size:12px;font-weight:600;color:#e57373;margin-bottom:6px">β  Failure Patterns Detected</div>`;
    d.failure_patterns.forEach(fp => {
      html += `<div style="font-size:11px;color:var(--text-dim);padding:4px 8px;background:rgba(229,115,115,0.05);border-radius:4px;margin-bottom:4px;border-left:2px solid #e57373">${esc(fp)}</div>`;
    });
    html += '</div>';
  }

  html += '<div style="font-size:12px;font-weight:600;color:#80cbc4;margin-bottom:8px">Recent Reports</div>';
  const reports = (d.recent_reports || []).slice().reverse();
  if (reports.length === 0) {
    html += '<div style="font-size:12px;color:var(--text-dim)">No introspection reports yet. Chat or run pipeline to generate.</div>';
  }
  reports.forEach(r => {
    const meta = r._meta || {};
    const integ = r.epistemic_integrity_score ?? '?';
    const integColor = integ >= 0.8 ? '#80cbc4' : integ >= 0.6 ? '#ffb74d' : '#e57373';
    const obs = r.self_observations || {};
    html += `<div style="padding:10px 12px;background:rgba(255,255,255,0.02);border-radius:6px;margin-bottom:8px;border-left:3px solid ${integColor}">
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <span style="font-size:11px;color:var(--text-dim)">${meta.type || '?'} β€” ${(meta.timestamp || '').substring(0,16)}</span>
        <span style="font-size:13px;font-weight:600;color:${integColor}">${typeof integ === 'number' ? integ.toFixed(2) : integ}</span>
      </div>
      ${obs.what_went_well ? `<div style="font-size:11px;color:var(--text-dim)">β“ ${esc(obs.what_went_well)}</div>` : ''}
      ${obs.what_could_improve ? `<div style="font-size:11px;color:#ffb74d">β†‘ ${esc(obs.what_could_improve)}</div>` : ''}
      ${obs.failure_mode_detected && obs.failure_mode_detected !== 'null' ? `<div style="font-size:11px;color:#e57373">β  ${esc(obs.failure_mode_detected)}</div>` : ''}
    </div>`;
  });
  html += '</div>';
  c.innerHTML = html;
}

function renderEvolutionTab(c) {
  const d = saData.evolution;
  if (!d) { c.innerHTML = '<div class="kb-empty">No data</div>'; return; }

  const stats = d.stats || {};
  let html = `<div style="padding:16px">
    <div style="display:flex;gap:12px;margin-bottom:16px">
      <div style="flex:1;background:rgba(128,203,196,0.06);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:24px;color:#80cbc4;font-weight:600">${stats.total_diagnoses || 0}</div>
        <div style="font-size:11px;color:var(--text-dim)">Diagnoses Run</div>
      </div>
      <div style="flex:1;background:rgba(128,203,196,0.06);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:24px;color:#ffb74d;font-weight:600">${stats.issues_found || 0}</div>
        <div style="font-size:11px;color:var(--text-dim)">Issues Found</div>
      </div>
      <div style="flex:1;background:rgba(128,203,196,0.06);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:24px;color:#80cbc4;font-weight:600">${stats.proposals || 0}</div>
        <div style="font-size:11px;color:var(--text-dim)">Proposals</div>
      </div>
    </div>`;

  const proposals = d.active_proposals || [];
  if (proposals.length > 0) {
    html += '<div style="font-size:12px;font-weight:600;color:#ffb74d;margin-bottom:8px">Active Proposals</div>';
    proposals.forEach(p => {
      const prop = p.proposal || {};
      html += `<div style="padding:10px 12px;background:rgba(255,183,77,0.04);border-radius:6px;margin-bottom:8px;border-left:3px solid #ffb74d">
        <div style="font-size:12px;color:var(--text-primary);font-weight:500;margin-bottom:4px">${esc(prop.description || 'No description')}</div>
        <div style="font-size:11px;color:var(--text-dim)">Target: ${esc(prop.target || '?')} | Type: ${esc(prop.type || '?')}</div>
        <div style="font-size:11px;color:var(--text-dim)">Expected: ${esc(prop.expected_improvement || '?')}</div>
        <div style="font-size:11px;color:#e57373">Risk: ${esc(prop.risk || '?')}</div>
        <div style="font-size:10px;color:var(--text-dim);margin-top:4px">Pattern: ${esc(p.pattern || '?')} | Confidence: ${(p.confidence * 100).toFixed(0)}%</div>
      </div>`;
    });
  } else {
    html += '<div style="font-size:12px;color:var(--text-dim)">No active proposals. The system will generate evolution proposals after detecting recurring patterns across multiple interactions.</div>';
  }
  html += '</div>';
  c.innerHTML = html;
}

function renderWisdomTab(c) {
  const d = saData.wisdom;
  if (!d) { c.innerHTML = '<div class="kb-empty">No data</div>'; return; }

  const wi = d.wisdom_index || {};
  const dp = wi.data_points || {};
  const wisdomVal = wi.wisdom_index;
  const wisdomColor = wisdomVal == null ? 'var(--text-dim)' : wisdomVal >= 0.7 ? '#80cbc4' : wisdomVal >= 0.5 ? '#ffb74d' : '#e57373';

  let html = `<div style="padding:16px">
    <div style="text-align:center;margin-bottom:20px">
      <div style="font-size:36px;font-weight:700;color:${wisdomColor}">${wisdomVal != null ? (wisdomVal * 100).toFixed(1) + '%' : 'β€”'}</div>
      <div style="font-size:13px;color:var(--text-dim)">Composite Wisdom Index</div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px">
      <div style="background:rgba(128,203,196,0.06);border-radius:6px;padding:10px;text-align:center">
        <div style="font-size:16px;color:#80cbc4">${wi.avg_integrity != null ? wi.avg_integrity.toFixed(3) : 'β€”'}</div>
        <div style="font-size:10px;color:var(--text-dim)">Avg Integrity</div>
      </div>
      <div style="background:rgba(128,203,196,0.06);border-radius:6px;padding:10px;text-align:center">
        <div style="font-size:16px;color:#80cbc4">${wi.calibration_error != null ? wi.calibration_error.toFixed(3) : 'β€”'}</div>
        <div style="font-size:10px;color:var(--text-dim)">Calibration Error</div>
      </div>
      <div style="background:rgba(128,203,196,0.06);border-radius:6px;padding:10px;text-align:center">
        <div style="font-size:16px;color:#80cbc4">${wi.avg_brier != null ? wi.avg_brier.toFixed(3) : 'β€”'}</div>
        <div style="font-size:10px;color:var(--text-dim)">Avg Brier Score</div>
      </div>
      <div style="background:rgba(128,203,196,0.06);border-radius:6px;padding:10px;text-align:center">
        <div style="font-size:16px;color:#80cbc4">${wi.humility_ratio != null ? (wi.humility_ratio * 100).toFixed(0) + '%' : 'β€”'}</div>
        <div style="font-size:10px;color:var(--text-dim)">Humility Ratio</div>
      </div>
    </div>
    <div style="display:flex;gap:12px;margin-bottom:16px">
      <div style="flex:1;text-align:center;font-size:11px;color:var(--text-dim)">
        <span style="font-size:18px;color:#80cbc4;display:block">${dp.total_claims || 0}</span>Claims Tracked
      </div>
      <div style="flex:1;text-align:center;font-size:11px;color:var(--text-dim)">
        <span style="font-size:18px;color:#80cbc4;display:block">${dp.resolved_claims || 0}</span>Claims Resolved
      </div>
      <div style="flex:1;text-align:center;font-size:11px;color:var(--text-dim)">
        <span style="font-size:18px;color:#80cbc4;display:block">${dp.integrity_samples || 0}</span>Integrity Samples
      </div>
    </div>`;

  html += `<div style="font-size:12px;font-weight:600;color:#80cbc4;margin-bottom:8px">Calibration Report</div>
    <pre style="font-size:11px;color:var(--text-dim);background:rgba(0,0,0,0.2);padding:10px;border-radius:6px;white-space:pre-wrap;font-family:monospace">${esc(d.calibration_report || 'No data yet')}</pre>
  </div>`;
  c.innerHTML = html;
}

// Load self-awareness badge on startup
(async function() {
  try {
    const res = await fetch(`${API_BASE}/xdart/wisdom`);
    const data = await res.json();
    const wi = data.wisdom_index?.wisdom_index;
    const badge = document.getElementById('saCountBadge');
    if (wi != null) {
      badge.textContent = `${(wi * 100).toFixed(0)}%`;
    }
  } catch (e) { /* ignore */ }
})();

// β”€β”€ Knowledge Dashboard β”€β”€
let kbData = null;
let kbOpen = false;
let activeKbTab = 'overview';

function toggleKnowledge() {
  kbOpen = !kbOpen;
  document.getElementById('kbPanel').classList.toggle('open', kbOpen);
  document.getElementById('kbOverlay').classList.toggle('visible', kbOpen);
  if (kbOpen && !kbData) loadKnowledge();
}

async function loadKnowledge() {
  const content = document.getElementById('kbContent');
  content.innerHTML = '<div class="kb-loading"><div class="spinner"></div><br>Loading knowledge...</div>';
  try {
    const res = await fetch(`${API_BASE}/xdart/knowledge`);
    kbData = await res.json();
    updateKbCounts();
    renderKbTab(activeKbTab);
  } catch (err) {
    content.innerHTML = `<div class="kb-empty">Cannot connect to backend.<br><span style="font-size:11px">${esc(err.message)}</span></div>`;
  }
}

function updateKbCounts() {
  if (!kbData) return;
  const evCount = (kbData.perception?.events || []).length;
  const indCount = (kbData.perception?.indicators || []).length;
  const cCount = kbData.concepts?.count || 0;
  const mCount = kbData.memories?.count || 0;
  const total = evCount + indCount + cCount + mCount;

  document.getElementById('kbCountBadge').textContent = total;
  document.getElementById('tabCountEvents').textContent = evCount ? ` (${evCount})` : '';
  document.getElementById('tabCountIndicators').textContent = indCount ? ` (${indCount})` : '';
  document.getElementById('tabCountConcepts').textContent = cCount ? ` (${cCount})` : '';
  document.getElementById('tabCountMemories').textContent = mCount ? ` (${mCount})` : '';
}

function switchKbTab(tab, btn) {
  activeKbTab = tab;
  document.querySelectorAll('.kb-tab').forEach(t => t.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderKbTab(tab);
}

function renderKbTab(tab) {
  if (!kbData) return;
  const content = document.getElementById('kbContent');

  switch (tab) {
    case 'overview': content.innerHTML = renderOverview(); break;
    case 'perception': content.innerHTML = renderPerception(); break;
    case 'indicators': content.innerHTML = renderIndicators(); break;
    case 'concepts': content.innerHTML = renderConcepts(); break;
    case 'memories': content.innerHTML = renderMemories(); break;
    case 'identity': content.innerHTML = renderIdentity(); break;
  }
}

function renderOverview() {
  const p = kbData.perception || {};
  const evCount = p.enabled ? (p.total_events || 0) : 0;
  const indCount = p.enabled ? (p.total_economic || 0) : 0;
  const cCount = kbData.concepts?.count || 0;
  const mCount = kbData.memories?.count || 0;
  const charV = kbData.character?.version || 0;
  const tensionCount = kbData.character?.tensions_count || 0;
  const recentRuns = kbData.immediate_memory?.recent_runs || [];

  let html = `
    <div class="kb-stats">
      <div class="kb-stat"><div class="stat-num">${evCount}</div><div class="stat-label">World Events</div></div>
      <div class="kb-stat"><div class="stat-num">${indCount}</div><div class="stat-label">Indicators</div></div>
      <div class="kb-stat"><div class="stat-num">${cCount}</div><div class="stat-label">Concepts</div></div>
      <div class="kb-stat"><div class="stat-num">${mCount}</div><div class="stat-label">Memories</div></div>
    </div>
    <div class="kb-stats">
      <div class="kb-stat"><div class="stat-num">v${charV}</div><div class="stat-label">Character</div></div>
      <div class="kb-stat"><div class="stat-num">${tensionCount}</div><div class="stat-label">Tensions</div></div>
      <div class="kb-stat"><div class="stat-num">${recentRuns.length}</div><div class="stat-label">Recent Runs</div></div>
    </div>`;

  if (!p.enabled) {
    html += `<div class="kb-empty" style="padding:16px">β  Perception layer is disabled</div>`;
  }

  // Recent runs
  if (recentRuns.length > 0) {
    html += `<div class="kb-section-title" style="margin-top:16px">Recent Runs</div>`;
    recentRuns.slice().reverse().forEach(r => {
      html += `<div class="kb-run">
        <div class="r-problem">${esc((r.problem || '').slice(0, 120))}</div>
        <div class="r-distillate">${esc((r.distillate || '').slice(0, 200))}</div>
        ${r.concept_born ? `<div class="r-concept">+ ${esc(r.concept_born)}</div>` : ''}
      </div>`;
    });
  }

  html += `<div style="text-align:center;margin-top:20px"><button class="kb-toggle" onclick="loadKnowledge()" style="font-size:11px;padding:4px 12px">β†» Refresh</button></div>`;
  return html;
}

function renderPerception() {
  const p = kbData.perception || {};
  if (!p.enabled) return '<div class="kb-empty">Perception layer is disabled</div>';

  const events = p.events || [];
  if (!events.length) return '<div class="kb-empty">No world events collected yet.<br>Events appear after the collector runs.</div>';

  let html = `<div class="kb-section-title">π World Events β€” last 72h (${events.length} shown / ${p.total_events} total)</div>`;
  events.forEach(e => {
    html += `<div class="kb-event ${esc(e.domain)}">
      <div class="ev-headline">${esc(e.headline)}</div>
      <div class="ev-meta">
        <span class="ev-tag">${esc(e.content_type)}</span>
        <span>${esc(e.source)}</span>
        <span>${esc(e.domain)}</span>
        <span>salience: ${(e.salience || 0).toFixed(2)}</span>
      </div>
    </div>`;
  });
  return html;
}

function renderIndicators() {
  const p = kbData.perception || {};
  if (!p.enabled) return '<div class="kb-empty">Perception layer is disabled</div>';

  const indicators = p.indicators || [];
  if (!indicators.length) return '<div class="kb-empty">No economic indicators collected yet.</div>';

  let html = `<div class="kb-section-title">π“ Economic Indicators (${indicators.length})</div>`;
  indicators.forEach(ind => {
    const val = ind.value != null ? Number(ind.value).toFixed(4) : 'β€”';
    let changeHtml = '';
    if (ind.change_pct != null) {
      const cls = ind.change_pct > 0 ? 'up' : 'down';
      const arrow = ind.change_pct > 0 ? 'β†‘' : 'β†“';
      changeHtml = `<span class="ind-change ${cls}">${arrow}${Math.abs(ind.change_pct).toFixed(2)}%</span>`;
    }
    html += `<div class="kb-indicator">
      <div>
        <div class="ind-name">${esc(ind.indicator)}</div>
        <div class="ind-source">${esc(ind.source)} Β· ${esc(ind.period)}</div>
      </div>
      <div>
        <span class="ind-value">${val} ${esc(ind.unit || '')}</span>
        ${changeHtml}
      </div>
    </div>`;
  });
  return html;
}

function renderConcepts() {
  const concepts = kbData.concepts?.entries || [];
  if (!concepts.length) return '<div class="kb-empty">No concepts in registry yet.<br>Concepts are born during reasoning runs.</div>';

  let html = `<div class="kb-section-title">π§  Concept Registry (${concepts.length})</div>`;
  concepts.forEach(c => {
    html += `<div class="kb-concept">
      <div><span class="c-name">${esc(c.name)}</span><span class="c-type">${esc(c.type)}</span></div>
      <div class="c-insight">${esc(c.key_insight)}</div>
      <div class="c-meta">Uses: ${c.usage_count || 0} Β· Born: ${esc((c.born_at || '').slice(0, 10))}</div>
    </div>`;
  });
  return html;
}

function renderMemories() {
  const memories = kbData.memories?.entries || [];
  if (!memories.length) return '<div class="kb-empty">No episodic memories stored yet.<br>Memories are created after each reasoning run.</div>';

  let html = `<div class="kb-section-title">β Episodic Memories (${memories.length})</div>`;
  memories.forEach(m => {
    const domains = (m.domains || []).join(', ');
    html += `<div class="kb-memory">
      <div class="m-problem">${esc((m.problem || '').slice(0, 150))}</div>
      <div class="m-distillate">${esc((m.distillate || '').slice(0, 300))}</div>
      <div class="m-meta">
        <span>Layer: ${(m.layer_score || 0).toFixed(1)}</span>
        <span>Domains: ${esc(domains) || 'β€”'}</span>
        <span>${esc((m.stored_at || '').slice(0, 10))}</span>
      </div>
    </div>`;
  });
  return html;
}

function renderIdentity() {
  const ch = kbData.character || {};
  const imm = kbData.immediate_memory || {};
  const conceptsOwned = ch.concepts_owned || [];
  const tensions = ch.tensions || [];

  let html = `<div class="kb-section-title">β—‰ Character State (v${ch.version || 0})</div>`;

  // Epistemic stance
  html += `<div class="kb-stance">${esc(ch.epistemic_stance || 'No epistemic stance recorded.')}</div>`;

  // Concepts owned
  if (conceptsOwned.length) {
    html += `<div class="kb-section-title" style="margin-top:16px">Named Concepts Owned (${conceptsOwned.length})</div>`;
    html += `<div class="chip-list" style="margin-bottom:16px">`;
    conceptsOwned.forEach(c => {
      html += `<span class="chip convergent">${esc(c)}</span>`;
    });
    html += `</div>`;
  }

  // Active tensions
  if (tensions.length) {
    html += `<div class="kb-section-title" style="margin-top:16px">Active Tensions (${tensions.length})</div>`;
    tensions.forEach(t => {
      const between = (t.between || []).join(' β†” ');
      html += `<div class="kb-tension">
        <div class="t-between">${esc(between)}</div>
        <div class="t-desc">${esc(t.description || '')}</div>
      </div>`;
    });
  }

  // Changes count
  html += `<div style="font-size:12px;color:var(--text-dim);margin-top:16px;text-align:center">
    ${ch.changes_count || 0} epistemic shifts recorded
  </div>`;

  return html;
}

// Auto-refresh knowledge counts on health check
async function updateKbBadge() {
  try {
    const res = await fetch(`${API_BASE}/xdart/health`);
    const h = await res.json();
    const total = (h.memories || 0) + (h.concepts || 0);
    document.getElementById('kbCountBadge').textContent = total || 'β€”';
  } catch {}
}
updateKbBadge();
setInterval(updateKbBadge, 30000);

// β”€β”€ Intelligence Panel β”€β”€
let intelOpen = false;
let intelData = null;
let intelRefreshTimer = null;

function toggleIntel() {
  intelOpen = !intelOpen;
  document.getElementById('intelPanel').classList.toggle('open', intelOpen);
  document.getElementById('intelOverlay').classList.toggle('visible', intelOpen);
  if (intelOpen) {
    loadIntelligence();
    if (!intelRefreshTimer) intelRefreshTimer = setInterval(loadIntelligence, 60000);
  } else {
    if (intelRefreshTimer) { clearInterval(intelRefreshTimer); intelRefreshTimer = null; }
  }
}

async function loadIntelligence() {
  const body = document.getElementById('intelBody');
  if (!intelData) body.innerHTML = '<div class="intel-empty">Loading intelligenceβ€¦</div>';
  try {
    const res = await fetch(`${API_BASE}/xdart/intelligence`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    intelData = await res.json();
    renderIntelligence();
    updateIntelBadge();
    // Also load economic snapshot (FX, commodities) from briefing endpoint
    loadEconomicSnapshot();
  } catch (err) {
    if (!intelData) body.innerHTML = `<div class="intel-empty">Intelligence unavailable<br><span style="font-size:10px;opacity:0.5">${esc(err.message)}</span></div>`;
  }
}

function updateIntelBadge() {
  const badge = document.getElementById('intelScoreBadge');
  if (intelData && intelData.strategic_risk_score != null) {
    badge.textContent = intelData.strategic_risk_score.toFixed(0);
  }
}

function riskColor(score) {
  if (score >= 60) return 'var(--red)';
  if (score >= 30) return 'var(--gold)';
  return 'var(--green)';
}

function renderIntelligence() {
  if (!intelData) return;
  const d = intelData;
  let html = '';

  // Strategic Risk Gauge
  const riskScore = d.strategic_risk_score || 0;
  const rc = riskColor(riskScore);
  html += `<div class="risk-gauge">
    <div class="rg-score" style="color:${rc}">${riskScore.toFixed(1)}</div>
    <div class="rg-label">Strategic Risk Composite</div>
    <div class="rg-sources">${d.perception_sources || 0} sources Β· ${d.total_events_24h || 0} events (24h)</div>
    <button onclick="downloadBriefing()" class="briefing-btn">π“‹ DAILY BRIEFING</button>
  </div>`;

  // CII Country Risk
  const ciiEntries = Object.entries(d.cii_scores || {})
    .map(([code, info]) => ({code, ...info}))
    .sort((a, b) => b.score - a.score)
    .slice(0, 12);
  if (ciiEntries.length > 0) {
    html += `<div class="intel-section-title">Country Instability Index</div>`;
    ciiEntries.forEach(c => {
      const sc = c.score || 0;
      const cl = riskColor(sc);
      html += `<div class="cii-row">
        <span class="cii-code">${esc(c.code)}</span>
        <span class="cii-name">${esc(c.name || c.code)}</span>
        <div class="cii-bar"><div class="cii-bar-fill" style="width:${Math.min(sc, 100)}%;background:${cl}"></div></div>
        <span class="cii-val" style="color:${cl}">${sc.toFixed(1)}</span>
        <span class="cii-events">${c.event_count || 0} evt</span>
      </div>`;
    });
  }

  // Economic Snapshot (FX + Commodities)
  if (d.economic_snapshot) {
    const snap = d.economic_snapshot;
    // Commodities
    if (snap.commodities && snap.commodities.length > 0) {
      html += `<div class="intel-section-title">Commodities</div>`;
      snap.commodities.forEach(c => {
        html += `<div class="econ-row">
          <span class="econ-label">${esc(c.indicator)}</span>
          <span class="econ-val">$${Number(c.value).toLocaleString(undefined, {maximumFractionDigits: 2})}</span>
          <span class="econ-unit">${esc(c.unit)}</span>
        </div>`;
      });
    }
    // Forex
    if (snap.forex && snap.forex.length > 0) {
      html += `<div class="intel-section-title">Forex (vs USD)</div>`;
      snap.forex.forEach(f => {
        html += `<div class="econ-row">
          <span class="econ-label">${esc(f.indicator)}</span>
          <span class="econ-val">${Number(f.value).toFixed(4)}</span>
        </div>`;
      });
    }
  }

  // Recent Spikes
  const spikes = (d.recent_spikes || []).slice(0, 8);
  if (spikes.length > 0) {
    html += `<div class="intel-section-title">Spike Alerts</div>`;
    spikes.forEach(sp => {
      const ago = sp.detected_at ? timeSince(new Date(sp.detected_at * 1000)) : '';
      html += `<div class="spike-alert">
        <span class="sp-icon">β΅</span>
        <span class="sp-term">${esc(sp.term)}</span>
        <span class="sp-meta">${sp.count}Γ— Β· ${sp.sources} src Β· ${sp.surge_ratio.toFixed(1)}Γ— surge${ago ? ' Β· ' + ago : ''}</span>
      </div>`;
    });
  }

  // Correlation Alerts
  if (d.correlation_alerts && d.correlation_alerts.length > 0) {
    html += `<div class="intel-section-title">Cross-Stream Correlations</div>`;
    d.correlation_alerts.forEach(a => {
      const sevColor = a.severity === 'critical' ? 'var(--red)' : a.severity === 'high' ? '#ff9800' : 'var(--gold)';
      html += `<div class="corr-alert" style="border-left:3px solid ${sevColor}">
        <div class="corr-sev" style="color:${sevColor}">${esc(a.severity.toUpperCase())}</div>
        <div class="corr-summary">${esc(a.summary)}</div>
        <div class="corr-types">${a.signal_types.join(' Β· ')}</div>
      </div>`;
    });
  }

  // Trending Keywords
  const trending = (d.trending_keywords || []).slice(0, 12);
  if (trending.length > 0) {
    html += `<div class="intel-section-title">Trending Terms</div>`;
    trending.forEach((t, i) => {
      html += `<div class="trend-row">
        <span class="tr-rank">${i + 1}.</span>
        <span class="tr-term">${esc(t.term)}</span>
        <span class="tr-count">${t.count}</span>
        <span class="tr-sources">${t.sources} src</span>
      </div>`;
    });
  }

  // Infrastructure Stats
  if (d.infrastructure) {
    const inf = d.infrastructure;
    html += `<div class="intel-section-title">Infrastructure Graph</div>`;
    html += `<div class="infra-stat">
      <div class="is-item"><div class="is-num">${inf.nodes || 0}</div><div class="is-label">Nodes</div></div>
      <div class="is-item"><div class="is-num">${inf.edges || 0}</div><div class="is-label">Dependencies</div></div>
    </div>`;
  }

  // Timestamp
  html += `<div class="intel-ts">${new Date().toISOString().replace('T', ' ').slice(0, 19)} UTC</div>`;

  document.getElementById('intelBody').innerHTML = html;
}

function timeSince(date) {
  const s = Math.floor((Date.now() - date) / 1000);
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

// Download full daily briefing as text
async function downloadBriefing() {
  try {
    const res = await fetch(`${API_BASE}/xdart/briefing`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const briefing = await res.json();

    // Also enrich intelData with economic_snapshot from briefing
    if (briefing.economic_snapshot) {
      intelData.economic_snapshot = briefing.economic_snapshot;
      renderIntelligence();
    }

    // Download narrative as .txt
    const blob = new Blob([briefing.narrative || 'No briefing available'], {type: 'text/plain'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `xdart-briefing-${new Date().toISOString().slice(0,10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert('Briefing unavailable: ' + err.message);
  }
}

// Augment loadIntelligence to also fetch economic data from briefing
async function loadEconomicSnapshot() {
  try {
    const res = await fetch(`${API_BASE}/xdart/briefing`);
    if (!res.ok) return;
    const briefing = await res.json();
    if (briefing.economic_snapshot && intelData) {
      intelData.economic_snapshot = briefing.economic_snapshot;
      if (briefing.correlation_alerts) intelData.correlation_alerts = briefing.correlation_alerts;
      renderIntelligence();
    }
  } catch {}
}

// Background intel badge refresh
async function refreshIntelBadge() {
  try {
    const res = await fetch(`${API_BASE}/xdart/intelligence`);
    if (res.ok) {
      const d = await res.json();
      intelData = d;
      updateIntelBadge();
    }
  } catch {}
}
refreshIntelBadge();
setInterval(refreshIntelBadge, 120000);

// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
//  PROACTIVE NOTIFICATION SYSTEM β€” Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ initiates contact
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•

let _notifSSE = null;
let _notifData = [];
let _notifUnreadCount = 0;
let _notifToastTimeout = null;

// β”€β”€ SSE Connection: persistent listener for real-time notifications β”€β”€
function connectNotificationSSE() {
  if (_notifSSE) { _notifSSE.close(); _notifSSE = null; }

  _notifSSE = new EventSource('/xdart/notifications/stream');

  _notifSSE.addEventListener('connected', (e) => {
    try {
      const d = JSON.parse(e.data);
      _notifUnreadCount = d.unread_count || 0;
      updateNotifBadge();
      console.log('[Proactive] SSE connected, unread:', _notifUnreadCount);
    } catch {}
  });

  _notifSSE.addEventListener('notification', (e) => {
    try {
      const notif = JSON.parse(e.data);
      _notifData.unshift(notif);
      _notifUnreadCount++;
      updateNotifBadge();
      showNotifToast(notif);
      playNotifSound(notif.urgency);
      requestBrowserNotification(notif);
      // If panel is open, refresh it
      if (document.getElementById('notifPanel').classList.contains('visible')) {
        renderNotifPanel();
      }
      // Proactive conversation: send data to Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ and let him respond
      // BUT NOT while the pipeline is running β€” defer until pipeline completes
      if (notif.conversation_start) {
        // Always enqueue β€” queue drains sequentially, even if pipeline is running
        initiateProactiveChat(notif);
        console.log('[Proactive] Enqueued:', notif.headline, `(queue size: ${_chatQueue.length})`);
      }
    } catch (err) {
      console.warn('[Proactive] SSE parse error:', err);
    }
  });

  _notifSSE.addEventListener('heartbeat', (e) => {
    try {
      const d = JSON.parse(e.data);
      _notifUnreadCount = d.unread_count || 0;
      updateNotifBadge();
    } catch {}
  });

  _notifSSE.onerror = () => {
    console.warn('[Proactive] SSE disconnected, reconnecting in 10s...');
    _notifSSE.close();
    _notifSSE = null;
    setTimeout(connectNotificationSSE, 10000);
  };
}

// β”€β”€ Badge Update β”€β”€
function updateNotifBadge() {
  const badge = document.getElementById('notifBadge');
  const btn = document.getElementById('notifToggle');
  if (_notifUnreadCount > 0) {
    badge.textContent = _notifUnreadCount > 99 ? '99+' : _notifUnreadCount;
    badge.classList.remove('hidden');
    btn.classList.add('has-unread');
  } else {
    badge.classList.add('hidden');
    btn.classList.remove('has-unread');
  }
}

// β”€β”€ Panel Toggle β”€β”€
function toggleNotifications() {
  const panel = document.getElementById('notifPanel');
  const overlay = document.getElementById('notifOverlay');
  const isVisible = panel.classList.contains('visible');

  if (isVisible) {
    panel.classList.remove('visible');
    overlay.classList.remove('visible');
  } else {
    panel.classList.add('visible');
    overlay.classList.add('visible');
    fetchAndRenderNotifs();
  }
}

// β”€β”€ Fetch & Render β”€β”€
async function fetchAndRenderNotifs() {
  try {
    const res = await fetch('/xdart/notifications?limit=50');
    if (res.ok) {
      const d = await res.json();
      _notifData = d.notifications || [];
      _notifUnreadCount = d.unread_count || 0;
      updateNotifBadge();
      renderNotifPanel();
    }
  } catch (err) {
    console.warn('[Proactive] Fetch failed:', err);
  }
}

function renderNotifPanel() {
  const body = document.getElementById('notifBody');
  if (!_notifData.length) {
    body.innerHTML = '<div class="notif-empty">No notifications yet. Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ will reach out when he finds something important.</div>';
    return;
  }

  body.innerHTML = _notifData.map(n => {
    const readClass = n.read ? 'read' : 'unread';
    const time = n.created_at ? new Date(n.created_at).toLocaleString('el-GR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
    return `<div class="notif-item ${readClass}" onclick="markNotifRead('${n.id}', this)">
      <span class="notif-urgency ${n.urgency}">${n.urgency}</span>
      <div class="notif-headline">${escH(n.headline)}</div>
      <div class="notif-summary">${escH(n.summary)}</div>
      <div class="notif-meta">
        <span>π“΅ ${escH(n.source)}</span>
        <span>π• ${time}</span>
        ${n.delivered_telegram ? '<span>βοΈ Telegram</span>' : ''}
      </div>
    </div>`;
  }).join('');
}

function escH(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// β”€β”€ Mark Read β”€β”€
async function markNotifRead(id, el) {
  try {
    await fetch('/xdart/notifications/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notification_id: id }),
    });
    if (el) {
      el.classList.remove('unread');
      el.classList.add('read');
    }
    _notifUnreadCount = Math.max(0, _notifUnreadCount - 1);
    updateNotifBadge();
  } catch {}
}

async function markAllNotificationsRead() {
  try {
    await fetch('/xdart/notifications/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    _notifUnreadCount = 0;
    updateNotifBadge();
    document.querySelectorAll('.notif-item.unread').forEach(el => {
      el.classList.remove('unread');
      el.classList.add('read');
    });
  } catch {}
}

// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
//  PATTERN ACCUMULATOR UI
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•

function switchNotifTab(tab) {
  document.querySelectorAll('.notif-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  const notifBody = document.getElementById('notifBody');
  const patternsBody = document.getElementById('patternsBody');
  if (tab === 'patterns') {
    notifBody.classList.add('hidden');
    patternsBody.classList.remove('hidden');
    fetchAndRenderPatterns();
  } else {
    notifBody.classList.remove('hidden');
    patternsBody.classList.add('hidden');
  }
}

async function fetchAndRenderPatterns() {
  const body = document.getElementById('patternsBody');
  try {
    const [patternsRes, statsRes] = await Promise.all([
      fetch('/xdart/patterns?'),
      fetch('/xdart/patterns/stats'),
    ]);
    if (!patternsRes.ok || !statsRes.ok) {
      body.innerHTML = '<div class="notif-empty">Pattern engine not active.</div>';
      return;
    }
    const pData = await patternsRes.json();
    const sData = await statsRes.json();

    if (!pData.active) {
      body.innerHTML = '<div class="notif-empty">Pattern Accumulator not active.</div>';
      return;
    }

    let html = '';

    // Stats bar
    html += `<div class="pattern-stats-bar">
      <div class="pattern-stat"><div class="pattern-stat-val">${sData.total_signals_ingested || 0}</div><div class="pattern-stat-label">Signals</div></div>
      <div class="pattern-stat"><div class="pattern-stat-val">${sData.active_patterns || 0}</div><div class="pattern-stat-label">Active Patterns</div></div>
      <div class="pattern-stat"><div class="pattern-stat-val">${sData.total_fires || 0}</div><div class="pattern-stat-label">Fired</div></div>
    </div>`;

    const patterns = (pData.patterns || []).sort((a, b) => b.convergence_score - a.convergence_score);
    if (!patterns.length) {
      html += '<div class="notif-empty">No active patterns. Signals are being collected...</div>';
      body.innerHTML = html;
      return;
    }

    for (const p of patterns) {
      const pct = Math.round(p.convergence_score * 100);
      const tier = p.fired ? 'fired' : pct >= 50 ? 'hot' : pct >= 30 ? 'warm' : 'low';
      const topics = (p.top_topics || []).slice(0, 10);
      const headlines = (p.headlines || []).slice(0, 5);
      const regions = (p.regions || []).join(', ') || 'GLOBAL';

      html += `<div class="pattern-item">
        <div class="pattern-convergence-bar">
          <div class="pattern-convergence-fill ${tier}" style="width:${pct}%"></div>
        </div>
        <div class="pattern-header">
          <span class="pattern-score ${tier}">${pct}%</span>
          <div class="pattern-meta">
            <span>π”— ${p.signal_count} signals</span>
            <span>π“ ${escH(regions)}</span>
            ${p.fired ? '<span>β… Fired</span>' : ''}
          </div>
        </div>
        <div class="pattern-topics">
          ${topics.map(t => `<span class="pattern-topic">${escH(t)}</span>`).join('')}
        </div>
        ${headlines.length ? `<div class="pattern-headlines">
          ${headlines.map(h => `<div class="pattern-headline-item">β€Ά ${escH(h)}</div>`).join('')}
        </div>` : ''}
      </div>`;
    }

    body.innerHTML = html;
  } catch (err) {
    console.warn('[Patterns] Fetch failed:', err);
    body.innerHTML = '<div class="notif-empty">Failed to load patterns.</div>';
  }
}

// β”€β”€ Toast (popup on new notification) β”€β”€
function showNotifToast(notif) {
  // Remove existing toast
  const existing = document.querySelector('.notif-toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = `notif-toast ${notif.urgency === 'critical' ? 'critical' : ''}`;
  toast.innerHTML = `
    <button class="notif-toast-dismiss" onclick="this.parentElement.remove()">β•</button>
    <div class="notif-toast-headline">π”” ${escH(notif.headline)}</div>
    <div class="notif-toast-summary">${escH(notif.summary)}</div>
  `;
  toast.onclick = (e) => {
    if (e.target.classList.contains('notif-toast-dismiss')) return;
    toast.remove();
    toggleNotifications();
  };
  document.body.appendChild(toast);

  // Auto-dismiss after 15s (critical stays 30s)
  const duration = notif.urgency === 'critical' ? 30000 : 15000;
  setTimeout(() => { if (toast.parentElement) toast.remove(); }, duration);
}

// β”€β”€ Sound Notification β”€β”€
function playNotifSound(urgency) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);

    if (urgency === 'critical') {
      // Urgent double-beep
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.setValueAtTime(0, ctx.currentTime + 0.15);
      osc.frequency.setValueAtTime(880, ctx.currentTime + 0.25);
      gain.gain.setValueAtTime(0.15, ctx.currentTime);
      gain.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.4);
      osc.start();
      osc.stop(ctx.currentTime + 0.45);
    } else {
      // Gentle single tone
      osc.frequency.setValueAtTime(660, ctx.currentTime);
      gain.gain.setValueAtTime(0.08, ctx.currentTime);
      gain.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.3);
      osc.start();
      osc.stop(ctx.currentTime + 0.35);
    }
  } catch {}
}

// β”€β”€ Browser Notification (when tab is in background) β”€β”€
function requestBrowserNotification(notif) {
  if (!('Notification' in window)) return;

  if (Notification.permission === 'default') {
    Notification.requestPermission();
    return;
  }

  if (Notification.permission === 'granted' && document.hidden) {
    new Notification(`Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚: ${notif.headline}`, {
      body: notif.summary?.substring(0, 200),
      icon: '/favicon.ico',
      tag: notif.id,
    });
  }
}

// β”€β”€ Initialize on page load β”€β”€
(function initNotifications() {
  // Request browser notification permission early
  if ('Notification' in window && Notification.permission === 'default') {
    // Will request on first actual notification instead (to avoid annoying prompt)
  }

  // Connect SSE for real-time push
  connectNotificationSSE();

  // Load initial badge count
  fetch('/xdart/notifications/stats').then(r => r.json()).then(d => {
    if (d.active) {
      _notifUnreadCount = d.unread_count || 0;
      updateNotifBadge();
    }
  }).catch(() => {});
})();

// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
//  PROPHECY COMMAND CENTER
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•

let prophecyOpen = false;
let prophecyData = null;
let autonomousData = null;
let accuracyData = null;
let activeProphecyTab = 'active';

function toggleProphecy() {
  prophecyOpen = !prophecyOpen;
  document.getElementById('prophecyPanel').classList.toggle('open', prophecyOpen);
  document.getElementById('prophecyOverlay').classList.toggle('visible', prophecyOpen);
  if (prophecyOpen) loadProphecyData();
}

async function loadProphecyData() {
  const body = document.getElementById('prophecyBody');
  if (!prophecyData) body.innerHTML = '<div class="prop-empty">Loading propheciesβ€¦</div>';
  try {
    const [propRes, autoRes, accRes] = await Promise.all([
      fetch(`${API_BASE}/xdart/prophecies?limit=100`),
      fetch(`${API_BASE}/xdart/prophecies/autonomous`),
      fetch(`${API_BASE}/xdart/accuracy`),
    ]);
    if (propRes.ok) prophecyData = await propRes.json();
    if (autoRes.ok) autonomousData = await autoRes.json();
    if (accRes.ok) accuracyData = await accRes.json();
    updateProphecyBadge();
    renderProphecyTab(activeProphecyTab);
  } catch (err) {
    body.innerHTML = `<div class="prop-empty">Failed to load prophecy data<br><span style="font-size:10px;opacity:0.5">${esc(err.message)}</span></div>`;
  }
}

function updateProphecyBadge() {
  const badge = document.getElementById('propCountBadge');
  const total = (prophecyData?.total || 0);
  const pending = (autonomousData?.count || 0);
  badge.textContent = pending > 0 ? `${pending}!` : (total || 'β€”');
  if (pending > 0) badge.style.background = '#ffd740';

  const ptabActive = document.getElementById('ptabActive');
  const ptabAuto = document.getElementById('ptabAutonomous');
  const ptabResolved = document.getElementById('ptabResolved');
  const prophecies = prophecyData?.prophecies || [];
  const activeCount = prophecies.filter(p => p.tracking_status === 'active' || p.tracking_status === 'tracking').length;
  const resolvedCount = prophecies.filter(p => ['confirmed', 'disconfirmed', 'expired'].includes(p.tracking_status)).length;
  if (ptabActive) ptabActive.textContent = activeCount ? ` (${activeCount})` : '';
  if (ptabAuto) ptabAuto.textContent = pending ? ` (${pending})` : '';
  if (ptabResolved) ptabResolved.textContent = resolvedCount ? ` (${resolvedCount})` : '';
}

function switchProphecyTab(tab, btn) {
  activeProphecyTab = tab;
  document.querySelectorAll('.prophecy-tab').forEach(t => t.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderProphecyTab(tab);
}

function renderProphecyTab(tab) {
  const body = document.getElementById('prophecyBody');
  switch (tab) {
    case 'active': body.innerHTML = renderActiveProphecies(); break;
    case 'autonomous': body.innerHTML = renderAutonomousProphecies(); break;
    case 'accuracy': body.innerHTML = renderAccuracyTab(); break;
    case 'resolved': body.innerHTML = renderResolvedProphecies(); break;
  }
}

function renderActiveProphecies() {
  const prophecies = (prophecyData?.prophecies || [])
    .filter(p => p.tracking_status === 'active' || p.tracking_status === 'tracking')
    .sort((a, b) => (b.scenario?.confidence || 0) - (a.scenario?.confidence || 0));
  if (!prophecies.length) return '<div class="prop-empty">No active prophecies.<br>Run a prophetic analysis to generate predictions.</div>';

  return prophecies.map(p => renderProphecyCard(p)).join('');
}

function renderResolvedProphecies() {
  const prophecies = (prophecyData?.prophecies || [])
    .filter(p => ['confirmed', 'disconfirmed', 'expired'].includes(p.tracking_status))
    .sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));
  if (!prophecies.length) return '<div class="prop-empty">No resolved prophecies yet.</div>';

  return prophecies.map(p => renderProphecyCard(p)).join('');
}

function renderProphecyCard(p) {
  const sc = p.scenario || {};
  const sim = p.simulation || {};
  const conf = sc.confidence || 0;
  const confClass = conf >= 0.7 ? 'high' : conf >= 0.4 ? 'med' : 'low';
  const markers = (sc.falsifiable_markers || []).slice(0, 5);
  const checks = (p.reality_checks || []).slice(0, 3);
  const ts = (p.timestamp || '').substring(0, 16).replace('T', ' ');

  let html = `<div class="prop-card">
    <div class="prop-card-header">
      <div class="prop-name">${esc(sc.name || p.problem || 'Untitled')}</div>
      <span class="prop-status ${esc(p.tracking_status)}">${esc(p.tracking_status)}</span>
    </div>
    <div class="prop-narrative">${esc(sc.narrative || sc.predicted_outcome || '')}</div>
    <div class="prop-meta-row">
      <span>Confidence: <span class="prop-confidence ${confClass}">${(conf * 100).toFixed(0)}%</span></span>
      <span>Tribunal: #${p.tribunal_rank || '?'} (${(p.tribunal_score || 0).toFixed(2)})</span>
      ${sim.robustness_score ? `<span>Robustness: ${(sim.robustness_score * 100).toFixed(0)}%</span>` : ''}
      ${sc.timeframe ? `<span>β± ${esc(sc.timeframe)}</span>` : ''}
      <span>π“… ${ts}</span>
    </div>`;

  if (markers.length) {
    html += `<div class="prop-markers">${markers.map(m => `<span class="prop-marker">${esc(typeof m === 'string' ? m : m.marker || m.description || JSON.stringify(m))}</span>`).join('')}</div>`;
  }

  if (checks.length) {
    html += `<div style="margin-top:6px;font-size:11px;color:var(--text-dim)">
      ${checks.map(c => `<div style="padding:2px 0;border-left:2px solid ${c.result === 'confirmed' ? '#4caf50' : c.result === 'disconfirmed' ? '#f44336' : 'var(--border)'};padding-left:6px;margin-bottom:2px">
        ${esc(c.check || c.description || JSON.stringify(c))}
      </div>`).join('')}
    </div>`;
  }

  html += '</div>';
  return html;
}

function renderAutonomousProphecies() {
  const pending = autonomousData?.pending || [];
  if (!pending.length) return '<div class="prop-empty">No autonomous prophecies pending approval.<br>Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ generates these from detected patterns.</div>';

  return pending.map(p => {
    const sc = p.scenario || {};
    const conf = sc.confidence || 0;
    const confClass = conf >= 0.7 ? 'high' : conf >= 0.4 ? 'med' : 'low';
    const ts = (p.timestamp || '').substring(0, 16).replace('T', ' ');

    return `<div class="prop-card" style="border-color:rgba(255,215,64,0.2)">
      <div class="prop-card-header">
        <div class="prop-name">${esc(sc.name || 'Autonomous Prophecy')}</div>
        <span class="prop-status autonomous_proposed">PENDING</span>
      </div>
      <div class="prop-narrative">${esc(sc.narrative || sc.predicted_outcome || p.trigger_summary || '')}</div>
      <div class="prop-meta-row">
        <span>Confidence: <span class="prop-confidence ${confClass}">${(conf * 100).toFixed(0)}%</span></span>
        ${sc.timeframe ? `<span>β± ${esc(sc.timeframe)}</span>` : ''}
        <span>π“… ${ts}</span>
        ${p.source ? `<span>Source: ${esc(p.source)}</span>` : ''}
      </div>
      ${(sc.falsifiable_markers || []).length ? `<div class="prop-markers">${sc.falsifiable_markers.slice(0, 5).map(m => `<span class="prop-marker">${esc(typeof m === 'string' ? m : m.marker || '')}</span>`).join('')}</div>` : ''}
      <div class="prop-actions">
        <button class="prop-action-btn approve" onclick="approveAutonomousProphecy('${esc(p.id)}')">β“ Approve</button>
        <button class="prop-action-btn reject" onclick="rejectAutonomousProphecy('${esc(p.id)}')">β• Reject</button>
      </div>
    </div>`;
  }).join('');
}

async function approveAutonomousProphecy(id) {
  try {
    const res = await fetch(`${API_BASE}/xdart/prophecies/autonomous/${id}/approve`, { method: 'POST' });
    if (res.ok) {
      await loadProphecyData();
    } else {
      const d = await res.json().catch(() => ({}));
      alert('Approval failed: ' + (d.detail || res.statusText));
    }
  } catch (err) { alert('Error: ' + err.message); }
}

async function rejectAutonomousProphecy(id) {
  try {
    const res = await fetch(`${API_BASE}/xdart/prophecies/autonomous/${id}/reject`, { method: 'POST' });
    if (res.ok) {
      await loadProphecyData();
    } else {
      const d = await res.json().catch(() => ({}));
      alert('Rejection failed: ' + (d.detail || res.statusText));
    }
  } catch (err) { alert('Error: ' + err.message); }
}

function renderAccuracyTab() {
  const d = accuracyData;
  if (!d) return '<div class="prop-empty">No accuracy data available yet.</div>';

  const brier = d.average_brier_score;
  const rating = d.rating || 'unknown';
  const brierColor = brier != null ? (brier < 0.1 ? '#4caf50' : brier < 0.25 ? '#ff9800' : '#f44336') : 'var(--text-dim)';
  const ratingColor = rating === 'excellent' ? '#4caf50' : rating === 'good' ? '#8bc34a' : rating === 'fair' ? '#ff9800' : '#f44336';

  let html = `<div class="accuracy-gauge">
    <div class="ag-score" style="color:${brierColor}">${brier != null ? brier.toFixed(3) : 'β€”'}</div>
    <div class="ag-label">Average Brier Score (lower = better)</div>
    <div class="ag-rating" style="color:${ratingColor}">${rating.toUpperCase()}</div>
  </div>`;

  html += `<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:16px">
    <div style="background:rgba(124,77,255,0.04);border-radius:8px;padding:12px;text-align:center">
      <div style="font-size:22px;font-weight:700;color:#7c4dff;font-family:var(--mono)">${d.total_prophecies || 0}</div>
      <div style="font-size:10px;color:var(--text-dim)">Total Prophecies</div>
    </div>
    <div style="background:rgba(76,175,80,0.04);border-radius:8px;padding:12px;text-align:center">
      <div style="font-size:22px;font-weight:700;color:#4caf50;font-family:var(--mono)">${d.confirmed || 0}</div>
      <div style="font-size:10px;color:var(--text-dim)">Confirmed</div>
    </div>
    <div style="background:rgba(244,67,54,0.04);border-radius:8px;padding:12px;text-align:center">
      <div style="font-size:22px;font-weight:700;color:#f44336;font-family:var(--mono)">${d.disconfirmed || 0}</div>
      <div style="font-size:10px;color:var(--text-dim)">Disconfirmed</div>
    </div>
  </div>`;

  // Per-prophecy scores if available
  const scores = d.per_prophecy_scores || d.prophecy_scores || [];
  if (scores.length) {
    html += `<div style="font-size:10px;color:#7c4dff;text-transform:uppercase;letter-spacing:1.5px;font-weight:700;margin-bottom:8px">Individual Scores</div>`;
    scores.forEach(s => {
      const sb = s.brier_score ?? s.score;
      const sc = sb != null ? (sb < 0.1 ? '#4caf50' : sb < 0.25 ? '#ff9800' : '#f44336') : 'var(--text-dim)';
      html += `<div style="display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:4px;margin-bottom:4px;background:rgba(255,255,255,0.02)">
        <span style="font-family:var(--mono);font-size:13px;font-weight:700;color:${sc};min-width:50px">${sb != null ? sb.toFixed(3) : 'β€”'}</span>
        <span style="font-size:12px;color:var(--text);flex:1">${esc(s.name || s.problem || 'Unknown')}</span>
        <span style="font-size:10px;color:var(--text-dim)">${esc(s.status || '')}</span>
      </div>`;
    });
  }

  html += `<div style="text-align:center;margin-top:16px"><button class="prophecy-close" style="font-size:11px;padding:4px 14px" onclick="loadProphecyData()">β†» Refresh</button></div>`;
  return html;
}

// Background badge refresh
async function refreshProphecyBadge() {
  try {
    const [propRes, autoRes] = await Promise.all([
      fetch(`${API_BASE}/xdart/prophecies?limit=1`),
      fetch(`${API_BASE}/xdart/prophecies/autonomous`),
    ]);
    if (propRes.ok) {
      const d = await propRes.json();
      const badge = document.getElementById('propCountBadge');
      const autoD = autoRes.ok ? await autoRes.json() : { count: 0 };
      const pending = autoD.count || 0;
      badge.textContent = pending > 0 ? `${pending}!` : (d.total || 'β€”');
      if (pending > 0) badge.style.background = '#ffd740';
      else badge.style.background = '#7c4dff';
    }
  } catch {}
}
refreshProphecyBadge();
setInterval(refreshProphecyBadge, 60000);

// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
//  GOVERNANCE HUB
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•

let govOpen = false;
let govPrinciples = null;
let govPending = null;
let govPhilosophy = null;
let govSandbox = null;
let govSandboxProposals = null;
let govStrategies = null;
let activeGovTab = 'principles';

function toggleGovernance() {
  govOpen = !govOpen;
  document.getElementById('govPanel').classList.toggle('open', govOpen);
  document.getElementById('govOverlay').classList.toggle('visible', govOpen);
  if (govOpen) loadGovernanceData();
}

async function loadGovernanceData() {
  const body = document.getElementById('govBody');
  if (!govPrinciples) body.innerHTML = '<div class="gov-empty">Loading governance dataβ€¦</div>';
  try {
    const [princRes, pendRes, philRes, sbRes, sbpRes, stratRes] = await Promise.all([
      fetch(`${API_BASE}/xdart/principles`),
      fetch(`${API_BASE}/xdart/principles/pending`),
      fetch(`${API_BASE}/xdart/principles/philosophy`),
      fetch(`${API_BASE}/xdart/logic-sandbox`),
      fetch(`${API_BASE}/xdart/logic-sandbox/proposals`),
      fetch(`${API_BASE}/xdart/strategies`),
    ]);
    if (princRes.ok) govPrinciples = await princRes.json();
    if (pendRes.ok) govPending = await pendRes.json();
    if (philRes.ok) govPhilosophy = await philRes.json();
    if (sbRes.ok) govSandbox = await sbRes.json();
    if (sbpRes.ok) govSandboxProposals = await sbpRes.json();
    if (stratRes.ok) govStrategies = await stratRes.json();
    updateGovernanceBadge();
    renderGovTab(activeGovTab);
  } catch (err) {
    body.innerHTML = `<div class="gov-empty">Failed to load governance data<br><span style="font-size:10px;opacity:0.5">${esc(err.message)}</span></div>`;
  }
}

function updateGovernanceBadge() {
  const pendingPrinc = govPending?.pending?.length || 0;
  const allSbProposals = govSandboxProposals?.proposals || [];
  const pendingSandbox = allSbProposals.filter(p => p.status === 'pending' || p.status === 'tested').length;
  const total = pendingPrinc + pendingSandbox;
  const badge = document.getElementById('govCountBadge');
  badge.textContent = total > 0 ? `${total}!` : 'β€”';
  if (total > 0) badge.style.background = '#ffd740';
  else badge.style.background = '#ff9800';
}

function switchGovTab(tab, btn) {
  activeGovTab = tab;
  document.querySelectorAll('.gov-tab').forEach(t => t.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderGovTab(tab);
}

function renderGovTab(tab) {
  const body = document.getElementById('govBody');
  switch (tab) {
    case 'principles': body.innerHTML = renderPrinciplesTab(); break;
    case 'sandbox': body.innerHTML = renderSandboxTab(); break;
    case 'strategies': body.innerHTML = renderStrategiesTab(); break;
  }
}

function renderPrinciplesTab() {
  let html = '';

  // Philosophy mode switcher
  const currentMode = govPhilosophy?.active_mode || 'balanced';
  html += `<div class="gov-section-title">Philosophy Mode</div>
  <div class="philosophy-switcher">
    <div class="philosophy-mode ${currentMode === 'balanced' ? 'active-mode' : ''}" onclick="switchPhilosophy('balanced')">
      <span class="pm-icon">β–</span>
      <div class="pm-name">Balanced</div>
      <div class="pm-desc">Default equilibrium</div>
    </div>
    <div class="philosophy-mode ${currentMode === 'conservative' ? 'active-mode' : ''}" onclick="switchPhilosophy('conservative')">
      <span class="pm-icon">π›΅</span>
      <div class="pm-name">Conservative</div>
      <div class="pm-desc">Strict validation</div>
    </div>
    <div class="philosophy-mode ${currentMode === 'exploratory' ? 'active-mode' : ''}" onclick="switchPhilosophy('exploratory')">
      <span class="pm-icon">π”¬</span>
      <div class="pm-name">Exploratory</div>
      <div class="pm-desc">Open discovery</div>
    </div>
  </div>`;

  // Pending principles
  const pending = govPending?.pending || [];
  if (pending.length) {
    html += `<div class="gov-section-title">Pending Approval (${pending.length})</div>`;
    pending.forEach(p => {
      html += `<div class="gov-card" style="border-color:rgba(255,215,64,0.2)">
        <div class="gov-card-title">${esc(p.name || p.id)}</div>
        <div class="gov-card-desc">${esc(p.description || p.text || '')}</div>
        <div class="gov-card-meta">
          ${p.confidence ? `<span>Confidence: ${(p.confidence * 100).toFixed(0)}%</span>` : ''}
          ${p.source ? `<span>Source: ${esc(p.source)}</span>` : ''}
        </div>
        <div class="prop-actions" style="margin-top:8px">
          <button class="prop-action-btn approve" onclick="approvePrinciple('${esc(p.id)}')">β“ Approve</button>
          <button class="prop-action-btn reject" onclick="rejectPrinciple('${esc(p.id)}')">β• Reject</button>
        </div>
      </div>`;
    });
  }

  // Active principles
  const active = govPrinciples?.principles || [];
  html += `<div class="gov-section-title" style="margin-top:16px">Active Principles (${active.length})</div>`;
  if (!active.length) {
    html += '<div class="gov-empty">No active principles yet.</div>';
  } else {
    active.forEach(p => {
      html += `<div class="gov-card">
        <div class="gov-card-title">${esc(p.name || p.id)}</div>
        <div class="gov-card-desc">${esc(p.description || p.text || '')}</div>
        <div class="gov-card-meta">
          ${p.confidence ? `<span>Confidence: ${(p.confidence * 100).toFixed(0)}%</span>` : ''}
          ${p.usage_count != null ? `<span>Uses: ${p.usage_count}</span>` : ''}
          ${p.source ? `<span>Source: ${esc(p.source)}</span>` : ''}
        </div>
      </div>`;
    });
  }

  html += `<div style="text-align:center;margin-top:16px"><button class="gov-close" style="font-size:11px;padding:4px 14px" onclick="loadGovernanceData()">β†» Refresh</button></div>`;
  return html;
}

async function switchPhilosophy(mode) {
  try {
    const res = await fetch(`${API_BASE}/xdart/principles/philosophy/${mode}`, { method: 'POST' });
    if (res.ok) {
      govPhilosophy = await res.json();
      renderGovTab('principles');
    } else {
      const d = await res.json().catch(() => ({}));
      alert('Switch failed: ' + (d.detail || res.statusText));
    }
  } catch (err) { alert('Error: ' + err.message); }
}

async function approvePrinciple(id) {
  try {
    const res = await fetch(`${API_BASE}/xdart/principles/${id}/approve`, { method: 'POST' });
    if (res.ok) await loadGovernanceData();
    else alert('Failed: ' + (await res.json().catch(() => ({}))).detail);
  } catch (err) { alert('Error: ' + err.message); }
}

async function rejectPrinciple(id) {
  try {
    const res = await fetch(`${API_BASE}/xdart/principles/${id}/reject`, { method: 'POST' });
    if (res.ok) await loadGovernanceData();
    else alert('Failed: ' + (await res.json().catch(() => ({}))).detail);
  } catch (err) { alert('Error: ' + err.message); }
}

function renderSandboxTab() {
  let html = '';

  // Pending proposals β€” only show actionable ones (pending/tested)
  const allProposals = govSandboxProposals?.proposals || [];
  const pendingProposals = allProposals.filter(p => p.status === 'pending' || p.status === 'tested');
  const completedProposals = allProposals.filter(p => p.status === 'applied' || p.status === 'rejected' || p.status === 'approved');
  if (pendingProposals.length) {
    html += `<div class="gov-section-title">Pending Proposals (${pendingProposals.length})</div>`;
    pendingProposals.forEach(p => {
      html += `<div class="gov-card" style="border-color:rgba(255,215,64,0.2)">
        <div class="gov-card-title">${esc(p.function_name || p.target || p.id)}</div>
        <div class="gov-card-desc">${esc(p.description || p.rationale || '')}</div>
        <div class="gov-card-meta">
          ${p.confidence ? `<span>Confidence: ${(p.confidence * 100).toFixed(0)}%</span>` : ''}
          ${p.status ? `<span>Status: ${esc(p.status)}</span>` : ''}
          ${p.pattern ? `<span>Pattern: ${esc(p.pattern)}</span>` : ''}
        </div>
        <div class="prop-actions" style="margin-top:8px">
          <button class="prop-action-btn approve" onclick="approveSandboxProposal('${esc(p.id)}')">β“ Approve</button>
          <button class="prop-action-btn reject" onclick="rejectSandboxProposal('${esc(p.id)}')">β• Reject</button>
        </div>
      </div>`;
    });
  }
  if (completedProposals.length) {
    html += `<div class="gov-section-title" style="margin-top:12px">Completed Proposals (${completedProposals.length})</div>`;
    completedProposals.forEach(p => {
      const statusColor = p.status === 'applied' ? '#2ecc71' : p.status === 'rejected' ? '#e74c3c' : '#f39c12';
      html += `<div class="gov-card" style="border-color:${statusColor}33; opacity:0.7">
        <div class="gov-card-title" style="display:flex;justify-content:space-between;align-items:center">
          ${esc(p.function_name || p.target || p.id)}
          <span style="font-size:11px;padding:2px 8px;border-radius:4px;background:${statusColor}22;color:${statusColor}">${esc(p.status.toUpperCase())}</span>
        </div>
        <div class="gov-card-desc" style="font-size:11px">${esc((p.description || p.rationale || '').slice(0, 150))}${(p.description || p.rationale || '').length > 150 ? '...' : ''}</div>
      </div>`;
    });
  }

  // Functions
  const functions = govSandbox?.functions || {};
  const funcList = Object.entries(functions);
  html += `<div class="gov-section-title" style="margin-top:16px">Registered Functions (${funcList.length})</div>`;
  if (!funcList.length) {
    html += '<div class="gov-empty">No sandbox functions registered.</div>';
  } else {
    funcList.forEach(([name, f]) => {
      const modified = f.version > 1 || f.current_code !== f.original_code;
      html += `<div class="sandbox-func" ${modified ? 'style="border-color:rgba(255,152,0,0.3)"' : ''}>
        <div class="sandbox-func-header">
          <span class="sandbox-func-name">${esc(name)}</span>
          <span class="sandbox-func-version">v${f.version || 1}${modified ? ' β΅' : ''}</span>
        </div>
        <div class="sandbox-func-desc">${esc(f.description || '')}</div>
        ${modified ? `<div style="margin-top:6px"><button class="prop-action-btn reject" style="font-size:10px;padding:3px 10px" onclick="rollbackSandboxFunc('${esc(name)}')">β†¶ Rollback</button></div>` : ''}
      </div>`;
    });
  }

  html += `<div style="text-align:center;margin-top:16px"><button class="gov-close" style="font-size:11px;padding:4px 14px" onclick="loadGovernanceData()">β†» Refresh</button></div>`;
  return html;
}

async function approveSandboxProposal(id) {
  try {
    const res = await fetch(`${API_BASE}/xdart/logic-sandbox/proposals/${id}/approve`, { method: 'POST' });
    if (res.ok) await loadGovernanceData();
    else alert('Failed: ' + (await res.json().catch(() => ({}))).detail);
  } catch (err) { alert('Error: ' + err.message); }
}

async function rejectSandboxProposal(id) {
  try {
    const res = await fetch(`${API_BASE}/xdart/logic-sandbox/proposals/${id}/reject`, { method: 'POST' });
    if (res.ok) await loadGovernanceData();
    else alert('Failed: ' + (await res.json().catch(() => ({}))).detail);
  } catch (err) { alert('Error: ' + err.message); }
}

async function rollbackSandboxFunc(name) {
  try {
    const res = await fetch(`${API_BASE}/xdart/logic-sandbox/functions/${name}/rollback`, { method: 'POST' });
    if (res.ok) await loadGovernanceData();
    else alert('Failed: ' + (await res.json().catch(() => ({}))).detail);
  } catch (err) { alert('Error: ' + err.message); }
}

function renderStrategiesTab() {
  const strategies = govStrategies?.strategies || [];
  const stats = govStrategies?.stats || {};
  let html = '';

  html += `<div style="display:flex;gap:12px;margin-bottom:16px">
    <div style="flex:1;background:rgba(255,152,0,0.04);border-radius:8px;padding:12px;text-align:center">
      <div style="font-size:22px;font-weight:700;color:#ff9800;font-family:var(--mono)">${stats.total || strategies.length}</div>
      <div style="font-size:10px;color:var(--text-dim)">Total</div>
    </div>
    <div style="flex:1;background:rgba(76,175,80,0.04);border-radius:8px;padding:12px;text-align:center">
      <div style="font-size:22px;font-weight:700;color:#4caf50;font-family:var(--mono)">${stats.active || strategies.filter(s => s.active !== false).length}</div>
      <div style="font-size:10px;color:var(--text-dim)">Active</div>
    </div>
    <div style="flex:1;background:rgba(244,67,54,0.04);border-radius:8px;padding:12px;text-align:center">
      <div style="font-size:22px;font-weight:700;color:#f44336;font-family:var(--mono)">${stats.inactive || strategies.filter(s => s.active === false).length}</div>
      <div style="font-size:10px;color:var(--text-dim)">Inactive</div>
    </div>
  </div>`;

  if (!strategies.length) {
    html += '<div class="gov-empty">No cognitive strategies registered.</div>';
  } else {
    html += `<div class="gov-section-title">Cognitive Strategies</div>`;
    strategies.forEach(s => {
      const isActive = s.active !== false;
      html += `<div class="gov-card" style="opacity:${isActive ? 1 : 0.5}">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div class="gov-card-title">${esc(s.name || s.id)}</div>
          <span style="font-size:9px;font-weight:700;padding:2px 8px;border-radius:4px;${isActive ? 'background:rgba(76,175,80,0.12);color:#4caf50' : 'background:rgba(244,67,54,0.12);color:#f44336'}">${isActive ? 'ACTIVE' : 'INACTIVE'}</span>
        </div>
        <div class="gov-card-desc">${esc(s.description || '')}</div>
        <div class="gov-card-meta">
          ${s.success_rate != null ? `<span>Success: ${(s.success_rate * 100).toFixed(0)}%</span>` : ''}
          ${s.uses != null ? `<span>Uses: ${s.uses}</span>` : ''}
          ${s.deactivation_reason ? `<span>Reason: ${esc(s.deactivation_reason)}</span>` : ''}
        </div>
        ${isActive ? `<div style="margin-top:6px"><button class="prop-action-btn reject" style="font-size:10px;padding:3px 10px" onclick="deactivateStrategy('${esc(s.id)}')">Deactivate</button></div>` : ''}
      </div>`;
    });
  }

  html += `<div style="text-align:center;margin-top:16px"><button class="gov-close" style="font-size:11px;padding:4px 14px" onclick="loadGovernanceData()">β†» Refresh</button></div>`;
  return html;
}

async function deactivateStrategy(id) {
  try {
    const res = await fetch(`${API_BASE}/xdart/strategies/${id}/deactivate`, { method: 'POST' });
    if (res.ok) await loadGovernanceData();
    else alert('Failed: ' + (await res.json().catch(() => ({}))).detail);
  } catch (err) { alert('Error: ' + err.message); }
}

// Background governance badge refresh
async function refreshGovBadge() {
  try {
    const [pendRes, sbpRes] = await Promise.all([
      fetch(`${API_BASE}/xdart/principles/pending`),
      fetch(`${API_BASE}/xdart/logic-sandbox/proposals`),
    ]);
    let total = 0;
    if (pendRes.ok) { const d = await pendRes.json(); total += (d.pending?.length || 0); }
    if (sbpRes.ok) { const d = await sbpRes.json(); total += (d.proposals?.length || 0); }
    const badge = document.getElementById('govCountBadge');
    badge.textContent = total > 0 ? `${total}!` : 'β€”';
    if (total > 0) badge.style.background = '#ffd740';
    else badge.style.background = '#ff9800';
  } catch {}
}
refreshGovBadge();
setInterval(refreshGovBadge, 90000);

// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
//  KNOWLEDGE INJECTOR
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•

let injectOpen = false;
let injectKnowledgeData = null;

function toggleInject() {
  injectOpen = !injectOpen;
  document.getElementById('injectPanel').classList.toggle('open', injectOpen);
  document.getElementById('injectOverlay').classList.toggle('visible', injectOpen);
  if (injectOpen) loadInjectedKnowledge();
}

async function loadInjectedKnowledge() {
  try {
    const res = await fetch(`${API_BASE}/xdart/knowledge/external`);
    if (res.ok) {
      injectKnowledgeData = await res.json();
      renderInjectedKnowledge();
      updateInjectBadge();
    }
  } catch {}
}

function updateInjectBadge() {
  const badge = document.getElementById('injectCountBadge');
  badge.textContent = injectKnowledgeData?.count || 0;
}

function renderInjectedKnowledge() {
  const container = document.getElementById('injectExistingList');
  const entries = injectKnowledgeData?.entries || [];
  if (!entries.length) {
    container.innerHTML = `<div style="text-align:center;padding:20px;color:var(--text-dim);font-size:12px;font-style:italic">
      No knowledge injected yet. Use the form above to add external knowledge.
    </div>`;
    return;
  }

  let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <span style="font-size:10px;color:#00e676;text-transform:uppercase;letter-spacing:1.5px;font-weight:700">
      Injected Knowledge (${entries.length})
    </span>
    <button class="inject-close" style="font-size:10px;padding:3px 10px;color:#f44336;border-color:rgba(244,67,54,0.2)" onclick="clearAllKnowledge()">Clear All</button>
  </div>`;

  entries.forEach(e => {
    html += `<div class="inject-entry">
      <div class="inject-entry-source">${esc(e.source || 'unknown')}</div>
      <div class="inject-entry-content">${esc((e.content || '').substring(0, 300))}${(e.content || '').length > 300 ? 'β€¦' : ''}</div>
      ${e.injected_at ? `<div class="inject-entry-time">${esc(e.injected_at)}</div>` : ''}
    </div>`;
  });

  container.innerHTML = html;
}

async function submitKnowledgeInjection() {
  const source = document.getElementById('injectSource').value.trim();
  const content = document.getElementById('injectContent').value.trim();
  if (!source || !content) {
    alert('Both Source and Content are required.');
    return;
  }

  const btn = document.getElementById('injectSubmitBtn');
  btn.disabled = true;
  btn.textContent = 'Injectingβ€¦';

  try {
    const res = await fetch(`${API_BASE}/xdart/knowledge/inject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, content }),
    });
    if (res.ok) {
      document.getElementById('injectSource').value = '';
      document.getElementById('injectContent').value = '';
      await loadInjectedKnowledge();
    } else {
      const d = await res.json().catch(() => ({}));
      alert('Injection failed: ' + (d.detail || res.statusText));
    }
  } catch (err) {
    alert('Error: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Inject Knowledge';
  }
}

async function clearAllKnowledge() {
  if (!confirm('Clear all injected knowledge?')) return;
  try {
    const res = await fetch(`${API_BASE}/xdart/knowledge/external`, { method: 'DELETE' });
    if (res.ok) await loadInjectedKnowledge();
  } catch (err) { alert('Error: ' + err.message); }
}

// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
//  LEFT DRAWER β€” DASHBOARD (Ξ¦ JARVIS)
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•

let dashOpen = false;
let dashData = null;
let dashRefreshTimer = null;

function toggleDash() {
  dashOpen = !dashOpen;
  document.getElementById('dashDrawer').classList.toggle('open', dashOpen);
  document.getElementById('dashOverlay').classList.toggle('visible', dashOpen);
  if (dashOpen) {
    loadDashData();
    dashRefreshTimer = setInterval(loadDashData, 30000);
  } else {
    if (dashRefreshTimer) { clearInterval(dashRefreshTimer); dashRefreshTimer = null; }
  }
}

async function loadDashData() {
  try {
    const res = await fetch(`${API_BASE}/xdart/dashboard/data`, { signal: AbortSignal.timeout(20000) });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    dashData = await res.json();
    renderDashDrawer();
  } catch (e) {
    document.getElementById('dashBody').innerHTML = '<div class="left-drawer-loading">Failed to load: ' + esc(e.message) + '</div>';
  }
}

function _dashTimeAgo(dateStr) {
  if (!dateStr) return '';
  const s = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s / 60) + 'm';
  if (s < 86400) return Math.floor(s / 3600) + 'h';
  return Math.floor(s / 86400) + 'd';
}

function _dashDomainColor(d) {
  const m = { geopolitical: '#c44040', economy: '#40a060', economic: '#40a060', security: '#ff9800',
    energy: '#d4a843', technology: '#9B59B6', climate: '#00bcd4', market: '#4A90D9', social: '#e91e63' };
  return m[(d || '').toLowerCase()] || '#808090';
}

function _dashConfColor(c) {
  if (c >= 0.7) return 'var(--green)';
  if (c >= 0.4) return 'var(--gold)';
  return 'var(--red)';
}

function _dashRiskColor(s) {
  if (s >= 70) return 'var(--red)';
  if (s >= 45) return 'var(--gold)';
  return 'var(--green)';
}

function renderDashDrawer() {
  if (!dashData) return;
  const d = dashData;
  let html = '';

  // β”€β”€ KPI Strip β”€β”€
  const wc = d.world_context || {};
  const events = wc.events || [];
  const proph = d.prophecies || {};
  const acc = d.accuracy?.accuracy || {};
  const health = d.health || {};
  const char = d.character || {};
  const wis = d.wisdom || {};

  html += '<div class="dash-kpi-strip">';
  html += '<div class="dash-kpi"><div class="dash-kpi-val" style="color:#4A90D9">' + events.length + '</div><div class="dash-kpi-label">Events</div><div class="dash-kpi-sub">' + events.filter(e => (e.salience || 0) >= 0.6).length + ' high-salience</div></div>';
  html += '<div class="dash-kpi"><div class="dash-kpi-val" style="color:var(--gold)">' + (proph.total || 0) + '</div><div class="dash-kpi-label">Prophecies</div><div class="dash-kpi-sub">' + (proph.active || 0) + ' active Β· ' + (proph.confirmed || 0) + ' confirmed</div></div>';
  const brier = acc.brier_score;
  html += '<div class="dash-kpi"><div class="dash-kpi-val" style="color:' + (brier !== undefined && brier <= 0.25 ? 'var(--green)' : 'var(--gold)') + '">' + (brier !== undefined ? brier.toFixed(3) : 'β€”') + '</div><div class="dash-kpi-label">Brier Score</div><div class="dash-kpi-sub">' + (acc.rating || '') + '</div></div>';
  html += '<div class="dash-kpi"><div class="dash-kpi-val" style="color:#80cbc4">' + (health.memories || 'β€”') + '</div><div class="dash-kpi-label">Memories</div><div class="dash-kpi-sub">' + (health.concepts || 0) + ' concepts</div></div>';
  html += '<div class="dash-kpi"><div class="dash-kpi-val" style="color:var(--text)">' + (char.version || 'β€”') + '</div><div class="dash-kpi-label">Version</div><div class="dash-kpi-sub">' + esc(char.name || '') + '</div></div>';
  html += '<div class="dash-kpi"><div class="dash-kpi-val" style="color:' + _dashRiskColor((wis.wisdom_index || 0) * 100) + '">' + ((wis.wisdom_index || 0) * 100).toFixed(1) + '</div><div class="dash-kpi-label">Wisdom</div><div class="dash-kpi-sub">' + (wis.calibration_report || '') + '</div></div>';
  html += '</div>';

  // β”€β”€ World Feed β”€β”€
  html += '<div class="dash-section"><div class="dash-section-title" onclick="this.querySelector(\'.toggle-icon\').classList.toggle(\'collapsed\');this.nextElementSibling.classList.toggle(\'collapsed\')">π“΅ Live World Feed (' + events.length + ')<span class="toggle-icon">β–Ό</span></div><div class="dash-section-body">';
  if (events.length === 0) {
    html += '<div style="color:var(--text-dim);padding:12px;text-align:center">No events loaded</div>';
  } else {
    events.slice(0, 50).forEach(ev => {
      const domain = ev.domain || ev.event_domain || '';
      const sal = (ev.salience || 0);
      html += '<div class="dash-feed-item">';
      html += '<div class="dash-domain-dot" style="background:' + _dashDomainColor(domain) + '" title="' + esc(domain) + '"></div>';
      html += '<div class="dash-feed-headline">' + esc(ev.headline || ev.title || '') + '</div>';
      html += '<div class="dash-feed-meta">' + (sal * 100).toFixed(0) + '% Β· ' + _dashTimeAgo(ev.collected_at || ev.timestamp) + '</div>';
      html += '</div>';
    });
  }
  html += '</div></div>';

  // β”€β”€ Prophecies β”€β”€
  const prophList = (d.prophecies?.items || d.prophecies?.prophecies || []).slice(0, 15);
  if (prophList.length > 0) {
    html += '<div class="dash-section"><div class="dash-section-title" onclick="this.querySelector(\'.toggle-icon\').classList.toggle(\'collapsed\');this.nextElementSibling.classList.toggle(\'collapsed\')">π”® Active Prophecies (' + prophList.length + ')<span class="toggle-icon">β–Ό</span></div><div class="dash-section-body">';
    prophList.sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    prophList.forEach(p => {
      const conf = p.confidence || 0;
      html += '<div class="dash-prophecy">';
      html += '<div class="dash-prophecy-name">' + esc(p.name || p.scenario_name || '') + '</div>';
      html += '<div class="dash-prophecy-meta"><span>β± ' + esc(p.timeframe || '') + '</span><span style="color:' + _dashConfColor(conf) + '">' + (conf * 100).toFixed(0) + '% conf</span><span>' + esc(p.tracking_status || '') + '</span></div>';
      html += '<div class="dash-conf-bar"><div class="dash-conf-fill" style="width:' + (conf * 100) + '%;background:' + _dashConfColor(conf) + '"></div></div>';
      html += '</div>';
    });
    html += '</div></div>';
  }

  // β”€β”€ Intelligence β”€β”€
  const intro = d.introspection || {};
  const evoChanges = (d.core_changes?.recent || []).slice(0, 10);
  html += '<div class="dash-section"><div class="dash-section-title" onclick="this.querySelector(\'.toggle-icon\').classList.toggle(\'collapsed\');this.nextElementSibling.classList.toggle(\'collapsed\')">π“ System Intelligence<span class="toggle-icon">β–Ό</span></div><div class="dash-section-body">';

  const metrics = [
    { label: 'Wisdom Index', val: (wis.wisdom_index || 0), color: _dashRiskColor((wis.wisdom_index || 0) * 100) },
    { label: 'Avg Integrity', val: (intro.avg_integrity || 0), color: _dashConfColor(intro.avg_integrity || 0) },
    { label: 'Brier (inv)', val: brier !== undefined ? 1 - brier : 0, color: brier !== undefined && brier <= 0.25 ? 'var(--green)' : 'var(--gold)' },
  ];
  metrics.forEach(m => {
    html += '<div class="dash-metric-row"><div class="dash-metric-label">' + m.label + '</div><div class="dash-metric-bar"><div class="dash-metric-fill" style="width:' + (m.val * 100) + '%;background:' + m.color + '"></div></div><div class="dash-metric-val">' + (m.val * 100).toFixed(1) + '%</div></div>';
  });

  // Failure patterns
  const failures = intro.failure_patterns || [];
  if (failures.length > 0) {
    html += '<div style="margin-top:8px;font-size:11px;color:var(--text-dim)">Failure patterns:</div>';
    failures.slice(0, 5).forEach(f => {
      html += '<div style="font-size:11px;color:var(--red);padding:2px 0">β€Ά ' + esc(typeof f === 'string' ? f : f.pattern || JSON.stringify(f)) + '</div>';
    });
  }
  html += '</div></div>';

  // β”€β”€ Evolution Timeline β”€β”€
  if (evoChanges.length > 0) {
    html += '<div class="dash-section"><div class="dash-section-title" onclick="this.querySelector(\'.toggle-icon\').classList.toggle(\'collapsed\');this.nextElementSibling.classList.toggle(\'collapsed\')">π§¬ Evolution Timeline<span class="toggle-icon">β–Ό</span></div><div class="dash-section-body">';
    evoChanges.reverse().forEach(c => {
      const typeColor = c.change_type === 'principle' ? '#9B59B6' : c.change_type === 'belief' ? '#4A90D9' : 'var(--gold)';
      html += '<div class="dash-evo-item">';
      html += '<span class="dash-evo-type" style="background:' + typeColor + '22;color:' + typeColor + '">' + esc(c.change_type || '') + '</span>';
      html += '<div class="dash-evo-desc">' + esc((c.description || '').slice(0, 200)) + '</div>';
      html += '<div class="dash-evo-time">' + _dashTimeAgo(c.timestamp) + '</div>';
      html += '</div>';
    });
    html += '</div></div>';
  }

  document.getElementById('dashBody').innerHTML = html;
}

// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
//  LEFT DRAWER β€” ENTITY KNOWLEDGE GRAPH
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•

// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
// ENTITY GRAPH β€” D3.js Force-Directed Network
// β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
let egraphOpen = false;
let _d3Loaded = false;
let _egSim = null;
let _egSvg = null;
let _egG = null;
let _egZoom = null;
let _egData = null;
let _egActiveType = 'ALL';
let _egSearchTerm = '';
let _egBuilt = false;

const EG_TYPE_LABELS = {
  GPE: 'Countries/Cities', PERSON: 'People', ORG: 'Organizations',
  NORP: 'Nationalities', EVENT: 'Events', LOC: 'Locations',
  FAC: 'Facilities', PRODUCT: 'Products', UNKNOWN: 'Other',
};

function toggleEgraph() {
  egraphOpen = !egraphOpen;
  document.getElementById('egraphDrawer').classList.toggle('open', egraphOpen);
  document.getElementById('egraphOverlay').classList.toggle('visible', egraphOpen);
  if (egraphOpen && !_egBuilt) {
    _initEgraphD3();
  } else if (egraphOpen && _egSim) {
    // Reheat simulation briefly when reopened
    _egSim.alpha(0.15).restart();
  }
}

function _loadD3() {
  return new Promise((ok, fail) => {
    if (_d3Loaded) { ok(); return; }
    if (typeof d3 !== 'undefined' && d3.forceSimulation) { _d3Loaded = true; ok(); return; }
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js';
    s.onload = () => { _d3Loaded = true; ok(); };
    s.onerror = () => fail(new Error('D3.js load failed'));
    document.head.appendChild(s);
  });
}

async function _initEgraphD3() {
  const emptyEl = document.getElementById('egraphEmpty');
  emptyEl.innerHTML = '<div class="spinner"></div><p>Loading D3.js + entity data...</p>';
  try {
    await _loadD3();
    const res = await fetch(`${API_BASE}/xdart/entity-graph/data?max_nodes=200&min_mentions=2`, { signal: AbortSignal.timeout(20000) });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    _egData = await res.json();
    if (!_egData.nodes || _egData.nodes.length === 0) {
      emptyEl.innerHTML = '<span style="font-size:28px">π•Έ</span><p>No entity data yet</p>';
      return;
    }
    emptyEl.style.display = 'none';
    _renderEgraphD3(_egData);
    _egBuilt = true;
    // Wire search
    document.getElementById('egraphSearch').addEventListener('input', (e) => {
      _egSearchTerm = e.target.value.toLowerCase().trim();
      _applyEgraphFilters();
    });
  } catch (e) {
    emptyEl.innerHTML = '<span style="font-size:28px">β οΈ</span><p>Error: ' + esc(e.message) + '</p>';
  }
}

function _renderEgraphD3(data) {
  const container = document.getElementById('egraphContainer');
  const rect = container.getBoundingClientRect();
  const W = rect.width || 780;
  const H = rect.height || 600;

  const meta = data.meta || {};
  // Stats overlay
  document.getElementById('egraphStatsOverlay').innerHTML =
    (meta.total_nodes?.toLocaleString() || '?') + ' total nodes Β· ' +
    (meta.headlines_ingested?.toLocaleString() || '?') + ' headlines';

  // Legend
  const legend = meta.type_legend || {};
  let legendHtml = '';
  for (const [type, color] of Object.entries(legend)) {
    legendHtml += '<span class="egraph-legend-item"><span class="egraph-legend-dot" style="background:' + color + '"></span>' + (EG_TYPE_LABELS[type] || type) + '</span>';
  }
  document.getElementById('egraphLegend').innerHTML = legendHtml;

  // Clone data (D3 mutates)
  const nodes = data.nodes.map(n => ({ ...n }));
  const edges = data.edges.map(e => ({ ...e }));

  // SVG
  const svg = d3.select('#egraphContainer')
    .append('svg')
    .attr('width', W)
    .attr('height', H);

  // Glow filter
  const defs = svg.append('defs');
  const filter = defs.append('filter').attr('id', 'egGlow');
  filter.append('feGaussianBlur').attr('stdDeviation', 3).attr('result', 'blur');
  const merge = filter.append('feMerge');
  merge.append('feMergeNode').attr('in', 'blur');
  merge.append('feMergeNode').attr('in', 'SourceGraphic');

  // Container group (zoom/pan)
  const g = svg.append('g');
  const zoom = d3.zoom()
    .scaleExtent([0.15, 6])
    .on('zoom', (ev) => g.attr('transform', ev.transform));
  svg.call(zoom);

  // Edges
  const linkG = g.append('g').attr('class', 'eg-links');
  const linkEls = linkG.selectAll('line')
    .data(edges)
    .enter().append('line')
    .attr('stroke', '#1e2d40')
    .attr('stroke-width', d => Math.max(0.5, d.width * 0.5))
    .attr('stroke-opacity', 0.45);

  // Nodes
  const nodeG = g.append('g').attr('class', 'eg-nodes');
  const nodeEls = nodeG.selectAll('g')
    .data(nodes)
    .enter().append('g')
    .attr('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (ev, d) => { if (!ev.active) sim.alphaTarget(0.2).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag', (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
      .on('end', (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

  // Circles
  nodeEls.append('circle')
    .attr('r', d => Math.max(4, d.size * 0.35))
    .attr('fill', d => d.color || '#95A5A6')
    .attr('stroke', d => d.color || '#95A5A6')
    .attr('stroke-width', 1.5)
    .attr('stroke-opacity', 0.5)
    .attr('fill-opacity', 0.75)
    .attr('filter', d => d.activity_score > 5 ? 'url(#egGlow)' : null);

  // Labels
  nodeEls.append('text')
    .text(d => d.mentions >= 10 ? d.label : '')
    .attr('text-anchor', 'middle')
    .attr('dy', d => -(Math.max(4, d.size * 0.35) + 4))
    .attr('fill', '#c8d4e0')
    .attr('font-size', d => Math.max(8, Math.min(12, d.size * 0.25)))
    .attr('opacity', 0.8)
    .attr('pointer-events', 'none');

  // Tooltip on hover
  const tooltip = document.getElementById('egraphTooltip');
  nodeEls
    .on('mouseenter', (ev, d) => {
      // Highlight neighborhood
      const connected = new Set();
      edges.forEach(e => {
        const src = typeof e.source === 'object' ? e.source.id : e.source;
        const tgt = typeof e.target === 'object' ? e.target.id : e.target;
        if (src === d.id) connected.add(tgt);
        if (tgt === d.id) connected.add(src);
      });
      connected.add(d.id);
      nodeEls.select('circle').attr('opacity', n => connected.has(n.id) ? 1 : 0.12);
      nodeEls.select('text').attr('opacity', n => connected.has(n.id) ? 1 : 0.05);
      linkEls.attr('stroke-opacity', e => {
        const src = typeof e.source === 'object' ? e.source.id : e.source;
        const tgt = typeof e.target === 'object' ? e.target.id : e.target;
        return (src === d.id || tgt === d.id) ? 0.8 : 0.04;
      });
      linkEls.attr('stroke', e => {
        const src = typeof e.source === 'object' ? e.source.id : e.source;
        const tgt = typeof e.target === 'object' ? e.target.id : e.target;
        return (src === d.id || tgt === d.id) ? '#00d4ff' : '#1e2d40';
      });

      // Headlines from connected edges
      let headlines = [];
      edges.forEach(e => {
        const src = typeof e.source === 'object' ? e.source.id : e.source;
        const tgt = typeof e.target === 'object' ? e.target.id : e.target;
        if (src === d.id || tgt === d.id) headlines = headlines.concat(e.recent_headlines || []);
      });
      headlines = [...new Set(headlines)].slice(0, 3);

      tooltip.innerHTML =
        '<div class="tt-name">' + esc(d.label) + '</div>' +
        '<div class="tt-type" style="color:' + d.color + '">' + d.type + '</div>' +
        '<div class="tt-stat">Mentions: ' + d.mentions + ' Β· Activity: ' + d.activity_score + '</div>' +
        '<div class="tt-stat">Last seen: ' + (d.last_seen_iso ? new Date(d.last_seen_iso).toLocaleString() : 'N/A') + '</div>' +
        (headlines.length ? '<div class="tt-headline">' + headlines.map(h => esc(h)).join('<br>') + '</div>' : '');
      tooltip.style.display = 'block';
      const cr = container.getBoundingClientRect();
      tooltip.style.left = Math.min(ev.clientX - cr.left + 12, cr.width - 320) + 'px';
      tooltip.style.top = Math.min(ev.clientY - cr.top - 10, cr.height - 150) + 'px';
    })
    .on('mouseleave', () => {
      nodeEls.select('circle').attr('opacity', 1);
      nodeEls.select('text').attr('opacity', 0.8);
      linkEls.attr('stroke-opacity', 0.45).attr('stroke', '#1e2d40');
      tooltip.style.display = 'none';
    })
    .on('click', (ev, d) => {
      // Zoom to node
      const scale = 2.5;
      svg.transition().duration(500).call(
        zoom.transform,
        d3.zoomIdentity.translate(W / 2 - d.x * scale, H / 2 - d.y * scale).scale(scale),
      );
    });

  // Force simulation
  const sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(edges).id(d => d.id).distance(d => 80 + (1 / Math.max(0.1, d.weight)) * 20).strength(d => Math.min(0.3, d.weight * 0.05)))
    .force('charge', d3.forceManyBody().strength(d => -30 - d.size * 2).distanceMax(300))
    .force('center', d3.forceCenter(W / 2, H / 2).strength(0.05))
    .force('collide', d3.forceCollide(d => Math.max(6, d.size * 0.4) + 2))
    .force('x', d3.forceX(W / 2).strength(0.02))
    .force('y', d3.forceY(H / 2).strength(0.02))
    .alphaDecay(0.02)
    .velocityDecay(0.4)
    .on('tick', () => {
      linkEls
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);
      nodeEls.attr('transform', d => `translate(${d.x},${d.y})`);
    });

  _egSim = sim;
  _egSvg = svg;
  _egG = g;
  _egZoom = zoom;

  // Resize handler
  const ro = new ResizeObserver(() => {
    const r = container.getBoundingClientRect();
    if (r.width < 10 || r.height < 10) return;
    svg.attr('width', r.width).attr('height', r.height);
    sim.force('center', d3.forceCenter(r.width / 2, r.height / 2).strength(0.05));
    sim.force('x', d3.forceX(r.width / 2).strength(0.02));
    sim.force('y', d3.forceY(r.height / 2).strength(0.02));
    sim.alpha(0.1).restart();
  });
  ro.observe(container);
}

function egraphToggleFilter(btn) {
  document.querySelectorAll('.egraph-filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  _egActiveType = btn.dataset.type;
  _applyEgraphFilters();
}

function _applyEgraphFilters() {
  if (!_egSvg) return;
  const nodeEls = _egSvg.selectAll('.eg-nodes g');
  const linkEls = _egSvg.selectAll('.eg-links line');
  const visibleNodes = new Set();
  nodeEls.each(function(d) {
    const matchType = _egActiveType === 'ALL' || d.type === _egActiveType;
    const matchSearch = !_egSearchTerm || d.label.toLowerCase().includes(_egSearchTerm);
    const visible = matchType && matchSearch;
    d3.select(this).style('display', visible ? null : 'none');
    if (visible) visibleNodes.add(d.id);
  });
  linkEls.each(function(d) {
    const src = typeof d.source === 'object' ? d.source.id : d.source;
    const tgt = typeof d.target === 'object' ? d.target.id : d.target;
    d3.select(this).style('display', visibleNodes.has(src) && visibleNodes.has(tgt) ? null : 'none');
  });
  // Show labels for search matches
  if (_egSearchTerm) {
    nodeEls.select('text').text(function(d) {
      return d.label.toLowerCase().includes(_egSearchTerm) ? d.label : (d.mentions >= 10 ? d.label : '');
    });
  }
}

// Badge init
(async function() {
  try {
    const res = await fetch(`${API_BASE}/xdart/knowledge/external`);
    if (res.ok) {
      const d = await res.json();
      document.getElementById('injectCountBadge').textContent = d.count || 0;
    }
  } catch {}
})();

/* β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•
   VISION β€” Browser COCO-SSD (80 objects) + Server FaceNet (face ID)
   β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β•β• */

// Dynamic URLs β€” use same origin as the page for XDART API,
// and derive FaceNet URL from current hostname (port 8100).
const VISION_BASE = window.location.protocol + '//' + window.location.hostname + ':8100';
const XDART_API = API_BASE;   // reuse the dynamic API_BASE already defined above
let visionOpen = false;
let _cocoModel = null;
let _visionStream = null;
let _visionRunning = false;
let _visionAnimId = null;
let _visionFrameCount = 0;
let _visionLastFpsTime = 0;
let _visionSceneSentCount = 0;    // track scene reports sent
let _visionSceneFailCount = 0;    // track scene report failures
let _visionFaceSentCount = 0;     // track face crop sends
let _visionFps = 0;
let _visionLastSceneReport = 0;
const SCENE_REPORT_INTERVAL = 3000;
const FACE_CROP_INTERVAL = 2000;
let _visionLastFaceCrop = 0;
let _visionKnownIdentities = [];

const OBJ_EMOJI = {
  person:'\u{1F464}', bicycle:'\u{1F6B2}', car:'\u{1F697}', motorcycle:'\u{1F3CD}', airplane:'\u2708',
  bus:'\u{1F68C}', train:'\u{1F686}', truck:'\u{1F6DB}', boat:'\u26F5', 'traffic light':'\u{1F6A6}',
  'stop sign':'\u{1F6D1}', bench:'\u{1FA91}', bird:'\u{1F426}', cat:'\u{1F431}', dog:'\u{1F436}',
  horse:'\u{1F434}', cow:'\u{1F404}', elephant:'\u{1F418}', bear:'\u{1F43B}', zebra:'\u{1F993}',
  giraffe:'\u{1F992}', backpack:'\u{1F392}', umbrella:'\u2602', handbag:'\u{1F45C}', tie:'\u{1F454}',
  suitcase:'\u{1F9F3}', bottle:'\u{1F37E}', 'wine glass':'\u{1F377}', cup:'\u2615', fork:'\u{1F374}',
  knife:'\u{1F52A}', spoon:'\u{1F944}', bowl:'\u{1F963}', banana:'\u{1F34C}', apple:'\u{1F34E}',
  sandwich:'\u{1F96A}', orange:'\u{1F34A}', pizza:'\u{1F355}', donut:'\u{1F369}', cake:'\u{1F382}',
  chair:'\u{1FA91}', couch:'\u{1F6CB}', 'potted plant':'\u{1FAB4}', bed:'\u{1F6CF}',
  'dining table':'\u{1F37D}', tv:'\u{1F4FA}', laptop:'\u{1F4BB}', mouse:'\u{1F5B1}',
  remote:'\u{1F4F1}', keyboard:'\u2328', 'cell phone':'\u{1F4F1}',
  oven:'\u{1F525}', sink:'\u{1F6B0}', refrigerator:'\u{1F9CA}', book:'\u{1F4D6}',
  clock:'\u{1F550}', vase:'\u{1F3FA}', scissors:'\u2702', 'teddy bear':'\u{1F9F8}',
  toothbrush:'\u{1FAA5}',
};

function toggleVision() {
  visionOpen = !visionOpen;
  document.getElementById('visionDrawer').classList.toggle('open', visionOpen);
  document.getElementById('visionOverlay').classList.toggle('visible', visionOpen);
  if (visionOpen && _visionRunning && !_visionAnimId) _visionDetectLoop();
  if (!visionOpen && !_visionRunning && _visionAnimId) {
    cancelAnimationFrame(_visionAnimId); _visionAnimId = null;
  }
}

async function visionStart() {
  if (_visionRunning) return;
  const video = document.getElementById('visionVideo');
  const btn = document.getElementById('visionStartBtn');
  btn.textContent = '\u23F3 Loading...'; btn.disabled = true;

  try {
    _visionStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false,
    });
    video.srcObject = _visionStream;
    await video.play();

    if (!_cocoModel) {
      console.log('[Vision] Loading COCO-SSD...');
      _cocoModel = await cocoSsd.load({ base: 'lite_mobilenet_v2' });
      console.log('[Vision] COCO-SSD ready \u2014 80 object classes');
    }

    _visionRunning = true;
    _visionFrameCount = 0;
    _visionLastFpsTime = performance.now();
    document.getElementById('visionDot').className = 'v-dot on';
    document.getElementById('visionCamLabel').textContent = 'Active';
    btn.textContent = '\u25B6 Start'; btn.disabled = false;

    _visionDetectLoop();

    fetch(XDART_API + '/xdart/vision/event', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: 'vision_started', timestamp: new Date().toISOString() }),
    }).catch(() => {});

  } catch (err) {
    console.error('[Vision] Error:', err);
    btn.textContent = '\u25B6 Start'; btn.disabled = false;
    document.getElementById('visionCamLabel').textContent = 'Error: ' + err.message;
  }
}

function visionStop() {
  _visionRunning = false;
  if (_visionAnimId) { cancelAnimationFrame(_visionAnimId); _visionAnimId = null; }
  if (_visionStream) { _visionStream.getTracks().forEach(t => t.stop()); _visionStream = null; }
  document.getElementById('visionVideo').srcObject = null;
  const c = document.getElementById('visionCanvas');
  c.getContext('2d').clearRect(0, 0, c.width, c.height);

  document.getElementById('visionDot').className = 'v-dot off';
  document.getElementById('visionCamLabel').textContent = 'Offline';
  document.getElementById('visionObjCount').textContent = '0';
  document.getElementById('visionFaceCount').textContent = '0';
  document.getElementById('visionFPS').textContent = '0';
  document.getElementById('visionObjList').innerHTML = '<em style="color:var(--text-dim)">\u0397 \u03ba\u03ac\u03bc\u03b5\u03c1\u03b1 \u03b4\u03b5\u03bd \u03b5\u03af\u03bd\u03b1\u03b9 \u03b5\u03bd\u03b5\u03c1\u03b3\u03ae</em>';

  fetch(XDART_API + '/xdart/vision/event', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event_type: 'human_departed', timestamp: new Date().toISOString() }),
  }).catch(() => {});
}

async function _visionDetectLoop() {
  if (!_visionRunning || !_cocoModel) return;
  const video = document.getElementById('visionVideo');
  const canvas = document.getElementById('visionCanvas');
  const ctx = canvas.getContext('2d');

  if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
  }

  try {
    const predictions = await _cocoModel.detect(video);
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    let faceCount = 0;
    const objectCounts = {};

    for (const pred of predictions) {
      const [x, y, w, h] = pred.bbox;
      const label = pred.class;
      const score = pred.score;
      objectCounts[label] = (objectCounts[label] || 0) + 1;
      if (label === 'person') faceCount++;

      const color = label === 'person' ? '#00ff00' : '#00ddff';
      ctx.strokeStyle = color; ctx.lineWidth = 2;
      ctx.strokeRect(x, y, w, h);

      const text = label + ' ' + (score * 100).toFixed(0) + '%';
      ctx.font = '14px sans-serif';
      const tm = ctx.measureText(text);
      ctx.fillStyle = color;
      ctx.fillRect(x, y - 20, tm.width + 8, 20);
      ctx.fillStyle = '#000';
      ctx.fillText(text, x + 4, y - 5);
    }

    _visionFrameCount++;
    const now = performance.now();
    if (now - _visionLastFpsTime >= 1000) {
      _visionFps = _visionFrameCount; _visionFrameCount = 0; _visionLastFpsTime = now;
      document.getElementById('visionFPS').textContent = _visionFps;
    }
    document.getElementById('visionObjCount').textContent = predictions.length;
    document.getElementById('visionFaceCount').textContent = faceCount;
    _updateVisionObjList(objectCounts);

    const nowMs = Date.now();
    if (nowMs - _visionLastSceneReport >= SCENE_REPORT_INTERVAL && predictions.length > 0) {
      _visionLastSceneReport = nowMs;
      _reportScene(predictions);
    }
    if (nowMs - _visionLastFaceCrop >= FACE_CROP_INTERVAL && faceCount > 0) {
      _visionLastFaceCrop = nowMs;
      _sendFaceCrops(video, predictions.filter(p => p.class === 'person'));
    }
  } catch (err) {
    console.warn('[Vision] Detection error:', err);
  }

  _visionAnimId = requestAnimationFrame(_visionDetectLoop);
}

function _updateVisionObjList(objectCounts) {
  const el = document.getElementById('visionObjList');
  const entries = Object.entries(objectCounts).sort((a, b) => b[1] - a[1]);
  if (!entries.length) { el.innerHTML = '<em style="color:var(--text-dim)">\u0394\u03b5\u03bd \u03b5\u03bd\u03c4\u03bf\u03c0\u03af\u03c3\u03c4\u03b7\u03ba\u03b1\u03bd \u03b1\u03bd\u03c4\u03b9\u03ba\u03b5\u03af\u03bc\u03b5\u03bd\u03b1</em>'; return; }
  el.innerHTML = entries.map(([cls, count]) => {
    const emoji = OBJ_EMOJI[cls] || '\u{1F4E6}';
    return '<div class="vision-obj-item"><span>' + emoji + ' ' + cls + '</span><span class="vision-obj-badge">' + count + '</span></div>';
  }).join('');
}

async function _reportScene(predictions) {
  const objects = {};
  for (const p of predictions) {
    if (!objects[p.class]) objects[p.class] = { count: 0, max_conf: 0 };
    objects[p.class].count++;
    objects[p.class].max_conf = Math.max(objects[p.class].max_conf, p.score);
  }
  const objNames = Object.keys(objects).join(', ');
  try {
    const res = await fetch(XDART_API + '/xdart/vision/scene', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ timestamp: new Date().toISOString(), objects, total_detections: predictions.length, source: 'browser_coco_ssd' }),
    });
    _visionSceneSentCount++;
    if (!res.ok) {
      _visionSceneFailCount++;
      console.warn('[Vision] Scene report failed:', res.status, await res.text());
    } else if (_visionSceneSentCount <= 3 || _visionSceneSentCount % 20 === 0) {
      console.log('[Vision] Scene #' + _visionSceneSentCount + ' sent β†’ [' + objNames + ']');
    }
  } catch (e) {
    _visionSceneFailCount++;
    console.warn('[Vision] Scene report error:', e.message, 'β€” URL:', XDART_API + '/xdart/vision/scene');
  }
  _updateVisionDataFlow();
}

// Reusable off-screen canvas for face crops (avoids creating one every 2s)
let _faceCropCanvas = null;

async function _sendFaceCrops(video, personDetections) {
  if (!personDetections.length) return;

  // Send the FULL video frame β€” MTCNN is designed to find faces in full images.
  // Cropping person bboxes loses resolution and context, making MTCNN fail.
  if (!_faceCropCanvas) _faceCropCanvas = document.createElement('canvas');
  const tc = _faceCropCanvas;
  const tctx = tc.getContext('2d');
  tc.width = video.videoWidth;
  tc.height = video.videoHeight;
  tctx.drawImage(video, 0, 0);

  try {
    const blob = await new Promise(r => tc.toBlob(r, 'image/jpeg', 0.92));
    const fd = new FormData(); fd.append('image', blob, 'full_frame.jpg');
    _visionFaceSentCount++;
    const res = await fetch(VISION_BASE + '/detect', { method: 'POST', body: fd });
    if (res.ok) {
      const data = await res.json();
      console.log('[Vision] /detect #' + _visionFaceSentCount + ':', data.faces_count, 'faces', data.faces?.map(f => f.identity || 'unknown'));
      if (data.faces && data.faces.length > 0) {
        const identified = data.faces.filter(f => f.identity);
        const unknown = data.faces.filter(f => !f.identity);

        // Show all detected faces (identified + unknown)
        _visionKnownIdentities = [
          ...identified.map(f => ({ name: f.identity, confidence: f.recognition_confidence })),
          ...unknown.map(f => ({ name: 'Ξ†Ξ³Ξ½Ο‰ΟƒΟ„ΞΏ Ο€ΟΟΟƒΟ‰Ο€ΞΏ', confidence: f.detection_confidence })),
        ];
        _updateIdentityList();

        // Report event to XDART
        fetch(XDART_API + '/xdart/vision/event', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            event_type: 'human_detected', timestamp: new Date().toISOString(),
            faces_count: data.faces.length,
            identified: identified.map(f => f.identity),
            unknown_count: unknown.length,
            details: data.faces,
          }),
        }).catch(err => console.warn('[Vision] human_detected event failed:', err.message));
      } else {
        // No faces found in this frame β€” clear identity list
        _visionKnownIdentities = [];
        _updateIdentityList();
      }
    } else {
      console.warn('[Vision] /detect error:', res.status, await res.text());
    }
  } catch (e) {
    if (_visionFaceSentCount <= 3 || _visionFaceSentCount % 30 === 0)
      console.warn('[Vision] FaceNet request failed (#' + _visionFaceSentCount + '):', e.message, 'β€” URL:', VISION_BASE + '/detect');
  }
}

function _updateIdentityList() {
  const el = document.getElementById('visionIdentityList');
  if (_visionKnownIdentities.length > 0) {
    el.innerHTML = _visionKnownIdentities.map(id =>
      '<div class="vision-identity-item"><span>\u{1F464} ' + id.name + '</span><span style="color:var(--accent)">' + (id.confidence * 100).toFixed(0) + '%</span></div>'
    ).join('');
  } else {
    el.innerHTML = '<em style="color:var(--text-dim)">\u0394\u03b5\u03bd \u03ad\u03c7\u03bf\u03c5\u03bd \u03b5\u03bd\u03c4\u03bf\u03c0\u03b9\u03c3\u03c4\u03b5\u03af \u03c0\u03c1\u03cc\u03c3\u03c9\u03c0\u03b1 \u03b1\u03ba\u03cc\u03bc\u03b1</em>';
  }
}

function _updateVisionDataFlow() {
  const el = document.getElementById('visionDataFlow');
  if (!el) return;
  const ok = _visionSceneFailCount === 0 || _visionSceneSentCount > _visionSceneFailCount * 2;
  el.innerHTML = '<span style="color:' + (ok ? 'var(--accent)' : '#f44') + '">\u{1F4E1} Backend: ' +
    _visionSceneSentCount + ' sent' +
    (_visionSceneFailCount > 0 ? ', <b>' + _visionSceneFailCount + ' failed</b>' : '') +
    ' | Faces: ' + _visionFaceSentCount + '</span>' +
    '<span id="visionBackendState" style="display:block;color:var(--text-dim);margin-top:2px"></span>';
  // Poll backend scene state every 10 reports
  if (_visionSceneSentCount > 0 && _visionSceneSentCount % 5 === 0) {
    _pollBackendVisionState();
  }
}

async function _pollBackendVisionState() {
  try {
    const res = await fetch(XDART_API + '/xdart/vision/debug');
    if (!res.ok) return;
    const d = await res.json();
    const el = document.getElementById('visionBackendState');
    if (!el) return;
    const sceneKeys = Object.keys(d.current_scene || {});
    const smoothedKeys = Object.keys(d.smoothed_scene || {});
    el.innerHTML = '\u{1F9E0} Ξ‘Ξ―ΞΏΞ»ΞΏΟ‚ sees: <b>' +
      (sceneKeys.length > 0 ? sceneKeys.join(', ') : 'nothing yet') +
      '</b> (smoothed: ' + smoothedKeys.join(', ') +
      ') | updates: ' + (d.scene_updates || 0);
    el.style.color = sceneKeys.length > 0 ? '#4caf50' : 'var(--text-dim)';
  } catch (e) { /* non-critical */ }
}

function visionSnapshot() {
  const video = document.getElementById('visionVideo');
  const c = document.createElement('canvas');
  c.width = video.videoWidth; c.height = video.videoHeight;
  const ctx = c.getContext('2d');
  ctx.drawImage(video, 0, 0);
  ctx.drawImage(document.getElementById('visionCanvas'), 0, 0);
  c.toBlob(blob => { window.open(URL.createObjectURL(blob), '_blank'); }, 'image/jpeg', 0.92);
}



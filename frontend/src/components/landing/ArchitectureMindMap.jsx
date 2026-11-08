import { useRef, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { investigateHref, missionHref } from '../../router.js';
import { phases } from './content.js';
import TechnicalIcon from './TechnicalIcon.jsx';

function Miniature({ id }) {
  if (id === 'observe') return <div className="mini-sensor"><div className="mini-rack">{[0, 1, 2].map(i => <span key={i}><i /><i /><i /></span>)}</div><div><strong>29.4<span>°C</span></strong><small>54% RH · SIMULATED FAULT</small></div></div>;
  if (id === 'detect') return <div className="mini-compare"><span>LEGACY<strong>NORMAL</strong></span><b aria-label="differs from">≠</b><span>EXPECTED<strong>WARNING</strong></span></div>;
  if (id === 'investigate') return <div className="mini-code"><TechnicalIcon kind="code" size={28} /><span>temperature &gt; 35</span><small>↳ fault ignored · PLANNED AI</small></div>;
  if (id === 'verify') return <div className="mini-test"><span><small>ORIGINAL</small><strong>NORMAL</strong></span><b aria-hidden="true">→</b><span><small>CANDIDATE</small><strong>WARNING</strong></span><em>EXAMPLE · TEST INTEGRATION PLANNED</em></div>;
  return <div className="mini-handoff"><TechnicalIcon kind="response" size={30} /><span>Incident → Ticket → Message<small>RESPONSE ≠ RESOLUTION</small></span></div>;
}

export default function ArchitectureMindMap() {
  const [selected, setSelected] = useState(0);
  const [detailOpen, setDetailOpen] = useState(false);
  const [tool, setTool] = useState(null);
  const viewport = useRef(null);
  const phaseRefs = useRef([]);
  const reduce = useReducedMotion();
  const phase = phases[selected];

  function revealMobileDetails() {
    if (window.innerWidth > 600) return;
    requestAnimationFrame(() => {
      const node = document.getElementById('phase-detail');
      node?.focus({ preventScroll: true });
      node?.scrollIntoView({ block: 'start', behavior: reduce ? 'instant' : 'smooth' });
    });
  }
  function select(index, reveal = false) {
    setSelected(index);
    setTool(null);
    setDetailOpen(true);
    revealMobileDetails();
    if (reveal && viewport.current && window.innerWidth > 600) {
      const node = phaseRefs.current[index];
      viewport.current.scrollTo({ left: node.offsetLeft - viewport.current.offsetLeft - 20, behavior: reduce ? 'instant' : 'smooth' });
    }
  }
  function openTool(index, name, description) {
    setSelected(index);
    setTool({ name, description });
    setDetailOpen(true);
    revealMobileDetails();
  }
  function closeDetails() {
    setDetailOpen(false);
    phaseRefs.current[selected]?.querySelector('.phase-core')?.focus({ preventScroll: true });
  }
  function toolNode(index, [name, description]) {
    return <button key={name} className={`tool-node ${tool?.name === name && selected === index ? 'is-active' : ''}`} title={description} aria-controls="phase-detail" aria-expanded={detailOpen && tool?.name === name && selected === index} onClick={() => openTool(index, name, description)}><TechnicalIcon kind={phases[index].icon} size={13} />{name}</button>;
  }
  return (
    <section className="landing-section architecture-section" id="architecture" aria-labelledby="architecture-title">
      <div className="section-intro"><h2 id="architecture-title">One connected workflow.</h2><p>From signal to response.</p></div>
      <div className="map-toolbar"><span><i className="diagram-key" /> ILLUSTRATIVE WORKFLOW · SELECT A PHASE</span><div className="map-controls"><button aria-label="Explore previous phase" disabled={selected === 0} onClick={() => select(selected - 1, true)}>←</button><button aria-label="Explore next phase" disabled={selected === 4} onClick={() => select(selected + 1, true)}>→</button></div></div>
      <div className="architecture-viewport" ref={viewport} tabIndex={0} aria-label="Scrollable five-phase system architecture">
        <div className="architecture-canvas">
          <div className="architecture-phases">
            {phases.map((p, index) => (
              <motion.div key={p.id} ref={node => { phaseRefs.current[index] = node; }} className={`phase-group ${selected === index ? 'is-selected' : ''}`} initial={reduce ? false : { opacity: 0, y: 15 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: .15 }} transition={{ duration: .45, delay: reduce ? 0 : index * .08 }}>
                <div className="phase-tools phase-tools-top">{p.tools.slice(0, 2).map(t => toolNode(index, t))}</div>
                <span className="tool-stem" aria-hidden="true" />
                <button className={`phase-core phase-${p.id}`} onClick={() => select(index)} aria-expanded={detailOpen && selected === index} aria-controls="phase-detail">
                  <span className="phase-index">0{index + 1}</span>
                  <Miniature id={p.id} />
                  <span className="phase-title">{p.title}</span>
                  <span className="phase-caption">{p.caption}</span>
                  <span className="phase-output">{['fault=true', 'legacy_missed_fault', 'Root cause → evidence', 'Original → candidate', 'Jira + Slack'][index]}</span>
                </button>
                {p.tools.length > 2 && <><span className="tool-stem" aria-hidden="true" /><div className="phase-tools phase-tools-bottom">{p.tools.slice(2).map(t => toolNode(index, t))}</div></>}
                {index < 4 && <span className="phase-connector" aria-hidden="true"><motion.i initial={reduce ? false : { scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }} transition={{ duration: .5, delay: reduce ? 0 : index * .08 }} style={{ transformOrigin: 'left' }} />→</span>}
              </motion.div>
            ))}
          </div>
          <div className="response-branch"><svg viewBox="0 0 1680 75" preserveAspectRatio="none" aria-hidden="true"><motion.path d="M505 0V45H1515V0" initial={reduce ? false : { pathLength: 0 }} whileInView={{ pathLength: 1 }} viewport={{ once: true }} transition={{ duration: 1 }} /><path d="m1509 8 6-8 6 8" /></svg><span>Incident → Jira + Slack <i>No waiting for AI or tests</i></span></div>
          <div className="data-foundation"><span className="foundation-label">SHARED DATA</span><button onClick={() => openTool(1, 'MongoDB · Planned', 'Incident persistence is planned; this checkout currently stores incidents in memory.')}>MongoDB <small>Incidents · Planned</small></button><button onClick={() => openTool(0, 'Tiger Data · Planned', 'Historical telemetry is planned; the dashboard currently keeps browser-session history only.')}>Tiger Data <small>Telemetry · Planned</small></button><button onClick={() => openTool(3, 'Evidence · Planned', 'Source revisions, diffs and test outputs need a connected artifact store.')}>Evidence <small>Source · Tests</small></button></div>
        </div>
      </div>
      <div className="map-step-nav" aria-label="Select workflow phase">{phases.map((p, i) => <button key={p.id} aria-pressed={selected === i} onClick={() => select(i, true)}><span>0{i + 1}</span>{p.title}</button>)}</div>
      {detailOpen && <section className="phase-detail" id="phase-detail" tabIndex={-1} aria-label={`Details for ${phase.title}`} onKeyDown={event => { if (event.key === 'Escape') closeDetails(); }}>
        <div className="phase-detail-heading"><strong>{phase.title}</strong><span className="architecture-status">{phase.status}</span><button className="detail-close" aria-label="Close phase details" onClick={closeDetails}>×</button></div>
        <div className="phase-detail-grid">{[['Input', phase.input], ['Action', phase.processing], ['Output', phase.output]].map(([label, value]) => <div key={label}><h3>{label}</h3><p>{value}</p></div>)}</div>
        {tool && <div className="tool-detail" role="status"><TechnicalIcon kind={phase.icon} /><p><strong>{tool.name}</strong>{tool.description}</p><button aria-label="Close tool details" onClick={() => setTool(null)}>×</button></div>}
        <div className="phase-detail-footer"><details><summary>Implementation notes</summary><ul>{phase.note.split(/\. (?=[A-Z])/).map((sentence, i) => <li key={i}>{sentence.replace(/\.$/, '')}.</li>)}</ul><small>{phase.technology}</small></details><a href={selected === 0 ? missionHref : investigateHref()}>Open {selected === 0 ? 'Mission Control' : 'Investigation'} ↗</a></div>
      </section>}
    </section>
  );
}

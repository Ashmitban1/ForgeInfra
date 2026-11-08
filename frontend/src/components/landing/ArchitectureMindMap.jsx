import { useRef, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { investigateHref, missionHref } from '../../router.js';
import { phases } from './content.js';
import TechnicalIcon from './TechnicalIcon.jsx';

function Miniature({ id }) {
  if (id === 'observe') return <div className="mini-sensor"><div className="mini-rack">{[0, 1, 2].map(i => <span key={i}><i /><i /><i /></span>)}</div><div><strong>29.4<span>°C</span></strong><small>54% RH <b>•</b> SENSOR</small></div></div>;
  if (id === 'detect') return <div className="mini-compare"><span>LEGACY<strong>NORMAL</strong></span><b aria-label="differs from">≠</b><span>EXPECTED<strong>WARNING</strong></span></div>;
  if (id === 'investigate') return <div className="mini-code"><span><em>if</em> temperature &gt; 35:</span><span className="code-indent">return <b>'WARNING'</b></span><small>↳ cooling_fault ignored</small></div>;
  if (id === 'verify') return <div className="mini-diff"><span>− temperature &gt; 35</span><span>+ … or cooling_fault</span><small>CANDIDATE REQUIRES TEST EVIDENCE</small></div>;
  return <div className="mini-response"><span><i /> JIRA / SLACK <b>HANDOFF</b></span><span>Human review <b>SEPARATE</b></span><small>NOTIFICATION ≠ RESOLUTION</small></div>;
}

export default function ArchitectureMindMap() {
  const [selected, setSelected] = useState(0);
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
  function select(index, reveal = false, showDetail = false) {
    setSelected(index);
    setTool(null);
    if (showDetail) revealMobileDetails();
    if (reveal && viewport.current && window.innerWidth > 600) {
      const node = phaseRefs.current[index];
      viewport.current.scrollTo({ left: node.offsetLeft - viewport.current.offsetLeft - 20, behavior: reduce ? 'instant' : 'smooth' });
    }
  }
  return (
    <section className="landing-section architecture-section" id="architecture" aria-labelledby="architecture-title">
      <div className="section-intro"><div><span className="landing-eyebrow">THE FACTORYOS SYSTEM</span><h2 id="architecture-title">From raw signals<br />to verified action.</h2></div><p>One connected workflow for detecting unreliable monitoring, understanding the defect, and coordinating the response.</p></div>
      <div className="map-toolbar"><span><i className="diagram-key" /> ARCHITECTURE EXAMPLES · NOT LIVE RESULTS</span><div className="map-controls"><span>EXPLORE THE SYSTEM</span><button aria-label="Explore previous phase" disabled={selected === 0} onClick={() => select(selected - 1, true)}>←</button><button aria-label="Explore next phase" disabled={selected === 4} onClick={() => select(selected + 1, true)}>→</button></div></div>
      <div className="architecture-viewport" ref={viewport} tabIndex={0} aria-label="Scrollable five-phase system architecture">
        <div className="architecture-canvas">
          <div className="architecture-phases">
            {phases.map((p, index) => (
              <motion.div key={p.id} ref={node => { phaseRefs.current[index] = node; }} className={`phase-group ${selected === index ? 'is-selected' : ''}`} initial={reduce ? false : { opacity: 0, y: 15 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: .15 }} transition={{ duration: .45, delay: reduce ? 0 : index * .08 }}>
                <div className="phase-tools phase-tools-top">{p.tools.slice(0, 2).map(([name, description]) => <button key={name} className={`tool-node ${tool?.name === name && selected === index ? 'is-active' : ''}`} onClick={() => { setSelected(index); setTool({ name, description }); revealMobileDetails(); }} aria-controls="phase-detail" title={description}><span aria-hidden="true">◇</span>{name}</button>)}</div>
                <span className="tool-stem" aria-hidden="true" />
                <button className={`phase-core phase-${p.id}`} onClick={() => select(index, false, true)} aria-pressed={selected === index} aria-controls="phase-detail">
                  <span className="phase-index">PHASE 0{index + 1}<TechnicalIcon kind={p.icon} size={21} /></span>
                  <span className="phase-title">{p.title}</span><span className="phase-caption">{p.caption}</span>
                  <Miniature id={p.id} /><span className="phase-open">Explore phase <span aria-hidden="true">↗</span></span>
                </button>
                <span className="tool-stem" aria-hidden="true" />
                <div className="phase-tools phase-tools-bottom">{p.tools.slice(2).map(([name, description]) => <button key={name} className="tool-node" title={description} aria-controls="phase-detail" onClick={() => { setSelected(index); setTool({ name, description }); revealMobileDetails(); }}><span aria-hidden="true">·</span>{name}</button>)}</div>
                {index < 4 && <span className="phase-connector" aria-hidden="true"><motion.i initial={reduce ? false : { scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }} transition={{ duration: .5, delay: reduce ? 0 : index * .08 }} style={{ transformOrigin: 'left' }} />→</span>}
              </motion.div>
            ))}
          </div>
          <div className="response-branch"><svg viewBox="0 0 1680 75" preserveAspectRatio="none" aria-hidden="true"><motion.path d="M505 0V45H1515V0" initial={reduce ? false : { pathLength: 0 }} whileInView={{ pathLength: 1 }} viewport={{ once: true }} transition={{ duration: 1 }} /><path d="m1509 8 6-8 6 8" /></svg><span><b>PARALLEL RESPONSE</b> Incident → Jira + Slack <i>Independent of AI and repair completion</i></span></div>
          <div className="data-foundation"><span className="foundation-label">THE DATA<br />FOUNDATION <small>SHARED ACROSS PHASES</small></span><button onClick={() => { select(1); setTool({ name: 'MongoDB Atlas · Planned', description: 'Intended canonical incident/evidence records. Current backend storage is an in-memory dictionary; no Atlas integration exists in this checkout.' }); }}>Incident records <small>MongoDB Atlas · Planned</small></button><button onClick={() => { select(0); setTool({ name: 'Tiger Data · Planned', description: 'Intended timestamped telemetry and historical analytics. The current dashboard keeps only browser-session history.' }); }}>Historical telemetry <small>Tiger Data · Planned</small></button><button onClick={() => { select(3); setTool({ name: 'Engineering artifacts · Planned', description: 'Source revisions, diffs, test outputs, findings and repair records must share an incident identity. No connected artifact store exists here.' }); }}>Engineering artifacts <small>Source · Diffs · Test evidence</small></button></div>
        </div>
      </div>
      <div className="map-step-nav" aria-label="Select workflow phase">{phases.map((p, i) => <button key={p.id} aria-pressed={selected === i} onClick={() => select(i, true)}><span>0{i + 1}</span>{p.title}</button>)}</div>
      <section className="phase-detail" id="phase-detail" tabIndex={-1} aria-label={`Details for ${phase.title}`}>
        <div className="phase-detail-heading"><span className="landing-eyebrow">0{selected + 1} / {phase.title}</span><span className="architecture-status">{phase.status}</span></div>
        <div className="phase-detail-grid">{[['Input', phase.input], ['Processing', phase.processing], ['Output', phase.output], ['Technology', phase.technology]].map(([label, value]) => <div key={label}><h3>{label}</h3><p>{value}</p></div>)}</div>
        {tool && <div className="tool-detail" role="status"><TechnicalIcon kind={phase.icon} /><p><strong>{tool.name}</strong>{tool.description}</p><button aria-label="Close tool details" onClick={() => setTool(null)}>×</button></div>}
        <div className="phase-detail-footer"><p>{phase.note}</p><a href={selected === 0 ? missionHref : investigateHref()}>Open {selected === 0 ? 'Mission Control' : 'Investigation'} <span aria-hidden="true">↗</span></a></div>
      </section>
    </section>
  );
}

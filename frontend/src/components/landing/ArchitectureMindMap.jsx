import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { investigateHref, missionHref } from '../../router.js';
import { phases } from './content.js';
import TechnicalIcon from './TechnicalIcon.jsx';
import '../../architecture-blueprint.css';

// Illustrative examples only; none of these values are live runtime data.
const EXAMPLES = ['29.4°C · Fault TRUE', 'NORMAL ≠ WARNING', 'Root cause identified', '4/5 → 5/5 tests', 'KAN-5 · Delivered'];
const STEP = 0.48; // seconds between phases in the intro sequence
const phaseTime = index => 0.3 + index * STEP;
const prefersReducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

function Miniature({ id, index }) {
  let body;
  if (id === 'observe') body = <div className="mini-sensor"><div className="mini-rack">{[0, 1, 2].map(i => <span key={i}><i /><i /><i /></span>)}</div><div><strong>29.4<span>°C</span></strong><small>FAULT TRUE · SIMULATED</small></div></div>;
  else if (id === 'detect') body = <div className="mini-compare"><span>LEGACY<strong>NORMAL</strong></span><b aria-label="differs from">≠</b><span>EXPECTED<strong>WARNING</strong></span></div>;
  else body = <div className="mini-example"><TechnicalIcon kind={phases[index].icon} size={30} /><strong>{EXAMPLES[index]}</strong></div>;
  return <div className="mini-frame" data-tag="EXAMPLE">{body}</div>;
}

// Position relative to the canvas using layout offsets, so hover/entrance transforms never skew the geometry.
function offsetBox(el, root) {
  let x = 0, y = 0, node = el;
  while (node && node !== root) { x += node.offsetLeft; y += node.offsetTop; node = node.offsetParent; }
  return { x, y, w: el.offsetWidth, h: el.offsetHeight };
}
function roundedRect({ x, y, w, h }, r = 10) {
  return `M${x + r} ${y}H${x + w - r}A${r} ${r} 0 0 1 ${x + w} ${y + r}V${y + h - r}A${r} ${r} 0 0 1 ${x + w - r} ${y + h}H${x + r}A${r} ${r} 0 0 1 ${x} ${y + h - r}V${y + r}A${r} ${r} 0 0 1 ${x + r} ${y}Z`;
}

export default function ArchitectureMindMap() {
  const uid = useId().replace(/:/g, '');
  const [selected, setSelected] = useState(0);
  const [detailOpen, setDetailOpen] = useState(false);
  const [tool, setTool] = useState(null);
  const [hover, setHover] = useState(null);
  const [geo, setGeo] = useState(null);
  const [motionState, setMotionState] = useState('static'); // static → armed → playing
  const viewport = useRef(null);
  const canvas = useRef(null);
  const branch = useRef(null);
  const groupRefs = useRef([]);
  const coreRefs = useRef([]);
  const phase = phases[selected];

  const measure = useCallback(() => {
    const root = canvas.current;
    if (!root || groupRefs.current.some(node => !node)) return;
    const groups = groupRefs.current.map(node => offsetBox(node, root));
    const cores = coreRefs.current.map(node => offsetBox(node, root));
    const branchBox = branch.current ? offsetBox(branch.current, root) : null;
    const stacked = groups[1].y > groups[0].y + groups[0].h / 2;
    const next = { w: root.offsetWidth, h: root.offsetHeight, groups, cores, stacked, branchY: branchBox?.y ?? 0 };
    setGeo(prev => (prev && JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
  }, []);

  useLayoutEffect(() => {
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(canvas.current);
    groupRefs.current.forEach(node => node && observer.observe(node));
    window.addEventListener('resize', measure);
    document.fonts?.ready.then(measure);
    return () => { observer.disconnect(); window.removeEventListener('resize', measure); };
  }, [measure]);

  // Arm only when JS and motion are available; otherwise the diagram is simply static and complete.
  useLayoutEffect(() => {
    if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') return undefined;
    setMotionState('armed');
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setMotionState('playing'); observer.disconnect(); }
    }, { threshold: 0.2 });
    observer.observe(canvas.current);
    return () => observer.disconnect();
  }, []);

  const scrollBehavior = () => (prefersReducedMotion() ? 'instant' : 'smooth');
  function revealMobileDetails() {
    if (window.innerWidth > 600) return;
    requestAnimationFrame(() => {
      const node = document.getElementById('phase-detail');
      node?.focus({ preventScroll: true });
      node?.scrollIntoView({ block: 'start', behavior: scrollBehavior() });
    });
  }
  function select(index, reveal = false) {
    setSelected(index);
    setTool(null);
    setDetailOpen(true);
    revealMobileDetails();
    if (reveal && viewport.current && window.innerWidth > 600) {
      const node = groupRefs.current[index];
      viewport.current.scrollTo({ left: node.offsetLeft - 24, behavior: scrollBehavior() });
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
    coreRefs.current[selected]?.focus({ preventScroll: true });
  }
  function coreKeys(event, index) {
    const target = { ArrowRight: index + 1, ArrowDown: index + 1, ArrowLeft: index - 1, ArrowUp: index - 1 }[event.key];
    if (target === undefined || !coreRefs.current[target]) return;
    event.preventDefault();
    coreRefs.current[target].focus();
  }
  function toolNode(index, [name, description], order) {
    const active = tool?.name === name && selected === index;
    return <button key={name} className={`tool-node rv ${active ? 'is-active' : ''}`} style={{ '--t': `${phaseTime(index) + 0.55 + order * 0.1}s` }} title={description} aria-controls="phase-detail" aria-expanded={detailOpen && active} onClick={() => openTool(index, name, description)}><TechnicalIcon kind={phases[index].icon} size={13} />{name}</button>;
  }

  const lit = i => hover === i;
  const spineLit = i => hover === i || hover === i + 1;
  const notifyLit = hover === 1 || hover === 4;
  const lineClass = on => `bp-line ${on ? 'is-lit' : ''}`;

  function renderLines() {
    if (!geo) return null;
    const { groups, cores, stacked } = geo;
    const arrow = (x, y, dir) => ({ right: `M${x - 8} ${y - 4}L${x} ${y}L${x - 8} ${y + 4}`, down: `M${x - 4} ${y - 8}L${x} ${y}L${x + 4} ${y - 8}`, up: `M${x - 4} ${y + 8}L${x} ${y}L${x + 4} ${y + 8}` })[dir];
    const introY = cores[0].y + cores[0].h / 2;
    const spines = [0, 1, 2, 3].map(i => {
      const a = groups[i], b = groups[i + 1];
      if (stacked) { const x = a.x + a.w / 2; return { d: `M${x} ${a.y + a.h}V${b.y}`, head: arrow(x, b.y, 'down') }; }
      const y = cores[i].y + cores[i].h / 2;
      const x1 = cores[i].x + cores[i].w, x2 = cores[i + 1].x;
      return { d: `M${x1} ${y}H${x2}`, head: arrow(x2, y, 'right') };
    });
    let notify;
    if (stacked) {
      const a = groups[1], b = groups[4], gutter = 7;
      const ya = a.y + a.h / 2, yb = b.y + b.h / 2;
      notify = { d: `M${a.x} ${ya}H${gutter}V${yb}H${b.x}`, head: arrow(b.x, yb, 'right') };
    } else {
      const a = groups[1], b = groups[4], yLow = geo.branchY + 34;
      const xa = a.x + a.w / 2, xb = b.x + b.w / 2, top = b.y + b.h;
      notify = { d: `M${xa} ${a.y + a.h}V${yLow}H${xb}V${top}`, head: arrow(xb, top, 'up'), chip: { x: (xa + xb) / 2, y: yLow } };
    }
    return { spines, notify, introY, intro: stacked ? null : `M0 ${introY}H${cores[0].x}` };
  }
  const lines = renderLines();

  return (
    <section className="landing-section architecture-section" id="architecture" aria-labelledby="architecture-title">
      <div className="section-intro"><h2 id="architecture-title">One connected workflow.</h2><p>From signal to response.</p></div>
      <div className="map-toolbar"><span><i className="diagram-key" /> ILLUSTRATIVE WORKFLOW · EXAMPLES ARE NOT LIVE DATA</span><div className="map-controls"><button aria-label="Explore previous phase" disabled={selected === 0} onClick={() => select(selected - 1, true)}>←</button><button aria-label="Explore next phase" disabled={selected === 4} onClick={() => select(selected + 1, true)}>→</button></div></div>
      <div className="architecture-viewport" ref={viewport} tabIndex={0} aria-label="Scrollable five-phase system architecture">
        <div className={`architecture-canvas bp-${motionState}`} ref={canvas}>
          {lines && (
            <svg className="bp-svg" width={geo.w} height={geo.h} viewBox={`0 0 ${geo.w} ${geo.h}`} aria-hidden="true" focusable="false">
              <defs>
                <filter id={`${uid}-rough`} filterUnits="userSpaceOnUse" x="0" y="0" width={geo.w} height={geo.h}><feTurbulence type="fractalNoise" baseFrequency=".035" numOctaves="2" seed="4" result="n" /><feDisplacementMap in="SourceGraphic" in2="n" scale="1.5" /></filter>
                {geo.groups.map((g, i) => <mask key={i} id={`${uid}-m${i}`} maskUnits="userSpaceOnUse" x="0" y="0" width={geo.w} height={geo.h}><path className="bp-mask dr" pathLength="1" d={roundedRect(g)} style={{ '--t': `${phaseTime(i) + 0.2}s`, '--d': '.7s' }} /></mask>)}
                <mask id={`${uid}-mn`} maskUnits="userSpaceOnUse" x="0" y="0" width={geo.w} height={geo.h}><path className="bp-mask dr" pathLength="1" d={lines.notify.d} style={{ '--t': `${phaseTime(1) + 1.1}s`, '--d': '1s' }} /></mask>
              </defs>
              <g filter={`url(#${uid}-rough)`}>
                {lines.intro && <path className="bp-line bp-intro dr" pathLength="1" d={lines.intro} style={{ '--t': '0s', '--d': '.35s' }} />}
                {geo.groups.map((g, i) => <g key={i} mask={`url(#${uid}-m${i})`}><path className={`bp-boundary ${lit(i) || selected === i ? 'is-lit' : ''}`} d={roundedRect(g)} /></g>)}
                {lines.spines.map((s, i) => (
                  <g key={i}>
                    <path className="bp-pencil dr" pathLength="1" d={s.d} transform="translate(0 1.4)" style={{ '--t': `${phaseTime(i) + 0.5}s`, '--d': '.5s' }} />
                    <path className={`${lineClass(spineLit(i))} dr`} pathLength="1" d={s.d} style={{ '--t': `${phaseTime(i) + 0.4}s`, '--d': '.45s' }} />
                    <path className={`${lineClass(spineLit(i))} bp-head rv`} d={s.head} style={{ '--t': `${phaseTime(i) + 0.8}s` }} />
                  </g>
                ))}
                <g>
                  <g mask={`url(#${uid}-mn)`}><path className={`bp-notify ${notifyLit ? 'is-lit' : ''}`} d={lines.notify.d} /></g>
                  <path className={`bp-notify bp-head ${notifyLit ? 'is-lit' : ''} rv`} d={lines.notify.head} style={{ '--t': `${phaseTime(1) + 2}s` }} />
                </g>
              </g>
            </svg>
          )}
          <div className="architecture-phases">
            {phases.map((p, index) => (
              <div key={p.id} ref={node => { groupRefs.current[index] = node; }} className={`phase-group ${selected === index ? 'is-selected' : ''} ${hover === index ? 'is-hover' : ''}`} onMouseEnter={() => setHover(index)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(index)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setHover(null); }}>
                <div className="phase-tools phase-tools-top">{p.tools.slice(0, 2).map((t, i) => toolNode(index, t, i))}</div>
                <span className="tool-stem rv" style={{ '--t': `${phaseTime(index) + 0.4}s` }} aria-hidden="true" />
                <button ref={node => { coreRefs.current[index] = node; }} className={`phase-core rv phase-${p.id}`} style={{ '--t': `${phaseTime(index)}s`, '--i': index }} onClick={() => select(index)} onKeyDown={event => coreKeys(event, index)} aria-expanded={detailOpen && selected === index} aria-controls="phase-detail" aria-label={`${p.title}: ${p.caption}. Example ${EXAMPLES[index]}. Show input, action and output.`}>
                  <span className="phase-index">0{index + 1}<TechnicalIcon kind={p.icon} size={34} /></span>
                  <span className="phase-title">{p.title}</span>
                  <span className="phase-caption">{p.caption}</span>
                  <Miniature id={p.id} index={index} />
                </button>
                {p.tools.length > 2 && <><span className="tool-stem rv" style={{ '--t': `${phaseTime(index) + 0.4}s` }} aria-hidden="true" /><div className="phase-tools phase-tools-bottom">{p.tools.slice(2).map((t, i) => toolNode(index, t, i + 2))}</div></>}
              </div>
            ))}
          </div>

          <div className="response-branch" ref={branch}>
            <span className={`bp-chip rv ${lines && !geo.stacked ? 'is-floating' : ''} ${notifyLit ? 'is-lit' : ''}`} style={{ '--t': `${phaseTime(1) + 1.6}s`, ...(lines && !geo.stacked ? { left: lines.notify.chip.x, top: lines.notify.chip.y } : {}) }}>Incident → Jira + Slack <i>Parallel · no waiting for AI or tests</i></span>
          </div>
          <div className="data-foundation rv" style={{ '--t': `${phaseTime(4) + 0.6}s` }}><span className="foundation-label">SHARED DATA</span><button onClick={() => openTool(1, 'MongoDB', 'Optional durable incident, evidence, job, and approval storage through the shared backend.')}>MongoDB <small>Incidents · Evidence</small></button><button onClick={() => openTool(0, 'Tiger Data', 'Configured telemetry history, persisted source discovery, and time-bucket analytics feed the dashboard.')}>Tiger Data <small>Telemetry · Analytics</small></button><button onClick={() => openTool(3, 'Evidence', 'The backend exposes captured source revisions, actual candidate diffs, acceptance-test evidence, and replay.')}>Evidence <small>Source · Tests</small></button></div>

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

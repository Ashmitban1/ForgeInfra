import { useState } from 'react';
import { personas, problems } from './content.js';
import TechnicalIcon from './TechnicalIcon.jsx';
import { workspaceHref } from '../../router.js';

export default function UserProblemMatrix() {
  const [selected, setSelected] = useState(0);
  return (
    <section className="landing-section people-section" id="people" aria-labelledby="people-title">
      <div className="section-intro"><div><h2 id="people-title">People. Problems.<br />Connected.</h2></div><p>Choose a role. See what changes.</p></div>
      <div className="people-matrix">
        <div className="persona-column"><span className="column-label">Who uses ForgeInfra?</span>{personas.map((p, i) => <button key={p.id} className={`persona-row ${selected === i ? 'is-selected' : ''}`} onMouseEnter={() => setSelected(i)} onFocus={() => setSelected(i)} onClick={() => setSelected(i)} aria-pressed={selected === i} aria-controls="problem-list"><TechnicalIcon kind={p.icon} /><span><strong>{p.title}</strong><span>{p.description}</span></span><span className="persona-arrow" aria-hidden="true">↗</span></button>)}<a className="persona-destination" href={workspaceHref(personas[selected].route)}>Open {personas[selected].destination} <span aria-hidden="true">→</span></a></div>
        <div className="matrix-junction" aria-hidden="true"><span /><i>+</i><span /></div>
        <div className="problem-column" id="problem-list"><span className="column-label">What problems do we solve?</span>{problems.map(([title, description, solution], i) => <article key={title} className={`problem-row ${personas[selected].problems.includes(i) ? 'is-related' : ''}`}><span className="problem-number">0{i + 1}</span><div><h3>{title}</h3><p>{description}</p>{personas[selected].problems.includes(i) && <span className="sr-only">Relevant to {personas[selected].title}</span>}</div></article>)}</div>
      </div>
      <p className="challenge-note">Aligned with Northmark Compute & Cloud challenge themes.</p>
    </section>
  );
}

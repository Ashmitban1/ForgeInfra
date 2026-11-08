import { useEffect, useState } from 'react';
import FactoryOSLogo, { FactoryOSMark } from '../components/brand/FactoryOSLogo.jsx';
import LandingHero from '../components/landing/LandingHero.jsx';
import ArchitectureMindMap from '../components/landing/ArchitectureMindMap.jsx';
import UserProblemMatrix from '../components/landing/UserProblemMatrix.jsx';
import TechnicalIcon from '../components/landing/TechnicalIcon.jsx';
import { missionHref, workspaceHref } from '../router.js';

const workspaces = [
  ['mission', 'signal', '01', 'Mission Control', 'Live monitoring', 'Open Mission Control'],
  ['investigate', 'response', '02', 'Incident Response', 'Investigations', 'Open Incidents'],
  ['engineering', 'code', '03', 'Modernization', 'AI and test evidence', 'Explore Modernization'],
  ['operations', 'layers', '04', 'Operations', 'Current incidents and oversight', 'View Operations'],
];

export default function LandingPage({ section }) {
  const [menu, setMenu] = useState(false);
  const [activeSection, setActiveSection] = useState(section || 'overview');
  function scrollTo(id) {
    setMenu(false);
    setActiveSection(id);
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.getElementById(id)?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth', block: 'start' });
    window.history.replaceState(null, '', '#' + id);
  }
  useEffect(() => {
    setActiveSection(section || 'overview');
    if (section) document.getElementById(section)?.scrollIntoView({ behavior: 'instant' });
    else window.scrollTo({ top: 0, behavior: 'instant' });
  }, [section]);
  return (
    <div className="landing">
      <a className="skip-link" href="#landing-main" onClick={event => { event.preventDefault(); document.getElementById('landing-main')?.focus(); }}>Skip to content</a>
      <header className="landing-nav" onKeyDown={event => { if (event.key === 'Escape') { setMenu(false); document.querySelector('.menu-toggle')?.focus(); } }}>
        <a className="landing-brand" href="#overview" aria-label="FactoryOS overview" onClick={event => { event.preventDefault(); scrollTo('overview'); }}><FactoryOSLogo /></a>
        <button className="menu-toggle" aria-label={menu ? 'Close navigation' : 'Open navigation'} aria-expanded={menu} aria-controls="landing-links" onClick={() => setMenu(!menu)}>{menu ? '×' : '☰'}</button>
        <nav id="landing-links" className={menu ? 'is-open' : ''} aria-label="Product navigation">{[['overview', 'Overview'], ['architecture', 'Architecture'], ['people', "Who it’s for"], ['mission', 'Mission']].map(([id, label]) => <a href={'#' + id} key={id} aria-current={activeSection === id ? 'location' : undefined} onClick={event => { event.preventDefault(); scrollTo(id); }}>{label}</a>)}</nav>
        <a href={missionHref} className="nav-launch">Launch FactoryOS <span aria-hidden="true">↗</span></a>
      </header>
      <main id="landing-main" tabIndex={-1}>
        <LandingHero scrollTo={scrollTo} />
        <ArchitectureMindMap />
        <UserProblemMatrix />
        <section className="landing-section workspace-section" id="workspaces" aria-labelledby="workspace-title"><div className="section-intro"><div><h2 id="workspace-title">Enter the platform.</h2></div><p>One platform. Four starting points.</p></div><div className="workspace-grid">{workspaces.map(([route, icon, index, title, text, action]) => <a href={workspaceHref(route)} className="workspace-card" key={route}><div><span className="landing-eyebrow">{index}</span><TechnicalIcon kind={icon} size={30} /></div><h3>{title}</h3><p>{text}</p><span className="workspace-action">{action}<span aria-hidden="true">↗</span></span></a>)}</div><small className="workspace-disclosure">Shared incidents · Navigation preferences, not permissions</small></section>
        <section className="closing-section" id="mission" aria-labelledby="mission-title"><div className="closing-mark"><FactoryOSMark size={48} /></div><h2 id="mission-title">Don’t just detect failures.<br /><span>Understand them.</span></h2><div className="hero-actions"><a className="metal-button" href={missionHref}>Launch FactoryOS <span aria-hidden="true">↗</span></a><button className="text-button" onClick={() => scrollTo('architecture')}>Explore the workflow ↑</button></div></section>
      </main>
      <footer className="landing-footer"><a href="#overview" onClick={event => { event.preventDefault(); scrollTo('overview'); }} aria-label="Back to FactoryOS overview"><FactoryOSLogo /></a><span>HACKUTD 2026 · INFRASTRUCTURE RELIABILITY</span></footer>
    </div>
  );
}

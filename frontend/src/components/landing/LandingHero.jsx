import { useRef } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { FactoryOSMark } from '../brand/FactoryOSLogo.jsx';
import { missionHref } from '../../router.js';

function ServerSculpture() {
  const ref = useRef(null);
  const reduce = useReducedMotion();
  function move(event) {
    if (reduce || event.pointerType !== 'mouse') return;
    const rect = event.currentTarget.getBoundingClientRect();
    ref.current.style.setProperty('--tilt-x', `${((event.clientY - rect.top) / rect.height - .5) * -5}deg`);
    ref.current.style.setProperty('--tilt-y', `${((event.clientX - rect.left) / rect.width - .5) * 7}deg`);
  }
  function reset() {
    ref.current.style.setProperty('--tilt-x', '0deg');
    ref.current.style.setProperty('--tilt-y', '0deg');
  }
  return (
    <div className="server-art" onPointerMove={move} onPointerLeave={reset}>
      <div className="server-art-inner" ref={ref}>
        <svg viewBox="0 0 640 540" role="img" aria-labelledby="sculpture-title sculpture-desc">
          <title id="sculpture-title">An engineered path from signal to response</title>
          <desc id="sculpture-desc">A metallic server connects four conceptual nodes: signal, verify, investigate, and respond. Architecture illustration, not live telemetry.</desc>
          <defs>
            <linearGradient id="rack-front" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#58616b" /><stop offset=".08" stopColor="#293139" /><stop offset=".5" stopColor="#131a20" /><stop offset="1" stopColor="#080c10" /></linearGradient>
            <linearGradient id="rack-edge"><stop stopColor="#aeb8c3" /><stop offset=".5" stopColor="#3b454e" /><stop offset="1" stopColor="#171e25" /></linearGradient>
            <linearGradient id="blade" x2="0" y2="1"><stop stopColor="#3c4752" /><stop offset=".14" stopColor="#202a33" /><stop offset="1" stopColor="#10171e" /></linearGradient>
            <radialGradient id="floor-glow"><stop stopColor="#5aa9ff" stopOpacity=".14" /><stop offset="1" stopColor="#5aa9ff" stopOpacity="0" /></radialGradient>
          </defs>
          <ellipse cx="325" cy="434" rx="270" ry="92" fill="url(#floor-glow)" />
          <g className="orbit-lines" fill="none" stroke="#657583" strokeWidth=".7">
            <ellipse cx="326" cy="354" rx="280" ry="108" transform="rotate(-17 326 354)" />
            <ellipse cx="326" cy="354" rx="228" ry="86" transform="rotate(-17 326 354)" strokeDasharray="3 8" />
            <path d="M60 170h100l65 40m221 14 55-76h90M404 380l93 42h90M204 349l-70 74H40" />
          </g>
          <g className="signal-traces" fill="none" stroke="#5aa9ff" strokeWidth="1.5"><path d="M60 170h100l65 40" /><path d="M404 380l93 42h90" /></g>
          <g className="sculpture-rack">
            <path d="m230 128 149-42 91 53-149 44Z" fill="url(#rack-edge)" stroke="#737f8a" strokeWidth=".8" />
            <path d="m379 86 91 53v255l-91-53Z" fill="#151c22" stroke="#424e59" strokeWidth="1" />
            <path d="m230 128 149 43v255l-149-43Z" fill="url(#rack-front)" stroke="#6d7882" strokeWidth="1" />
            <path d="m239 140 131 38v233l-131-38Z" fill="#0a1015" stroke="#34414d" />
            {[0, 1, 2, 3, 4, 5].map((n) => <g key={n} transform={`translate(0 ${n * 34})`}>
              <path d="m246 150 117 34v27l-117-34Z" fill="url(#blade)" stroke="#4b5863" strokeWidth=".6" />
              <path d="m254 159 73 22m-73-17 73 22m-73-17 73 22" stroke="#66717a" strokeWidth=".6" opacity=".6" />
              <path d="m344 187 10 3" stroke={n === 2 ? '#5aa9ff' : '#76b900'} strokeWidth="2.8" />
              <circle cx="354" cy="197" r="1.4" fill="#b8c6d1" />
            </g>)}
            <path d="m391 115 60 35v213l-60-35Z" fill="#10161c" stroke="#25323c" />
            {Array.from({ length: 18 }, (_, n) => <path key={n} d={`m398 ${139+n*10} 45 26`} stroke="#2c3944" strokeWidth="1.5" />)}
            <path d="m230 128 149 43v255" fill="none" stroke="#c9d4dd" strokeWidth="1.4" opacity=".7" />
          </g>
          <g className="art-labels" fontFamily="ui-monospace,monospace" fontSize="10" letterSpacing="2">
            <g transform="translate(35 131)"><rect width="123" height="47" rx="4" fill="#121a21" stroke="#3b4b58" /><circle cx="15" cy="16" r="3" fill="#5aa9ff" /><text x="29" y="20" fill="#dce2e8">SIGNAL</text><text x="15" y="36" fill="#8393a1" fontSize="8" letterSpacing="1">01 / SOURCE</text></g>
            <g transform="translate(472 101)"><rect width="126" height="47" rx="4" fill="#121a21" stroke="#3b4b58" /><circle cx="15" cy="16" r="3" fill="#76b900" /><text x="29" y="20" fill="#dce2e8">VERIFY</text><text x="15" y="36" fill="#8393a1" fontSize="8" letterSpacing="1">02 / COMPARE</text></g>
            <g transform="translate(25 420)"><rect width="149" height="47" rx="4" fill="#121a21" stroke="#3b4b58" /><circle cx="15" cy="16" r="3" fill="#76b900" /><text x="29" y="20" fill="#dce2e8">INVESTIGATE</text><text x="15" y="36" fill="#8393a1" fontSize="8" letterSpacing="1">03 / UNDERSTAND</text></g>
            <g transform="translate(475 421)"><rect width="123" height="47" rx="4" fill="#121a21" stroke="#3b4b58" /><circle cx="15" cy="16" r="3" fill="#a9b3be" /><text x="29" y="20" fill="#dce2e8">RESPOND</text><text x="15" y="36" fill="#8393a1" fontSize="8" letterSpacing="1">04 / HUMAN</text></g>
          </g>
        </svg>
      </div>
      <span className="art-caption">Architecture illustration · not live data</span>
    </div>
  );
}
export default function LandingHero({ scrollTo }) {
  const reduce = useReducedMotion();
  return (
    <section className="landing-hero" id="overview" aria-labelledby="hero-heading">
      <motion.div className="hero-copy" initial={reduce ? false : { opacity: 0, y: 22 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .6 }}>
        <h1 id="hero-heading" className="hero-brand"><FactoryOSMark size={72} /><span>ForgeInfra</span></h1>
        <p className="hero-tagline">Detect. Investigate.<br className="hero-mobile-break" /> Verify. Respond.</p>
        <p className="hero-description">AI-powered infrastructure reliability and legacy software modernization.</p>
        <div className="hero-actions"><a className="metal-button" href={missionHref}>Enter Mission Control <span aria-hidden="true">↗</span></a><button className="text-button" onClick={() => scrollTo('architecture')}>Explore Workflow <span aria-hidden="true">↓</span></button></div>
      </motion.div>
      <motion.div className="hero-visual" initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: .9, delay: .15 }}><ServerSculpture /></motion.div>
      <div className="hero-bottom"><span>HACKUTD 2026</span><button onClick={() => scrollTo('architecture')} aria-label="Scroll to system architecture">↓</button></div>
    </section>
  );
}

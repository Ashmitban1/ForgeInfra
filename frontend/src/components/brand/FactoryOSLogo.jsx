export function FactoryOSMark({ size = 34 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden="true">
      <path d="M7 33V7h26v7H15v5h14v7H15v7H7Z" fill="currentColor" />
      <path d="M7 7h26M15 19h14" stroke="white" strokeOpacity=".5" />
      <path d="M24 33h9v-7" stroke="currentColor" strokeWidth="2" />
      <rect x="29" y="29" width="5" height="5" fill="#76B900" />
    </svg>
  );
}
export default function FactoryOSLogo({ compact = false }) {
  return <span className="fos-logo"><FactoryOSMark />{!compact && <span>Factory<span className="fos-logo-os">OS</span></span>}</span>;
}

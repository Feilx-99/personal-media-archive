export default function Mark({ className = "mark" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="3" y="4" width="26" height="24" rx="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="16" cy="16" r="4.2" fill="currentColor" />
      <rect x="6.5" y="7.2" width="2.4" height="2.4" rx="0.4" fill="currentColor" />
      <rect x="23.1" y="7.2" width="2.4" height="2.4" rx="0.4" fill="currentColor" />
      <rect x="6.5" y="22.4" width="2.4" height="2.4" rx="0.4" fill="currentColor" />
      <rect x="23.1" y="22.4" width="2.4" height="2.4" rx="0.4" fill="currentColor" />
    </svg>
  );
}

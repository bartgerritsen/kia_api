type Level = "good" | "warning" | "critical" | "neutral";

/** Status icon so state is never conveyed by colour alone. */
export function StatusIcon({ level }: { level: Level }) {
  const common = { className: `icon ${level}`, viewBox: "0 0 20 20", fill: "none", stroke: "currentColor", strokeWidth: 2 } as const;
  if (level === "good")
    return (
      <svg {...common} aria-hidden="true">
        <circle cx="10" cy="10" r="8" />
        <path d="M6.5 10.5l2.3 2.3 4.7-5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  if (level === "neutral")
    return (
      <svg {...common} aria-hidden="true">
        <circle cx="10" cy="10" r="8" />
      </svg>
    );
  return (
    <svg {...common} aria-hidden="true">
      <path d="M10 2.5l8 14.5H2z" strokeLinejoin="round" />
      <path d="M10 8v4M10 14.5v.5" strokeLinecap="round" />
    </svg>
  );
}

export function StatusLine({ level, children }: { level: Level; children: React.ReactNode }) {
  return (
    <div className="status-line">
      <StatusIcon level={level} />
      <span>{children}</span>
    </div>
  );
}

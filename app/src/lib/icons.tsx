// Single-stroke icons drawn for Guider (replace text glyphs ✓ ✗ × ← →). 16px, currentColor.
type P = { className?: string; label?: string };

function Svg({ className = "", label, children }: P & { children: React.ReactNode }) {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" className={`inline-block flex-none ${className}`}
      role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      {children}
    </svg>
  );
}

export const Check = (p: P) => <Svg {...p}><path d="M3 8.5l3.2 3L13 4.5" /></Svg>;
export const Cross = (p: P) => <Svg {...p}><path d="M4 4l8 8M12 4l-8 8" /></Svg>;
export const Pending = (p: P) => <Svg {...p}><path d="M3 8h1M7.5 8h1M12 8h1" /></Svg>;
export const ArrowLeft = (p: P) => <Svg {...p}><path d="M13 8H3M7 4L3 8l4 4" /></Svg>;
export const ArrowRight = (p: P) => <Svg {...p}><path d="M3 8h10M9 4l4 4-4 4" /></Svg>;

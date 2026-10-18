// Compact numbers for tiles: 1.4B, 119.7k, 704.
export function compact(n: number, digits = 1): string {
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${trim((n / 1e9).toFixed(digits))}B`;
  if (abs >= 1e6) return `${trim((n / 1e6).toFixed(digits))}M`;
  if (abs >= 1e4) return `${trim((n / 1e3).toFixed(digits))}k`;
  return Math.round(n).toLocaleString('en-US');
}

export function usd(n: number): string {
  if (Math.abs(n) >= 1e9) return `$${trim((n / 1e9).toFixed(1))}B`;
  if (Math.abs(n) >= 1e6) return `$${trim((n / 1e6).toFixed(1))}M`;
  return `$${compact(n)}`;
}

export function mw(n: number): string {
  return `${Math.round(n).toLocaleString('en-US')} MW`;
}

export function pct(ratio: number): string {
  return `${Math.round(ratio * 100)}%`;
}

export function gb(bytes: number): string {
  return `${trim((bytes / 1e9).toFixed(2))} GB`;
}

function trim(s: string): string {
  return s.includes('.') ? s.replace(/\.?0+$/, '') : s;
}

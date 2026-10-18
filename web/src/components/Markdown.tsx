import { marked } from 'marked';
import { useMemo } from 'react';

// Renders the team's own markdown from docs/. The content is ours, not user input.
export function Markdown({ source, className = '' }: { source: string; className?: string }) {
  const html = useMemo(() => marked.parse(source, { async: false, gfm: true }), [source]);
  return <div className={`md ${className}`} dangerouslySetInnerHTML={{ __html: html }} />;
}

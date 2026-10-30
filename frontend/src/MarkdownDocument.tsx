import type { ReactNode } from 'react';

// Render the application's generated Markdown subset as escaped React nodes.
// Raw HTML and executable links are never interpreted.
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => part.startsWith('**') ?
    <strong key={i}>{part.slice(2, -2)}</strong> : part);
}
export function MarkdownDocument({text}: {text: string}) {
  const blocks: ReactNode[] = []; const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) continue;
    if (line.startsWith('### ')) blocks.push(<h3 key={i}>{inline(line.slice(4))}</h3>);
    else if (line.startsWith('## ')) blocks.push(<h2 key={i}>{inline(line.slice(3))}</h2>);
    else if (line.startsWith('# ')) blocks.push(<h1 key={i}>{inline(line.slice(2))}</h1>);
    else if (line.startsWith('- ')) {
      const items = []; const start = i;
      while (i < lines.length && lines[i].startsWith('- ')) {items.push(<li key={i}>{inline(lines[i].slice(2))}</li>); i++;}
      i--; blocks.push(<ul key={start}>{items}</ul>);
    } else blocks.push(<p key={i}>{inline(line)}</p>);
  }
  return <article className="document">{blocks}</article>;
}

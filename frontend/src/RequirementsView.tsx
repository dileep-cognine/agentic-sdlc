import { useState } from 'react';
import type { Analysis } from './workspaceTypes';

export function RequirementsView({analysis: a}: {analysis: Analysis}) {
  const [search, setSearch] = useState(''); const [type, setType] = useState(''); const [origin, setOrigin] = useState('');
  const rows = a.document.requirements.filter(r => (!type || r.category === type) && (!origin || r.classification === origin) &&
    `${r.id} ${r.title} ${r.text}`.toLowerCase().includes(search.toLowerCase()));
  return <><div className="filters"><label>Search<input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search requirements…"/></label>
    <label>Type<select value={type} onChange={e => setType(e.target.value)}><option value="">All types</option>
      {[...new Set(a.document.requirements.map(r => r.category))].map(t => <option key={t} value={t}>{t.replaceAll('_', ' ')}</option>)}</select></label>
    <label>Source classification<select value={origin} onChange={e => setOrigin(e.target.value)}><option value="">All sources</option>
      {['STATED','INFERRED','CUSTOMER_CONFIRMED','UNRESOLVED'].map(t => <option key={t}>{t}</option>)}</select></label></div>
    <p className="subtle">{rows.length} requirements · Stable IDs are preserved across revisions</p>
    <div className="requirement-list">{rows.map(r => <section className="panel requirement-card" key={r.id}>
      <div className="section-heading"><span className="requirement-id">{r.id}</span><div className="tags"><span className="pill">{r.category.replaceAll('_',' ')}</span>
        <span className={`pill ${r.classification === 'INFERRED' ? 'amber' : ''}`}>{r.classification.replaceAll('_',' ')}</span><span className="pill">{r.resolution}</span></div></div>
      <h3>{r.title || r.text.split('.')[0]}</h3><p>{r.text}</p>
      <details><summary>Traceability</summary><p>Related questions: {a.document.questions.filter(q => q.related_requirement_ids.includes(r.id) ||
        r.source_refs.some(ref => ref.startsWith(`answer:${q.id}:`))).map(q => q.id).join(', ') || 'None'}</p>
        <p>Source references: {r.source_refs.join(', ') || 'Inferred; no direct source'}</p></details>
    </section>)}</div>{!rows.length && <div className="empty-state">No requirements match these filters.</div>}</>;
}

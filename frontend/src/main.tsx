import { useEffect, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { AnalysisPanel, UploadPanel } from './AnalysisPanel';
import { api } from './api';

type Project = {id: string; name: string; description: string; state: string; version: number};
type Requirement = {id: string; requirement_id: string; version: number; text: string};

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);
  const [history, setHistory] = useState<Requirement[]>([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  async function refresh() {
    const data = await api<Project[]>('/projects?limit=100');
    setProjects(data);
    setSelected(current => data.find(p => p.id === current?.id) || null);
  }
  useEffect(() => { refresh().catch(() => setError('Cannot connect to backend.')); }, []);
  useEffect(() => {
    let active = true;
    setHistory([]);
    if (selected) api<Requirement[]>(`/projects/${selected.id}/requirements?limit=100`)
      .then(data => { if (active) setHistory(data); })
      .catch(() => { if (active) setError('Could not load requirement history.'); });
    return () => { active = false; };
  }, [selected]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : 'Request failed'); }
    finally { setBusy(false); }
  }
  function create(event: FormEvent) {
    event.preventDefault();
    void run(async () => {
      const project = await api<Project>('/projects', {name, description});
      await refresh(); setSelected(project); setName(''); setDescription('');
      setMessage('Project created. Submit requirements to begin intake.');
    });
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    void run(async () => {
      await api(`/projects/${selected.id}/requirements`, {text, expected_version: selected.version});
      await refresh(); setText(''); setMessage('Requirement version saved. Ready for analysis.');
    });
  }
  return <main>
    <header><span className="eyebrow">AGENTIC SDLC / PHASE 2</span><h1>Business Analyst workspace</h1>
      <p>Capture requirements. Preserve decisions. Build a shared understanding.</p></header>
    {error && <div role="alert" className="notice error">{error}</div>}
    {message && <div role="status" className="notice">{message}</div>}
    <div className="layout"><aside><section><h2>Create a project</h2><form onSubmit={create}>
      <label>Project name<input required maxLength={200} value={name} onChange={e => setName(e.target.value)}/></label>
      <label>Description<textarea maxLength={10000} value={description} onChange={e => setDescription(e.target.value)}/></label>
      <button disabled={busy || !name.trim()}>Create project</button></form></section>
      <section><div className="row"><h2>Projects</h2><button disabled={busy} onClick={() => void run(refresh)}>Refresh</button></div>
      <p className="muted">Showing the latest 100 projects.</p>
      {!projects.length && <p>No projects yet. Create your first project above.</p>}
      {projects.map(p => <button className={`project ${p.id === selected?.id ? 'active' : ''}`} key={p.id}
        disabled={busy} onClick={() => {setSelected(p); setText(''); setMessage('');}}>
        <strong>{p.name}</strong><span>{p.state.replaceAll('_', ' ')} · v{p.version}</span></button>)}
      </section></aside>
      <section>{selected ? <><div className="row"><h2>{selected.name}</h2><span className="badge">{selected.state}</span></div>
        <p>{selected.description || 'No description provided.'}</p><p className="muted">Project version {selected.version}</p>
        <h3>Submit requirements</h3><p>Paste customer requirements as plain text. Each submission saves a new version of this project’s intake document.</p>
        <form onSubmit={submit}><label>Requirement text<textarea className="requirements" required maxLength={100000}
          value={text} onChange={e => setText(e.target.value)}/></label>
          <button disabled={busy || !text.trim() || selected.state !== 'INTAKE'}>Save requirement version</button></form>
        <UploadPanel key={`upload-${selected.id}`} project={selected} onChanged={refresh}/>
        <AnalysisPanel key={selected.id} project={selected} onChanged={refresh}/>
        <h3>Intake version history</h3><p className="muted">Latest 100 versions of the original customer input.</p>
        {!history.length && <p>No requirements submitted yet.</p>}
        {history.map(r => <details key={r.id}><summary>Requirement version {r.version}</summary><small>{r.requirement_id}</small><pre>{r.text}</pre></details>)}
      </> : <div className="empty"><h2>Your requirements start here</h2><p>Select a project to view its workflow status and submit requirements.</p></div>}</section>
    </div>
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);

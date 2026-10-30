import { useEffect, useState, type FormEvent } from 'react';
import { api } from './api';
import { ClarificationEditor } from './ClarificationEditor';
import { RequirementsView } from './RequirementsView';
import { SummaryReview } from './SummaryReview';
import { WorkflowJourney } from './WorkflowJourney';
import type { Analysis, Page, Project } from './workspaceTypes';

const pages: Page[] = ['Dashboard', 'Requirements', 'Clarifications', 'Requirement Summary', 'Version History'];
type Event = {version: number; state: string; created_at: string};
type Revision = {question_id: string; revision: number; value: string | string[]; created_at: string};
type Version = {version: number; created_at: string};
const friendly = (text: string) => text.toLowerCase().replaceAll('_', ' ');
const date = (text: string) => new Date(text).toLocaleString();

export function Workspace() {
  const [projects, setProjects] = useState<Project[]>([]); const [project, setProject] = useState<Project | null>(null);
  const [page, setPage] = useState<Page>('Dashboard'); const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false); const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState(''); const [saved, setSaved] = useState('Ready'); const [modal, setModal] = useState(false);
  const [events, setEvents] = useState<Event[]>([]); const [revisions, setRevisions] = useState<Revision[]>([]);
  const [versions, setVersions] = useState<Version[]>([]); const [intakes, setIntakes] = useState<{version: number; created_at: string}[]>([]);
  const [historical, setHistorical] = useState<Analysis | null>(null); const [text, setText] = useState('');
  const [validationLogs, setValidationLogs] = useState<unknown[]>([]);
  async function refresh(id?: string) {
    const rows = await api<Project[]>('/projects?limit=100'); setProjects(rows);
    setProject(current => rows.find(p => p.id === (id ?? current?.id)) ?? rows[0] ?? null);
  }
  useEffect(() => {refresh().catch(e => setError(e.message));}, []);
  useEffect(() => {
    let active = true; setHistorical(null);
    if (!project) return;
    const root = `/projects/${project.id}`;
    api<Analysis>(root + '/analysis').then(a => {if (active) setAnalysis(a);}).catch(e => {
      if (active) {setAnalysis(null); if (e.message !== 'Analysis not found') setError(e.message);}
    });
    const loads: [string, (data: never) => void][] = [
      ['/activity', setEvents], ['/answers/history', setRevisions], ['/analysis/versions', setVersions],
      ['/requirements', setIntakes], ['/validations', setValidationLogs],
    ];
    loads.forEach(([path, setter]) => api(root + path).then(data => {if (active) setter(data as never);}).catch(e => {
      if (active) setError(e.message);
    }));
    return () => {active = false;};
  }, [project?.id, project?.version]);
  useEffect(() => {if (!busy) return; const started = Date.now(); setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000); return () => clearInterval(timer);
  }, [busy]);
  useEffect(() => {
    if (!modal) return;
    const previous = document.activeElement as HTMLElement | null;
    function keys(e: KeyboardEvent) {
      if (e.key === 'Escape' && !busy) setModal(false);
      if (e.key !== 'Tab') return;
      const nodes = [...document.querySelectorAll<HTMLElement>('.modal input:not([disabled]), .modal textarea:not([disabled]), .modal button:not([disabled])')];
      if (!nodes.length) return;
      if (e.shiftKey && document.activeElement === nodes[0]) {e.preventDefault(); nodes[nodes.length-1].focus();}
      else if (!e.shiftKey && document.activeElement === nodes[nodes.length-1]) {e.preventDefault(); nodes[0].focus();}
    }
    document.addEventListener('keydown', keys);
    return () => {document.removeEventListener('keydown', keys); previous?.focus();};
  }, [modal, busy]);
  async function run(action: () => Promise<void>, rethrow = false) {
    setBusy(true); setError(''); setSaved('Processing');
    try {await action(); setSaved('Saved');} catch (e) {setSaved('Needs attention');
      if (!rethrow) setError(e instanceof Error ? e.message : 'Request failed'); if (rethrow) throw e;
    } finally {setBusy(false);}
  }
  async function action(path: string, body: unknown = {}) {
    if (!project) return;
    const data = await api<Analysis>(`/projects/${project.id}/${path}`, {...body as object, expected_version: project.version});
    setAnalysis(data); await refresh(project.id);
  }
  async function intake(event: FormEvent) {event.preventDefault(); if (!project) return;
    await run(async () => {await api(`/projects/${project.id}/requirements`, {text, expected_version: project.version});
      setText(''); await refresh(project.id);});
  }
  async function upload(file: File | undefined) {if (!file || !project) return;
    await run(async () => {if (file.size > 5 * 1024 * 1024) throw new Error('File exceeds 5 MiB.');
      const data = new FormData(); data.append('file', file); data.append('expected_version', String(project.version));
      await api(`/projects/${project.id}/uploads`, data); await refresh(project.id);});
  }
  function download(content: string, name: string, type: string) {
    const url = URL.createObjectURL(new Blob([content], {type})); const link = document.createElement('a');
    link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const shown = historical ?? analysis;
  return <div className="workspace"><aside className="sidebar"><a className="brand" href="#" onClick={() => setPage('Dashboard')}>
    <span className="brand-mark">BA</span><span>Analyst<span className="brand-sub">AGENTIC SDLC</span></span></a>
    <label className="project-switch">Workspace project<select aria-label="Workspace project" disabled={busy} value={project?.id ?? ''}
      onChange={e => {setAnalysis(null); setProject(projects.find(p => p.id === e.target.value) ?? null); setText('');}}>
      {!projects.length && <option value="">No projects yet</option>}{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    <button className="secondary new-project" disabled={busy} onClick={() => setModal(true)}>＋ New project</button>
    <nav aria-label="Workspace navigation">{pages.map((p, i) => <button key={p} className={page === p ? 'nav-item active' : 'nav-item'}
      aria-current={page === p ? 'page' : undefined} aria-label={p} onClick={() => setPage(p)}><span className="nav-icon" aria-hidden="true">{['◫','▤','☑','▧','◷'][i]}</span>{p}
      {p === 'Clarifications' && !!analysis?.questions.length && <span className="nav-count" aria-hidden="true">{analysis.questions.length}</span>}</button>)}</nav>
    <div className="sidebar-footer"><span className="status-dot"/> Business analysis workspace<p>Customer decisions. Clear requirements.</p></div></aside>
    <div className="workspace-main"><header className="topbar"><div><div className="breadcrumb">Projects / {project?.name ?? 'Get started'}</div>
      <h1>{project?.name ?? 'Your BA workspace'}</h1></div><div className="header-meta"><span className="save-state" role="status">{busy ? `Processing · ${elapsed}s` : saved}</span>
        {project && <><span className="pill">{friendly(project.state)}</span><span className="version-label">Version {project.version}</span></>}
        {project?.state === 'INTAKE' && <button disabled={busy || !intakes.length} onClick={() => void run(() => action('analyze'))}>Analyze requirements</button>}
        {analysis && <button className="secondary" disabled={busy} onClick={() => setPage(analysis.progress.summary_ready ? 'Requirement Summary' : 'Clarifications')}>
            {project?.state === 'AWAITING_ARCHITECTURE' ? 'View approved baseline' : analysis.progress.summary_ready ? 'Review draft' : 'Continue clarification'}</button>}</div></header>
      <main className="content-area"><div className="page-title"><div><span className="eyebrow">BUSINESS ANALYST AGENT</span><h2>{page}</h2>
        <p className="subtle">{({Dashboard:'A clear view of your project, decisions, and next steps.', Requirements:'Structured, traceable requirements you can review.',
          Clarifications:'Resolve one decision at a time. Your drafts stay available.', 'Requirement Summary':'Your business document, consolidated from validated decisions.',
          'Version History':'An auditable record of requirements, answers, and workflow changes.'})[page]}</p></div>
        <button className="text-button" disabled={busy} onClick={() => void refresh().catch(e => setError(e.message))}>↻ Refresh</button></div>
      {error && <div className="feedback danger" role="alert">{error}</div>}
      {busy && <div className="processing" role="status"><span className="spinner"/> Processing and validating · {elapsed}s elapsed. Results are checked before saving.</div>}
      {!project ? <section className="panel empty-state"><h2>Start with a customer requirement</h2><p>Create a project to capture a brief, clarify decisions, and build a reviewable BA document.</p>
        <button onClick={() => setModal(true)}>Create your first project</button></section> : <>
      {page === 'Dashboard' && <><WorkflowJourney project={project} analysis={analysis}/><div className="stat-grid">{[
        ['Requirements', analysis?.document.requirements.length ?? 0], ['Open gaps', analysis?.gap_statuses.filter(g => g.status !== 'RESOLVED').length ?? 0],
        ['Answered questions', analysis?.progress.answered_questions ?? 0], ['Workflow stage', friendly(project.state)],
      ].map(([label, value]) => <section className="stat-card" key={label}><span>{label}</span><strong>{value}</strong></section>)}</div>
      <div className="dashboard-grid"><section className="panel"><div className="section-heading"><h3>Requirement intake</h3><span className="pill">{intakes.length} versions</span></div>
        <p className="subtle">Paste a brief or upload a PDF, DOCX, or UTF-8 TXT file.</p>
        <form onSubmit={e => void intake(e)}><label>Customer requirements<textarea value={text} onChange={e => setText(e.target.value)} maxLength={100000}
          disabled={busy || project.state !== 'INTAKE'} placeholder="Describe the business goal, users, and expected behavior…"/></label>
          <div className="actions"><button disabled={busy || !text.trim() || project.state !== 'INTAKE'}>Save intake</button>
            <label className="upload-button">Upload document<input type="file" aria-label="Upload document" accept=".pdf,.docx,.txt"
              disabled={busy || project.state !== 'INTAKE'} onChange={e => {void upload(e.target.files?.[0]); e.target.value='';}}/></label></div></form>
        <small className="subtle">Up to 5 MiB · No OCR · Original documents are treated as untrusted input.</small>
      </section><section className="panel"><h3>Next steps</h3>{analysis ? <><p>{analysis.progress.answered_questions} of {analysis.progress.total_questions} decisions resolved.</p>
        <progress value={analysis.progress.answered_questions} max={analysis.progress.total_questions || 1}/>
        <ul className="task-list">{analysis.progress.blocking_reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
        <button onClick={() => setPage(analysis.progress.summary_ready ? 'Requirement Summary' : 'Clarifications')}>Open {analysis.progress.summary_ready ? 'summary' : 'questions'}</button>
        {analysis.needs_reconciliation && <button className="secondary" disabled={busy} onClick={() => void run(() => action('reconcile'))}>Revalidate saved analysis</button>}
      </> : <p className="subtle">Save your input, then analyze it to begin.</p>}</section></div>
      <section className="panel"><h3>Recent activity</h3><Activity events={events.slice(0,5)}/></section></>}
      {page === 'Requirements' && (analysis ? <RequirementsView analysis={analysis}/> : <EmptyAnalysis/>)}
      {analysis && <div hidden={page !== 'Clarifications'}><div className="progress-strip"><span>{analysis.progress.answered_questions} / {analysis.progress.total_questions} resolved</span>
        <progress value={analysis.progress.answered_questions} max={analysis.progress.total_questions || 1}/>
        <button className="secondary" disabled={!analysis.progress.summary_ready} onClick={() => setPage('Requirement Summary')}>Continue to summary</button></div>
        {project.state === 'AWAITING_ARCHITECTURE' ? <section className="panel"><h3>Business baseline is approved</h3><p>Clarification edits are locked. The Architecture Agent integration is pending.</p></section> :
          <ClarificationEditor key={project.id} analysis={analysis} busy={busy} submit={body => run(() => action('answers', body), true)}/>}</div>}
      {page === 'Clarifications' && !analysis && <EmptyAnalysis/>}
      {page === 'Requirement Summary' && (shown ? <SummaryReview project={project} analysis={shown}
        historical={!!historical} busy={busy} changed={() => refresh(project.id)}/> : <EmptyAnalysis/>)}
      {page === 'Version History' && <div className="history-grid"><section className="panel"><h3>Analysis versions</h3>{versions.map(v => <button className="history-row" key={v.version}
        onClick={() => void run(async () => {const old=await api<Analysis>(`/projects/${project.id}/analysis?version=${v.version}`);setHistorical(old);setPage('Requirement Summary');})}>
        <strong>Version {v.version}</strong><time>{date(v.created_at)}</time><span>View document →</span></button>)}<h3>Intake versions</h3>
        {intakes.map(v => <div className="history-row" key={v.version}><strong>Version {v.version}</strong><time>{date(v.created_at)}</time></div>)}</section>
        <section className="panel"><h3>Answer revisions</h3>{revisions.map((r,i) => <details key={i}><summary>{r.question_id} · Revision {r.revision} <time>{date(r.created_at)}</time></summary>
          <p>{Array.isArray(r.value) ? r.value.join(', ') : r.value}</p></details>)}<h3>Workflow events</h3><Activity events={events}/></section></div>}
      {analysis && <details className="diagnostics"><summary>Developer diagnostics</summary><p className="subtle">Metadata only. Original documents and prompts are not displayed.</p>
        <div className="metric-table"><div className="metric-row"><strong>Operation</strong><strong>Input</strong><strong>Output</strong><strong>Latency</strong><strong>Attempts</strong></div>
        {analysis.usage.map((u,i) => <div className="metric-row" key={i}><span>{u.operation}</span><span>{u.input_tokens}</span><span>{u.output_tokens}</span><span>{(u.latency_ms/1000).toFixed(1)}s</span><span>{u.attempts}</span></div>)}</div>
        <details><summary>Validation audit</summary><pre>{JSON.stringify(validationLogs,null,2)}</pre></details>
        <details><summary>Analysis metadata JSON</summary><pre>{JSON.stringify({analysis_version:analysis.version,
          workflow_state:analysis.state,progress:analysis.progress},null,2)}</pre></details>
        <button className="secondary" disabled={busy} onClick={() => void run(async () => {await api('/llm/health');setSaved('Model check passed');})}>Check remote model</button>
        <details><summary>Technical identifiers</summary><p>Project: {project.id}</p><p>Analysis version: {analysis.version}</p></details></details>}
      </>}</main></div>
      {modal && <div className="modal-backdrop"><section className="modal panel" role="dialog" aria-modal="true" aria-labelledby="new-project-title"><h2 id="new-project-title">Create a project</h2>
        <form onSubmit={e => {e.preventDefault(); const data = new FormData(e.currentTarget); void run(async () => {
          const p = await api<Project>('/projects', {name:data.get('name'),description:data.get('description')});
          setAnalysis(null); await refresh(p.id); setPage('Dashboard');setModal(false);});}}>
          <label>Project name<input name="name" required maxLength={200} autoFocus/></label>
          <label>Description<textarea name="description" maxLength={10000}/></label><div className="actions"><button type="button" className="secondary" onClick={() => setModal(false)}>Cancel</button>
          <button disabled={busy}>Create project</button></div></form></section></div>}
    </div>;
}
function EmptyAnalysis(){return <div className="empty-state"><h2>No analysis yet</h2><p>Save your requirements on the dashboard, then select Analyze requirements.</p></div>;}
function Activity({events}:{events:Event[]}) {return <div className="activity-list">{!events.length && <p className="subtle">No activity yet.</p>}
  {events.map(e => <div className="activity-row" key={e.version}><span className="activity-dot"/><div><strong>{friendly(e.state)}</strong><p>Version {e.version}</p></div><time>{date(e.created_at)}</time></div>)}</div>;}

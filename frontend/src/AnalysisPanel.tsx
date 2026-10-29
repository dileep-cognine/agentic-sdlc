import { useEffect, useState, type FormEvent } from 'react';
import { api } from './api';

type Project = {id: string; state: string; version: number};
type Value = string | string[];
type Question = {id: string; text: string; type: string; options: string[];
  blocking: boolean; priority: number; related_requirement_ids: string[];
  condition: {question_id: string; any_of: string[]} | null};
type Requirement = {id: string; text: string; category: string; origin: string; source_refs: string[]};
type Description = {status: string; project_overview: string; sections: Record<string, Requirement[]>;
  clarification_decisions?: {question_id: string; question: string; answer: Value}[];
  open_non_blocking_questions: Question[]};
type Analysis = {version: number; state: string; questions: Question[]; answered_questions: Question[];
  answers: Record<string, Value>; markdown: string | null; summary: Description | null;
  initial_description: Description;
  document: {overview: string; requirements: Requirement[]; gaps: {kind: string; description: string; question_ids: string[]}[]};
  sources: {id: string; location: string; text: string}[];
  usage: {input_tokens: number; output_tokens: number; latency_ms: number; attempts: number}[]};

function QuestionInput({question: q, value, busy, change}: {
  question: Question; value: Value; busy: boolean; change: (value: Value) => void;
}) {
  return <fieldset className="question" disabled={busy}><legend>{q.id} · {q.blocking ? 'Required' : 'Optional'}</legend>
    <p><strong>{q.id} · {q.text}</strong><br/><small>
      Priority {q.priority} · {q.blocking ? 'Blocking' : 'Non-blocking'} · {q.related_requirement_ids.join(', ')}
      {q.condition && ` · Conditional on ${q.condition.question_id}: ${q.condition.any_of.join(', ')}`}
    </small></p>
    {q.type === 'free_text' ? <label>Your answer<textarea maxLength={10000}
      value={value as string} onChange={e => change(e.target.value)}/></label> :
      q.type === 'multi_select' ? <fieldset><legend>Select all that apply</legend>
        {q.options.map(option => <label className="choice" key={option}><input type="checkbox"
          checked={(value as string[]).includes(option)} onChange={e => change(e.target.checked ?
            [...value as string[], option] : (value as string[]).filter(v => v !== option))}/>{option}</label>)}
      </fieldset> : <div>{q.options.map(option => <label className="choice" key={option}>
        <input type="radio" name={q.id} checked={value === option} onChange={() => change(option)}/>
        {q.type === 'yes_no' ? option === 'yes' ? 'Yes' : 'No' : option}</label>)}</div>}
  </fieldset>;
}

function QuestionForm({question: q, current, busy, save}: {
  question: Question; current?: Value; busy: boolean; save: (id: string, value: Value) => void;
}) {
  const [value, setValue] = useState<Value>(current ?? (q.type === 'multi_select' ? [] : ''));
  function submit(event: FormEvent) { event.preventDefault(); save(q.id, value); }
  return <form onSubmit={submit}><QuestionInput question={q} value={value} busy={busy} change={setValue}/>
    <button disabled={busy || !value.length}>{current === undefined ? 'Save answer' : 'Save edited answer'}</button>
  </form>;
}

function QuestionBatch({questions, busy, save}: {questions: Question[]; busy: boolean;
  save: (answers: {question_id: string; value: Value}[]) => void}) {
  const [values, setValues] = useState<Record<string, Value>>({});
  const answers = questions.filter(q => values[q.id]?.length).map(q => ({question_id: q.id, value: values[q.id]}));
  return <form onSubmit={e => {e.preventDefault(); save(answers);}}>
    {questions.map(q => <QuestionInput key={q.id} question={q} busy={busy}
      value={values[q.id] ?? (q.type === 'multi_select' ? [] : '')}
      change={value => setValues(previous => ({...previous, [q.id]: value}))}/>)}
    <button disabled={busy || !answers.length}>Save answers and continue</button>
    <p className="muted">Save this checklist together. Conditional follow-up questions may appear next.</p>
  </form>;
}

function BADescription({description}: {description: Description}) {
  return <div className="ba-description"><p className="overview">{description.project_overview}</p>
    {Object.entries(description.sections).map(([heading, requirements]) => <div key={heading}>
      <h4>{heading}</h4>{requirements.length ? <ul>{requirements.map(r => <li key={r.id}>
        {r.text} {r.origin === 'assumption' && <small className="assumption">(Assumption — needs confirmation)</small>}
      </li>)}</ul> : <p className="muted">Not specified.</p>}
    </div>)}
    {!!description.clarification_decisions?.length && <><h4>Customer decisions</h4>
      <dl>{description.clarification_decisions.map(d => <div key={d.question_id}><dt>{d.question}</dt>
        <dd>{Array.isArray(d.answer) ? d.answer.join(', ') : d.answer}</dd></div>)}</dl></>}
    {!!description.open_non_blocking_questions.length && <><h4>Open optional questions</h4>
      <ul>{description.open_non_blocking_questions.map(q => <li key={q.id}>{q.text}</li>)}</ul></>}
  </div>;
}

export function UploadPanel({project, onChanged}: {project: Project; onChanged: () => Promise<void>}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!file) return;
    const formElement = event.currentTarget;
    setBusy(true); setNotice('');
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error('File must be at most 5 MiB.');
      const data = new FormData(); data.append('file', file); data.append('expected_version', String(project.version));
      await api(`/projects/${project.id}/uploads`, data);
      await onChanged(); setFile(null); formElement.reset(); setNotice('Document extracted and saved.');
    } catch (e) { setNotice(e instanceof Error ? e.message : 'Upload failed'); }
    finally { setBusy(false); }
  }
  return <div><h3>Or upload a document</h3><p className="muted">PDF, DOCX or UTF-8 TXT · up to 5 MiB. Scanned PDFs require OCR before upload.</p>
    <form onSubmit={submit}><label>Customer document<input type="file" accept=".pdf,.docx,.txt"
      disabled={project.state !== 'INTAKE' || busy} onChange={e => setFile(e.target.files?.[0] ?? null)}/></label>
      <button disabled={!file || busy || project.state !== 'INTAKE'}>{busy ? 'Extracting…' : 'Upload and save'}</button>
    </form>{notice && <p role="status">{notice}</p>}</div>;
}

export function AnalysisPanel({project, onChanged}: {project: Project; onChanged: () => Promise<void>}) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  const [error, setError] = useState('');
  const [health, setHealth] = useState('');
  const [versions, setVersions] = useState<{version: number}[]>([]);
  const [historical, setHistorical] = useState<Analysis | null>(null);
  useEffect(() => {
    let active = true;
    api<Analysis>(`/projects/${project.id}/analysis`).then(data => { if (active) setAnalysis(data); })
      .catch(e => { if (active && e.message !== 'Analysis not found') setError(e.message); });
    api<{version: number}[]>(`/projects/${project.id}/analysis/versions?limit=100`)
      .then(data => { if (active) setVersions(data); }).catch(() => {});
    return () => { active = false; };
  }, [project.id, project.version]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setHistorical(null);
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : 'Analysis failed'); }
    finally { setBusy(false); }
  }
  async function analyze() {
    const data = await api<Analysis>(`/projects/${project.id}/analyze`, {expected_version: project.version});
    setAnalysis(data); await onChanged();
  }
  async function saveAnswers(answers: {question_id: string; value: Value}[]) {
    const data = await api<Analysis>(`/projects/${project.id}/answers`, {
      expected_version: project.version, answers,
    });
    setAnalysis(data); await onChanged();
  }
  function download(value: string, filename: string, type: string) {
    const url = URL.createObjectURL(new Blob([value], {type}));
    const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const shown = historical ?? analysis;
  return <div className="analysis"><h3>Requirement analysis</h3>
    <div className="actions"><button disabled={busy} onClick={() => void run(async () => {
      await api('/llm/health'); setHealth('Remote model is reachable and passed a small JSON-schema probe. Analyze input to verify the full workflow.');
    })}>Check remote model</button>
    {project.state === 'INTAKE' && <button disabled={busy} onClick={() => void run(analyze)}>Analyze latest input</button>}</div>
    {health && <p role="status">{health}</p>}
    {busy && <p role="status">Waiting for the remote model — {elapsed}s elapsed. Results appear after validation completes.</p>}
    {error && <p role="alert" className="notice error">{error}</p>}
    {shown && <><p>Analysis version {shown.version} · {shown.markdown ? 'DRAFT — awaiting customer review' : 'Waiting for clarification'}</p>
      <label>View analysis version<select disabled={busy} value={historical?.version ?? ''} onChange={e => {
        if (!e.target.value) { setHistorical(null); return; }
        void run(async () => setHistorical(await api<Analysis>(`/projects/${project.id}/analysis?version=${e.target.value}`)));
      }}><option value="">Current version</option>{versions.map(v => <option key={v.version} value={v.version}>Version {v.version}</option>)}</select></label>
      <div className="initial-understanding"><h3>1. Initial BA understanding</h3>
        <p className="muted">This is the agent's initial reading of your requirements. Unconfirmed assumptions are marked below.</p>
        {shown.initial_description ? <BADescription description={shown.initial_description}/> : <p>{shown.document.overview}</p>}</div>
      {!historical && <><h3>2. Clarification checklist</h3><p className="muted">Up to five questions per batch. Choose options below to refine the description.</p>
        {!shown.questions.length && <p>Required clarifications are complete.</p>}
        {!!shown.questions.length && <QuestionBatch key={`${project.id}-${shown.version}`} questions={shown.questions}
          busy={busy} save={answers => void run(() => saveAnswers(answers))}/>}
        {!!shown.answered_questions.length && <details><summary>Edit saved answers</summary>
          {shown.answered_questions.map(q => <QuestionForm key={`${q.id}-${JSON.stringify(shown.answers[q.id])}`}
            question={q} current={shown.answers[q.id]} busy={busy}
            save={(id, value) => void run(() => saveAnswers([{question_id: id, value}]))}/>)}
          <p>Changing a conditional parent clears dependent answers and creates a new analysis version.</p>
        </details>}</>}
      <details><summary>Structured requirements and evidence</summary><p>{shown.document.overview}</p>
        {shown.document.requirements.map(r => <div className="requirement" key={r.id}><strong>{r.id} · {r.category} · {r.origin}</strong>
          <p>{r.text}</p><small>Sources: {r.source_refs.join(', ') || 'Assumption without source'}</small></div>)}
        <h4>Initial gap and conflict findings</h4>{shown.document.gaps.map((g, i) => <p key={i}><strong>{g.kind}</strong>: {g.description} ({g.question_ids.join(', ')})</p>)}
        <h4>Source references</h4>{shown.sources.map(s => <details key={s.id}><summary>{s.id} · {s.location}</summary><pre>{s.text}</pre></details>)}
      </details>
      {shown.markdown && shown.summary && <><h3>3. Complete BA project description</h3>
        <p className="notice">Required clarifications resolved. This complete description remains DRAFT for your review.</p>
        <BADescription description={shown.summary}/><div className="actions">
        <button onClick={() => download(shown.markdown!, `requirements-v${shown.version}.md`, 'text/markdown')}>Download Markdown</button>
        <button onClick={() => download(JSON.stringify(shown.summary, null, 2), `requirements-v${shown.version}.json`, 'application/json')}>Download JSON</button>
      </div><details><summary>View Markdown source</summary><pre className="summary">{shown.markdown}</pre></details></>}
      <p className="muted">LLM usage across this analysis: {shown.usage.reduce((n, u) => n + u.input_tokens, 0)} input tokens · {' '}
        {shown.usage.reduce((n, u) => n + u.output_tokens, 0)} output tokens · {' '}
        {shown.usage.reduce((n, u) => n + u.latency_ms, 0)} ms</p>
    </>}
  </div>;
}

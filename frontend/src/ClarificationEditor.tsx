import { useEffect, useState } from 'react';
import type { Analysis, Question, Value } from './workspaceTypes';

export function ClarificationEditor({analysis: a, busy, submit}: {analysis: Analysis; busy: boolean;
  submit: (body: unknown) => Promise<void>}) {
  const [editing, setEditing] = useState('');
  const [values, setValues] = useState<Record<string, Value>>({});
  const [confirm, setConfirm] = useState(false); const [reason, setReason] = useState('');
  const q = a.document.questions.find(q => q.id === editing) ?? a.questions[0];
  const [localError, setLocalError] = useState(''); const [draftSaved, setDraftSaved] = useState(false);
  useEffect(() => { setConfirm(false); setReason(''); setLocalError(''); setDraftSaved(false); }, [q?.id]);
  useEffect(() => {if (editing && a.answer_feedback[editing] &&
    (a.answer_feedback[editing].status === 'VALID' || a.answer_feedback[editing].confirmed_by_customer) &&
    !a.questions.some(q => q.id === editing)) setEditing('');}, [a.version]);
  if (!q) return <div className="empty-state"><h2>Required questions are resolved</h2><p>Review the draft summary or edit a previous decision below.</p>
    <label>Edit a saved answer<select value={editing} onChange={e => setEditing(e.target.value)}><option value="">Select a question</option>
      {a.answered_questions.map(q => <option key={q.id} value={q.id}>{q.id} · {q.text}</option>)}</select></label></div>;
  const value = values[q.id] ?? a.answers[q.id] ?? (q.type === 'multi_select' ? [] : '');
  const feedback = a.answer_feedback[q.id];
  async function save(draft: boolean) {
    setLocalError(''); setDraftSaved(false);
    if (!value.length || typeof value === 'string' && !value.trim()) {setLocalError('Enter an answer before saving.'); return;}
    if (confirm && !reason.trim()) {setLocalError('Explain why you want to confirm this uncertain decision.'); return;}
    try { await submit({draft, answers: [{question_id: q.id, value, question_version: a.version,
      confirm, confirmation_reason: reason}]}); setDraftSaved(draft); }
    catch (error) {setLocalError(error instanceof Error ? error.message : 'Could not save. Your text is preserved.');}
  }
  return <div className="clarification-layout"><div className="question-queue" aria-label="Question navigation">
    {a.questions.map(item => <button key={item.id} className={item.id === q.id ? 'queue-item selected' : 'queue-item'}
      disabled={busy} onClick={() => setEditing(item.id)}><span>{item.id}</span>{item.text}</button>)}
    <label>Edit previous answer<select value={editing} onChange={e => setEditing(e.target.value)}><option value="">Current question</option>
      {a.answered_questions.map(q => <option key={q.id} value={q.id}>{q.id} · {q.text}</option>)}</select></label>
  </div><section className="panel question-editor"><div className="section-heading"><span className="pill">{q.id}</span>
    <span className={q.blocking ? 'pill amber' : 'pill'}>{q.blocking ? 'Required' : 'Optional'} · Priority {q.priority}</span></div>
    <h2>{q.text}</h2><p className="subtle">{q.why_it_matters || a.gap_statuses?.find(g => g.question_ids?.includes(q.id))?.description ||
      'This decision helps keep the business requirements specific and avoids assumptions about your project.'}</p>
    <form onSubmit={e => {e.preventDefault(); void save(false);}}><fieldset disabled={busy} aria-describedby={`feedback-${q.id}`}>
      <legend className="sr-only">{q.text}</legend>
      <QuestionControl question={q} value={value} change={v => setValues(old => ({...old, [q.id]: v}))}/>
      {feedback && <div id={`feedback-${q.id}`} role="status" className={`feedback ${feedback.status === 'VALID' ? 'good' : 'warning'}`}>
        <strong>{feedback.confirmed_by_customer ? 'Explicitly confirmed · ' : ''}{feedback.status.replaceAll('_', ' ')}</strong>
        <p>{feedback.reason}</p>{feedback.suggested_clarification && <p>{feedback.suggested_clarification}</p>}</div>}
      {feedback && ['NEEDS_REVIEW', 'INCOMPLETE'].includes(feedback.status) && <div className="confirmation">
        <label className="choice"><input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)}/>
          I explicitly confirm this decision despite the recorded uncertainty.</label>
        {confirm && <label>Confirmation rationale<textarea value={reason} onChange={e => setReason(e.target.value)} maxLength={2000}/></label>}
        <small>Confirmation is audited. Gibberish, contradictions, and undecided answers cannot bypass validation.</small></div>}
    </fieldset>
    {localError && <p className="feedback danger" role="alert">{localError}</p>}
    {draftSaved && <p role="status">Draft saved. This does not resolve the question.</p>}
    <div className="actions"><button type="button" className="secondary" disabled={busy} onClick={() => void save(true)}>Save draft</button>
      <button disabled={busy}>{busy ? 'Validating…' : 'Validate and continue'}</button></div></form>
  </section></div>;
}

export function QuestionControl({question: q, value, change}: {question: Question; value: Value; change: (value: Value) => void}) {
  if (q.type === 'free_text') return <label>Your answer<textarea aria-label="Your answer" value={value as string} maxLength={10000}
    placeholder="Describe the business decision clearly…" onChange={e => change(e.target.value)}/></label>;
  return <div className="option-list">{q.options.map(option => <label className="option" key={option}>
    <input type={q.type === 'multi_select' ? 'checkbox' : 'radio'} name={q.id}
      checked={Array.isArray(value) ? value.includes(option) : value === option}
      onChange={e => change(q.type === 'multi_select' ? e.target.checked ? [...value as string[], option] :
        (value as string[]).filter(v => v !== option) : option)}/><span>{option}</span></label>)}</div>;
}

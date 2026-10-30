import { useEffect, useState } from 'react';
import { api } from './api';
import { MarkdownDocument } from './MarkdownDocument';
import type { Analysis, Project } from './workspaceTypes';

type Review = {status: string; analysis_version: number; summary_revision: number; can_approve: boolean;
  blockers: string[]; markdown: string | null; summary: {project_overview: string; review_notes?: string} | null;
  approval: {reviewer: string; content_hash: string; created_at: string} | null;
  handoff: {status: string; message: string} | null;
  revisions: {revision: number; reviewer: string; created_at: string}[]};

export function SummaryReview({project, analysis, historical, busy, changed}: {
  project: Project; analysis: Analysis; historical: boolean; busy: boolean; changed: () => Promise<void>;
}) {
  const [review, setReview] = useState<Review | null>(null); const [editing, setEditing] = useState(false);
  const [overview, setOverview] = useState(''); const [notes, setNotes] = useState('');
  const [reviewer, setReviewer] = useState(''); const [confirmed, setConfirmed] = useState(false);
  const [feedback, setFeedback] = useState(''); const [localBusy, setLocalBusy] = useState(false); const [error, setError] = useState('');
  useEffect(() => {
    let current = true; setReview(null);setEditing(false);setConfirmed(false);
    if (historical) return;
    api<Review>(`/projects/${project.id}/summary-review`).then(data => {
      if (current) {setReview(data);setOverview(data.summary?.project_overview ?? '');setNotes(data.summary?.review_notes ?? '');}
    }).catch(e => {if (current) setError(e.message);});
    return () => {current=false;};
  }, [project.id, project.version, analysis.version, historical]);
  async function send(path: string, body: object) {
    setLocalBusy(true);setError('');
    try {await api(`/projects/${project.id}/${path}`, {...body, expected_version:project.version,analysis_version:analysis.version});
      await changed();setConfirmed(false);setEditing(false);
    } catch(e) {setError(e instanceof Error ? e.message : 'Request failed');} finally {setLocalBusy(false);}
  }
  function download(text: string, file: string, type: string) {
    const url=URL.createObjectURL(new Blob([text],{type}));const link=document.createElement('a');
    link.href=url;link.download=file;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  const locked=busy||localBusy; const markdown=historical?analysis.markdown:review?.markdown??analysis.markdown;
  const status=historical?(analysis.summary as {status?:string}|null)?.status??'DRAFT':review?.status??'DRAFT';
  return <><div className="section-heading"><div><span className={`pill ${status==='APPROVED'?'approved':'amber'}`}>{status}</span>
    <span className="version-label"> Analysis {analysis.version} · Summary revision {review?.summary_revision??0}</span></div>
    <div className="actions"><button className="secondary" disabled={!markdown} onClick={()=>download(markdown!,`business-summary-v${analysis.version}.md`,'text/markdown')}>Download Markdown</button>
      <button disabled={!(review?.summary??analysis.summary)} onClick={()=>download(JSON.stringify(review?.summary??analysis.summary,null,2),`business-summary-v${analysis.version}.json`,'application/json')}>Export JSON</button></div></div>
    {error&&<div role="alert" className="feedback danger">{error}</div>}
    {!analysis.progress.summary_ready&&<div className="feedback warning"><strong>Draft is incomplete</strong>
      <ul>{analysis.progress.blocking_reasons.map(r=><li key={r}>{r}</li>)}</ul></div>}
    {review?.approval&&<div className="feedback good"><strong>Business requirements approved by {review.approval.reviewer}</strong>
      <p>{review.handoff?.message}</p><p>Architecture design and architecture approval remain separate. Epics, stories and tasks are locked until an approved architecture baseline exists.</p>
      <details><summary>Baseline traceability</summary><p>SHA-256: {review.approval.content_hash}</p></details></div>}
    <section className="panel document-panel">{markdown?<MarkdownDocument text={markdown}/>:<><h1>Working business requirements</h1>
      <p>{analysis.working_description.project_overview}</p>{Object.entries(analysis.working_description.sections).filter(([,r])=>r.length).map(([heading,rows])=><div key={heading}><h2>{heading}</h2><ul>{rows.map(r=><li key={r.id}>{r.text}</li>)}</ul></div>)}</>}</section>
    {!historical&&review?.can_approve&&<section className="panel"><h3>Review the business understanding</h3>
      <p className="subtle">Editorial changes can refine the overview and add review notes. Changes to business requirements must return through clarification.</p>
      <button className="secondary" disabled={locked} onClick={()=>setEditing(!editing)}>{editing?'Cancel editing':'Edit overview and review notes'}</button>
      {editing&&<form onSubmit={e=>{e.preventDefault();void send('summary-revisions',{overview,review_notes:notes,reviewer});}}>
        <label>Project overview<textarea value={overview} onChange={e=>setOverview(e.target.value)} maxLength={5000} required/></label>
        <label>Review notes<textarea value={notes} onChange={e=>setNotes(e.target.value)} maxLength={5000}/></label>
        <label>Reviewer name<input value={reviewer} onChange={e=>setReviewer(e.target.value)} maxLength={200} required/></label>
        <button disabled={locked}>Save new summary revision</button></form>}
      <hr/><h4>Request business changes</h4><label>What needs to change?<textarea value={feedback} onChange={e=>setFeedback(e.target.value)} maxLength={1800}/></label>
      <button className="secondary" disabled={locked||!feedback.trim()} onClick={()=>void send('summary-changes',{feedback})}>Return to clarification</button>
      <hr/><h4>Approve this exact summary revision</h4><label>Reviewer name<input value={reviewer} onChange={e=>setReviewer(e.target.value)} maxLength={200}/></label>
      <label className="choice"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>
        I confirm that this summary accurately represents the business requirements. This does not approve technical design.</label>
      <button disabled={locked||editing||!confirmed||!reviewer.trim()} onClick={()=>void send('summary-approval',{
        summary_revision:review.summary_revision,reviewer,confirm_business_understanding:true})}>Approve business summary</button>
      <small className="subtle">The approval freezes this version and creates a durable architecture handoff. It does not execute an Architecture Agent.</small>
    </section>}
    {!historical&&!!review?.revisions?.length&&<details><summary>Summary editorial history</summary>{review.revisions.map(r=><p key={r.revision}>Summary revision {r.revision} · {r.reviewer} · {new Date(r.created_at).toLocaleString()}</p>)}</details>}
  </>;
}

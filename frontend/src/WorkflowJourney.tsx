import type { Analysis, Project } from './workspaceTypes';

export function WorkflowJourney({project,analysis}: {project: Project; analysis: Analysis|null}) {
  const approved=project.state==='AWAITING_ARCHITECTURE';
  const steps=[
    ['1','Requirements intake','BRD, PDF, DOCX or text',analysis?'done':'current'],
    ['2','Analyze and clarify','Parse, chunk, extract, resolve gaps',analysis?(analysis.progress.summary_ready?'done':'current'):'waiting'],
    ['3','Business summary approval','Human review of business understanding',approved?'done':analysis?.progress.summary_ready?'current':'waiting'],
    ['4','Architecture baseline',approved?'Handoff saved · integration pending':'Separate Architecture Agent',approved?'pending':'planned'],
    ['5','Architecture approval','Technical review · not implemented','planned'],
    ['6','BA delivery artifacts','Epics, stories, criteria and tasks · locked','planned'],
  ];
  return <section className="journey" aria-label="Agent workflow"><div className="section-heading"><h3>Project journey</h3><span className="subtle">Business understanding → approved architecture → BA artifacts</span></div>
    <ol>{steps.map(([number,title,detail,status])=><li className={`journey-step ${status}`} key={number}><span className="step-number">{status==='done'?'✓':number}</span><div><strong>{title}</strong><small>{detail}</small></div></li>)}</ol>
  </section>;
}

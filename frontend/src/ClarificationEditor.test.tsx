import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ClarificationEditor, QuestionControl } from './ClarificationEditor';
import { MarkdownDocument } from './MarkdownDocument';
import type { Analysis, Question } from './workspaceTypes';
afterEach(cleanup);
it('labels a saved draft separately from semantic uncertainty',()=>{
  const a=data();a.answers={Q001:'Customers use email and password.'};
  a.answer_feedback={Q001:{status:'INCOMPLETE',reason:'Draft saved; not submitted for validation.',
    suggested_clarification:'Submit when ready.',confirmed_by_customer:false,confirmation_reason:''}};
  render(<ClarificationEditor analysis={a} busy={false} submit={vi.fn()}/>);
  expect(screen.getByText('SAVED DRAFT — NOT VALIDATED')).toBeTruthy();
  expect(screen.queryByRole('checkbox')).toBeNull();
});

it('preserves answer text and displays model validation errors',async()=>{
  const submit=vi.fn().mockRejectedValue(new Error('The model could not quote supporting evidence.'));
  render(<ClarificationEditor analysis={data()} busy={false} submit={submit}/>);
  fireEvent.change(screen.getByLabelText('Your answer'),{target:{value:'Customers use email and password.'}});
  fireEvent.click(screen.getByRole('button',{name:'Validate and continue'}));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect((screen.getByLabelText('Your answer') as HTMLTextAreaElement).value).toBe('Customers use email and password.');
});
const question: Question={id:'Q001',text:'How should customers authenticate?',type:'free_text',options:[],blocking:true,priority:1,related_requirement_ids:['R001'],condition:null};
function data(): Analysis{return {version:3,document:{questions:[question],requirements:[]},questions:[question],answered_questions:[],answers:{},answer_feedback:{}} as unknown as Analysis;}
it('preserves entered text when a semantic review is unclear',async()=>{
  const a=data();const submit=vi.fn().mockResolvedValue(undefined);const view=render(<ClarificationEditor analysis={a} busy={false} submit={submit}/>);
  fireEvent.change(screen.getByLabelText('Your answer'),{target:{value:'fgh'}});fireEvent.click(screen.getByRole('button',{name:'Validate and continue'}));
  await waitFor(()=>expect(submit).toHaveBeenCalledOnce());
  view.rerender(<ClarificationEditor analysis={{...a,version:4,answers:{Q001:'fgh'},answer_feedback:{Q001:{status:'UNCLEAR',reason:'Specify an authentication method.',suggested_clarification:'Describe the login policy.',confirmed_by_customer:false,confirmation_reason:''}}}} busy={false} submit={submit}/>);
  expect((screen.getByLabelText('Your answer') as HTMLTextAreaElement).value).toBe('fgh');expect(screen.getByText('Specify an authentication method.')).toBeTruthy();expect(screen.queryByText(/I explicitly confirm/)).toBeNull();
});
it('saves drafts with the question version',async()=>{
  const submit=vi.fn().mockResolvedValue(undefined);render(<ClarificationEditor analysis={data()} busy={false} submit={submit}/>);
  fireEvent.change(screen.getByLabelText('Your answer'),{target:{value:'Email/password; admins SSO'}});fireEvent.click(screen.getByRole('button',{name:'Save draft'}));
  await waitFor(()=>expect(submit).toHaveBeenCalledWith(expect.objectContaining({draft:true,answers:[expect.objectContaining({question_version:3})]})));
});
it('validates required input locally',()=>{
  const submit=vi.fn();render(<ClarificationEditor analysis={data()} busy={false} submit={submit}/>);fireEvent.click(screen.getByRole('button',{name:'Validate and continue'}));
  expect(screen.getByRole('alert').textContent).toContain('Enter an answer');expect(submit).not.toHaveBeenCalled();
});
it('requires rationale for explicit confirmation',()=>{
  const a=data();a.answers={Q001:'An unusual policy'};a.answer_feedback={Q001:{status:'NEEDS_REVIEW',reason:'Please confirm.',suggested_clarification:'Explain intention.',confirmed_by_customer:false,confirmation_reason:''}};
  const submit=vi.fn();render(<ClarificationEditor analysis={a} busy={false} submit={submit}/>);fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'Validate and continue'}));
  expect(screen.getByRole('alert').textContent).toContain('Explain why');expect(submit).not.toHaveBeenCalled();
});
it('uses accessible selection controls',()=>{
  const change=vi.fn();const q={...question,type:'single_select',options:['Password','SSO']};const view=render(<QuestionControl question={q} value="" change={change}/>);
  fireEvent.click(screen.getByLabelText('SSO'));expect(change).toHaveBeenCalledWith('SSO');view.rerender(<QuestionControl question={{...q,type:'multi_select'}} value={['Password']} change={change}/>);
  fireEvent.click(screen.getByLabelText('SSO'));expect(change).toHaveBeenCalledWith(['Password','SSO']);
});
it('renders Markdown without executing embedded HTML',()=>{
  const view=render(<MarkdownDocument text={'# Draft requirements\n- **R001** Customers shall sign in.\n<script>alert(1)</script>'}/>);
  expect(screen.getByRole('heading',{name:'Draft requirements'})).toBeTruthy();expect(view.container.querySelector('strong')?.textContent).toBe('R001');expect(view.container.querySelector('script')).toBeNull();
});

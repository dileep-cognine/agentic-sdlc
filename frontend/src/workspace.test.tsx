import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Workspace } from './Workspace';
import { api } from './api';

vi.mock('./api', () => ({api: vi.fn()}));
afterEach(() => {cleanup();vi.clearAllMocks();});
it('provides working project navigation and searchable requirement cards', async () => {
  vi.mocked(api).mockImplementation(async path => {
    if (path.startsWith('/projects?')) return [{id:'p1',name:'Customer portal',description:'A portal',state:'AWAITING_CLARIFICATION',version:4}];
    if (path.endsWith('/analysis')) return {version:1,state:'AWAITING_CLARIFICATION',document:{requirements:[{
      id:'R001',title:'Customer login',text:'Customers shall authenticate using email and password.',category:'functional',origin:'stated',
      classification:'STATED',resolution:'ACTIVE',source_refs:['S1']}],questions:[]},questions:[],answered_questions:[],answers:{},answer_feedback:{},
      progress:{total_questions:1,answered_questions:0,summary_ready:false,blocking_reasons:['Authentication policy is missing.']},
      working_description:{project_overview:'A customer portal',sections:{}},gap_statuses:[{id:'G001',description:'Authentication missing',status:'OPEN'}],usage:[],needs_reconciliation:false};
    return [];
  });
  render(<Workspace/>);
  await waitFor(() => expect(screen.getByRole('heading',{name:'Customer portal'})).toBeTruthy());
  for (const label of ['Dashboard','Requirements','Clarifications','Requirement Summary','Version History']) {
    expect(screen.getByRole('button',{name:label})).toBeTruthy();
  }
  fireEvent.click(screen.getByRole('button',{name:'Requirements'}));
  expect(await screen.findByRole('heading',{name:'Customer login'})).toBeTruthy();
  fireEvent.change(screen.getByPlaceholderText('Search requirements…'),{target:{value:'does not exist'}});
  expect(screen.getByText('No requirements match these filters.')).toBeTruthy();
});
it('keeps summary export disabled while blocking questions remain', async () => {
  vi.mocked(api).mockImplementation(async path => {
    if (path.startsWith('/projects?')) return [{id:'p1',name:'Portal',state:'AWAITING_CLARIFICATION',version:4}];
    if (path.endsWith('/analysis')) return {version:1,document:{requirements:[],questions:[]},questions:[],answered_questions:[],
      answers:{},answer_feedback:{},progress:{total_questions:1,answered_questions:0,summary_ready:false,blocking_reasons:['Confirm the access policy.']},
      gap_statuses:[],working_description:{project_overview:'Portal',sections:{}},usage:[],markdown:null,summary:null};
    return [];
  });
  render(<Workspace/>);
  await waitFor(() => expect(screen.getByRole('heading',{name:'Portal'})).toBeTruthy());
  fireEvent.click(screen.getByRole('button',{name:'Requirement Summary'}));
  expect(await screen.findByText('Draft is incomplete')).toBeTruthy();
  expect((screen.getByRole('button',{name:'Export JSON'}) as HTMLButtonElement).disabled).toBe(true);
});

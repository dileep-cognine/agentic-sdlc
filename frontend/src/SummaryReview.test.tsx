import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {SummaryReview} from './SummaryReview';
import {api} from './api';
import type {Analysis, Project} from './workspaceTypes';

vi.mock('./api', () => ({api: vi.fn()}));
afterEach(() => {cleanup();vi.clearAllMocks();});

it('requires explicit business confirmation and submits the reviewed revision', async () => {
  vi.mocked(api).mockResolvedValue({status:'DRAFT',summary_revision:2,can_approve:true,
    summary:{project_overview:'Portal'},markdown:'# Portal',blockers:[],revisions:[]});
  const changed=vi.fn().mockResolvedValue(undefined);
  render(<SummaryReview project={{id:'p1',version:8} as Project}
    analysis={{version:3,progress:{summary_ready:true},markdown:'# Portal'} as Analysis}
    historical={false} busy={false} changed={changed}/>);
  const approve=await screen.findByRole('button',{name:'Approve business summary'});
  expect((approve as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Reviewer name'),{target:{value:'Customer'}});
  expect((approve as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(approve);
  await waitFor(()=>expect(api).toHaveBeenCalledWith('/projects/p1/summary-approval',{
    expected_version:8,analysis_version:3,summary_revision:2,reviewer:'Customer',confirm_business_understanding:true}));
  expect(changed).toHaveBeenCalledOnce();
});

it('shows the architecture boundary after approval', async () => {
  vi.mocked(api).mockResolvedValue({status:'APPROVED',summary_revision:0,can_approve:false,
    summary:{project_overview:'Portal'},markdown:'# Portal',revisions:[],
    approval:{reviewer:'Customer',content_hash:'abc'},
    handoff:{status:'PENDING_INTEGRATION',message:'Architecture integration pending.'}});
  render(<SummaryReview project={{id:'p1',version:9} as Project}
    analysis={{version:3,progress:{summary_ready:true},markdown:'# Portal'} as Analysis}
    historical={false} busy={false} changed={vi.fn()}/>);
  expect(await screen.findByText('Architecture integration pending.')).toBeTruthy();
  expect(screen.queryByRole('button',{name:'Approve business summary'})).toBeNull();
});

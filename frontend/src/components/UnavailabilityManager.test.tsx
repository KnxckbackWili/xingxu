import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import UnavailabilityManager from './UnavailabilityManager'
import { availabilityApi } from '../api'
vi.mock('../api', () => ({ availabilityApi: { listUnavailability: vi.fn(), updateUnavailability: vi.fn(), deleteUnavailability: vi.fn() } }))
vi.mock('../api/client', () => ({ errMsg: () => '请求失败，请重试' }))
const period = { id: 'a1', start_date: '2026-01-02', end_date: '2027-02-03', reason: '请假', note: '原备注' }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(availabilityApi.listUnavailability).mockResolvedValue([period]); vi.mocked(availabilityApi.updateUnavailability).mockResolvedValue(period); vi.mocked(availabilityApi.deleteUnavailability).mockResolvedValue({}) })
function setup() { const changed = vi.fn(); const close = vi.fn(); render(<ConfigProvider theme={{ token: { motion: false } }}><UnavailabilityManager people={[{ id: 'u1', name: '王工' }, { id: 'u2', name: '李工' }]} onChanged={changed} onClose={close} /></ConfigProvider>); return { changed, close } }
async function selectPerson(name = '王工') { fireEvent.mouseDown(screen.getByRole('combobox', { name: '管理人员' })); fireEvent.click(await screen.findByText(name, { selector: '.ant-select-item-option-content' })) }
it('loads all dates and preserves the edit draft on error, then saves corrected details and refreshes', async () => {
 const { changed } = setup(); await selectPerson(); fireEvent.click(await screen.findByRole('button', { name: '编辑时段' }));
 const dialog = screen.getByLabelText('备注').closest('[role=dialog]') as HTMLElement;
 expect(within(dialog).getByPlaceholderText('Start date')).toHaveValue('2026-01-02'); expect(within(dialog).getByPlaceholderText('End date')).toHaveValue('2027-02-03')
 fireEvent.change(within(dialog).getByLabelText('备注'), { target: { value: '更正后备注' } });
 vi.mocked(availabilityApi.updateUnavailability).mockRejectedValueOnce(new Error('offline'));
 fireEvent.click(within(dialog).getByRole('button', { name: '保 存' }));
 await waitFor(() => expect(screen.getByText('请求失败，请重试')).toBeVisible()); expect(within(dialog).getByLabelText('备注')).toHaveValue('更正后备注'); expect(changed).not.toHaveBeenCalled();
 fireEvent.click(within(dialog).getByRole('button', { name: '保 存' })); await waitFor(() => expect(changed).toHaveBeenCalledOnce());
 expect(availabilityApi.updateUnavailability).toHaveBeenLastCalledWith('u1', 'a1', { start_date: '2026-01-02', end_date: '2027-02-03', reason: '请假', note: '更正后备注' });
})
it('requires confirmation, retains the period on deletion failure, and suppresses repeated submission', async () => {
 const { changed } = setup(); await selectPerson(); fireEvent.click(await screen.findByRole('button', { name: '取消时段' }));
 fireEvent.click(screen.getByRole('button', { name: '保留时段' })); await waitFor(() => expect(screen.queryByRole('button', { name: '保留时段' })).not.toBeInTheDocument()); expect(availabilityApi.deleteUnavailability).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button', { name: '取消时段' })); vi.mocked(availabilityApi.deleteUnavailability).mockRejectedValueOnce(new Error('offline'));
 fireEvent.click(screen.getByRole('button', { name: '确认取消时段' })); await waitFor(() => expect(screen.getByText('请求失败，请重试')).toBeVisible()); expect(screen.getByRole('button', { name: '保留时段' })).toBeInTheDocument(); expect(changed).not.toHaveBeenCalled();
 let finish!: (value: any) => void; vi.mocked(availabilityApi.deleteUnavailability).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }));
 const confirm = screen.getByRole('button', { name: '确认取消时段' }); fireEvent.click(confirm); fireEvent.click(confirm);
 await waitFor(() => expect(availabilityApi.deleteUnavailability).toHaveBeenCalledTimes(2)); expect(screen.getByRole('button', { name: '保留时段' })).toBeDisabled();
 await act(async () => finish({})); expect(await screen.findByText('该人员暂无不可用时段')).toBeVisible(); expect(changed).toHaveBeenCalledOnce();
})
it('discards an abandoned edit and reloads original values when reopened', async () => {
 setup(); await selectPerson(); fireEvent.click(await screen.findByRole('button', { name: '编辑时段' })); fireEvent.change(screen.getByLabelText('备注'), { target: { value: '未保存草稿' } }); fireEvent.click(screen.getByRole('button', { name: '放弃修改' }));
 fireEvent.click(screen.getByRole('button', { name: '编辑时段' })); expect(screen.getByLabelText('备注')).toHaveValue('原备注'); expect(availabilityApi.updateUnavailability).not.toHaveBeenCalled();
})
it('retries failed reads and ignores a stale person response after selection changes', async () => {
 let finish!: (value: any) => void; vi.mocked(availabilityApi.listUnavailability).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([]);
 setup(); await selectPerson(); await selectPerson('李工'); await waitFor(() => expect(screen.getByText('请求失败，请重试')).toBeVisible());
 await act(async () => finish([period])); expect(screen.queryByRole('button', { name: '编辑时段' })).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: '重 试' })); expect(await screen.findByText('该人员暂无不可用时段')).toBeVisible(); expect(availabilityApi.listUnavailability).toHaveBeenLastCalledWith('u2');
})

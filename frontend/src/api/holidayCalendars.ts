import { api } from './client'

export interface AnnualCalendar {
  year: number; available: boolean; source_kind: 'bundled_official' | 'maintained' | 'missing'
  holidays: string[]; workdays: string[]; version: number
  source_name: string; source_url: string; published_on: string | null; note: string
}
export interface CalendarWrite {
  year: number; holidays: string[]; workdays: string[]; source_name: string
  source_url: string; published_on: string; note: string; complete: true; expected_version: number
}
export const holidayCalendarsApi = {
  get: async (year: number): Promise<AnnualCalendar> => (await api.get(`/holiday-calendars/${year}`)).data,
  save: async (year: number, body: CalendarWrite): Promise<AnnualCalendar> => (await api.put(`/holiday-calendars/${year}`, body)).data,
}

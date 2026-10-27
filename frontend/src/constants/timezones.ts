/** 项目现场时区选项（P2-体验：俄/越等海外现场）。 */

export const TIMEZONE_OPTIONS: Array<{ label: string; value: string }> = [
  { label: '上海 (UTC+8)', value: 'Asia/Shanghai' },
  { label: '河内/胡志明市 (UTC+7)', value: 'Asia/Ho_Chi_Minh' },
  { label: '曼谷 (UTC+7)', value: 'Asia/Bangkok' },
  { label: '雅加达 (UTC+7)', value: 'Asia/Jakarta' },
  { label: '阿拉木图 (UTC+6)', value: 'Asia/Almaty' },
  { label: '塔什干 (UTC+5)', value: 'Asia/Tashkent' },
  { label: '莫斯科 (UTC+3)', value: 'Europe/Moscow' },
  { label: '克拉斯诺亚尔斯克 (UTC+7)', value: 'Asia/Krasnoyarsk' },
  { label: '海参崴/符拉迪沃斯托克 (UTC+10)', value: 'Asia/Vladivostok' },
  { label: '新德里 (UTC+5:30)', value: 'Asia/Kolkata' },
  { label: 'UTC', value: 'UTC' },
]

export const DEFAULT_TIMEZONE = 'Asia/Shanghai'

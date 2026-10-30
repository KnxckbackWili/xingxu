import { useEffect, useMemo, useRef, useState } from 'react'
import { Drawer, Input, type InputRef } from 'antd'
import { MoreOutlined, SearchOutlined } from '@ant-design/icons'
import { useDrawerReturnFocus } from '../../../hooks/useDrawerReturnFocus'
import { useAuth } from '../../../stores/auth'
import { hasSystemPermission } from '../../../constants/systemPermissions'
import { PROJECT_ITEM_ICON, PROJECT_NAV_ITEMS, PROJECT_DISPLAY_LABEL, PROJECT_MORE_KEYS, PROJECT_PAGE_INFO } from '../../../constants/projectNav'
import './projectNavigation.css'

export interface ProjectMenuProps {
  projectId: string
  activeParent: string
  activeChild: string | null
  onNavigate: (path: string) => void
  capabilities?: string[]
  canEditSettings?: boolean
  activeSpecial?: string
  onPrefetch?: (key: string) => void
  /** Accepted location: blocked navigation leaves the menu and input in place. */
  navigationKey?: string
}
export function ProjectMenuContent({ projectId, activeParent, activeChild, activeSpecial, onNavigate, capabilities, navigationKey, onPrefetch }: ProjectMenuProps) {
  const { user }=useAuth()
  const current=activeSpecial || activeChild || activeParent
  const [open,setOpen]=useState(false)
  const [search,setSearch]=useState('')
  const trigger=useRef<HTMLButtonElement>(null)
  const input=useRef<InputRef>(null)
  const restore=useRef(false)
  useDrawerReturnFocus(open,restore,'project-navigation-drawer',()=>trigger.current)
  const close=()=>{restore.current=true;setOpen(false)}
  const canExport=user?.permission_overrides?.['project.export']!==false && (capabilities!==undefined ? capabilities.includes('project.export') : !['worker','intern','readonly'].includes(user?.role ?? ''))
  const canAudit=hasSystemPermission(user,'system.audit.read')
  const leaves=useMemo(()=>PROJECT_NAV_ITEMS.flatMap(item=>(item.children ?? [{key:item.key,label:item.label,path:item.path}]).map(child=>({...child,parent:item.key,more:!!item.more})))
    .filter(item=>(item.key!=='export'||canExport)&&(item.key!=='history'||canAudit)),[canExport,canAudit])
  const daily=PROJECT_NAV_ITEMS.filter(item=>!item.more)
  const extras=leaves.filter(item=>item.more)
  const term=search.trim().toLocaleLowerCase()
  const found=(term?leaves:extras).filter(item=>!term||`${item.label} ${PROJECT_PAGE_INFO[item.parent]?.label ?? ''} ${PROJECT_PAGE_INFO[item.key]?.description ?? ''}`.toLocaleLowerCase().includes(term))
  const nav=(path:string)=>{
    const next=`/pm/projects/${projectId}/${path}`
    if(navigationKey===next){close();return}
    restore.current=false;onNavigate(next)
  }
  useEffect(()=>{setOpen(false);setSearch('')},[projectId,navigationKey])
  useEffect(()=>{
    const key=(event:KeyboardEvent)=>{
      const target=event.target instanceof Element?event.target:document.activeElement
      if(target?.closest('.ant-modal'))return
      if(event.key==='Escape'&&open){event.preventDefault();close();return}
      if(event.defaultPrevented||event.altKey||!(event.ctrlKey||event.metaKey)||event.key.toLowerCase()!=='k')return
      if(target?.closest('input,textarea,select,[contenteditable="true"]'))return
      event.preventDefault();restore.current=false;setSearch('');setOpen(true)
    }
    window.addEventListener('keydown',key,true);return()=>window.removeEventListener('keydown',key,true)
  },[open])
  const field=PROJECT_NAV_ITEMS.find(item=>item.key==='field')!
  return <>
    <nav className="project-daily-navigation" aria-label="项目常用功能">
      {daily.map(item=><button key={item.key} type="button" aria-current={activeParent===item.key&&!activeSpecial?'page':undefined}
        onClick={()=>nav(item.path)} onMouseEnter={()=>onPrefetch?.(item.key)} onFocus={()=>onPrefetch?.(item.key)}>{item.icon&&<span className="project-tab-icon" aria-hidden="true">{item.icon}</span>}{item.label}</button>)}
      <button ref={trigger} type="button" className="project-more-trigger" aria-haspopup="dialog" aria-expanded={open} aria-current={PROJECT_MORE_KEYS.includes(current)?'page':undefined}
        onClick={()=>{restore.current=false;setSearch('');setOpen(true)}}><MoreOutlined aria-hidden="true" />{PROJECT_MORE_KEYS.includes(current)?<>更多<span className="project-more-current">· {PROJECT_DISPLAY_LABEL[current]??''}</span></>:'更多'}</button>
    </nav>
    {activeParent==='field'&&<nav className="project-field-navigation" aria-label="现场内容">{field.children!.map(item=><button key={item.key} type="button" aria-current={activeChild===item.key?'page':undefined} onClick={()=>nav(item.path)}>{item.label}</button>)}</nav>}
    <Drawer title="更多" open={open} onClose={close} width="min(420px, calc(100vw - 16px))" rootClassName="project-navigation-drawer" destroyOnHidden afterOpenChange={value=>{if(value)input.current?.focus()}}>
      <Input ref={input} aria-label="查找项目功能" placeholder="按功能名称或用途查找" prefix={<SearchOutlined />} value={search} onChange={event=>setSearch(event.target.value)} allowClear />
      <ul className="project-more-list">{found.map(item=><li key={item.key}><button type="button" aria-label={item.label} aria-describedby={`project-more-description-${item.key}`} aria-current={current===item.key?'page':undefined} onClick={()=>nav(item.path)} onMouseEnter={()=>onPrefetch?.(item.parent)} onFocus={()=>onPrefetch?.(item.parent)}>
        <span className="project-more-icon" aria-hidden="true">{PROJECT_ITEM_ICON[item.parent]}</span><span className="project-more-copy"><strong>{item.label}</strong><small id={`project-more-description-${item.key}`}>{PROJECT_PAGE_INFO[item.key]?.description}</small></span>
      </button></li>)}</ul>
      {!found.length&&<p>没有找到功能，请按名称或用途查找。</p>}
    </Drawer>
  </>
}
export function ProjectMenuPanel(props:ProjectMenuProps){return <ProjectMenuContent {...props}/>}
export function ProjectMenuNarrow(props:ProjectMenuProps){return <ProjectMenuContent {...props}/>}
export function currentMenuLabel(parent:string,child:string|null){return PROJECT_DISPLAY_LABEL[child||parent]??'概况'}

import { useEffect, useState, useRef } from 'react';

const BASE = import.meta.env.VITE_API_BASE || '';
async function api(path, options = {}) {
  const response = await fetch(`${BASE}/api/monthly${path}`, {credentials: 'include', ...options});
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail));
  return value;
}
const json = (method, value) => ({method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(value)});
const statuses = {queued:'В очереди', processing:'Обработка', draft:'Черновик', approved:'Утверждён', failed:'Ошибка'};
const taskStatuses = ['Завершено','В работе','На согласовании','Ожидается информация','Приостановлено','Требует уточнения'];
const failureSummary = message => {
  if(message?.includes('Первичный отбор')) return 'Модель вернула неполный список решений по письмам. Проверка полноты остановила эту попытку.';
  if(message?.includes('missing field') || message?.includes('closed stdout')) return 'Процесс Codex завершился при обращении к каталогу моделей. В журнале зафиксирована несовместимость кеша моделей.';
  if(message?.includes('перезапуск')) return 'Обработка остановилась при перезапуске приложения. Промежуточный кеш сохранён.';
  return message || 'Причина не указана в журнале.';
};
const monthName = p => p ? new Date(p+'-01T12:00:00').toLocaleDateString('ru-RU',{month:'long',year:'numeric'}).replace(' г.','') : 'Отчёт';
const riskStatuses = ['Открыт','Снижен','Повышен','Реализовался','Снят','Требует уточнения'];

export default function Monthly() {
  const sourceDialog = useRef(null);
  const [settings, setSettings] = useState(null);
  const [history, setHistory] = useState([]);
  const [period, setPeriod] = useState('');
  const [baselinePeriod, setBaselinePeriod] = useState('2026-07');
  const [report, setReport] = useState(null);
  const [attempt, setAttempt] = useState(null);
  const [source, setSource] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState('tasks');
  const [query, setQuery] = useState('');
  const [section, setSection] = useState('all');
  const [showArchived, setShowArchived] = useState(false);
  const [ack, setAck] = useState(false);
  const running = report && ['queued','processing'].includes(report.status);
  const editable = report?.status === 'draft';
  async function refreshHistory() { setHistory(await api('/reports')); }
  useEffect(() => {
    api('/settings').then(s => {setSettings(s); setPeriod(s.default_period);}).catch(e => setError(e.message));
    api('/reports').then(async rows => {setHistory(rows); const latest = rows.find(r=>r.status !== 'failed'); if(latest) setReport(await api(`/reports/${latest.id}`));}).catch(e => setError(e.message));
  }, []);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => api(`/reports/${report.id}`).then(r => {
      setReport(r); if (!['queued','processing'].includes(r.status)) refreshHistory();
    }).catch(e => setError(e.message)), 2000);
    return () => clearInterval(timer);
  }, [report?.id, running]);
  useEffect(() => { const warn = e => {if(dirty){e.preventDefault();e.returnValue='';}}; window.addEventListener('beforeunload',warn); return ()=>window.removeEventListener('beforeunload',warn); }, [dirty]);
  useEffect(() => { if(source && sourceDialog.current && !sourceDialog.current.open) sourceDialog.current.showModal(); }, [source]);
  useEffect(() => { const close = e => {if(e.key==='Escape')setSource(null);}; window.addEventListener('keydown',close);return ()=>window.removeEventListener('keydown',close); }, []);
  async function action(fn) {
    setBusy(true); setError('');
    try { const r = await fn(); if (r) {setReport(r); setDirty(false); setAck(false); setSource(null);} await refreshHistory(); }
    catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  function change(kind, index, field, value) {
    setReport(r => ({...r, [kind]: r[kind].map((x,i) => i===index ? {...x,[field]:value} : x)}));
    setDirty(true); setAck(false);
  }
  async function importFile(event) {
    const file = event.target.files[0]; if (!file) return;
    const form = new FormData(); form.append('file',file); form.append('period',baselinePeriod);
    await action(() => api('/reference',{method:'POST',body:form})); event.target.value='';
  }
  const includedTasks = report?.tasks?.filter(x=>x.include_in_report) || [];
  const includedRisks = report?.risks?.filter(x=>x.include_in_report) || [];
  const failed = history.filter(r=>r.status==='failed');
  return <section className="monthly" id="reports">
    <header className="workspaceHeader"><span>Проектный офис <span className="slash">/</span> Отчётность</span><span className="connection"><i/> {settings?.ews_configured ? 'Почта настроена' : 'Настройка почты'}</span></header>
    <div className="pageHeading"><div><p className="eyebrow">ОТЕЛЬ И АПАРТАМЕНТЫ</p><h1>Отчётность проекта<span className="headingDot">.</span></h1><p>От переписки — к решениям, результатам и рискам.</p></div><button className="btn" aria-expanded={creating} onClick={()=>setCreating(!creating)}>Новый отчёт <span>+</span></button></div>
    {creating && <div className="generationBar"><div><strong>Новый отчёт</strong><span>Почта за месяц + история предыдущего периода</span></div><div className="monthlyActions">
      <label className="field"><span>Отчётный месяц</span><input type="month" value={period} max={settings?.default_period} onChange={e=>setPeriod(e.target.value)}/></label>
      <button className="btn" disabled={busy || running || dirty || !settings?.ews_configured} onClick={()=>action(()=>api('/reports',json('POST',{period})))}>{busy || running ? 'Обработка…' : 'Сформировать'} <span aria-hidden="true">↗</span></button>
    </div></div>}
    {settings && !settings.ews_configured && <p className="error">Почта ещё не подключена. Администратору необходимо настроить пароль Exchange на сервере.</p>}

    {error && <p role="alert" className="error">{error}</p>}
    <div className="historyList"><span className="sectionLabel">ПЕРИОДЫ</span>{history.filter(r=>r.status!=='failed').map(r=><button className={`periodButton ${report?.id===r.id?'selected':''}`} key={r.id} disabled={busy || dirty} onClick={()=>action(()=>api(`/reports/${r.id}`))}><span>{monthName(r.period)}</span><small className={`badge ${r.status}`}>{statuses[r.status]}</small></button>)}</div>
    {report && <article className="reportSheet">
      <div className="reportHeading"><div><p className="eyebrow">ЕЖЕМЕСЯЧНЫЙ ОТЧЁТ</p><h2>{monthName(report.period)}</h2><span className={`badge ${report.status}`}>{statuses[report.status]}</span><span className="revisionLabel">Солощенко С.С.</span></div>{['draft','approved'].includes(report.status) && !dirty && <div className="downloadActions"><a className="btn" href={`${BASE}/api/monthly/reports/${report.id}/document`}>↓ Таблицы Word</a><a className="textLink" href={`${BASE}/api/monthly/reports/${report.id}/attachments`}>Вложения по пунктам ↗</a></div>}</div>
      {report.status==='failed' && report.error && <p className="error">{report.error}</p>}
      <div className="reportMetrics"><div><strong>{includedTasks.length}</strong><span>пунктов отчёта</span></div><div><strong>{includedRisks.length}</strong><span>актуальных рисков</span></div><div><strong>{report.selected_count ?? '—'}</strong><span>писем отобрано</span></div><div><strong className="metricText">{report.previous_report_id ? 'Сохранена' : 'Исходный'}</strong><span>{report.previous_report_id ? 'связь с прошлым периодом' : 'отчёт для истории'}</span></div></div>
      {report.coverage?.folders?.length>0 && <details><summary>Полнота сбора: {report.coverage.complete ? 'все запросы выполнены' : 'не завершён'}</summary>
        {report.coverage.folders.map((f,i)=><p key={i}>{f.root} / {f.name}: прочитано {f.read} из {f.found}</p>)}
        <p>Отобрано сообщений: {report.selected_count ?? '—'}</p>
      </details>}
      {report.warnings?.length>0 && <details className="reviewNotice"><summary>Замечания для проверки ({report.warnings.length})</summary><ul>{report.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul></details>}
      <div className="reportTabs" role="group" aria-label="Раздел отчёта">{[['tasks','Задачи и результаты',includedTasks.length],['risks','Риски проекта',includedRisks.length]].map(([key,label,count])=><button aria-pressed={tab===key} className={tab===key?'active':''} onClick={()=>{setTab(key);setQuery('');}} key={key}>{label}<span>{count}</span></button>)}</div>
      <div className="filterBar"><input type="search" aria-label="Поиск по пунктам" placeholder="Поиск по задачам, решениям и статусам…" value={query} onChange={e=>setQuery(e.target.value)}/>{tab==='tasks' && <select aria-label="Раздел задач" value={section} onChange={e=>setSection(e.target.value)}><option value="all">Все направления</option>{[['4.1','HMA'],['4.2','Dusit'],['4.3','Закупки'],['4.4','Dyer'],['4.5','Координация']].map(([n,t])=><option key={n} value={n}>{n} · {t}</option>)}</select>}<div className="scopeSwitch" role="group" aria-label="Показать пункты"><button aria-pressed={!showArchived} onClick={()=>setShowArchived(false)}>В отчёте</button><button aria-pressed={showArchived} onClick={()=>setShowArchived(true)}>В истории</button></div></div>
      {!report[tab]?.some(x=>(showArchived ? !x.include_in_report : x.include_in_report) && (tab!=='tasks'||section==='all'||x.section===section) && `${x.title} ${x.result||x.dynamics} ${x.status}`.toLowerCase().includes(query.toLowerCase())) && <p className="emptyState">По этим условиям пунктов нет. Измените поиск или фильтры.</p>}
      {[tab].map(kind=><div key={kind} className="itemList">
        <div className="listHeader"><span>ПУНКТ / РЕЗУЛЬТАТ</span><span>СТАТУС</span></div>
        {report[kind]?.map((item,index)=>((showArchived ? !item.include_in_report : item.include_in_report) && (kind!=='tasks'||section==='all'||item.section===section) && `${item.title} ${item.result||item.dynamics} ${item.status}`.toLowerCase().includes(query.toLowerCase())) && <details className="reportItem" key={item.id}><summary><span className="itemNumber">{item.section || item.number}</span><span className="itemText"><strong>{item.title}</strong><span>{kind==='tasks' ? item.result : item.dynamics}</span><small>{item.previous_id ? 'Продолжение' : 'Новый пункт'} · {item.attachment_ids.length} {item.attachment_ids.length===1?'вложение':item.attachment_ids.length>1 && item.attachment_ids.length<5?'вложения':'вложений'}</small></span><span className={`badge ${['Повышен','Реализовался'].includes(item.status)?'failed':['Завершено','Снижен','Снят'].includes(item.status)?'approved':'draft'}`}>{item.status}</span><span className="expandIcon" aria-hidden="true">+</span></summary>
          <div className="monthlyActions"><strong>Редактирование пункта {item.section || item.number}</strong>
            <label><input type="checkbox" checked={item.include_in_report} disabled={!editable || busy} onChange={e=>change(kind,index,'include_in_report',e.target.checked)}/> Включить в таблицу</label></div>
          <label className="field"><span>Предмет</span><input value={item.title} disabled={!editable || busy} onChange={e=>change(kind,index,'title',e.target.value)}/></label>
          {(kind==='tasks' ? ['result'] : ['characteristics','dynamics','response']).map(field=><label className="field" key={field}><span>{{result:'Выполнено и результат', characteristics:'Характеристики', dynamics:'Динамика',response:'Мероприятия реагирования'}[field]}</span><textarea rows={3} value={item[field]} disabled={!editable || busy} onChange={e=>change(kind,index,field,e.target.value)}/></label>)}
          <label className="field"><span>Статус</span><select value={item.status} disabled={!editable || busy} onChange={e=>change(kind,index,'status',e.target.value)}>{(kind==='tasks' ? taskStatuses : riskStatuses).map(s=><option key={s}>{s}</option>)}</select></label>
          <p>{item.previous_id ? 'Связано с предыдущим периодом' : 'Новый пункт'} · документов: {item.attachment_ids.length}</p>
          {!item.evidence_ids.length && item.previous_id && <p>Новых подтверждений нет. Сохранён последний известный статус.</p>}
          <div className="monthlyActions">{item.evidence_ids.map((sid,i)=><button className="btn ghost small" key={sid} onClick={()=>api(`/reports/${report.id}/sources/${sid}`).then(setSource).catch(e=>setError(e.message))}>Письмо {i+1}</button>)}</div>
        </details>)}
      </div>)}
      {source && <dialog ref={sourceDialog} onCancel={()=>setSource(null)} aria-modal="true" aria-label="Письмо-основание" className="sourceDialog">
        <div className="sourceHeader"><div><p className="eyebrow">ПИСЬМО-ОСНОВАНИЕ</p><h3>{source.subject}</h3></div><button className="btn ghost small" onClick={()=>setSource(null)}>Закрыть ×</button></div>
        <div className="sourceMeta"><span><small>Отправитель</small>{source.sender}</span><span><small>Дата письма · Москва</small>{new Date(source.date).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'})}</span></div>
        {source.attachments.length>0 && <details className="sourceAttachments"><summary>Вложения · {source.attachments.length}</summary>{source.attachments.map((a,i)=><p key={a.id || i}>{a.id && <a href={`${BASE}/api/monthly/reports/${report.id}/sources/${source.id}/attachments/${a.id}`}>{a.name}</a>} {a.url && /^https?:\/\//.test(a.url) && <a href={a.url} target="_blank" rel="noreferrer">Исходная ссылка ↗</a>} {a.warning && <small>{a.warning==='unsupported'?'Текст не извлечён':a.warning}</small>}</p>)}</details>}
        <pre>{source.body}</pre>
      </dialog>}

      {editable && <div className={`monthlyActions approvalBar ${dirty ? "hasChanges" : ""}`}>
        <button className="btn" disabled={busy || !dirty} onClick={()=>action(()=>api(`/reports/${report.id}`,json('PUT',{revision:report.revision,tasks:report.tasks,risks:report.risks,warnings:report.warnings})))}>Сохранить правки</button>
        <label><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/> Проверены формулировки, полнота и замечания</label>
        <button className="btn" disabled={busy || dirty || !ack} onClick={()=>action(()=>api(`/reports/${report.id}/approve`,json('POST',{revision:report.revision,warnings_acknowledged:ack})))}>Утвердить версию</button>
      </div>}
      {report.status==='approved' && <button className="btn ghost" disabled={busy} onClick={()=>action(()=>api(`/reports/${report.id}/revision`,json('POST',{})))}>Создать редакцию</button>}
      {dirty && <p className="unsavedNotice" role="status">Есть несохранённые правки. Сохраните их, чтобы обновить Word и вложения.</p>}

      {report.usage && <p>Вызовов модели: {report.usage.runs}; повторно использовано: {report.usage.cache_hits}; входных токенов: {report.usage.input_tokens}; выходных: {report.usage.output_tokens}.</p>}
      <details open={Boolean(running)}><summary>Журнал обработки</summary><pre className="monthlyLog">{report.logs?.join('\n')}</pre></details>
    </article>}
    <details className="baselineImport"><summary>Импорт исходного отчёта <span>DOCX</span></summary>
      <p>Выберите фактический период содержания, даже если название файла отличается. После анализа проверьте и утвердите исходную версию.</p>
      <input aria-label="Период предыдущего отчёта" type="month" value={baselinePeriod} max={settings?.default_period} onChange={e=>setBaselinePeriod(e.target.value)}/>
      <input aria-label="Файл предыдущего отчёта" type="file" accept=".docx" disabled={busy || dirty} onChange={importFile}/>
    </details>
    {failed.length>0 && <details className="attempts"><summary>Журнал предыдущих попыток <span>{failed.length} незавершённых</span></summary><p>Эти запуски завершились до готового черновика. Они сохранены для диагностики и не влияют на текущий отчёт.</p>{failed.map(r=><button className="attemptRow" key={r.id} disabled={busy||dirty} onClick={()=>api(`/reports/${r.id}`).then(setAttempt).catch(e=>setError(e.message))}><span>{monthName(r.period)} · {new Date(r.created_at).toLocaleString('ru-RU')}</span><span>Открыть подробности ↗</span></button>)}{attempt && <div className="attemptDetail"><strong>{monthName(attempt.period)} · Незавершённая попытка</strong><p>{failureSummary(attempt.error)}</p><details><summary>Технические подробности</summary><pre className="monthlyLog">{attempt.error}{'\n'}{attempt.logs?.join('\n')}</pre></details></div>}</details>}
  </section>;
}

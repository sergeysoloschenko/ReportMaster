import { useEffect, useState } from 'react';

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
const riskStatuses = ['Открыт','Снижен','Повышен','Реализовался','Снят','Требует уточнения'];

export default function Monthly() {
  const [settings, setSettings] = useState(null);
  const [history, setHistory] = useState([]);
  const [period, setPeriod] = useState('');
  const [baselinePeriod, setBaselinePeriod] = useState('2026-07');
  const [report, setReport] = useState(null);
  const [source, setSource] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [ack, setAck] = useState(false);
  const running = report && ['queued','processing'].includes(report.status);
  const editable = report?.status === 'draft';
  async function refreshHistory() { setHistory(await api('/reports')); }
  useEffect(() => {
    api('/settings').then(s => {setSettings(s); setPeriod(s.default_period);}).catch(e => setError(e.message));
    refreshHistory().catch(e => setError(e.message));
  }, []);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => api(`/reports/${report.id}`).then(r => {
      setReport(r); if (!['queued','processing'].includes(r.status)) refreshHistory();
    }).catch(e => setError(e.message)), 2000);
    return () => clearInterval(timer);
  }, [report?.id, running]);
  async function action(fn) {
    setBusy(true); setError('');
    try { const r = await fn(); if (r) {setReport(r); setDirty(false); setAck(false); setSource(null);} await refreshHistory(); }
    catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  function change(kind, index, field, value) {
    setReport(r => ({...r, [kind]: r[kind].map((x,i) => i===index ? {...x,[field]:value} : x)}));
    setDirty(true);
  }
  async function importFile(event) {
    const file = event.target.files[0]; if (!file) return;
    const form = new FormData(); form.append('file',file); form.append('period',baselinePeriod);
    await action(() => api('/reference',{method:'POST',body:form})); event.target.value='';
  }
  return <section className="card monthly">
    <p className="eyebrow">Отель и апартаменты · Солощенко С.С.</p>
    <h2>Ежемесячный отчёт</h2>
    <p>Входящая и исходящая почта Exchange, история задач и актуальные риски. Следующий месяц опирается на последнюю утверждённую версию.</p>
    <div className="monthlyActions">
      <label className="field"><span>Отчётный месяц</span><input type="month" value={period} max={settings?.default_period} onChange={e=>setPeriod(e.target.value)}/></label>
      <button className="btn" disabled={busy || running || dirty || !settings?.ews_configured} onClick={()=>action(()=>api('/reports',json('POST',{period})))}>Сформировать отчёт</button>
    </div>
    {settings && !settings.ews_configured && <p className="error">Почта ещё не подключена. Администратору необходимо настроить пароль Exchange на сервере.</p>}
    <details><summary>Загрузить предыдущий отчёт</summary>
      <p>Выберите фактический период содержания, даже если название файла отличается. После анализа проверьте и утвердите исходную версию.</p>
      <input aria-label="Период предыдущего отчёта" type="month" value={baselinePeriod} max={settings?.default_period} onChange={e=>setBaselinePeriod(e.target.value)}/>
      <input aria-label="Файл предыдущего отчёта" type="file" accept=".docx" disabled={busy || dirty} onChange={importFile}/>
    </details>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="historyList">{history.map(r=><button className="btn ghost small" key={r.id} disabled={busy || dirty} onClick={()=>action(()=>api(`/reports/${r.id}`))}>{r.period} · {statuses[r.status]}{r.source_type==='reference' ? ' · Исходный' : ''}</button>)}</div>
    {report && <>
      <h3>{report.period} · {statuses[report.status]}</h3>
      {report.error && <p className="error">{report.error}</p>}
      {report.coverage?.folders?.length>0 && <details><summary>Полнота сбора: {report.coverage.complete ? 'все запросы выполнены' : 'не завершён'}</summary>
        {report.coverage.folders.map((f,i)=><p key={i}>{f.root} / {f.name}: прочитано {f.read} из {f.found}</p>)}
        <p>Отобрано сообщений: {report.selected_count ?? '—'}</p>
      </details>}
      {report.warnings?.length>0 && <details open><summary>Замечания для проверки ({report.warnings.length})</summary><ul>{report.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul></details>}
      {['tasks','risks'].map(kind=><div key={kind}>
        <h3>{kind==='tasks' ? 'Задачи и результаты' : 'Риски проекта'}</h3>
        {report[kind]?.map((item,index)=><details className="reportItem" key={item.id}><summary>{item.section || item.number} · {item.title} — {item.status}{!item.include_in_report ? ' · Только в истории' : ''}</summary>
          <div className="monthlyActions"><strong>{item.section || item.number} · {item.id}</strong>
            <label><input type="checkbox" checked={item.include_in_report} disabled={!editable || busy} onChange={e=>change(kind,index,'include_in_report',e.target.checked)}/> Включить в таблицу</label></div>
          <label className="field"><span>Предмет</span><input value={item.title} disabled={!editable || busy} onChange={e=>change(kind,index,'title',e.target.value)}/></label>
          {(kind==='tasks' ? ['result'] : ['characteristics','dynamics','response']).map(field=><label className="field" key={field}><span>{{result:'Выполнено и результат', characteristics:'Характеристики', dynamics:'Динамика',response:'Мероприятия реагирования'}[field]}</span><textarea rows={3} value={item[field]} disabled={!editable || busy} onChange={e=>change(kind,index,field,e.target.value)}/></label>)}
          <label className="field"><span>Статус</span><select value={item.status} disabled={!editable || busy} onChange={e=>change(kind,index,'status',e.target.value)}>{(kind==='tasks' ? taskStatuses : riskStatuses).map(s=><option key={s}>{s}</option>)}</select></label>
          <p>{item.previous_id ? 'Связано с предыдущим периодом' : 'Новый пункт'} · документов: {item.attachment_ids.length}</p>
          {!item.evidence_ids.length && item.previous_id && <p>Новых подтверждений нет. Сохранён последний известный статус.</p>}
          <div className="monthlyActions">{item.evidence_ids.map((sid,i)=><button className="btn ghost small" key={sid} onClick={()=>api(`/reports/${report.id}/sources/${sid}`).then(setSource).catch(e=>setError(e.message))}>Письмо {i+1}</button>)}</div>
        </details>)}
      </div>)}
      {source && <dialog open className="sourceDialog"><button className="btn ghost small" onClick={()=>setSource(null)}>Закрыть</button><h3>{source.subject}</h3><p>{source.date} · {source.sender}</p><pre>{source.body}</pre>
        {source.attachments.map((a,i)=><p key={a.id || i}>{a.id && <a href={`${BASE}/api/monthly/reports/${report.id}/sources/${source.id}/attachments/${a.id}`}>{a.name}</a>} {a.url && /^https?:\/\//.test(a.url) && <a href={a.url} target="_blank" rel="noreferrer">Исходная ссылка</a>} {a.warning}</p>)}
      </dialog>}
      {editable && <div className="monthlyActions">
        <button className="btn" disabled={busy || !dirty} onClick={()=>action(()=>api(`/reports/${report.id}`,json('PUT',{revision:report.revision,tasks:report.tasks,risks:report.risks,warnings:report.warnings})))}>Сохранить правки</button>
        <label><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/> Проверены формулировки, полнота и замечания</label>
        <button className="btn" disabled={busy || dirty || !ack} onClick={()=>action(()=>api(`/reports/${report.id}/approve`,json('POST',{revision:report.revision,warnings_acknowledged:ack})))}>Утвердить версию</button>
      </div>}
      {report.status==='approved' && <button className="btn ghost" disabled={busy} onClick={()=>action(()=>api(`/reports/${report.id}/revision`,json('POST',{})))}>Создать редакцию</button>}
      {['draft','approved'].includes(report.status) && <div className="monthlyActions"><a className="btn" href={`${BASE}/api/monthly/reports/${report.id}/document`}>Скачать таблицы Word</a><a className="btn ghost" href={`${BASE}/api/monthly/reports/${report.id}/attachments`}>Скачать вложения по пунктам</a>{dirty && <span>Сначала сохраните правки, чтобы обновить файлы.</span>}</div>}
      {report.usage && <p>Вызовов модели: {report.usage.runs}; повторно использовано: {report.usage.cache_hits}; входных токенов: {report.usage.input_tokens}; выходных: {report.usage.output_tokens}.</p>}
      <details open={Boolean(running)}><summary>Журнал обработки</summary><pre className="monthlyLog">{report.logs?.join('\n')}</pre></details>
    </>}
  </section>;
}

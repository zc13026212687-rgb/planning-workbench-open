import './style.css';

type Dict = Record<string, any>;
type Point = [number, number];
type ChatMessage = { role: 'assistant' | 'user' | 'error'; text: string };
const app = document.querySelector<HTMLDivElement>('#app')!;
const sessionToken = new URLSearchParams(location.hash.slice(1)).get('token') || '';
if (sessionToken) history.replaceState(null, '', location.pathname + location.search);
const state = {
  bootstrap: { cases: [], skills: [], providers: [], runtimes: [], jobs: [], cad: {}, version: '' } as Dict,
  projects: [] as Dict[], project: null as Dict | null, projectName: '道路设计工作台',
  selectedCase: null as Dict | null, selectedVariant: '', spec: null as Dict | null,
  job: null as Dict | null, result: null as Dict | null, messages: [] as ChatMessage[],
  providerId: '', skillId: '', tab: 'plan', modal: '', busy: false, connected: false, cad: {} as Dict,
  providerEdit: null as Dict | null, selectedRoad: '', view: null as number[] | null,
  pollTimer: 0, toastTimer: 0, activeRuntime: 'builtin', latestEvent: '', workspaceMode: 'assistant', specDirty: false,
  importNeedsReview: false, streamedText: '', mcpDiagnostic: null as Dict | null, mcpBusy: false, library: null as Dict | null, comparison: null as Dict | null, cadInspection: null as Dict | null,
  skillBusy: '', skillDiagnostics: {} as Record<string, Dict>, cadBusy: false, cadError: '',
};
const paths: Record<string, string> = {
  plan: '<path d="m4 18 4-12 4 12 4-12 4 12M3 12h18"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  chat: '<path d="M20 15a3 3 0 0 1-3 3H8l-5 3V6a3 3 0 0 1 3-3h11a3 3 0 0 1 3 3Z"/><path d="M7 8h9M7 12h6"/>',
  book: '<path d="M12 5v15M3 4h5a4 4 0 0 1 4 2 4 4 0 0 1 4-2h5v15h-5a5 5 0 0 0-4 1 5 5 0 0 0-4-1H3Z"/>',
  spark: '<path d="m12 3 2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2ZM20 2v4M18 4h4"/>',
  tasks: '<path d="M9 6h12M9 12h12M9 18h12M3 6l1 1 2-3M3 12l1 1 2-3M3 18l1 1 2-3"/>',
  settings: '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2" fill="currentColor"/><circle cx="16" cy="12" r="2" fill="currentColor"/><circle cx="10" cy="18" r="2" fill="currentColor"/>',
  plus: '<path d="M12 5v14M5 12h14"/>', close: '<path d="m6 6 12 12M6 18 18 6"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>', upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
  download: '<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>', send: '<path d="m4 12 16-8-6 16-3-7ZM11 13l9-9"/>',
  check: '<path d="m5 12 4 4L19 6"/>', warning: '<path d="m12 3 10 18H2Z"/><path d="M12 9v5M12 17v.2"/>',
  cad: '<path d="M3 3h18v18H3ZM6 17l4-10 4 10M8 13h4M16 7v10"/>', fit: '<path d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5"/>',
  minus: '<path d="M5 12h14"/>', layer: '<path d="m3 8 9-5 9 5-9 5Zm0 5 9 5 9-5M3 18l9 5 9-5"/>',
  file: '<path d="M14 3H5v18h14V8ZM14 3v6h5M8 13h8M8 17h6"/>', refresh: '<path d="M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 3M4 16l2 3a8 8 0 0 0 13-3"/>',
  undo: '<path d="M7 5 2 10l5 5M3 10h10a6 6 0 0 1 0 12"/>', link: '<path d="m9 15 6-6M8 16l-2 2a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0M16 8l2-2a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0"/>',
};
const icon = (name: string, extra = '') => `<svg class="icon ${extra}" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.file}</svg>`;
const esc = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const list = (value: unknown): Dict[] => Array.isArray(value) ? value : value && typeof value === 'object' ? Object.entries(value).map(([id, item]) => typeof item === 'object' ? { id, ...item } : { id, name: item }) : [];
const statuses: Record<string, string> = {queued:'排队中',running:'正在计算',succeeded:'已完成',completed:'已完成',success:'已完成',failed:'未完成',canceled:'已取消',cancelled:'已取消',interrupted:'已中断',pending:'等待中',needs_review:'待审核'};
const done = (job: Dict | null) => ['succeeded','completed','success'].includes(job?.status);
const running = (job: Dict | null) => ['queued','running','pending'].includes(job?.status);
const issues = (kind: string): Dict[] => list(state.result?.report?.[kind]).map(x => typeof x === 'string' ? {message:x} : x);
const blockingErrors = () => issues('errors').length > 0 || state.result?.report?.valid === false;
const canExport = () => !!state.result && done(state.job) && !blockingErrors() && !state.specDirty;
const canWriteCad = () => canExport() && state.spec?.units === 'm';
const isSection = () => state.spec?.kind === 'road_cross_section';
function geometrySkills():Dict[]{return list(state.bootstrap.skills).filter(s=>s.ready===true&&s.executor===(isSection()?'section':'geometry'));}
function resolveSkill(){
  const skills=geometrySkills(),current=skills.find(s=>s.id===state.skillId&&s.enabled===true);
  if(current)return;
  const preferred=isSection()?'road-cross-section':state.selectedCase?.id==='renewal-street-adjustment'?'urban-renewal':'road-plan';
  state.skillId=(skills.find(s=>s.id===preferred&&s.enabled===true)||skills.find(s=>s.enabled===true))?.id||'';
}


async function api(path: string, options: RequestInit = {}): Promise<any> {
  const headers = new Headers(options.headers);
  if (sessionToken) headers.set('X-Local-Token', sessionToken);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
  let result: any;
  const ct = response.headers.get('content-type') || '';
  result = ct.includes('json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = result?.detail ?? result?.error ?? result;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return result;
}
const post = (path: string, data: Dict = {}) => api(path, {method:'POST',body:JSON.stringify(data)});
function toast(message: string, error = false) {
  document.querySelector('.toast')?.remove(); clearTimeout(state.toastTimer);
  const node = document.createElement('div');node.className=`toast${error ? ' error' : ''}`;node.setAttribute('role','status');node.textContent=message;document.body.append(node);
  state.toastTimer = window.setTimeout(() => node.remove(), error ? 8000 : 4300);
}
function message(text: string, role: ChatMessage['role'] = 'assistant') { state.messages.push({role,text}); }
function caseDescription(item: Dict) { return item.description || item.subtitle || (item.synthetic === false ? '道路设计案例' : '教学演示 · 参数可编辑'); }
function viewHeader(title: string, subtitle = '', wide = false) {
  return `<div class="modal-overlay" role="presentation"><section class="modal ${wide?'wide':''}" role="dialog" aria-modal="true" aria-label="${esc(title)}"><header class="modal-header"><div><h2>${esc(title)}</h2>${subtitle?`<small>${esc(subtitle)}</small>`:''}</div><button class="icon-btn" data-action="close-modal" aria-label="关闭">${icon('close')}</button></header><div class="modal-body">`;
}
function modalEnd(footer = '') { return `</div>${footer?`<footer class="modal-footer">${footer}</footer>`:''}</section></div>`; }

function render() {
  const inspectorScrollTop=document.querySelector('.inspector-scroll')?.scrollTop||0;
  const cases = list(state.bootstrap.cases), providers = list(state.bootstrap.providers), runtimes = list(state.bootstrap.runtimes);
  const latestJobs = list(state.bootstrap.jobs);
  const caseOptions = cases.map(c => `<option value="${esc(c.id)}" ${c.id === state.selectedCase?.id ? 'selected':''}>${esc(c.name || c.title || c.id)}</option>`).join('');
  const variants = list(state.selectedCase?.variants);
  resolveSkill();
  const unit = state.spec?._import&&!state.spec?.units?'待确认':state.spec?.units || state.spec?.unit || 'm';
  const unitLabel = typeof unit === 'string' ? unit : (unit.length || 'm');
  const cadConnected = !!(state.cad.connected || state.cad.available && state.cad.document_id);
  app.innerHTML = `<div class="shell ${state.workspaceMode==='assistant'?'assistant-mode':''}"><aside class="sidebar"><div class="brand"><div class="brand-mark">${icon('plan')}</div><div><div class="brand-name">清规AI</div><div class="brand-sub">PlanningWorkbench<br/>Open 0.2.0</div></div></div>
    <div class="nav-label">设计空间</div><nav aria-label="主导航"><button class="nav-btn active" data-action="workspace" title="设计工作台">${icon('grid')}<span>设计工作台</span></button><button class="nav-btn" data-action="regulatory" title="地块分割、控制指标与图则">${icon('layer')}<span>地块与图则</span><i class="tiny">新</i></button><button class="nav-btn" data-action="cases" title="教学案例">${icon('book')}<span>教学案例</span><i class="tiny">${cases.length.toString().padStart(2,'0')}</i></button><button class="nav-btn" data-action="skills" title="技能库">${icon('spark')}<span>专业技能</span></button><button class="nav-btn" data-action="jobs" title="任务记录">${icon('tasks')}<span>任务记录</span></button></nav>
    <button class="new-project" data-action="new-project" title="新建设计">${icon('plus')}<span>新建设计</span></button><button class="nav-btn" data-action="library">${icon('book')}规范与图纸库</button><div class="nav-label">最近项目</div><div class="recent-list">${state.projects.slice(0,7).map(p=>`<button class="recent-btn ${p.id===state.project?.id?'selected':''}" data-action="project" data-id="${esc(p.id)}" title="${esc(p.name)}">${esc(p.name || '未命名项目')}</button>`).join('') || '<div class="hint" style="padding:0 12px;color:#82998b">生成方案后保存在这里</div>'}</div>
    <div class="sidebar-footer"><button class="nav-btn" data-action="settings" title="模型与接口">${icon('settings')}<span>模型与接口</span></button><div class="local-badge"><i class="dot ${state.connected?'':'off'}"></i>${state.connected?'本地工作台已连接':'本地服务未连接'}</div><div class="profile"><div class="avatar">清</div><div>本地设计空间<small>文件与计算在本机运行</small></div></div></div></aside>
    <main class="main"><nav class="module-nav" aria-label="规划功能导航"><button data-action="case" data-id="regulatory-road-plan" class="${state.selectedCase?.id==='regulatory-road-plan'?'selected':''}">${icon('plan')}道路平面</button><button data-action="case" data-id="road-cross-section" class="${isSection()?'selected':''}">${icon('layer')}道路横断面</button><button data-action="regulatory">${icon('grid')}地块与图则</button><span>清规AI · PlanningWorkbench Open 0.2.0</span></nav><header class="topbar"><div><div class="breadcrumb">工作空间<span>/</span>道路方案<span>/</span>${isSection()?'横断面设计':'平面设计'}</div><div class="project-heading">${esc(state.projectName)}<span class="tag">本地原型</span></div></div><div class="top-actions"><button class="button" data-action="toggle-workspace">${icon(state.workspaceMode==='assistant'?'plan':'chat')}${state.workspaceMode==='assistant'?'图纸与参数':'返回助手'}</button><button class="button" data-action="import">${icon('upload')}导入 DXF</button><button class="button mobile-only" data-action="json">${icon('settings')}参数</button><button class="button primary" data-action="download" ${canExport()?'':'disabled'}>${icon('download')}导出 DXF</button></div></header>
    <div class="work-grid"><section class="chat-panel"><header class="panel-title"><span>${icon('chat')}${isSection()?'横断面设计助手':'道路设计助手'}</span><span class="status-caption">${esc(runtimes.find(r=>r.id===state.activeRuntime)?.name||'内置工具工作流')}</span></header><div class="chat-stream" id="chat-stream"><div class="assistant-intro"><div class="intro-symbol">${icon('spark')}</div><div class="intro-title">${isSection()?'从明确的组成，<br/>检查宽度与横坡。':'从一条中心线，<br/>开始你的道路方案。'}</div><p class="intro-desc">${isSection()?'每侧按中心向外排序，填写宽度、横坡和中心高程。<br class="welcome-break"/>几何引擎逐段累加，生成 1:1 可编辑横断面。':'先选教学案例或导入中心线，再设置道路宽度。<br class="welcome-break"/>几何引擎会生成可编辑图纸，并逐项校核。'}</p><div class="ability-chips"><span>中心线输入</span><span>参数编辑</span><span>道路生成</span><span>约束检查</span><span>矢量导出</span><span>报告校核</span></div><div class="case-label">从案例开始</div><div class="quick-cases">${cases.slice(0,3).map(c=>`<button class="quick-case" data-action="case" data-id="${esc(c.id)}">${icon('plan')}<div><strong>${esc(c.name||c.id)}</strong><small>${esc(caseDescription(c))}</small></div></button>`).join('') || '<div class="quality-empty">正在读取教学案例。服务未就绪时请使用左下角重连。</div>'}</div></div>
    ${state.messages.map(m=>`<article class="message ${m.role}"><div class="message-role">${m.role==='user'?'你':m.role==='error'?'执行提示':'清规AI助手'}</div><div class="message-body">${esc(m.text)}</div></article>`).join('')}
    ${state.streamedText?`<article class="message assistant"><div class="message-role">清规AI助手 · 正在接收模型输出</div><div class="message-body">${esc(state.streamedText)}</div></article>`:''}
    ${state.job?`<div class="task-chip"><div class="task-chip-header"><span>${state.job.mock?'离线规则演示（非 AI）':state.job.kind==='agent'?'助手任务':'道路几何任务'}</span><span class="${running(state.job)?'busy-text':''}">${esc(state.job.cancel_requested?'取消已请求，等待当前步骤返回':statuses[state.job.status]||state.job.status)}</span></div><div class="progress-track ${running(state.job)?'running':''}"><span></span></div><small>${esc(state.latestEvent || `任务 ${String(state.job.id).slice(0,12)}`)}</small>${running(state.job)?'<button class="text-btn" data-action="cancel-job">取消任务</button>':''}</div>`:''}</div>
    <div class="composer"><form id="chat-form"><div class="composer-box"><div class="composer-notice">${isSection()?'横断面使用组件表单 · 先确认宽度、横坡与基准高程。':state.activeRuntime==='mock'?'离线规则演示 · 不是 AI 推理，支持「左宽 8、右宽 8、圆角 4」。':state.activeRuntime==='codex'?'Codex CLI 使用自身授权与模型 · 当前平台尚未验证真实调用。':state.providerId?'AI 给出可审核的设计参数，几何引擎执行确定性计算。':'尚未接入模型 API · 可直接载入教学案例并生成道路。'}</div><textarea id="chat-input" aria-label="设计需求" placeholder="${isSection()?'横断面请用右侧组件表单确认宽度、横坡与高程。':'描述设计需求，例如：把左侧宽度改为 8 米…'}" ${state.busy?'disabled':''}></textarea><div class="runtime-row"><label for="runtime-choice">执行方式</label><select id="runtime-choice" ${state.busy?'disabled':''}>${runtimes.map(r=>`<option value="${esc(r.id)}" ${r.id===state.activeRuntime?'selected':''} ${r.available===false||r.status==='unavailable'?'disabled':''}>${esc(r.name)}${r.mock?' · 非 AI':''}</option>`).join('')}</select></div><div class="composer-bottom"><div class="composer-tools"><button class="icon-btn" type="button" data-action="import" title="导入中心线 DXF">${icon('plus')}</button><select class="model-select" id="provider-choice" aria-label="模型供应商" ${state.activeRuntime!=='builtin'||state.busy?'disabled':''}><option value="">手动几何 · 无模型调用</option>${providers.map(p=>`<option value="${esc(p.id)}" ${p.id===state.providerId?'selected':''}>${esc(p.name)} · ${esc(p.model)}</option>`).join('')}</select><button class="composer-tool" type="button" data-action="skills">${icon('spark')}技能</button><button class="composer-tool" type="button" data-action="cases">${icon('book')}教程</button></div><button class="send-button" type="submit" aria-label="发送需求" ${state.busy?'disabled':''}>${icon('send')}</button></div></div></form><div class="composer-hint">${state.activeRuntime==='mock'?'规则匹配教学演示 · 不调用模型、不消耗 API 额度':state.activeRuntime==='codex'?'仅生成预览 · 实际 CLI 调用须主动确认':state.providerId?'使用所选官方 API · 调用可能产生费用':'配置模型后可使用 AI · 手动生成始终可用'}</div></div></section>
    <section class="canvas-column"><header class="canvas-toolbar"><div class="canvas-tabs"><button class="canvas-tab ${state.tab==='plan'?'selected':''}" data-action="tab" data-tab="plan">${icon('plan')}${isSection()?'道路横断面':'方案平面'}</button><button class="canvas-tab ${state.tab==='report'?'selected':''}" data-action="tab" data-tab="report">${icon('file')}校核报告</button></div><div class="toolbar-mini"><button class="icon-btn" data-action="json" title="查看与编辑 RoadSpec">${icon('settings')}</button><button class="icon-btn" data-action="fit" title="适合画布">${icon('fit')}</button></div></header>
    ${state.tab==='plan'?`<div class="viewport" id="viewport">${canvasMarkup()}${isSection()?'':'<div class="north">N</div>'}${state.result?`<div class="canvas-plate"><strong>${esc(state.selectedCase?.name||state.projectName)}</strong><small>${state.specDirty?'参数已改变 · 请重新生成':blockingErrors()?'诊断预览 · 存在阻断错误':canExport()?'几何计算完成 · 可编辑矢量成果':'预览结果 · 请查看任务状态'}<br/>${esc(unitLabel)} · ${esc((typeof state.spec?.coordinate_reference==='string'?state.spec.coordinate_reference:state.spec?.coordinate_reference?.type) || state.spec?.crs || '工程坐标')}</small></div><div class="view-label">${isSection()?'横轴：偏距 / 纵轴：高程 · 1:1':'工程坐标'} · ${esc(unitLabel)}<div class="scale-line"></div></div>`:''}<div class="viewport-actions"><button class="icon-btn" data-action="zoom-in" title="放大">${icon('plus')}</button><button class="icon-btn" data-action="zoom-out" title="缩小">${icon('minus')}</button><button class="icon-btn" data-action="fit" title="适合画布">${icon('fit')}</button></div></div>`:`<div class="report-view"><div class="section-label">本次计算的检查记录</div>${state.result?`<pre>${esc(JSON.stringify({report:state.result.report,metrics:state.result.metrics,runtime:state.job?.runtime,mock:state.job?.mock,usage:state.job?.usage,events:state.job?.events},null,2))}</pre>`:'<div class="quality-empty">生成方案后展示真实质量报告。尚未执行任何校核。</div>'}</div>`}
    <footer class="canvas-bottom"><div class="legend"><span><i></i>${isSection()?'连续路表':'道路边界'}</span><span><i class="center"></i>${isSection()?'基准中心':'中心线'}</span><span><i class="restrict"></i>${isSection()?'宽度标注':'约束范围'}</span></div><span class="canvas-footnote">滚轮缩放 · 拖动画布</span></footer></section>
    <aside class="inspector"><header class="panel-title"><span>${icon('settings')}方案参数</span><button class="icon-btn" data-action="json" title="高级参数">${icon('file')}</button></header><div class="inspector-scroll"><div class="form-field"><label for="project-name">项目名称</label><input id="project-name" value="${esc(state.projectName)}" maxlength="120" placeholder="学号-道路-基线" ${state.busy?'disabled':''}/><small class="hint">名称随下一次生成保存。</small></div><div class="section-label">教学场景<small>CASE STUDY</small></div><div class="form-field"><label for="case-choice">选择案例</label><select id="case-choice"><option value="">选择一个起始场景</option>${caseOptions}</select></div>${variants.length?`<div class="form-field"><label for="variant-choice">方案对比</label><select id="variant-choice"><option value="">原始方案</option>${variants.map(v=>`<option value="${esc(v.id)}" ${v.id===state.selectedVariant?'selected':''}>${esc(v.name||v.id)}</option>`).join('')}</select></div>`:''}
    <div class="divider"></div><div class="form-field"><label for="skill-choice">执行技能</label><select id="skill-choice" ${state.busy?'disabled':''}><option value="">${geometrySkills().some(s=>s.enabled)?'选择几何技能':'无已启用的对应技能'}</option>${geometrySkills().map(s=>`<option value="${esc(s.id)}" ${s.id===state.skillId?'selected':''} ${s.enabled?'':'disabled'}>${esc(s.name)}${s.enabled?'':' · 未启用'}</option>`).join('')}</select><p class="hint">只列出匹配当前图纸的几何执行器；技能草稿须在技能中心主动启用。</p></div>${parametersMarkup(unitLabel)}<button class="button primary" data-action="generate" style="width:100%;margin-top:5px" ${state.spec&&state.skillId&&!state.busy?'':'disabled'}>${icon('spark')}${state.busy?'正在执行…':isSection()?'生成道路横断面':'生成道路方案'}</button>
    <div class="split-fields" style="margin-top:10px"><button class="button small" data-action="assignment" ${state.job&&!state.busy?'':'disabled'}>作业包</button><button class="button small" data-action="compare">任务对比</button></div><button class="button small" style="margin-top:10px;width:100%" data-action="restore-revision" ${state.project?.history?.length&&!state.busy?'':'disabled'}>恢复上一版参数</button><div class="divider"></div><div class="section-label">方案指标<small>${state.result?'计算结果':'待生成'}</small></div><div class="metric-grid">${metricsMarkup()}</div><div class="divider"></div><div class="section-label">质量校核<small>${state.result?`${issues('errors').length} 错误 · ${issues('warnings').length} 提示`:'尚未执行'}</small></div>${qualityMarkup()}</div>
    <footer class="inspector-footer"><button class="button accent" data-action="cad" ${state.connected?'':'disabled'}>${icon('cad')}连接与写入 CAD</button><div class="cad-status"><i class="dot ${cadConnected?'':'off'}"></i>${cadConnected?'CAD 已连接':'CAD 状态待连接 / 检查'}</div></footer></aside></div>
    <footer class="activity-footer"><span><i class="dot ${state.connected?'':'off'}"></i>${state.connected?'本地服务在线':'服务连接中断'}${state.bootstrap.version?` · ${esc(state.bootstrap.version)}`:''}</span><span>${state.spec?'RoadSpec 已载入':'等待输入'} · ${state.result?`${list(state.result.entities).length} 个几何实体`:'无计算结果'}<button class="text-btn" data-action="refresh" style="font-size:9px">刷新状态</button></span></footer></main></div><input id="dxf-upload" type="file" accept=".dxf" hidden/>${modalMarkup()}`;
  bindEvents();
  const inspectorBody=document.querySelector('.inspector-scroll');if(inspectorBody)inspectorBody.scrollTop=inspectorScrollTop;
  const chat = document.querySelector('#chat-stream');if(state.messages.length&&chat) chat.scrollTop = chat.scrollHeight;
}

function importReviewMarkup():string{return `<div class="import-review"><strong>CAD 输入待确认</strong><p>填写左右宽度和圆角；在高级规格确认局部工程坐标、工程容差及每条道路的交叉类型。源单位保留，未缩放坐标。</p><p>${Array.isArray(state.spec?._import?.required_fields)?state.spec!._import.required_fields.map(esc).join(' · '):'coordinate_reference · qa_tolerance · roads[*].junction_type'}</p><button class="button small" data-action="json">确认高级 RoadSpec</button></div>`;}
function parametersMarkup(unitLabel:string):string {
  const width=state.spec?.left_width,rwidth=state.spec?.right_width,radius=state.spec?.junction_radius;
  if(!isSection())return `${state.importNeedsReview?importReviewMarkup():''}<div class="divider"></div><div class="section-label">道路断面<small>全局默认</small></div><div class="split-fields"><div class="form-field"><label for="left-width">左侧宽度</label><div class="number-field"><input id="left-width" type="number" min="0.01" step="0.5" value="${esc(width??'')}" placeholder="—" ${state.spec&&!state.busy?'':'disabled'}/><span>${esc(unitLabel)}</span></div></div><div class="form-field"><label for="right-width">右侧宽度</label><div class="number-field"><input id="right-width" type="number" min="0.01" step="0.5" value="${esc(rwidth??'')}" placeholder="—" ${state.spec&&!state.busy?'':'disabled'}/><span>${esc(unitLabel)}</span></div></div></div><div class="form-field"><label for="junction-radius">路口转角半径</label><div class="number-field"><input id="junction-radius" type="number" min="0" step="1" value="${esc(radius??'')}" placeholder="由场景定义" ${state.spec&&!state.busy?'':'disabled'}/><span>${esc(unitLabel)}</span></div></div><p class="hint">左右按中心线前进方向定义。单路段覆盖参数可在高级编辑中查看。</p>`;
  const roles:Record<string,string>={carriageway:'车行部分',cycleway:'骑行部分',sidewalk:'步行部分',median:'分隔带',greenbelt:'绿带'};
  const components=list(state.spec?.components).map((c,index):Dict=>({...c,index})).sort((a,b)=>String(a.side).localeCompare(String(b.side))||a.order-b.order);
  return `<div class="divider"></div><div class="section-label">横断面组成<small>偏距—高程 · 1:1</small></div><p class="hint">每侧按 order 从中心向外递增。两侧负横坡均向外下降，正横坡均向外上升。数值为输入参数，不是规范推荐值。</p><div class="form-field"><label for="reference-elevation">中心基准高程</label><div class="number-field"><input id="reference-elevation" type="number" step="0.1" value="${esc(state.spec?.reference_elevation??'')}" ${state.busy?'disabled':''}/><span>m</span></div></div><div class="section-components">${components.map(c=>`<section class="component-card"><strong>${esc(c.name||c.id)}</strong><small>${c.side==='left'?'左侧':'右侧'} · order ${esc(c.order)} · ${esc(roles[c.role]||c.role||'未定义角色')}</small><code>${esc(c.id)} · ${esc(c.role||'')}</code><div class="split-fields"><div class="form-field"><label for="component-width-${c.index}">宽度</label><div class="number-field"><input id="component-width-${c.index}" data-component-index="${c.index}" data-component-field="width" type="number" min="0.01" max="10000" step="0.25" value="${esc(c.width)}" ${state.busy?'disabled':''}/><span>m</span></div></div><div class="form-field"><label for="component-slope-${c.index}">向外横坡</label><div class="number-field"><input id="component-slope-${c.index}" data-component-index="${c.index}" data-component-field="slope_percent" type="number" min="-100" max="100" step="0.25" value="${esc(c.slope_percent)}" ${state.busy?'disabled':''}/><span>%</span></div></div></div></section>`).join('')}</div><p class="hint">本版为连续路表；组成名称、左右、顺序与角色可在高级 JSON 查看或修改，不包含缘石台阶、结构层或纵断面。</p>`;
}

function metricsMarkup() {
  const m = state.result?.metrics || {};
  const lengthUnit=String(m.length_unit||state.spec?.units||'m'),areaUnit=String(m.area_unit||lengthUnit+'²');
  const mappings: [string, string, string][] = [['component_count','组成数量','段'],['total_width','断面总宽',lengthUnit],['left_width','左侧总宽',lengthUnit],['right_width','右侧总宽',lengthUnit],['reference_elevation','中心高程',lengthUnit],['total_centerline_length','中心线总长',lengthUnit],['total_length','道路总长',lengthUnit],['centerline_length','中心线长度',lengthUnit],['road_count','道路数量','条'],['entity_count','几何实体','个'],['junction_count','平交节点','处'],['road_area','道路面积',areaUnit],['area','道路面积',areaUnit],['total_area','道路面积',areaUnit]];
  const found = mappings.filter(([key])=>m[key]!==undefined).slice(0,6);
  if (!found.length && state.result) return `<div class="metric"><small>几何实体</small><strong>${list(state.result.entities).length}</strong><span>个</span></div><div class="metric"><small>阻断问题</small><strong>${issues('errors').length}</strong><span>项</span></div>`;
  if (!found.length) return `<div class="metric"><small>道路总长</small><strong>—</strong><span>m</span></div><div class="metric"><small>平交节点</small><strong>—</strong><span>处</span></div>`;
  return found.map(([key,name,unit])=>`<div class="metric"><small>${name}</small><strong>${typeof m[key]==='number'?Number(m[key].toFixed(2)):esc(m[key])}</strong><span>${unit}</span></div>`).join('');
}
function qualityMarkup() {
  if (!state.result) return '<div class="quality-empty">完成几何计算后，将显示连接、半径、约束与拓扑等检查结果。</div>';
  const errors=issues('errors'), warnings=issues('warnings');
  const rows:Dict[]=[...errors.map(x=>({...x,severity:'error'})),...warnings.map(x=>({...x,severity:'warning'}))];
  if (!rows.length) return `<div class="quality-row">${icon('check')}<div>本次报告无阻断错误<small>仅代表已执行检查，不等于工程审定</small></div></div>`;
  return rows.slice(0,12).map(x=>`<button class="quality-row ${x.severity}" data-action="issue" data-road="${esc(x.road_id||'')}">${icon('warning')}<div>${esc(x.message||x.code)}<small>${esc([x.road_id,x.constraint_id,x.code].filter(Boolean).join(' · '))}</small></div></button>`).join('');
}
function pt(value: any): Point { return Array.isArray(value)?[Number(value[0]),Number(value[1])]:[Number(value?.x||0),Number(value?.y||0)]; }
function boundsFromEntities(): number[] {
  if(isSection()&&Array.isArray(state.result?.bounds)&&state.result.bounds.length===4&&state.result.bounds.every(Number.isFinite)){const[x0,y0,x1,y1]=state.result.bounds;const pad=Math.max(x1-x0,y1-y0,1)*.08;return[x0-pad,-y1-pad,x1-x0+2*pad,y1-y0+2*pad];}
  const points: Point[]=[];
  for(const e of list(state.result?.entities)) {
    const type=e.type||e.kind;
    if(type==='line') points.push(pt(e.start),pt(e.end));
    if(type==='polyline') points.push(...(e.points||[]).map(pt));
    if(type==='arc'||type==='circle') {const [x,y]=pt(e.center),r=Number(e.radius);points.push([x-r,y-r],[x+r,y+r]);}
    if(type==='text') points.push(pt(e.position));
  }
  for(const c of list(state.spec?.constraints)) points.push(...(c.polygon||[]).map(pt));
  const valid=points.filter(p=>p.every(Number.isFinite));if(!valid.length)return[-100,-100,200,200];
  const xs=valid.map(p=>p[0]),ys=valid.map(p=>-p[1]);const x=Math.min(...xs),y=Math.min(...ys),w=Math.max(...xs)-x,h=Math.max(...ys)-y;
  const pad=Math.max(w,h,1)*.14;return[x-pad,y-pad,Math.max(w,1)+pad*2,Math.max(h,1)+pad*2];
}
function entityMarkup(e:Dict):string {
  const type=e.type||e.kind, layer=String(e.layer||'').toLowerCase();
  const highlight=state.selectedRoad&&String(e.road_id||e.id||'').includes(state.selectedRoad);
  const center=/center|centre|中心|axis/.test(layer), redline=/red|红线/.test(layer);
  const color=highlight?'#bc6749':/section_dimension/.test(layer)?'#ac937a':redline?'#ac937a':center?'#a3a371':'#607e69';
  const attrs=`stroke="${color}" stroke-width="${highlight?2.5:center?1:1.4}" vector-effect="non-scaling-stroke" fill="none" ${center?'stroke-dasharray="7 5"':''}`;
  const pointstr=(p:any)=>{const [x,y]=pt(p);return`${x},${-y}`;};
  const title=`<title>${esc(e.id||'')} · ${esc(e.layer||'')}</title>`;
  if(type==='line'){const a=pt(e.start),b=pt(e.end);return`<line x1="${a[0]}" y1="${-a[1]}" x2="${b[0]}" y2="${-b[1]}" ${attrs}>${title}</line>`;}
  if(type==='polyline')return`<${e.closed?'polygon':'polyline'} points="${(e.points||[]).map(pointstr).join(' ')}" ${attrs}>${title}</${e.closed?'polygon':'polyline'}>`;
  if(type==='arc'||type==='circle') {
    const [cx,cy]=pt(e.center),r=Number(e.radius),a=Number(e.start_angle||0),b=Number(e.end_angle||0),tau=Math.PI*2;
    if(!Number.isFinite(r)||r<=0)return'';
    if(type==='circle'||Math.abs(b-a)>=tau-1e-8)return`<circle cx="${cx}" cy="${-cy}" r="${r}" ${attrs}>${title}</circle>`;
    const delta=((b-a)%tau+tau)%tau;return`<path d="M ${cx+r*Math.cos(a)} ${-cy-r*Math.sin(a)} A ${r} ${r} 0 ${delta>Math.PI?1:0} 0 ${cx+r*Math.cos(b)} ${-cy-r*Math.sin(b)}" ${attrs}>${title}</path>`;
  }
  if(type==='text'){const[x,y]=pt(e.position);return`<text x="${x}" y="${-y}" font-size="${Number(e.height||2)}" fill="#879774" font-family="Segoe UI,Microsoft YaHei UI,sans-serif">${esc(e.text)}</text>`;}
  return '';
}
function canvasMarkup():string {
  if(!state.result)return`<div class="canvas-empty">${icon('plan')}<strong>你的方案，将从这里展开</strong><p>载入教学案例或 DXF 中心线，<br/>点击「生成道路方案」查看真实计算结果。</p><button class="button" data-action="cases">${icon('book')}浏览教学案例</button></div>`;
  const bounds=state.view||boundsFromEntities(); state.view=bounds;
  const spacing=Math.pow(10,Math.floor(Math.log10(Math.max(bounds[2],bounds[3])))-1);
  const constraints=list(state.spec?.constraints).map(c=>`<polygon points="${(c.polygon||[]).map((v:any)=>{const p=pt(v);return`${p[0]},${-p[1]}`}).join(' ')}" fill="${c.type==='preserve'?'#d5dfc158':'#dfd2b958'}" stroke="#b5aa81" stroke-width="1" vector-effect="non-scaling-stroke" stroke-dasharray="5 4"><title>${esc(c.name||c.id)}</title></polygon>`).join('');
  return `<svg class="plan-svg" id="plan-svg" viewBox="${bounds.join(' ')}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${isSection()?'道路横断面几何预览':'道路平面几何预览'}"><defs><pattern id="plan-grid" width="${spacing}" height="${spacing}" patternUnits="userSpaceOnUse"><path d="M ${spacing} 0 L 0 0 0 ${spacing}" fill="none" stroke="#e2e7d6" stroke-width=".5" vector-effect="non-scaling-stroke"/></pattern></defs><rect x="${bounds[0]-bounds[2]*10}" y="${bounds[1]-bounds[3]*10}" width="${bounds[2]*21}" height="${bounds[3]*21}" fill="url(#plan-grid)"/>${constraints}${list(state.result.entities).map(entityMarkup).join('')}</svg>`;
}

function modalMarkup():string {
  if(!state.modal)return'';
  if(state.modal==='cases')return viewHeader('教学案例库','从可解释的几何场景开始，逐步验证设计方法。')+`<div class="card-grid">${list(state.bootstrap.cases).map(c=>`<article class="catalog-card"><strong>${esc(c.name||c.id)}</strong><p>${esc(caseDescription(c))}</p><div class="case-card-label"><span>${c.synthetic===false?'来源见案例说明':'教学 / 合成示例'}</span><span>参数化道路</span></div><details style="margin-bottom:16px"><summary class="hint">教学目标与操作步骤</summary>${c.objectives?`<ul class="teaching-steps">${c.objectives.map((x:string)=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}${c.steps?`<ol class="teaching-steps">${c.steps.map((x:string)=>`<li>${esc(x)}</li>`).join('')}</ol>`:''}${c.limitations?`<p class="hint">${c.limitations.map(esc).join('<br/>')}</p>`:''}</details><button class="button small" data-action="case" data-id="${esc(c.id)}">载入案例 ${icon('arrow')}</button></article>`).join('')}</div>`+modalEnd();
  if(state.modal==='skills')return viewHeader('专业技能','本地草稿先做真实几何试运行，通过后显式启用；修改文件会使旧诊断失效。')+mcpDiagnosticMarkup()+`<div class="card-grid">${list(state.bootstrap.skills).map(skillMarkup).join('')||'<div class="empty-list">尚未注册专业技能。</div>'}</div>`+modalEnd();
  if(state.modal==='jobs')return viewHeader('任务记录','打开任务可恢复已保存的结果与校核报告。')+`${list(state.bootstrap.jobs).map(j=>`<div class="job-list-item"><div><strong>${esc(j.name||j.message||`${j.kind==='agent'?'助手':'几何'}任务`)}</strong><small>${esc(j.id)} · ${esc(statuses[j.status]||j.status)}</small></div><button class="button small" data-action="job" data-id="${esc(j.id)}">打开 ${icon('arrow')}</button></div>`).join('')||'<div class="empty-list">还没有执行任务。选择案例并生成方案后，记录会出现在这里。</div>'}`+modalEnd();
  if(state.modal==='json')return viewHeader('RoadSpec 高级编辑','单位、曲线、约束和道路参数均保留在可审核的规格中。')+`<textarea class="json-editor" id="spec-editor" aria-label="RoadSpec JSON">${esc(JSON.stringify(state.spec||{},null,2))}</textarea><div class="hint">修改后需要重新生成方案。未执行几何引擎前，不会显示为新计算结果。</div>`+modalEnd('<button class="button" data-action="close-modal">取消</button><button class="button primary" data-action="save-spec">应用规格</button>');
  if(state.modal==='library')return viewHeader('规范与本地图纸库','索引与来源可追溯；参考图纸不等同于当前规范。',true)+`<div class="split-fields"><input id="library-query" placeholder="北京 控规 / 横断 / 节点"/><button class="button primary" data-action="search-library">检索</button></div><p class="hint">${esc(state.library?.note||'')} · 索引 ${state.library?.total||0} 项</p>${list(state.library?.items).map(r=>`<article class="catalog-card"><strong>${esc(r.title||r.name||r.filename||r.id||'资料')}</strong><p>${esc(r.summary||r.category||r.evidence_status||'本机参考资料')}</p><small>${esc(r.standard_id||r.version||'')} · ${esc(r.rights||r.redistribution||'再分发许可待确认')}</small><pre class="diagnostic-json">${esc(JSON.stringify(r,null,2))}</pre></article>`).join('')}`+modalEnd();
  if(state.modal==='compare')return viewHeader('任务与方案对比','选取独立任务版本，按道路 ID 定位参数和几何差异。',true)+`<div class="split-fields">${['a','b'].map((k,i)=>`<div class="form-field"><label>方案 ${k.toUpperCase()}</label><select id="compare-${k}">${list(state.bootstrap.jobs).filter(j=>j.result).map((j,n)=>`<option value="${esc(j.id)}" ${n===i?'selected':''}>${esc(j.id.slice(0,8))} · ${esc(j.message||j.kind)} · ${esc(statuses[j.status])}</option>`).join('')}</select></div>`).join('')}</div><button class="button primary" data-action="run-compare">计算差异</button>${state.comparison?`<pre class="diagnostic-json">${esc(JSON.stringify(state.comparison,null,2))}</pre>`:''}`+modalEnd();
  if(state.modal==='settings')return settingsMarkup();
  if(state.modal==='cad')return cadMarkup();
  return '';
}
function skillMarkup(s:Dict):string {
  const diagnostic=state.skillDiagnostics[s.id]||s.diagnostic;
  const current=diagnostic?.content_hash===s.content_hash;
  const states:Record<string,string>={builtin_registered:'内置执行器已登记',not_diagnosed:'尚未诊断',passed:'当前版本诊断通过',failed:'当前版本诊断失败',stale:'文件已更新 · 旧诊断失效',invalid:'登记校验未通过'};
  const canEnable=s.ready!==false&&(s.source!=='local'||s.validation_state==='passed');
  const diagnoseable=['geometry','section'].includes(s.executor)||s.source==='local';
  const errs=Array.isArray(diagnostic?.errors)?diagnostic.errors:[];
  return `<article class="catalog-card skill-card" data-skill-id="${esc(s.id)}"><strong>${esc(s.name||s.id)}</strong><p>${esc(s.description||s.summary||'暂无说明')}</p><div class="case-card-label"><span>${esc(s.version||'本地技能')} · ${s.source==='local'?'本地草稿':'内置'}</span><span>${s.enabled?'已启用':'已停用'} · ${s.ready===false?'登记不可用':'执行器就绪'}</span></div><p class="skill-state">${esc(states[s.validation_state]||'诊断状态未知')}${s.content_hash?`<small>内容 ${esc(s.content_hash.slice(0,12))}</small>`:''}</p><div class="skill-actions">${diagnoseable?`<button class="button small" data-action="diagnose-skill" data-id="${esc(s.id)}" ${state.busy||state.skillBusy?'disabled':''}>${state.skillBusy===s.id?'正在实际计算…':'几何试运行'}</button>`:''}<button class="button small" data-action="toggle-skill" data-id="${esc(s.id)}" ${(!s.enabled&&!canEnable)||state.busy||state.skillBusy?'disabled':''}>${s.enabled?'停用技能':'启用技能'}</button></div>${Array.isArray(s.validation_errors)&&s.validation_errors.length?`<div class="skill-diagnostic failed">${s.validation_errors.map((e:any)=>`<p>${esc(e)}</p>`).join('')}</div>`:''}${diagnostic?`<div class="skill-diagnostic ${current&&diagnostic.status==='passed'?'passed':'failed'}" role="status"><strong>${!current?'旧版本诊断 · 当前内容尚未通过':diagnostic.status==='passed'?'真实几何试运行通过':'几何试运行未通过'}</strong><p>实体 ${Number(diagnostic.entity_count||0)} 个 · ${esc(diagnostic.example||'未执行案例')}</p>${errs.slice(0,4).map((e:any)=>`<p>${esc(typeof e==='string'?e:e.message||JSON.stringify(e))}</p>`).join('')}<small>${esc(diagnostic.scope||'未收到有效几何诊断结果。')}${diagnostic.warnings?.length?` · ${diagnostic.warnings.length} 项提示，详见记录。`:''}</small><details><summary class="hint">查看诊断记录</summary><pre class="diagnostic-json">${esc(JSON.stringify(diagnostic,null,2))}</pre></details></div>`:''}<details style="margin-top:12px"><summary class="hint">查看技能说明、Schema 与权限</summary><pre class="diagnostic-json">${esc(s.instructions||s.content||'暂无说明')}\n\n权限：${esc(Array.isArray(s.permissions)?s.permissions.join('、'):'未登记')}\n\n${esc(s.isolation||'实际计算由固定执行器完成。')}</pre>${s.schema_definition!==null&&s.schema_definition!==undefined?`<p class="hint">执行前强制检查的 JSON Schema</p><pre class="diagnostic-json">${esc(JSON.stringify(s.schema_definition,null,2))}</pre>`:'<p class="hint">未单独声明 Schema；输入仍由固定几何执行器校验。</p>'}</details></article>`;
}
async function diagnoseSkill(id:string){
  if(state.skillBusy||state.busy)return;state.skillBusy=id;delete state.skillDiagnostics[id];render();
  try{const diagnostic=await post(`/api/skills/${encodeURIComponent(id)}/diagnose`);state.bootstrap.skills=await api('/api/skills');state.skillDiagnostics[id]=diagnostic;toast(diagnostic.status==='passed'?'真实几何试运行通过。本地草稿仍需显式启用。':'技能试运行未通过，请查看错误。',diagnostic.status!=='passed');}
  catch(e){const skill=list(state.bootstrap.skills).find(s=>s.id===id);state.skillDiagnostics[id]={status:'failed',success:false,content_hash:skill?.content_hash,errors:[{message:(e as Error).message}],scope:'诊断请求未完成；不构成试运行通过。'};toast((e as Error).message,true);}
  finally{state.skillBusy='';render();}
}
function mcpDiagnosticMarkup():string {
  const result=state.mcpDiagnostic;
  return `<section class="mcp-diagnostic"><div class="mcp-diagnostic-heading"><div><strong>MCP 通道诊断</strong><p class="hint">通过自有只读 fixture 检查 stdio 初始化、工具发现与回读。此结果不代表 CAD 通过 MCP 操作，也不代表第三方 MCP 或模型自动选工具已验收。</p></div><button class="button small" data-action="mcp-diagnostic" ${state.mcpBusy?'disabled':''}>${state.mcpBusy?'正在诊断…':'诊断 MCP 通道'}</button></div>${result?`<div class="settings-status" role="status"><strong>${result.success===true?'自有 fixture 诊断通过':'诊断未通过'}</strong>${result.message?`<p>${esc(result.message)}</p>`:''}${result.transport?`<p>传输：${esc(result.transport)} · 协议：${esc(result.protocol)} · 自有子进程${result.child_exited===true?'已退出':'退出状态未确认'}</p>`:''}<div>工具：${Array.isArray(result.tools)&&result.tools.length?result.tools.map((t:any)=>`<code>${esc(typeof t==='string'?t:t.name)}</code>`).join('、'):'未收到工具列表'}</div><details style="margin-top:10px"><summary class="hint">查看真实诊断返回</summary><pre class="diagnostic-json">${esc(JSON.stringify(result,null,2))}</pre></details></div>`:''}</section>`;
}
function settingsMarkup():string {
  const p=state.providerEdit||{};
  return viewHeader('模型与接口','配置你的官方 API。保存不会发起模型请求；连接测试由你主动触发。',true)+`<div class="settings-layout"><div><div class="section-label">模型供应商</div>${list(state.bootstrap.providers).map(item=>`<div class="provider-item ${item.id===p.id?'selected':''}"><strong>${esc(item.name)}</strong><small>${esc(item.model)}<br/>${item.has_key?'已保存密钥':'未设置密钥'} · ${esc(item.protocol)}</small><div class="provider-actions"><button class="button small" data-action="edit-provider" data-id="${esc(item.id)}">编辑</button><button class="button small" data-action="test-provider" data-id="${esc(item.id)}">测试</button><button class="button small danger" data-action="delete-provider" data-id="${esc(item.id)}">移除</button></div></div>`).join('')||'<div class="quality-empty">尚未配置模型。手动参数设计与几何生成无需 API。</div>'}<button class="button" data-action="new-provider" style="margin-top:12px;width:100%">${icon('plus')}添加接口</button><div class="divider"></div><div class="section-label">运行时</div><div class="settings-note">当前工作流：builtin<br/>模型供应商负责推理；本地几何工具负责计算与 DXF。Codex 等运行时与模型接口独立。</div></div><form id="provider-form" class="settings-form"><div class="section-label">${p.id?'编辑接口':'新增接口'}</div><div class="split-fields"><div class="form-field"><label for="provider-name">显示名称</label><input id="provider-name" required value="${esc(p.name||'')}" placeholder="例如 Kimi 官方 API"/></div><div class="form-field"><label for="provider-protocol">接口协议</label><select id="provider-protocol"><option value="chat_completions" ${p.protocol==='responses'?'':'selected'}>Chat Completions</option><option value="responses" ${p.protocol==='responses'?'selected':''}>Responses</option></select></div></div><div class="form-field"><label for="provider-url">Base URL</label><input id="provider-url" type="url" required value="${esc(p.base_url||'')}" placeholder="https://api.moonshot.cn/v1"/></div><div class="form-field"><label for="provider-model">模型 ID</label><input id="provider-model" required value="${esc(p.model||'')}" placeholder="填写服务商当前可用的模型 ID"/></div><div class="form-field"><label for="provider-key">API Key ${p.has_key?'· 留空保留现有密钥':''}</label><input id="provider-key" type="password" autocomplete="new-password" placeholder="密钥不在界面回显"/></div><div class="form-field"><label for="provider-headers">敏感自定义请求头（JSON）</label><textarea id="provider-headers" rows="3" autocomplete="off" spellcheck="false" aria-describedby="provider-headers-hint" placeholder='{&quot;X-Api-Version&quot;:&quot;填写所需版本&quot;}'></textarea><p class="hint" id="provider-headers-hint">留空保留已有请求头；输入 {} 清空。已保存的值不会回显。${p.header_names?.length?`<br/>已保存名称：${p.header_names.map(esc).join('、')}`:''}</p></div><div class="form-field"><label for="provider-timeout">请求超时（秒）</label><input id="provider-timeout" type="number" min="5" max="600" value="${Number(p.timeout||120)}"/></div><div class="settings-note">调用使用你的供应商账户并可能产生费用。不会导入个人订阅或桌面登录凭据。OpenAI 接入须满足服务地区与账户条件。</div><div class="settings-status" id="provider-status" role="status"></div><button class="button primary" type="submit">保存接口</button></form></div>`+modalEnd();
}
function cadMarkup():string {
  const cad=state.cad, doc=cad.document||{}, docid=cad.document_id||doc.document_id||doc.id;
  const markup = viewHeader('本机 CAD 工作区','先连接与预览，再由你确认写入。原始图纸不自动覆盖。')+`<div class="dialog-warning">仅修改本平台新建的独立文档。写入要求无阻断错误、参数未变更且单位为米。首次落图与更新已有图元分开执行。</div><dl class="cad-details"><dt>连接状态</dt><dd>${esc(cad.error||cad.message||cad.status||(cad.connected?'已连接':'未连接'))}</dd><dt>CAD 程序</dt><dd>${esc(cad.application||cad.product||cad.progid||cad.version||'待检测')}</dd><dt>操作目标（固定）</dt><dd>${esc(doc.name||cad.active_document?.name||cad.document_name||docid||'尚未选择文档')}${docid?' · '+esc(docid):' · 尚无可写目标'}</dd><dt>CAD 当前图纸</dt><dd>${esc(cad.active_document?.name||'无活动图纸')}${cad.active_document?.document_id!==docid?' · 与操作目标不同':''}</dd><dt>单位 / 当前图层</dt><dd>${esc(doc.units||cad.active_document?.units||'待读取')} / ${esc(doc.active_layer||state.cadInspection?.document?.active_layer||'点击读取实体')}</dd><dt>本平台可写</dt><dd>${docid?'当前会话创建的测试图纸':'只读，可另建测试图纸'}</dd><dt>文档版本</dt><dd>${esc(String(doc.version??cad.document_version??'—').slice(0,24))}</dd><dt>待写入任务</dt><dd>${state.job?esc(state.job.id):'尚未生成'}${blockingErrors()?' · 存在阻断错误':''}${state.specDirty?' · 参数已修改，请重新生成':''}</dd></dl><div class="readable-list">新建文档后“首次写入”。重新调整参数并生成后，使用“更新已落图方案”保留图元标识；不匹配的图元由后端拒绝。</div><details><summary>拟写入图层和对象</summary><pre class="diagnostic-json">${esc(JSON.stringify({layers:[...new Set(list(state.result?.entities).map(e=>e.layer))],objects:list(state.result?.entities).map(e=>({id:e.id,type:e.type,layer:e.layer}))},null,2))}</pre></details>${state.cadInspection?`<details open><summary>CAD 实际回读</summary><pre class="diagnostic-json">${esc(JSON.stringify(state.cadInspection,null,2))}</pre></details>`:''}<div id="cad-action-status" class="settings-status" role="status">${esc(state.cadBusy?'CAD 操作进行中，请等待返回；不会强杀 CAD。':state.cadError)}</div>`+modalEnd(`<button class="button small" data-action="cad-refresh">检查连接</button><button class="button small" data-action="cad-use-active">选用 CAD 当前图纸</button><button class="button small" data-action="cad-inspect">读取实体与选择集</button><button class="button small" data-action="cad-import-centerlines" ${state.busy?'disabled':''}>用所选实体建道路项目</button><button class="button small" data-action="cad-new">新建文档</button><button class="button small" data-action="cad-undo" ${docid?'':'disabled'}>撤销</button><button class="button small" data-action="cad-save" ${docid?'':'disabled'}>保存</button><button class="button small" data-action="cad-modify" ${canWriteCad()&&docid?'':'disabled'}>更新已落图方案</button><button class="button small" data-action="cad-auto" ${canWriteCad()?'':'disabled'}>新图自动落图并保存</button><button class="button primary small" data-action="cad-apply" ${canWriteCad()&&docid?'':'disabled'}>首次写入</button>`);
  return state.cadBusy?markup.replace(/<button\b/g,'<button disabled'):markup;
}

function readParameters() {
  const name=document.getElementById('project-name') as HTMLInputElement|null;
  if(name)state.projectName=name.value.trim();
  if(!state.spec)return;
  if(isSection()){
    const reference=document.getElementById('reference-elevation') as HTMLInputElement|null;
    if(reference){const value=Number(reference.value);if(!reference.value.trim()||!Number.isFinite(value))throw new Error('请填写有限的中心基准高程。');state.spec.reference_elevation=value;}
    for(const input of app.querySelectorAll<HTMLInputElement>('[data-component-field]')){const index=Number(input.dataset.componentIndex),field=input.dataset.componentField!,value=Number(input.value);if(!input.value.trim()||!Number.isFinite(value)||(field==='width'&&value<=0)||(field==='slope_percent'&&Math.abs(value)>100))throw new Error('组成宽度须大于 0，横坡须在 -100 至 100 内且明确填写。');state.spec.components[index][field]=value;}
    return;
  }
  for(const [id,key] of [['left-width','left_width'],['right-width','right_width'],['junction-radius','junction_radius']]) {
    const input=document.getElementById(id) as HTMLInputElement|null;
    if(input?.value!==undefined&&input.value!==''){const v=Number(input.value);if(!Number.isFinite(v)||v<0)throw new Error('宽度和半径必须为有效的非负数。');state.spec[key]=v;if(state.importNeedsReview&&v>0&&['left_width','right_width'].includes(key)){for(const road of list(state.spec.roads))if(road[key]===null)delete road[key];}}
  }
}
async function bootstrap() {
  try {
    state.bootstrap=await api('/api/bootstrap');state.connected=true;
    state.cad=state.bootstrap.cad||{};
    const projects=await api('/api/projects');state.projects=list(projects.projects||projects);
    if(state.providerId&&!list(state.bootstrap.providers).some(p=>p.id===state.providerId))state.providerId='';
    render();
  }catch(error){state.connected=false;render();toast(`连接本地服务失败：${(error as Error).message}`,true);}
}
async function loadCase(id:string, variantId='') {
  try {
    if(state.busy)throw new Error('请先完成或取消当前任务，再切换案例。');
    if(id==='regulatory-parcels'){location.href='/regulatory'+(sessionToken?'#token='+encodeURIComponent(sessionToken):'');return;}
    const c=await api(`/api/cases/${encodeURIComponent(id)}`);state.selectedCase=c;state.skillId='';state.importNeedsReview=false;state.streamedText='';state.selectedVariant=variantId||c.default_variant||'';
    const variant=list(c.variants).find(v=>v.id===variantId);state.spec=structuredClone(variant?.spec||c.spec);
    if(!state.spec)throw new Error('案例没有可用 RoadSpec。');
    clearTimeout(state.pollTimer);state.project=null;state.projectName=variant?`${c.name} · ${variant.name}`:c.name||id;
    state.job=null;state.result=null;state.view=null;state.modal='';state.messages=[];state.latestEvent='';state.workspaceMode='plan';state.specDirty=false;
    message(`已载入「${state.projectName}」。这是${c.synthetic===false?'案例数据':'教学示例'}，${isSection()?'请检查中心高程、组成宽度和向外横坡，再生成横断面。':'你可以调整道路宽度和路口参数，再生成方案。'}`);render();
  }catch(e){toast((e as Error).message,true);}
}
async function ensureProject() {
  if(!state.projectName.trim())throw new Error('请填写项目名称，例如“学号-道路-基线”。');
  if(state.project){
    if(JSON.stringify(state.spec)!==JSON.stringify(state.project.spec)||state.projectName!==state.project.name){
      const saved=await api(`/api/projects/${encodeURIComponent(state.project.id)}`,{method:'PUT',body:JSON.stringify({spec:state.spec,name:state.projectName,revision:state.project.revision})});
      state.project=saved.project||saved;const index=state.projects.findIndex(p=>p.id===state.project!.id);if(index>=0)state.projects[index]=state.project!;
    }
    return state.project!;
  }
  const project=await post('/api/projects',{name:state.projectName,case_id:state.selectedCase?.id||null,spec:state.spec,synthetic:state.selectedCase?state.selectedCase.synthetic!==false:false});
  state.project=project.project||project;state.projects.unshift(state.project!);return state.project!;
}
function adoptJob(job:Dict) {
  state.job=job.job||job;
  if(state.job?.skill_id)state.skillId=state.job.skill_id;
  if(state.job?.result){state.result=state.job.result;if(state.result?.spec)state.spec=structuredClone(state.result.spec);state.specDirty=false;}else if(state.job?.spec)state.spec=structuredClone(state.job.spec);
  const events=list(state.job?.events);const last=events.at(-1);
  state.latestEvent=last?last.type==='validation'?`校核完成：${list(last.data?.errors).length} 项错误、${list(last.data?.warnings).length} 项提示`:String(last.message||last.text||(typeof last.data==='string'?last.data:last.type)||'').slice(0,280):'';
  let lastMessageIndex=-1;events.forEach((event,index)=>{if(event.type==='message')lastMessageIndex=index;});state.streamedText=running(state.job)?events.slice(lastMessageIndex+1).filter(e=>e.type==='token'&&typeof e.data==='string').map(e=>e.data).join(''):'';
  state.busy=running(state.job);const idx=list(state.bootstrap.jobs).findIndex(j=>j.id===state.job?.id);
  if(idx>=0)state.bootstrap.jobs[idx]=state.job;else state.bootstrap.jobs=[state.job,...list(state.bootstrap.jobs)];
}
async function generate(kind:'geometry'|'agent', text='') {
  if(state.busy)return;
  try {
    readParameters();if(!state.spec)throw new Error('请先载入教学案例或导入中心线，再描述修改需求或生成方案。');
    if(state.importNeedsReview){
      const validWidth=(v:any)=>typeof v==='number'&&Number.isFinite(v)&&v>0;
      if(!validWidth(state.spec.left_width)||!validWidth(state.spec.right_width)||typeof state.spec.junction_radius!=='number'||!Number.isFinite(state.spec.junction_radius)||state.spec.junction_radius<0)throw new Error('CAD 中心线尚未确认左右宽度与圆角半径，请明确填写；空值不会自动作为 0。');
      if(typeof state.spec.units!=='string'||!state.spec.units||state.spec.coordinate_reference!=='local_cartesian'||!validWidth(state.spec.qa_tolerance)||!list(state.spec.roads).length||list(state.spec.roads).some(r=>!['at_grade','unknown'].includes(r.junction_type)))throw new Error('请打开“确认高级 RoadSpec”：核实来源为局部工程坐标后填写 coordinate_reference=local_cartesian；明确 qa_tolerance 工程容差，并为每条道路选择 junction_type=at_grade 或 unknown。此处不会重投影或替你判断道路平交。');
      state.importNeedsReview=false;
    }
    resolveSkill();if(!state.skillId)throw new Error('当前图纸没有已启用的几何技能，请先在技能中心检查。');
    if(kind==='agent'&&isSection())throw new Error('横断面目前使用组件表单生成。当前聊天工具仅支持平面全局宽度，请修改右侧宽度、横坡或基准高程后点击“生成道路横断面”。');
    if(kind==='agent'&&state.activeRuntime==='builtin'&&!state.providerId)throw new Error('尚未配置或选择模型。你可以直接修改参数并生成几何；AI 需求请先在“模型与接口”添加官方 API。');
    if(kind==='agent'&&state.activeRuntime==='codex'&&!confirm('使用本机 Codex CLI 自身授权发起一次只读参数规划？\n该调用使用 CLI 配置的模型与账户，可能消耗额度。本平台尚未验证此真实调用；所选 API 供应商不会用于该运行时。'))return;
    document.querySelector('.toast')?.remove();state.streamedText='';if(text)message(text,'user');if(kind==='agent'&&state.activeRuntime==='mock')message('本次为离线规则匹配教学演示，不是 AI 推理。');state.busy=true;render();
    const project=await ensureProject();
    const job=await post('/api/jobs',{project_id:project.id,kind,skill_id:state.skillId,spec:state.spec,message:text||undefined,provider_id:state.activeRuntime==='builtin'?state.providerId||undefined:undefined,runtime:kind==='geometry'?'builtin':state.activeRuntime});
    state.view=null;state.selectedRoad='';adoptJob(job);render();
    if(running(state.job))pollJob();else finishJob();
  }catch(e){state.busy=false;message((e as Error).message,'error');render();toast((e as Error).message,true);}
}
function finishJob() {
  state.busy=false;
  const j=state.job||{};
  state.streamedText='';const replies=list(j.events).filter(e=>e.type==='message'&&typeof e.data==='string').map(e=>e.data);for(const reply of replies)if(!state.messages.some(m=>m.role==='assistant'&&m.text===reply))message(reply);
  if(j.response||j.reply||j.assistant_message){const reply=String(j.response||j.reply||j.assistant_message);if(!state.messages.some(m=>m.role==='assistant'&&m.text===reply))message(reply);}
  else if(state.result&&blockingErrors())message(`已生成诊断预览，发现 ${issues('errors').length} 项阻断问题。请先查看右侧校核或完整报告，修正后再导出。`,'error');
  else if(done(j)&&state.result)message(isSection()?'横断面已按输入宽度与横坡生成，偏距—高程保持 1:1。请检查组成与外端高程，再导出 DXF 或连接本机 CAD。':'道路几何已完成，结果已显示在画布中。你可以检查参数与质量报告，下载可编辑 DXF，或连接本机 CAD。');
  else if(done(j))message(j.result?.message||'任务已完成。此次任务未返回道路几何，请检查任务记录。');
  else message(typeof j.error==='string'?j.error:j.error?.message||j.message||`任务${statuses[j.status]||j.status}。`,'error');
  render();
}
function pollJob() {
  clearTimeout(state.pollTimer);
  state.pollTimer=window.setTimeout(async()=>{
    try{if(!state.job)return;const j=await api(`/api/jobs/${encodeURIComponent(state.job.id)}`);adoptJob(j);render();if(running(state.job))pollJob();else finishJob();}
    catch(e){state.busy=false;toast(`获取任务状态失败，任务可能仍在后台运行：${(e as Error).message}`,true);render();}
  },1100);
}
async function download() {
  if(!canExport())return;
  try {
    const response=await fetch(`/api/jobs/${encodeURIComponent(state.job!.id)}/download.dxf`,{headers:sessionToken?{'X-Local-Token':sessionToken}:{},credentials:'same-origin'});
    if(!response.ok){const data=await response.text();throw new Error(data);}
    const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${state.projectName.replace(/[<>:"/\\|?*]/g,'_')}.dxf`;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);toast('DXF 已生成，正在交给下载程序。');
  }catch(e){toast((e as Error).message,true);}
}
async function importDxf(file:File) {
  try {
    if(state.busy)throw new Error('请等待当前任务结束后再导入。');
    const form=new FormData();form.append('file',file);const result=await api('/api/import/dxf',{method:'POST',body:form});
    const spec=result.spec||result.project?.spec;if(!spec)throw new Error(result.message||'导入接口没有返回 RoadSpec，请检查文件内容。');
    state.spec=spec;state.project=result.project||null;state.projectName=file.name.replace(/\.dxf$/i,'');state.selectedCase=null;state.selectedVariant='';state.result=null;state.job=null;state.view=null;state.messages=[];state.workspaceMode='plan';state.specDirty=false;state.importNeedsReview=false;state.streamedText='';
    message(`已导入 ${file.name}。请核对单位、中心线和未支持实体提示，再生成道路。${result.warnings?.length?'\n'+result.warnings.map((x:any)=>typeof x==='string'?x:x.message).join('\n'):''}`);render();
  }catch(e){toast((e as Error).message,true);}
}
async function saveProvider(event:SubmitEvent) {
  event.preventDefault();const value=(id:string)=>(document.getElementById(id) as HTMLInputElement).value;
  const payload:Dict={name:value('provider-name'),protocol:value('provider-protocol'),base_url:value('provider-url'),model:value('provider-model'),timeout:Number(value('provider-timeout'))};
  if(state.providerEdit?.id)payload.id=state.providerEdit.id;if(value('provider-key'))payload.api_key=value('provider-key');
  try{
    const headersText=value('provider-headers').trim();
    if(headersText){
      let headers:unknown;try{headers=JSON.parse(headersText);}catch{throw new Error('自定义请求头必须是有效 JSON 对象。请检查括号、引号和逗号。');}
      if(!headers||typeof headers!=='object'||Array.isArray(headers))throw new Error('自定义请求头必须是 JSON 对象。');
      if(Object.entries(headers).some(([key,value])=>!(/^[A-Za-z0-9-]+$/.test(key))||typeof value!=='string'||/[\r\n]/.test(value)))throw new Error('请求头名称仅支持字母、数字与连字符，值须为不含换行的字符串。');
      payload.headers=headers;
    }
    const p=await post('/api/providers',payload);state.providerEdit=p.provider||p;const data=await api('/api/bootstrap');state.bootstrap=data;state.providerId=state.providerEdit?.id||state.providerId;render();toast('接口已保存。尚未发起模型调用。');
  }catch(e){const status=document.querySelector('#provider-status');if(status)status.textContent=(e as Error).message;}
}
async function diagnoseMcp(){
  if(state.mcpBusy)return;state.mcpBusy=true;state.mcpDiagnostic=null;render();
  try{state.mcpDiagnostic=await post('/api/mcp/diagnostic');}
  catch(e){state.mcpDiagnostic={success:false,message:(e as Error).message};}
  finally{state.mcpBusy=false;render();}
}
async function refreshCad(targetId?:string) {
  const cad=await api('/api/cad/status');
  const id=targetId||state.cad.document_id||(cad.active_document?.owned?cad.active_document.document_id:null);
  if(id){
    try{cad.document=await api(`/api/cad/document?document_id=${encodeURIComponent(id)}`);cad.document_id=id;}
    catch(e){state.cad={...cad,document_id:null};throw e;}
  }
  state.cad=cad;
}
async function cadAction(action:string) {
  if(state.cadBusy)return;
  state.cadBusy=true;state.cadError='';render();
  try {
    const doc=state.cad.document||{},id=state.cad.document_id||doc.document_id||doc.id;
    if(action==='cad-import-centerlines'){
      if(state.busy)throw new Error('请完成或取消当前任务后再读取 CAD 中心线。');
      if(!confirm('请先在 CAD 中选中 LINE、ARC 或开放 LWPOLYLINE。\n确认这些对象表示道路中心线，而不是道路边界、红线或地块轮廓？\n这里只读当前选择并载入新方案，不写入原图。'))return;
      const imported=await post('/api/cad/import-centerlines',{confirmed_centerlines:true});
      if(!imported.spec||typeof imported.spec!=='object')throw new Error('CAD 导入没有返回有效 RoadSpec，请先在 CAD 选中完整中心线再重试。');
      clearTimeout(state.pollTimer);state.spec=structuredClone({...imported.spec,_import:{...imported.spec._import,source:imported.source}});state.project=null;state.projectName='CAD 中心线道路方案';state.selectedCase=null;state.selectedVariant='';state.skillId='';state.result=null;state.job=null;state.view=null;state.messages=[];state.streamedText='';state.workspaceMode='plan';state.modal='';state.specDirty=true;state.importNeedsReview=true;
      message(`已只读载入 CAD 所选中心线，原图保持未修改。源单位：${state.spec?.units||'待确认'}。请填写左右宽度与圆角半径，然后点击“确认高级 RoadSpec”：核实局部工程坐标后填 coordinate_reference=local_cartesian，明确 qa_tolerance 工程容差，并为每条道路指定 junction_type=at_grade 或 unknown。不会自动缩放、重投影或假定平交。重新生成并校核后可导出，CAD 写入另建本平台图纸。`);render();return;
    }
    if(action==='cad-inspect'){state.cadInspection=await api('/api/cad/inspect');render();return;}
    if(action==='cad-auto'){if(!canWriteCad())throw new Error('需要米制、已校核且参数未变的方案');if(!confirm('新建独立 CAD 图纸，写入当前已校核方案并保存到本地成果目录？\n不会修改已有图纸。'))return;const created=await post('/api/cad/new');const target=created.document_id;await post('/api/cad/apply',{document_id:target,job_id:state.job!.id,expected_version:created.version});await post('/api/cad/save',{document_id:target,job_id:state.job!.id});await refreshCad(target);render();toast('新图落图、回读、保存已完成。');return;}
    if(action==='cad-refresh'){await refreshCad();render();return;}
    if(action==='cad-new'){if(!confirm('在本机 CAD 中新建一个独立文档？'))return;const created=await post('/api/cad/new');state.cad={...state.cad,document_id:created.document_id,document:created};await refreshCad(created.document_id);render();toast('已锁定新建文档，请核对操作目标。');return;}
    if(action==='cad-use-active'){const current=await api('/api/cad/status');if(!current.active_document?.owned)throw new Error('CAD 当前图纸不是本次连接创建的可写图纸。');await refreshCad(current.active_document.document_id);return;}
    if(!id)throw new Error('请先连接或新建 CAD 文档。');
    if(action==='cad-apply'||action==='cad-modify'){
      if(!canWriteCad())throw new Error('当前任务必须通过校核、参数未变更，且单位为米才能写入 CAD。');
      if(!confirm(`确认${action==='cad-modify'?'更新已落图方案':'首次写入'}「${state.projectName}」到 CAD 文档 ${doc.name||state.cad.document_name||id}？\n此操作会修改该文档，请核对目标。`))return;
      const version=doc.version??state.cad.document_version;const result=await post(action==='cad-modify'?'/api/cad/modify':'/api/cad/apply',{job_id:state.job!.id,document_id:id,...(version!==undefined?{expected_version:version}:{})});toast(result.message||'CAD 操作接口返回成功。请在 CAD 核查图纸。');
    }else if(action==='cad-undo'){if(!confirm('撤销本平台对当前 CAD 文档的上一项修改？'))return;const result=await post('/api/cad/undo',{document_id:id,job_id:state.job?.id});toast(result.message||'撤销请求完成。');}
    else if(action==='cad-save'){if(!confirm('保存当前 CAD 文档？'))return;const result=await post('/api/cad/save',{document_id:id,job_id:state.job?.id});toast(result.message||'保存请求完成。');}
    await refreshCad();render();
  }catch(e){state.cadError=(e as Error).message;toast(state.cadError,true);}
  finally{state.cadBusy=false;render();}
}
function zoom(factor:number) {if(!state.result)return;const b=state.view||boundsFromEntities();const cx=b[0]+b[2]/2,cy=b[1]+b[3]/2;state.view=[cx-b[2]*factor/2,cy-b[3]*factor/2,b[2]*factor,b[3]*factor];updateCanvas();}
function updateCanvas() {const svg=document.querySelector('#plan-svg');if(svg&&state.view)svg.setAttribute('viewBox',state.view.join(' '));}
async function dispatch(action:string,element:HTMLElement) {
  if(state.cadBusy){toast('CAD 操作尚未返回，请等待当前步骤完成。');return;}
  try {
    if(['cases','skills','jobs','settings','json','compare'].includes(action)){state.modal=action;if(action==='settings')state.providerEdit=null;render();return;}
    if(action.startsWith('cad-')){await cadAction(action);return;}
    switch(action) {
      case 'library':state.library=await api('/api/library');state.modal='library';render();break;
      case 'search-library':state.library=await api('/api/library?q='+encodeURIComponent((document.querySelector('#library-query') as HTMLInputElement).value));render();break;
      case 'run-compare':state.comparison=await api('/api/compare?a='+encodeURIComponent((document.querySelector('#compare-a') as HTMLSelectElement).value)+'&b='+encodeURIComponent((document.querySelector('#compare-b') as HTMLSelectElement).value));render();break;
      case 'assignment':if(state.job){const a=document.createElement('a');a.href='/api/jobs/'+encodeURIComponent(state.job.id)+'/assignment.zip';a.download='Assignment-'+state.job.id.slice(0,8)+'.zip';a.click();}break;
      case 'restore-revision':if(state.project?.history?.length){if(!confirm('将上一版参数载入编辑区？当前 CAD 不变，需要重新计算后确认更新。'))return;state.spec=structuredClone(state.project.history.at(-1).spec);state.specDirty=true;state.result=null;state.job=null;message('上一版参数已恢复到编辑区。重新生成后记录新版本。');render();}break;
      case 'workspace':state.modal='';state.workspaceMode='assistant';render();break;
      case 'regulatory':await loadCase('regulatory-parcels');break;
      case 'toggle-workspace':readParameters();state.workspaceMode=state.workspaceMode==='assistant'?'plan':'assistant';render();break;
      case 'close-modal':state.modal='';render();break;
      case 'case':await loadCase(element.dataset.id!);break;
      case 'refresh':await bootstrap();break;
      case 'generate':await generate('geometry');break;
      case 'download':await download();break;
      case 'import':(document.getElementById('dxf-upload') as HTMLInputElement).click();break;
      case 'new-project':if(state.busy){toast('请先完成或取消当前任务。');break;}state.project=null;state.projectName='未命名道路方案';state.spec=null;state.importNeedsReview=false;state.streamedText='';state.selectedCase=null;state.result=null;state.job=null;state.messages=[];state.view=null;state.modal='cases';render();break;
      case 'project':{if(state.busy)throw new Error('请先完成或取消当前任务，再切换项目。');const p=await api(`/api/projects/${encodeURIComponent(element.dataset.id!)}`);state.project=p.project||p;state.projectName=state.project!.name;state.spec=structuredClone(state.project!.spec);state.importNeedsReview=state.spec?._import?.kind==='cad_pickfirst';state.streamedText='';state.selectedCase=state.project!.case_id?await api(`/api/cases/${encodeURIComponent(state.project!.case_id)}`):null;state.result=null;state.job=null;state.messages=[];state.view=null;state.modal='';state.workspaceMode='plan';state.specDirty=false;render();break;}
      case 'job':{if(state.busy)throw new Error('请先完成或取消当前任务，再打开其他任务。');const job=await api(`/api/jobs/${encodeURIComponent(element.dataset.id!)}`);if(job.project_id){state.project=await api(`/api/projects/${encodeURIComponent(job.project_id)}`);state.projectName=state.project!.name;state.selectedCase=state.project!.case_id?await api(`/api/cases/${encodeURIComponent(state.project!.case_id)}`):null;}state.result=null;state.importNeedsReview=false;adoptJob(job);state.messages=[];if(job.message)message(String(job.message),'user');for(const event of list(job.events))if(event.type==='message'&&typeof event.data==='string'&&!state.messages.some(m=>m.role==='assistant'&&m.text===event.data))message(event.data);if(!state.messages.length)message('已恢复此任务的参数、计算结果与校核事件。完整记录可在校核报告中查看。');state.view=null;state.modal='';state.workspaceMode='plan';render();if(running(state.job))pollJob();break;}
      case 'cancel-job':if(state.job){adoptJob(await post(`/api/jobs/${encodeURIComponent(state.job.id)}/cancel`));render();if(running(state.job))pollJob();}break;
      case 'tab':state.tab=element.dataset.tab!;render();break;
      case 'fit':state.view=null;state.selectedRoad='';render();break;
      case 'zoom-in':zoom(.8);break;
      case 'zoom-out':zoom(1.25);break;
      case 'issue':state.selectedRoad=element.dataset.road||'';state.tab='plan';render();if(!state.selectedRoad)toast('此问题未提供可定位的道路 ID，请查看完整报告。');break;
      case 'save-spec':{if(state.busy)throw new Error('请先完成或取消当前任务，再修改规格。');const value=(document.querySelector('#spec-editor') as HTMLTextAreaElement).value;const spec=JSON.parse(value);if(typeof spec!=='object'||Array.isArray(spec)||!spec)throw new Error('RoadSpec 必须为 JSON 对象。');state.spec=spec;state.result=null;state.job=null;state.view=null;state.modal='';state.workspaceMode='plan';state.specDirty=true;message('RoadSpec 已修改。请重新生成方案执行校核。');render();break;}
      case 'toggle-skill':{if(state.busy)throw new Error('请等待当前任务结束后再调整技能。');const skill=list(state.bootstrap.skills).find(s=>s.id===element.dataset.id);if(!skill)throw new Error('技能记录已变化，请刷新。');await post(`/api/skills/${encodeURIComponent(skill.id)}/toggle`,{enabled:!skill.enabled});state.bootstrap.skills=await api('/api/skills');render();toast(`技能已${skill.enabled?'停用':'启用'}。`);break;}
      case 'diagnose-skill':await diagnoseSkill(element.dataset.id!);break;
      case 'mcp-diagnostic':await diagnoseMcp();break;
      case 'new-provider':state.providerEdit=null;render();break;
      case 'edit-provider':state.providerEdit=list(state.bootstrap.providers).find(p=>p.id===element.dataset.id)||null;render();break;
      case 'delete-provider':if(confirm('移除此模型接口及其本地保存的密钥？')){await api(`/api/providers/${encodeURIComponent(element.dataset.id!)}`,{method:'DELETE'});state.providerEdit=null;await bootstrap();toast('接口已移除。');}break;
      case 'test-provider':if(confirm('主动发起一次供应商 API 连接测试？\n该测试可能使用账户额度并产生少量费用。')){element.setAttribute('disabled','');toast('正在测试接口…');const result=await post(`/api/providers/${encodeURIComponent(element.dataset.id!)}/test`);const t=typeof result==='string'?result:result.message||JSON.stringify(result);toast(t,result.ok===false);element.removeAttribute('disabled');}break;
      case 'cad':await refreshCad();state.modal='cad';render();break;
    }
  }catch(e){toast((e as Error).message,true);element.removeAttribute('disabled');}
}
function bindEvents() {
  app.querySelectorAll<HTMLElement>('[data-action]').forEach(el=>el.addEventListener('click',()=>{void dispatch(el.dataset.action!,el);}));
  document.querySelector('#project-name')?.addEventListener('input',e=>{state.projectName=(e.target as HTMLInputElement).value.trim();});
  document.querySelector('#case-choice')?.addEventListener('change',e=>{const id=(e.target as HTMLSelectElement).value;if(id)void loadCase(id);});
  document.querySelector('#variant-choice')?.addEventListener('change',e=>{if(state.selectedCase)void loadCase(state.selectedCase.id,(e.target as HTMLSelectElement).value);});
  document.querySelector('#skill-choice')?.addEventListener('change',e=>{state.skillId=(e.target as HTMLSelectElement).value;render();});
  document.querySelector('#runtime-choice')?.addEventListener('change',e=>{const draft=(document.querySelector('#chat-input') as HTMLTextAreaElement)?.value||'';state.activeRuntime=(e.target as HTMLSelectElement).value;render();(document.querySelector('#chat-input') as HTMLTextAreaElement).value=draft;});
  document.querySelector('#provider-choice')?.addEventListener('change',e=>{state.providerId=(e.target as HTMLSelectElement).value;const hint=document.querySelector('.composer-hint');if(hint)hint.textContent=state.providerId?'使用所选官方 API · 调用可能产生费用':'配置模型后可使用 AI · 手动生成始终可用';});
  document.querySelector('#chat-form')?.addEventListener('submit',e=>{e.preventDefault();const text=(document.querySelector('#chat-input') as HTMLTextAreaElement).value.trim();if(text)void generate('agent',text);});
  document.querySelector('#chat-input')?.addEventListener('keydown',e=>{const k=e as KeyboardEvent;if(k.key==='Enter'&&!k.shiftKey&&!k.isComposing){k.preventDefault();(document.querySelector('#chat-form') as HTMLFormElement).requestSubmit();}});
  document.querySelector('#provider-form')?.addEventListener('submit',e=>void saveProvider(e as SubmitEvent));
  document.querySelector('#dxf-upload')?.addEventListener('change',e=>{const file=(e.target as HTMLInputElement).files?.[0];if(file)void importDxf(file);});
  for(const input of app.querySelectorAll<HTMLInputElement>('#left-width,#right-width,#junction-radius,#reference-elevation,[data-component-field]'))input.addEventListener('change',()=>{state.specDirty=true;try{readParameters();render();toast('参数已修改。当前预览属于上次计算，请重新生成后导出。');}catch(e){render();toast((e as Error).message,true);}});
  const svg=document.querySelector<SVGSVGElement>('#plan-svg');
  if(svg){let drag:{x:number;y:number;b:number[]}|null=null;svg.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.12:.89);},{passive:false});svg.addEventListener('pointerdown',e=>{if(e.button!==0)return;drag={x:e.clientX,y:e.clientY,b:[...(state.view||boundsFromEntities())]};svg.setPointerCapture(e.pointerId);svg.classList.add('dragging');});svg.addEventListener('pointermove',e=>{if(!drag)return;const rect=svg.getBoundingClientRect(),scale=Math.max(drag.b[2]/rect.width,drag.b[3]/rect.height);state.view=[drag.b[0]-(e.clientX-drag.x)*scale,drag.b[1]-(e.clientY-drag.y)*scale,drag.b[2],drag.b[3]];updateCanvas();});svg.addEventListener('pointerup',()=>{drag=null;svg.classList.remove('dragging');});svg.addEventListener('pointercancel',()=>{drag=null;svg.classList.remove('dragging');});}
}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&state.modal){state.modal='';render();}});
render();void bootstrap().then(async()=>{const requestedCase=new URLSearchParams(location.search).get('case');if(state.connected&&requestedCase&&['regulatory-road-plan','road-cross-section'].includes(requestedCase))await loadCase(requestedCase);});

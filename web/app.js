'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {token: sessionStorage.getItem('saber-panel-token') || '', data:null, session:null, events:[], eventSession:null, view:'overview', images:new Map(), formDirty:false, voiceDirty:false, busy:false};
const clockFmt = new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
const timeFmt = new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
const time = t => t ? timeFmt.format(new Date(t*1000)) : '—';
function toast(text){ $('toast').textContent=text; $('toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').hidden=true,4500); }
async function api(path,body){
  const response = await fetch('/panel/api'+path,{method:body?'POST':'GET',headers:{'Authorization':'Bearer '+state.token,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,cache:'no-store'});
  if(!response.ok){ let text='请求失败';try{text=(await response.json()).detail||text;}catch{} if(response.status===401){$('loginOverlay').classList.remove('hidden');} throw new Error(text); }
  return response.json();
}
async function image(id){
  if(state.images.has(id))return state.images.get(id);
  const r=await fetch('/panel/api/stickers/'+encodeURIComponent(id),{headers:{Authorization:'Bearer '+state.token}});
  if(!r.ok)return '';
  const url=URL.createObjectURL(await r.blob());state.images.set(id,url);return url;
}
function link(url,label){try{const u=new URL(url);if(!['https:','http:'].includes(u.protocol))return '';return `<a class="event-link" href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(label||u.hostname)} ↗</a>`;}catch{return '';}}
function view(name){state.view=name;document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id==='view-'+name));document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x.dataset.view===name));$('viewTitle').textContent={overview:'相处概览',diary:'活动日记',tasks:'任务工作台',stickers:'表情收藏',settings:'记忆与设置'}[name];if(name==='settings')loadMemories().catch(e=>toast(e.message));if(name==='tasks')loadTasks().catch(e=>toast(e.message));}
function sessionLabel(s){return (s.group_id?'群聊':'私聊')+' · 尾号 '+String(s.group_id||s.user_id).slice(-4)+(s.is_companion?' · 伴侣':'');}
function fillSettings(s){if(!s||state.formDirty)return;const p=s.schedule;$('enabledInput').checked=!!s.proactive;$('stickersInput').checked=s.stickers_enabled;$('voiceEnabledInput').checked=s.voice_enabled;$('idleInput').value=p.idle_minutes;$('dailyInput').value=p.limit;$('quietStartInput').value=p.quiet_start_hour;$('quietEndInput').value=p.quiet_end_hour;$('personaInput').innerHTML=state.data.personas.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');$('personaInput').value=s.persona;$('companionBadge').textContent=s.is_companion?'伴侣私聊':'普通会话';$('bindCompanion').disabled=!!s.group_id||s.is_companion;}
function fillVoice(){const v=state.data?.voice;if(!v||state.voiceDirty)return;$('voiceState').textContent=v.enabled?(v.provider==='gpt_sovits'?'本机 Saber 声线':'通用中文女声'):'请先开启 voice.enabled';$('voicePitch').disabled=v.provider==='gpt_sovits';$('voiceDescription').textContent=v.provider==='gpt_sovits'?'使用本机参考音色合成中文；不同语气由参考片段控制，不使用音调滑杆。本地服务失败且开启回退时，会改用通用在线女声，日记会明确记录。':'平时文字，偶尔主动说一句。私聊说“想听你的声音”也能请求语音。朗读正文会发送给微软在线朗读服务，合成失败退回文字。';$('voiceSelect').innerHTML=Object.entries(state.data.voices).map(([id,label])=>`<option value="${esc(id)}">${esc(label)}</option>`).join('');$('voiceSelect').value=v.voice;$('voiceRate').value=v.rate_percent;$('voicePitch').value=v.pitch_hz;$('voiceProbability').value=v.proactive_probability;}
function renderStatus(){
  const d=state.data,s=state.session;if(!d)return;fillVoice();
  $('sideDot').classList.toggle('online',d.connected);$('sideConnection').textContent=d.connected?'QQ 已连接':'QQ 未连接';$('connection').textContent=d.connected?'已连接':'等待连接';$('connectionHint').textContent=d.connected?'Saber 正在这里':'检查 NapCat 登录与连接';$('modelName').textContent=d.model;
  $('pauseAll').textContent=d.paused?'恢复主动任务':'暂停主动任务';$('testNow').disabled=!s||!!s.group_id;
  if(!s){$('heroTitle').textContent='等你来打个招呼';$('heroText').textContent='先在 QQ 私聊 Saber 一条消息，会话随后会出现在这里。';return;}
  $('daily').innerHTML=`${s.schedule.used} <em>/ ${s.schedule.limit}</em>`;$('quotaBar').style.width=Math.min(100,s.schedule.used/s.schedule.limit*100)+'%';
  $('nextTime').textContent=s.proactive?time(s.schedule.earliest_at).split(' ').at(-1):'尚未开启';$('nextReason').textContent=s.schedule.reason;
  const current=s.current;const phase=current?.phase;$('phase').textContent=d.paused?'主动已暂停':current?'正在进行':'安静陪伴中';
  $('heroTitle').textContent=current?.summary||(s.proactive?'等到合适的时候，再来找你':'让陪伴从一句话开始');
  $('heroText').textContent=current?'她的实际活动会记录在下方日记中。':s.schedule.reason+'。你也可以安排一次测试，看看她此刻想说些什么。';
  document.querySelectorAll('.stage-track span').forEach(x=>x.classList.toggle('active',x.dataset.phase===phase));
  $('stageText').textContent=current?.summary||s.schedule.reason;fillSettings(s);tick();
}
const statusNames={running:'进行中',done:'已完成',failed:'未完成',queued:'等待中',cancelled:'已取消',skipped:'未打扰'};
function eventHTML(e){const d=e.detail||{};let content='';if(d.reason)content+=`<div class="event-detail">${esc(d.reason)}</div>`;if(d.provider==='gpt_sovits'&&d.profile)content+=`<div class="event-detail">语气参考：${esc(({neutral:'平静',warm:'温柔',cheerful:'开心',serious:'认真',sleepy:'晚安'})[d.profile]||d.profile)}</div>`;if(d.explanation)content+=`<div class="event-detail">选择说明：${esc(d.explanation)}</div>`;if(d.query)content+=`<div class="event-detail">搜索：${esc(d.query)}</div>`;if(d.title)content+=`<div class="event-detail">${esc(d.title)}</div>`;if(d.excerpt)content+=`<div class="event-detail">${esc(d.excerpt.slice(0,350))}</div>`;if(d.text)content+=`<div class="event-quote">${esc(d.text)}</div>`;if(d.voice===true&&e.kind==='sent'&&e.status==='done')content+='<div class="event-detail">已使用 QQ 语音发送</div>';if(d.sticker)content+=`<div class="event-detail">配图：${esc(d.sticker)}</div>`;if(d.url)content+=link(d.url);if(d.category||d.type)content+=`<div class="event-detail">${esc(d.category||d.type)}</div>`;if(d.next_consider_at)content+=`<div class="event-detail">建议下次考虑：${esc(time(d.next_consider_at))}</div>`;return `<div class="event ${esc(e.status)}"><div class="event-time">${esc(time(e.created).replace(' ','<br>')).replace('&lt;br&gt;','<br>')}</div><div class="event-node"></div><div><div class="event-title">${esc(e.summary)} <span class="event-status">${esc(statusNames[e.status]||e.status)}</span></div>${content}</div></div>`;}
function renderEvents(){const filter=$('eventFilter').value;const rows=state.events.filter(e=>filter==='all'||filter==='sent'&&e.kind==='sent'||filter==='reading'&&['reading','decision','planning'].includes(e.kind)||filter==='failed'&&['failed','cancelled','skipped'].includes(e.status));$('recentEvents').innerHTML=state.events.slice(0,5).map(eventHTML).join('')||'<div class="empty">还没有活动记录。升级之前的活动不会被补写成新日记。</div>';$('diaryEvents').innerHTML=rows.map(eventHTML).join('')||'<div class="empty">这个分类下还没有记录。</div>';const reading=state.events.find(x=>x.kind==='reading'&&x.status==='done'&&x.detail.url);$('latestReading').className=reading?'':'empty';$('latestReading').innerHTML=reading?`<div class="reading-title">${link(reading.detail.url,reading.detail.title||'随手看到的一段内容')}</div><div class="excerpt">${esc(reading.detail.excerpt||'')}</div><div class="muted">${esc(time(reading.created))} · 实际读取记录</div>`:'还没有新的阅读记录。可以安排一次主动测试。';}
async function loadEvents(before=0){const key=state.session?.key||'';if(state.eventSession!==key){state.events=[];state.eventSession=key;}const data=await api('/activities?session='+encodeURIComponent(key)+(before?'&before='+before:''));if((state.session?.key||'')!==key)return;const merged=new Map([...state.events,...data.items].map(x=>[x.id,x]));state.events=[...merged.values()].sort((a,b)=>b.id-a.id).slice(0,1000);renderEvents();}
async function loadStickers(){const {items}=await api('/stickers');$('stickerGrid').innerHTML=items.map(x=>`<div class="sticker-card"><img data-sticker="${esc(x.id)}" alt="${esc(x.label)}"><div class="sticker-name">${esc(x.label)} ${x.custom?'<span class="tiny-label">自定义</span>':''}</div><button class="secondary sticker-send" data-id="${esc(x.id)}">发给我看看</button></div>`).join('')||'<div class="empty">还没有表情图片，可以在下方添加。</div>';await Promise.all(items.map(async x=>{const url=await image(x.id);document.querySelectorAll('[data-sticker="'+x.id+'"]').forEach(el=>el.src=url);}));const hug=items.find(x=>x.id==='hug')||items[0];if(hug){$('heroSticker').src=await image(hug.id);$('heroSticker').hidden=false;}}
async function loadMemories(){
  if(!state.session)return;
  const key=state.session.key;
  const [result,c]=await Promise.all([api('/memories?session='+encodeURIComponent(key)),api('/continuity?session='+encodeURIComponent(key))]);
  if(state.session?.key!==key)return;
  $('memoryList').innerHTML=result.items.map(x=>`<div class="memory-item"><p>${esc(x.content)}</p><button class="text-button memory-delete" data-id="${x.id}">忘记</button></div>`).join('')||'<div class="empty">还没有显式记忆。只保存你希望她记住的事。</div>';
  $('history').innerHTML=result.history.map(x=>`<div class="history-row"><span class="history-role">${x.role==='assistant'?'Saber':'你'}</span><span class="history-text">${esc(x.content)}</span></div>`).join('')||'<div class="empty">还没有保存的对话。</div>';
  $('rollingSummary').textContent=c.summary_enabled?(c.summary||'还没有生成摘要，最近对话仍正常保留。'):'此私聊尚未开启自动摘要。';
  $('summaryMeta').textContent=c.summary_enabled?`更新：${time(c.summary_at)} · 待整理 ${c.pending_messages} 条消息 · 保留 ${c.archive_turns} 组归档`:'';
  $('clearSummary').disabled=!c.summary_enabled;
  $('moodLabel').textContent=c.mood_enabled?c.mood_label:'未启用';
  $('moodValue').textContent=c.mood_enabled?`当前角色状态 ${c.mood}/100，会逐渐恢复平静。`:'';
  $('moodEvent').textContent=c.mood_enabled?'最近变化：'+c.mood_event:'';
  $('resetMood').disabled=!c.mood_enabled;
}

async function refresh(){if(!state.token||state.busy)return;state.busy=true;try{const d=await api('/status');state.data=d;const old=state.session?.key||localStorage.getItem('saber-panel-session');state.session=d.sessions.find(x=>x.key===old)||d.sessions.find(x=>x.is_companion)||d.sessions.find(x=>x.proactive&&!x.group_id)||d.sessions.find(x=>!x.group_id)||d.sessions[0]||null;$('sessionSelect').innerHTML=d.sessions.map(x=>`<option value="${esc(x.key)}">${esc(sessionLabel(x))}</option>`).join('')||'<option>暂无会话</option>';if(state.session)$('sessionSelect').value=state.session.key;renderStatus();await loadEvents();if(state.view==='settings')await loadMemories();}catch(e){toast(e.message);}finally{state.busy=false;}}
function tick(){const now=Date.now()/1000;$('clock').textContent='北京时间 '+clockFmt.format(new Date());if(state.data){const seconds=Math.max(0,Math.ceil(state.data.next_check_at-now));$('nextTick').textContent=seconds>0?seconds+' 秒':'即将检查';}}
async function control(action,values={}){await api('/control',{action,session:state.session?.key,...values});await refresh();}
$('loginForm').addEventListener('submit',async e=>{e.preventDefault();state.token=$('tokenInput').value.trim();try{await api('/status');sessionStorage.setItem('saber-panel-token',state.token);$('tokenInput').value='';$('loginError').textContent='';$('loginOverlay').classList.add('hidden');await refresh();await loadStickers();}catch(error){$('loginError').textContent=error.message;}});
$('logout').onclick=()=>{state.token='';sessionStorage.removeItem('saber-panel-token');$('loginOverlay').classList.remove('hidden');for(const url of state.images.values())URL.revokeObjectURL(url);state.images.clear();};
document.querySelectorAll('.nav').forEach(x=>x.onclick=()=>view(x.dataset.view));document.querySelectorAll('[data-go]').forEach(x=>x.onclick=()=>view(x.dataset.go));
$('sessionSelect').onchange=async()=>{state.session=state.data.sessions.find(x=>x.key===$('sessionSelect').value);if(!state.session)return;localStorage.setItem('saber-panel-session',state.session.key);state.formDirty=false;renderStatus();await loadEvents();await loadMemories();};
$('refresh').onclick=()=>refresh();$('eventFilter').onchange=renderEvents;$('olderEvents').onclick=()=>loadEvents(state.events.at(-1)?.id||0).catch(e=>toast(e.message));
$('testNow').onclick=async()=>{try{await control('test');toast('已排队，稍后会实际发到这个 QQ 私聊。');}catch(e){toast(e.message);}};
$('pauseAll').onclick=async()=>{try{await control('pause',{paused:!state.data.paused});toast(state.data.paused?'主动任务已暂停':'主动任务已恢复');}catch(e){toast(e.message);}};
$('settingsForm').oninput=()=>state.formDirty=true;
$('settingsForm').onsubmit=async e=>{e.preventDefault();if(!state.session)return;const values={idle_minutes:Number($('idleInput').value),max_daily_attempts:Number($('dailyInput').value),quiet_start_hour:Number($('quietStartInput').value),quiet_end_hour:Number($('quietEndInput').value),stickers_enabled:$('stickersInput').checked,voice_enabled:$('voiceEnabledInput').checked};if(!state.session.group_id)values.proactive=$('enabledInput').checked;if($('personaInput').value!==state.session.persona)values.persona=$('personaInput').value;try{await control('settings',values);state.formDirty=false;await refresh();toast('偏好已保存，即时生效。');}catch(error){toast(error.message);}};
$('bindCompanion').onclick=async()=>{try{await control('bind_companion');state.formDirty=false;await refresh();toast('已绑定伴侣账号。');}catch(e){toast(e.message);}};
$('memoryForm').onsubmit=async e=>{e.preventDefault();try{await api('/memories',{session:state.session?.key,content:$('memoryInput').value});$('memoryInput').value='';await loadMemories();toast('已经记住了。');}catch(error){toast(error.message);}};
document.addEventListener('click',async e=>{const del=e.target.closest('.memory-delete');const sticker=e.target.closest('.sticker-send');try{if(del){await api('/memories',{session:state.session?.key,action:'delete',id:Number(del.dataset.id)});await loadMemories();toast('已删除这条记忆。');}if(sticker){await control('sticker_test',{sticker:sticker.dataset.id});toast('表情测试已排队。');}}catch(error){toast(error.message);}});
$('uploadForm').onsubmit=async e=>{e.preventDefault();try{const file=$('stickerFile').files[0];if(!file)throw new Error('请先选择图片');if(file.size>(state.data?.max_image_bytes||1048576))throw new Error('图片超过大小限制');const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});await api('/stickers',{label:$('stickerLabel').value,image:encoded});$('uploadForm').reset();await loadStickers();toast('新表情已加入，下一轮对话即可选择。');}catch(error){toast(error.message);}};

$('voiceForm').oninput=()=>state.voiceDirty=true;
$('voiceForm').onsubmit=async e=>{e.preventDefault();try{await control('voice_settings',{voice:$('voiceSelect').value,rate_percent:Number($('voiceRate').value),pitch_hz:Number($('voicePitch').value),proactive_probability:Number($('voiceProbability').value)});state.voiceDirty=false;await refresh();toast('声音设置已保存。');}catch(error){toast(error.message);}};
$('sendVoiceTest').onclick=async()=>{try{await control('voice_test');toast('语音测试已排队，会发送到选中的私聊。');}catch(error){toast(error.message);}};
$('previewVoice').onclick=async()=>{const button=$('previewVoice');button.disabled=true;try{const r=await fetch('/panel/api/voice/preview',{method:'POST',headers:{Authorization:'Bearer '+state.token}});if(!r.ok){let detail='试听失败';try{detail=(await r.json()).detail||detail;}catch{}throw new Error(detail);}const player=$('voicePlayer');if(player.dataset.blob)URL.revokeObjectURL(player.dataset.blob);const url=URL.createObjectURL(await r.blob());player.dataset.blob=url;player.src=url;player.hidden=false;await player.play();}catch(error){toast(error.message);}finally{button.disabled=false;}};
$('previewVoiceSoft').onclick=async()=>{const button=$('previewVoiceSoft');button.disabled=true;try{const r=await fetch('/panel/api/voice/preview?variant=soft',{method:'POST',headers:{Authorization:'Bearer '+state.token}});if(!r.ok){let detail='试听失败';try{detail=(await r.json()).detail||detail;}catch{}throw new Error(detail);}const player=$('voicePlayer');if(player.dataset.blob)URL.revokeObjectURL(player.dataset.blob);const url=URL.createObjectURL(await r.blob());player.dataset.blob=url;player.src=url;player.hidden=false;await player.play();}catch(error){toast(error.message);}finally{button.disabled=false;}};
setInterval(tick,1000);setInterval(refresh,5000);tick();if(state.token){api('/status').then(async()=>{$('loginOverlay').classList.add('hidden');await refresh();await loadStickers();}).catch(()=>{});}

$('clearSummary').onclick=async()=>{try{await api('/continuity',{session:state.session?.key,action:'clear_summary'});await loadMemories();toast('摘要与较早归档已清除，最近对话和显式记忆保留。');}catch(e){toast(e.message);}};
$('resetMood').onclick=async()=>{try{await api('/continuity',{session:state.session?.key,action:'reset_mood'});await loadMemories();toast('角色状态已恢复平静。');}catch(e){toast(e.message);}};

async function loadTasks(){
  const {items,automatic,paused,desktop_enabled,desktop_auto}=await api('/tasks');
  state.desktopEnabled=desktop_enabled;
  state.desktopAuto=desktop_auto;
  $('toggleDesktop').textContent=desktop_enabled?'关闭电脑工具':'开启电脑工具';
  $('desktopStatus').textContent=desktop_enabled?'已允许手动任务使用电脑工具。':'已关闭；也请确认本机桌面桥服务已启动。';
  $('toggleDesktopAuto').textContent=desktop_auto?'关闭自主桌面操作':'开启自主桌面操作';
  $('desktopAutoStatus').textContent=desktop_auto?(desktop_enabled?'自主桌面操作已开启，受主动时间和次数限制。':'自主桌面开关已开启，但电脑工具总开关关闭。'):'自主桌面操作已关闭。';
  state.autoExplore=automatic;
  $('toggleAuto').textContent=automatic?'关闭自主探索':'开启自主探索';
  $('autoStatus').textContent=automatic?(paused?'已开启，但全部主动任务目前暂停。':'已开启，等待合适时机。'):'已关闭；你仍可在下方手动交给她任务。';
  const names={queued:'等待中',running:'执行中',done:'已完成',failed:'未完成',cancelled:'已停止',interrupted:'重启中断',limited:'达到步数上限'};
  $('taskList').innerHTML=items.map(t=>`<article class="memory-item"><p><strong>${esc(t.goal)}</strong> · ${esc(names[t.status]||t.status)}</p>${t.steps.map(s=>`<p class="muted">${esc(s.tool)} · ${esc(s.reason)} · ${esc(names[s.status]||s.status)}</p>`).join('')}<p style="white-space:pre-wrap">${esc(t.result)}</p>${['queued','running'].includes(t.status)?`<button class="secondary task-stop" data-id="${esc(t.id)}">停止此任务</button>`:''}${t.file?`<button class="secondary task-note" data-id="${esc(t.id)}">下载笔记</button>`:''}</article>`).join('')||'还没有任务。';
}
$('taskForm').onsubmit=async e=>{e.preventDefault();try{await api('/tasks',{action:'start',session:state.session?.key,goal:$('taskGoal').value});await loadTasks();toast('已开始，Saber 会在权限范围内选择步骤。');}catch(e){toast(e.message);}};
$('toggleAuto').onclick=async()=>{try{await api('/tasks',{action:'automatic',enabled:!state.autoExplore});await loadTasks();toast('自主探索设置已更新。');}catch(e){toast(e.message);}};
$('toggleDesktop').onclick=async()=>{try{await api('/tasks',{action:'desktop',enabled:!state.desktopEnabled});await loadTasks();toast('电脑工具设置已更新。');}catch(e){toast(e.message);}};
$('toggleDesktopAuto').onclick=async()=>{try{await api('/tasks',{action:'desktop_auto',enabled:!state.desktopAuto});await loadTasks();toast('自主桌面操作设置已更新。');}catch(e){toast(e.message);}};
document.addEventListener('click',async e=>{const stop=e.target.closest('.task-stop'),note=e.target.closest('.task-note');try{if(stop){await api('/tasks',{action:'stop',id:stop.dataset.id});await loadTasks();}if(note){const r=await fetch('/panel/api/tasks/'+encodeURIComponent(note.dataset.id)+'/note',{headers:{Authorization:'Bearer '+state.token}});if(!r.ok)throw new Error('笔记下载失败');const u=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=u;a.download=note.dataset.id+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}}catch(e){toast(e.message);}});
setInterval(()=>{if(state.token&&state.view==='tasks')loadTasks().catch(e=>toast(e.message));},3000);

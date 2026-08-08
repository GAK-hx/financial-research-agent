from __future__ import annotations


DEMO_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>股票分析 Agent · 运行台</title>
  <style>
    :root{color-scheme:dark;--bg:#0b1020;--card:#141b2d;--line:#29334d;--text:#edf2ff;--muted:#9ba9c6;--accent:#67d5b5;--warn:#ffc86b}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#162847 0,var(--bg) 42%);color:var(--text);font:15px/1.55 ui-sans-serif,system-ui}
    main{max-width:1180px;margin:auto;padding:36px 22px 64px}h1{font-size:28px;margin:0 0 6px}.sub{color:var(--muted);margin-bottom:24px}
    .grid{display:grid;grid-template-columns:minmax(300px,.75fr) minmax(420px,1.25fr);gap:16px}.card{background:rgba(20,27,45,.94);border:1px solid var(--line);border-radius:14px;padding:18px}
    label{display:block;color:var(--muted);font-size:12px;margin:12px 0 5px}input,textarea,select,button{width:100%;border:1px solid var(--line);border-radius:9px;background:#0d1425;color:var(--text);padding:10px 12px;font:inherit}
    textarea{min-height:112px;resize:vertical}button{margin-top:14px;background:var(--accent);color:#07140f;border:0;font-weight:700;cursor:pointer}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
    .status{display:flex;gap:9px;align-items:center;margin-bottom:12px}.pill{border:1px solid var(--line);border-radius:999px;padding:3px 9px;color:var(--warn)}pre{white-space:pre-wrap;word-break:break-word;background:#0a1020;border-radius:9px;padding:12px;max-height:330px;overflow:auto;color:#cbd8f5}
    .events{display:grid;gap:7px;max-height:310px;overflow:auto}.event{border-left:3px solid var(--accent);padding:7px 10px;background:#0d1425}.event small{color:var(--muted)}
    @media(max-width:820px){.grid{grid-template-columns:1fr}}
  </style>
</head>
<body><main>
  <h1>股票分析 Agent · 运行台</h1>
  <div class="sub">异步 Job、受控 Tool、Evidence、校验与报告的一页式调试视图</div>
  <div class="grid">
    <section class="card">
      <div class="row"><div><label>租户</label><input id="tenant" value="local"></div><div><label>用户</label><input id="user" value="local"></div></div>
      <label>API Key（local 模式留空）</label><input id="key" type="password" autocomplete="off">
      <label>查询</label><textarea id="question">分析贵州茅台近期技术面与主要风险</textarea>
      <label>任务类型</label><select id="queue"><option value="interactive">交互查询</option><option value="batch">离线批处理</option></select>
      <button id="run">开始分析</button>
      <label>当前 Run ID</label><input id="runId" readonly>
    </section>
    <section class="card">
      <div class="status"><strong>运行状态</strong><span class="pill" id="status">idle</span></div>
      <div class="events" id="events"></div>
      <label>最终结果 / 错误</label><pre id="result">尚未运行</pre>
    </section>
  </div>
  <script>
    const $=id=>document.getElementById(id); let timer=null,cursor=0;
    const headers=()=>{const h={'Content-Type':'application/json','X-Tenant-ID':$('tenant').value,'X-User-ID':$('user').value};if($('key').value)h.Authorization='Bearer '+$('key').value;return h};
    const show=(v)=>{$('result').textContent=typeof v==='string'?v:JSON.stringify(v,null,2)};
    async function poll(runId){try{const h=headers();const [state,events]=await Promise.all([fetch('/runs/'+runId,{headers:h}),fetch('/runs/'+runId+'/events.json?after='+cursor,{headers:h})]);const sj=await state.json(),ej=await events.json();if(!state.ok)throw sj;for(const e of ej.events||[]){cursor=e.event_id;const d=document.createElement('div');d.className='event';const t=document.createElement('strong');t.textContent=e.event_type;const s=document.createElement('small');s.textContent=' · '+(e.node_name||e.source)+' · #'+e.event_id;d.append(t,s);$('events').append(d)}const status=sj.job?.status||'error';$('status').textContent=status;if(['completed','failed','cancelled'].includes(status)){clearInterval(timer);show(sj.result||sj)}else show({job:sj.job,last_event_id:cursor})}catch(e){clearInterval(timer);$('status').textContent='error';show(e)}}
    $('run').onclick=async()=>{clearInterval(timer);cursor=0;$('events').replaceChildren();$('status').textContent='submitting';try{const h=headers();h['Idempotency-Key']=crypto.randomUUID();const r=await fetch('/runs',{method:'POST',headers:h,body:JSON.stringify({question:$('question').value,queue_class:$('queue').value})});const b=await r.json();if(!r.ok)throw b;const id=b.job.run_id;$('runId').value=id;$('status').textContent=b.job.status;await poll(id);timer=setInterval(()=>poll(id),900)}catch(e){$('status').textContent='rejected';show(e)}};
  </script>
</main></body></html>"""

"""HTML for the portal's browser experience (deployment layer, Phase 3).

Three pages, all served by app/portal.py:
  home_html()        GET /            browse + search questions, create a new one
  viewer_html(qid)   GET /q/{id}      the read view — reuses viewer/template.html, rendered live
  contribute_html()  GET /q/{id}/add  add sources WITHOUT a server key: find (OpenAlex, free) ->
                                       fetch best available paper text -> copy a labelling prompt for YOUR chatbot
                                       -> paste the JSON back -> deterministic merge server-side.

The contribute flow keeps the manual / chatbot path available in the browser (no key ever leaves
the user's own chatbot), mirroring the local CLI's --dry-run path.
"""
import os

from engine.assess import assess
from engine.render import json_for_script

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# shared palette (matches viewer/template.html)
_CSS = """
:root{--bg:#F5F6F7;--surface:#FFFFFF;--ink:#15171B;--muted:#61676E;--faint:#8A9098;
--line:#E4E7EA;--line-strong:#CDD2D7;--chrome:#1B1D24;--ochre:#8a6510;--flag:#2f6296;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--sans:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;}
*{box-sizing:border-box;} body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);}
a{color:var(--flag);text-decoration:none;} a:hover{text-decoration:underline;}
.wrap{max-width:960px;margin:0 auto;padding:32px 24px 80px;}
.kicker{font-family:var(--mono);font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);}
h1{font-size:30px;margin:6px 0 4px;letter-spacing:-.01em;} .sub{color:var(--muted);max-width:60ch;margin:0 0 26px;}
input,button,textarea{font:inherit;}
button{cursor:pointer;} input[type=checkbox]{cursor:pointer;}
.bar{display:flex;gap:10px;margin:0 0 22px;flex-wrap:wrap;}
.bar input{flex:1;min-width:220px;padding:11px 13px;border:1px solid var(--line-strong);border-radius:9px;background:#fff;}
.btn{padding:11px 16px;border:1px solid var(--chrome);background:var(--chrome);color:#fff;border-radius:9px;cursor:pointer;transition:opacity .15s,box-shadow .15s;}
.btn.ghost{background:#fff;color:var(--ink);border-color:var(--line-strong);}
.btn:hover{opacity:.92;box-shadow:0 1px 4px rgba(0,0,0,.12);} .btn.ghost:hover{border-color:var(--chrome);background:#fafbfc;}
.btn:disabled{opacity:.5;cursor:default;box-shadow:none;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;}
.card{display:block;border:1px solid var(--line);border-radius:12px;padding:16px;background:var(--surface);cursor:pointer;transition:border-color .15s,box-shadow .15s,transform .15s;}
.card:hover{border-color:var(--line-strong);text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.09);transform:translateY(-2px);}
.card .q{font-size:16px;font-weight:600;color:var(--ink);line-height:1.35;}
.card:hover .q{color:var(--flag);}
.card .meta{font-family:var(--mono);font-size:12px;color:var(--faint);margin-top:10px;display:flex;gap:12px;flex-wrap:wrap;}
.empty{color:var(--muted);padding:30px 0;}
.back{font-family:var(--mono);font-size:12px;color:var(--muted);}
.back a{cursor:pointer;}
.panel{border:1px solid var(--line);border-radius:12px;padding:18px;background:var(--surface);margin:16px 0;}
.panel h2{font-size:17px;margin:0 0 4px;} .panel .desc{color:var(--muted);font-size:14px;margin:0 0 14px;}
.step{font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);}
.btn.sm{padding:6px 13px;border-radius:8px;font-size:13px;}
/* review cards: ensemble disagreements to resolve */
.rev{border:1px solid var(--line);border-radius:11px;padding:14px 16px;margin:12px 0;background:var(--surface);}
.rev-h{font-weight:600;font-size:15px;line-height:1.4;}
.rev-h .yr{font-family:var(--mono);font-size:12px;color:var(--faint);font-weight:400;}
.rev-h a{font-size:12.5px;}
.rev-badge{display:inline-block;font-family:var(--mono);font-size:10px;letter-spacing:.03em;padding:2px 7px;border-radius:5px;white-space:nowrap;vertical-align:middle;}
.rev-badge.merged{background:#F5ECD6;color:#8a6510;} .rev-badge.queued{background:#EEF0F1;color:var(--muted);}
.rev-cur{font-size:12.5px;color:var(--muted);margin-top:4px;}
.rev-opts{margin:11px 0 0;border:1px solid var(--line);border-radius:9px;overflow:hidden;}
.rev-opt{display:flex;align-items:center;gap:12px;padding:10px 12px;border-top:1px solid var(--line);}
.rev-opt:first-child{border-top:0;} .rev-opt:hover{background:#fafbfc;}
.rev-opt .oi{flex:1;min-width:0;}
.rev-opt .on{font-weight:600;font-size:13.5px;}
.rev-opt .ov{font-family:var(--mono);font-size:11px;color:var(--faint);}
.rev-opt .oq{font-size:12px;color:var(--muted);margin-top:2px;line-height:1.4;}
.rev-act{display:flex;gap:8px;align-items:center;margin-top:11px;flex-wrap:wrap;}
.rev-act select{flex:1;min-width:160px;padding:8px 10px;border:1px solid var(--line-strong);border-radius:8px;background:#fff;}
.kindsel{flex:0 0 auto;padding:6px 9px;border:1px solid var(--line-strong);border-radius:8px;background:#fff;color:var(--ink);font:inherit;font-size:12.5px;cursor:pointer;}
.kindsel:focus{outline:none;border-color:var(--chrome);}
.rev-act .btn{padding:7px 12px;font-size:13px;}
.rev-abs{margin:8px 0 0;} .rev-abs summary{font-size:12.5px;color:var(--muted);cursor:pointer;}
.cand{display:flex;gap:9px;align-items:flex-start;padding:8px 6px;border-top:1px solid var(--line);border-radius:6px;transition:background .12s;}
.cand:hover{background:#fafbfc;}
.cand label{font-size:14px;cursor:pointer;} .cand .why{color:var(--faint);font-size:12px;font-family:var(--mono);}
.dsrow{align-items:center;flex-wrap:wrap;}
.combo{position:relative;flex:0 0 200px;min-width:150px;}
.combo-in{width:100%;padding:8px 10px;border:1px solid var(--line-strong);border-radius:8px;background:#fff;color:var(--ink);}
.combo-in::placeholder{color:var(--faint);}
.combo-in:focus{outline:none;border-color:var(--chrome);box-shadow:0 1px 4px rgba(0,0,0,.08);}
.combo-menu{position:absolute;z-index:30;top:calc(100% + 4px);right:0;left:auto;width:max-content;min-width:100%;max-width:min(460px,88vw);max-height:280px;overflow:auto;background:var(--surface);border:1px solid var(--line-strong);border-radius:9px;box-shadow:0 8px 24px rgba(0,0,0,.14);display:none;padding:4px;}
.combo-menu.open{display:block;}
.combo-opt{padding:8px 10px;border-radius:6px;font-size:13px;line-height:1.35;color:var(--ink);cursor:pointer;white-space:normal;overflow-wrap:anywhere;}
.combo-opt:hover,.combo-opt.active{background:#f2f4f6;}
.combo-opt .why{color:var(--faint);font-size:11px;font-family:var(--mono);}
.combo-empty{padding:9px 10px;color:var(--muted);font-size:12.5px;}
textarea{width:100%;border:1px solid var(--line-strong);border-radius:9px;padding:10px;min-height:120px;font-family:var(--mono);font-size:12px;}
.toast{margin-top:10px;font-size:13px;color:var(--muted);} .toast.ok{color:#2E8B6F;} .toast.warn{color:var(--ochre);}
.log{background:#0d0f13;color:#cfe;border-radius:8px;padding:10px;font-family:var(--mono);font-size:12px;white-space:pre-wrap;margin-top:10px;display:none;}
.overlay{position:fixed;inset:0;background:rgba(21,23,27,.45);backdrop-filter:blur(2px);
  display:none;align-items:flex-start;justify-content:center;padding:14vh 20px 20px;z-index:50;}
.overlay.show{display:flex;}
.modal{background:var(--surface);border:1px solid var(--line-strong);border-radius:14px;
  width:100%;max-width:520px;padding:22px 22px 18px;box-shadow:0 18px 50px rgba(0,0,0,.22);
  animation:pop .14s ease-out;}
@keyframes pop{from{opacity:0;transform:translateY(-6px) scale(.98);}to{opacity:1;transform:none;}}
.modal h2{margin:0 0 4px;font-size:19px;}
.modal .desc{color:var(--muted);font-size:13.5px;margin:0 0 14px;}
.modal textarea{width:100%;border:1px solid var(--line-strong);border-radius:9px;padding:11px 12px;
  font:inherit;font-size:15px;min-height:70px;resize:vertical;}
.modal textarea:focus{outline:none;border-color:var(--flag);box-shadow:0 0 0 3px rgba(47,98,150,.12);}
.modal .actions{display:flex;justify-content:flex-end;gap:9px;margin-top:14px;}
.modal .hintline{color:var(--faint);font-size:12px;margin-top:9px;}
pre{background:#0d0f13;color:#e6edf3;border-radius:9px;padding:13px 15px;overflow-x:auto;
  font-family:var(--mono);font-size:12.5px;line-height:1.65;margin:10px 0;}
pre .c{color:#7d8590;}
.doc code{font-family:var(--mono);font-size:.88em;background:#eef0f2;padding:1px 5px;border-radius:5px;color:#0d0f13;}
.doc h2{font-size:20px;margin:34px 0 6px;letter-spacing:-.01em;}
.doc h3{font-size:15px;margin:22px 0 4px;}
.doc p,.doc li{color:var(--muted);line-height:1.65;}
.doc ul,.doc ol{margin:8px 0;padding-left:22px;} .doc li{margin:3px 0;}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 8px;}
.toc a{font-size:13px;padding:5px 12px;border:1px solid var(--line-strong);border-radius:20px;color:var(--muted);}
.toc a:hover{border-color:var(--chrome);color:var(--ink);text-decoration:none;}
.cmdtbl{width:100%;border-collapse:collapse;margin:8px 0;font-size:13.5px;}
.cmdtbl td{border-top:1px solid var(--line);padding:8px 8px;vertical-align:top;color:var(--muted);}
.cmdtbl td:first-child{white-space:nowrap;width:1%;}
.note{background:#eef4fb;border-left:3px solid var(--flag);border-radius:0 8px 8px 0;
  padding:11px 14px;margin:14px 0;font-size:13.5px;color:var(--ink);line-height:1.6;}
.thesis{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:0 0 26px;}
.tcol{border:1px solid var(--line);border-radius:12px;padding:15px 16px;background:var(--surface);}
.tnum{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--flag);margin-bottom:6px;}
.tcol p{margin:0;font-size:13.5px;line-height:1.55;color:var(--muted);}
@media (max-width:720px){
  .wrap{padding:22px 16px 64px;}
  h1{font-size:24px;}
  .thesis{grid-template-columns:1fr;gap:10px;margin-bottom:20px;}
  .bar{gap:8px;}
  .bar input:not([type=number]){flex:1 1 100%!important;min-width:0;}
  .bar input[type=number]{flex:0 0 72px!important;}
  .bar .btn{flex:1;text-align:center;justify-content:center;}
  .grid{grid-template-columns:1fr;}
  .toc{gap:6px;} .cmdtbl td:first-child{white-space:normal;}
  pre{font-size:11.5px;}
}
"""


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _page(title, body):
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>{}</title><style>{}</style></head><body><div class='wrap'>{}</div></body></html>"
            ).format(_esc(title), _CSS, body)


def home_html():
    body = """
    <div class="kicker">Ground Knowledge</div>
    <h1>Research disputes, mapped by the evidence</h1>
    <p class="sub">See how the evidence on a contested question splits — and whether an apparent
    consensus is real, or just the same few sources counted many times.</p>

    <div class="thesis">
      <div class="tcol">
        <div class="tnum">1 · The problem</div>
        <p>Count the sources and whoever publishes most appears to win — even when it's the same
        lab, funder, or dataset showing up again and again. That's how <b>false balance</b> creeps in.</p>
      </div>
      <div class="tcol">
        <div class="tnum">2 · The fix</div>
        <p>We show <b>confirmed evidence-root coverage</b>, not headcount. Ten papers resting on one
        dataset cover roughly <b>one</b> root — while quality and shared-method bias stay separate.</p>
      </div>
      <div class="tcol">
        <div class="tnum">3 · How</div>
        <p>Each source is fetched, labelled with a quote-backed position, and merged into a living
        map — positions, shared datasets, the real cruxes, and each side's blind spots.</p>
      </div>
    </div>

    <div class="bar">
      <input id="q" placeholder="Search questions…" autocomplete="off">
      <button class="btn ghost" onclick="newQ()">+ New question</button>
      <a class="btn ghost" href="/docs" style="display:inline-flex;align-items:center;text-decoration:none">⌨ CLI &amp; local app</a>
    </div>
    <div id="list" class="grid"></div>

    <div class="overlay" id="nqOverlay">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="nqTitle">
        <h2 id="nqTitle">New question</h2>
        <p class="desc">State it as a yes/no research dispute — the way the two sides would frame it.</p>
        <textarea id="nqInput" placeholder="e.g. Do eggs increase cardiovascular disease risk?"></textarea>
        <div class="hintline">Press ⌘/Ctrl + Enter to create · Esc to cancel</div>
        <div class="actions">
          <button class="btn ghost" onclick="closeNQ()">Cancel</button>
          <button class="btn" id="nqCreate" onclick="createNQ()">Create question</button>
        </div>
      </div>
    </div>

    <script>
    const E=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    async function load(){
      const s=document.getElementById('q').value.trim();
      const r=await fetch('/api/questions'+(s?'?search='+encodeURIComponent(s):''));
      const {questions}=await r.json();
      const box=document.getElementById('list');
      if(!questions.length){box.innerHTML='<div class="empty">No questions yet. Create one above.</div>';return;}
      box.innerHTML=questions.map(q=>{
        const c=q.counts||{};
        return `<a class="card" href="/q/${q.id}">
          <div class="q">${E(q.question)}</div>
          <div class="meta"><span>v${c.version||0}</span><span>${c.sources||0} sources</span>
          <span>${c.positions||0} positions</span><span>${c.datasets||0} datasets</span></div></a>`;
      }).join('');
    }
    const ov=document.getElementById('nqOverlay'), nqIn=document.getElementById('nqInput');
    function newQ(){ov.classList.add('show');nqIn.value=document.getElementById('q').value.trim();
      setTimeout(()=>{nqIn.focus();nqIn.select();},30);}
    function closeNQ(){ov.classList.remove('show');}
    async function createNQ(){
      const question=nqIn.value.trim();
      if(!question){nqIn.focus();return;}
      const btn=document.getElementById('nqCreate');btn.disabled=true;btn.textContent='Creating…';
      try{
        const r=await fetch('/api/questions',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({question})});
        const j=await r.json();
        if(j.id){location.href='/q/'+j.id;return;}
        btn.disabled=false;btn.textContent='Create question';
      }catch(e){btn.disabled=false;btn.textContent='Create question';}
    }
    ov.addEventListener('click',e=>{if(e.target===ov)closeNQ();});       // click outside to close
    document.addEventListener('keydown',e=>{
      if(e.key==='Escape')closeNQ();
      if((e.metaKey||e.ctrlKey)&&e.key==='Enter'&&ov.classList.contains('show'))createNQ();
    });
    let t;document.getElementById('q').addEventListener('input',()=>{clearTimeout(t);t=setTimeout(load,200);});
    load();
    </script>"""
    return _page("Ground Knowledge", body)


def docs_html(repo="https://github.com/Zhenia-Magic/epistemic-coverage"):
    """Static documentation page for the power-user tools: the CLI and the local web console.
    Explains why they exist, how to install and configure them, and the command reference."""
    body = """
    <div class="back"><a href="/">← all questions</a></div>
    <div class="kicker">Ground Knowledge</div>
    <h1>Power tools: the CLI &amp; local app</h1>
    <p class="sub">This website is the easy, keyless way to read and contribute. The
    <b>command-line tool</b> and the <b>local web console</b> are for power users who want to
    cold-start a whole question, label sources automatically with their own AI key, batch-import
    citations, or curate the knowledge base — then push the result back here.</p>

    <div class="doc">
    <div class="toc">
      <a href="#why">Why these exist</a>
      <a href="#install">Install</a>
      <a href="#configure">Configure</a>
      <a href="#localui">Local app</a>
      <a href="#cli">CLI commands</a>
      <a href="#workflow">A typical workflow</a>
      <a href="#sync">Push &amp; pull</a>
    </div>

    <h2 id="why">Why these exist</h2>
    <p>The portal does <b>no AI work and holds no API key</b> — contributing here means you fetch a
    source, copy a labelling prompt into your own chatbot, and paste the JSON back. That keeps the
    server safe and free to run. The local tools remove the copy-paste: with your own AI key they
    label automatically, and they can do things the website can't:</p>
    <ul>
      <li><b>Cold-start</b> a brand-new question from scratch (discover + label dozens of sources).</li>
      <li><b>Automatic labelling</b> of fetched text using your own key — Anthropic, NVIDIA (free, build.nvidia.com), OpenAI, DeepSeek, Mistral, Groq, Gemini, or OpenRouter. Set an Anthropic <i>and</i> an NVIDIA key together and Claude does the web search while NVIDIA does the (free) labelling.</li>
      <li><b>Import a whole library</b> from Zotero / Mendeley / EndNote (.ris, .bib, .csl-json).</li>
      <li><b>Curate</b>: merge duplicate datasets, rename, tidy messy labels.</li>
      <li><b>Push / pull</b> a knowledge base between your machine and this portal.</li>
    </ul>
    <div class="note">Everything except <i>automatic</i> labelling works with <b>no API key</b> —
    finding, fetching, the local store, the viewer, push/pull and the manual (chatbot) path all run
    keyless, exactly like this website.</div>

    <h2 id="install">Install</h2>
    <p>You need <b>Python 3.9+</b> and <code>git</code>. The core engine, viewer, fetching, the
    manual path and the local store need <b>no third-party packages</b>.</p>
    <pre><span class="c"># 1. Get the code</span>
git clone %REPO%.git
cd epistemic-coverage

<span class="c"># 2. (optional) extras — only for full-text PDF, .docx, or running the portal yourself</span>
pip install -r requirements.txt</pre>
    <p>That's it — <code>python cli.py --help</code> should now list every command.</p>

    <h2 id="configure">Configure (.env)</h2>
    <p>Copy the template and fill in what you need. A key is <b>only</b> required for automatic
    labelling; leave it blank to use the manual / chatbot path.</p>
    <pre><span class="c"># copy the template, then edit .env</span>
cp .env.example .env</pre>
    <table class="cmdtbl">
      <tr><td><code>ANTHROPIC_API_KEY</code></td><td>Your AI key for automatic labelling. Web search / deep research need Anthropic.</td></tr>
      <tr><td>… or any one of</td><td><code>NVIDIA_API_KEY</code> (free, build.nvidia.com), <code>OPENAI_API_KEY</code>, <code>DEEPSEEK_API_KEY</code>, <code>MISTRAL_API_KEY</code>, <code>GROQ_API_KEY</code>, <code>GEMINI_API_KEY</code>, <code>OPENROUTER_API_KEY</code> — all label fetched text fine. Set NVIDIA alongside Anthropic and Claude searches while NVIDIA labels for free. The local app also lets you paste a key and pick the provider.</td></tr>
      <tr><td><code>EPISTEMIC_SEARCH_PROVIDER</code> <span style="color:var(--faint)">/ <code>EPISTEMIC_LABEL_PROVIDER</code></span></td><td>Pin each phase to one provider by id (<code>anthropic</code>, <code>nvidia</code>, <code>openai</code>, …) instead of the automatic split. A pin whose key isn't set is ignored. The local console's "Models &amp; access" panel sets these live.</td></tr>
      <tr><td><code>EPISTEMIC_MODEL</code> <span style="color:var(--faint)">/ <code>EPISTEMIC_SEARCH_MODEL</code> / <code>EPISTEMIC_LABEL_MODEL</code></span></td><td>Pin the model. The <code>SEARCH</code>/<code>LABEL</code> variants set each phase independently; plain <code>EPISTEMIC_MODEL</code> applies to both when they share a provider.</td></tr>
      <tr><td><code>EPISTEMIC_LABEL_MODELS</code> <span style="color:var(--faint)">/ <code>EPISTEMIC_RATE_LIMIT_RPM</code></span></td><td>List 2+ label models (comma-separated) to run a multi-model ENSEMBLE and combine by majority vote — a less model-dependent label. The rate cap (default 40/min) paces the free provider so the fan-out stays under its limit.</td></tr>
      <tr><td><code>EPISTEMIC_PORTAL</code></td><td>This portal's URL for push/pull — e.g. <code>https://groundknowledge.org</code>.</td></tr>
      <tr><td><code>EPISTEMIC_CONTACT_EMAIL</code></td><td>Your email → OpenAlex/Crossref "polite pool" (faster, higher limits).</td></tr>
      <tr><td><code>EPISTEMIC_ADMIN_TOKEN</code></td><td>Only if you run a portal and want to push whole-KB replacements.</td></tr>
    </table>

    <h2 id="localui">The local app (browser console)</h2>
    <p>Prefer clicking to typing? Launch a local web console that drives the same
    find → fetch → label → merge flow in your browser — including a panel to paste your API key and
    to push/pull cases to this portal.</p>
    <pre>python cli.py ui            <span class="c"># opens http://localhost:8765</span>
python cli.py ui --port 9000 --no-open</pre>

    <h2 id="cli">CLI command reference</h2>
    <p>Every command is <code>python cli.py &lt;command&gt;</code>. Add <code>--build</code> to most
    mutating commands to regenerate the static viewer afterwards.</p>

    <h3>Create &amp; inspect</h3>
    <table class="cmdtbl">
      <tr><td><code>init &lt;id&gt; "question"</code></td><td>Start a new, empty knowledge base.</td></tr>
      <tr><td><code>show &lt;kb&gt;</code></td><td>Print a summary of the KB.</td></tr>
      <tr><td><code>assess &lt;kb&gt;</code></td><td>Print the metrics (distribution, independence, cruxes, blindspots).</td></tr>
      <tr><td><code>build &lt;kb…&gt;</code></td><td>Render the standalone HTML viewer for one or more cases.</td></tr>
    </table>

    <h3>Add sources</h3>
    <table class="cmdtbl">
      <tr><td><code>research &lt;kb&gt;</code></td><td><b>One-shot cold start.</b> Emits a single prompt for a browsing chatbot that discovers <i>and</i> labels sources. <code>--apply</code> to auto-merge with a key.</td></tr>
      <tr><td><code>discover &lt;kb&gt;</code></td><td>Find candidate sources (<code>--source api</code> = OpenAlex, no key; <code>web</code> / <code>both</code> use AI search).</td></tr>
      <tr><td><code>ingest &lt;kb&gt; &lt;url&gt;</code></td><td>Fetch one source and label it. <code>--dry-run</code> writes a prompt to paste into a chatbot; <code>--apply</code> labels with your key.</td></tr>
      <tr><td><code>ingest-batch &lt;kb&gt; …</code></td><td>Fetch + label many at once. <code>--bundle</code> (with <code>--dry-run</code>) packs them into ONE file to upload to a chatbot.</td></tr>
      <tr><td><code>harvest &lt;kb&gt;</code></td><td>Discover + ingest in one step.</td></tr>
      <tr><td><code>add &lt;kb&gt; &lt;delta&gt;</code></td><td>Merge a hand-written / chatbot-returned delta JSON into the KB.</td></tr>
    </table>

    <h3>Curate</h3>
    <table class="cmdtbl">
      <tr><td><code>dups &lt;kb&gt;</code></td><td>List likely-duplicate entities worth merging.</td></tr>
      <tr><td><code>merge &lt;kb&gt; &lt;type&gt; &lt;src&gt; &lt;dst&gt;</code></td><td>Fold one entity (position/dataset/factor/…) into another.</td></tr>
      <tr><td><code>rename &lt;kb&gt; &lt;type&gt; &lt;ref&gt; "label"</code></td><td>Rename an entity.</td></tr>
      <tr><td><code>tidy &lt;kb&gt;</code></td><td>Prettify id-style / slug labels for display.</td></tr>
    </table>

    <h3>Citations &amp; sync</h3>
    <table class="cmdtbl">
      <tr><td><code>import-citations &lt;kb&gt; &lt;file&gt;</code></td><td>Import a Zotero/Mendeley/EndNote export (.ris, .bib, .csl-json) and label each entry.</td></tr>
      <tr><td><code>export &lt;kb&gt; --format bibtex|ris|csl</code></td><td>Export the KB's sources as a citation file.</td></tr>
      <tr><td><code>questions</code></td><td>List the questions on the portal.</td></tr>
      <tr><td><code>pull &lt;id&gt;</code></td><td>Download a question's KB from the portal to your machine.</td></tr>
      <tr><td><code>push &lt;kb&gt;</code></td><td>Send your local sources up to the portal.</td></tr>
    </table>

    <h2 id="workflow">A typical workflow</h2>
    <p>Cold-start a new question locally, then publish it here:</p>
    <pre><span class="c"># 1. create it</span>
python cli.py init eggs "Do eggs increase cardiovascular disease risk?"

<span class="c"># 2. find + label sources automatically (needs an AI key in .env)</span>
python cli.py harvest cases/eggs.kb.json --k 12 --build

<span class="c"># 3. no key? do it the manual way — get one file, label it in your chatbot, merge it back</span>
python cli.py ingest-batch cases/eggs.kb.json --from finds.json --dry-run --bundle
python cli.py add cases/eggs.kb.json delta.json --build

<span class="c"># 4. look at it</span>
python cli.py assess cases/eggs.kb.json

<span class="c"># 5. publish to the portal</span>
python cli.py push cases/eggs.kb.json --as "Your name"</pre>

    <h2 id="sync">Push &amp; pull (sync with this portal)</h2>
    <p>Set <code>EPISTEMIC_PORTAL</code> in <code>.env</code> (or pass <code>--portal</code>).
    Whole-KB replacement via <code>push</code> also needs the portal admin token in
    <code>EPISTEMIC_ADMIN_TOKEN</code> or <code>--token</code>:</p>
    <pre>python cli.py questions                 <span class="c"># browse what's here</span>
python cli.py pull &lt;question-id&gt;        <span class="c"># grab it locally</span>
python cli.py push cases/your.kb.json --token "$EPISTEMIC_ADMIN_TOKEN"</pre>
    <div class="note">Source-by-source contributions are <b>keyless</b> — anyone can push new
    sources through the browser contribution flow. Replacing a whole knowledge base from the CLI
    is gated by the portal's admin token.</div>

    <p style="margin-top:30px"><a href="%REPO%">Full source &amp; README on GitHub →</a></p>
    </div>"""
    body = body.replace("%REPO%", repo)
    return _page("CLI & local app — Ground Knowledge", body)


def viewer_html(qid, get_question):
    """The read view: reuse viewer/template.html, populated live with this one question.

    The template is render-only and knows nothing about portal routes (see its header
    comment); it just renders a `portalLinks` field verbatim if present. A CLI-built static
    multi-case bundle (cli.py build) never sets this key, so Add source / Export / Manage
    simply don't render there — there is no server behind a static bundle to point them at.
    """
    q = get_question(qid)
    if not q:
        return None
    bundle = {
        "order": [q["id"]],
        "cases": {q["id"]: {"kb": q["kb"], "assessment": assess(q["kb"])}},
        "portalLinks": {
            "home": "/",
            "add": "/q/{}/add".format(qid),
            "manage": "/q/{}/manage".format(qid),
            "export": {fmt: "/api/questions/{}/export?format={}".format(qid, fmt)
                       for fmt in ("kb", "bibtex", "ris", "csl")},
        },
    }
    with open(os.path.join(ROOT, "viewer", "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    return tpl.replace("/*__DATA__*/null", json_for_script(bundle))


def manage_html(qid, get_question):
    """Admin-only moderation page: remove sources or delete the whole question. Gated by an
    admin token (set ADMIN_TOKEN on the server, paste it here once — stored on this device)."""
    q = get_question(qid)
    if not q:
        return None
    head = """
    <div class="back"><a href="/q/{id}">← back to the report</a></div>
    <div class="kicker">Admin · moderation</div>
    <h1>{question}</h1>
    <div id="gate"></div>
    <div id="panel" style="display:none">
      <div class="panel" id="revpanel" style="display:none"><h2>Needs review <span id="revn"></span></h2>
        <p class="desc">The labelling models disagreed on these sources' positions — they are parked
        here (counted in <b>no</b> metric) until someone decides. Read the abstract, then pick a
        position or drop the paper.</p>
        <div id="revs"></div></div>
      <div class="panel"><h2>Evidence bases <span id="dscount"></span></h2>
        <p class="desc">These are the case's <b>proposed</b> evidence bases — each worth <b>zero</b> to
        confirmed-root coverage until it is grounded. <b>Confirm</b> a base you have checked
        to admit it (it then enters the count), or <b>merge</b> a proposed base that is the same data
        under a different name <b>into an existing grounded base</b> (one you confirmed, or one a
        fetched source's exact quote already verifies). Merging two grounded bases (or un-confirming /
        renaming) is done in the CLI. Each action is logged with your admin identity.</p>
        <div class="bar" style="margin-bottom:10px"><button class="btn ghost sm" onclick="confirmAllProposed(this)">Confirm all proposed…</button></div>
        <div id="dsdup"></div>
        <div id="dss"></div>
        <details id="dskindwrap" style="margin-top:6px"><summary style="cursor:pointer;color:var(--faint);font-size:12px">Set evidence-base kinds</summary>
          <p class="desc" style="margin:10px 0 8px">Most bases are empirical <b>datasets</b>. Mark a proposal or record (a grant, a leaked document) as <b>document</b>, a chain of reasoning as <b>argument</b>, or a calculation / simulation as <b>model</b> — theoretical roots are exempt from the empirical non-human discount. This never changes a base's admission.</p>
          <div id="dskinds"></div></details></div>
      <div class="panel"><h2>Sources</h2>
        <p class="desc">Remove a source if it's inappropriate or spam — the metrics recompute.</p>
        <div id="srcs"></div></div>
      <div class="panel"><h2 style="color:#B4502E">Danger zone</h2>
        <p class="desc">Delete the entire question and every source in it. This cannot be undone.</p>
        <button class="btn" style="background:#B4502E;border-color:#B4502E" onclick="delQuestion()">Delete this question</button>
        <button class="btn ghost" style="margin-left:8px" onclick="signOut()">Sign out admin</button></div>
    </div>
    """.format(id=_esc(qid), question=_esc(q["question"]))
    script = """
    <script>
    const QID="{id}";
    const E=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const tok=()=>localStorage.getItem('gk_admin')||'';
    const H=()=>({'Content-Type':'application/json','X-Admin-Token':tok()});
    async function isAdmin(){ if(!tok())return false;
      try{const r=await fetch('/api/admin-check',{method:'POST',headers:H()});return (await r.json()).admin;}catch(e){return false;} }
    async function render(){
      if(!await isAdmin()){
        document.getElementById('panel').style.display='none';
        document.getElementById('gate').innerHTML=`<div class="panel"><h2>Enter admin token</h2>
          <p class="desc">Paste the admin token to manage this question. Stored on this device only.</p>
          <div class="bar"><input id="tk" type="password" placeholder="admin token" style="flex:1">
          <button class="btn" onclick="saveTok()">Unlock</button></div>
          <div id="gerr" class="toast warn"></div></div>`;
        return;
      }
      document.getElementById('gate').innerHTML='';
      document.getElementById('panel').style.display='';
      const r=await fetch('/api/questions/'+QID); const kb=(await r.json()).kb||{};
      try{const s=await fetch('/api/admin/dataset-status',{method:'POST',headers:H(),body:JSON.stringify({id:QID})});
        window.__dsStatus=((await s.json()).status)||{};}catch(e){window.__dsStatus={};}
      renderReview(kb);
      const srcs=kb.sources||[];
      document.getElementById('srcs').innerHTML = srcs.length? srcs.map(s=>`
        <div class="cand"><div style="flex:1"><b>${E(s.title)}</b> <span class="why">${E(s.year||'')}</span><br>
        <span class="why">${E((s.authors||[]).slice(0,3).join(', '))}${(s.authors||[]).length>3?' et al.':''}</span></div>
        <button class="btn ghost" onclick="delSource('${s.id}',this)">✕ remove</button></div>`).join('')
        : '<div class="empty">No sources yet.</div>';
      renderDatasets(kb);
    }
    // admission status mirrors the report: a base is GROUNDED (counts) if a curator confirmed it OR a
    // fetched source's exact quote verifies it; only truly proposed bases are worth zero and triageable.
    const dsStatusOf=d=>(window.__dsStatus&&window.__dsStatus[d.id])
        || ((d.confirmed===true||(d.confirmation&&d.confirmation.status==='confirmed'))?'curator':'proposed');
    const dsGrounded=d=>dsStatusOf(d)!=='proposed';
    function renderDatasets(kb){
      window.__kb=kb;
      renderKinds(kb);
      const ds=kb.datasets||[], wrap=document.getElementById('dss'), dup=document.getElementById('dsdup');
      const grounded=ds.filter(dsGrounded).length, proposed=ds.filter(d=>!dsGrounded(d));
      document.getElementById('dscount').innerHTML = ds.length
        ? `<span class="why" style="font-weight:400">— ${proposed.length} proposed · ${grounded} grounded</span>` : '';
      if(!ds.length){wrap.innerHTML='<div class="empty">No datasets yet.</div>';dup.innerHTML='';return;}
      if(!proposed.length){
        wrap.innerHTML=`<div class="empty">All ${ds.length} evidence bases are grounded — nothing to triage here. Un-confirm, rename, or merge grounded bases from the CLI.</div>`;
        dup.innerHTML=''; return;
      }
      const cliNote=grounded?`<div class="why" style="padding:2px 6px 12px">${grounded} grounded base${grounded===1?'':'s'} not shown (already counted) — manage those in the CLI.</div>`:'';
      wrap.innerHTML=cliNote+proposed.map(d=>{
        return `<div class="cand dsrow"><div style="flex:1;min-width:180px"><b>${E(d.label||d.id)}</b>
          <span class="why">${E(d.kind||'dataset')}</span> <span class="rev-badge queued">proposed · 0 weight</span></div>
          <span class="combo" data-ds="${E(d.id)}"><input class="combo-in" type="text" placeholder="Merge into…" autocomplete="off" spellcheck="false" title="fold this proposed base into an existing grounded base (same data, different name)"><div class="combo-menu" role="listbox"></div></span>
          <button class="btn sm" onclick="confirmDataset('${E(d.id)}',true,this)">Confirm</button></div>`;
      }).join('');
      renderDupes(kb);
      setupCombo();
    }
    async function renderDupes(kb){
      const box=document.getElementById('dsdup'); if(!box)return;
      let pairs=[];
      try{const r=await fetch('/api/admin/suggest-duplicates',{method:'POST',headers:H(),body:JSON.stringify({id:QID})});
        pairs=((await r.json()).dataset)||[];}catch(e){box.innerHTML='';return;}
      const ds=kb.datasets||[], isc=id=>{const d=ds.find(x=>x.id===id);return d&&dsGrounded(d);};
      pairs=pairs.filter(p=>isc(p.a.ref)!==isc(p.b.ref));   // only proposed↔grounded pairs (fold proposed into the grounded base)
      if(!pairs.length){box.innerHTML='';return;}
      box.innerHTML=`<div class="toast warn" style="margin-bottom:10px"><b>Possible duplicates.</b>
        These labels look like the same evidence base — merge so one cohort isn't counted as two roots.</div>`
        + pairs.map(p=>{
          const keep=(isc(p.b.ref)&&!isc(p.a.ref))?p.b:p.a, fold=(keep===p.a)?p.b:p.a;
          return `<div class="cand"><div style="flex:1"><b>${E(fold.label)}</b>
            <span class="why">→</span> <b>${E(keep.label)}</b>
            <span class="why">· ${E(p.reason)} · ${p.sim}</span></div>
            <button class="btn ghost" onclick="mergeDataset('${E(fold.ref)}','${E(keep.ref)}',null)">Merge</button></div>`;
        }).join('');
    }
    function renderKinds(kb){
      const box=document.getElementById('dskinds'), wrap=document.getElementById('dskindwrap');
      if(!box)return;
      const ds=kb.datasets||[];
      if(!ds.length){ if(wrap)wrap.style.display='none'; box.innerHTML=''; return; }
      if(wrap)wrap.style.display='';
      const KINDS=['dataset','document','argument','model'];
      box.innerHTML=ds.map(d=>{
        const cur=d.kind||'dataset';
        const opts=KINDS.map(k=>`<option value="${k}"${k===cur?' selected':''}>${k}</option>`).join('');
        return `<div class="cand"><div style="flex:1;min-width:160px"><b>${E(d.label||d.id)}</b>${cur!=='dataset'?` <span class="rev-badge merged">${cur}</span>`:''}</div>
          <select class="kindsel" onchange="setKind('${E(d.id)}',this.value,this)">${opts}</select></div>`;
      }).join('');
    }
    async function setKind(dsId,kind,el){
      if(el)el.disabled=true;
      const r=await fetch('/api/admin/set-dataset-kind',{method:'POST',headers:H(),body:JSON.stringify({id:QID,dataset:dsId,kind})});
      const j=await r.json();
      if(j.error){alert(j.error); if(el)el.disabled=false; return;}
      render();
    }
    async function mergeDataset(srcId,dstId,el){
      const ds=(window.__kb&&window.__kb.datasets)||[], nm=id=>{const d=ds.find(x=>x.id===id);return d?(d.label||d.id):id;};
      if(!confirm('Merge “'+nm(srcId)+'” into “'+nm(dstId)+'”?\\n\\nSources resting on “'+nm(srcId)+'” are repointed to “'+nm(dstId)+'”, the old name is kept as an alias, and “'+nm(srcId)+'” is removed.')){ if(el)el.value=''; return; }
      const r=await fetch('/api/admin/merge-dataset',{method:'POST',headers:H(),body:JSON.stringify({id:QID,src:srcId,dst:dstId})});
      const j=await r.json();
      if(j.error){alert(j.error); if(el)el.value=''; return;}
      render();
    }
    // Searchable "Merge into…" combobox — vanilla, styled to match the portal. Delegated listeners
    // are attached once; each row's .combo carries its dataset id in data-ds.
    function comboMenuHtml(srcId,q){
      // portal only merges a PROPOSED base INTO an existing GROUNDED one; grounded↔grounded is CLI.
      const ds=(window.__kb&&window.__kb.datasets)||[], ql=(q||'').trim().toLowerCase();
      const grounded=ds.filter(o=>o.id!==srcId && dsGrounded(o));
      if(!grounded.length)return '<div class="combo-empty">No grounded base yet — confirm one first, then merge into it.</div>';
      const hits=grounded.filter(o=>!ql||String(o.label||o.id).toLowerCase().includes(ql));
      if(!hits.length)return '<div class="combo-empty">No matching grounded base</div>';
      return hits.slice(0,40).map(o=>{
        const via=dsStatusOf(o)==='verified'?'via source quote':'confirmed';
        return `<div class="combo-opt" role="option" data-id="${E(o.id)}">${E(o.label||o.id)} <span class="why">${via}</span></div>`;
      }).join('');
    }
    function fillCombo(combo){ if(!combo)return;
      const inp=combo.querySelector('.combo-in'), menu=combo.querySelector('.combo-menu');
      menu.innerHTML=comboMenuHtml(combo.dataset.ds, inp.value); menu.classList.add('open'); }
    function openCombo(combo){ if(!combo)return; closeAllCombos(combo); fillCombo(combo); }
    function closeAllCombos(except){ const keep=except&&except.querySelector('.combo-menu');
      document.querySelectorAll('.combo-menu.open').forEach(m=>{ if(m!==keep){m.classList.remove('open');
        m.querySelectorAll('.combo-opt.active').forEach(o=>o.classList.remove('active'));} }); }
    function comboKey(e){ const combo=e.target.closest('.combo'); if(!combo)return;
      const menu=combo.querySelector('.combo-menu'), opts=[...menu.querySelectorAll('.combo-opt')];
      let i=opts.findIndex(o=>o.classList.contains('active'));
      if(e.key==='ArrowDown'){e.preventDefault(); if(!menu.classList.contains('open'))return openCombo(combo); i=Math.min(opts.length-1,i+1);}
      else if(e.key==='ArrowUp'){e.preventDefault(); i=Math.max(0,i-1);}
      else if(e.key==='Enter'){ if(i>=0&&opts[i]){e.preventDefault(); chooseCombo(combo,opts[i].dataset.id);} return; }
      else if(e.key==='Escape'){ menu.classList.remove('open'); return; }
      else return;
      opts.forEach(o=>o.classList.remove('active')); if(opts[i]){opts[i].classList.add('active'); opts[i].scrollIntoView({block:'nearest'});}
    }
    function chooseCombo(combo,dstId){ if(!combo||!dstId)return; closeAllCombos(); mergeDataset(combo.dataset.ds,dstId,combo.querySelector('.combo-in')); }
    function setupCombo(){ if(window.__comboReady)return; window.__comboReady=1;
      const isIn=t=>t&&t.classList&&t.classList.contains('combo-in');
      document.addEventListener('focusin',e=>{ if(isIn(e.target))openCombo(e.target.closest('.combo')); });
      document.addEventListener('input',e=>{ if(isIn(e.target))fillCombo(e.target.closest('.combo')); });
      document.addEventListener('keydown',e=>{ if(isIn(e.target))comboKey(e); });
      document.addEventListener('click',e=>{ const opt=e.target.closest('.combo-opt');
        if(opt){chooseCombo(opt.closest('.combo'),opt.dataset.id);return;}
        if(!e.target.closest('.combo'))closeAllCombos(); });
    }
    async function confirmDataset(dsId,confirmed,btn,extra){
      if(btn)btn.disabled=true;
      const r=await fetch('/api/admin/confirm-dataset',{method:'POST',headers:H(),
        body:JSON.stringify(Object.assign({id:QID,dataset:dsId,confirmed},extra||{}))});
      const j=await r.json();
      if(j.error){
        if(confirmed && /duplicate/i.test(j.error)){
          const note=prompt(j.error+"\\n\\nIf these are genuinely distinct evidence bases, add a short note to confirm anyway (or Cancel to merge first):");
          if(note&&note.trim())return confirmDataset(dsId,true,btn,{allowSimilar:true,note:note.trim()});
          if(btn)btn.disabled=false; return {skipped:true};
        }
        if(btn){alert(j.error);btn.disabled=false;} return {error:j.error};
      }
      if(btn)render(); return {ok:true};
    }
    async function confirmAllProposed(btn){
      const r=await fetch('/api/questions/'+QID); const kb=(await r.json()).kb||{};
      const todo=(kb.datasets||[]).filter(d=>!dsGrounded(d));
      if(!todo.length){alert('Every dataset is already confirmed.');return;}
      if(!confirm('Confirm '+todo.length+' proposed evidence base'+(todo.length===1?'':'s')+' as real, identified datasets? Only do this after checking them.'))return;
      btn.disabled=true; let done=0, dup=0, err=0;
      for(const d of todo){ const res=await confirmDataset(d.id,true,null);
        if(res.ok)done++; else if(res.skipped||/duplicate/i.test(res.error||''))dup++; else err++; }
      btn.disabled=false;
      alert('Confirmed '+done+'. '+(dup?dup+' skipped as possible duplicates (confirm those individually). ':'')+(err?err+' failed.':''));
      render();
    }
    const posName=k=>{const s=String(k||'').replace(/^NEW:\\s*/i,'').replace(/^pos[_ ]/,'').replace(/_/g,' ');return s.charAt(0).toUpperCase()+s.slice(1);};
    function reviewItems(kb){
      const pend=(kb.pendingReview||[]).map(e=>({kind:'pending',id:e.id,title:e.title,url:e.url,year:e.year,
        abstract:e.abstract,proposals:e.proposals||[]}));
      const flagged=(kb.sources||[]).filter(s=>(s.modelAgreement||{}).flagged).map(s=>{
        const ma=s.modelAgreement||{};
        const props=ma.proposals||Object.entries(ma.positionVote||{}).map(([k,v])=>({position:k,votes:v,quote:''}));
        return {kind:'flagged',id:s.id,title:s.title,url:s.url,year:s.year,abstract:'',
          current:s.position,proposals:props};
      });
      return pend.concat(flagged);
    }
    function renderReview(kb){
      const items=reviewItems(kb), panel=document.getElementById('revpanel');
      if(!items.length){panel.style.display='none';return;}
      panel.style.display='';
      document.getElementById('revn').textContent='('+items.length+')';
      const posOpts=(kb.positions||[]).map(p=>`<option value="${E(p.id)}">${E(p.label)}</option>`).join('');
      document.getElementById('revs').innerHTML=items.map(e=>{
        const merged=e.kind==='flagged';
        const badge=merged
          ? '<span class="rev-badge merged">imported with a guess</span>'
          : '<span class="rev-badge queued">not imported yet</span>';
        const opts=(e.proposals||[]).map(p=>`
          <div class="rev-opt">
            <div class="oi"><span class="on">${E(posName(p.position))}</span> <span class="ov">· ${p.votes} vote${p.votes===1?'':'s'}</span>
              ${p.quote?`<div class="oq">“${E(String(p.quote).slice(0,180))}”</div>`:''}</div>
            <button class="btn sm" onclick="resolveRev('${E(e.id)}','${e.kind}','position','${E(String(p.position).replace(/'/g,''))}',this)">Use this</button>
          </div>`).join('');
        return `<div class="rev">
          <div class="rev-h">${E(e.title)} <span class="yr">${E(e.year||'')}</span> ${badge}
            ${e.url?` &nbsp;<a href="${E(e.url)}" target="_blank" rel="noopener">source ↗</a>`:''}</div>
          ${merged?`<div class="rev-cur">Currently counted as <b>${E(posName(e.current))}</b> — pick a camp, keep it, or drop it.</div>`:''}
          ${e.abstract?`<details class="rev-abs"><summary>Abstract / what the models read</summary>
            <div class="why" style="white-space:pre-wrap;margin-top:6px">${E(e.abstract)}</div></details>`:''}
          <div class="rev-opts">${opts}</div>
          <div class="rev-act">
            <select id="sel_${E(e.id)}">${posOpts}</select>
            <button class="btn ghost sm" onclick="resolveRev('${E(e.id)}','${e.kind}','existing','',this)">Use selected</button>
            ${merged?`<button class="btn ghost sm" onclick="resolveRev('${E(e.id)}','${e.kind}','accept','',this)">Keep the guess</button>`:''}
            <button class="btn ghost sm" style="color:#B4502E;border-color:#e0c2b8" onclick="resolveRev('${E(e.id)}','${e.kind}','drop','',this)">Drop ${merged?'source':'paper'}</button>
          </div>
        </div>`;
      }).join('');
    }
    async function resolveRev(itemId,kind,act,pos,btn){
      let action=act, position=pos;
      if(act==='drop'){ if(!confirm('Drop this source? It will not be in the knowledge base.'))return; position=''; }
      if(act==='existing'){ action='position'; position=document.getElementById('sel_'+itemId).value; }
      btn.disabled=true;
      const r=await fetch('/api/admin/review-resolve',{method:'POST',headers:H(),
        body:JSON.stringify({id:QID,itemId,kind,action,position})});
      const j=await r.json();
      if(j.error){alert(j.error);btn.disabled=false;return;}
      render();
    }
    async function saveTok(){
      const t=document.getElementById('tk').value.trim(); if(!t)return;
      localStorage.setItem('gk_admin',t);
      if(!await isAdmin()){localStorage.removeItem('gk_admin');document.getElementById('gerr').textContent='That token is not valid.';return;}
      render();
    }
    async function delSource(sid,btn){
      if(!confirm('Remove this source? The metrics will recompute.'))return; btn.disabled=true;
      const r=await fetch('/api/admin/delete-source',{method:'POST',headers:H(),body:JSON.stringify({id:QID,sourceId:sid})});
      const j=await r.json(); if(j.error){alert(j.error);btn.disabled=false;return;} render();
    }
    async function delQuestion(){
      if(!confirm('Delete the ENTIRE question and all its sources? This cannot be undone.'))return;
      const r=await fetch('/api/admin/delete-question',{method:'POST',headers:H(),body:JSON.stringify({id:QID})});
      const j=await r.json(); if(j.ok)location.href='/'; else alert(j.error||'failed');
    }
    function signOut(){localStorage.removeItem('gk_admin');render();}
    render();
    </script>""".replace("{id}", _esc(qid))
    return _page("Manage · " + q["question"], head + script)


def contribute_html(qid, get_question):
    q = get_question(qid)
    if not q:
        return None
    head = """
    <div class="back"><a href="/q/{id}">← back to the report</a></div>
    <div class="kicker">Add sources · no API key needed</div>
    <h1>{question}</h1>
    <p class="sub">Find papers, fetch the best available text, then label them with <b>your own</b> chatbot
    — copy the prompt below into Claude or ChatGPT and paste its JSON back. Nothing you paste needs
    a key on our side; the merge is deterministic.</p>
    """.format(id=_esc(qid), question=_esc(q["question"]))
    body = head + """
    <div class="note">⚡ <b>Best results come from AI retrieval.</b> The scholarly search here is a
      free, keyless fallback. To let an AI find, read, and label sources for you — the recommended
      way — use the <a href="/docs">CLI or local app</a> with your own API key (Anthropic, OpenAI,
      DeepSeek, and more).</p>
    <div class="panel">
      <div class="step">Step 1 · Find or paste a URL</div><h2>Find candidate papers</h2>
      <p class="desc">Free scholarly search (OpenAlex) across the positions — no key. (For AI-powered
      discovery, use the <a href="/docs">CLI or local app</a>.)</p>
      <div class="bar"><input id="k" type="number" value="10" style="flex:0 0 90px">
        <button class="btn" onclick="find()">Find sources</button></div>
      <div id="finds"></div>
      <p class="desc" style="margin:16px 0 6px">— or add <b>one source by URL</b>, no search —</p>
      <div class="bar"><input id="oneUrl" placeholder="https://doi.org/… , a PubMed/arXiv link, or any article URL" style="flex:1">
        <button class="btn ghost" onclick="fetchUrl()">Fetch this URL ↓</button></div>
      <p class="desc" style="margin:16px 0 6px">— or import from <b>Zotero / a reference manager</b> (.ris, .bib, .json) —</p>
      <input type="file" accept=".ris,.bib,.bibtex,.json" onchange="importCit(this)"
        style="font-size:13px;color:var(--muted)">
    </div>
    <div class="panel">
      <div class="step">Step 2 · Fetch &amp; get one file</div><h2>Fetch text &amp; get one labelling file</h2>
      <p class="desc">We download the richest text available for each selected paper — open full
      text when available, otherwise abstract and metadata — and bundle it into a <b>single file</b>.
      Upload that one file to Claude or ChatGPT and ask it to follow the instructions inside — it
      returns one JSON array for all of them. No more pasting prompts one by one.</p>
      <button class="btn" id="fetchBtn" disabled onclick="fetchSel()">Fetch &amp; build file</button>
      <div id="prompts"></div>
    </div>
    <div class="panel">
      <div class="step">Step 3 · Paste &amp; import</div><h2>Paste your chatbot's JSON</h2>
      <p class="desc">Paste the JSON array your chatbot returned, then import — it's merged into the report.</p>
      <textarea id="delta" placeholder='[ { "source": { "title": "...", "position": "NEW:...", ... }, "factorWeights": [...] } ]'></textarea>
      <div style="margin-top:10px"><button class="btn" onclick="importDelta()">Import</button></div>
      <div id="imp" class="toast"></div>
    </div>
    <script>
    const QID="{id}";
    const E=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    let CANDS=[];
    function renderFinds(note){
      const nFull = CANDS.filter(c=>c.relevance!=='partial').length;
      const head = note || `${CANDS.length} found · ${nFull} strong match${nFull===1?'':'es'} pre-selected. Review and tick/untick before fetching.`;
      document.getElementById('finds').innerHTML = CANDS.length? (
        `<p class="why" style="margin:6px 0 2px">${E(head)}</p>`+
        CANDS.map((c,i)=>{
        const partial = c.relevance==='partial';
        return `<div class="cand"><input type="checkbox" class="ck" data-i="${i}" onchange="upd()" ${partial?'':'checked'}>
         <label><b>${E(c.title)}</b>${partial?' <span class="why" style="color:#8a6510">· weaker match</span>':''}
         <span class="why">${E(c.why||'')}</span><br>
         <span class="why">${E(c.url)}</span></label></div>`;}).join(''))
        : '<div class="empty">No candidates found.</div>';
      upd();
    }
    async function find(){
      const k=document.getElementById('k').value||10;
      const r=await fetch(`/api/questions/${QID}/discover`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({k:+k})});
      const j=await r.json(); CANDS=j.candidates||[]; renderFinds();
    }
    function importCit(input){
      const f=input.files&&input.files[0]; if(!f)return;
      const rd=new FileReader();
      rd.onload=async()=>{
        const r=await fetch(`/api/questions/${QID}/import-citations`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:rd.result,filename:f.name})});
        const j=await r.json();
        if(j.error){document.getElementById('finds').innerHTML='<div class="empty">'+E(j.error)+'</div>';return;}
        CANDS=(j.candidates||[]).map(c=>({...c,relevance:'full'}));   // imported = all pre-selected
        renderFinds(`Imported ${CANDS.length} citation(s) from ${E(f.name)}. Review, then fetch & label.`);
      };
      rd.readAsText(f);
    }
    function selected(){return [...document.querySelectorAll('.ck:checked')].map(c=>CANDS[+c.dataset.i].url);}
    function upd(){document.getElementById('fetchBtn').disabled = selected().length===0;}
    let BUNDLE='';
    function fetchSel(){doFetch(selected());}
    function fetchUrl(){const u=document.getElementById('oneUrl').value.trim(); if(!u){return;} doFetch([u]);}
    async function doFetch(urls){
      if(!urls.length)return;
      const b=document.getElementById('prompts'); b.innerHTML='Fetching best available text…';
      const r=await fetch(`/api/questions/${QID}/fetch`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({urls})});
      const j=await r.json();
      BUNDLE=j.bundle||'';
      const skip=j.skipped&&j.skipped.length?` · ${j.skipped.length} couldn't be fetched (skipped)`:'';
      if(!BUNDLE){b.innerHTML=`<p class="toast warn">Nothing fetched${skip}.</p>`;return;}
      b.innerHTML=`<p class="toast ok">Fetched ${j.fetched} source(s)${skip}.</p>
        <p class="desc">Upload this one file to your chatbot (or copy it), tell it to follow the
        instructions inside, then paste the JSON array it returns into Step 3.</p>
        <div style="margin:8px 0"><button class="btn" onclick="dlBundle(this)">⬇ Download labelling file</button>
        &nbsp;<button class="btn ghost" onclick="copyBundle(this)">Copy instead</button></div>`;
    }
    function flash(btn,msg){if(!btn)return;const t=btn.textContent;btn.textContent=msg;
      btn.disabled=true;setTimeout(()=>{btn.textContent=t;btn.disabled=false;},1500);}
    function dlBundle(btn){
      const blob=new Blob([BUNDLE],{type:'text/markdown'});
      const a=document.createElement('a');a.href=URL.createObjectURL(blob);
      a.download='label-sources.md';document.body.appendChild(a);a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(a.href),1000);
      flash(btn,'Downloaded ✓');
    }
    function copyBundle(btn){
      navigator.clipboard.writeText(BUNDLE).then(()=>flash(btn,'Copied ✓'))
        .catch(()=>flash(btn,'Copy failed — select & copy manually'));
    }
    async function importDelta(){
      let data; try{data=JSON.parse(document.getElementById('delta').value);}catch(e){return toast('Not valid JSON: '+e.message,'warn');}
      const r=await fetch(`/api/questions/${QID}/delta`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delta:data})});
      const j=await r.json();
      if(j.error)return toast(j.error,'warn');
      toast(`Submitted. ${j.queued||0} queued for curator review, ${j.duplicates||0} duplicate(s). `+
        `The public submission does not change the report until reviewed. Now v${j.version}. `,'ok');
    }
    function toast(m,c){const e=document.getElementById('imp');e.textContent=m;e.className='toast '+(c||'');
      if(c==='ok')e.innerHTML+=`<a href="/q/${QID}"> View the report →</a>`;}
    </script>""".replace("{id}", _esc(qid))
    return _page("Add sources · " + q["question"], body)

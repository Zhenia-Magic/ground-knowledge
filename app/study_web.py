"""Reader-study web surface: the blinded participant form, the deep-research report view, and the
admin results page. Rendering only — assignment/scoring live in eval/reader_study/study.py, storage
in app/store.py. Participants are anonymous (self-chosen token, never PII)."""
import os
import re

from app.web import _page, _esc, ROOT
from engine.render import json_for_script
from eval.reader_study import study

_REPORTS_DIR = os.path.join(ROOT, "eval", "baselines", "claude-code")


def _strip_preamble(md):
    """Drop any pre-report narration (research-session commentary) by starting at the first heading."""
    lines = (md or "").split("\n")
    for idx, ln in enumerate(lines):
        if re.match(r"^#{1,6}\s+", ln):
            return "\n".join(lines[idx:])
    return md or ""


def _match_url(s, start):
    """s[start]=='('; return (url, end_index) extracting a URL with BALANCED inner parens — so DOIs
    like https://www.cell.com/cell/fulltext/S0092-8674(24)00901-2 aren't truncated at the first ')'.
    None if it isn't a parenthesised http(s) URL."""
    if start >= len(s) or s[start] != "(":
        return None
    depth, i = 0, start
    while i < len(s):
        c = s[i]
        if c.isspace():
            return None
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                url = s[start + 1:i]
                return (url, i + 1) if re.match(r"https?://", url) else None
        i += 1
    return None


def _find_link(s, start):
    """A Markdown link at s[start]=='[': (text, url, end) with the TEXT matched by balanced brackets
    (a nested [x](u) doesn't end it early) and the URL by balanced parens; else None."""
    if start >= len(s) or s[start] != "[":
        return None
    depth, i = 0, start
    while i < len(s):
        if s[i] == "[":
            depth += 1
        elif s[i] == "]":
            depth -= 1
            if depth == 0:
                u = _match_url(s, i + 1)
                return (s[start + 1:i], u[0], u[1]) if u else None
        i += 1
    return None


def _strip_inner_links(text):
    """Reduce any links inside a link's TEXT to their visible label — repairs capture-corrupted
    nested links like [[DEFUSE](u)](u) and [*[Proximal Origin](u)* + [more](u)](u)."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == "[":
            link = _find_link(text, i)
            if link:
                out.append(_strip_inner_links(link[0]))
                i = link[2]
                continue
        out.append(text[i]); i += 1
    return "".join(out)


def _emph(escaped):
    """Bold/italic/code on already-escaped text."""
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*([^*\n]+?)\*", r"<em>\1</em>", s)
    return s


def _inline(t):
    """Inline Markdown -> HTML via a scanner that handles links (balanced [] and (), nested-link
    corruption, paren-containing URLs). Emphasis (bold/italic/code) is applied as a FINAL pass over
    the assembled HTML, so it renders whether it sits inside a link or spans one. Injection-safe:
    text and URLs are escaped before any tags are added."""
    t = re.sub(r"cite(?:turn\w+)+", "", t)                    # strip stray deep-research cite tokens
    out, buf, i, n = [], [], 0, len(t)

    def flush():
        if buf:
            out.append(_esc("".join(buf))); buf.clear()

    while i < n:
        if t[i] == "[":
            link = _find_link(t, i)
            if link:
                text, url, end = link
                flush()
                out.append('<a href="{}" target="_blank" rel="noopener">{}</a>'.format(
                    _esc(url), _esc(_strip_inner_links(text))))
                i = end
                continue
        buf.append(t[i]); i += 1
    flush()
    return _emph("".join(out))                                # emphasis last: spans/enters links cleanly


def _table_cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _render_table(rows):
    header = _table_cells(rows[0])
    body = rows[2:] if len(rows) > 1 and re.match(r"^\|?[\s:|-]+\|?$", rows[1]) else rows[1:]
    th = "".join("<th>" + _inline(c) + "</th>" for c in header)
    trs = "".join("<tr>" + "".join("<td>" + _inline(c) + "</td>" for c in _table_cells(r)) + "</tr>"
                  for r in body)
    return "<table><thead><tr>" + th + "</tr></thead><tbody>" + trs + "</tbody></table>"


def _render_md(md):
    """A compact but real Markdown -> HTML renderer: headings, horizontal rules, ordered/unordered
    lists, blockquotes, tables, and inline bold/italic/code/links. Enough for the deep-research
    reports shown to study participants."""
    lines = (md or "").split("\n")
    out, para, i, n = [], [], 0, len(lines)

    def flush():
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    while i < n:
        line = lines[i].rstrip()
        h = re.match(r"^(#{1,6})\s+(.*)", line)
        if h:
            flush(); lvl = min(len(h.group(1)), 4)
            out.append("<h{0}>{1}</h{0}>".format(lvl, _inline(h.group(2)))); i += 1; continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line):
            flush(); out.append("<hr>"); i += 1; continue
        if line.startswith("|") and "|" in line[1:]:                 # table block
            flush(); tbl = []
            while i < n and lines[i].strip().startswith("|"):
                tbl.append(lines[i].strip()); i += 1
            out.append(_render_table(tbl)); continue
        if re.match(r"^\s*[-*]\s+", line):                            # unordered list
            flush(); items = []
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append("<li>" + _inline(re.sub(r"^\s*[-*]\s+", "", lines[i].rstrip())) + "</li>"); i += 1
            out.append("<ul>" + "".join(items) + "</ul>"); continue
        if re.match(r"^\s*\d+\.\s+", line):                           # ordered list
            flush(); items = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append("<li>" + _inline(re.sub(r"^\s*\d+\.\s+", "", lines[i].rstrip())) + "</li>"); i += 1
            out.append("<ol>" + "".join(items) + "</ol>"); continue
        if line.startswith(">"):                                     # blockquote
            flush(); quote = []
            while i < n and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i].rstrip())); i += 1
            out.append("<blockquote>" + _inline(" ".join(quote)) + "</blockquote>"); continue
        if not line.strip():
            flush(); i += 1; continue
        para.append(line); i += 1
    flush()
    return "\n".join(out)


def study_report_html(case):
    gold = study.load_gold()
    if case not in gold["cases"]:
        return None
    path = os.path.join(_REPORTS_DIR, case + ".md")
    if not os.path.isfile(path):
        return _page("Report unavailable", "<p>Report not found.</p>")
    with open(path, encoding="utf-8") as f:
        md = f.read()
    body = ("<div class='kicker'>Research report</div>"
            "<h1>{}</h1><div class='report'>{}</div>").format(
                _esc(gold["cases"][case]["title"]), _render_md(_strip_preamble(md)))
    return _page("Report · " + gold["cases"][case]["title"], body + _REPORT_CSS)


_REPORT_CSS = """<style>
  .report{max-width:760px;line-height:1.65;color:#23262c;}
  .report h1,.report h2,.report h3,.report h4{margin:1.3em 0 .4em;line-height:1.3;}
  .report h1{font-size:24px;} .report h2{font-size:19px;} .report h3{font-size:16px;} .report h4{font-size:14px;}
  .report p{margin:.7em 0;} .report a{color:#2f6296;}
  .report ul,.report ol{margin:.5em 0 .8em 1.4em;} .report li{margin:.3em 0;}
  .report hr{border:0;border-top:1px solid #E4E7EA;margin:1.5em 0;}
  .report blockquote{border-left:3px solid #CDD2D7;margin:.9em 0;padding:.2em 0 .2em 14px;color:#4a4f57;}
  .report code{background:#eef0f2;padding:1px 5px;border-radius:4px;font-size:.9em;
    font-family:ui-monospace,Menlo,Consolas,monospace;}
  .report table{border-collapse:collapse;margin:1em 0;font-size:14px;display:block;overflow-x:auto;}
  .report th,.report td{border:1px solid #E4E7EA;padding:6px 11px;text-align:left;vertical-align:top;}
  .report th{background:#F5F6F7;}
</style>"""


def _question_block(case, spec, gold):
    """The objective + free-text items for one case (radio groups, a slider, textareas)."""
    q = ['<div class="q"><label class="qlabel">{}</label>{}</div>'.format(
        _esc(gold["flood_prompt"]),
        "".join('<label class="opt"><input type="radio" name="{c}_flood" value="{v}"> {v}</label>'
                .format(c=case, v=_esc(o)) for o in gold["flood_options"]))]
    for item in spec["questions"]:
        opts = "".join(
            '<label class="opt"><input type="radio" name="{c}_{id}" value="{v}"> {v}</label>'
            .format(c=case, id=item["id"], v=_esc(o)) for o in item["options"])
        q.append('<div class="q"><label class="qlabel">{}</label>{}</div>'.format(
            _esc(item["prompt"]), opts))
    q.append('<div class="q"><label class="qlabel">How confident are you in the strongest side\'s '
             'conclusion? <span class="conf" id="{c}_confv">50</span>/100</label>'
             '<input type="range" min="0" max="100" value="50" name="{c}_confidence" '
             'oninput="document.getElementById(\'{c}_confv\').textContent=this.value"></div>'.format(c=case))
    for ft in spec.get("freeText", []):
        q.append('<div class="q"><label class="qlabel">{}</label>'
                 '<textarea name="{c}_{id}" rows="3"></textarea></div>'.format(
                     _esc(ft["prompt"]), c=case, id=ft["id"]))
    return "".join(q)


def study_form_html(participant_index, token):
    gold = study.load_gold()
    plan = study.assign(participant_index)
    sections = []
    for row in plan:
        case = row["case"]
        spec = gold["cases"][case]
        # blinded: the participant sees the materials, never the condition label ("DR"/"DR+GK").
        materials = ['<a class="btn" href="/study/report/{}" target="_blank" rel="noopener">'
                     '📄 Open the research report</a>'.format(case)]
        if row["condition"] == "DR+GK":
            materials.append('<a class="btn" href="/q/{}" target="_blank" rel="noopener">'
                             '🗺️ Open the evidence map</a>'.format(spec["gkQuestionId"]))
        sections.append(
            '<section class="case" data-case="{c}" data-condition="{cond}">'
            '<div class="cnum">Case {n} of {tot}</div><h2>{title}</h2>'
            '<div class="materials">Read your materials, then answer below.<div class="mbtns">{mats}</div></div>'
            '{qs}</section>'.format(
                c=case, cond=row["condition"], n=row["sequence"], tot=len(plan),
                title=_esc(spec["title"]), mats="".join(materials),
                qs=_question_block(case, spec, gold)))
    plan_json = json_for_script(plan)
    body = """
    <div class="kicker">Ground Knowledge — reader exercise</div>
    <h1>How well can you read the evidence?</h1>
    <div class="consent">This is an <b>anonymous</b> research exercise comparing two ways of presenting
      evidence on a contested question — it takes about <b>10 minutes</b>. <b>Do not enter your name or
      anything identifying</b> — your token below is just a random nickname. Open the materials, then
      answer. There are no trick questions; answer as you see it. By submitting you consent to anonymous
      use of your responses.</div>
    <div class="q"><label class="qlabel">Your token (random — not your name)</label>
      <input id="token" value="{token}" maxlength="64" style="max-width:240px"></div>
    <div class="q"><label class="qlabel">How familiar are you with this topic? (1 = not at all, 5 = expert)</label>
      <input type="range" min="1" max="5" value="3" id="familiarity"
        oninput="document.getElementById('famv').textContent=this.value">
      <span class="conf" id="famv">3</span></div>
    {sections}
    <button class="btn primary" id="submit">Submit my answers</button>
    <div id="done" style="display:none"></div>
    <script id="plan" type="application/json">{plan}</script>
    <script>
    const START=Date.now(), PLAN=JSON.parse(document.getElementById('plan').textContent);
    document.getElementById('submit').onclick=async()=>{{
      const val=n=>{{const el=document.querySelector('[name="'+n+'"]:checked')||document.querySelector('[name="'+n+'"]');return el?el.value:"";}};
      const cases=PLAN.map(r=>{{
        const c=r.case, sec=document.querySelector('section[data-case="'+c+'"]');
        const answers={{flood:val(c+'_flood')}}; const free={{}};
        sec.querySelectorAll('input[type=radio]').forEach(i=>{{const k=i.name.slice(c.length+1); if(i.checked) answers[k]=i.value;}});
        sec.querySelectorAll('textarea').forEach(t=>{{free[t.name.slice(c.length+1)]=t.value;}});
        return {{case:c, condition:r.condition, confidence:Number(val(c+'_confidence'))||null, answers, free}};
      }});
      const payload={{participant:document.getElementById('token').value.trim(),
        familiarity:Number(document.getElementById('familiarity').value),
        totalSeconds:Math.round((Date.now()-START)/1000), cases}};
      const btn=document.getElementById('submit'); btn.disabled=true; btn.textContent='Submitting…';
      try{{
        const res=await fetch('/api/study',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});
        const data=await res.json();
        if(!res.ok){{throw new Error(data.error||'submit failed');}}
        document.getElementById('done').style.display='block';
        document.getElementById('done').innerHTML='<div class="thanks"><b>Thank you!</b> Your responses were recorded. '
          +'You got <b>'+data.correct+' of '+data.items+'</b> objective items right across your cases.</div>';
        btn.style.display='none';
      }}catch(e){{btn.disabled=false; btn.textContent='Submit my answers'; alert('Could not submit: '+e.message);}}
    }};
    </script>
    """.format(token=_esc(token), sections="".join(sections), plan=plan_json)
    return _page("Reader exercise · Ground Knowledge", body + _FORM_CSS)


_FORM_CSS = """<style>
  .consent{background:#F5ECD6;border:1px solid #e4d9b8;border-radius:8px;padding:12px 15px;margin:12px 0;font-size:14px;}
  .case{border:1px solid #E4E7EA;border-radius:10px;padding:16px 18px;margin:18px 0;}
  .cnum{font-family:monospace;font-size:11px;color:#8A9098;text-transform:uppercase;letter-spacing:.05em;}
  .materials{background:#F5F6F7;border-radius:8px;padding:10px 12px;margin:8px 0 14px;font-size:14px;}
  .mbtns{margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;}
  .q{margin:14px 0;} .qlabel{display:block;font-weight:600;font-size:14px;margin-bottom:6px;}
  .opt{display:block;font-weight:400;margin:3px 0;cursor:pointer;} .opt input{margin-right:7px;}
  textarea{width:100%;border:1px solid #CDD2D7;border-radius:6px;padding:8px;font:inherit;}
  input[type=range]{vertical-align:middle;} .conf{font-family:monospace;color:#2f6296;font-weight:600;}
  .btn{display:inline-block;background:#fff;border:1px solid #CDD2D7;border-radius:7px;padding:8px 14px;
    text-decoration:none;color:#15171B;font-size:14px;cursor:pointer;}
  .btn.primary{background:#2f6296;color:#fff;border-color:#2f6296;font-size:15px;padding:11px 20px;margin-top:10px;}
  .thanks{background:#E7EEF6;border:1px solid #b9cfe6;border-radius:8px;padding:14px 16px;margin-top:14px;}
</style>"""


def study_results_html(responses):
    """Admin: DR vs DR+GK on the auto-scored objective items, over every stored response."""
    obs = [o for r in responses for o in (r.get("scored") or [])]
    agg = study.aggregate(obs)
    n_participants = len({r.get("participant") for r in responses if r.get("participant")}) or len(responses)

    def _cond_row(name):
        b = agg.get(name)
        if not b:
            return "<tr><td>{}</td><td>0</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>".format(name)
        ia = b["itemAccuracy"]
        pct = lambda k: ("%.0f%%" % (100 * ia[k])) if k in ia else "—"
        return "<tr><td><b>{}</b></td><td>{}</td><td>{:.2f}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            name, b["n"], b["meanObjective"] or 0, pct("flood"), pct("bases"), pct("crux"))

    uplift = agg.get("upliftDRplusGK")
    uplift_txt = ("<p class='uplift'>DR+GK − DR objective-score difference: <b>{:+.2f}</b> "
                  "(positive = the evidence map helped). <b>Exploratory</b> — a between-observations "
                  "read; see PROTOCOL.md for the paired analysis.</p>".format(uplift)) if uplift is not None else ""
    body = ("<div class='kicker'>Reader study · results</div><h1>DR vs DR+GK</h1>"
            "<p>{np} participant(s), {no} case-observation(s) auto-scored.</p>"
            "<table class='rtbl'><thead><tr><th>Condition</th><th>n</th><th>mean objective (0–1)</th>"
            "<th>flood-trap</th><th>independent-bases</th><th>crux</th></tr></thead><tbody>{dr}{drgk}</tbody></table>"
            "{uplift}").format(np=n_participants, no=len(obs),
                               dr=_cond_row("DR"), drgk=_cond_row("DR+GK"), uplift=uplift_txt)
    return _page("Reader study results", body + _RESULTS_CSS)


_RESULTS_CSS = """<style>
  .rtbl{border-collapse:collapse;margin:14px 0;} .rtbl th,.rtbl td{border:1px solid #E4E7EA;padding:7px 12px;text-align:left;}
  .rtbl th{background:#F5F6F7;font-size:13px;} .uplift{background:#E7EEF6;border-radius:8px;padding:12px 15px;max-width:640px;}
</style>"""

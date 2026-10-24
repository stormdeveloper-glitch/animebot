css_add = '''
/* ══ CHANNEL PAGE ══ */
.channel-page{display:flex;flex-direction:column;gap:20px;max-width:600px;margin:0 auto}
.ch-banner{background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:16px;padding:24px;color:#fff;display:flex;justify-content:space-between;align-items:center;box-shadow:0 10px 30px var(--shadow),0 0 20px var(--glow-c);border:1px solid rgba(255,255,255,.1);}
.ch-tabs{display:flex;gap:8px;margin-bottom:4px;background:var(--border2);padding:4px;border-radius:30px;width:fit-content;}
.ch-tab{padding:8px 20px;border-radius:24px;border:none;background:transparent;color:var(--muted);cursor:pointer;font-family:'Orbitron',monospace;font-size:.68rem;font-weight:700;transition:all .2s;text-transform:uppercase;}
.ch-tab.active{background:var(--accent);color:#000;box-shadow:0 4px 12px var(--glow-c)}
.ch-stats{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.ch-st-card{background:var(--card-bg);border:1px solid var(--border);border-radius:14px;padding:20px;text-align:center;display:flex;flex-direction:column;gap:6px;transition:all .25s cubic-bezier(.4,0,.2,1);position:relative;overflow:hidden;}
.ch-st-card::before{content:'';position:absolute;top:0;left:0;width:3px;height:100%;background:var(--accent);opacity:0;transition:opacity .2s;}
.ch-st-card:hover{transform:translateY(-4px);border-color:var(--accent);box-shadow:0 12px 28px var(--shadow);}
.ch-st-card:hover::before{opacity:1}
.ch-st-val{font-family:'Orbitron',monospace;font-size:1.8rem;font-weight:900;color:var(--accent);text-shadow:0 0 10px var(--glow-c)}
.ch-st-lbl{font-size:.65rem;color:var(--muted);text-transform:uppercase;font-weight:700;letter-spacing:.08em}
'''
import re
content = open('e:/bot-main/index.html', 'r', encoding='utf-8').read()

if '.ch-banner' not in content:
    # Find the end of style
    idx = content.find('</style>')
    if idx != -1:
        new_content = content[:idx] + css_add + content[idx:]
        open('e:/bot-main/index.html', 'w', encoding='utf-8').write(new_content)
        print("CSS added.")
    else:
        print("</style> not found")
else:
    print("CSS already exists.")

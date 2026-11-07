#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ДАШБОРД УПАКОВКИ: ОПИСАНИЯ И ЗАГОЛОВКИ ВСЕХ РОЛИКОВ ДНЯ (07.11.2026).

    python3 upakovka_dash.py <ДД-ММ> [--port 8810]

Его заказ: «чтобы на одном дашборде были описания на три темы для двух
каналов, название и описание, с кнопкой копировать — чтобы я мог
скопировать описание и вставить на YouTube».

Собирает `УПАКОВКА.json` из папок тем ВСЕХ каналов за этот день и строит
одну страницу: карточка на ролик, кнопка копирования у описания, у
каждого заголовка и у каждой надписи. Порт занимает первый свободный.
"""
import argparse
import html
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import threading

# Агент на машине ОДИН — два задания одновременно он не тянет.
_codex_lock = threading.Lock()
import sys

NEWS = os.environ.get("VIDEORYAD_NEWS_DIR", "/mnt/d/YouTube/НОВОСТИ")
CHANNELS = ("5 МИНУТ", "ПЛАНЕТА", "ОЛЬКА НОВОСТИ", "ДИПЛОМАТИЯ СИЛЫ",
            "ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО")
MONTHS = ("ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ", "ИЮЛЬ",
          "АВГУСТ", "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ")


def collect(day):
    out = []
    for ch in CHANNELS:
        for mon in MONTHS:
            d = os.path.join(NEWS, ch, mon, day)
            if not os.path.isdir(d):
                continue
            for t in sorted(os.listdir(d)):
                j = os.path.join(d, t, "УПАКОВКА.json")
                if os.path.isfile(j):
                    try:
                        data = json.load(open(j, encoding="utf-8"))
                    except ValueError:
                        continue
                    data.setdefault("канал", ch)
                    data.setdefault("тема", t)
                    # сами файлы превью из папки темы
                    folder = os.path.join(d, t)
                    data["превью_папка"] = folder
                    data["превью_файлы"] = []
                    out.append(data)
    return out


# ЦВЕТ КАНАЛА — ЧТОБЫ КАРТОЧКИ НЕ СЛИВАЛИСЬ (07.11, его слово: «каждый
# канал подсвечивает своим цветом, чтобы они немножко отличались, чтобы не
# сливались у меня в одно»). Цвета взяты те же, что у гаммы канала в
# роликах, — тогда дашборд читается как продолжение самого канала.
CH_COLOR = {
    "ПЛАНЕТА":                    ("#4a90e2", "#101822"),
    "5 МИНУТ":                    ("#e0b33a", "#221a10"),
    "ОЛЬКА НОВОСТИ":              ("#a882e8", "#1a1424"),
    "ОЛЬКА":                      ("#a882e8", "#1a1424"),
    "ДИПЛОМАТИЯ СИЛЫ":            ("#48bb78", "#101e16"),
    "ПЕРЕВОД с ДИПЛОМАТИЧЕСКОГО": ("#06c7c7", "#0c1e1e"),
}


def ch_color(name):
    key = (name or "").strip().upper()
    for n, pair in CH_COLOR.items():
        if key.startswith(n.upper()) or n.upper().startswith(key):
            return pair
    return ("#9a9aa2", "#17171a")


CSS = """
:root{--bg:#0e0e10;--card:#17171a;--line:#26262b;--ink:#e8e8e8;
      --dim:#9a9aa2;--hot:#e0b33a;--ok:#4a9d5f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
header{padding:18px 24px;border-bottom:1px solid var(--line);
       position:sticky;top:0;background:var(--bg);z-index:9}
h1{margin:0;font-size:19px;letter-spacing:.3px}
.sub{color:var(--dim);font-size:13px;margin-top:4px}
.wrap{padding:20px 24px;display:grid;gap:18px;
      grid-template-columns:repeat(auto-fit,minmax(460px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
      padding:16px 18px}
.ch{display:inline-block;font-size:12px;letter-spacing:.6px;
    padding:3px 9px;border-radius:4px;background:#2a2a30;color:var(--hot)}
.tema{font-size:17px;font-weight:600;margin:9px 0 14px}
.ch{background:transparent!important}
.lab{font-size:12px;color:var(--dim);letter-spacing:.5px;margin:16px 0 7px;
     text-transform:uppercase}
.desc{white-space:pre-wrap;background:#121214;border:1px solid var(--line);
      border-radius:7px;padding:12px;max-height:230px;overflow:auto;
      font-size:14px}
ol{margin:0;padding-left:22px}
li{margin:5px 0;cursor:pointer}
li:hover{color:var(--hot)}
button{background:#232329;color:var(--ink);border:1px solid var(--line);
       border-radius:6px;padding:7px 13px;cursor:pointer;font-size:13px}
button:hover{border-color:var(--hot);color:var(--hot)}
button.done{border-color:var(--ok);color:var(--ok)}
.row{display:flex;gap:9px;align-items:center;margin-top:9px}
.hint{color:var(--dim);font-size:12px}
"""

JS = """
// КЛИК ПО ПРЕВЬЮ → ОКНО НАДПИСЕЙ → ГОТОВОЕ ПРЕВЬЮ (07.11, его заказ:
// «выбираю один, кликаю, появляется диалоговое окно — запись вверху и
// запись внизу, нажимаю ОК, и ты генерируешь только его»).
var CUR = null;
function openDlg(item, n, src, titles){
  CUR = {item:item, n:n};
  // ПОЛЯ ОЧИЩАЮТСЯ ПРИ КАЖДОМ ОТКРЫТИИ (07.11): раньше надписи прошлой
  // темы оставались в полях, и следующий вариант получал чужой текст.
  document.getElementById('dlg-top').value = '';
  document.getElementById('dlg-bottom').value = '';
  var ok = document.getElementById('dlg-ok');
  ok.textContent = 'ОК'; ok.disabled = false;
  document.getElementById('dlg-img').src = src;
  var sel = document.getElementById('dlg-pick');
  sel.innerHTML = '<option value="">— выбрать из готовых надписей —</option>';
  (titles||[]).forEach(function(t){
    var o=document.createElement('option'); o.value=t; o.textContent=t;
    sel.appendChild(o);
  });
  document.getElementById('dlg-res').innerHTML='';
  var dlg = document.getElementById('dlg');
  dlg.style.display='flex';
  // ОКНО НЕ УБЕГАЕТ: страница под ним замораживается, а само окно
  // прокручивается с начала. Без этого при длинной карточке браузер
  // уводил вид вниз, и окно «уезжало» за край.
  document.body.style.overflow = 'hidden';
  var box = dlg.firstElementChild;
  if(box){ box.scrollTop = 0; }
}
function pickInto(which){
  var v = document.getElementById('dlg-pick').value;
  if(v) document.getElementById(which).value = v;
}
function closeDlg(){
  document.getElementById('dlg').style.display='none';
  document.body.style.overflow = '';          // страница снова листается
}
function makeIt(){
  var top = document.getElementById('dlg-top').value.trim();
  var bot = document.getElementById('dlg-bottom').value.trim();
  if(!top && !bot){ alert('Введи хотя бы одну надпись'); return; }
  var btn = document.getElementById('dlg-ok');
  btn.textContent = 'делаю…'; btn.disabled = true;
  fetch('/make', {method:'POST', headers:{'Content-Type':'application/json'},
                  body: JSON.stringify({item:CUR.item, n:CUR.n, top:top, bottom:bot})})
   .then(function(r){ return r.json(); })
   .then(function(d){
      btn.textContent='ОК'; btn.disabled=false;
      if(d.ok){
        var warn = '';
        if(d.grammatika && d.grammatika.length){
          warn += '<div style="margin:8px 0;padding:9px 12px;border:1px solid #e06a6a;' +
                  'border-radius:7px;color:#e06a6a;font-size:14px">' +
                  '⚠ грамматика:<br>• ' + d.grammatika.join('<br>• ') + '</div>';
        }
        if(d.opechatki && d.opechatki.length){
          warn = '<div style="margin:8px 0;padding:9px 12px;border:1px solid #e0b33a;' +
                 'border-radius:7px;color:#e0b33a;font-size:14px">' +
                 '⚠ проверь слова: <b>' + d.opechatki.join(', ') + '</b>' +
                 '<div style="color:#9a9aa2;font-size:12px;margin-top:4px">' +
                 'их нет в твоих текстах — возможно, опечатка. Файлы всё равно сделаны.' +
                 '</div></div>';
        }
        document.getElementById('dlg-res').innerHTML = warn +
          '<div class="lab">готово — ' + d.file + '</div>' +
          '<img src="' + d.url + '?t=' + Date.now() + '" style="width:100%;border-radius:6px">' +
          '<div class="row"><button onclick="closeDlg()" ' +
          'style="font-size:15px;padding:9px 22px">закрыть</button>' +
          '<span class="hint">файлы уже в папке темы</span></div>';
        // ПЛИТКА В СЕТКЕ СТАНОВИТСЯ ГОТОВОЙ ВЕРСИЕЙ
        var tile = document.getElementById('p-' + CUR.item + '-' + CUR.n);
        if(tile){
          tile.src = d.url + '?t=' + Date.now();
          tile.style.border = '3px solid ' + (d.accent || '#e0b33a');
        }
      } else {
        document.getElementById('dlg-res').innerHTML =
          '<div style="color:#e06a6a">не вышло: ' + (d.error||'?') + '</div>';
      }
   })
   .catch(function(e){ btn.textContent='ОК'; btn.disabled=false; alert(e); });
}

// СКОПИРОВАЛ ОПИСАНИЕ → ОНО СВОРАЧИВАЕТСЯ (07.11, его заказ: «чтобы я
// понимал, что это я уже сделал, это будет мне сигналом»). Карточка
// остаётся, но описание прячется и помечается галочкой — видно с одного
// взгляда, что по этому ролику описание уже ушло на YouTube.
function copy(txt,el,descId){
  navigator.clipboard.writeText(txt).then(function(){
    el.textContent='скопировано';
    el.classList.add('done');
    if(descId){
      var d=document.getElementById(descId);
      if(d){
        d.style.display='none';
        var m=document.getElementById(descId+'-mark');
        if(m){ m.style.display='block'; }
        el.textContent='описание скопировано ✓';
      }
    } else {
      setTimeout(function(){el.textContent='копировать';el.classList.remove('done')},1200);
    }
  });
}
// СКРЫТЬ БЛОК ЗАГОЛОВКОВ ИЛИ НАДПИСЕЙ (07.11, та же мысль, что и с
// описанием: «чтобы тоже мне не мешало, чтобы я понимал, что с этим я
// уже закончил»). Блок сворачивается в узкую строку с галочкой, клик по
// ней разворачивает обратно.
function fold(id){
  var b=document.getElementById(id);
  var m=document.getElementById(id+'-mark');
  if(b){ b.style.display='none'; }
  if(m){ m.style.display='block'; }
}
function unfoldBlock(id){
  var b=document.getElementById(id);
  var m=document.getElementById(id+'-mark');
  if(b){ b.style.display='block'; }
  if(m){ m.style.display='none'; }
}
// ЕЩЁ ДЕСЯТЬ ВАРИАНТОВ (07.11). Агент думает около минуты — пишем об
// этом прямо, чтобы кнопка не выглядела залипшей.
function more(item, kind, blockId, btn){
  var hint = document.getElementById(blockId + '-hint');
  btn.disabled = true; btn.textContent = 'думаю…';
  hint.textContent = 'агент пишет новые десять, это около минуты';
  fetch('/more', {method:'POST', headers:{'Content-Type':'application/json'},
                  body: JSON.stringify({item:item, kind:kind})})
   .then(function(r){ return r.json(); })
   .then(function(d){
      btn.disabled = false; btn.textContent = 'ещё 10 вариантов';
      if(!d.ok){ hint.textContent = 'не вышло: ' + (d.error||'?'); return; }
      var ol = document.querySelector('#' + blockId + ' ol');
      d.items.forEach(function(t){
        var li = document.createElement('li');
        li.dataset.t = t; li.textContent = t;
        li.onclick = function(){ copyLi(li); };
        li.style.color = '#e0b33a';
        ol.appendChild(li);
      });
      hint.textContent = 'добавлено ' + d.items.length;
   })
   .catch(function(e){ btn.disabled=false; btn.textContent='ещё 10 вариантов';
                       hint.textContent = 'сбой: ' + e; });
}
function unfold(descId,btnId){
  var d=document.getElementById(descId);
  var m=document.getElementById(descId+'-mark');
  var b=document.getElementById(btnId);
  if(d){ d.style.display='block'; }
  if(m){ m.style.display='none'; }
  if(b){ b.textContent='копировать описание'; b.classList.remove('done'); }
}
function copyLi(li){
  navigator.clipboard.writeText(li.dataset.t).then(function(){
    var o=li.style.color; li.style.color='#4a9d5f';
    setTimeout(function(){li.style.color=o},900);
  });
}
"""


def page(items, day):
    P = ['<!doctype html><meta charset="utf-8">',
         '<title>Упаковка роликов — %s</title>' % html.escape(day),
         '<style>%s</style>' % CSS, '<script>%s</script>' % JS,
         '<header><h1>УПАКОВКА РОЛИКОВ · %s</h1>' % html.escape(day),
         '<div class="sub">описание, заголовки и надписи на превью · '
         'роликов: %d · нажми на строку, чтобы скопировать её</div>'
         % len(items)]
    _seen = []
    for it in items:
        c = it.get("канал", "")
        if c not in _seen:
            _seen.append(c)
    P.append('<div class="sub" style="margin-top:8px">')
    for c in _seen:
        a, _ = ch_color(c)
        P.append('<span style="color:%s;margin-right:14px">■ %s</span>'
                 % (a, html.escape(c)))
    P.append('</div></header><div class="wrap">')
    for it in items:
        desc = it.get("описание", "")
        _accent, _bg = ch_color(it.get("канал", ""))
        P.append('<div class="card" style="border-left:4px solid %s;'
                 'background:%s">' % (_accent, _bg))
        P.append('<span class="ch" style="color:%s;border:1px solid %s">%s</span>'
                 % (_accent, _accent, html.escape(it.get("канал", ""))))
        P.append('<div class="tema">%s</div>' % html.escape(it.get("тема", "")))
        # ПАТТЕРН — метка редакционной классификации (решение 20.10.2026).
        # Годится и как фильтр в георадаре, и как подсказка при выборе
        # заголовка: сюжеты одного паттерна упаковываются похоже.
        if it.get("паттерн"):
            P.append('<div style="font-size:12px;color:%s;margin:-8px 0 12px">'
                     'паттерн: %s</div>'
                     % (_accent, html.escape(it["паттерн"])))
        _did = "d%d" % items.index(it)
        _bid = _did + "-btn"
        P.append('<div class="lab">описание для YouTube</div>')
        P.append('<div class="desc" id="%s">%s</div>'
                 % (_did, html.escape(desc)))
        P.append('<div id="%s-mark" style="display:none;padding:10px 12px;'
                 'border:1px dashed %s;border-radius:7px;color:%s;'
                 'font-size:13px;cursor:pointer" onclick="unfold(\'%s\',\'%s\')">'
                 '✓ описание скопировано — нажми, чтобы раскрыть</div>'
                 % (_did, _accent, _accent, _did, _bid))
        P.append('<div class="row"><button id="%s" onclick=\'copy(%s,this,"%s")\'>'
                 'копировать описание</button>'
                 '<span class="hint">%d знаков</span></div>'
                 % (_bid, json.dumps(desc, ensure_ascii=False), _did, len(desc)))
        for key, lab in (("заголовки", "заголовки — 10 вариантов"),
                         ("надписи", "надписи на превью — 10 вариантов")):
            rows = it.get(key) or []
            if not rows:
                continue
            _bid = "%s%d" % ("t" if key == "заголовки" else "n",
                             items.index(it))
            P.append('<div id="%s-mark" style="display:none;padding:9px 12px;'
                     'margin-top:14px;border:1px dashed %s;border-radius:7px;'
                     'color:%s;font-size:13px;cursor:pointer" '
                     'onclick="unfoldBlock(\'%s\')">✓ %s — скрыто, '
                     'нажми чтобы раскрыть</div>' % (_bid, _accent, _accent,
                                                     _bid, lab))
            P.append('<div id="%s">' % _bid)
            P.append('<div class="lab">%s</div><ol>' % lab)
            for r in rows:
                P.append('<li data-t="%s" onclick="copyLi(this)">%s</li>'
                         % (html.escape(r, quote=True), html.escape(r)))
            P.append('</ol>')
            P.append('<div class="row">'
                     '<button onclick="fold(\'%s\')">скрыть — с этим '
                     'закончил</button>'
                     '<button onclick=\'more(%d,"%s","%s",this)\'>'
                     'ещё 10 вариантов</button>'
                     '<span class="hint" id="%s-hint"></span></div>'
                     % (_bid, items.index(it), key, _bid, _bid))
            P.append('</div>')
        # ПРЕВЬЮ — САМИ КАРТИНКИ, А НЕ ПРОМПТ (07.11). Файлы лежат в папке
        # темы как ПРЕВЬЮ-N.png; на страницу они отдаются по短 ссылке
        # /prevyu/<индекс>/<N>.png, которую раздаёт тот же сервер.
        shots = it.get("превью_файлы") or []
        if shots:
            P.append('<div class="lab">превью — %d вариантов</div>' % len(shots))
            P.append('<div style="display:grid;grid-template-columns:'
                     'repeat(auto-fit,minmax(150px,1fr));gap:8px">')
            _titles = json.dumps((it.get("надписи") or [])[:10],
                                 ensure_ascii=False)
            _done = it.get("превью_готовые") or {}
            for k, u in enumerate(shots, 1):
                # ЕСЛИ ВАРИАНТ УЖЕ СДЕЛАН С НАДПИСЬЮ — В СЕТКЕ СТОИТ ОН
                # (07.11, его слово: «чтобы я понимал: вот этот вариант я
                # не сделал, а вот этот у меня с надписью»). Готовый
                # подсвечен рамкой в цвете канала.
                _src = _done.get(k) or u
                _ready = k in _done
                P.append('<img id="p-%d-%d" src="%s" '
                         'onclick=\'openDlg(%d,%d,"%s",%s)\' '
                         'title="нажми, чтобы наложить надписи" '
                         'style="width:100%%;border-radius:6px;cursor:pointer;'
                         'border:%s">'
                         % (items.index(it), k, _src, items.index(it), k, u,
                            _titles,
                            ("3px solid %s" % _accent) if _ready
                            else "1px solid var(--line)"))
            P.append('</div>')
        P.append('</div>')
    P.append('</div>')
    P.append("""
<div id="dlg" style="display:none;position:fixed;inset:0;background:#000c;
     z-index:99;align-items:center;justify-content:center" onclick="if(event.target===this)closeDlg()">
 <div style="background:#17171a;border:1px solid #33333a;border-radius:10px;
      padding:18px;width:min(760px,92vw);max-height:92vh;overflow:auto">
  <div style="display:flex;align-items:center;justify-content:space-between">
    <div class="lab" style="margin-top:0">надписи на превью</div>
    <button onclick="closeDlg()" title="закрыть"
       style="font-size:18px;line-height:1;padding:4px 11px">×</button>
  </div>
  <img id="dlg-img" style="width:100%;border-radius:7px;margin-bottom:12px">
  <select id="dlg-pick" style="width:100%;padding:8px;background:#121214;
     color:#e8e8e8;border:1px solid #26262b;border-radius:6px;margin-bottom:6px"></select>
  <div class="row" style="margin:0 0 10px">
    <button onclick="pickInto('dlg-top')">вставить наверх</button>
    <button onclick="pickInto('dlg-bottom')">вставить вниз</button>
  </div>
  <input id="dlg-top" placeholder="надпись СВЕРХУ" style="width:100%;padding:10px;
     background:#121214;color:#e8e8e8;border:1px solid #26262b;border-radius:6px;
     margin-bottom:8px;font-size:15px">
  <input id="dlg-bottom" placeholder="надпись СНИЗУ" style="width:100%;padding:10px;
     background:#121214;color:#e8e8e8;border:1px solid #26262b;border-radius:6px;
     font-size:15px">
  <div class="row">
    <button id="dlg-ok" onclick="makeIt()" style="font-size:15px;padding:9px 20px">ОК</button>
    <button onclick="closeDlg()">отмена</button>
    <span class="hint">гамма подставится по каналу сама</span>
  </div>
  <div id="dlg-res" style="margin-top:12px"></div>
 </div>
</div>""")
    return "\n".join(P)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day", help="день в виде ДД-ММ, например 08-11")
    ap.add_argument("--port", type=int, default=8810)
    ap.add_argument("--out", help="сохранить html и не поднимать сервер")
    a = ap.parse_args()
    items = collect(a.day)
    if not items:
        sys.exit("за %s ни одной УПАКОВКА.json не нашлось — сначала "
                 "upakovka.py <папка дня> --all" % a.day)
    if a.out:
        htm = page(items, a.day)
        open(a.out, "w", encoding="utf-8").write(htm)
        print("страница: %s (роликов %d)" % (a.out, len(items)))
        return
    import importlib.util as _ilu0
    _sp0 = _ilu0.spec_from_file_location(
        "prevyu_text", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "prevyu_text.py"))
    _pt0 = _ilu0.module_from_spec(_sp0)
    _sp0.loader.exec_module(_pt0)
    _pt_name = _pt0.theme_name

    d = os.path.join("/tmp", "upakovka-%s" % a.day)
    os.makedirs(d, exist_ok=True)
    # КАРТИНКИ КЛАДЁМ РЯДОМ СО СТРАНИЦЕЙ: сервер раздаёт только свою папку,
    # а папки тем лежат на D: — ссылаться туда напрямую нельзя.
    for i, it in enumerate(items):
        folder = it.get("превью_папка") or ""
        urls = []
        vdir = os.path.join(folder, "превью-варианты")
        if not os.path.isdir(vdir):
            vdir = folder
        for n in range(1, 9):
            src = os.path.join(vdir, "ПРЕВЬЮ-%d.png" % n)
            if not os.path.isfile(src):
                continue
            sub = os.path.join(d, "prevyu", str(i))
            os.makedirs(sub, exist_ok=True)
            dst = os.path.join(sub, "%d.png" % n)
            try:
                if (not os.path.exists(dst)
                        or os.path.getmtime(src) > os.path.getmtime(dst)):
                    shutil.copy2(src, dst)
                urls.append("prevyu/%d/%d.png" % (i, n))
            except OSError:
                pass
        it["превью_файлы"] = urls
        # УЖЕ СДЕЛАННЫЕ С НАДПИСЬЮ — ищем в корне темы по имени ролика
        ready = {}
        try:
            name = _pt_name(folder)
        except Exception:
            name = ""
        for n in range(1, 9):
            f = os.path.join(folder, "%s ПРЕВЬЮ-%d.png" % (name, n))
            if name and os.path.isfile(f):
                sub = os.path.join(d, "prevyu", str(i))
                os.makedirs(sub, exist_ok=True)
                dst = os.path.join(sub, "%d-text.png" % n)
                try:
                    if (not os.path.exists(dst)
                            or os.path.getmtime(f) > os.path.getmtime(dst)):
                        shutil.copy2(f, dst)
                    ready[n] = "prevyu/%d/%d-text.png" % (i, n)
                except OSError:
                    pass
        it["превью_готовые"] = ready
    htm = page(items, a.day)
    open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(htm)
    os.chdir(d)
    # СОБСТВЕННЫЙ ОБРАБОТЧИК: статика плюс один POST `/make` — он и делает
    # финальное превью. Надписи рисует `prevyu_text.py` (код, не модель):
    # цвет получается ровно заданный, полосы одинаковые на всех вариантах,
    # и «своего» ничего не придумывается — его прямое требование.
    # ── ПРОВЕРКА ОПЕЧАТОК В НАДПИСЯХ (07.11, его слово: «я печатаю
    # вручную и по-быстрому, могу букву пропустить — надо, чтобы ты ловил
    # эту хрень»).
    # Словарь собран ИЗ ЕГО СОБСТВЕННЫХ текстов и субтитров (75 файлов,
    # 10 тысяч слов): он знает фамилии, жаргон и манеру — обычный
    # орфографический словарь ругался бы на «Сибига» и «ответка».
    # Слова нет в словаре — это ПРЕДУПРЕЖДЕНИЕ, а не запрет: надпись может
    # быть новой и законной. Файл всё равно делается, но в ответе
    # возвращается список подозрительных слов, и дашборд их показывает.
    _slova = {}
    _sl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "upakovka_lib", "slova.json")
    try:
        _slova = json.load(open(_sl_path, encoding="utf-8"))
    except (OSError, ValueError):
        pass

    # ── ГРАММАТИКА (07.11, его слово: «если я написал, допустим,
    # придется — поставил мягкий знак, значит надо убрать. Эту грамматику
    # тоже нужно следить и цеплять»).
    # Проверяем ТОЛЬКО то, что решается надёжно и не спорит с его стилем:
    # авторские слова вроде «капитулирован» не трогаем вовсе — словарь их
    # пропустит, а грамматика к ним не придирается.
    _MODAL = ("будет", "будут", "может", "могут", "должен", "должна",
              "должны", "надо", "нужно", "хочет", "хотят", "придется",
              "придётся", "пришлось", "стоит", "готов", "готова", "готовы",
              "решил", "решили", "пора", "нельзя", "можно")

    def _grammatika(text):
        import re as _re
        out = []
        words = _re.findall(r"[А-Яа-яЁё]+", text or "")
        low = [w.lower().replace("ё", "е") for w in words]
        for i, w in enumerate(low):
            orig = words[i]
            # 1. -ТСЯ / -ТЬСЯ. Перед глаголом стоит модальное слово —
            #    значит отвечает на «что делать?» и мягкий знак НУЖЕН.
            #    Нет модального — обычно «что делает?», знак лишний.
            if w.endswith("ться") or w.endswith("тся"):
                prev = low[i - 1] if i else ""
                need_soft = prev in _MODAL
                has_soft = w.endswith("ться")
                if need_soft and not has_soft:
                    out.append("%s — после «%s» нужен мягкий знак: %sться"
                               % (orig, prev, orig[:-3]))
                elif has_soft and not need_soft and i > 0:
                    out.append("%s — похоже, мягкий знак лишний: %sтся"
                               % (orig, orig[:-4]))
            # 2. школьные сочетания — это всегда ошибка
            for bad, good in (("чя", "ча"), ("щя", "ща"), ("жы", "жи"),
                              ("шы", "ши"), ("чю", "чу"), ("щю", "щу")):
                if bad in w:
                    out.append("%s — «%s» пишется как «%s»" % (orig, bad, good))
            # 3. слово без гласных или с тройной буквой — верный признак
            #    пропущенной или залипшей клавиши
            if len(w) >= 4 and not _re.search(r"[аеиоуыэюя]", w):
                out.append("%s — в слове нет гласных, пропущена буква?" % orig)
            if _re.search(r"(.)\1\1", w):
                out.append("%s — три одинаковые буквы подряд" % orig)
        return out

    def _opechatki(text):
        import re as _re
        bad = []
        for w in _re.findall(r"[А-Яа-яЁё]{3,}", text or ""):
            k = w.lower().replace("ё", "е")
            if k in _slova:
                continue
            # формы слова: ищем основу длиной от четырёх букв
            if any(k[:n] in _slova for n in range(len(k), 3, -1)
                   if len(k[:n]) >= 4 and _slova.get(k[:n], 0) >= 3):
                continue
            bad.append(w)
        return bad

    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "prevyu_text", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "prevyu_text.py"))
    _pt = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_pt)
    _spec2 = _ilu.spec_from_file_location(
        "upakovka", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "upakovka.py"))
    _up = _ilu.module_from_spec(_spec2)
    _spec2.loader.exec_module(_up)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            if self.path == "/more":
                return self.more()
            if self.path == "/make":
                return self.do_make()
            return self.send_error(404)

        def more(self):
            """ЕЩЁ ДЕСЯТЬ ВАРИАНТОВ (07.11, его заказ: «не подошли мне эти,
            или же, может быть, ты что-то другое бы предложил»).
            Спрашиваем того же внешнего агента, передав ему УЖЕ ВЫДАННОЕ —
            чтобы новые десять были именно другими, а не перетасовкой."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n).decode("utf-8"))
                it = items[int(req["item"])]
                kind = req.get("kind") or "заголовки"
                folder = it.get("превью_папка") or ""
                text = _up.read_text(_up.find_text(folder))
                было = it.get(kind) or []
                task = (
                    "ЗАДАНИЕ: ЕЩЁ ДЕСЯТЬ ВАРИАНТОВ\n\n"
                    "Канал: %s\nТема: %s\n\n"
                    "Нужны ещё ДЕСЯТЬ вариантов — %s.\n"
                    "Они должны быть ДРУГИМИ по ходу мысли, а не "
                    "перетасовкой уже выданных.\n\n"
                    "УЖЕ ВЫДАНО, НЕ ПОВТОРЯТЬ И НЕ ПЕРЕФРАЗИРОВАТЬ:\n· %s\n\n"
                    "%s\n\n"
                    "ЗАПРЕТЫ: стоп-слова «терроризм», «война», «шок» и "
                    "чувствительная лексика на обложку не выносить; "
                    "гипербола не подменяет факт; без капслока.\n\n"
                    "СЛОВАРЬ АВТОРСКИХ ФОРМУЛИРОВОК (источник интонации):\n%s\n\n"
                    "ФОРМАТ ОТВЕТА: ровно десять строк, пронумерованных "
                    "1..10, без заголовков и пояснений.\n\n"
                    "СТАТЬЯ\n%s\n"
                    % (it.get("канал", ""), it.get("тема", ""),
                       ("кликбейтные ЗАГОЛОВКИ: триггер + конкретный участник "
                        "+ действие + интрига, суть не раскрывать"
                        if kind == "заголовки" else
                        "НАДПИСИ НА ПРЕВЬЮ: 2-4 слова, резкий глагол или "
                        "реакция, без капслока"),
                       "\n· ".join(было),
                       ("Надпись и заголовок дополняют друг друга, а не "
                        "повторяют." if kind == "надписи" else ""),
                       _up.lib_text("bank.txt", 9000),
                       text[:9000]))
                tz = os.path.join(folder, "превью-варианты",
                                  "ЗАДАНИЕ-ЕЩЁ-%s.txt" % kind)
                os.makedirs(os.path.dirname(tz), exist_ok=True)
                open(tz, "w", encoding="utf-8").write(task)
                # ОДИН ВЫЗОВ АГЕНТА ЗА РАЗ (07.11, живая ошибка у
                # пользователя). Два задания одновременно — и второе
                # возвращается без файла ответа: агент на машине один,
                # параллелить его нельзя (тот же класс, что «три Codex
                # машина не тянет»). Замок держит очередь.
                # ВОЗВРАЩАЕМ ДОЧЕРНЕМУ ПРОЦЕССУ ОБЫЧНУЮ РЕАКЦИЮ НА SIGHUP
                # (07.11, живая ошибка «агент не ответил, код 2»).
                # Дашборд сам поднимается фоном, и его дети наследуют
                # игнор SIGHUP от `nohup`. `codex_ask.sh` это видит и
                # отказывается работать — справедливо: под nohup его
                # обёртка возвращается раньше агента, и разбор ответа
                # теряется. Поэтому не обходим защиту флагом, а снимаем
                # саму причину: в ребёнке возвращаем SIGHUP по умолчанию.
                def _restore_sighup():
                    import signal as _sg
                    try:
                        _sg.signal(_sg.SIGHUP, _sg.SIG_DFL)
                    except (ValueError, OSError):
                        pass

                with _codex_lock:
                    r = subprocess.run(["bash", os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        "codex_ask.sh"), tz],
                        capture_output=True, text=True, timeout=1800,
                        preexec_fn=_restore_sighup)
                _ans_path = tz[:-4] + ".ОТВЕТ.txt"
                # ЗАПАСНОЙ РАЗБОР: агент пишет черновик в `.raw` ещё до
                # готового ответа. Если ответа нет, а черновик есть —
                # берём список оттуда, он уже пригоден.
                if not os.path.isfile(_ans_path):
                    if os.path.isfile(_ans_path + ".raw"):
                        _ans_path += ".raw"
                    else:
                        raise RuntimeError(
                            "агент не ответил (код %s). %s"
                            % (r.returncode,
                               (r.stderr or r.stdout or "")[-200:]))
                ans = _up.read_text(_ans_path)
                import re as _re
                got = [_re.sub(r"^\s*\d+[.)]\s*", "", l).strip()
                       for l in ans.splitlines() if _re.match(r"^\s*\d+[.)]", l)]
                got = [g for g in got if g and g not in было][:10]
                if not got:
                    raise ValueError("агент не вернул список")
                it[kind] = было + got
                # дописываем в УПАКОВКА.json, чтобы не потерялось
                jp = os.path.join(folder, "УПАКОВКА.json")
                try:
                    data = json.load(open(jp, encoding="utf-8"))
                    data[kind] = it[kind]
                    json.dump(data, open(jp, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1)
                except (OSError, ValueError):
                    pass
                body = {"ok": True, "items": got}
            except Exception as exc:
                body = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            out = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_make(self):
            """Наложить надписи и сделать квадрат. Отдельным
            методом: при правке 07.11 тело обработчика случайно
            уехало внутрь `more()`, и POST /make обрывал соединение
            молча — снаружи это выглядело как «Failed to fetch».
            Разводим явно, чтобы такое не повторилось."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n).decode("utf-8"))
                it = items[int(req["item"])]
                folder = it.get("превью_папка") or ""
                num = int(req["n"])
                vdir = os.path.join(folder, "превью-варианты")
                src = os.path.join(vdir, "ПРЕВЬЮ-%d.png" % num)
                if not os.path.isfile(src):
                    src = os.path.join(folder, "ПРЕВЬЮ-%d.png" % num)
                if not os.path.isfile(src):
                    raise FileNotFoundError(src)
                ch = (it.get("канал") or "").upper()
                gamma = _pt.GAMMA.get(ch, _pt.DEFAULT)
                # ГОТОВОЕ — В КОРЕНЬ ТЕМЫ, рядом с озвучкой, имя ПО
                # НАЗВАНИЮ РОЛИКА (07.11)
                name = _pt.theme_name(folder)
                _t = (req.get("top") or "").upper()
                _b = (req.get("bottom") or "").upper()
                dst = os.path.join(folder, "%s ПРЕВЬЮ-%d.png" % (name, num))
                _pt.put(src, dst, _t, _b, gamma)
                # КВАДРАТ СРАЗУ ЖЕ, тем же именем плюс «КВАДРАТ», в ту же
                # папку (07.11, его слово: «делаю с тем же названием,
                # только квадратное, и ложишь туда же, рядышком»).
                _pt.put(src, os.path.join(
                    folder, "%s ПРЕВЬЮ-%d-КВАДРАТ.png" % (name, num)),
                    _t, _b, gamma, square=True)
                # кладём рядом со страницей, чтобы браузер смог показать
                sub = os.path.join(d, "prevyu", str(int(req["item"])))
                os.makedirs(sub, exist_ok=True)
                web = os.path.join(sub, "%d-text.png" % num)
                shutil.copy2(dst, web)
                _bad = _opechatki(_t) + _opechatki(_b)
                _gram = _grammatika(_t) + _grammatika(_b)
                body = {"ok": True,
                        "accent": ch_color(it.get("канал", ""))[0],
                        "opechatki": _bad,
                        "grammatika": _gram,
                        "file": os.path.basename(dst) + "  +  квадрат",
                        "url": "prevyu/%d/%d-text.png" % (int(req["item"]), num)}
            except Exception as exc:          # ответ всегда, даже на сбой
                body = {"ok": False, "error": "%s: %s"
                        % (type(exc).__name__, exc)}
            out = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    port = a.port
    while port < a.port + 40:
        try:
            # ПОТОЧНЫЙ СЕРВЕР: пока агент думает над «ещё 10 вариантов»
            # (это минуты), обычный однопоточный сервер не отдавал бы ни
            # страницу, ни картинки — дашборд выглядел бы мёртвым.
            class _Srv(socketserver.ThreadingTCPServer):
                daemon_threads = True
                allow_reuse_address = True

            srv = _Srv(("", port), Handler)
            break
        except OSError:
            port += 1
    else:
        sys.exit("свободного порта не нашлось")
    print("УПАКОВКА %s: роликов %d" % (a.day, len(items)))
    print("http://localhost:%d/index.html" % port)
    srv.serve_forever()


if __name__ == "__main__":
    main()

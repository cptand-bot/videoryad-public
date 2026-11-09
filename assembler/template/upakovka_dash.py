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
import time
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
# сливались у меня в одно»). Цвета приходят ИЗ ОДНОЙ ТАБЛИЦЫ ПАЛИТРЫ
# (`template/palitra.py`, 09.11) — своего списка здесь больше нет: раньше
# таких списков было три, и они разъехались (плашка субтитров ДС красилась
# бирюзой ПЛАНЕТЫ, пока дашборд знал про зелёный).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import palitra

CH_COLOR = {ch: palitra.KANALY[ch]["dash"] for ch in palitra.KANALY}


def ch_color(name):
    """Пара (акцент, фон) карточки канала. Неизвестный канал — нейтральная
    серая пара и голос в stderr, чужим фирменным цветом не красим."""
    return palitra.dash(name)


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
function openDlg(item, n, src, titles, sig, where){
  CUR = {item:item, n:n, sig:sig||''};
  // ЧТО ИМЕННО ПОЙДЁТ В РАБОТУ — НАДПИСЬЮ В ШАПКЕ ОКНА (08.11): канал,
  // тема и НОМЕР варианта. Раньше окно показывало только картинку, и
  // проверить, тот ли это вариант, было нечем.
  var cap = document.getElementById('dlg-where');
  if(cap){ cap.textContent = where || ''; }
  // ПОЛЯ ОЧИЩАЮТСЯ ПРИ КАЖДОМ ОТКРЫТИИ (07.11): раньше надписи прошлой
  // темы оставались в полях, и следующий вариант получал чужой текст.
  document.getElementById('dlg-top').value = '';
  document.getElementById('dlg-bottom').value = '';
  var ok = document.getElementById('dlg-ok');
  ok.textContent = 'ОК'; ok.disabled = false;
  document.getElementById('dlg-img').src = src + '?t=' + (sig||Date.now());
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
                  body: JSON.stringify({item:CUR.item, n:CUR.n, sig:CUR.sig,
                                        top:top, bottom:bot})})
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

// ЕГО ВЫБОР И СВЁРНУТЫЙ ВИД ЖИВУТ НА ДИСКЕ (09.11, его прямое слово: «то,
// что я уже сделал, я не хочу ещё раз сворачивать, но меня бесит вот это…
// чтобы оно уже пришло с моим выбором, вот в этом свёрнутом варианте»).
// Пишем КАЖДОЕ действие сразу, а не в конце: вкладку он закрывает когда
// захочет, и «конца работы» у дашборда нет — он пересобирается весь день.
function sost(item, patch){
  try{ fetch('/sostoyanie', {method:'POST',
       headers:{'Content-Type':'application/json'},
       body: JSON.stringify({item:item, patch:patch})}); }catch(e){}
}
// СВЕРНУТЬ / РАЗВЕРНУТЬ ВСЮ КАРТОЧКУ. Прячутся ДЕВЯТЬ отвергнутых
// вариантов и сетка превью; его выбор и описание с кнопкой «копировать»
// остаются на виду — «мне только осталось скопировать описание».
function cardFold(item){
  var v = document.getElementById('vars-' + item);
  var b = document.getElementById('foldbtn-' + item);
  if(!v){ return; }
  var hide = (v.style.display !== 'none');
  v.style.display = hide ? 'none' : 'block';
  if(b){ b.textContent = hide ? 'развернуть варианты'
                              : 'свернуть — с этим закончил'; }
  sost(item, {'свёрнута': hide});
}
// СКОПИРОВАЛ ОПИСАНИЕ → ОНО СВОРАЧИВАЕТСЯ (07.11, его заказ: «чтобы я
// понимал, что это я уже сделал, это будет мне сигналом»). Карточка
// остаётся, но описание прячется и помечается галочкой — видно с одного
// взгляда, что по этому ролику описание уже ушло на YouTube.
function copy(txt,el,descId,item){
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
      if(item!==undefined){ sost(item, {'описание_скопировано': true}); }
    } else {
      setTimeout(function(){el.textContent='копировать';el.classList.remove('done')},1200);
    }
  });
}
// СКРЫТЬ БЛОК ЗАГОЛОВКОВ ИЛИ НАДПИСЕЙ (07.11, та же мысль, что и с
// описанием: «чтобы тоже мне не мешало, чтобы я понимал, что с этим я
// уже закончил»). Блок сворачивается в узкую строку с галочкой, клик по
// ней разворачивает обратно.
function fold(id, item, kind){
  var b=document.getElementById(id);
  var m=document.getElementById(id+'-mark');
  if(b){ b.style.display='none'; }
  if(m){ m.style.display='block'; }
  if(kind){ var p={}; p['скрыто_'+kind]=true; sost(item, p); }
}
function unfoldBlock(id, item, kind){
  var b=document.getElementById(id);
  var m=document.getElementById(id+'-mark');
  if(b){ b.style.display='block'; }
  if(m){ m.style.display='none'; }
  if(kind){ var p={}; p['скрыто_'+kind]=false; sost(item, p); }
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
function unfold(descId,btnId,item){
  var d=document.getElementById(descId);
  var m=document.getElementById(descId+'-mark');
  var b=document.getElementById(btnId);
  if(d){ d.style.display='block'; }
  if(m){ m.style.display='none'; }
  if(b){ b.textContent='копировать описание'; b.classList.remove('done'); }
  if(item!==undefined){ sost(item, {'описание_скопировано': false}); }
}
// СВОЙ ВАРИАНТ ЗАГОЛОВКА (08.11, его просьба: «чтобы было поле, не
// обязательное, куда бы я мог вставить свой вариант, который я взял и сделал
// для этой статьи. Чтобы ты понимал, что я беру, что я сделал сам»).
// Это самый ценный материал для обучения: не выбор из наших десяти, а то,
// что он написал сам, когда ни один не подошёл.
function svoy(item, kind, id, btn){
  var el = document.getElementById(id);
  var t = (el && el.value || '').trim();
  if(!t){ el && el.focus(); return; }
  btn.disabled = true; var was = btn.textContent; btn.textContent = '…';
  fetch('/zhurnal', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({kind:'свой_'+kind, text:t, item:item})})
   .then(function(){ btn.textContent = 'записано ✓'; btn.classList.add('done');
                     el.readOnly = true; })
   .catch(function(){ btn.disabled = false; btn.textContent = was; });
}
function zhurnal(kind, text, item){
  try{ fetch('/zhurnal', {method:'POST', headers:{'Content-Type':'application/json'},
       body: JSON.stringify({kind:kind, text:text, item:item||0})}); }catch(e){}
}
function copyLi(li){
  zhurnal(li.dataset.k || 'строка', li.dataset.t, li.dataset.i || 0);
  navigator.clipboard.writeText(li.dataset.t).then(function(){
    var o=li.style.color; li.style.color='#4a9d5f';
    setTimeout(function(){li.style.color=o},900);
  });
}
"""


ЖУРНАЛ = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "upakovka_lib", "vybor.jsonl")


def записать_выбор(событие):
    """ЧТО ОН ВЫБРАЛ И ЧТО ВПИСАЛ — КОПИМ (08.11, его прямое слово).

    «Надо не просто выдавать варианты, а фиксировать, записывать логику, как
    это работает, по какой логике я их отбираю, какие вношу правки и какие
    надписи. Чтобы оно накапливалось… потом уже переобучить будет проще.
    Чтобы ты мне выдавал те варианты, которые меня устраивали бы».

    Его оценка выдачи на сегодня: «на девяносто процентов не соответствует
    тому, что я хотел бы видеть». Объяснять словами долго — значит собираем
    ПРИМЕРЫ: что выбрано, что вписано руками, что отвергнуто («ещё десять»).
    `upakovka.py` подкладывает последние принятые варианты в задание агенту,
    и выдача подтягивается к его вкусу без долгих объяснений.

    Пишем строками JSON — файл только дополняется, ничего не перезаписывается.
    """
    try:
        os.makedirs(os.path.dirname(ЖУРНАЛ), exist_ok=True)
        событие.setdefault("когда", time.strftime("%Y-%m-%d %H:%M:%S"))
        with open(ЖУРНАЛ, "a", encoding="utf-8") as f:
            f.write(json.dumps(событие, ensure_ascii=False) + "\n")
    except Exception:
        pass          # журнал не имеет права ломать работу дашборда
    # СЛЕД ДЛЯ СТОРОЖА ПОВТОРНЫХ ОПОВЕЩЕНИЙ (08.11, живой случай: он сделал
    # надписи на превью, а `dash_watch.sh` прислал «дашборд не тронут 15
    # минут»). Сторож смотрит `.dashboard_touch` в рабочем каталоге процесса,
    # который держит порт; боевой `review.py` эту метку пишет, а дашборд
    # упаковки не писал — значит любая работа руками была для сторожа
    # невидимой. Метка ставится на КАЖДОЕ действие руками: выбор заголовка,
    # выбор надписи, готовое превью.
    try:
        open(os.path.join(os.getcwd(), ".dashboard_touch"), "w").write(
            time.strftime("%H:%M:%S"))
    except OSError:
        pass


# ══════════════════════════════════════════════════════════════════════════
# ЕГО ВЫБОР И СВЁРНУТЫЙ ВИД ЖИВУТ НА ДИСКЕ (09.11.2026)
#
# Его прямое слово: «Вот этот мой выбор нужно будет запомнить. И каждый раз,
# если у нас какое-то обновление этого дашборда… чтобы оно уже пришло с моим
# выбором, вот в этом свёрнутом варианте, который сейчас. То есть то, что я
# уже сделал, я не хочу ещё раз сворачивать, но меня бесит вот это».
#
# Дашборд за день пересобирается несколько раз — по мере того, как
# появляются новые темы. До сегодня каждая сборка приходила ЧИСТОЙ: уже
# закрытые карточки приходилось закрывать заново. Поэтому состояние
# карточки пишется на диск при КАЖДОМ действии руками (вкладку он закрывает
# когда захочет, «в конце» не бывает) и восстанавливается при сборке.
#
# Ключ — канал + тема + день: тема с тем же номером и названием бывает и на
# другой день, и на другом канале.
# ══════════════════════════════════════════════════════════════════════════
СОСТОЯНИЕ = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "upakovka_lib", "sostoyanie.json")
_сост_замок = threading.Lock()


def ключ_карточки(канал, тема, день):
    return "%s | %s | %s" % ((канал or "").strip(), (тема or "").strip(),
                             день)


def читать_состояние():
    """Весь файл словарём. Правили руками и сломали — работаем как с
    чистого листа, а не падаем: состояние это удобство, а не данные."""
    try:
        d = json.load(open(СОСТОЯНИЕ, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def писать_состояние(ключ, патч):
    """Доливаем поля в запись карточки. Подмена файла через os.replace —
    он открыт на чтение сборкой страницы, рвать его на половине нельзя."""
    if not ключ or not патч:
        return
    try:
        with _сост_замок:
            всё = читать_состояние()
            зап = всё.get(ключ) or {}
            зап.update(патч)
            зап["когда"] = time.strftime("%Y-%m-%d %H:%M:%S")
            всё[ключ] = зап
            os.makedirs(os.path.dirname(СОСТОЯНИЕ), exist_ok=True)
            tmp = СОСТОЯНИЕ + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(всё, f, ensure_ascii=False, indent=1,
                          sort_keys=True)
            os.replace(tmp, СОСТОЯНИЕ)
    except Exception:
        pass          # состояние не имеет права ломать работу дашборда


def из_журнала(канал, тема, день):
    """ПРЕЖНИЕ КЛИКИ — ТОЖЕ СОСТОЯНИЕ (09.11).

    `vybor.jsonl` пишется с 08.11 и уже знает, что он выбрал. Это ЖУРНАЛ:
    только дополняется, переписывать его нельзя — но читать можно и нужно,
    иначе первая сборка с этой правкой пришла бы пустой по уже сделанным
    темам (а сделана, например, 5 МИНУТ «1-Украина Новая форма ПЕРЕГОВОРЫ»:
    превью-3 и свой заголовок).

    Дня в журнале нет, зато у события «превью» есть ПУТЬ к файлу, а в пути
    стоит папка дня — по ней и отличаем сегодняшнюю тему от одноимённой
    вчерашней. У выбора заголовка пути нет: там берём последнюю запись по
    каналу и теме.
    """
    st = {}
    try:
        строки = open(ЖУРНАЛ, encoding="utf-8").read().splitlines()
    except OSError:
        return st
    ck = (канал or "").strip().upper()
    tk = (тема or "").strip().upper()
    for line in строки:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if (ev.get("канал") or "").strip().upper() != ck:
            continue
        if (ev.get("тема") or "").strip().upper() != tk:
            continue
        вид = ev.get("событие") or ""
        if вид == "превью":
            путь = (ev.get("файл_превью") or ev.get("готовый_файл")
                    or "").replace("\\", "/")
            if путь and ("/%s/" % день) not in путь:
                continue              # одноимённая тема другого дня
            st["выбрано_превью"] = ev.get("выбран_вариант")
            st["надпись_сверху"] = ev.get("надпись_сверху") or ""
            st["надпись_снизу"] = ev.get("надпись_снизу") or ""
        elif вид == "свой_заголовки":
            st["свой_заголовок"] = ev.get("выбрано") or ""
        elif вид == "заголовки":
            st["выбран_заголовок"] = ev.get("выбрано") or ""
        elif вид == "надписи":
            st["выбрана_надпись"] = ev.get("выбрано") or ""
    return st


def состояние_карточки(it, день, файл=None):
    """Журнал даёт основу, файл состояния — последнее слово: руками он
    сворачивает и разворачивает уже ПОСЛЕ выбора."""
    ключ = ключ_карточки(it.get("канал", ""), it.get("тема", ""), день)
    st = из_журнала(it.get("канал", ""), it.get("тема", ""), день)
    всё = читать_состояние() if файл is None else файл
    st.update(всё.get(ключ) or {})
    return ключ, st


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
    # СОСТОЯНИЕ ЧИТАЕМ ОДИН РАЗ НА СТРАНИЦУ, а не на карточку
    _сост_файл = читать_состояние()
    for _i, it in enumerate(items):
        desc = it.get("описание", "")
        _accent, _bg = ch_color(it.get("канал", ""))
        # ЕГО ВЫБОР И ВИД КАРТОЧКИ — С ДИСКА (09.11, см. блок выше)
        _ключ, _st = состояние_карточки(it, day, _сост_файл)
        _zag = (_st.get("свой_заголовок")
                or _st.get("выбран_заголовок") or "").strip()
        _nad_t = (_st.get("надпись_сверху") or "").strip()
        _nad_b = (_st.get("надпись_снизу") or "").strip()
        if not _nad_t and not _nad_b:
            _nad_t = (_st.get("выбрана_надпись") or "").strip()
        try:
            _pn = int(_st.get("выбрано_превью") or 0)
        except (TypeError, ValueError):
            _pn = 0
        # ВЫБОР СДЕЛАН — значит по этой теме он уже работал
        _есть_выбор = bool(_zag or _nad_t or _nad_b or _pn)
        # СВЁРНУТА ПО УМОЛЧАНИЮ ТАМ, ГДЕ ВЫБОР ЕСТЬ; руками свернул или
        # развернул — его решение старше (пункт 5 его требования).
        _сверн = bool(_st.get("свёрнута", _есть_выбор))
        _desc_hid = bool(_st.get("описание_скопировано"))
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
        # ── ТВОЙ ВЫБОР: РЕЗУЛЬТАТ, А НЕ ВАРИАНТЫ (09.11, его слово: «тема
        # один у меня в принципе закончилась, мне только осталось
        # скопировать описание и вставить на YouTube»). Сворачивание убирает
        # ДЕВЯТЬ отвергнутых вариантов, а результат остаётся на виду и
        # копируется одной кнопкой.
        if _есть_выбор:
            P.append('<div style="border:1px solid %s;border-radius:8px;'
                     'padding:11px 13px;margin:0 0 15px;background:#0d0d10">'
                     % _accent)
            P.append('<div class="lab" style="margin:0 0 8px;color:%s">'
                     'твой выбор</div>' % _accent)
            if _zag:
                P.append('<div style="font-size:15px;font-weight:600;'
                         'margin-bottom:8px">%s</div>' % html.escape(_zag))
                P.append('<div class="row" style="margin:0 0 9px">'
                         '<button onclick=\'copy(%s,this)\'>копировать '
                         'заголовок</button></div>'
                         % json.dumps(_zag, ensure_ascii=False))
            if _nad_t or _nad_b:
                P.append('<div class="hint" style="margin-bottom:8px">'
                         'надписи на превью: <b style="color:%s">%s</b></div>'
                         % (_accent, html.escape(
                             "  /  ".join([x for x in (_nad_t, _nad_b) if x]))))
            # МИНИАТЮРА ВЫБРАННОГО ПРЕВЬЮ: с надписями, если готовое уже
            # сделано, иначе чистый вариант.
            _thumb = (it.get("превью_готовые") or {}).get(_pn)
            if not _thumb and _pn:
                for _u in (it.get("превью_файлы") or []):
                    if _u.endswith("/%d.png" % _pn):
                        _thumb = _u
                        break
            if _thumb:
                P.append('<div style="display:flex;gap:11px;'
                         'align-items:flex-start">')
                P.append('<img src="%s?t=%s" style="width:200px;'
                         'border-radius:6px;border:2px solid %s">'
                         % (_thumb, int(time.time()), _accent))
                P.append('<div class="hint">превью — вариант %d</div>' % _pn)
                P.append('</div>')
            elif _pn:
                P.append('<div class="hint">превью — вариант %d</div>' % _pn)
            P.append('</div>')
        _did = "d%d" % _i
        _bid = _did + "-btn"
        P.append('<div class="lab">описание для YouTube</div>')
        P.append('<div class="desc" id="%s"%s>%s</div>'
                 % (_did, ' style="display:none"' if _desc_hid else '',
                    html.escape(desc)))
        P.append('<div id="%s-mark" style="display:%s;padding:10px 12px;'
                 'border:1px dashed %s;border-radius:7px;color:%s;'
                 'font-size:13px;cursor:pointer" onclick="unfold(\'%s\',\'%s\',%d)">'
                 '✓ описание скопировано — нажми, чтобы раскрыть</div>'
                 % (_did, "block" if _desc_hid else "none", _accent, _accent,
                    _did, _bid, _i))
        P.append('<div class="row"><button id="%s"%s '
                 'onclick=\'copy(%s,this,"%s",%d)\'>%s</button>'
                 '<span class="hint">%d знаков</span></div>'
                 % (_bid, ' class="done"' if _desc_hid else '',
                    json.dumps(desc, ensure_ascii=False), _did, _i,
                    "описание скопировано ✓" if _desc_hid
                    else "копировать описание", len(desc)))
        # ── ДЕСЯТЬ ВАРИАНТОВ И СЕТКА ПРЕВЬЮ — ЭТО И ЕСТЬ СВОРАЧИВАЕМАЯ
        # ЧАСТЬ. Внутри остаётся всё как было, меняется только обёртка.
        P.append('<div id="vars-%d" style="display:%s">'
                 % (_i, "none" if _сверн else "block"))
        for key, lab in (("заголовки", "заголовки — 10 вариантов"),
                         ("надписи", "надписи на превью — 10 вариантов")):
            rows = it.get(key) or []
            if not rows:
                continue
            _bid = "%s%d" % ("t" if key == "заголовки" else "n", _i)
            _скрыт = bool(_st.get("скрыто_" + key))
            P.append('<div id="%s-mark" style="display:%s;padding:9px 12px;'
                     'margin-top:14px;border:1px dashed %s;border-radius:7px;'
                     'color:%s;font-size:13px;cursor:pointer" '
                     'onclick="unfoldBlock(\'%s\',%d,\'%s\')">✓ %s — скрыто, '
                     'нажми чтобы раскрыть</div>'
                     % (_bid, "block" if _скрыт else "none", _accent, _accent,
                        _bid, _i, key, lab))
            P.append('<div id="%s"%s>'
                     % (_bid, ' style="display:none"' if _скрыт else ''))
            P.append('<div class="lab">%s</div><ol>' % lab)
            for r in rows:
                # data-k и data-i — чтобы журнал знал, ЧТО именно выбрано
                # и по какому ролику (08.11)
                P.append('<li data-t="%s" data-k="%s" data-i="%d" '
                         'onclick="copyLi(this)">%s</li>'
                         % (html.escape(r, quote=True), key, _i,
                            html.escape(r)))
            P.append('</ol>')
            # ПОЛЕ «МОЙ ВАРИАНТ» — ТОЛЬКО У ЗАГОЛОВКОВ (08.11, его поправка:
            # «для надписей на превью этого поля не надо. Когда я ввожу сами
            # надписи, работая с превью, нет смысла мне её туда писать, и
            # неудобно — там две надписи. Ты должен поймать их уже с самого
            # превью, когда я его делаю»). Надписи и так пишутся в журнал при
            # нажатии «ОК» в окне превью: и верхняя, и нижняя, и пометка
            # «вписал сам», если текст не из наших десяти.
            _sid = "own-%s-%d" % (key, _i)
            if key == "заголовки":
              # УЖЕ ВПИСАННЫЙ ВАРИАНТ ВОЗВРАЩАЕТСЯ В ПОЛЕ (09.11): он его
              # писал руками, это самый дорогой материал — терять нельзя.
              _свой = (_st.get("свой_заголовок") or "").strip()
              P.append('<div class="row" style="margin-top:8px">'
                     '<input id="%s" placeholder="%s — вставь свой вариант, '
                     'если взял не из списка" value="%s"%s '
                     'style="flex:1;min-width:280px;padding:8px 10px;'
                     'border:1px solid var(--line);border-radius:6px;'
                     'background:#101014;color:inherit;font-size:13px">'
                     '<button%s onclick=\'svoy(%d,"%s","%s",this)\'>'
                     '%s</button></div>'
                     % (_sid, "заголовок", html.escape(_свой, quote=True),
                        " readonly" if _свой else "",
                        ' class="done"' if _свой else "", _i, key, _sid,
                        "записано ✓" if _свой else "записать мой вариант"))
            P.append('<div class="row">'
                     '<button onclick="fold(\'%s\',%d,\'%s\')">скрыть — с этим '
                     'закончил</button>'
                     '<button onclick=\'more(%d,"%s","%s",this)\'>'
                     'ещё 10 вариантов</button>'
                     '<span class="hint" id="%s-hint"></span></div>'
                     % (_bid, _i, key, _i, key, _bid, _bid))
            P.append('</div>')
        # ПРЕВЬЮ — САМИ КАРТИНКИ, А НЕ ПРОМПТ (07.11). Файлы лежат в папке
        # темы как ПРЕВЬЮ-N.png; на страницу они отдаются по короткой ссылке
        # /prevyu/<индекс>/<N>.png, которую раздаёт тот же сервер.
        shots = it.get("превью_файлы") or []
        if shots:
            P.append('<div class="lab">превью — %d вариантов</div>' % len(shots))
            P.append('<div style="display:grid;grid-template-columns:'
                     'repeat(auto-fit,minmax(150px,1fr));gap:8px">')
            _titles = json.dumps((it.get("надписи") or [])[:10],
                                 ensure_ascii=False)
            _done = it.get("превью_готовые") or {}
            # НОМЕР ВАРИАНТА = НОМЕР ФАЙЛА, А НЕ ПОЗИЦИЯ В СЕТКЕ (08.11):
            # стоит пропасть одному ПРЕВЬЮ-N, и позиции съезжают, а сервер
            # открывает файл по номеру — плитка и результат расходятся.
            _nums = it.get("превью_номера") or list(range(1, len(shots) + 1))
            for k, u in enumerate(shots, 1):
                # ЕСЛИ ВАРИАНТ УЖЕ СДЕЛАН С НАДПИСЬЮ — В СЕТКЕ СТОИТ ОН
                # (07.11, его слово: «чтобы я понимал: вот этот вариант я
                # не сделал, а вот этот у меня с надписью»). Готовый
                # подсвечен рамкой в цвете канала.
                # ГОТОВОЕ ИЩЕМ ПО НОМЕРУ ФАЙЛА, А НЕ ПО ПОЗИЦИИ
                _num = _nums[k - 1] if k - 1 < len(_nums) else k
                _src = _done.get(_num) or u
                _ready = _num in _done
                # НОМЕР ВАРИАНТА, ОТПЕЧАТОК ФАЙЛА И ИМЯ ТЕМЫ ЕДУТ ВМЕСТЕ С
                # КЛИКОМ (08.11). Раньше уезжал только номер — и если перед
                # ним была устаревшая страница, надпись ложилась на другую
                # картинку молча.
                _sig = (it.get("превью_отпечатки") or {}).get(_num, "")
                _where = "%s · %s · вариант %d" % (it.get("канал", ""),
                                                   it.get("тема", ""), _num)
                P.append('<img id="p-%d-%d" src="%s?t=%s" '
                         'onclick=\'openDlg(%d,%d,"%s",%s,"%s","%s")\' '
                         'title="нажми, чтобы наложить надписи" '
                         'style="width:100%%;border-radius:6px;cursor:pointer;'
                         'border:%s">'
                         % (_i, _num, _src, _sig, _i, _num, u, _titles, _sig,
                            _where.replace('"', "'"),
                            ("3px solid %s" % _accent) if _ready
                            else "1px solid var(--line)"))
            P.append('</div>')
        P.append('</div>')          # конец vars-N
        # КНОПКА СВОРАЧИВАНИЯ КАРТОЧКИ — И ЕЁ ПАМЯТЬ (09.11)
        P.append('<div class="row" style="margin-top:12px">'
                 '<button id="foldbtn-%d" onclick="cardFold(%d)">%s</button>'
                 '<span class="hint">этот вид запомнится — следующая сборка '
                 'придёт такой же</span></div>'
                 % (_i, _i, "развернуть варианты" if _сверн
                    else "свернуть — с этим закончил"))
        P.append('</div>')
    P.append('</div>')
    P.append("""
<div id="dlg" style="display:none;position:fixed;inset:0;background:#000c;
     z-index:99;align-items:center;justify-content:center" onclick="if(event.target===this)closeDlg()">
 <div style="background:#17171a;border:1px solid #33333a;border-radius:10px;
      padding:18px;width:min(760px,92vw);max-height:92vh;overflow:auto">
  <div style="display:flex;align-items:center;justify-content:space-between">
    <div>
      <div class="lab" style="margin-top:0">надписи на превью</div>
      <div id="dlg-where" class="hint" style="margin-top:2px"></div>
    </div>
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



def _otpechatok(path):
    """Короткий отпечаток файла: им страница и сервер сверяют, что речь об
    ОДНОЙ И ТОЙ ЖЕ картинке (08.11). Берём размер и время правки — читать
    трёхмегабайтный png на каждый клик незачем."""
    try:
        st = os.stat(path)
        return "%d-%d" % (st.st_size, int(st.st_mtime))
    except OSError:
        return ""


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

    # ДВА ДАШБОРДА ОДНОГО ДНЯ ДЕЛИЛИ ОДНУ ПАПКУ (09.11, живой случай при
    # этой же правке): папка `/tmp/upakovka-<день>` зависит только от дня,
    # поэтому проверочный сервер на своём порту перезаписывал `index.html`
    # ЖИВОГО дашборда пользователя — тот начинал отдавать чужую страницу.
    # Теперь папку можно увести переменной и проверять, никого не задев.
    d = os.environ.get("VIDEORYAD_UPAK_TMP") or os.path.join(
        "/tmp", "upakovka-%s" % a.day)
    os.makedirs(d, exist_ok=True)
    # КАРТИНКИ КЛАДЁМ РЯДОМ СО СТРАНИЦЕЙ: сервер раздаёт только свою папку,
    # а папки тем лежат на D: — ссылаться туда напрямую нельзя.
    for i, it in enumerate(items):
        folder = it.get("превью_папка") or ""
        urls = []
        vdir = os.path.join(folder, "превью-варианты")
        if not os.path.isdir(vdir):
            vdir = folder
        _nums, _sigs = [], {}
        # ДИАПАЗОН ШИРЕ ВОСЬМИ (08.11): после «ещё 10 вариантов» файлы
        # бывают с номерами за десяток, и сетка их просто не показывала.
        for n in range(1, 41):
            src = os.path.join(vdir, "ПРЕВЬЮ-%d.png" % n)
            if not os.path.isfile(src):
                continue
            _nums.append(n)
            _sigs[n] = _otpechatok(src)
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
        it["превью_номера"] = _nums
        it["превью_отпечатки"] = _sigs
        # УЖЕ СДЕЛАННЫЕ С НАДПИСЬЮ — ищем в корне темы по имени ролика
        ready = {}
        try:
            name = _pt_name(folder)
        except Exception:
            name = ""
        for n in range(1, 41):
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

        # НИЧЕГО НЕ КЭШИРУЕМ (08.11, его улов: «выбираю картинку, делаю
        # надписи, а применяется к другой»). Порт 8811 поднимается каждый
        # день заново, адреса плиток при этом ОДНИ И ТЕ ЖЕ
        # (`prevyu/<номер темы>/<номер варианта>.png`). Браузер честно
        # показывал вчерашнюю картинку из своего кэша, а клик уходил на
        # сегодняшний файл с тем же номером — отсюда «применилось к другой».
        def end_headers(self):
            self.send_header("Cache-Control",
                             "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            http.server.SimpleHTTPRequestHandler.end_headers(self)

        def do_POST(self):
            if self.path == "/more":
                return self.more()
            if self.path == "/make":
                return self.do_make()
            if self.path == "/zhurnal":
                return self.do_zhurnal()
            if self.path == "/sostoyanie":
                return self.do_sostoyanie()
            return self.send_error(404)

        def _ok(self):
            out = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_sostoyanie(self):
            """ВИД КАРТОЧКИ РУКАМИ (09.11): свернул, развернул, скопировал
            описание. Журнал этого не знает — он про ВЫБОР, а это про то,
            что он уже закрыл. Пишем сразу, на каждое действие."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n).decode("utf-8"))
                it = items[int(req.get("item", 0))]
                писать_состояние(
                    ключ_карточки(it.get("канал", ""), it.get("тема", ""),
                                  a.day),
                    req.get("patch") or {})
            except Exception:
                pass
            return self._ok()

        def do_zhurnal(self):
            """Клик по строке = выбор. Пишем, что именно он скопировал."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n).decode("utf-8"))
                it = items[int(req.get("item", 0))] if items else {}
                записать_выбор({"событие": req.get("kind") or "строка",
                                "канал": it.get("канал", ""),
                                "тема": it.get("тема", ""),
                                "выбрано": req.get("text", "")[:300],
                                "предложено": (it.get(req.get("kind") or "") or [])[:10]})
                # ЖУРНАЛ — ЭТО ИСТОРИЯ, СОСТОЯНИЕ — ЭТО «ЧТО СЕЙЧАС»
                # (09.11). Один и тот же клик пишем в оба места: журнал
                # копится для обучения выдачи, состояние возвращает карточке
                # его выбор при следующей сборке.
                _вид = req.get("kind") or ""
                _поле = {"заголовки": "выбран_заголовок",
                         "надписи": "выбрана_надпись",
                         "свой_заголовки": "свой_заголовок"}.get(_вид)
                if _поле:
                    писать_состояние(
                        ключ_карточки(it.get("канал", ""), it.get("тема", ""),
                                      a.day),
                        {_поле: (req.get("text") or "")[:300]})
            except Exception:
                pass
            return self._ok()

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
                записать_выбор({"событие": "ещё_десять", "вид": kind,
                                "канал": it.get("канал", ""),
                                "тема": it.get("тема", ""),
                                "отвергнуто": (it.get(kind) or [])[:10]})
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
                # СТРАНИЦА ОБЯЗАНА НАЗВАТЬ ТО ЖЕ, ЧТО ВИДИТ ПОЛЬЗОВАТЕЛЬ
                # (08.11). Вместе с номером она присылает отпечаток
                # картинки, которую показала в окне. Не совпал — значит
                # перед ним устаревшая страница, и МЫ НИЧЕГО НЕ ДЕЛАЕМ:
                # молча наложить надпись на другую картинку хуже отказа.
                _есть = _otpechatok(src)
                _ждали = (req.get("sig") or "").strip()
                if _ждали and _ждали != _есть:
                    raise ValueError(
                        "страница показывает не тот вариант, что лежит на "
                        "диске (вариант %d темы «%s»). Обнови страницу "
                        "(Ctrl+F5) и выбери картинку заново — надписи на "
                        "чужой кадр я не кладу." % (num, it.get("тема", "")))
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
                записать_выбор({
                    "событие": "превью",
                    "канал": it.get("канал", ""), "тема": it.get("тема", ""),
                    "выбран_вариант": num,
                    # ПУТЬ К КАРТИНКЕ — ЧТОБЫ ПОТОМ ОПИСАТЬ, ЧТО НА НЕЙ
                    # (08.11, его слово: «записал бы, что нарисовано на
                    # превью, как оно отражается… может быть, какие-то эмоции
                    # заходят. Мы всё равно выявим на дистанции паттерн»).
                    "файл_превью": os.path.abspath(src),
                    "готовый_файл": os.path.abspath(dst),
                    "надпись_сверху": _t, "надпись_снизу": _b,
                    "предложенные_надписи": (it.get("надписи") or [])[:10],
                    "вписал_сам": bool(_t and _t not in
                                       [x.upper() for x in (it.get("надписи") or [])]),
                })
                # ВЫБРАННОЕ ПРЕВЬЮ И НАДПИСИ — В СОСТОЯНИЕ (09.11):
                # «картинка там применилась, заголовки я тоже применил, и
                # всё свернул. Вот этот мой выбор нужно будет запомнить».
                писать_состояние(
                    ключ_карточки(it.get("канал", ""), it.get("тема", ""),
                                  a.day),
                    {"выбрано_превью": num, "надпись_сверху": _t,
                     "надпись_снизу": _b})
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

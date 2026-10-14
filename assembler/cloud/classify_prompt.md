# Задача: разложить видеоряд на сцены и классифицировать — SEARCH-ONLY

Ты в облаке (GitHub Actions), на второй канал (НЕ «ПЛАНЕТА»). Медиатеки здесь
нет и быть не может. Работай только с папкой проекта в `queue/<name>/` и с
`_assembler/` (это копия скилла news-video, только чтение).

Сначала прочитай `_assembler/СБОРКА-НОВОСТНОГО-РОЛИКА.md` целиком — там все
правила. Ключевое для облака:

## Что делаешь (и только это — сборку НЕ запускай, её сделает cloud_pipeline.py потом)

1. **Сцены из SRT.** В папке проекта лежит `*-caption.srt` и озвучка
   (`*_1080p.mp4`). Запусти:
   `python3 _assembler/template/scenes_from_srt.py <srt> <озвучка> <name>.scenes.json`
   (name — любое короткое, напр. `videoryad`). Проверь строку «diff ≈0.00s».

2. **Классифицируй КАЖДУЮ сцену.** Для каждой сцены заполни `source` и
   `source_query`:
   - **Всё через поиск.** `source: "press_photo"` + `source_query` —
     **запрос ПО-РУССКИ** (Яндекс их резолвит: имена, ТЦК, конкретные места).
     Формулируй запрос по СУТИ сцены, а не по слову из предложения
     (правило a0/«illustrate the event, not the word»). Абстрактная фраза
     про цифры/арифметику → реальный предмет темы (люди, событие, место,
     карта), НЕ калькулятор/шестерёнка/метафора.
   - Чистый объект без людей (панорама, документ крупным планом, техника) →
     `source: "pexels_photo"` или `"pexels_video"`, запрос по-английски.
   - **Сток людей для политики ЗАПРЕЩЁН** (правило 2).
   - **Видео-лид (правило 7):** сцена 1 — `pexels_video`; и в первой трети
     ролика по хронометражу видео должно ПРЕОБЛАДАТЬ над фото. Для видео бери
     обобщённый современный B-roll: `military convoy on a road`,
     `soldiers running field`, `armored vehicle dust`, `drone aerial fields`,
     `artillery firing smoke`, `flags waving wind`, `intercity bus highway`,
     `lit candles close`, `crowd walking street`. НЕ бери запросы, по которым
     сток отдаёт исторических реконструкторов («soldiers marching column» и
     т.п. без «modern»). Прогони `python3 _assembler/template/check_lead.py
     <name>.scenes.json images` — если exit 1, переведи ещё фото-сцены первой
     трети на `pexels_video`, пока не ok.
   - Разнообразие: не лепи один и тот же субъект (напр. лицо одного человека)
     больше ~3–4 раз за ролик — остальные его сцены давай через то, о чём он
     говорит.

3. **Шапка scenes.json — `meta`:** `{"channel": "<имя канала>",
   "library": "NO (search-only)"}`.

4. **Всплывашки.** Создай `overlays.json`:
   - Первым ключом верхнего уровня: `"anchor": "top"` (не-Планета = сверху).
   - ~3 всплывашки на минуту, на видео-сценах, staggered. Каждая:
     `{"photo": "overlays/scene_NNN.jpg", "sound": "<whoosh|zatvor|pop>",
       "at": <≈0.35·длит>, "shape": "rect", "style": "up-center", "scale": 1.0}`.
   - Всплывашка = ДРУГАЯ половина смысла сцены, НЕ тот же субъект, что в
     кадре (человек в кадре → место/объект/карта; место/событие → человек).
   - Создай `overlays_fetch.scenes.json`:
     `{"scenes": [{"id": NNN, "text": "", "duration_sec": 4,
       "visual_prompt": "<рус. запрос>", "source": "press_photo",
       "source_query": "<рус. запрос>"}, ...]}` — по одному на каждую
     всплывашку. cloud_pipeline.py скачает их в `overlays/`.

5. **Отчёт о своих решениях** — обязательно. Создай в папке проекта
   `_cloud/classify_report.md` (папку `_cloud/` создай, если нет):
   - одной строкой на сцену: `NN | source | source_query | почему именно так`
   - отдельным списком в конце: сцены, где ты НЕ уверен в подборе (нужен
     глаз человека на дашборде), и почему.
   Это единственный способ для нас потом поймать твои косяки — пиши честно,
   не приукрашивай.

6. **НЕ запускай** `fetch_assets_news.py`, `build_clips_1080.py`,
   `build_overlays.py`. НЕ создавай `needs_upload.json` заранее — пусть поиск
   отработает. НЕ трогай `_assembler/`.

Когда `<name>.scenes.json` (все сцены с `source`+`source_query`, лид ok),
`overlays.json` (с `anchor`), `overlays_fetch.scenes.json` и
`_cloud/classify_report.md` готовы — останавливайся. Всё, что дальше,
сделает cloud_pipeline.py на этом же прогоне, а финал + логи + QA-отчёт
уедут в GitHub Release.

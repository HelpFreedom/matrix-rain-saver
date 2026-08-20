# matrix-rain — архитектура и техническое резюме

Матричный «дождь» для X11: скринсейвер и полноценный экранный локер, порт
рендер-пайплайна [Rezmason/matrix](https://github.com/Rezmason/matrix) (WebGL/regl)
на Python + moderngl (OpenGL 3.3 core), в котором дождь «расшифровывается» в русские
новостные заголовки из локальной SQLite-базы. Стилистика текстовой машины (reveal →
dwell → erase со скрэмблом) — по мотивам
[meanwhile](https://github.com/tomdavenport/meanwhile). Обе лицензии MIT.

- **Язык/стек:** Python 3.11+ (tomllib), moderngl, numpy, python-xlib, Pillow, ctypes (Xlib/GLX).
- **Платформа:** X11 (любой WM, любое число мониторов через RandR). Wayland вне скоупа.
- **Безопасный локер:** xsecurelock как хост (грабы, устойчивость, PAM) + наши модули
  saver (дождь) и auth (диалог SYSTEM FAILURE).
- **Кириллица:** собственный Matrix-шрифт — осевые скелеты → раздувание штриха → MSDF-атлас.

---

## 1. Общая схема

```
                    ┌────────────────────────────────────────────────┐
  standalone        │  python -m matrixrain --standalone             │
                    │  launcher.run() — супервизор                   │
                    │   ├── renderer proc (--geometry, монитор 1)    │
                    │   ├── renderer proc (--geometry, монитор 2)    │
                    │   ├── ...                                      │
                    │   └── InputWatcher: грабы клав+мышь,           │
                    │       любой ввод → SIGTERM детям → выход       │
                    └────────────────────────────────────────────────┘

                    ┌────────────────────────────────────────────────┐
  локер             │  bin/matrix-lock → exec xsecurelock            │
                    │   ├── SAVER: saver_matrixrain (на монитор)     │
                    │   │    └── python -m matrixrain                │
                    │   │        --embed-window $XSCREENSAVER_WINDOW │
                    │   └── AUTH: auth_matrixrain (на любой ввод)    │
                    │        └── python -m matrixrain.lock.run_auth  │
                    │             ├── ждёт печатную клавишу (gate)   │
                    │             ├── LockDialog (SYSTEM FAILURE)    │
                    │             └── authproto_pam → PAM → unlock   │
                    └────────────────────────────────────────────────┘

  Межпроцессная координация (файлы в $XDG_RUNTIME_DIR/matrix-rain/):
    textstate-WxH.npy   — общий текстовый слой (мастер пишет, реплики читают)
    textstate-WxH.lock  — flock-выборы мастера текста
    freeze              — флаг «заморозь дождь» (auth держит, saver опрашивает)
    savers/saverwin-PID.json — реестр живых окон saver'ов (для диалога)
```

Ключевая идея мультимонитора: **один общий «мир»** — bounding box всех мониторов.
Каждый процесс-рендерер детерминированно симулирует весь (крошечный) мир от общей
временной базы `--t0` и рисует только свой кроп (`uvOffset`/`uvScale`). Потоки дождя
и заголовки непрерывны через границы мониторов без какого-либо обмена кадрами.

---

## 2. Дерево репозитория

```
matrix-rain-saver/
├── install.sh                  # venv, зависимости, сборка msdfgen, ассеты, атлас
├── requirements.txt            # moderngl, numpy, python-xlib, Pillow, wcwidth
├── LICENSE                     # GNU GPL-3.0
├── NOTICE                      # атрибуция MIT-кода, из которого сделан порт
├── README.md                   # описание проекта (RU — основной)
├── README.en.md                # то же по-английски
├── docs/INSTALL.md             # подробная установка и настройка (RU)
├── docs/INSTALL.en.md          # то же по-английски
├── docs/demo.gif               # демонстрация для README
├── config/default.toml         # все настройки с комментариями (= документация)
├── bin/matrix-lock             # запуск защищённого локера (xsecurelock)
├── matrixrain/                 # основной пакет (в сеть не ходит вообще)
│   ├── __main__.py             # CLI: --standalone | --geometry | --embed-window
│   ├── config.py               # слоёный TOML-конфиг
│   ├── launcher.py             # standalone-супервизор
│   ├── xwindow.py              # python-xlib: RandR, грабы, координаты окон
│   ├── glx.py                  # ctypes: X-окно + GL 3.3 core контекст
│   ├── lockui.py               # GL-диалог SYSTEM FAILURE (свой bloom)
│   ├── renderer/
│   │   ├── engine.py           # весь фрейм-граф (порт Rezmason)
│   │   ├── buffers.py          # PassFBO, PingPong
│   │   └── shaders/*.glsl      # 10 шейдеров (порт ES 1.0 → 330 core)
│   ├── text/
│   │   ├── feed.py             # заголовки из произвольной SQLite-базы
│   │   ├── layout.py           # нормализация + разбивка на 2 строки
│   │   ├── message.py          # стейт-машина reveal/dwell/erase
│   │   ├── textstate.py        # TextLayer → RGBA-текстура мира
│   │   └── share.py            # мастер/реплики через файл + flock
│   └── lock/
│       ├── run_auth.py         # entry point AUTH-модуля
│       ├── authmod.py          # gate, KeyStream, PAM-цикл, зануление пароля
│       ├── authproto.py        # wire-протокол authproto (пакеты)
│       ├── freeze.py           # freeze-флаг (файл с TTL)
│       └── savermap.py         # реестр saver-окон
├── atlas/
│   ├── skeletons.py            # осевые скелеты глифов (данные)
│   ├── stroke_expand.py        # скелет → msdfgen shape description
│   ├── build_atlas.py          # сборка atlas_combined.png + atlas.json
│   ├── preview.py              # CPU-декод MSDF для визуальной проверки
│   └── fetch_assets.sh         # скачивание оригинального атласа + референсов
├── assets/                     # matrixcode_msdf.png, atlas_combined.png, atlas.json
├── vendor/rezmason/            # референс-исходники для диффа (не коммитятся)
└── xsecurelock/
    ├── saver_matrixrain        # обёртка SAVER-модуля
    ├── auth_matrixrain         # обёртка AUTH-модуля
    └── pam.d/xsecurelock       # шаблон PAM-сервиса (@include common-auth)
```

Объём Python-кода: ~3250 строк + ~460 строк GLSL.

---

## 3. Точка входа: `matrixrain/__main__.py`

Три взаимоисключающих режима CLI:

| Флаг | Режим |
|---|---|
| `--standalone` | супервизор: рендерер на каждый монитор, выход по любому вводу |
| `--geometry WxH+X+Y` | одно окно с заданной геометрией (отладка/ребёнок супервизора) |
| `--embed-window ID` | рендер в чужое окно (`$XSCREENSAVER_WINDOW` xsecurelock) |

Дополнительно: `--monitor` (имя для per-monitor секций конфига), `--config`,
`--world WxH+X+Y` (bbox мира, передаёт супервизор), `--t0` (общая временная база),
`--timeout` (для тестов).

### Функции

- `parse_geometry(s)` / `parse_window_id(s)` — парсеры аргументов (`int(s, 0)`
  принимает и десятичные, и `0x…` id окон).
- `_coverage_cells(mons, wx, wy, grid_w, grid_h, cell)` — прямоугольники мониторов →
  прямоугольники в ячейках мировой сетки (для размещения текста строго внутри
  одного монитора).
- `run_renderer(cfg, *, geometry, embed, monitor_name, timeout, world, t0)` — тело
  процесса-рендерера. Ключевые моменты:
  - **embed**: окно-ребёнок заполняет родителя; если `--t0` не передан (под
    xsecurelock супервизора нет), база выводится из wall-clock:
    `t0 = floor(time.time()/300)*300` — все дети, стартовавшие в одном 5-минутном
    окне, получают одинаковую базу и рисуют один непрерывный дождь.
  - **viewport**: `(own_rect - world_origin)` — положение окна внутри мира.
  - **Время кадра**: `t = wall - t0 - pause_offset`. При заморозке `t` пинится на
    момент заморозки, но кадр продолжает перерисовываться — окно «чинится», если
    поверх него что-то рисовали (диалог пароля).
  - **Только в embed-режиме**: опрос `is_frozen()` (заморозка от auth-модуля),
    `SIGUSR1/2 = SIG_IGN` (xsecurelock шлёт SIGUSR1 при reset — не наш сигнал),
    `SaverRegistration(win.win, own_rect)` — публикация своего GL-окна для диалога.
    Регистрируется именно **внутреннее GL-окно** (не внешний `$XSCREENSAVER_WINDOW`):
    диалог затем рисуется его ребёнком, а не сиблингом — иначе композитор
    произвольно выбирает, кого из сиблингов показать сверху.
  - **Цикл кадра**: poll_resize → text_share.tick → engine.render → swap → сон до
    fps-бюджета. SIGTERM/SIGINT завершают цикл чисто (finally: close всех ресурсов).
- `run_standalone(cfg, timeout, config_path)` — тонкая обёртка над `launcher.run`.
- `main()` — argparse, загрузка конфига, экспорт `display.env` (например,
  `DRI_PRIME=1`) через `os.environ.setdefault`.

---

## 4. Конфигурация: `matrixrain/config.py` + `config/default.toml`

Слои (нижний перекрывается верхним):

1. `config/default.toml` — встроенные дефолты, полностью откомментированы;
2. `~/.config/matrix-rain/config.toml` — пользовательский (deep-merge);
3. `[monitor.<RandR-имя>]` — плоские per-monitor переопределения (применяет
   `Config.for_monitor`, раскладывая ключи по секциям rain/glyphs/text/display);
4. CLI-флаги.

### Класс `Config`

- `cfg["a.b.c"]` / `cfg.get("a.b.c", default)` — доступ по точечному пути.
- `cfg.section(name)` — глубокая копия секции.
- `cfg.path("feed.db")` — значение как путь: `~` раскрывается, относительные пути
  якорятся на корень репозитория (`PROJECT_ROOT`).
- `cfg.palette_stops()` — стоп-точки градиента текущего пресета палитры
  (`classic-green` | `amber` | `ice-blue` | `red` | `custom`).
- `cfg.for_monitor(name)` — новый Config с наложенной секцией `[monitor.<name>]`.

### Секции default.toml

- `[display]` — mode, monitors ("all" или список RandR-имён), fps, env.
- `[palette]` — пресет, cursor_color/intensity, **text_color** (тёмно-оранжевый
  `[0.85, 0.42, 0.05]` — цвет осевших заголовков; bloom канала подхватывает его
  автоматически), background, dither.
- `[rain]` — direction (**horizontal** по умолчанию — потоки слева направо, как в
  meanwhile; vertical — канонический дождь), animation_speed, fall_speed,
  raindrop_length, cycle_speed/frame_skip, brightness_decay, base_brightness/contrast,
  skip_intro.
- `[bloom]` — strength (0 отключает пасс), size (масштаб пирамиды), high_pass_threshold.
- `[glyphs]` — atlas/atlas_meta (пути), rain_sequence_length (57 — дождь сыплет
  только оригинальные матричные глифы; поднять — и кириллица посыплется в дожде),
  cell_size (20 px — фактически размер шрифта).
- `[text]` — max_length (72, построчный лимит), interval_min/max, reveal_rate,
  dwell, erase_rate, brightness, scramble_brightness, fade_brightness,
  scramble_width, max_concurrent.
- `[feed]` — db (путь к вашей SQLite-базе; по умолчанию пусто = только fallback-фразы), window_hours (20),
  refresh_seconds (3600), db_table/db_title_column/db_time_column,
  db_time_local (false — время в БД UTC), exclude (регэкспы мусора), fallback-фразы.
- `[lock]` — key_to_open (true — диалог открывается когда пользователь начинает
  печатать; мышь не открывает), idle_timeout (45 c).

---

## 5. Оконный слой

### `matrixrain/glx.py` — ctypes Xlib + GLX

python-xlib — чистый протокольный клиент и не может отдать соединение в GLX,
поэтому рендер-окна создаются напрямую через `libX11`/`libGL` (ctypes). Два
соединения с X (ctypes и python-xlib) сосуществуют свободно — XID глобальны.

Класс **`GLWindow(x, y, width, height, parent=None, override_redirect=True,
title, argb=False, fill_parent=True)`**:

- Выбор `GLXFBConfig` (RGBA8, double-buffer; при `argb=True` — ищется конфиг с
  32-битным X-визуалом, чтобы композитор трактовал альфу как прозрачность;
  fallback на opaque, фактический режим — `self.argb`).
- Создание окна: родитель = root (standalone, override-redirect — WM игнорирует)
  или чужое окно (embed). `fill_parent=True` — ребёнок с (0,0) заполняет родителя
  (saver); `fill_parent=False` — ребёнок в точке (x, y) внутри родителя (диалог).
- Контекст: `glXCreateContextAttribsARB` → GL 3.3 core → `glXMakeCurrent`;
  vsync через `glXSwapIntervalEXT` (best-effort). moderngl подключается к текущему
  контексту через `moderngl.create_context()`.
- `_hide_cursor()` — классический трюк: 1×1 нулевой bitmap как source и mask
  курсора → полностью прозрачный курсор (сейвер не показывает указатель).
- `raise_()` — XRaiseWindow (диалог держится над сиблингами).
- `poll_resize()` — дренаж очереди событий; ConfigureNotify → (w, h).
- `swap()`, `close()` — буферы/уничтожение ресурсов.

### `matrixrain/xwindow.py` — python-xlib утилиты

- `Monitor` (dataclass: name, x, y, width, height; `.geometry` → "WxH+X+Y").
- `monitors()` — RandR-энумерация мониторов (никакого хардкода имён/геометрий).
- `world_bbox(mons)` — bounding box всех мониторов = мир дождя.
- `window_root_position(window_id)` — абсолютные координаты чужого окна
  (`translate_coords` от root) — нужно embed-рендереру и диалогу.
- `InputWatcher` — супервизорная сторона standalone: display-wide граб клавиатуры
  и указателя с ретраями (25×100 мс — граб может держать чужой popup),
  `wait_for_input()` — блокируется до клавиши/кнопки/заметного (>10 px) движения
  мыши, `close()` — снятие грабов.

---

## 6. Standalone-супервизор: `matrixrain/launcher.py`

Модель — точь-в-точь `saver_multiplex` xsecurelock, поэтому переход embed ↔
standalone не требует изменений рендерера.

- `_selected_monitors(cfg)` — RandR-мониторы, отфильтрованные `display.monitors`
  (отсутствующие имена — warning, не ошибка).
- `run(cfg, timeout, config_path)`:
  1. Мир = bbox **всех** мониторов (даже невыбранных — сетка идентична при любом
     подмножестве), t0 = текущий wall-clock.
  2. Спавн ребёнка на монитор: `python -m matrixrain --geometry … --monitor …
     --world … --t0 …`.
  3. 0.3 c на маппинг окон детей → грабы (`InputWatcher`); при неудаче — деградация
     в no-grab режим (выход по SIGTERM).
  4. Ожидание: ввод / timeout / SIGTERM / смерть ребёнка → SIGTERM всем детям,
     wait с таймаутом, kill упрямым.
- `_wait_for_input(watcher, stop, deadline, children)` — select на fd X-соединения
  вместо блокирующего `next_event` (иначе SIGTERM/timeout не обработать):
  KeyPress/ButtonPress → выход; MotionNotify — с порогом 10 px от первой позиции.

Это **не локер** (грабы держим, но пароля нет) — для лока есть `bin/matrix-lock`.

---

## 7. Рендер-пайплайн: `matrixrain/renderer/`

### Фрейм-граф (порт Rezmason, невольюметрический путь)

```
GPGPU (пинг-понг f2-текстуры, 1 тексель = 1 ячейка сетки):
  intro ──► raindrop ──► symbol
                └───────► effect
Рендер:
  rain.frag (MSDF-глифы) ──► primary FBO (каналы R/G/B — см. ниже)
Свечение:
  highpass ──► пирамида blur (5 уровней, H+V) ──► combine ──► bloom FBO
Финал:
  palette.frag (primary + bloom → градиент палитры + дизеринг) ──► экран
```

### `buffers.py`

- `make_texture(ctx, size, dtype="f2", filter=NEAREST)` — RGBA half-float текстура
  без repeat.
- `PassFBO` — текстура + FBO (аналог makePassFBO), `release()`.
- `PingPong` — две пары FBO+текстура, `front_fbo` / `front_texture` /
  `back_texture`, `swap()` раз в кадр (аналог makeDoubleBuffer regl).

### `engine.py` — класс `Engine`

`Engine(ctx, size, cfg, target=None, world=None, viewport=None)`:

- `_load_atlas()` — atlas_combined.png (fallback: оригинальный matrixcode_msdf.png),
  метаданные atlas.json (`grid`, `char_map`). **Критично:** изображение
  переворачивается по вертикали (`FLIP_TOP_BOTTOM`) — regl грузит текстуры с
  `flipY: true`, и `getSymbolUV` адресует ячейки в этой системе.
- `_build_programs()` — 9 программ (все пассы — полноэкранный треугольник,
  `vao.vertices = 3` без атрибутов; координаты генерирует `fullscreen.vert.glsl`
  из `gl_VertexID`). Палитра — 2048×1 RGBA8 LUT из стоп-точек (`_build_palette`
  интерполирует `np.interp` по каналам).
- `_allocate(size, world, viewport)` — вычисление **мировой сетки**
  (`grid = world_px / cell_size`) и **сим-сетки**: в горизонтальном режиме
  симуляция — транспонированная мировая сетка (сим-«колонки» = мировые строки,
  голова потока движется к sim y=0 = вправо по миру). Аллокация пинг-понгов
  (intro — одномерный, colums×1), primary, пирамиды bloom
  (`floor(size * bloom.size / 2^i)`, 5 уровней), текстовой текстуры мира
  (нули = чистый дождь). UV-маппинг кропа: `uv_scale = viewport/world`,
  `uv_offset` с переводом в GL-координаты (v=0 — низ мира).
- `_set_static_uniforms()` — все константные униформы из конфига одним махом
  (`_set` пишет только если шейдер сохранил юниформу — moderngl выбрасывает
  неиспользуемые).
- `set_text_state(data)` — загрузка текстового слоя (grid_h × grid_w × 4 f16;
  строка 0 массива = НИЖНИЙ ряд мира). Семантика каналов:
  - **R** = индекс глифа / 255;
  - **G** = «текстовость»: 1.0 осевший текст, 0.55 скрэмбл-голова, 0.25 гаснущий
    скрэмбл;
  - **B** = окклюзия: 1.0 подавляет дождь в «кармане» вокруг сообщения.
- `resize(size, viewport)` — release всего и реаллокация (embed-окно может менять
  размер).
- `render(t, dt)` — прогон фрейм-графа (см. схему выше); в конце `swap()` всех
  пинг-понгов. `_run(prog, vao, fbo, samplers, time, extra)` — обвязка одного
  пасса (байнд текстур по юнитам, time/tick, рендер треугольника).

### Шейдеры (`renderer/shaders/`, все — порт ES 1.0 → 330 core)

- `fullscreen.vert.glsl` — треугольник на весь экран из `gl_VertexID`, отдаёт vUV.
- `intro.frag.glsl` — «первые капли на пустом экране»: R = прогресс интро-потока
  колонки; у центра и 3/4 ширины фиксированные смещения (как в оригинале), у
  остальных случайное −4..0 плюс синусоидальный провал — суммарно до −8.5.
- `raindrop.frag.glsl` — сердце дождя: R яркость капли, G флаг курсора (голова),
  B «активировано» (интро прошло), A прогресс интро. Яркость — детерминированная
  функция от (колонка, строка, время): `1 - fract(wobble((y*0.01 + columnTime) /
  raindropLength))`; курсор — там, где яркость больше, чем у соседа ниже.
  `brightnessDecay` подмешивает предыдущий кадр (глифы «зажигаются» органично).
- `symbol.frag.glsl` — какой глиф в ячейке: R индекс, G возраст; каждые
  `cycleFrameSkip` тиков возраст растёт, при ≥1 — новый случайный индекс из
  `[0, glyphSequenceLength)`.
- `effect.frag.glsl` — R мультипликативные / G аддитивные эффекты (гром, круги);
  в нашей конфигурации выключены (`hasThunder=false`, `rippleType=-1`), пасс
  оставлен для совместимости порта.
- `rain.frag.glsl` — **главный рендер-пасс**, переработан для мира/горизонтали/
  текста. `uvWorld = uvOffset + vUV*uvScale`; `simUV` — транспонирование при
  горизонтали. Каналы primary FBO: **R** дождь (позже — палитра), **G** курсор/
  скрэмбл (позже — cursorColor), **B** осевший текст (позже — textColor).
  Приоритет ячейки: kind>0.75 → текстовый глиф в B; kind>0.4 → скрэмбл-голова в G;
  kind>0.1 → гаснущий скрэмбл в R; иначе дождь: `base = raindrop.r +
  max(0, 1-raindrop.a*5)` (интро-вспышка) → contrast/brightness → effect →
  `*= raindrop.b * (1-occlusion)` — окклюзия выключает дождь в кармане текста.
  MSDF-выборка: median-of-RGB + скрин-скейл через fwidth.
- `highpass.frag.glsl` — порог яркости для bloom.
- `blur.frag.glsl` — сепарабельный гаусс; **width/height намеренно перепутаны**,
  как в оригинальном bloomPass.js (сохранено для идентичности картинки).
- `combine.frag.glsl` — сумма 5 уровней пирамиды × bloomStrength.
- `palette.frag.glsl` — финал: `brightness = primary + bloom`; дизеринг (случайное
  вычитание, прячет бандинг градиента); выход = `palette[R] +
  min(cursorColor*intensity*G, 1) + min(textColor*intensity*B, 1) + background`.
  Так текст и его свечение автоматически получают свой цвет, отличный от дождя.

---

## 8. Текстовый слой: `matrixrain/text/`

### `share.py` — `TextShare`: один мастер на мир

Процессы-рендереры независимы, но текст должен быть одинаковым во всех — фраза
может пересекать монитор. Решение:

- Файл `textstate-{W}x{H}.npy` в runtime-каталоге + lock-файл.
- `_try_become_master()` — неблокирующий `flock(LOCK_EX|LOCK_NB)`: победитель
  создаёт `TextLayer` и **сразу публикует нули** (иначе реплики показали бы фразы
  прошлой сессии на пустом экране); fd лока держится всю жизнь процесса.
- Мастер: `tick()` → при изменении массива атомарная публикация (tmp + `os.replace`);
  раз в секунду `os.utime` — heartbeat.
- Реплика: следит за mtime; файл без свежего heartbeat (>3 c) — «протухший»
  (мёртвый мастер или прошлая сессия) — не показывается, а реплика пробует сама
  стать мастером.
- `close()` — закрыть fd, **не** удалять lock-файл (свежий процесс залочил бы новый
  inode, пока старый держит прежний, — было бы два мастера).

### `feed.py` — `Feed`: заголовки из SQLite

- Источник: **любая** SQLite-база с колонкой заголовка и колонкой времени (имена
  задаются в `[feed]`); никакой базы в комплекте нет и не требуется. По умолчанию
  `db = ""` — база не настроена, показываются fallback-фразы. Строки с пустым
  временем игнорируются (`IS NOT NULL`), время читается `datetime()` SQLite.
- Запрос: `SELECT DISTINCT title … WHERE datetime(created_at) >=
  datetime('now', '-20 hours') ORDER BY created_at DESC`; база открывается
  **read-only** (`file:…?mode=ro`). Имена таблицы/колонок валидируются регэкспом
  идентификатора (защита от инъекции через конфиг).
- `_refresh()` — раз в `refresh_seconds` (3600 c — сейвер может висеть часами);
  ошибка SQLite не роняет процесс: старые заголовки остаются, ретрай через 60 c.
- `exclude` — регэкспы для отсева мусора источника (по умолчанию `^Error\s*\d`).
- Отсутствие файла базы — не ошибка: предупреждение один раз, дальше тихие ретраи
  раз в 60 c (база может появиться позже) и работа на fallback-фразах.
- `next()` — перетасованная очередь без повторов до исчерпания; при пустой базе —
  fallback-фразы («ПРОСНИСЬ», …).

### `layout.py` — нормализация и разбивка

- `_clean(text, char_map)` — верхний регистр, маппинг типографики (—, «умные»
  кавычки, × → Х), молчаливое выбрасывание символов без глифа (эмодзи просто не
  имеют записи в атласе), схлопывание пробелов.
- `_trim(text, max_length)` — обрезка по границе слова с «…».
- `prepare_lines(text, char_map, max_length, max_lines=2)` — заголовок → 1–2
  строки: перебор всех пробелов, скор = `max(len1, len2)` с тай-брейком в пользу
  более длинной первой строки. Если сбалансированного разрыва нет — **всегда две
  строки** (максимальный префикс по слову + остаток с «…»), никогда одна обрезанная
  (терялась бы половина фразы).

### `message.py` — `Message`: стейт-машина одной фразы

Состояния `REVEAL → DWELL → ERASE → DONE`; «голова» (`head`) — позиция развёртки по
конкатенации строк, скрэмбл шириной `scramble_width` бежит перед осевшим текстом.
На двухстрочном сообщении развёртка перетекает со строки 1 на строку 2 — и при
проявлении, и при стирании. Строки центрированы в блоке.

- `tick(dt)` → изменилось ли видимое состояние (DWELL почти всегда «нет» —
  экономит перезаливку текстуры).
- `_ranges()` — интервалы (осевшие, голова) в глобальных ячейках + вид головы
  (SCRAMBLE при проявлении, FADE при стирании).
- `cells(rain_sequence_length)` — генератор (row, col, kind, char|index):
  осевшие ячейки отдают символ (текст), голова — случайный матричный индекс.
- `occlusion_spans()` — построчные интервалы «кармана» (подавление дождя),
  корректно сужающиеся при стирании.
- `dwell` масштабируется длиной: `dwell + 0.055 * total` (длинные фразы читают
  дольше).

### `textstate.py` — `TextLayer`: машины → текстура

- `_activation_time(row, col, length)` — самое раннее сим-время, к которому
  интро-дождь гарантированно прорисовал все ячейки будущей фразы (выведено из
  формулы intro.frag с худшим смещением −8.5): **фразы рисуются дождём и никогда
  не появляются на чёрном поле**.
- `_place(t, block_w, n_lines)` — случайное размещение: строго внутри прямоугольника
  ОДНОГО монитора (физически невыровненные мониторы разорвали бы фразу), боковые
  поля 2 ячейки, вертикальные ~1/12 высоты, не ближе 2 строк к другим сообщениям,
  и только там, где интро уже прошло; 32 попытки, взвешенно по площади монитора.
- `_spawn(t)` — `Feed.next()` → `prepare_lines` → `_place` → `Message`.
- `tick(t, dt)` — спавн по таймеру (`interval_min..max`, не больше `max_concurrent`),
  тик машин, ре-рандомизация скрэмбла с частотой 12 Гц; при любом изменении —
  полная пересборка массива: сначала окклюзия (канал B), затем глифы (R) + уровень
  (G), с переводом «строка мира сверху-вниз» → «строка массива снизу-вверх».

---

## 9. Атласный пайплайн: `atlas/`

Оригинальный `matrixcode_msdf.png` (512×512, сетка 8×8, 64 ячейки по 64 px,
pxrange 4) **не перегенерируется** — расширяется вниз. Дождь берёт индексы
`< rain_sequence_length` (57) и до кириллицы не дотягивается; текстовый слой
адресует новые глифы (64+) напрямую через `char_map`.

### `skeletons.py` — данные шрифта

ДНК шрифта измерена по Matrix-Code.ttf: монолинейный штрих 123/1024 em, квадратные
торцы, без оптической компенсации, кривые заменены срезами 45°. Каждый глиф —
`{"w": фактор_ширины, "strokes": [полилиния, …]}` в единичном боксе (y вниз);
одноточечная полилиния — точка (увеличенный квадрат). Набор: 33 кириллицы, цифры,
14 «недостающих» латинских (остальные — `ALIASES` на кириллицу: A→А, B→В, …),
пунктуация, `«»`, `…`, валюты `$ ₽ €` (добавлены в конец `GLYPH_ORDER` — индексы
существующих глифов не сдвинулись). `char_to_glyph(ch)` — резолвер.

### `stroke_expand.py` — скелет → контуры

- Em-геометрия: unitsPerEm 1024, штрих 123, cap height 720 (не 780 — оставлен
  запас ~150 юнитов сверху и снизу, чтобы точки Ё, бреве Й и хвосты Ц/Щ не
  клипались краем 64px-ячейки).
- `_segment_contour(p1, p2)` — прямоугольник со «square caps» (концы продлены на
  полштриха); стыки заполняются перекрытием — msdfgen `-overlap` объединяет контуры.
- `shape_description(glyph)` — текстовый формат shape description msdfgen
  (собирается без SVG и без FreeType).

### `build_atlas.py`

Для каждого глифа: shape description → `msdfgen msdf -shapedesc -size 64 64
-pxrange 4 -overlap` (BMP — core-сборка msdfgen не пишет PNG) → вклейка в сетку
шириной 8 начиная с индекса 64. Выход: `assets/atlas_combined.png` (512×1088) и
`assets/atlas.json` (`{"grid": [8, rows], "char_map": {…}, "base_count": 64}`),
латинские алиасы дублируются в char_map.

### `preview.py`

CPU-декод MSDF (median-of-RGB + билинейный апсемпл) → `atlas_preview.png` —
быстрая итерация форм букв без запуска GL.

### `fetch_assets.sh`

Качает из Rezmason/matrix (MIT): оригинальный атлас в `assets/`, референсные GLSL
и regl-пассы в `vendor/rezmason/` (для диффа при порте; в гит не попадают).

---

## 10. Локер: xsecurelock + наши модули

### Почему xsecurelock

Экранный локер — код с высокой ценой ошибки (грабы, крах = разблокировка, PAM).
xsecurelock даёт проверенную обвязку: display-wide грабы, устойчивость к крашам
(упавший модуль ≠ разблокировка), спавн модулей, PAM через отдельный C-хелпер.
Мы поставляем только «вид»: SAVER (дождь) и AUTH (диалог). Небезопасный встроенный
локер (plaintext-пароль) из проекта **удалён полностью**.

### `bin/matrix-lock`

Настраивает окружение и `exec xsecurelock`:

- `XSECURELOCK_SAVER` / `XSECURELOCK_AUTH` — наши обёртки (абсолютные пути
  допустимы). Мультимонитор автоматический: глобальный saver xsecurelock — это
  multiplexer, запускающий наш saver на каждый монитор.
- `XSECURELOCK_AUTHPROTO=authproto_pam`, `XSECURELOCK_PAM_SERVICE=xsecurelock`
  (нужен `/etc/pam.d/xsecurelock` — шаблон в `xsecurelock/pam.d/`, делегирует в
  `@include common-auth` — разблокировка **системным паролем**).
- `XSECURELOCK_SAVER_RESET_ON_AUTH_CLOSE=0` — иначе xsecurelock шлёт saver'ам
  SIGUSR1 (конфликт с нашей семантикой сигналов; embed их игнорирует).
- `XSECURELOCK_DISCARD_FIRST_KEYPRESS=0` — **критично**: без этого терялась бы и
  первая печатная клавиша (см. ниже).
- `XSECURELOCK_BLANK_TIMEOUT=-1` — не гасить экран отдельным чёрным слоем.
- `--daemon` — печатает готовую команду `xss-lock` для автолока по простою.

### Обёртки `xsecurelock/{saver,auth}_matrixrain`

Bash: `exec 2>>$XDG_RUNTIME_DIR/matrix-rain-{saver,auth}.log` (xsecurelock глотает
stderr модулей — без этого краш Python был бы невидим), затем `exec
.venv/bin/python -m matrixrain --embed-window $XSCREENSAVER_WINDOW` (saver) или
`-m matrixrain.lock.run_auth` (auth). `MATRIXRAIN_CONFIG` пробрасывается.

### Поток управления AUTH-модуля

xsecurelock спавнит AUTH-модуль на **любой** ввод — клавишу или простое движение
мыши — и пересылает нажатия в его stdin (UTF-8 байты). Выход 0 = разблокировка.

**Фундаментальное ограничение (выяснено по исходникам xsecurelock 1.5.1,
`auth_child.c:149`):** *разбудившее* нажатие пересылается свежезапущенному
auth-ребёнку только если `DISCARD_FIRST_KEYPRESS=0` **и** символ печатный
(`ContainsNonControl`: байт > 0x1f и ≠ 0x7f). **Esc (0x1b) — управляющий и
отбрасывается всегда**; движение мыши не даёт байтов вовсе. Поэтому «открыть
диалог по Esc» физически невозможно — принятая модель:

> **Диалог открывается, когда пользователь начинает печатать пароль.** Первая
> печатная клавиша надёжно доходит (проверено 4/4), открывает диалог и становится
> первым символом пароля. Мышь (0/4) и Esc диалог не открывают — дождь просто идёт.
> Esc **по уже открытому** диалогу закрывает его. Нет ввода `idle_timeout` (45 c)
> — модуль тихо выходит (код 1), экран не менялся.

### `lock/run_auth.py` — entry point

- `_log_crash(msg)` — трейсбек в `$XDG_RUNTIME_DIR/matrix-rain/auth.log`
  (переопределяется `MATRIXRAIN_AUTH_LOG`); любой `BaseException` в `main()` →
  лог + код 1 (экран остаётся заблокированным).
- `_middle_monitor()` — монитор, средний по горизонтальному центру (сортировка по
  `x + width/2`) — на нём рисуется диалог; при 1–2 мониторах формула корректно
  выбирает единственный/правый.
- `_placement()` — где рисовать диалог. Предпочтительно — **ребёнком saver-окна**,
  накрывающего центр среднего монитора (`savermap.find_covering`, ретраи до 1.5 c —
  сразу после (пере)создания saver'а регистрации может ещё не быть): под
  композитором (picom) новорождённое top-level окно может не попасть в композицию
  (невидимо, хотя X считает его viewable), а saver-окна композитятся — ребёнок
  наследует слой. Fallback — top-level окно по центру монитора. Координаты
  переводятся в систему родителя.
- `main()` — конфиг → `_placement()` → `authmod.run(cfg, parent, rect,
  freeze=FreezeWriter(), wake_on_key, idle_exit)`.

### `lock/authmod.py` — ядро аутентификации

- `find_authproto()` — поиск `authproto_pam`: `XSECURELOCK_AUTHPROTO_HELPER` →
  перебор дистро-каталогов (`/usr/libexec/xsecurelock` на Debian,
  `/usr/lib/xsecurelock[/helpers]`, `/usr/local/...`) → `which`.
- **`KeyStream`** — декодер stdin: читает доступные байты, разбивает на события
  `('char', ch) | ('submit'|'backspace'|'cancel'|'clear', None) | ('eof', None)`.
  Корректно копит незавершённый multibyte-хвост UTF-8 между чтениями (кириллица
  режется на границе read); Enter/CR → submit, BS/DEL → backspace, Esc → cancel,
  Ctrl-U → clear.
- `_wait_for_key(keys, idle_exit)` — **gate**: select-цикл до первого ввода;
  события `cancel` (Esc) отбрасываются — живой от предыдущего касания модуль мог
  получить Esc, и открытый им диалог тем же событием мгновенно закрылся бы
  (симптом «открывает и сразу закрывает»). Возвращает первый батч событий или
  None (timeout / EOF).
- **`AuthProtoSession`** — одна PAM-попытка: спавн хелпера, `PacketReader` на его
  stdout; `pump()` — обработка пакетов (P → ждём пароль; U → отвечаем `$USER` сами;
  e → текст ошибки); `send_response(password)` — bytearray пишется в хелпер
  напрямую; `poll_result()` — **exit-статус хелпера — единственная истина**
  (0 = аутентифицирован); `cancel()`, `close()`.
- **Зануление пароля**: пароль — `bytearray` (не str!); `_wipe(buf)` зануляет
  байты и очищает; `_utf8_backspace(buf)` удаляет последний целый UTF-8 символ
  (поиск lead-байта). Wipe при clear/submit/denied и в finally. Best-effort
  (Python не гарантирует отсутствие копий), но оригинал не живёт в куче вечно,
  как жила бы str.
- **`run(cfg, parent_window, center_rect, freeze=None, wake_on_key=True,
  idle_exit=45.0)`** — главный цикл:
  1. gate (если `wake_on_key`); None → выход 1;
  2. `LockDialog` + `freeze.set()` (дождь замирает);
  3. начальные события gate проигрываются через `handle_events` — первый символ
     уже в пароле;
  4. select-цикл 60 Гц: stdin (клавиши → пароль/диалог; Esc → выход 1; ввод во
     время красной вспышки игнорируется), stdout хелпера (pump), poll_result
     (True → выход 0; False → `dialog.set_error()` — красная вспышка, wipe,
     новый хелпер после вспышки), `freeze.refresh()`, `dialog.raise_window()` +
     `render()`;
  5. finally: wipe, cancel+close сессии, `freeze.clear()`, `dialog.close()`.

### `lock/authproto.py` — wire-протокол

Формат пакета: `<ptype> <SPC> <десятичная длина> <NL> <тело> <NL>`
(из `helpers/authproto.h`). Типы: `i`/`e` info/error, `U`/`P` запрос
логина/пароля, `u`/`p`/`x` ответы/отмена.

- `write_packet(fd, ptype, message)` — принимает str **или bytes/bytearray**:
  байтовое тело пишется через `memoryview` без промежуточных копий — вызывающий
  может занулить оригинал (путь пароля).
- `PacketReader` — неблокирующий буферизованный ридер для select-цикла: fd
  переводится в `O_NONBLOCK` (иначе буфер рассинхронизируется с тем, что видит
  select), `poll()` дренирует всё доступное и возвращает список полных пакетов,
  неполный остаётся в буфере; `read()` — блокирующий вариант для тестов.

### `lock/freeze.py` — заморозка дождя

Auth и saver — независимые процессы без общего родителя, сигналов нет. Флаг —
файл `$XDG_RUNTIME_DIR/matrix-rain/freeze`:

- `FreezeWriter.set()/refresh()` (атомарный touch не чаще 1 Гц), `clear()`.
- `is_frozen()` на стороне saver'а: свежесть mtime ≤ 4 c — упавший auth никогда
  не оставит дождь замороженным навсегда.

### `lock/savermap.py` — реестр saver-окон

- `SaverRegistration(window_id, rect)` — файл `savers/saverwin-PID.json`
  (`window`, `rect`, `ts`), refresh не чаще 1 Гц, `close()` удаляет.
- `find_covering(x, y)` — свежайшая (ts, < 5 c) ЖИВАЯ регистрация, чей rect
  накрывает точку; живость проверяется `get_attributes` (BadWindow = мёртвое окно —
  xsecurelock пересоздаёт saver'ы, и диалог-ребёнок мёртвого окна был бы невидим).

### `matrixrain/lockui.py` — `LockDialog`

Диалог «как в фильме»: узкая почти белая рамка вплотную вокруг светящегося
зелёного «SYSTEM FAILURE», под ним только ввод пароля — маска случайными
матричными глифами + мигающий курсор. Никакого другого текста.

- Геометрия выводится из тайтла (TITLE_CELL 44 px, spacing 1.15); `dialog_size()`
  — размер окна для решений о размещении. PAD 104 — запас, чтобы свечение мягко
  гасло внутри окна; FRAME_INSET 60 — внешняя светящаяся рамка всего окна.
- Окно: `GLWindow(..., argb=False, fill_parent=False)` — непрозрачный чёрный фон
  (решение пользователя; ARGB-механизм в glx.py сохранён, но не используется),
  ребёнок saver-окна в точке центрирования.
- Пайплайн: сцена в FBO (инлайновые шейдеры `_TEXT_VERT`/`_TEXT_FRAG`: пиксельные
  координаты y-вниз, MSDF-глифы или `solid`-прямоугольники) → **тот же bloom, что
  у дождя** (highpass → пирамида 5 уровней H/V blur → combine, переиспользованы
  файлы шейдеров рендерера) → `_FINAL_FRAG` (scene + glow; для ARGB-случая
  premultiplied: rgb>alpha работает аддитивно у композитора).
- Ввод: `add_char()` (маска ≤ 16 глифов — длина пароля не раскрывается),
  `backspace()`, `clear()`; `set_error()` — вся рамка и текст вспыхивают красным
  на 1.2 c (без надписей), ввод в это время игнорируется; `in_error`.
- `render()` — рамки (`_rect_outline`), чёрная плашка бокса, тайтл, маска, курсор
  (мигание 2.4 Гц), bloom, композит; `raise_window()` — над замороженным дождём.

### Гарантии и ограничения безопасности

- Грабы, обработка крашей, «модуль умер ≠ разблокировка» — на стороне xsecurelock
  (проверенный код, GPL/Apache, не наш).
- Пароль: только транзитом bytearray → authproto_pam (C-хелпер) → PAM;
  в конфиге/логах паролей нет; зануление после каждого использования.
- Разбудившая клавиша становится частью пароля — это **дизайн xsecurelock**
  (`DISCARD_FIRST_KEYPRESS=0` документированно ведёт себя так); первый символ
  виден в маске диалога.
- **Известная дыра (осознанно отложена):** переключение VT (Ctrl+Alt+F2) обходит
  любой X-локер. Закрывается `DontVTSwitch` в xorg.conf или setuid-хелпером с
  `VT_LOCKSWITCH`. Запланировано следующим шагом.

---

## 11. Данные времени выполнения

Каталог `$XDG_RUNTIME_DIR/matrix-rain/` (fallback `/tmp/matrix-rain-<uid>`):

| Файл | Писатель | Читатель | TTL/семантика |
|---|---|---|---|
| `textstate-WxH.npy` | текст-мастер | реплики | heartbeat 1 c, протухание 3 c |
| `textstate-WxH.lock` | flock-выборы | — | держится fd, не удаляется |
| `freeze` | auth-модуль | saver'ы | touch 1 Гц, протухание 4 c |
| `savers/saverwin-PID.json` | saver'ы | auth-модуль | refresh 1 Гц, протухание 5 c |
| `auth.log` | run_auth (крэши) | человек | append |
| `../matrix-rain-{auth,saver}.log` | stderr обёрток | человек | append |

Все записи атомарны (tmp + `os.replace`); все флаги — с TTL, чтобы упавший процесс
не оставлял вечного мусора. Никакой сети ни в одном процессе.

---

## 12. Установка и запуск

### `install.sh` (идемпотентен)

1. Поиск python 3.11+ (3.13 → 3.11, затем системный python3, если ≥3.11).
2. Проверка cmake/g++/make/curl/git с подсказками `apt install`.
3. venv + `pip install -r requirements.txt`.
4. Сборка **msdfgen core-only** (без Skia/FreeType/vcpkg — нам хватает shape
   descriptions) в `build/msdfgen/bin/msdfgen`.
5. `atlas/fetch_assets.sh` — оригинальный атлас + референсы.
6. `atlas/build_atlas.py` — комбинированный атлас.

### Команды

```bash
.venv/bin/python -m matrixrain --standalone     # сейвер на все мониторы
bin/matrix-lock                                  # заблокировать сейчас
bin/matrix-lock --daemon                         # команда для xss-lock (автолок)
sudo install -m 644 xsecurelock/pam.d/xsecurelock /etc/pam.d/xsecurelock  # PAM
```

---

## 13. Ключевые инженерные решения (и почему)

1. **Мир как чистая функция (grid, t)** — вместо обмена кадрами между процессами.
   Достаточно одинаковых (world, t0, конфиг) — и N процессов рисуют один дождь.
   Под xsecurelock, где супервизора нет, t0 квантуется wall-clock'ом по 5 минут.
2. **Один код-путь окна для standalone и embed** — своё окно с GLX-визуалом
   всегда; чужое окно только родитель (его визуал может не подходить GL).
3. **Текст-мастер по flock** — работает одинаково под нашим launcher'ом и под
   saver_multiplex; смерть мастера лечится протуханием heartbeat.
4. **Диалог — ребёнок saver-окна** — единственный найденный способ гарантированной
   видимости под picom: новорождённые top-level окна во время лока композитор
   может не подхватить, а saver-слой уже композитится.
5. **Файловые флаги с TTL вместо сигналов** — у auth и saver нет общего предка;
   SIGUSR1 занят самим xsecurelock; протухание страхует от крашей.
6. **`ContainsNonControl` и судьба Esc** — «открытие по Esc» невозможно без
   пересборки xsecurelock; UX «начни печатать — окно всплыло» и надёжен
   (4/4 против 0/4 у Esc), и удобнее: первый символ не пропадает.
7. **bytearray-пароль + memoryview-запись** — единственный способ в Python хоть
   как-то контролировать время жизни плейнтекста в памяти.
8. **Интро-гейт для текста** (`_activation_time`) — фразы появляются только там,
   где дождь уже «прошёл», сохраняя иллюзию «дождь печатает текст».
9. **Атлас расширяется, не пересобирается** — оригинальные 64 ячейки нетронуты,
   дождь ограничен `rain_sequence_length=57`, поэтому апстрим-совместимость
   полная, а кириллица адресуется только текстовым слоем.
10. **Крэш-логи everywhere** — xsecurelock глотает stderr модулей; каждая обёртка
    и entry point пишут в свой файл, иначе «диалог не появился» недиагностируем.

---

## 14. Статус и что осталось

**Готово и проверено вживую:** порт всего пайплайна (intro/raindrop/symbol/effect/
rain/bloom/palette), собственная кириллица (75+ глифов), горизонтальный единый
дождь на 3 монитора, текстовый слой с карманами и двухстрочной разбивкой,
SQLite-фид с часовым обновлением, standalone-сейвер с грабами, локер
xsecurelock+PAM с диалогом SYSTEM FAILURE, заморозкой дождя, занулением пароля и
надёжным открытием по первой печатной клавише.

**Осталось:**

1. **VT-switch (Ctrl+Alt+F2)** — закрыть дыру (`DontVTSwitch` / VT_LOCKSWITCH);
   следующий шаг по плану.
2. **Тесты** — нет автоматического набора тестов в репозитории (проверки
   выполнялись вручную и скриптами вне дерева).
3. **Дистрибуция** — прогнать install.sh с нуля на чистой машине, финализировать
   README для чужого X11-окружения.

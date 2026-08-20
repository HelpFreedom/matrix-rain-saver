# Установка и настройка

Подробное руководство. Краткая версия — в [README](../README.md).
[English version →](INSTALL.en.md)

---

## 1. Требования

| Компонент | Требование | Зачем |
|---|---|---|
| ОС | Linux с **X11** | Оконный слой построен на Xlib/RandR/GLX |
| Сервер | Любой WM или без него | Окна создаются `override-redirect` — WM их не трогает |
| GPU | OpenGL **3.3 core** | Весь рендер — шейдерный |
| Python | **3.11+** | Используется `tomllib` из стандартной библиотеки |
| Сборка | `cmake`, `g++`, `make`, `curl`, `git` | Компиляция msdfgen (генератор атласа глифов) |
| Локер | `xsecurelock`, `xss-lock` | Перехват ввода и проверка пароля через PAM |

> **Wayland не поддерживается.** Проект использует X11-специфичные механизмы
> (override-redirect окна, RandR, GLX, display-wide грабы ввода).

### Установка зависимостей системы

**Debian / Ubuntu / Mint:**

```sh
sudo apt update
sudo apt install python3.11 python3.11-venv cmake g++ make curl git \
                 libx11-dev libgl1-mesa-dev
# для локера:
sudo apt install xsecurelock xss-lock
```

**Fedora:**

```sh
sudo dnf install python3.11 cmake gcc-c++ make curl git \
                 libX11-devel mesa-libGL-devel
sudo dnf install xsecurelock xss-lock
```

**Arch:**

```sh
sudo pacman -S python cmake gcc make curl git libx11 mesa
sudo pacman -S xsecurelock xss-lock
```

### Проверка перед установкой

```sh
python3 --version              # нужно 3.11 или новее
glxinfo -B | grep "OpenGL core profile version"   # нужно 3.3+
echo $XDG_SESSION_TYPE         # должно быть x11 (не wayland)
```

---

## 2. Быстрая установка

```sh
git clone https://github.com/HelpFreedom/matrix-rain-saver.git
cd matrix-rain-saver
./install.sh
```

Скрипт идемпотентен — его можно запускать повторно, ничего не сломается.

### Что делает `install.sh`

1. **Ищет Python 3.11+** — перебирает `python3.13`, `python3.12`, `python3.11`,
   затем системный `python3`, если он достаточно новый.
2. **Проверяет** наличие `cmake`, `g++`, `make`, `curl`, `git` и подсказывает
   команду установки, если чего-то нет.
3. **Создаёт venv** в `.venv/` и ставит зависимости из `requirements.txt`
   (moderngl, numpy, python-xlib, Pillow, wcwidth).
4. **Собирает msdfgen** в `build/` — в режиме core-only, без Skia и FreeType
   (проекту нужен только генератор MSDF из описания контуров).
5. **Скачивает** оригинальный матричный MSDF-атлас из
   [Rezmason/matrix](https://github.com/Rezmason/matrix) в `assets/`
   (в репозитории он не хранится).
6. **Генерирует** объединённый атлас `assets/atlas_combined.png` — оригинальные
   матричные глифы плюс сгенерированная кириллица.

### Проверка, что всё встало

```sh
.venv/bin/python -m matrixrain --geometry 800x600+100+100 --timeout 10
```

Должно появиться окно 800×600 с дождём и через 10 секунд закрыться.

---

## 3. Ручная установка

Если `install.sh` не подошёл (нестандартный дистрибутив, свой msdfgen, offline):

```sh
# 1. venv и зависимости
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. msdfgen (core-only) — если у вас его ещё нет
git clone --depth 1 https://github.com/Chlumsky/msdfgen.git build/msdfgen-src
cmake -S build/msdfgen-src -B build/msdfgen-build \
      -DCMAKE_BUILD_TYPE=Release -DMSDFGEN_CORE_ONLY=ON \
      -DMSDFGEN_BUILD_STANDALONE=ON -DMSDFGEN_USE_VCPKG=OFF \
      -DMSDFGEN_USE_SKIA=OFF -DMSDFGEN_DISABLE_SVG=ON
cmake --build build/msdfgen-build -j$(nproc)
mkdir -p build/msdfgen/bin
cp $(find build/msdfgen-build -name msdfgen -type f -perm -u+x | head -1) build/msdfgen/bin/

# 3. Оригинальный атлас
bash atlas/fetch_assets.sh

# 4. Объединённый атлас с кириллицей
.venv/bin/python atlas/build_atlas.py
```

Без атласа проект тоже запустится — дождь будет идти на оригинальных матричных
глифах, но кириллические заголовки показать будет нечем.

---

## 4. Запуск скринсейвера

```sh
# Все мониторы; выход по любой клавише или заметному движению мыши
.venv/bin/python -m matrixrain --standalone

# Одно окно заданной геометрии — удобно для подбора настроек
.venv/bin/python -m matrixrain --geometry 1920x1080+0+0

# Автовыход через N секунд (для тестов)
.venv/bin/python -m matrixrain --standalone --timeout 30
```

### Все флаги

| Флаг | Назначение |
|---|---|
| `--standalone` | Супервизор: по процессу-рендереру на монитор, выход по любому вводу |
| `--geometry WxH+X+Y` | Одно окно указанной геометрии |
| `--embed-window ID` | Рисовать внутрь чужого окна (так работает saver-модуль xsecurelock) |
| `--config ПУТЬ` | Свой файл конфигурации |
| `--monitor ИМЯ` | Имя монитора RandR для секции `[monitor.<имя>]` |
| `--timeout N` | Завершиться через N секунд |

### Автозапуск по простою (без блокировки)

```sh
xset s 600      # считать простоем 10 минут бездействия
xss-lock -- /полный/путь/matrix-rain-saver/.venv/bin/python -m matrixrain --standalone
```

Добавьте обе строки в `~/.xinitrc`, `~/.xprofile` или в автозапуск вашего WM.

---

## 5. Локер

### Разовая настройка

```sh
# 1. Сам xsecurelock
sudo apt install xsecurelock xss-lock

# 2. PAM-сервис: разрешает разблокировку системным паролем
sudo install -m 644 xsecurelock/pam.d/xsecurelock /etc/pam.d/xsecurelock
```

Файл PAM-сервиса состоит из двух строк `@include common-auth` и
`@include common-account` — то есть делегирует проверку той же системной цепочке,
что и обычный вход. Никаких паролей проект не хранит.

> На Fedora/Arch имена включаемых файлов другие (`system-auth` вместо
> `common-auth`). Отредактируйте `/etc/pam.d/xsecurelock` соответственно.

### Блокировка

```sh
bin/matrix-lock            # заблокировать прямо сейчас
bin/matrix-lock --daemon   # напечатает команды для автоблокировки по простою
```

### Как это выглядит в работе

1. Экран блокируется, на всех мониторах идёт дождь.
2. Движение мыши ничего не меняет — дождь продолжается.
3. **Как только вы начинаете печатать пароль**, появляется окно `SYSTEM FAILURE`;
   первая нажатая буква уже учтена как первый символ пароля. Дождь замирает.
4. `Enter` — проверка пароля. Неверный — красная вспышка рамки, ввод сбрасывается.
5. `Esc` — закрыть окно и вернуться к дождю (экран остаётся заблокированным).
6. Если ничего не печатать 45 секунд (`[lock] idle_timeout`), окно не появляется
   вовсе и всё возвращается к дождю.

### Автоблокировка по простою

```sh
xset s 600
xss-lock -- /полный/путь/matrix-rain-saver/bin/matrix-lock
```

Именно `bin/matrix-lock`, а не `xsecurelock` напрямую: скрипт выставляет переменные
окружения, без которых поведение будет другим.

---

## 6. Настройка

```sh
mkdir -p ~/.config/matrix-rain
cp config/default.toml ~/.config/matrix-rain/config.toml
```

Ваш файл накладывается поверх встроенных значений — можно оставить в нём только
изменённые ключи. Порядок слоёв:

```
встроенные значения  →  ~/.config/matrix-rain/config.toml  →  [monitor.<имя>]  →  флаги CLI
```

### Частые правки

**Классический вертикальный дождь:**

```toml
[rain]
direction = "vertical"
```

**Крупнее/мельче глифы** (это же — «размер шрифта»):

```toml
[glyphs]
cell_size = 26     # по умолчанию 20 пикселей на ячейку
```

**Другая палитра:**

```toml
[palette]
preset = "amber"   # classic-green | amber | ice-blue | red | custom
```

**Свои цвета:**

```toml
[palette]
preset = "custom"
text_color = [0.2, 0.9, 1.0]      # цвет осевших заголовков

[palette.custom]
stops = [                          # градиент яркости дождя: [позиция, R, G, B]
    [0.00, 0.0, 0.0, 0.0],
    [0.50, 0.1, 0.4, 0.5],
    [1.00, 0.7, 1.0, 1.0],
]
```

**Кириллица прямо в дожде** (а не только в заголовках):

```toml
[glyphs]
rain_sequence_length = 96   # по умолчанию 57 — только оригинальные матричные глифы
```

**Разные настройки для разных мониторов** (имена — как в `xrandr`):

```toml
[monitor.DP-2]
cell_size = 16        # на портретном мониторе глифы мельче
```

**Дискретная видеокарта на гибридной графике:**

```toml
[display]
env = { DRI_PRIME = "1" }
```

**Слабая машина:**

```toml
[display]
fps = 30
[bloom]
strength = 0.0     # полностью отключить пасс свечения
```

---

## 7. Свои заголовки из базы

Проект читает **любую** SQLite-базу — своей не поставляет. Нужны колонка с текстом
и колонка со временем.

```toml
[feed]
db = "~/.local/share/matrix-rain/headlines.db"
db_table = "posts"
db_title_column = "title"
db_time_column = "created_at"
window_hours = 20          # показывать записи за последние 20 часов
refresh_seconds = 3600     # перечитывать базу раз в час
db_time_local = false      # true, если время в базе локальное, а не UTC
exclude = ["^Error\\s*\\d"]  # регэкспы для отсева мусора
```

Создать простую базу для проверки:

```sh
mkdir -p ~/.local/share/matrix-rain
sqlite3 ~/.local/share/matrix-rain/headlines.db <<'SQL'
CREATE TABLE posts (title TEXT, created_at TEXT);
INSERT INTO posts VALUES ('ПЕРВЫЙ ЗАГОЛОВОК',  datetime('now'));
INSERT INTO posts VALUES ('ВТОРОЙ ЗАГОЛОВОК',  datetime('now','-2 hours'));
SQL
```

Требования к данным:

- Время должно читаться функцией SQLite `datetime()` — подойдут
  `2026-08-20 09:15:00` и ISO-8601. Строки с пустым временем игнорируются.
- База открывается **только на чтение**, изменения в неё не вносятся.
- Если базы нет или она пуста — показываются `fallback`-фразы из конфигурации.

---

## 8. Свой шрифт

Начертания заданы осевыми ломаными в [`atlas/skeletons.py`](../atlas/skeletons.py):
координаты в единичном квадрате, `y` растёт вниз. Толщина штриха, высота прописных
и ширина буквы — в [`atlas/stroke_expand.py`](../atlas/stroke_expand.py).

```sh
# Быстрый просмотр без запуска GL -> assets/atlas_preview.png
.venv/bin/python atlas/preview.py "ПРОВЕРКА 123"

# Пересобрать атлас после правок
.venv/bin/python atlas/build_atlas.py
```

Новые символы добавляйте **в конец** списка `GLYPH_ORDER` — тогда индексы уже
существующих глифов не сдвинутся.

---

## 9. Диагностика

### Логи

xsecurelock скрывает вывод своих модулей, поэтому обёртки пишут его в файлы:

```sh
$XDG_RUNTIME_DIR/matrix-rain-saver.log    # вывод saver-модуля (дождь)
$XDG_RUNTIME_DIR/matrix-rain-auth.log     # вывод auth-модуля (диалог пароля)
$XDG_RUNTIME_DIR/matrix-rain/auth.log     # трассировки падений auth-модуля
```

Обычно это `/run/user/1000/…`.

### Типичные проблемы

**`no matching GLXFBConfig` / `failed to create GL 3.3 core context`**
Драйвер не даёт OpenGL 3.3 core. Проверьте `glxinfo -B`. На гибридной графике
попробуйте `[display] env = { DRI_PRIME = "1" }`.

**`cannot open X display`**
Не задан `DISPLAY` или вы в Wayland-сессии. Проверьте: `echo $DISPLAY` и
`echo $XDG_SESSION_TYPE`.

**`no monitors reported by RandR`**
Драйвер не отдаёт мониторы через RandR. Обойти можно явной геометрией:
`--geometry 1920x1080+0+0`.

**Дождь идёт, но заголовков нет**
Не собран объединённый атлас — запустите `.venv/bin/python atlas/build_atlas.py`.
Проверьте, что существует `assets/atlas_combined.png` и `assets/atlas.json`.

**Локер: `xsecurelock not found`**
`sudo apt install xsecurelock xss-lock`.

**Локер: пароль не принимается**
Не установлен PAM-сервис или в нём чужие имена файлов. Проверьте
`/etc/pam.d/xsecurelock`; на Fedora/Arch замените `common-auth` на `system-auth`.

**Локер: `authproto_pam helper not found`**
Хелпер лежит в другом каталоге. Найдите его и укажите явно:

```sh
find /usr -name authproto_pam 2>/dev/null
XSECURELOCK_AUTHPROTO_HELPER=/путь/к/authproto_pam bin/matrix-lock
```

**Окно пароля не появляется**
Оно и не должно появляться от мыши или `Esc` — начните печатать пароль
(см. раздел «Локер» в [README](../README.md)).

---

## 10. Обновление и удаление

**Обновление:**

```sh
git pull
./install.sh     # доставит новые зависимости и пересоберёт атлас при необходимости
```

**Удаление:** проект не устанавливает ничего вне своего каталога, кроме двух
необязательных вещей:

```sh
rm -rf /путь/к/matrix-rain-saver      # сам проект вместе с venv и сборкой
rm -rf ~/.config/matrix-rain          # ваша конфигурация
sudo rm -f /etc/pam.d/xsecurelock     # PAM-сервис локера, если он больше не нужен
```

Временные файлы в `$XDG_RUNTIME_DIR/matrix-rain/` исчезают сами при перезагрузке.

# Сборка в один EXE-файл

Проект **VCS Recording Auto-Mover** можно скомпилировать в полностью самодостаточный один исполняемый файл (`vcrs.exe`) с помощью [PyInstaller](https://pyinstaller.org/).

## Требования

- Python 3.11+
- Windows (для сборки EXE)

## Подготовка

1. Установите зависимости проекта и PyInstaller:

```powershell
pip install -r requirements.txt
pip install pyinstaller
```

## Сборка (рекомендуемые команды)

### Вариант 1 — Простая команда (CLI)

В корне проекта выполните:

```powershell
pyinstaller --onefile --noconsole --name vcrs --clean main.py
```

### Вариант 2 — Через spec-файл (рекомендуется)

```powershell
pyinstaller --clean main.spec
```

Spec-файл уже настроен на:
- один файл (`onefile`)
- без консоли
- имя `vcrs`
- необходимые скрытые импорты (`pystray`, `boto3`, `botocore`, `s3transfer`)

## Результат сборки

После завершения в папке `dist` появится:

```
dist/vcrs.exe
```

Это **один** файл (~25–30 МБ), который можно запускать на любой Windows-машине без Python и зависимостей.

## Распространение

Достаточно передать только `vcrs.exe`.

При первом запуске приложение автоматически создаст:

```
%USERPROFILE%\.vcs_automover\
├── config.json
└── logs\
```

## Важные особенности для собранного EXE

- Функция **"Запускать при старте Windows"** работает корректно (в UI регистрируется сам `vcrs.exe`, а не python + main.py).
- Приложение не показывает чёрное консольное окно.
- Логи и настройки хранятся в профиле пользователя (как и при запуске из исходников).

## Дополнительные опции PyInstaller

| Флаг                    | Описание                              |
|-------------------------|---------------------------------------|
| `--onefile` / `-F`      | Собрать в один exe-файл               |
| `--noconsole` / `-w`    | Без консольного окна (GUI)            |
| `--clean`               | Очистить кэш перед сборкой            |
| `--name vcrs`           | Задать имя выходного файла            |
| `--hidden-import=xxx`   | Добавить скрытый импорт при ошибках   |
| `--upx-dir`             | Сжатие exe с помощью UPX (опционально)|

## Очистка после сборки

```powershell
# PowerShell
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
```

## Возможные проблемы

- **Pystray / tray иконка не работает** — добавьте в команду: `--hidden-import pystray._win32`
- **Ошибки импорта watchdog** — добавьте: `--hidden-import watchdog.observers.winapi`
- Для отладки соберите с консолью (уберите `--noconsole`) и смотрите вывод.

## Пример полной команды с доп. импортами

```powershell
pyinstaller --onefile --noconsole --name vcrs --clean `
  --hidden-import pystray._win32 `
  --hidden-import pystray._base `
  main.py
```

Готово! Теперь у вас есть один `vcrs.exe`, который можно запускать и распространять.

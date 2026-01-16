@echo off
REM install_coingecko.cmd
REM Скрипт установки CoinGecko интеграции для Windows

echo ============================================
echo    Установка CoinGecko интеграции
echo ============================================
echo.

REM Проверить что мы в правильной папке
if not exist "backend\" (
    echo ОШИБКА: Запустите скрипт из корня проекта crypto-screener-bybit!
    echo Текущая папка: %CD%
    pause
    exit /b 1
)

echo [1/6] Остановка контейнеров...
docker-compose down

echo.
echo [2/6] Создание папок...
if not exist "migrations\" mkdir migrations

echo.
echo [3/6] Обновление .env файла...
if not exist ".env" (
    echo Создаю .env из .env.example...
    copy .env.example .env
)

echo.
echo ВНИМАНИЕ: Откройте .env файл и добавьте свой COINGECKO_API_KEY
echo.
echo Нажмите любую клавишу когда добавите ключ, или Ctrl+C для отмены
pause

echo.
echo [4/6] Проверка файлов...

if not exist "backend\config.py" (
    echo ОШИБКА: Не найден backend\config.py
    echo Скопируйте файл config.py в папку backend\
    pause
    exit /b 1
)

if not exist "backend\screener\coingecko.py" (
    echo ОШИБКА: Не найден backend\screener\coingecko.py
    echo Скопируйте файл coingecko.py в папку backend\screener\
    pause
    exit /b 1
)

if not exist "migrations\001_add_coingecko_tables.sql" (
    echo ОШИБКА: Не найден migrations\001_add_coingecko_tables.sql
    echo Скопируйте файл coingecko_schema.sql в папку migrations\001_add_coingecko_tables.sql
    pause
    exit /b 1
)

if not exist "apply_migrations.sh" (
    echo ОШИБКА: Не найден apply_migrations.sh
    echo Скопируйте файл apply_migrations.sh в корень проекта
    pause
    exit /b 1
)

if not exist "Dockerfile.backend" (
    echo ОШИБКА: Не найден Dockerfile.backend
    echo Скопируйте файл Dockerfile.backend в корень проекта
    pause
    exit /b 1
)

echo ✅ Все файлы на месте

echo.
echo [5/6] Пересборка Docker образов...
docker-compose build

echo.
echo [6/6] Запуск контейнеров...
docker-compose up -d

echo.
echo ============================================
echo    Установка завершена!
echo ============================================
echo.
echo Проверьте логи:
echo    docker-compose logs -f backend
echo.
echo Проверьте статус синхронизации:
echo    Откройте: http://localhost:8000/api/status
echo.
echo При возникновении проблем - смотрите INSTALL_COINGECKO.md
echo.
pause

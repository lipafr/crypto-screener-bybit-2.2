# ============================================
# Crypto Screener - Makefile
# ============================================
# Удобные команды для управления проектом

.PHONY: help build up down restart logs logs-backend logs-frontend status clean test backup

# ============================================
# Help
# ============================================
help:
	@echo "======================================"
	@echo "Crypto Screener - Доступные команды:"
	@echo "======================================"
	@echo ""
	@echo "  make build         - Собрать Docker образы"
	@echo "  make up            - Запустить контейнеры"
	@echo "  make down          - Остановить контейнеры"
	@echo "  make restart       - Перезапустить контейнеры"
	@echo "  make logs          - Показать все логи"
	@echo "  make logs-backend  - Показать логи backend"
	@echo "  make logs-frontend - Показать логи frontend"
	@echo "  make status        - Показать статус контейнеров"
	@echo "  make clean         - Удалить контейнеры и volumes"
	@echo "  make backup        - Создать бэкап БД"
	@echo "  make shell         - Открыть shell в backend контейнере"
	@echo "  make test-telegram - Отправить тестовое уведомление"
	@echo ""

# ============================================
# Docker Operations
# ============================================

# Сборка образов
build:
	docker-compose build

# Запуск контейнеров
up:
	docker-compose up -d

# Остановка контейнеров
down:
	docker-compose down

# Перезапуск
restart:
	docker-compose restart

# Пересборка и запуск
rebuild:
	docker-compose up -d --build

# ============================================
# Logs
# ============================================

# Все логи (follow mode)
logs:
	docker-compose logs -f

# Backend логи
logs-backend:
	docker-compose logs -f backend

# Frontend логи
logs-frontend:
	docker-compose logs -f frontend

# Последние N строк логов
logs-tail:
	docker-compose logs --tail=100

# ============================================
# Status & Monitoring
# ============================================

# Статус контейнеров
status:
	docker-compose ps

# Статистика ресурсов
stats:
	docker stats crypto_screener_backend crypto_screener_frontend

# Health check
health:
	@echo "Checking backend health..."
	@curl -s http://localhost:8000/health | python -m json.tool || echo "❌ Backend не доступен"
	@echo ""
	@echo "Checking frontend..."
	@curl -s -o /dev/null -w "Frontend: %%{http_code}\n" http://localhost:3000

# ============================================
# Maintenance
# ============================================

# Очистка (ОСТОРОЖНО - удалит данные!)
clean:
	docker-compose down -v
	@echo "⚠️  Volumes удалены! БД и логи потеряны!"

# Удалить только контейнеры (сохранить данные)
clean-containers:
	docker-compose down

# Удалить образы
clean-images:
	docker-compose down --rmi all

# ============================================
# Database
# ============================================

# Бэкап БД
backup:
	@mkdir -p backups
	@docker cp crypto_screener_backend:/data/screener.db backups/screener_$(shell date +%Y%m%d_%H%M%S).db
	@echo "✅ Бэкап создан: backups/screener_$(shell date +%Y%m%d_%H%M%S).db"

# Восстановить БД (указать файл: make restore FILE=backups/screener_20260112.db)
restore:
	@if [ -z "$(FILE)" ]; then echo "❌ Укажите файл: make restore FILE=backups/screener_20260112.db"; exit 1; fi
	docker cp $(FILE) crypto_screener_backend:/data/screener.db
	docker-compose restart backend
	@echo "✅ БД восстановлена из $(FILE)"

# Открыть SQLite shell
db-shell:
	docker exec -it crypto_screener_backend sqlite3 /data/screener.db

# ============================================
# Development
# ============================================

# Shell в backend контейнере
shell:
	docker exec -it crypto_screener_backend /bin/bash

# Установить зависимости Python (если изменился requirements.txt)
install-deps:
	docker-compose exec backend pip install -r requirements.txt

# Тест Telegram уведомления
test-telegram:
	@curl -X POST http://localhost:8000/api/settings/test-telegram

# ============================================
# Git Operations (опционально)
# ============================================

# Git status
git-status:
	git status

# Git commit и push
git-push:
	git add .
	git commit -m "$(MSG)"
	git push

# Пример: make git-push MSG="Added new feature"

# ============================================
# Info
# ============================================

# Показать версии
versions:
	@echo "Docker version:"
	@docker --version
	@echo ""
	@echo "Docker Compose version:"
	@docker-compose --version
	@echo ""
	@echo "Python version (в контейнере):"
	@docker-compose exec backend python --version || echo "Backend не запущен"

# Показать переменные окружения
show-env:
	@echo "⚠️  Показываю переменные из .env (БЕЗ секретов!):"
	@cat .env | grep -v "TOKEN\|PASSWORD\|SECRET" || echo "Файл .env не найден"

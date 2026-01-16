#!/bin/bash
# apply_migrations.sh
# Автоматически применяет SQL миграции при старте контейнера

set -e

DB_PATH="${DB_PATH:-/data/screener.db}"
MIGRATIONS_DIR="/app/migrations"

echo "============================================"
echo "🔄 Applying database migrations..."
echo "============================================"

# Проверить что БД существует
if [ ! -f "$DB_PATH" ]; then
    echo "❌ Database not found at $DB_PATH"
    echo "   Database will be created by application"
    exit 0
fi

# Проверить что папка миграций существует
if [ ! -d "$MIGRATIONS_DIR" ]; then
    echo "⚠️  Migrations directory not found: $MIGRATIONS_DIR"
    echo "   Skipping migrations..."
    exit 0
fi

# Создать таблицу для отслеживания примененных миграций
sqlite3 "$DB_PATH" <<EOF
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at INTEGER NOT NULL
);
EOF

echo "✅ Migrations tracking table ready"

# Применить каждую миграцию по порядку
for migration_file in "$MIGRATIONS_DIR"/*.sql; do
    # Пропустить если файлов нет
    if [ ! -f "$migration_file" ]; then
        echo "⚠️  No migration files found"
        break
    fi
    
    # Получить имя файла
    migration_name=$(basename "$migration_file")
    
    # Проверить применена ли уже эта миграция
    already_applied=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM schema_migrations WHERE version='$migration_name';")
    
    if [ "$already_applied" -gt 0 ]; then
        echo "⏭️  Skipping already applied: $migration_name"
        continue
    fi
    
    echo "📝 Applying migration: $migration_name"
    
    # Применить миграцию
    if sqlite3 "$DB_PATH" < "$migration_file"; then
        # Записать что миграция применена
        timestamp=$(date +%s)
        sqlite3 "$DB_PATH" "INSERT INTO schema_migrations (version, applied_at) VALUES ('$migration_name', $timestamp);"
        echo "✅ Successfully applied: $migration_name"
    else
        echo "❌ Failed to apply: $migration_name"
        exit 1
    fi
done

echo "============================================"
echo "✅ All migrations applied successfully!"
echo "============================================"

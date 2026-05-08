#FROM python:3.11-slim
#
#WORKDIR /app
#
#ENV PYTHONDONTWRITEBYTECODE 1
#ENV PYTHONUNBUFFERED 1
#
#ENV PYTHONPATH=/app/app
#
#RUN apt-get update && apt-get install -y --no-install-recommends \
#    build-essential \
#    libpq-dev \
#    curl \
#    && apt-get clean \
#    && rm -rf /var/lib/apt/lists/*
#
#COPY requirements.txt .
#RUN pip install --no-cache-dir --upgrade pip \
#    && pip install --no-cache-dir -r requirements.txt
#
#COPY . .
#
#RUN chmod +x commands/entrypoint.sh
#
#ENTRYPOINT ["commands/entrypoint.sh"]

FROM python:3.11-slim

# Настройки окружения
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR='/tmp/poetry_cache'

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    dos2unix \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Ставим Poetry (всегда последнюю)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir poetry

WORKDIR /app

# Сначала копируем только файлы зависимостей
COPY pyproject.toml poetry.lock* ./

# Обновляем lock внутри, если он вдруг разошелся с pyproject.toml
RUN poetry lock --check || poetry lock

# Устанавливаем пакеты
RUN poetry install --only main --no-root && rm -rf $POETRY_CACHE_DIR

# Копируем всё остальное
COPY . .

# Лечим Windows-окончания строк
RUN dos2unix commands/entrypoint.sh && chmod +x commands/entrypoint.sh

ENTRYPOINT ["commands/entrypoint.sh"]
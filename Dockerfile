# agent-forge runner (SPEC.md NFR-1: референс Python 3.12).
# Сборка:  docker build -t agent-forge .
# Прогон:  docker run --rm --env-file .env -v ${PWD}/runs:/app/runs \
#            -v /path/to/target-repo:/target agent-forge \
#            run --tasks config/tasks.example.yaml --target /target
FROM python:3.12-slim

WORKDIR /app

# Сначала зависимости — слой кешируется отдельно от кода.
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[dev]"

COPY forge/ forge/
COPY prompts/ prompts/
COPY config/ config/
COPY tests/ tests/
COPY README.md ./

RUN pip install --no-cache-dir -e .

# Точка входа — CLI forge; команда передаётся аргументами.
ENTRYPOINT ["forge"]
CMD ["--help"]

FROM python:3.8-buster

ENV PIP_DISABLE_PIP_VERSION_CHECK=on

RUN pip install poetry

WORKDIR /app
COPY poetry.lock pyproject.toml /app/

RUN poetry config virtualenvs.create false
RUN poetry install --no-dev --no-interaction

COPY . /app

WORKDIR /app/free_smiley_dealer
CMD python /app/free_smiley_dealer/main.py

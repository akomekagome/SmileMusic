FROM python:3.9.7-buster
USER root

ARG postgres_database_url smilemusic_discord_token smilemusic_prefix smilemusic_env

ENV POSTGRES_DATABASE_URL=${postgres_database_url}
ENV SMILEMUSIC_DISCORD_TOKEN=${smilemusic_discord_token}
ENV SMILEMUSIC_PREFIX=${smilemusic_prefix}
ENV SMILEMUSIC_ENV=${smilemusic_env}

ENV TZ JST-9
ENV TERM xterm

COPY ./requirements.txt /opt
COPY ./python /opt
WORKDIR /opt

RUN apt-get update
RUN apt-get install -y libpq-dev
RUN apt-get install -y ffmpeg
RUN pip install -r requirements.txt

CMD ["python", "smile_music.py"]
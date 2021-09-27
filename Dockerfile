FROM python:3.9.7-buster
USER root

ENV SMILEMUSIC_PREFIX=?
ENV SMILEMUSIC_ENV=Prod

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
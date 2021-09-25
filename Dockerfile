FROM python:3.9.7-buster
USER root

RUN apt update
ENV TZ JST-9
ENV TERM xterm

COPY ./requirements.txt /opt
COPY ./python /opt
WORKDIR /opt

RUN apt-get update
RUN apt-get install -y libpq-dev
RUN apt-get install -y ffmpeg
RUN apt-get install -y nodejs
RUN apt-get install -y npm
RUN npm install -g forever
RUN pip install -r requirements.txt
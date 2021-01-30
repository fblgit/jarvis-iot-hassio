FROM ubuntu:20.04
RUN apt update -qyy && apt install tzdata
RUN apt install -qyy python3-dev python3-pip python3
RUN apt install -qyy python3-yarl git
RUN cp /usr/share/zoneinfo/Asia/Singapore /etc/localtime
#COPY *.py /app/
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh
COPY requirements.txt /app/requirements.txt
RUN pip3 install homeassistant
RUN pip3 install -r /app/requirements.txt
WORKDIR /app
CMD ["/app/start.sh"]

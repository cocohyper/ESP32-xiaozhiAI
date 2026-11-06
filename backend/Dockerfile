# Fixed upstream dependency image; source revision is in upstream-version.json.
FROM ghcr.io/xinnan-tech/xiaozhi-esp32-server@sha256:c94ab84085f843a2c329019ff77cffca7bc3832e4cf55878ef8cb613985d4f37
WORKDIR /opt/xiaozhi-esp32-server
COPY upstream/ ./
COPY console/ ./console/
COPY manage.py upstream-version.json ./
CMD ["sh", "-c", "python manage.py check && exec python app.py"]

FROM python:3.12-alpine

RUN pip install --no-cache-dir flask requests gunicorn

WORKDIR /router
COPY router.py /router/router.py

EXPOSE 80

# gunicorn reads GUNICORN_CMD_ARGS from the environment (set in compose),
# so worker class / counts / timeouts are configured there, not baked in here.
ENTRYPOINT ["gunicorn"]
CMD ["router:app", "--bind", "0.0.0.0:80"]

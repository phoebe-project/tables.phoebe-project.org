FROM phoebe:2.4.23-blending

RUN pip install --no-cache-dir flask flask-cors gunicorn

WORKDIR /tables
COPY server.py tables-phoebe-project.wsgi ./

EXPOSE 80

ENTRYPOINT ["gunicorn"]
CMD ["server:app", "--bind", "0.0.0.0:80", "--forwarded-allow-ips", "*", "--access-logfile", "-", "--error-logfile", "-", "--capture-output", "--access-logformat", "%({X-Forwarded-For}i)s %({Host}i)s %(l)s %(u)s %(t)s \"%(r)s\" %(s)s %(b)s \"%(f)s\" \"%(a)s\""]

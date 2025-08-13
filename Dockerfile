FROM phoebe:blending

RUN pip install --no-cache-dir flask gunicorn

WORKDIR /tables
COPY server.py tables-phoebe-project.wsgi ./

EXPOSE 5600

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["exec gunicorn server:app --bind 0.0.0.0:5600 --forwarded-allow-ips '*' --access-logfile - --error-logfile - --capture-output --access-logformat '%({X-Forwarded-For}i)s %({Host}i)s %(l)s %(u)s %(t)s \"%(r)s\" %(s)s %(b)s \"%(f)s\" \"%(a)s\"'"]

# ENTRYPOINT ["gunicorn"]
# CMD ["server:app" "--bind" "0.0.0.0:5600" "--forwarded-allow-ips" "*" "--access-logformat" "%({X-Forwarded-For}i)s %({Host}i)s %(l)s %(u)s %(t)s \"%(r)s\" %(s)s %(b)s \"%(f)s\" \"%(a)s\""]

# tables.phoebe-project.org

Flask web-server to serve passband and atmosphere tables compatible with PHOEBE 2.2+.  As long as you have a stable internet connection, PHOEBE will query and pull tables on-the-fly as necessary.  Alternatively, you can call phoebe.download_passband or use the web form at [phoebe-project.org/tables](http://phoebe-project.org/tables) to download tables in advance.
* For tables compatible with PHOEBE 1.x (legacy), see [phoebe-project.org/1.0](http://phoebe-project.org/1.0/download)
* For tables compatible with PHOEBE 2.0.x and PHOEBE 2.1.x, see [phoebe2-tables](https://github.com/phoebe-project/phoebe2-tables) instead.

## Docker Deployment

Copy `.env.example` to `.env` and adjust to match your host:

```
cp .env.example .env
```

| Variable | Description | Example |
|---|---|---|
| `HOST_IP` | Host IP to bind the published port to | `192.168.1.109` |
| `HOST_PORT` | Host port to publish | `8002` |
| `MEMORY_LIMIT` | Container memory limit | `16GB` |

Then build and start:

```
docker compose build
docker compose up -d
```

The passband data directory is expected at `./data/` relative to this repo — it is mounted read-only into the container at `/tables/data`.

## Development Testing

To test the server before deploying, run `python server.py` and then point the local version of phoebe to localhost and refresh the cache of available online passbands:

```
import phoebe
phoebe.atmospheres.passbands._url_tables_server = 'http://localhost:5555'
phoebe.list_online_passbands(refresh=True)
phoebe.download_passband('Johnson:R')
```

## After updating passbands

To prevent burst requests from forcing worker restarts, caching for 1 hour has been instituted. To force cache expiration, run:

```
sudo htcacheclean -r /var/cache/apache2/mod_cache_disk
```

This will eliminate the need to wait (up to) 1 hour for cache to automatically clear.

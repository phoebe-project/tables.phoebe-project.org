# tables.phoebe-project.org

Flask web-server to serve passband and atmosphere tables compatible with PHOEBE 2.2+.  As long as you have a stable internet connection, PHOEBE will query and pull tables on-the-fly as necessary.  Alternatively, you can call phoebe.download_passband or use the web form at [phoebe-project.org/tables](http://phoebe-project.org/tables) to download tables in advance.
* For tables compatible with PHOEBE 1.x (legacy), see [phoebe-project.org/1.0](http://phoebe-project.org/1.0/download)
* For tables compatible with PHOEBE 2.0.x and PHOEBE 2.1.x, see [phoebe2-tables](https://github.com/phoebe-project/phoebe2-tables) instead.

## Development Testing

To test the server before deploying, run `python server.py` and then point the local version of phoebe to localhost and refresh the cache of available online passbands:

```
import phoebe
phoebe.atmospheres.passbands._url_tables_server = 'http://localhost:5555'
phoebe.list_online_passbands(refresh=True)
phoebe.download_passband('Johnson:R')
```

#!/usr/bin/python

"""
pip install flask
"""

try:
    from flask import Flask, jsonify, request, redirect, send_file, after_this_request
    from flask_cors import CORS
except ImportError:
    raise ImportError("dependencies not met: pip install flask flask-cors")

################################ SERVER/APP SETUP ##############################

app = Flask(__name__)
CORS(app)
app._verbose = True

import os
pwd = os.path.dirname(os.path.abspath(__file__))
tmpdir = os.path.join(pwd, 'flask_server_generated_tables')
datadir = os.path.join(pwd, 'data')
if not os.path.exists(tmpdir):
    os.mkdir(tmpdir)

# disable online passbands to prevent attempting an infinite loop
os.environ["PHOEBE_ENABLE_ONLINE_PASSBANDS"] = "FALSE"


################################## ADDITIONAL IMPORTS ##########################

import sys
import phoebe
from astropy.io import fits
import tempfile
import tarfile
import gzip
from datetime import datetime
from packaging import version
import re

phoebe.interactive_off()

def _pbs_flush(force=False):
    global _pbs_last_flush
    if _pbs_last_flush is None or force or (datetime.now()-_pbs_last_flush).total_seconds() > (60*60):
        print("flushing passbands cache")
        phoebe.atmospheres.passbands._pbtable = {}
        phoebe.atmospheres.passbands._init_passbands(refresh=True, query_online=False, passband_directories=datadir)
        _pbs_last_flush = datetime.now()

global _pbs_last_flush
_pbs_last_flush = None
_pbs_flush()

def _string_to_bool(value):
    if isinstance(value, bool):
        return value
    elif value.lower() == 'false':
        return False
    elif value.lower() == 'true':
        return True
    else:
        raise ValueError("{} could not be cast to bool".format(value))

def requires_inorm_tables(phoebe_version):
    """
    Returns True if the version is less than 2.5
    
    Arguments
    ---------
    phoebe_version : str
        The version string to compare
    
    Returns
    -------
    bool
        True if the version is less than 2.5, False otherwise
    """

    # normalize version number if necessary:
    version_base = re.match(r'(\d+\.\d+\.\d+)', phoebe_version)

    try:
        return version.parse(version_base.group(1)) < version.parse('2.5')
    except ValueError:
        # can't parse the version, so assume it's legacy
        return True

############################ HTTP ROUTES ######################################
def _get_response(data, status_code=200):
    resp = jsonify(data)
    resp.status_code = status_code
    return resp

def _unpack_passband_request(passband_request):
    online_passbands = phoebe.list_installed_passbands()

    if passband_request.lower() == 'all':
        return online_passbands
    else:
        ret = []
        # we need to handle logic of ['Johnson', 'Johnson:V', 'Stromgren:V']
        for pb in passband_request.split(','):
            if ':' in pb and pb not in ret:
                ret.append(pb)
            else:
                for pbo in online_passbands:
                    if pbo.split(':')[0] == pb and pbo not in ret:
                        ret.append(pbo)

        return ret


def _unpack_content_request(content_request):
    # if isinstance(passband_request, str):
    #     raise ValueError("pass passband_request through _unpack_passband_request first")

    if isinstance(content_request, list):
        return content_request
    elif not (isinstance(content_request, str) or isinstance(content_request, unicode)):
        raise TypeError("content_request must be of type list or string")
    elif content_request.lower() == 'all':
        return 'all'
    else:
        # note: the individual entries may still contain atm:all... each item
        # in the returned list will later need to be processed via _expand_content_item
        return content_request.split(",")

def _expand_content_item(pb, cr_item):
    """
    cr_item is a single item from this list returned by _unpack_content_request
    """
    if cr_item in pb.content:
        return [cr_item]
    else:
        # then we need to handle the chance that cr_item might be an atm
        atm = cr_item.split(':')[0]
        c_matches = [c for c in pb.content if c.split(':')[0]==atm]
        return c_matches


def _unpack_version_request(phoebe_version_request):
    if phoebe_version_request == 'latest':
        return phoebe.__version__
    else:
        return phoebe_version_request

def _generate_request_passband(pbr, content_request, export_inorm_tables=False, gzipped=False, save=True):
    if app._verbose:
        print("_generate_request_passband {} {} gzipped={} save={}".format(pbr, content_request, gzipped, save))

    # we have to force reloading from the file here or else changing the content
    # will persist in memory
    pb = phoebe.get_passband(pbr, reload=True)

    prefix = '{}_{}'.format(pb.pbset.lower(), pb.pbname.lower())
    filename = '{}.fits.gz'.format(prefix) if gzipped else '{}.fits'.format(prefix)

    if isinstance(content_request, str):
        if content_request.lower() == 'all':
            pass
        else:
            raise ValueError("pass content_request through _unpack_content_request first")
    else:
        content_return = []
        for c in content_request:
            c_expanded = _expand_content_item(pb, c)
            # if not len(c_expanded):
            #     raise ValueError("could not find content match for content_request={}".format(c))
            content_return += c_expanded

        content_return = list(set(content_return))
        print("serving {} passband with content={}".format(pbr, content_return))
        pb.content = content_return

    if save:
        pbf = tempfile.NamedTemporaryFile(mode='w+b', dir=tmpdir, prefix=prefix, suffix=".fits.gz" if gzipped else ".fits")
        if gzipped:
            gzf = gzip.GzipFile(mode='wb', fileobj=pbf)
            pb.save(gzf, export_inorm_tables=export_inorm_tables, update_timestamp=False)
            return gzf, filename

        else:
            pb.save(pbf, export_inorm_tables=export_inorm_tables, update_timestamp=False)
            return pbf, filename

    else:
        return pb

@app.route('/favicon.ico', methods=['GET'])
def favicon():
    if app._verbose:
        print("favicon")

    return _get_response({})

@app.route('/', methods=['GET'])
def redirect_to_form():
    return redirect("http://phoebe-project.org/tables", code=302)

@app.route('/pbs', methods=['GET'])
def redirect_to_form_pbs():
    return redirect("http://phoebe-project.org/tables/pbs", code=302)

@app.route('/info', methods=['GET'])
def info():
    if app._verbose:
        print("info", sys.version_info, phoebe.__version__)

    version_info = sys.version_info

    return _get_response({'python_version_server': "{}.{}.{}".format(version_info.major, version_info.minor, version_info.micro),
                          'phoebe_version_server': phoebe.__version__})

@app.route('/flush', methods=['GET'])
def flush():
    if app._verbose:
        print("flush")

    _pbs_flush(force=True)
    return redirect('/info')

@app.route('/pbs/phoebe_versions', methods=['GET'])
def pbs_phoebe_versions():
    return _get_response({'phoebe_version_server': phoebe.__version__,
                          'phoebe_versions_available': [phoebe.__version__, 'latest']})

@app.route('/pbs/list', methods=['GET'])
def pbs_list():
    if app._verbose:
        print("pbs_list")

    _pbs_flush()

    phoebe_version_request = _unpack_version_request(request.args.get('phoebe_version', 'lastest'))
    online_passbands = phoebe.list_installed_passbands(full_dict=True, skip_keys=['pb', 'installed', 'local'])

    for pb,info in online_passbands.items():
        info['fname'] = 'tables.phoebe-project.org/pbs/{}'.format(pb)

    return _get_response({'phoebe_version_request': phoebe_version_request,
                          'phoebe_version_server': phoebe.__version__,
                          'passbands_list': online_passbands})


@app.route('/pbs/available', methods=['GET'])
def pbs_available():
    if app._verbose:
        print("pbs_available")

    _pbs_flush()

    phoebe_version_request = _unpack_version_request(request.args.get('phoebe_version', 'lastest'))
    online_passbands = phoebe.list_installed_passbands(full_dict=True, skip_keys=['pb', 'installed', 'local'])

    available_content = []
    for pb,d in online_passbands.items():
        for c in d['content']:
            # in addition to the individual content entries, provide an atm:all
            # option.  This will be accepted by pbs_generate_and_serve's content_request
            # via _unpack_content_request and _expand_content_item
            # atm = c.split(':')[0]
            # if atm not in available_content:
            #     available_content.append(atm)

            if c not in available_content:
                available_content.append(c)

    # NOTE: the returned content items are not guaranteed to exist for each
    # passband entry, but are a complete list of all available content across
    # all passbands.  If an item in content does not exist for a given passband
    # that can be checked via pbs_content or will just be skipped during
    # pbs_generate_and_serve
    passbands = sorted(online_passbands.keys())
    passband_sets = sorted(list(set([pb.split(':')[0] for pb in online_passbands.keys()])))
    passbands_per_set = {pbs: len([pb for pb in passbands if pb.split(':')[0]==pbs]) for pbs in passband_sets}
    return _get_response({'phoebe_version_request': phoebe_version_request,
                          'phoebe_version_server': phoebe.__version__,
                          'passbands': passbands,
                          'passband_sets': passband_sets,
                          'npassbands_per_set': passbands_per_set,
                          'content': sorted(available_content),
                          'content_atms': sorted(list(set([c.split(':')[0] for c in available_content])))})

@app.route('/pbs/history', methods=['GET'])
@app.route('/pbs/history/<string:passband_request>', methods=['GET'])
def pbs_history(passband_request='all'):
    if app._verbose:
        print("pbs_history")

    _pbs_flush()

    passband_request = _unpack_passband_request(passband_request)
    phoebe_version_request = _unpack_version_request(request.args.get('phoebe_version', 'lastest'))
    online_passbands = phoebe.list_installed_passbands(full_dict=True, skip_keys=['pb', 'installed', 'local'])

    pb_history = {}
    for pbr in passband_request:
        pb_history[pbr] = {}

        fname = online_passbands.get(pbr, {}).get('fname', None)
        if fname is None:
            continue

        pb = phoebe.atmospheres.passbands.Passband.load(fname, load_content=False)
        pb_history[pbr] = pb.history

    return _get_response({'phoebe_version_request': phoebe_version_request,
                          'phoebe_version_server': phoebe.__version__,
                          'passband_history': pb_history})

@app.route('/pbs/content/<string:passband_request>', methods=['GET'])
def pbs_content(passband_request):
    if app._verbose:
        print("pbs_content for passband: {}".format(passband_request))

    _pbs_flush()

    passband_request = _unpack_passband_request(passband_request)
    phoebe_version_request = _unpack_version_request(request.args.get('phoebe_version', 'lastest'))


    online_passbands = phoebe.list_installed_passbands(full_dict=True, skip_keys=['pb', 'installed', 'local'])


    return _get_response({'phoebe_version_request': phoebe_version_request,
                          'phoebe_version_server': phoebe.__version__,
                          'content': {pbr: online_passbands.get(pbr, {}).get('content', []) for pbr in passband_request}})


# @app.route('/pbs/unpack_request', methods=['GET'])
@app.route('/pbs/unpack_request/<string:passband_request>', methods=['GET'])
@app.route('/pbs/unpack_request/<string:passband_request>/<string:content_request>', methods=['GET'])
def pbs_unpack_request(passband_request='all', content_request='all'):
    if app._verbose:
        print("pbs_unpack_request", passband_request, content_request)

    _pbs_flush()

    passband_request = _unpack_passband_request(passband_request)
    content_request = _unpack_content_request(content_request)
    phoebe_version_request = _unpack_version_request(request.args.get('phoebe_version', 'lastest'))
    gzipped = _string_to_bool(request.args.get('gzipped', False))

    generated = {}
    for pbr in passband_request:
        pb = _generate_request_passband(pbr, content_request, export_inorm_tables=requires_inorm_tables(phoebe_version_request), gzipped=gzipped, save=False)
        generated["{}:{}".format(pb.pbset, pb.pbname)] = pb.content

    return _get_response({'phoebe_version_request': phoebe_version_request,
                          'phoebe_version_server': phoebe.__version__,
                          'passband_request': passband_request,
                          'content_request': content_request,
                          'content_generated': generated,
                          'content_gzipped': gzipped})

# @app.route('/pbs', methods=['GET'])
@app.route('/pbs/<string:passband_request>', methods=['GET'])
@app.route('/pbs/<string:passband_request>/<string:content_request>', methods=['GET'])
def pbs_generate_and_serve(passband_request='all', content_request='all',):
    if app._verbose:
        print("pbs_generate_and_serve", passband_request, content_request)

    _pbs_flush()

    created_tmp_files = []

    @after_this_request
    def cleanup(response):
        for tf in created_tmp_files:
            tf.close()
        return response

    passband_request = _unpack_passband_request(passband_request)
    content_request = _unpack_content_request(content_request)
    phoebe_version_request = _unpack_version_request(request.args.get('phoebe_version', 'lastest'))
    gzipped = _string_to_bool(request.args.get('gzipped', False))

    if len(passband_request) > 1:
        # TODO: flexibility for tar vs zip?
        tbf = tempfile.NamedTemporaryFile(suffix='.tar.gz')
        tar = tarfile.open(fileobj=tbf, mode='w:gz')

        created_tmp_files.append(tbf)

        for pbr in passband_request:
            pbf, pbfname = _generate_request_passband(pbr, content_request, export_inorm_tables=requires_inorm_tables(phoebe_version_request), gzipped=gzipped, save=True)
            created_tmp_files.append(pbf)

            tar.add(pbf.name, arcname=pbfname)

        return send_file(tbf.name, as_attachment=True, download_name='generated_phoebe_tables.tar.gz')

    # if we're here, then we know we're a list with only one entry
    pbf, pbfname = _generate_request_passband(passband_request[0], content_request, export_inorm_tables=requires_inorm_tables(phoebe_version_request), gzipped=gzipped, save=True)
    created_tmp_files.append(pbf)

    return send_file(pbf.name, as_attachment=True, download_name=pbfname)


if __name__ == "__main__":
    # flask-server.py port, host
    if len(sys.argv) >= 2:
        port = int(float(sys.argv[1]))
    else:
        port = 5555

    if len(sys.argv) >=3:
        host = sys.argv[2]
    else:
        host = '127.0.0.1'

    if app._verbose:
        print("*** SERVER READY at {}:{} ***".format(host, port))


    app.run(host=host, port=port)

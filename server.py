#!/usr/bin/python

"""
pip install flask
"""

try:
    from flask import Flask, jsonify, request, redirect, Response, make_response, send_from_directory, send_file, after_this_request
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



################################## ADDITIONAL IMPORTS ##########################

import phoebe
import tempfile
import tarfile
import sys
from datetime import datetime

phoebe.interactive_off()

def _flush():
    print("flushing passbands cache")
    phoebe.atmospheres.passbands._pbtable = {}
    phoebe.atmospheres.passbands._init_passbands(refresh=True, query_online=False, passband_directories=datadir)

_flush()

############################ HTTP ROUTES ######################################
def _get_response(data, status_code=200):
    resp = jsonify(data)
    resp.status_code = status_code
    return resp

def _unpack_passband_request(passband_request):
    if passband_request.lower() == 'all':
        online_passbands = phoebe.list_installed_passbands()

        return online_passbands
    else:
        return passband_request.split(",")

def _unpack_content_request(content_request):
    # if isinstance(passband_request, str):
    #     raise ValueError("pass passband_request through _unpack_passband_request first")

    if isinstance(content_request, list):
        return content_request
    elif content_request.lower() == 'all':
        return 'all'

    else:
        return content_request.split(",")


def _generate_requested_passband(pbr, content_request):
    if app._verbose:
        print("_generate_requested_passband {} {}".format(pbr, content_request))

    pb = phoebe.get_passband(pbr)

    prefix = '{}_{}'.format(pb.pbset.lower(), pb.pbname.lower())
    filename = '{}.fits'.format(prefix)

    if isinstance(content_request, str):
        if content_request.lower() == 'all':
            pass
        else:
            raise ValueError("pass content_request through _unpack_content_request first")
    else:
        pb.content = [c for c in content_request]


    pbf = tempfile.NamedTemporaryFile(dir=tmpdir, prefix=prefix, suffix=".fits")
    pb.save(pbf.name)

    return pbf, filename


@app.route('/', methods=['GET'])
def redirect_to_form():
    return redirect("http://phoebe-project.org/tables", code=302)

@app.route('/flush', methods=['GET'])
def flush():
    _flush()
    return redirect("/list")

@app.route('/list', methods=['GET'])
def list_passbands():
    if app._verbose:
        print("list_passbands")

    online_passbands = phoebe.list_installed_passbands(full_dict=True)

    return _get_response(online_passbands)

@app.route('/favicon.ico', methods=['GET'])
def favicon():
    if app._verbose:
        print("favicon")

    return _get_response({})

@app.route('/available', methods=['GET'])
def available():
    if app._verbose:
        print("available")

    online_passbands = phoebe.list_installed_passbands(full_dict=True)

    available_contents = []
    for pb,d in online_passbands.items():
        for atm in d['atms']:
            if atm not in available_contents:
                available_contents.append(atm)

    return _get_response({'passbands': sorted(online_passbands.keys()),
                          'contents': sorted(available_contents)})

@app.route('/info', methods=['GET'])
def info():
    if app._verbose:
        print("info", sys.version_info, phoebe.__version__)

    version_info = sys.version_info

    return _get_response({'python_version': "{}.{}.{}".format(version_info.major, version_info.minor, version_info.micro),
                          'phoebe_version': phoebe.__version__})

@app.route('/<string:passband_request>', methods=['GET'])
def list_contents_for_passband(passband_request):
    if app._verbose:
        print("list_contents_for_passband: {}".format(passband_request))

    online_passbands = phoebe.list_installed_passbands(full_dict=True)

    passband_request = _unpack_passband_request(passband_request)

    return _get_response([online_passbands.get(pbr, {}) for pbr in passband_request])




@app.route('/<string:passband_request>/<string:content_request>', methods=['GET'])
def generate_and_serve_passband(passband_request, content_request):
    if app._verbose:
        print("generate_and_serve_passband", passband_request, content_request)

    created_tmp_files = []

    @after_this_request
    def cleanup(response):
        for tf in created_tmp_files:
            tf.close()
        return response

    passband_request = _unpack_passband_request(passband_request)
    content_request = _unpack_content_request(content_request)

    if len(passband_request) > 1:
        # TODO: flexibility for tar vs zip?
        tbf = tempfile.NamedTemporaryFile(suffix='.tar.gz')
        tar = tarfile.open(fileobj=tbf, mode='w:gz')

        created_tmp_files.append(tbf)

        for pbr in passband_request:
            pbf, pbfname = _generate_requested_passband(pbr, content_request)
            created_tmp_files.append(pbf)

            tar.add(pbf.name, arcname=pbfname)

        return send_file(tbf.name, as_attachment=True, attachment_filename='generated_phoebe_tables.tar.gz')

    pbf, pbfname = _generate_requested_passband(passband_request[0], content_request)
    created_tmp_files.append(pbf)

    return send_file(pbf.name, as_attachment=True, attachment_filename=pbfname)


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

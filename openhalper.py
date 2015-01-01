#!/usr/bin/python3

import sys
import flask
from time import sleep, time as now
import subprocess
import threading
import os.path
import json

ACTIONS = {
    "temp": {
        "exec": ["temp", "24"],
        "parse": lambda r: r.split()[0],
        "interval": 60,
        "lifetime": 15
    },
    "hum": {
        "exec": ["temp",  "24"],
        "parse": lambda r: r.split()[1],
        "interval": 60,
        "lifetime": 15
    },
    "say": {
        "exec": ["espeak", "{[text]}"],
    },
}

PORT = 8081

for conf_file in "/etc/openhalper.conf", os.path.expanduser("~/.config/openhalper.conf"), "./openhalper.conf":
    try:
        with open(conf_file) as f:
            conf = json.load(f)
            if "port" in conf:
                PORT = conf["port"]
                if "actions" in conf:
                    ACTIONS.update(conf["actions"])
    except FileNotFoundError:
        pass

if len(sys.argv) > 1:
    PORT = int(sys.argv[1])

NEXT_UPDATES = {}
CACHE = {}

def init_intervals():
    for name, item in ACTIONS.items():
        if "interval" in item:
            NEXT_UPDATES[name] = now()

def do_action(name, **kwargs):
    item = ACTIONS[name]
    if "exec" in item:
        try:
            result = subprocess.check_output([arg.format(kwargs) for arg in item["exec"]], timeout=10).decode('ascii')
        except subprocess.CalledProcessError as e:
            return e.returncode
        except subprocess.TimeoutExpired:
            return "Timed out"
    elif "func" in item:
        result = item["func"](**kwargs)
    else:
        result = None

    if "parse" in item:
        result = item["parse"](result)

    return result
            
def do_update():
    for name, time in NEXT_UPDATES.items():
        if time <= now():
            CACHE[name] = {"value": do_action(name), "time": now()}
            NEXT_UPDATES[name] = now() + ACTIONS[name]["interval"]

    next = min([v for k, v in NEXT_UPDATES.items()])
    if next > now():
        sleep(next - now())

def handle_request(item):
    if item in CACHE:
        if "cache" in ACTIONS[item]:
            if CACHE[item]["time"] + ACTIONS[item]["lifetime"] < now():
                return CACHE[item]["value"]

    CACHE[item] = {"value": do_action(name), "time": now()}
    return CACHE[item]["value"]

def update():
    init_intervals()
    while True:
        do_update()

updater = threading.Thread(target=update, name="ClimateUpdater")
updater.setDaemon(True)
updater.start()
        
app = flask.Flask(__name__)

@app.route('/<name>', methods=['GET', 'POST'])
def serve(name):
    if name in ACTIONS:
        args = flask.request.args
        return do_action(name, **args)
    else:
        return "Page not found", 404

app.run('0.0.0.0', port=PORT, debug=True)

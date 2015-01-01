#!/usr/bin/python

import sys
import flask
from time import sleep, time as now
import subprocess
import threading
import os.path
import json

try:
    raise TimeoutExpired()
except NameError:
    class TimeoutExpired(Exception):
        pass
    subprocess.TimeoutExpired = TimeoutExpired

try:
    subprocess.check_output(["true"], timeout=60)
except TypeError:
    subprocess.__real__check_output = subprocess.check_output
    def co_proxy(*args, **kwargs):
        if "timeout" in kwargs:
            del kwargs["timeout"]
        return subprocess.__real__check_output(*args, **kwargs)
    subprocess.check_output = co_proxy
except CalledProcessError:
    pass

try:
    raise FileNotFoundError()
except NameError:
    FileNotFoundError = IOError
except:
    pass

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
        "exec": 'echo {[text]} | espeak --stdin',
        "parse": lambda r: r,
        "shell": True
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
    except OSError:
        pass
    except IOError:
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
    result = ""
    if "exec" in item:
        try:
            args = item["exec"]
            try:
                args = [arg.format(kwargs) for arg in item["exec"]]
            except:
                args = item["exec"].format(kwargs)
            result = subprocess.check_output(args, timeout=10, shell=(item["shell"] if "shell" in item else False)).decode('ascii')
        except subprocess.CalledProcessError as e:
            return "Error: {}".format(e.returncode)
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

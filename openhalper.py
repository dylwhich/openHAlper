#!/usr/bin/python

import sys
import flask
from time import sleep, time as now
import subprocess
import threading
import os.path
import json
import RPi.GPIO as GPIO
import requests

GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)

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
        "type": "temp",
        "exec": ["temp", "24"],
        "parse": lambda r: float(r.split()[0]),
        "validate": lambda r: r > 0 and r < 40,
        "interval": 60,
        "lifetime": 15
    },
    "hum": {
        "type": "hum",
        "exec": ["temp",  "24"],
        "parse": lambda r: float(r.split()[1]),
        "validate": lambda r: r > 0 and r <= 100,
        "interval": 60,
        "lifetime": 15
    },
    "say": {
        "type": "speak",
        "exec": 'echo {[text]} | espeak --stdin --stdout | aplay',
        "parse": lambda r: "",
        "shell": True
    },
    "gpio_in": {
        "type": "gpio_in",
        "pin": 3,
        "url": "http://vegasix.xn--hackaf-gva.net:8081/rest/items/Kitchen_Button_Button/state",
        "method": "put",
        "interval": 0.1,
        "state": 0
    },
    "led": {
        "type": "gpio_out",
        "pin": 5
    },
    "furnace": {
        "type": "gpio_out",
        "state": False,
        "pin": 7
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

def start_io():
    for name, item in ACTIONS.items():
        if item['type'] == "gpio_out":
            GPIO.setup(item['pin'], GPIO.OUT)
        if item['type'] == "gpio_in":
            GPIO.setup(item['pin'], GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(item['pin'], GPIO.BOTH)

def init_intervals():
    for name, item in ACTIONS.items():
        if "interval" in item:
            NEXT_UPDATES[name] = now()

def do_action(name, **kwargs):
    item = ACTIONS[name]
    result = ""
    valid = True
    for i in range(10):
        if "exec" in item:
            try:
                args = item["exec"]
                try:
                    args = [arg.format(kwargs) for arg in item["exec"]]
                except:
                    args = item["exec"].format(kwargs)

                result = subprocess.check_output(args, timeout=10, shell=(item["shell"] if "shell" in item else False)).decode('ascii')
            except subprocess.CalledProcessError as e:
                return "Error: {0}".format(e.returncode)
            except subprocess.TimeoutExpired:
                return "Timed out"
        elif "func" in item:
            result = item["func"](**kwargs)
        else:
            result = None

        if "parse" in item:
            result = item["parse"](result)

        if "validate" in item:
            if item["validate"](result):
                break
        if item['type'] == "gpio_in":
            newstate = GPIO.input(item['pin'])
            if item['state'] != newstate:
                if item['method'].lower() == "put":
                    method = requests.put
                elif item['method'].lower() == "get":
                    method = requests.get
                elif item['method'].lower() == "post":
                    method = requests.post
                else:
                    method = requests.get
                payload = "OPEN" if item['state'] else "CLOSED"
                print("state", newstate, item['state'])
                print(method(item['url'], data=payload))
            item['state'] = newstate
            result = item['state']
        if item['type'] == "gpio_out":
            if 'state' in kwargs:
              result = bool(int(kwargs['state'][0]))
              GPIO.output(item['pin'], result)
              item['state'] = result
            else:
              result = item['state']
            break
        else:
            break
    else:
        valid = False

    return result, valid

def do_update():
    for name, time in NEXT_UPDATES.items():
        if time <= now():
            res, valid = do_action(name)
            if valid:
                CACHE[name] = {"value": res, "time": now()}
            else:
                print("do_update: Not caching request for {0}, it was invalid ({1})".format(name, res))
            NEXT_UPDATES[name] = now() + ACTIONS[name]["interval"]

    next = min([v for k, v in NEXT_UPDATES.items()])
    if next > now():
        sleep(next - now())

def handle_request(item, **args):
    if item in CACHE:
        if "cache" in ACTIONS[item]:
            if CACHE[item]["time"] + ACTIONS[item]["lifetime"] < now():
                return CACHE[item]["value"]

    res, valid = do_action(item, **args)
    if valid:
        CACHE[item] = {"value": res, "time": now()}
    else:
        print("handle_request: Not caching request for {0}, it was invalid ({1})".format(item, res))
    return str(res)

def update():
    start_io()
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
        return handle_request(name, **args)
    else:
        return "Page not found", 404

app.run('0.0.0.0', port=PORT, debug=False)

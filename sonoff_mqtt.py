#!/bin/python3
#
# Gateway between sonoff devices using pysonofflan and mqtt server
#
# Only works with single switch devices, but using CH01 in case of future devices with more channels
#
# Sonoff devices supports only one conection, because of this this routine does not keep the conection stablished full time
#
# TODO : 
#      more command line parameters for configurations
#      update for more devices when pysonofflan supports 
#      check if mqtt will reconnect in case of error
#
import paho.mqtt.client as mqtt
from pysonofflan import SonoffSwitch
from threading import Thread,Condition,Event
import time
import logging
import logging.config
import traceback
import argparse
import datetime



deviceObjects = {}
deviceCommands = {}
deviceThreads = {}
events = {}
topicPrefix = "/sonoff_mqtt/"
disconnectWait = 5
commandString = "command"


def wait_disconnect(host):
    time.sleep( disconnectWait )
    deviceObjects[host].shutdown_event_loop()
    events[host].set()
    
def host_topic(host):
    return topicPrefix + host 

def alive_topic(host):
    return host_topic(host) + "/alive"

def state_topic(host):
    return host_topic(host) + "/CH01/state"

def command_topic(host):
    return host_topic(host) + "/CH01/" + commandString

async def state_callback(device):
    logging.debug("callback : " + str(device))
    if device.basic_info is not None:
        deviceObjects[device.host] = device
        topic = state_topic(device.host)
        
        if device.host in deviceCommands:
            command = deviceCommands[device.host]
            logging.info ("sending command " + command + " to " + device.host)
            if command.upper() == "ON":
                await device.turn_on()
            else:
                await device.turn_off()
            deviceCommands.pop(device.host)

            # delayed disconnect to keep communications running....
            t = Thread(target=wait_disconnect,args=[device.host])
            t.start()
        else:
            # no command to send, stop communication
            device.shutdown_event_loop()

        payload = ("ON" if device.is_on else "OFF")
        logging.debug (topic + " " + payload)        
        msg_info = mqtt.publish(topic, payload=payload)
        msg_info.wait_for_publish()
        # For reference indicate last time message was received
        mqtt.publish(alive_topic(device.host), datetime.datetime.utcnow().replace(microsecond=0).isoformat())

    logging.debug("callback-end : " + str(device))

def command_waiting(host):
    return host in deviceCommands
    
def deviceThread(host):
    while True:
        try:
            events[host].clear()
            switch = SonoffSwitch(host=host, callback_after_update=state_callback)
            logging.debug ("connected " + host)
            events[host].wait( 30 )
            switch.shutdown_event_loop()
        except Exception as error:
            if "Connect call failed" not in str(error):
                logging.error (host + " error=" + str(error))
#               traceback.print_stack(error)
            time.sleep( 30 )
            pass
    

def mqtt_on_message(client, userdata, message):
    logging.debug ("mqtt message received : " + message.topic + " " + str(message.payload))

# split with prefix
# ['', 'sonoff_mqtt', '10.1.12.82', 'CH01', 'command']
# split without prefix
# [ '10.1.12.82', 'CH01', 'command']
    top = message.topic[len(topicPrefix):].split("/")
    payload = message.payload.decode("utf-8")

    host = top[0]
    if host in deviceObjects:
        device = deviceObjects[host]
        if  device and top[2] == commandString:
            logging.info ("command  " + payload + " to " + host)        
            deviceCommands[host] = payload
            events[host].set()
    else:
        logging.error ("Host not available " + host)

def mqtt_connect(client, userdata, flags, rc):
    logging.info ("connected " + str(client))


parser = argparse.ArgumentParser()
parser.add_argument( "host", nargs='+', help="sonnof host")
parser.add_argument( "--mqtt", default="mqtt", help="mqtt host")
parser.add_argument( "--logConfig", help="logConfig")
args = parser.parse_args()


if args.logConfig:
    logging.config.fileConfig(args.logConfig)
else:
    logging.basicConfig(level=logging.INFO) 

mqtt = mqtt.Client(client_id="sonoff_mqtt", clean_session=False)
mqtt.on_connect = mqtt_connect
mqtt.connect(args.mqtt, 1883, 20)
mqtt.on_message = mqtt_on_message

for ip in args.host:
    events[ip] = Event()
    deviceThreads[ip] = Thread(target=deviceThread,args=[ip])
    deviceThreads[ip].start()
    result = mqtt.subscribe(command_topic(ip), 0)
    logging.info ("subscribing to mqtt : " + ip + " " + str(result))

logging.info ("processing....")
mqtt.loop_start()


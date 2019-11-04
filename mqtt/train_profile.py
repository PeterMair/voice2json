#!/usr/bin/env python3
import re
import sys
import json
import argparse
import subprocess
import shlex
import time
import logging

logger = logging.getLogger("train_profile")

import paho.mqtt.client as mqtt

TOPIC_TRAIN = "voice2json/train-profile/train"
TOPIC_TRAINED = "voice2json/train-profile/trained"

from .utils import voice2json


def main():
    parser = argparse.ArgumentParser(prog="train_profile")
    parser.add_argument(
        "--host", default="localhost", help="MQTT host (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=1883, help="MQTT port (default: 1883)"
    )
    parser.add_argument("--profile", help="Path to voice2json profile")
    parser.add_argument(
        "--topic-trained",
        action="append",
        default=[TOPIC_TRAINED],
        help="Topic(s) to send trained events out on",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Print DEBUG messages to the console"
    )
    args, other_args = parser.parse_known_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    logger.debug(args)

    try:
        # Listen for messages
        client = mqtt.Client()

        def on_connect(client, userdata, flags, rc):
            try:
                logger.info("Connected")

                # Subscribe to topics
                for topic in [TOPIC_TRAIN]:
                    client.subscribe(topic)
                    logger.debug(f"Subscribed to {topic}")
            except Exception as e:
                logging.exception("on_connect")

        def on_disconnect(client, userdata, flags, rc):
            try:
                # Automatically reconnect
                logger.info("Disconnected. Trying to reconnect...")
                client.reconnect()
            except Exception as e:
                logging.exception("on_disconnect")

        def on_message(client, userdata, msg):
            try:
                if msg.topic == TOPIC_TRAIN:
                    result = voice2json(
                        "train-profile",
                        *other_args,
                        profile_path=args.profile,
                        stderr=subprocess.STDOUT,
                    ).read()

                    for topic in args.topic_trained:
                        client.publish(topic, result)

            except Exception as e:
                logger.exception("on_message")

        # Connect
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        client.connect(args.host, args.port)

        client.loop_forever()
    except KeyboardInterrupt:
        pass
    finally:
        logger.debug("Shutting down")


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
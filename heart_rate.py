#!/usr/bin/env python3

import array
import collections
import datetime
import math
import os
import queue
import random
import struct
import sys
import threading
import time

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

import pygame
import pygame.freetype
import pygame.time

import usb.core
import usb.util

from openant.base.message import Message
from openant.base.driver import find_driver

from dataclasses import dataclass, field

from typing import List

HEART = "♥"
COLOR = (255, 0, 0)

class State():
    pass
STATE = State()
STATE.heart_rate = None
STATE.running = True

class Ant:
    _RESET_WAIT = 1
    CHANNEL_ID = 0
    NETWORK_ID = 0

    def __init__(self):
        self._buffer = array.array("B", [])

        self._driver = find_driver()
        self._driver.open()

        self.reset_system()

    def stop(self):
        self._driver.close()

    def pump(self):
        message = self.read_message()

        if message is None:
            return False

        if message._id == Message.ID.BROADCAST_DATA:
            page = message._data[1]

            if (page & 0x0F) <= 7:
                raw_heart_rate = message._data[8]
                if raw_heart_rate > 0:
                    STATE.heart_rate = raw_heart_rate
        return True

    def write_message(self, message: Message):
        data = message.get()
        self._driver.write(data)

    def read_packet(self):
        if len(self._buffer) >= 5 and len(self._buffer) >= self._buffer[1] + 4:
            packet = self._buffer[: self._buffer[1] + 4]
            self._buffer = self._buffer[self._buffer[1] + 4 :]
            return packet
        return None

    def read_message(self):
        packet = self.read_packet()
        if packet == None:
            try:
                data = self._driver.read()
            except usb.core.USBTimeoutError:
                return None
            self._buffer.extend(data)
            packet = self.read_packet()
        if packet != None:
            return Message.parse(packet)
        return None

    def assign_channel(self, channelType, networkNumber, ext_assign):
        self.write_message(Message(Message.ID.ASSIGN_CHANNEL, [self.CHANNEL_ID, channelType, networkNumber, ext_assign]))

    def open_channel(self):
        self.write_message(Message(Message.ID.OPEN_CHANNEL, [self.CHANNEL_ID]))

    def open_rx_scan_mode(self):
        """
        Enable RX scanning mode

        In scanning mode, the radio is active in receive mode 100% of the time
        so no other channels but the scanning channel can run. The scanning
        channel picks up any message regardless of period that is being
        transmitted on its RF frequency and matches its channel ID mask. It can
        receive from multiple devices simultaneously.

        A CLOSE_ALL_CHANNELS message from ANT will indicate an invalid attempt
        to start the scanning mode while any channels are open.

        :param channel int: channel number to use (doesn't really matter)
        """
        # [Channel, 1-Enable]
        self.write_message(Message(Message.ID.OPEN_RX_SCAN_MODE, [self.CHANNEL_ID, 1]))

    def close_channel(self):
        self.write_message(Message(Message.ID.CLOSE_CHANNEL, [self.CHANNEL_ID]))

    def unassign_channel(self):
        self.write_message(Message(Message.ID.UNASSIGN_CHANNEL, [self.CHANNEL_ID]))

    def set_channel_id(self, deviceNum, deviceType, transmissionType):
        data = array.array(
            "B", struct.pack("<BHBB", self.CHANNEL_ID, deviceNum, deviceType, transmissionType)
        )
        self.write_message(Message(Message.ID.SET_CHANNEL_ID, data))

    def set_channel_period(self, messagePeriod):
        data = array.array("B", struct.pack("<BH", self.CHANNEL_ID, messagePeriod))
        self.write_message(Message(Message.ID.SET_CHANNEL_PERIOD, data))

    def set_channel_search_timeout(self, timeout):
        self.write_message(Message(Message.ID.SET_CHANNEL_SEARCH_TIMEOUT, [self.CHANNEL_ID, timeout]))

    def set_channel_rf_freq(self, rfFreq):
        self.write_message(Message(Message.ID.SET_CHANNEL_RF_FREQ, [self.CHANNEL_ID, rfFreq]))

    def set_network_key(self, network, key):
        self.write_message(Message(Message.ID.SET_NETWORK_KEY, [network] + key))

    def reset_system(self):
        self.write_message(Message(Message.ID.RESET_SYSTEM, [0x00]))
        time.sleep(self._RESET_WAIT)

class HeartRate:
    CHANNEL_ID = 0
    NETWORK_ID = 0
    NETWORK_KEY = [0xB9, 0xA5, 0x21, 0xFB, 0xBD, 0x72, 0xC3, 0x45]
    HEART_RATE_SENSOR = 120

    def __init__(self, device_id):
        self.ant = Ant()

        self.ant.set_network_key(self.NETWORK_ID, self.NETWORK_KEY)
        self.ant.assign_channel(0x00, self.NETWORK_ID, 0x01)
        self.ant.set_channel_search_timeout(0xFF)
        self.ant.set_channel_id(device_id, self.HEART_RATE_SENSOR, 0)
        self.ant.set_channel_period(8070)
        self.ant.set_channel_rf_freq(57)
        self.ant.open_channel()

    def pump(self):
        return self.ant.pump()

    def stop(self):
        self.ant.close_channel()
        self.ant.unassign_channel()
        self.ant.stop()

def ant_worker():
    DEVICE_ID = 0xE55F  # FIXME
    device = HeartRate(DEVICE_ID)
    STATE.last_update = None
    while STATE.running:
        while device.pump():
            STATE.last_update = pygame.time.get_ticks()
        if STATE.last_update != None and 0.001 * (pygame.time.get_ticks() - STATE.last_update) > 30:
            STATE.last_update = None
            STATE.heart_rate = None
    device.stop()

def main():
    ant_worker_thread = threading.Thread(target=ant_worker, name="ant_worker")
    ant_worker_thread.start()

    pygame.init()

    screen = pygame.display.set_mode((1080, 170))
    pygame.display.set_caption("Heart Rate Monitor")

    font = pygame.freetype.Font("MPLUSRounded1c-ExtraBold.ttf", 160)

    beat = 0
    clock = pygame.time.Clock()
    while STATE.running:
        try:
            screen.fill((0, 0, 0))

            elapsed_time = 0.001 * clock.tick(60)
            heart_rate = (STATE.heart_rate or 60)
            heart_speed = heart_rate / 60
            heart_amplitude = min(1.0, max(0.2, (heart_rate - 120) / 60))
            beat += heart_speed * elapsed_time
            while beat >= 1:
                beat -= 1
            heart_size = (6 - heart_amplitude + heart_amplitude * math.cos(2 * math.pi * beat)) * 30
            heart_rect = font.get_rect(HEART, size=heart_size)
            font.render_to(screen, (85 - 0.5 * heart_rect.width, 85 - 0.5 * heart_rect.height), HEART, COLOR, size=heart_size)

            if STATE.heart_rate == None:
                heart_rate_text = "?"
            else:
                heart_rate_text = str(STATE.heart_rate)
            for i in range(len(heart_rate_text)):
                digit = heart_rate_text[i]
                rect = font.get_rect(digit)
                width = rect.width
                if digit == '1':
                    width += 5
                offset = (420 - 60 * len(heart_rate_text) + 110 * i - 0.5 * width, 25)
                font.render_to(screen, offset, digit, COLOR)
                
            pygame.display.flip()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    STATE.running = False
        except KeyboardInterrupt:
            STATE.running = False

    pygame.display.quit()
    ant_worker_thread.join()

if __name__ == "__main__":
    main()


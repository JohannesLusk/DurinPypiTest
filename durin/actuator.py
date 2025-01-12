from abc import abstractmethod
from dataclasses import dataclass
import queue
import struct
from typing import ByteString, TypeVar

import numpy as np
from durin import io

from durin.io import SENSORS
from durin.io.network import TCPLink
from durin.controller import *


T = TypeVar("T")


@dataclass
class Command:
    pass

    @abstractmethod
    def encode() -> ByteString:
        pass


class PowerOff(Command):
    def __init__(self):
        self.cmd_id = 1

    def encode(self):
        data = bytearray([0] * 1)
        data[0] = self.cmd_id

        return data


class Move(Command):
    def __init__(self, vel_x: int, vel_y: int, rot: int):
        """
        Moves Durin

        Arguments:
            vel_x (int): Velocity in the x axis
            vel_y (int): Velocity in the y axis
            rot (int): Degrees per second
        """
        self.cmd_id = 2
        self.vel_x = int(vel_x)
        self.vel_y = int(vel_y)
        self.rot = int(rot)

    def encode(self):
        data = bytearray([0] * 7)
        data[0] = self.cmd_id
        data[1:3] = bytearray(
            struct.pack("<h", self.vel_x)
        )  # short (int16) little endian
        data[3:5] = bytearray(
            struct.pack("<h", self.vel_y)
        )  # short (int16) little endian
        data[5:7] = bytearray(
            struct.pack("<h", -self.rot)
        )  # short (int16) little endian

        return data

    def __repr__(self) -> str:
        return f"Move({self.vel_x}, {self.vel_y}, {-self.rot})"


class MoveWheels(Command):
    """
    Moves individual wheels on Durin

    Arguments:
        ne (float): North east wheel
        nw (float): North west wheel
        sw (float): South west wheel
        se (float): South east wheel
    """

    def __init__(self, ne, nw, sw, se):
        self.cmd_id = 3
        self.ne = int(ne)
        self.nw = int(nw)
        self.sw = int(sw)
        self.se = int(se)

    def encode(self):
        data = bytearray([0] * 9)
        data[0] = self.cmd_id
        data[1:3] = bytearray(
            struct.pack("<h", -self.se)
        )  # short (int16) little endian
        data[3:5] = bytearray(
            struct.pack("<h", self.sw)
        )  # short (int16) little endian
        data[5:7] = bytearray(
            struct.pack("<h", -self.ne)
        )  # short (int16) little endian
        data[7:9] = bytearray(
            struct.pack("<h", self.nw)
        )  # short (int16) little endian
        return data

    def __repr__(self) -> str:
        return f"MoveWheels({self.ne}, {self.nw}, {self.sw}, {self.se})"


class PollAll(Command):
    def __init__(self):
        self.cmd_id = 16

    def encode(self):
        data = bytearray([0] * 1)
        data[0] = self.cmd_id

        return data


class PollSensor(Command):
    def __init__(self, sensor_id):
        self.cmd_id = 17
        self.sensor_id = int(sensor_id)

    def encode(self):
        data = bytearray([0] * 2)
        data[0] = self.cmd_id
        data[1:2] = self.sensor_id.to_bytes(
            1, "little"
        )  # integer (uint8) little endian

        return data


class StreamOn(Command):
    def __init__(self, host, port, period):
        self.cmd_id = 18
        self.host = host
        self.port = port
        self.period = period

    def encode(self):
        data = bytearray([0] * 9)
        data[0] = self.cmd_id
        host = self.host.split(".")
        data[1] = int(host[0])
        data[2] = int(host[1])
        data[3] = int(host[2])
        data[4] = int(host[3])
        data[5:7] = self.port.to_bytes(2, "little")
        data[7:9] = self.period.to_bytes(2, "little")
        return data


class StreamOff(Command):
    def __init__(self):
        self.cmd_id = 19

    def encode(self):
        data = bytearray([0] * 1)
        data[0] = self.cmd_id

        return data


class DurinActuator:
    def __init__(self, tcp_link: TCPLink):
        self.tcp_link = tcp_link

    def __call__(self, action: Command, timeout: float = 0.05):
        command_bytes = action.encode()
        reply = []
        if command_bytes[0] == 0:
            return reply

        try:
            self.tcp_link.send(command_bytes, timeout=timeout)
        except queue.Full:
            pass

        return None

    def read(self):
        reply = self.tcp_link.read()
        if reply is not None:
            return io.decode(reply)
        else:
            return None

    def start(self):
        self.tcp_link.start()

    def stop(self):
        self.tcp_link.stop()

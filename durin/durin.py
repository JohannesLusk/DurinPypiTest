import logging
import multiprocessing
import socket
import sys
from typing import Optional, Tuple

from .actuator import DurinActuator
from .sensor import DurinSensor, Observation, DVSSensor
from .network import DVSClient, TCPLink, UDPLink
from .common import *
from .cli import *

import torch


class Durin:
    def __init__(
        self,
        durin_ip: str,
        dvs_ip: str,
        durin_port: int = 2300,
        device: str = "cpu",
        stream_command: Optional[StreamOn] = None,
        spawn_cli: bool = True,
    ):
        self.tcp_link = TCPLink(durin_ip, durin_port)
        self.udp_link = UDPLink()
        self.sensor = DurinSensor(self.udp_link)
        self.dvs_client = DVSClient(dvs_ip, durin_port + 1)
        self.actuator = DurinActuator(self.tcp_link, self.udp_link)
        self.dvs = DVSSensor((640, 480), device, 4301)
        self.spawn_cli = spawn_cli
        std_in = sys.stdin.fileno()
        self.cli_process = multiprocessing.Process(
            target=run_cli, args=(self.actuator, std_in)
        )

        if stream_command is not None:
            self.stream_command = stream_command
        else:
            response_ip = get_ip()
            self.stream_command = StreamOn(response_ip, 4300, 50)

    def __enter__(self):
        # Controller
        self.tcp_link.start_com()
        self(self.stream_command)

        # DVS
        self.dvs.start_stream()
        self.dvs_client.start_stream(
            self.stream_command.host, self.stream_command.port + 1
        )
        logging.debug(
            f"DVS sensor on {self.stream_command.host}:{self.stream_command.port + 1}"
        )

        # CLI
        if self.spawn_cli:
            self.cli_process.start()
        return self

    def __exit__(self, e, b, t):
        self.tcp_link.stop_com()
        self.udp_link.stop_com()
        self.dvs_client.stop_stream()
        self.dvs.stop_stream()

        if self.spawn_cli:
            self.cli_process.terminate()
            self.cli_process.join()

    def __call__(self, command):
        reply_bytes = self.actuator(command)
        return reply_bytes

    def sense(self) -> Tuple[Observation, torch.Tensor]:
        durin = self.sensor.read()
        dvs = self.dvs.read()
        return (durin, dvs)

from abc import abstractmethod
import ipaddress
import logging
import subprocess
import socket
from multiprocessing import Process
import time
from typing import Optional

from durin.controller import dvs


class Streamer:
    @abstractmethod
    def start_stream(self, host: str, port: int):
        pass

    @abstractmethod
    def stop_stream(self):
        pass


def _log_thread(pipe):
    with pipe:
        for line in iter(pipe.readline, ""):
            if len(line) > 0:
                logging.warning(f"AESTREAM: {line.decode('utf-8')}")


class AEStreamer(Streamer):
    def __init__(self) -> None:
        self.aestream = None
        self.aestream_log = None
        # Test that aestream exists
        if subprocess.run(["which", "aestream"]).returncode > 0:
            raise RuntimeError("No aestream binary found on path")
        # Test that cameras exist
        try:
            self.camera_string = dvs.identify_inivation_camera()
        except RuntimeError as e:
            logging.warning("No DVX camera found on startup", e)

    def start_stream(self, host: str, port: int):
        if self.aestream is not None:
            self.stop_stream()

        # Get the camera string
        try:
            self.camera_string = dvs.identify_inivation_camera()
            logging.debug(f"Camera found at {self.camera_string}")
        except Exception as e:
            logging.warning("No camera found", e)
            return

        command = f"aestream input {self.camera_string} output udp {host} {port}"
        self.aestream = subprocess.Popen(
            command.split(" "), stderr=subprocess.STDOUT, stdout=subprocess.PIPE
        )
        self.aestream_log = Process(target=_log_thread, args=(self.aestream.stdout,))
        self.aestream_log.start()

        logging.debug(f"Sending DVS to {host}:{port} with command\n\t{command}")

    def stop_stream(self):
        try:
            if self.aestream is not None:
                self.aestream.terminate()
                self.aestream.wait(1)
                self.aestream.kill()
                self.aestream.wait()
            if self.aestream_log is not None:
                self.aestream_log.terminate()
                self.aestream_log.join()
            subprocess.run(["pkill", "aestream"])  # Kill remaining aestream processes
            self.aestream = None
            self.aestream_log = None
        except Exception as e:
            logging.warning("Error when closing aestream", e)


class DVSServer:
    def __init__(self, port: int, streamer: Optional[Streamer] = None) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        logging.debug(f"Listening to 0.0.0.0 {port}")
        self.sock.bind(("0.0.0.0", port))
        self.sock.listen(1)
        self.streamer = streamer if streamer is not None else AEStreamer()
        self.clients = []
        self.is_streaming = False

    def listen(self):
        self.is_streaming = True
        while self.is_streaming:
            connection, address = self.sock.accept()
            logging.debug("New client connection established")
            self.streamer.stop_stream()
            self.close_clients()
            thread = Process(target=self.client_loop, args=(connection, self.streamer))
            thread.start()
            self.clients.append(thread)

    def close(self):
        self.is_streaming = False
        self.close_clients()
        self.sock.close()

    def close_clients(self):
        logging.debug(f"Closing {len(self.clients)} old clients")
        for thread in self.clients:
            try:
                thread.terminate()
                thread.join()
            except:
                pass

    @staticmethod
    def client_loop(connection, streamer):
        try:
            while True:
                msg = connection.recv(512)
                DVSServer._parse_command(msg, streamer)
        except Exception as e:
            streamer.stop_stream()
            logging.warning("Error when receiving data", e)

    @staticmethod
    def _parse_command(data, streamer):
        if len(data) == 0:
            return
        logging.debug(f"Received command: {len(data)} bytes of type {data[0]}")
        if data[0] == 0:  # Start streaming
            host_ip = ipaddress.ip_address(int.from_bytes(data[1:5], "little"))
            port = int.from_bytes(data[5:7], "little")
            logging.debug(f"Streaming to {host_ip}:{port}")
            streamer.start_stream(str(host_ip), port)
        else:  # Stop streaming
            logging.debug(f"Terminating streaming")
            streamer.stop_stream()


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    server = DVSServer(2301)
    try:
        server.listen()
    finally:
        server.close()

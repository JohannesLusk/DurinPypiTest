from abc import ABC, abstractmethod
import multiprocessing
import time
from typing import Generic, NamedTuple, Tuple, TypeVar

import numpy as np
from durin.io import SENSORS

from durin.io.network import UDPLink
from durin.io.runnable import RunnableConsumer
from durin.io.ringbuffer import RingBuffer

T = TypeVar("T")


class Observation(NamedTuple):
    tof: np.ndarray = np.zeros((8, 8, 8))
    charge: float = 0
    voltage: float = 0
    imu: np.ndarray = np.zeros((3, 3))
    uwb: float = 0
    frequency: float = 0

    def __repr__(self) -> str:
        tof_str = " ".join([f"{x.mean():.0f}±{x.std():.0f}" for x in self.tof])
        return f"Durin {self.battery}%\n\tIMU: {self.imu}\n\tTOF: {tof_str}"


class Sensor(ABC, Generic[T]):
    @abstractmethod
    def read(self) -> T:
        pass


class DurinSensor(RunnableConsumer, Sensor[Observation]):
    def __init__(self, link: UDPLink):
        self.link = link
        context = multiprocessing.get_context("spawn")
        self.tof = context.Array("f", 8 * 8 * 8)
        self.charge = context.Value("f", 0)
        self.voltage = context.Value("f", 0)
        self.imu = context.Array("d", 3 * 3)
        self.uwb = context.Value("d", 0)
        self.ringbuffer = context.Array("d", 50)
        self.ringbuffer_idx = context.Value("i", 0)
        self.timestamp_update = context.Value("d", time.time())

        super().__init__(
            self.link.buffer,
            self.tof,
            self.charge,
            self.voltage,
            self.imu,
            self.uwb,
            self.ringbuffer,
            self.ringbuffer_idx,
            self.timestamp_update,
        )

    def read(self) -> Observation:
        tof = np.frombuffer(self.tof.get_obj(), dtype=np.float32).reshape((8, 8, 8))
        imu = np.frombuffer(self.imu.get_obj()).reshape((3, 3))
        frequency = 1 / (np.frombuffer(self.ringbuffer.get_obj()).mean() + 1e-7)
        return Observation(
            tof,
            charge=self.charge.value,
            voltage=self.voltage.value,
            imu=imu,
            uwb=self.uwb.value,
            frequency=frequency,
        )

    def start(self):
        super().start()
        self.link.start()

    def stop(self):
        super().stop()
        self.link.stop()

    def consume(
        self,
        item,
        tof,
        charge,
        voltage,
        imu,
        uwb,
        ringbuffer,
        ringbuffer_idx,
        timestamp_update,
    ):
        (sensor_id, data) = item
        if sensor_id >= SENSORS["tof_a"] and sensor_id <= SENSORS["tof_d"]:
            # Multiply by two since each package contains data from two sensors
            idx = (sensor_id - SENSORS["tof_a"]) * 2
            # We assign a flattened (2, 8, 8) array
            tof.get_obj()[idx * 64 : (idx + 2) * 64] = data.reshape(-1)
        if sensor_id == SENSORS["misc"]:
            charge.value = data[0]
            voltage.value = data[1]
            imu.get_obj()[:] = data[2].reshape(-1)
        # if sensor_id == SENSORS["uwb"]:
        #     obs.uwb[:] = data

        # Update Hz
        time_now = time.time()
        buffer = RingBuffer(np.frombuffer(ringbuffer.get_obj()))
        buffer.counter = ringbuffer_idx.value
        buffer.append(time_now - timestamp_update.value)
        ringbuffer.get_obj()[:] = buffer.buffer
        ringbuffer_idx.value = buffer.counter
        timestamp_update.value = time_now

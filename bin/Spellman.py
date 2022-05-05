#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Tango Device server for the custom BLiX Spellman controller"""

__author__ = "Jonas Grage"
__copyright__ = "Copyright 2020"
__license__ = "GPLv3"
__version__ = "1.0"
__maintainer__ = "Jonas Grage"
__email__ = "grage@physik.tu-berlin.de"
__status__ = "Production"

import sys
import socket
import math

from time import time, sleep
from functools import partial

from tango import Attr, AttrQuality, AttrWriteType, DispLevel, DevState, DevString, DebugIt
from tango.server import Device, attribute, command, pipe, device_property

LF = '\x0A'


class DACError(Exception):
    def __init__(self, dac_value):
        self.message = "DAC Value {0} out of range!".format(dac_value)
        super().__init__(self.message)
        
        
class VoltageExceededError(DACError):
    pass
    
    
class CurrentExceededError(DACError):
    pass
    
    
class SpellmanEthernetInterface:
    def __init__(self, HOST, PORT):
        self.interface = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        IP = socket.gethostbyname(HOST)
        
        try:
            self.interface.connect((IP, PORT))
            
        except socket.error as exc:
            raise exc
            
            
    def receive(self):
        sleep(0.01)
        data = self.interface.recv(1024)
        
        if LF.encode() in data:
            response, *rest = data.split(LF.encode())
            return response.decode()
        else:
            raise SocketError
    
    
    def send(self, mnemonic: str):
        tmp = [mnemonic]
        tmp.append(LF)
        commandstring = ''.join(tmp)
        
        # Send command to device
        self.interface.send(commandstring.encode())

        
    def __del__(self): 
        self.interface.close()


class Spellman(Device):
    host = device_property(dtype=str)
    port = device_property(dtype=int, default_value=23)
    
    voltage_range = device_property(dtype=float)            # full output range in kV
    current_range = device_property(dtype=float)            # full output range in mA
    filament_current_range = device_property(dtype=float)   # full range in mA
    
    dac_resolution = device_property(dtype=int, default_value=256)
    adc_resolution = device_property(dtype=int, default_value=1024)
    
    
    def set_voltage(self, voltage):
        dac_value = math.floor(voltage / self._voltage_set_factor)
        
        """
        Check if setpoint is within DAC range 
        """
        if dac_value in range(0, self.dac_resolution):
            setpoint = (1.0 * dac_value * self._voltage_set_factor)
        else:
            raise VoltageExceededError(dac_value)
        
        
        command = ":V {:d}".format(dac_value)
        self.connection.send(command)
        response = self.connection.receive()
        
        """
        Update voltage setpoint attribute if the response is valid
        """
        if response == "OK":
            self._voltage_setpoint = setpoint
            return
        else:
            #ToDo: Create custom exception
            raise ValueError
            
            
    def set_current(self, current):
        dac_value = math.floor(current / self._current_set_factor)
        
        """
        Check if setpoint is within DAC range 
        """
        if dac_value in range(0, self.dac_resolution):
            setpoint = (1.0 * dac_value * self._current_set_factor)
        else:
            raise CurrentExceededError(dac_value)
            
            
        command = ":C {:d}".format(dac_value)
        self.connection.send(command)
        response = self.connection.receive()
        
        """
        Update current setpoint attribute if the response is valid
        """
        if response == "OK":
            self._current_setpoint = setpoint
            return
        else:
            #ToDo: Create custom exception
            raise ValueError
            
            
    @attribute(label="Voltage Setpoint", unit="kV", dtype=float)
    def voltage_setpoint(self):
        return self._voltage_setpoint
        
        
    @voltage_setpoint.write
    def voltage_setpoint(self, value):
        try:
            self.info_stream("set psu voltage setpoint to {0}kV".format(value))
            self.set_voltage(value)
        
        except Exception as ex:
            self.error_stream(ex.message)
            
            
    @attribute(label="Current Setpoint", unit="mA", dtype=float)
    def current_setpoint(self):
        return self._current_setpoint
        
        
    @current_setpoint.write
    def current_setpoint(self, value):
        try:
            self.info_stream("set psu current setpoint to {0}kV".format(value))
            self.set_current(value)
        
        except Exception as ex:
            self.error_stream(ex.message)
            
            
    @attribute(label="Voltage", unit="kV", dtype=float)
    def voltage(self):
        self.info_stream("get psu voltage readback")
        command = ":V?"
        self.connection.send(command)
        response = float(self.connection.receive())
        return response * self._voltage_get_factor
        
        
    @attribute(label="Current", unit="mA", dtype=float)
    def current(self):
        self.info_stream("get psu current readback")
        command = ":C?"
        self.connection.send(command)
        response = float(self.connection.receive())
        return response * self._current_get_factor
        
        
    @attribute(label="Filament Current", unit="mA", dtype=float)
    def filament(self):
        self.info_stream("get filament current readback")
        command = ":FIL?"
        self.connection.send(command)
        response = float(self.connection.receive())
        return response * self._filament_current_get_factor
        
        
    @attribute(label="Interlock Status", dtype=str)
    def interlock(self):
        self.info_stream("get interlock status")
        command = ":ILOCK?"
        self.connection.send(command)
        response = self.connection.receive()
        if response == "open\n":
            self._current_setpoint = 0.0
            self._voltage_setpoint = 0.0
        return response
        
        
    @command(dtype_out=str, doc_out="Confirm action")
    def enable(self):
        self.info_stream("enable DAC outputs")
        mnemonic = ":ON"
        
        self.set_voltage(0.0)
        self.set_current(0.0)
        self.connection.send(mnemonic)
        response = self.connection.receive()
        return response
        
        
    @command(dtype_out=str, doc_out="Confirm action")
    def disable(self):
        self.info_stream("disable DAC outputs")
        mnemonic = ":OFF"
        self.connection.send(mnemonic)
        response = self.connection.receive()
        return response
        
        
    @command(dtype_out=str, doc_out="Get the ID of the controller.")
    def IDN(self):
        self.info_stream("send identification request")
        mnemonic = '*IDN?'
        self.connection.send(mnemonic)
        response = self.connection.receive()
        return response
        
        
    def init_device(self):
        self.info_stream("call init_device() ({0})".format(self.__class__.__name__))
        Device.init_device(self)
        self.set_state(DevState.INIT)
        
        # Establish connection to controller
        try:
            self.connection = SpellmanEthernetInterface(self.host, self.port)
            sleep(1)
            self.info_stream("connected to {0} device at {1}:{2:d}".format(self.__class__.__name__, self.host, self.port))
            
            self._voltage_set_factor = 1.0*self.voltage_range/self.dac_resolution
            self._voltage_get_factor = 1.0*self.voltage_range/self.adc_resolution
    
            self._current_set_factor = 1.0*self.current_range/self.dac_resolution
            self._current_get_factor = 1.0*self.current_range/self.adc_resolution
            self._filament_current_get_factor = 1.0*self.filament_current_range/self.adc_resolution
    
            self._current_setpoint = 0.0
            self._voltage_setpoint = 0.0
            
            self.set_state(DevState.ON)
        
        # Exit if connection can't be established
        except Exception as exc:
            self.error_stream("error in init_device(): {0}".format(exc))
            self.set_state(DevState.OFF)
            sys.exit()
            
if __name__ == "__main__":
    Spellman.run_server()

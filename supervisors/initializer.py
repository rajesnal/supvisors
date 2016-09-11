#!/usr/bin/python
#-*- coding: utf-8 -*-

# ======================================================================
# Copyright 2016 Julien LE CLEACH
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ======================================================================

from supervisor.loggers import getLogger
from supervisor.xmlrpc import Faults, RPCError

from supervisors.addressmapper import AddressMapper
from supervisors.context import Context
from supervisors.deployer import Deployer
from supervisors.infosource import SupervisordSource
from supervisors.listener import SupervisorListener
from supervisors.options import SupervisorsOptions
from supervisors.parser import Parser
from supervisors.publisher import EventPublisher
from supervisors.rpcrequests import RpcRequester
from supervisors.statemachine import FiniteStateMachine
from supervisors.statistics import StatisticsCompiler


class Supervisors(object):
    """ The Supervisors class  """

    # logger output
    LOGGER_FORMAT = '%(asctime)s %(levelname)s %(message)s\n'

    def __init__(self, supervisord):
        # store this instance in supervisord to ensure persistence
        supervisord.supervisors = self
        # get options from config file
        self.options = SupervisorsOptions()
        # create logger
        stdout = supervisord.options.nodaemon
        self.logger = getLogger(self.options.logfile, self.options.loglevel, Supervisors.LOGGER_FORMAT, True, self.options.logfile_maxbytes, self.options.logfile_backups, stdout)
        # configure supervisor info source
        self.info_source = SupervisordSource(supervisord)
        # set addresses and check local address
        self.address_mapper = AddressMapper(self.logger)
        self.address_mapper.addresses = self.options.address_list
        if not self.address_mapper.local_address:
            raise RPCError(Faults.SUPERVISORS_CONF_ERROR, 'local host unexpected in address list: {}'.format(self.options.address_list))
        # create context data
        self.context = Context(self)
        # create event publisher
        self.publisher = EventPublisher(self)
        # create deployer
        self.deployer = Deployer(self)
        # create statistics handler
        self.statistician = StatisticsCompiler(self)
        # create RPC requester
        self.requester = RpcRequester(self)
        # create state machine
        self.fsm = FiniteStateMachine(self)
        # check parsing
        try:
            self.parser = Parser(self)
        except:
            raise RPCError(Faults.SUPERVISORS_CONF_ERROR, 'cannot parse deployment file: {}'.format(self.options.deployment_file))
        # create event subscriber
        self.listener = SupervisorListener(self)
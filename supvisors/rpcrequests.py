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

import xmlrpclib

from supervisor.xmlrpc import SupervisorTransport


def getRPCInterface(address, env):
    """ The getRPCInterface creates a proxy to a supervisor XML-RPC server.
    Information about the HTTP configuration is required in env. """
    # get configuration info from env
    serverurl = env['SUPERVISOR_SERVER_URL']
    username = env.get('SUPERVISOR_USERNAME', '')
    password = env.get('SUPERVISOR_PASSWORD', '')
    # check that Supervisor is configured in HTTP
    if not serverurl.startswith('http://'):
        raise ValueError('Incompatible protocol for Supvisors: serverurl={}'.format(serverurl))
    # replace address in URL
    serverurl = serverurl.split(':')
    serverurl[1] = '//' + address
    serverurl = ':'.join(serverurl)
    # create transport and return proxy
    transport = SupervisorTransport(username, password, serverurl)
    return xmlrpclib.ServerProxy('http://{}'.format(address), transport)


class RpcRequester(object):
    """ The RpcRequester is used to perform the XML-RPC used internally by Supvisors.
    It either uses the internal interface or a proxy, depending if the target address
    is the local address or not."""

    def __init__(self, supvisors):
        """ The constructor keeps a reference to the Supvisors insternal structure. """
        self.supvisors = supvisors

    # utilities to determine if using XmlRpcClient or internal handler directly
    def use_proxy(self, address):
        """ Return True if RPC address is NOT the local address. """
        return address != self.supvisors.address_mapper.local_address

    def get_proxy(self, address):
        """ Return the Supervisor XML-RPC general proxy. """
        return getRPCInterface(address, self.supvisors.info_source.get_env())

    def supervisor_proxy(self, address):
        """ Return Supervisor interface and proxy (so as is it not destroyed when exiting). """
        proxy = self.get_proxy(address)
        return proxy, proxy.supervisor

    def supvisors_proxy(self, address):
        """ Return Supvisors interface and proxy (so as is it not destroyed when exiting). """
        proxy = self.get_proxy(address)
        return proxy, proxy.supvisors

    def internal_supervisor(self):
        """ Return the supervisor interface, taken directly from the supervisor internal structure. """
        return None, self.supvisors.info_source.supervisor_rpc_interface

    def internal_supvisors(self):
        """ Return the supvisors interface, taken directly from the supervisor internal structure. """
        return None, self.supvisors.info_source.supvisors_rpc_interface

    def get_supervisor(self, address):
        """ Depending if the address is the local address or not,
        return the Supervisor internal interface or a proxy to the remote Supervisor interface. """
        return self.supervisor_proxy(address) if self.use_proxy(address) else self.internal_supervisor()

    def get_supvisors(self, address):
        """ Depending if the address is the local address or not,
        return the Supvisors internal interface or a proxy to the remote Supvisors interface. """
        return self.supvisors_proxy(address) if self.use_proxy(address) else self.internal_supvisors()

    # Requests
    def all_process_info(self, address):
        """ Shortcut to the getAllProcessInfo XML-RPC. """
        proxy, supervisor = self.get_supervisor(address)
        return supervisor.getAllProcessInfo()

    def internal_start_process(self, address, program, extra_args):
        """ Shortcut to the start_args XML-RPC. """
        proxy, supvisors = self.get_supvisors(address)
        return supvisors.start_args(program, extra_args, False)

    def address_info(self, address, remote_address):
        """ Shortcut to the get_address_info XML-RPC. """
        proxy, supvisors = self.get_supvisors(address)
        return supvisors.get_address_info(remote_address)

    def start_process(self, address, program, wait):
        """ Shortcut to the startProcess XML-RPC. """
        proxy, supervisor = self.get_supervisor(address)
        return supervisor.startProcess(program, wait)

    def stop_process(self, address, program, wait):
        """ Shortcut to the stopProcess XML-RPC. """
        proxy, supervisor = self.get_supervisor(address)
        return supervisor.stopProcess(program, wait)

    def restart(self, address):
        """ Shortcut to the restart XML-RPC. """
        proxy, supervisor = self.get_supervisor(address)
        return supervisor.restart()

    def shutdown(self, address):
        """ Shortcut to the shutdown XML-RPC. """
        proxy, supervisor = self.get_supervisor(address)
        return supervisor.shutdown()

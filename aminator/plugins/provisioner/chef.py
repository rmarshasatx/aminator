# -*- coding: utf-8 -*-

#
#
#  Copyright 2013 Riot Games
#
#     Licensed under the Apache License, Version 2.0 (the "License");
#     you may not use this file except in compliance with the License.
#     You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.
#
#

"""
aminator.plugins.provisioner.chef
================================
basic chef provisioner
"""
import logging
import os
from collections import namedtuple

from aminator.plugins.provisioner.linux import BaseLinuxProvisionerPlugin
from aminator.util.linux import command
from aminator.util.linux import short_circuit_files, rewire_files
from aminator.config import conf_action

__all__ = ('ChefProvisionerPlugin',)
log = logging.getLogger(__name__)
CommandResult = namedtuple('CommandResult', 'success result')
CommandOutput = namedtuple('CommandOutput', 'std_out std_err')

class ChefProvisionerPlugin(BaseLinuxProvisionerPlugin):
    """
    ChefProvisionerPlugin takes the majority of its behavior from BaseLinuxProvisionerPlugin
    See BaseLinuxProvisionerPlugin for details
    """
    _name = 'chef'
    _default_chef_version = '10.18.0'

    def add_plugin_args(self):
        context = self._config.context
        chef_config = self._parser.add_argument_group(title='Chef Solo Options', description='Options for the chef solo provisioner')

        chef_config.add_argument('-a', '--alias', dest='alias', help='Alias for AMI naming. (default: runlist)',
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('--payload-url', dest='payload_url', help='Location to fetch the payload from (required)',
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('--payload-version', dest='payload_version', help='Payload version (default: 0.0.1)',
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('--payload-release', dest='payload_release', help='Payload release (default: 0)',
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('--chef-version', dest='chef_version', help='Version of chef to install (default: %s)' % self._default_chef_version,
                                 action=conf_action(self._config.plugins[self.full_name]))
        

    def get_config_value(name, default):
        config = self._config.plugins[self.full_name]

        if config.get(name):
            return config.get(name)
        
        self._config.plugins[self.full_name].__setattr__(name, default)
        return default


    def _refresh_package_metadata(self):
        """
        Fetch the latest version of cookbooks and JSON node info
        """
        context         = self._config.context
        config          = self._config.plugins[self.full_name]

        # This is a required arg, so no default values
        payload_url     = config.get('payload_url')

        # Fetch config values if provided, otherwise set them to their default values
        alias           = self.get_config_value('alias', context.package.arg)
        payload_version = self.get_config_value('payload_version', '0.0.1')
        payload_release = self.get_config_value('payload_release', '0')
        chef_version    = self.get_config_value('chef_version', self._default_chef_version)

        if not payload_url:
            log.critical('Missing required argument for chef provisioner: --payload-url')
            return CommandResult(False, CommandOutput('', 'Missing required argument for chef provisioner: --payload-url'))

        if os.path.exists("/opt/chef/bin/chef-solo"):
            log.debug('Omnibus chef is already installed, skipping install')
        else:
            log.debug('Installing omnibus chef-solo')
            result = install_omnibus_chef(chef_version)
            if not result.success:
                log.critical('Failed to install chef')
                return result

        log.debug('Downloading payload from %s' % payload_url)
        payload_result = fetch_chef_payload(payload_url)

        return payload_result

    def _provision_package(self):
        config          = self._config.plugins[self.full_name]

        pass
        context = self._config.context
        log.debug('Running chef-solo for runlist items: %s' % context.package.arg)
        chef_result = chef_solo(context.package.arg)

        return chef_result

    def _store_package_metadata(self):
        context = self._config.context
        config = self._config.plugins[self.full_name]

        context.package.attributes = { 'name': config.get('alias'), 'version': config.get('payload_version'), 'release': config.get('payload_release') }

    def _deactivate_provisioning_service_block(self):
        """
        Prevent packages installing the chroot from starting
        For RHEL-like systems, we can use short_circuit which replaces the service call with /bin/true
        """
        config = self._config.plugins[self.full_name]
        files = config.get('short_circuit_files', [])
        if files:
            if not short_circuit_files(self._mountpoint, files):
                log.critical('Unable to short circuit {0} to {1}')
                return False
            else:
                log.debug('Files short-circuited successfully')
                return True
        else:
            log.debug('No short circuit files configured')
            return True

    def _activate_provisioning_service_block(self):
        """
        Enable service startup so that things work when the AMI starts
        For RHEL-like systems, we undo the short_circuit
        """
        config = self._config.plugins[self.full_name]
        files = config.get('short_circuit_files', [])
        if files:
            if not rewire_files(self._mountpoint, files):
                log.critical('Unable to rewire {0} to {1}')
                return False
            else:
                log.debug('Files rewired successfully')
                return True
        else:
            log.debug('No short circuit files configured, no rewiring done')
        return True


@command()
def curl_download(src, dst):
    return 'curl {0} -o {1}'.format(src, dst)


@command()
def install_omnibus_chef(chef_version = None):
    curl_download('https://www.opscode.com/chef/install.sh', '/tmp/install-chef.sh')

    if chef_version:
        return 'bash /tmp/install-chef.sh -v {0}'.format(chef_version)
    else:
        return 'bash /tmp/install-chef.sh'


@command()
def chef_solo(runlist):
    return 'chef-solo -j /tmp/node.json -c /tmp/solo.rb -o {0}'.format(runlist)


@command()
def fetch_chef_payload(payload_url):
    curl_download(payload_url, '/tmp/chef_payload.tar.gz')

    return 'tar -C / -xf /tmp/chef_payload.tar.gz'.format(payload_url)

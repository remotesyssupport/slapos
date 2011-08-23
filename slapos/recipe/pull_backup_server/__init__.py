##############################################################################
#
# Copyright (c) 2010 Vifib SARL and Contributors. All Rights Reserved.
#
# WARNING: This program as such is intended to be used by professional
# programmers who take the whole responsibility of assessing all potential
# consequences resulting from its eventual inadequacies and bugs
# End users who are looking for a ready-to-use solution with commercial
# guarantees and support are strongly adviced to contract a Free Software
# Service Company
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
##############################################################################
from slapos.recipe.librecipe import BaseSlapRecipe

import os
import subprocess
import pkg_resources
import zc.buildout
import sys

class Recipe(BaseSlapRecipe):

  # Kinda like C macro to avoid magic number/expression
  SSH_KEY_BIT_SIZE = 2048
  SSH_KEY_TYPE = 'rsa'
  SSH_KEY_PUBLIC_NAME = staticmethod(
    lambda name: '%s.pub' % name
  )

  def getTemplateFilename(self, template_name):
    return pkg_resources.resource_filename(__name__,
        'template/%s' % template_name)

  def _install(self):
    self.path_list = []

    self.requirements, self.ws = self.egg.working_set()

    self.cron_d = self.installCrond()

    self.ssh_conf = self.installOpenSSHClient()

    self.setConnectionDict(dict(
      public_ssh_key=ssh_conf['sshpublic_key_value']
    ))

    return self.path_list

  def installCrond(self):
    timestamps = self.createDataDirectory('cronstamps')
    cron_output = os.path.join(self.log_directory, 'cron-output')
    self._createDirectory(cron_output)
    catcher = zc.buildout.easy_install.scripts([('catchcron',
      __name__ + '.catdatefile', 'catdatefile')], self.ws, sys.executable,
      self.bin_directory, arguments=[cron_output])[0]
    self.path_list.append(catcher)
    cron_d = os.path.join(self.etc_directory, 'cron.d')
    crontabs = os.path.join(self.etc_directory, 'crontabs')
    self._createDirectory(cron_d)
    self._createDirectory(crontabs)
    wrapper = zc.buildout.easy_install.scripts([('crond',
      'slapos.recipe.librecipe.execute', 'execute')], self.ws, sys.executable,
      self.wrapper_directory, arguments=[
        self.options['dcrond_binary'].strip(), '-s', cron_d, '-c', crontabs,
        '-t', timestamps, '-f', '-l', '5', '-M', catcher]
      )[0]
    self.path_list.append(wrapper)
    return cron_d

  def installOpenSSHClient(self):
    # Get parameters of the instance
    try:
      instance_pubkey = self.parameter_dict['remote_pubkey']
      instance_name = self.parameter_dict['remote_hostname']
    except KeyError as e:
      raise TypeError('The parameter %r was not specified.' % e.args[0])
    # Directories configuration
    sshconf_dir = os.path.join(self.etc_directory, 'ssh')
    self._createDirectory(sshconf_dir)
    sshkey = os.path.join(sshconf_dir, 'key')

    ssh_conf = dict(sshconf_dir=sshconf_dir,
                    sshprivate_key_file=sshkey,
                    sshpublic_key_file=Recipe.SSH_KEY_PUBLIC_NAME(sshkey),
                   )

    # Generate SSH keys
    ssh_keys = (ssh_conf['sshprivate_key_file'],
                ssh_conf['sshpublic_key_file'],
               )

    if not all([os.path.isfile(key) for key in ssh_keys]):
      # If any ssh_key exists
      for file_ in ssh_keys:
        if os.path.exists(file_):
          os.remove(file_)
      # SSH Key generation
      self.logger.debug('SSH Keys generation...')
      returncode = subprocess.call([str(self.options['ssh_keygen_binary']),
                                    '-b', str(Recipe.SSH_KEY_BIT_SIZE),
                                    '-t', str(Recipe.SSH_KEY_TYPE),
                                    '-N', '', # No password
                                    '-C', '', # No comment
                                    '-f', str(ssh_conf['sshprivate_key']),
                                   ])
      if returncode != 0:
        raise OSError('Error during the ssh client key configuration.')
      self.logger.info('SSH Keys generated.')

    else:
      # XXX-Antoine: to avoid "unused option" message
      self.options['ssh_keygen_binary']
      self.logger.info('SSH Keys already generated.')

    # Getting the public ssh key value
    with open(ssh_conf['sshpublic_key_file']) as file_:
      ssh_conf.update(sshpublic_key_value=str(file_.read()).strip())

    self.logger.debug('Known Hosts file generation...')
    known_host_template = self.getTemplateFilename('known_hosts.in')
    known_host_conf = {'name': instance_name,
                       'pubkey': instance_pubkey,
                      }

    known_hosts_file = self.createConfigurationFile(
      os.path.join('ssh', 'known_hosts'),
      self.substituteTemplate(known_host_template,
                              known_host_conf)
    )
    ssh_conf.update(known_hosts_file=known_hosts_file)

    self.logger.info('Known Hosts file generated.')

    return ssh_conf


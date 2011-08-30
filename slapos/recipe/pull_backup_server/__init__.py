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
  DEFAULT_BACKUP_FRENQUENCY = 'daily'
  AVAILABLE_FREQUENCIES = ('hourly',
                           'daily',
                           'weekly',
                           'monthly',
                           'yearly',
                          )

  def getTemplateFilename(self, template_name):
    return pkg_resources.resource_filename(__name__,
        'template/%s' % template_name)

  def _install(self):
    self.path_list = []

    self.requirements, self.ws = self.egg.working_set()

    self.cron_d = self.installCrond()

    self.ssh_conf = self.installOpenSSHClient()

    self.installRdiffBackup()

    self.setConnectionDict(dict(
      public_ssh_key=self.ssh_conf['sshpublic_key_value'],
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
      instance_port = self.parameter_dict['remote_port']
    except KeyError as e:
      raise TypeError('The parameter %r was not specified.' % e.args[0])
    # Directories configuration
    fakehome_dir = os.path.join(self.work_directory, 'home')
    self._createDirectory(fakehome_dir)
    fakessh_dir = os.path.join(fakehome_dir, '.ssh')
    self._createDirectory(fakessh_dir)
    sshkey = os.path.join(fakessh_dir, 'id_rsa')
    sshpubkey = os.path.join(fakessh_dir, 'id_rsa.pub')

    ssh_conf = dict(fakehome_dir=fakehome_dir,
                    fakessh_dir=fakessh_dir,
                    sshprivate_key_file=sshkey,
                    sshpublic_key_file=sshpubkey,
                    hostname=instance_name,
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
      dropbearkey = subprocess.Popen(
        [
          str(self.options['dropbear_keygen_binary']),
          '-t', str(Recipe.SSH_KEY_TYPE),
          '-s', str(Recipe.SSH_KEY_BIT_SIZE),
          '-f', str(ssh_conf['sshprivate_key_file']),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
      )
      stdout, stderr = dropbearkey.communicate()
      returncode = dropbearkey.poll()
      if returncode != 0:
        raise OSError('Error during the ssh client key configuration.')
      # XXX: equivalent to ... | egrep "^ssh-" | head -n 1
      pubkey = [line
                for line in str(stdout).splitlines()
                if line.startswith('ssh-')][0]
      self._writeFile(ssh_conf['sshpublic_key_file'], pubkey)
      self.logger.info('SSH Keys generated.')

    else:
      # XXX-Antoine: to avoid "unused option" message
      self.options['dropbear_keygen_binary']
      self.logger.info('SSH Keys already generated.')

    # Getting the public ssh key value
    with open(ssh_conf['sshpublic_key_file']) as file_:
      ssh_conf.update(sshpublic_key_value=str(file_.read()).strip())

    self.logger.debug('Known Hosts file generation...')
    known_host_template = self.getTemplateFilename('known_hosts.in')
    known_host_conf = {'hostname': instance_name,
                       'port': instance_port,
                       'pubkey': instance_pubkey,
                      }

    known_hosts_file = os.path.join(ssh_conf['fakessh_dir'], 'known_hosts')
    self._writeFile(
      known_hosts_file,
      self.substituteTemplate(known_host_template,
                              known_host_conf)
    )
    ssh_conf.update(known_hosts_file=known_hosts_file)

    self.logger.info('Known Hosts file generated.')

    self.logger.debug('Create SSH client binary')
    ssh_binary_template = self.getTemplateFilename('dbclient.in')
    ssh_binary_conf = {
      'fakehome': ssh_conf['fakehome_dir'],
      'dbclient_binary': self.options['dropbear_client_binary'],
    }
    ssh_binary = os.path.join(self.bin_directory, 'ssh')
    self._writeExecutable(ssh_binary,
                          self.substituteTemplate(ssh_binary_template,
                                                  ssh_binary_conf)
                         )

    ssh_conf.update(ssh_binary=ssh_binary)

    return ssh_conf

  def installRdiffBackup(self):
    try:
      instance_port = self.parameter_dict['remote_port']
    except KeyError as e:
      raise TypeError('The parameter %r was not specified.' % e.args[0])

    frequency = self.parameter_dict.get('frequency', None)
    if frequency is None:
      frequency = Recipe.DEFAULT_BACKUP_FRENQUENCY

    if frequency not in Recipe.AVAILABLE_FREQUENCIES:
      raise ValueError('Frequency parameter not in %r' % \
                       Recipe.AVAILABLE_FREQUENCIES
                      )

    distant_directory = self.parameter_dict.get('remote_directory', None)
    if distant_directory is None:
      raise TypeError("Distant directory wasn't specified.")

    distant_rdiffbackup = self.parameter_dict.get('remote_rdiffbackup', None)
    if distant_rdiffbackup is None:
      raise TypeError("Distant rdiff-backup binary path wasn't specified")


    backup_directory = self.createBackupDirectory('remote')
    remote_schema = ("'%(ssh_binary)s' -p %(port)s %%s " + \
                    "'%(rdiffbackup_binary)s' --server") % {
                      'ssh_binary': self.ssh_conf['ssh_binary'],
                      'port': instance_port,
                      'rdiffbackup_binary': distant_rdiffbackup,
                    }

    cron_command = ('%(rdiff_backup_binary)s ' + \
                   '--remote-schema "%(remote_schema)s" ' + \
                   '"%(source)s" ' + \
                   '"%(destination)s"') % {
                     'rdiff_backup_binary': self.options['rdiff_backup_binary'],
                     'remote_schema': remote_schema,
                     'source':  '[%s]:%s' % (self.ssh_conf['hostname'],
                                           distant_directory,
                                          ),
                     'destination': backup_directory,
                   }

    cron_line = '@%(frequency)s %(command)s'

    backup_cron = os.path.join(self.cron_d, 'backup')
    with open(backup_cron, 'w') as file_:
      file_.write(cron_line % {
        'frequency': frequency,
        'command': cron_command,
      })

    return backup_directory


##############################################################################
#
# Copyright (c) 2011 Vifib SARL and Contributors. All Rights Reserved.
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
from slapos.recipe.librecipe import GenericBaseRecipe

class Recipe(GenericBaseRecipe):
  """
  ZEO instance configuration.

  wrapper-path -- location of the init script to generate

  binary-path -- location of the runzeo command

  ip -- ip of the zeo server

  port -- port of the zeo server

  log-path -- location of the log file

  pid-path -- location of the pid file

  conf-path -- location of the configuration file

  zodb-path -- location of the zodb directory (which contains all storage)

  storage -- string with list of all resquested storage
    Example: event_module person_module
  """

  def install(self):
    snippet_filename = self.getTemplateFilename(
                                    'zeo-filestorage-snippet.conf.in')
    zodb_directory_path = self.options['zodb-path']

    # Prepare all filestorages
    filestorage_snippet = ""
    for storage_name in self.options['storage'].split():
      storage_path = os.path.join(zodb_directory_path, '%s.fs' % storage_name)

      filestorage_snippet += self.substituteTemplate(
          snippet_filename, dict(storage_name=storage_name, path=storage_path))

    config = dict(
      zeo_ip=self.options['ip'],
      zeo_port=self.options['port'],
      zeo_event_log=self.options['log-path'],
      zeo_pid=self.options['pid-path'],
      zeo_filestorage_snippet=filestorage_snippet,
    )

    # Create configuration file
    template_filename = self.getTemplateFilename('zeo.conf.in')
    configuration_path = self.createFile(
        self.options['conf-path'],
        self.substituteTemplate(template_filename, config))

    # Create running wrapper
    wrapper_path = self.createPythonScript(
      self.options['wrapper-path'],
      'slapos.recipe.librecipe.execute.execute',
      arguments=[self.options['binary-path'].strip(), '-C', zeo_conf_path],

    return [configuration_path, wrapper_path]

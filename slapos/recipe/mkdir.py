#!/usr/bin/env python
# -*- coding: utf-8 -*-
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

import os

from slapos.recipe.librecipe import BaseSlapRecipe
import zc.buildout

class Recipe(BaseSlapRecipe):

  def directoryByType(self, type_):
    try:
      return {
        'data': self.data_root_directory,
        'backup': self.backup_directory,
        'log': self.log_directory,
        'config_parts': self.etc_directory,
      }[type_]
    except KeyError, e:
      self.logger.error('Directory type %r does not exist' % e.message)
      raise zc.buildout.UserError('Directory type %r does not exist' % e.message)

  def _options(self, options):
    if 'type' not in options:
      self.logger.error('No directory type was specified.')
      raise zc.buildout.UserError('No directory type in the part %s' % self.name)

    name = self.name
    if 'name' in options:
      name = options['name']

    options['location'] = os.path.join(self.directoryByType(options['type']),
                                                            name)

  def _install(self):
    mode = '0700'
    if mode in self.options:
      mode = self.options['mode']

    removable = True
    if 'removable' in self.options:
      removable = str(self.options['removable']).lower() in ['y', 'yes',
                                                             'true', '1']

    if os.path.exists(self.options['location']):
      if not os.path.isdir(self.options['location']):
        self.logger.error("There is already something in %r, but it's not a directory!")
        raise OSError("Impossible to create directory %r, something's already there.")

    else:
      os.makedirs(self.options['location'], mode=0700)

    if removable:
      return [self.options['location']]
    return []

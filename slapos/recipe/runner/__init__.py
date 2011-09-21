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

import shlex
import sys

from slapos.recipe.librecipe import BaseSlapRecipe
import zc.buildout

class Recipe(BaseSlapRecipe):

  def _install(self):
    self.path_list = []
    self.createRunner()
    return self.path_list

  def createRunner(self):
    command_line = shlex.split(self.options['cmd'])
    environment = self.options.get('environment', None)
    name = self.options['name']
    self.requirements, self.ws = self.egg.working_set()
    if environment is not None:
      # Just a dummy parser
      environment = dict([
        tuple([str(values).strip() for values in line.split('=', 1)
               if '=' in line])
        for line in str(environment).splitlines()
      ])

    function = 'execute'
    arguments = command_line

    if environment is not None:
      function = 'executee'
      arguments = (command_line, environment)

    wrapper = zc.buildout.easy_install.scripts([(name,
      'slapos.recipe.librecipe.execute', function)], self.ws,
      sys.executable, self.wrapper_directory, arguments=arguments)[0]
    self.path_list.append(wrapper)

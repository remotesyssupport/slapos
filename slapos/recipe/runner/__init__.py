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
import re

from slapos.recipe.librecipe import BaseSlapRecipe
import zc.buildout

class Recipe(BaseSlapRecipe):

  YES = ['1', 'yes', 'y', 'true']


  def _options(self, options):
      if 'name' not in options:
        options['name'] = self.name

      self.python = ('type' in options and options['type'] == 'python')

      options['location'] = self.wrapper_directory
      if 'service' in options and  options['service'] not in Recipe.YES:
        options['location'] = self.bin_directory

  def _install(self):
    self.path_list = []
    self.createRunner()
    return self.path_list

  def getCommandLine(self):
    if 'cmd' in self.options:
      return shlex.split(self.options['cmd'])
    elif any([re.match(r'cmd_\d+', option) for option in self.options.keys()]):
      arguments = [matching for matching in [re.match(r'cmd_(\d+)', option)
                                             for option in self.options.keys()]
                   if matching]
      arguments.sort(cmp=lambda x, y: cmp(int(x.group(1)), int(y.group(1))))
      return [self.options[arg.group()] for arg in arguments]
    else:
      raise zc.buildout.UserError("No command line specified.")

  def createRunner(self):
    self.requirements, self.ws = self.egg.working_set()
    environment = self.options.get('environment', None)

    if environment is not None:
      # Just a dummy parser
      environment = dict([
        tuple([str(values).strip() for values in line.split('=', 1)])
        for line in str(environment).splitlines()
        if '=' in line
      ])

    if not self.python:
      command_line = self.getCommandLine()

      function = 'execute'
      arguments = command_line

      if environment is not None:
        function = 'executee'
        arguments = (command_line, environment)

      runner = zc.buildout.easy_install.scripts([(self.options['name'],
        'slapos.recipe.librecipe.execute', function)], self.ws,
        sys.executable, self.options['location'], arguments=arguments)[0]

    else:
      if 'script' not in self.options:
        raise zc.buildout.UserError("No python script specified")

      if environment is None:
        environment = {}
      args = ', '.join([repr(arg) for arg in (self.options['script'], {}, environment)])

      runner = zc.buildout.easy_install.scripts([(self.options['name'],
        '__builtin__', 'execfile')], self.ws,
        sys.executable, self.options['location'], arguments=args)[0]

    self.path_list.append(runner)

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
#############################################################################

import os
import sys
import zc.buildout
from slapos.recipe.librecipe import BaseSlapRecipe
import pkg_resources

class Recipe(BaseSlapRecipe):

    def _install(self):
      """
      Set the connection dictionnary for the computer partition and create a list
      of paths to the different wrappers

      Parameters : none

      Returns    : List path_list
      """

      self.path_list = []

      self.requirements, self.ws = self.egg.working_set()
      
      xvfb_conf                  = self.instaciateXvfb()

      self.instanciateTestRunner(xvfb_conf['display'])

      self.linkBinary()
      self.computer_partition_setConnectionDict()

      return self.path_list

    def instanciateXvfb(self):
      """
      Create Xvfb configuration dictionnary and instanciate a wrapper for it

      Parameters : None

      Returns    : Dictionnary xvfb_conf
      """
      xvfb_conf={}

      xvfb_conf['xvfb_binary'] = self.options['xvfb_binary']

      display_list = [":%s" % i for i in range(123,144)]
      
      for display_try in display_list:
        lock_filepath = '/tmp/.X%s-lock' % display_try.replace(":", "")
        if not os.path.exists(lock_filepath):
          xvfb_conf['display'] = display_try
          break
      
      xvfb_template_location = pkg_resources.resource_filename(          
                                             __name__, os.path.join(         
                                             'template', 'xvfb_run.in'))     
    
      xvfb_runner_path = self.createRunningWrapper("Xvfb",
                               self.substituteTemplate(xvfb_template_location, 
                                                       xvfb_conf))
   
      self.path_list.append(xvfb_runner_path)

      return xvfb_conf

    def instanciateTestRunner(self, display):
      """
      Instanciate a wrapper for the browser and the test report's

      Parameters : display on which the browser will run

      Returns    : None
      """

      self.path_list.extend(zc.buildout.easy_install.scripts([(
                      'selenium',__name__+'.testrunner', 'run')], self.ws,
                      sys.executable, self.wrapper_directory, arguments=[
                  dict(
                      browser_binary  = self.options['chromium_binary'],
                      display         = display,
                      option          = "--ignore-certificate-errors --disable-translate --disable-web-security",
                      suite_name      = self.parameter_dict['suite_name'],
                      base_url        = self.parameter_dict['url'],
                      user            = self.parameter_dict['user'],
                      password        = self.paramer_dict['password']
                      )]))

    def linkBinary(self):
      """Links binaries to instance's bin directory for easier exposal"""
      for linkline in self.options.get('link_binary_list', '').splitlines():
        if not linkline:
          continue
        target = linkline.split()
        if len(target) == 1:
          target = target[0]
          path, linkname = os.path.split(target)
        else:
          linkname = target[1]
          target = target[0]
        link = os.path.join(self.bin_directory, linkname)
        if os.path.lexists(link):
          if not os.path.islink(link):
            raise zc.buildout.UserError(
              'Target link already %r exists but it is not link' % link)
          os.unlink(link)
        os.symlink(target, link)
        self.logger.debug('Created link %r -> %r' % (link, target))
        self.path_list.append(link)
      

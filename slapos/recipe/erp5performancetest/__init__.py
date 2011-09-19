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
import slapos.recipe.erp5
import sys
import zc.buildout
import os

server_ip_dict = {
  "server1" : "10.0.247.181",
  "server2" : "10.0.247.181",
  "server3" : "10.0.247.181",
}

class Recipe(slapos.recipe.erp5.Recipe):

  def getLocalIPv4Address(self, server_type="server1"):
    return server_ip_dict.get(server_type)

  def installZeo(self, ip, template_name='zeo.conf.in'):
    zodb_dir = os.path.join(self.data_root_directory, 'zodb')
    self._createDirectory(zodb_dir)
    zeo_configuration_dict = {}
    zeo_number = 0
    for zeo_server in sorted(self._zeo_storage_dict.iterkeys()):
      zeo_number += 1
      zeo_event_log = os.path.join(self.log_directory, 'zeo-%s.log'% zeo_number)
      zeo_pid = os.path.join(self.run_directory, 'zeo-%s.pid'% zeo_number)
      self.registerLogRotation('zeo-%s' % zeo_number, [zeo_event_log],
          self.killpidfromfile + ' ' + zeo_pid + ' SIGUSR2')
      config = dict(
        zeo_ip=ip,
        zeo_port=self._zeo_storage_port_dict[zeo_server],
        zeo_event_log=zeo_event_log,
        zeo_pid=zeo_pid,
      )
      storage_definition_list = []
      for storage_name in sorted(self._zeo_storage_dict[zeo_server]):
        path = os.path.join(zodb_dir, '%s.fs' % storage_name)
        storage_definition_list.append("""<filestorage %(storage_name)s>
  path %(path)s
</filestorage>"""% dict(storage_name=storage_name, path=path))
        zeo_configuration_dict[storage_name] = dict(
          ip=ip,
          port=config['zeo_port'],
          path=path
          )
      config['zeo_filestorage_snippet'] = '\n'.join(storage_definition_list)
      zeo_conf_path = self.createConfigurationFile('zeo-%s.conf' % zeo_number,
        self.substituteTemplate(self.getTemplateFilename(template_name), config))
      self.path_list.append(zeo_conf_path)
      wrapper = zc.buildout.easy_install.scripts([('zeo_%s' % zeo_number,
       'slapos.recipe.librecipe.execute', 'execute')], self.ws, sys.executable,
        self.wrapper_directory, arguments=[
          self.options['runzeo_binary'].strip(), '-C', zeo_conf_path]
        )[0]
      self.path_list.append(wrapper)
    return zeo_configuration_dict


  
  def _getZeoClusterDict(self):
    return {
        '/': (self._requestZeoFileStorage('Zeo Server 1', 'main'),
              self.site_id + 'account_module'),
        '/'+self.site_id+'/person_module': (self._requestZeoFileStorage('Zeo Server 1', 'person_module'),
                           None),
        '/'+self.site_id+'/document_module': (self._requestZeoFileStorage('Zeo Server 1', 'document_module'),
                                          None),
        '/'+self.site_id+'/sale_packing_list_module': (self._requestZeoFileStorage('Zeo Server 1', 'sale_packing_list_module'),
                                                   None),
        }

  def _install(self):
    self.path_list = []
    self.requirements, self.ws = self.egg.working_set()
    # Install stuff that is common for all servers
    # Crond, logrotate, killpid, 
    # self.cron_d is a directory, where cron jobs can be registered
    self.cron_d = self.installCrond()
    self.logrotate_d, self.logrotate_backup = self.installLogrotate()
    self.killpidfromfile = zc.buildout.easy_install.scripts(
        [('killpidfromfile', 'slapos.recipe.erp5' + '.killpidfromfile',
          'killpidfromfile')], self.ws, sys.executable, self.bin_directory)[0]
    self.path_list.append(self.killpidfromfile)

    instance_type = self.parameter_dict.get('instance_type', '')
    if instance_type == 'server1':
      self._installServer1()
    elif instance_type == 'server2':
      self._installServer2()
    elif instance_type == 'server3':
      self._installServer3()
    else:
      raise ValueError, "Bad instance type given %s" %(instance_type,)

    return self.path_list

  def _installServer1(self,):
    """ Install
    - memcached
    - kumo
    - cloudooo
    - MySQL
    - ZEO server
    - TID Storage
    - Apache
    - HAProxy
    - helper scripts
    """
    ip = self.getLocalIPv4Address()

    # Memcached
    memcached_conf = self.installMemcached(ip=self.getLocalIPv4Address(),
        port=11000)
    # Kumo
    kumo_conf = self.installKumo(self.getLocalIPv4Address())
    # Cloudooo
    conversion_server_conf = self.installConversionServer(
        self.getLocalIPv4Address(), 23000, 23060)
    # MySQL
    mysql_conf = self.installMysqlServer(self.getLocalIPv4Address(), 45678)

    # ERP5 Installation
    user, password = self.installERP5()

    # ZEO Mount point installation
    mount_point_zeo_dict = self._getZeoClusterDict()
    use_zlibstorage = self.parameter_dict.get('use_zlibstorage',
                                              False)
    if use_zlibstorage:
      template_name = "zeo-zlibstorage.conf.in"
    else:
      template_name = "zeo.conf.in"
    zeo_conf = self.installZeo(ip, template_name)
    known_tid_storage_identifier_dict = {}
    for mount_point, (storage_dict, check_path) in mount_point_zeo_dict.iteritems():
      # Build TID Storage parameter
      known_tid_storage_identifier_dict[
        (((storage_dict['ip'],storage_dict['port']),), storage_dict['storage_name'])
        ] = (zeo_conf[storage_dict['storage_name']]['path'], check_path or mount_point)
    zodb_configuration_string = self._getZODBConfigurationString()

    zope_port = 12000

    # HAProxy
    # We need to get the list of ip:port for haproxy that will be
    # installed
    login_url_list = []
    login_url_list.extend(self._installServer2(dry_run=True))
    login_url_list.extend(self._installServer3(dry_run=True))
    site_check_path = '/%s/getId' % self.site_id
    login_haproxy = self.installHaproxy(ip, 15001, 'login', site_check_path,
        login_url_list)
    # Apache
    ca_conf = self.installCertificateAuthority()
    key, certificate = self.requestCertificate('Login Based Access')
    apache_login = self.installBackendApache(self.getGlobalIPv6Address(), 15002,
        login_haproxy, key, certificate)
    # TID Storage
    tidstorage_config = self._getTIDStorageConfig()
    self.installTidStorage(tidstorage_config['host'], tidstorage_config['port'],
        known_tid_storage_identifier_dict, 'http://'+login_haproxy)
    # Helper scripts for tests
    self.installTestRunner(ca_conf, mysql_conf, conversion_server_conf,
                           memcached_conf, kumo_conf)
    self.installTestSuiteRunner(ca_conf, mysql_conf, conversion_server_conf,
                           memcached_conf, kumo_conf)
    self.linkBinary()
    self.setConnectionDict(dict(
      site_url=apache_login,
      site_user=user,
      site_password=password,
      memcached_url=memcached_conf['memcached_url'],
      kumo_url=kumo_conf['kumo_address']
    ))

  def _getZODBConfigurationString(self):
    mount_point_zeo_dict = self._getZeoClusterDict()
    zodb_configuration_list = []
    use_zlibstorage = self.parameter_dict.get('use_zlibstorage',
                                              False)
    if use_zlibstorage:
      template_name = "zope-zeo-zlibstorage-snippet.conf.in"
    else:
      template_name = "zope-zeo-snippet.conf.in"
    
    for mount_point, (storage_dict, check_path) in mount_point_zeo_dict.iteritems():
      # Update configuration
      zodb_configuration_list.append(self.substituteTemplate(
        self.getTemplateFilename(template_name), dict(
        storage_name=storage_dict['storage_name'],
        address='%s:%s' % (storage_dict['ip'], storage_dict['port']),
        mount_point=mount_point,
        zodb_cache_size=5000, 
        zeo_client_cache_size=int(self.parameter_dict.get('zeo_client_cache_size', 0)),
        )))
    zodb_configuration_string = '\n'.join(zodb_configuration_list)
    return zodb_configuration_string


  def _getTIDStorageConfig(self):
    return dict(host=self.getLocalIPv4Address(), port='6001')

  def _installServer2(self, dry_run=False):
    """ Install one distribution node, 4 activity nodes
        and 5 client nodes """
    # ERP5 Installation
    user, password = self.installERP5()

    zodb_configuration_string = self._getZODBConfigurationString()
    tidstorage_config = self._getTIDStorageConfig()
    # One Distribution Node
    ip = self.getLocalIPv4Address()
    zope_port = 12000
    zope_port +=1
    if not dry_run:
      self.installZope(ip, zope_port, 'zope_distribution',
                       with_timerservice=True,
                       zodb_configuration_string=zodb_configuration_string,
                       tidstorage_config=tidstorage_config)
    # 4 Activity Nodes
    for i in xrange(1,5):
      zope_port += 1
      if not dry_run:
        self.installZope(ip, zope_port, 'zope_activity_%s' % i,
                         with_timerservice=True,
                         zodb_configuration_string=zodb_configuration_string,
                         tidstorage_config=tidstorage_config)
    # 5 Working Nodes (Human access)
    login_url_list = []
    for i in xrange(1,6):
      zope_port += 1
      if not dry_run:
        login_url_list.append(self.installZope(ip, zope_port,
                                               'zope_login_%s' % i, with_timerservice=False,
                                               zodb_configuration_string=zodb_configuration_string,
                                               tidstorage_config=tidstorage_config))
      else:
        login_url_list.append("%s:%s" %(ip, zope_port))
    return login_url_list

  def _installServer3(self, dry_run=False):
    """ Install 5 activity nodes
        and 5 client nodes """
    # ERP5 Installation
    user, password = self.installERP5()

    zodb_configuration_string = self._getZODBConfigurationString()
    tidstorage_config = self._getTIDStorageConfig()
    # One Distribution Node
    ip = self.getLocalIPv4Address()
    zope_port = 12100
    zope_port +=1
    # 5 Activity Nodes
    for i in xrange(1,6):
      zope_port += 1
      if not dry_run:
        self.installZope(ip, zope_port, 'zope_activity_%s' % i,
                         with_timerservice=True,
                         zodb_configuration_string=zodb_configuration_string,
                         tidstorage_config=tidstorage_config)
    # 5 Working Nodes (Human access)
    login_url_list = []
    for i in xrange(1,6):
      zope_port += 1
      if not dry_run:
        login_url_list.append(self.installZope(ip, zope_port,
                                               'zope_login_%s' % i, with_timerservice=False,
                                               zodb_configuration_string=zodb_configuration_string,
                                               tidstorage_config=tidstorage_config))
      else:
        login_url_list.append("%s:%s" %(ip, zope_port))
    return login_url_list

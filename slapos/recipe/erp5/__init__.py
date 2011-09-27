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
import binascii
import os
import pkg_resources
import pprint
import hashlib
import sys
import zc.buildout
import zc.recipe.egg
import ConfigParser
import re

_isurl = re.compile('([a-zA-Z0-9+.-]+)://').match

# based on Zope2.utilities.mkzopeinstance.write_inituser
def Zope2InitUser(path, username, password):
  open(path, 'w').write('')
  os.chmod(path, 0600)
  open(path, "w").write('%s:{SHA}%s\n' % (
    username,binascii.b2a_base64(hashlib.sha1(password).digest())[:-1]))

class Recipe(BaseSlapRecipe):
  def getTemplateFilename(self, template_name):
    return pkg_resources.resource_filename(__name__,
        'template/%s' % template_name)

  site_id = 'erp5'

  def _install(self):
    self.path_list = []
    self.requirements, self.ws = self.egg.working_set()
    # self.cron_d is a directory, where cron jobs can be registered
    self.cron_d = self.installCrond()
    self.logrotate_d, self.logrotate_backup = self.installLogrotate()
    self.killpidfromfile = zc.buildout.easy_install.scripts(
        [('killpidfromfile', __name__ + '.killpidfromfile',
          'killpidfromfile')], self.ws, sys.executable, self.bin_directory)[0]
    self.path_list.append(self.killpidfromfile)
    ca_conf = self.installCertificateAuthority()

    memcached_conf = self.installMemcached(ip=self.getLocalIPv4Address(),
        port=11000)
    kumo_conf = self.installKumo(self.getLocalIPv4Address())
    conversion_server_conf = self.installConversionServer(
        self.getLocalIPv4Address(), 23000, 23060)
    mysql_conf = self.installMysqlServer(self.getLocalIPv4Address(), 45678)
    user, password = self.installERP5()

    if self.parameter_dict.get("slap_software_type", "").lower() == "cluster":
      # Site access is done by HAProxy
      zope_access, site_access, key_access = self.installZopeCluster(ca_conf)
    else:
      zope_access = self.installZopeStandalone()
      site_access = zope_access
      key_access = None

    key, certificate = self.requestCertificate('Login Based Access')
    apache_conf = dict(
         apache_login=self.installBackendApache(ip=self.getGlobalIPv6Address(),
         port=13000, backend=site_access, key=key, certificate=certificate))

    connection_dict = dict(site_url=apache_conf['apache_login'])

    if self.parameter_dict.get("domain_name") is not None:
      connection_dict["backend_url"] = apache_conf['apache_login']
      connection_dict["domain_ip"] = self.getGlobalIPv6Address()

      # XXX Define a fake domain_name for now.
      frontend_name = self.parameter_dict.get("domain_name")
      frontend_key, frontend_certificate = \
             self.requestCertificate(frontend_name)

      connection_dict["site_url"] = self.installFrontendZopeApache(
        ip=self.getGlobalIPv6Address(), port=4443, name=frontend_name,
        frontend_path='/', backend_path='',
        backend_url=apache_conf['apache_login'], key=frontend_key,
        certificate=frontend_certificate)

    default_bt5_list = []
    if self.parameter_dict.get("flavour", "default") == 'configurator':
      default_bt5_list = self.options.get("configurator_bt5_list", '').split()

    self.installERP5Site(user, password, zope_access, mysql_conf,
             conversion_server_conf, memcached_conf, kumo_conf,
             self.site_id, default_bt5_list, ca_conf)

    self.installTestRunner(ca_conf, mysql_conf, conversion_server_conf,
                           memcached_conf, kumo_conf)
    self.installTestSuiteRunner(ca_conf, mysql_conf, conversion_server_conf,
                           memcached_conf, kumo_conf)
    self.linkBinary()
    connection_dict.update(**dict(
      site_user=user,
      site_password=password,
      memcached_url=memcached_conf['memcached_url'],
      kumo_url=kumo_conf['kumo_address']
    ))
    if key_access is not None:
      connection_dict['key_access'] = key_access
    if self.options.get('fulltext_search', None) == 'sphinx':
      sphinx_searchd = self.installSphinxSearchd(ip=self.getLocalIPv4Address())
      connection_dict.update(**sphinx_searchd)
    self.setConnectionDict(connection_dict)
    return self.path_list

  def installZopeStandalone(self):
    """ Install a single Zope instance without ZEO Server.
    """
    zodb_dir = os.path.join(self.data_root_directory, 'zodb')
    self._createDirectory(zodb_dir)
    zodb_root_path = os.path.join(zodb_dir, 'main.fs')

    thread_amount_per_zope = int(self.options.get(
                                 'single_zope_thread_amount', 4))

    zodb_cache_size = int(self.options.get('zodb_cache_size', 5000))

    return self.installZope(ip=self.getLocalIPv4Address(),
          port=12000 + 1, name='zope_%s' % 1,
          zodb_configuration_string=self.substituteTemplate(
            self.getTemplateFilename('zope-zodb-snippet.conf.in'),
            dict(zodb_root_path=zodb_root_path,
                 zodb_cache_size=zodb_cache_size)),
            with_timerservice=True,
            thread_amount=thread_amount_per_zope)

  def installKeyAuthorisationApache(self, ipv6, port, backend, key, certificate,
      ca_conf, key_auth_path='/'):
    if ipv6:
      ip = self.getGlobalIPv6Address()
    else:
      ip = self.getLocalIPv4Address()
    ssl_template = """SSLEngine on
SSLVerifyClient require
RequestHeader set REMOTE_USER %%{SSL_CLIENT_S_DN_CN}s
SSLCertificateFile %(key_auth_certificate)s
SSLCertificateKeyFile %(key_auth_key)s
SSLCACertificateFile %(ca_certificate)s
SSLCARevocationPath %(ca_crl)s"""
    apache_conf = self._getApacheConfigurationDict('key_auth_apache', ip, port)
    apache_conf['ssl_snippet'] = ssl_template % dict(
        key_auth_certificate=certificate,
        key_auth_key=key,
        ca_certificate=ca_conf['ca_certificate'],
        ca_crl=ca_conf['ca_crl']
        )
    prefix = 'ssl_key_auth_apache'
    rewrite_rule_template = \
      "RewriteRule (.*) http://%(backend)s%(key_auth_path)s$1 [L,P]"
    path_template = pkg_resources.resource_string('slapos.recipe.erp5',
      'template/apache.zope.conf.path.in')
    path = path_template % dict(path='/')
    d = dict(
          path=path,
          backend=backend,
          backend_path='/',
          port=apache_conf['port'],
          vhname=path.replace('/', ''),
          key_auth_path=key_auth_path,
    )
    rewrite_rule = rewrite_rule_template % d
    apache_conf.update(**dict(
      path_enable=path,
      rewrite_rule=rewrite_rule
    ))
    apache_config_file = self.createConfigurationFile(prefix + '.conf',
        pkg_resources.resource_string('slapos.recipe.erp5',
          'template/apache.zope.conf.in') % apache_conf)
    self.path_list.append(apache_config_file)
    self.path_list.extend(zc.buildout.easy_install.scripts([(
      'key_auth_apache',
        'slapos.recipe.erp5.apache', 'runApache')], self.ws,
          sys.executable, self.wrapper_directory, arguments=[
            dict(
              required_path_list=[certificate, key, ca_conf['ca_certificate'],
                ca_conf['ca_crl']],
              binary=self.options['httpd_binary'],
              config=apache_config_file
            )
          ]))
    if ipv6:
      return 'https://[%(ip)s:%(port)s]' % apache_conf
    else:
      return 'https://%(ip)s:%(port)s' % apache_conf

  def installZopeCluster(self, ca_conf=None):
    """ Install ERP5 using ZEO Cluster
    """
    site_check_path = '/%s/getId' % self.site_id
    thread_amount_per_zope = int(self.options.get(
                                'cluster_zope_thread_amount', 1))

    activity_node_amount = int(self.options.get(
                   "cluster_activity_node_amount", 2))

    user_node_amount = int(self.options.get(
                   "cluster_user_node_amount", 2))

    key_auth_node_amount = int(self.options.get(
                   "key_auth_node_amount", 0))

    ip = self.getLocalIPv4Address()
    storage_dict = self._requestZeoFileStorage('Zeo Server 1', 'main')

    zeo_conf = self.installZeo(ip)
    tidstorage_config = dict(host=ip, port='6001')

    # XXX How to define good values for this?
    mount_point = '/'
    zodb_cache_size = 5000
    zeo_client_cache_size = '20MB'
    check_path = '/erp5/account_module'

    known_tid_storage_identifier_dict = {}
    known_tid_storage_identifier_dict[
      (((storage_dict['ip'],storage_dict['port']),), storage_dict['storage_name'])
        ] = (zeo_conf[storage_dict['storage_name']]['path'], check_path or mount_point)

    zodb_configuration_string = self.substituteTemplate(
        self.getTemplateFilename('zope-zeo-snippet.conf.in'), dict(
        storage_name=storage_dict['storage_name'],
        address='%s:%s' % (storage_dict['ip'], storage_dict['port']),
        mount_point=mount_point, zodb_cache_size=zodb_cache_size,
        zeo_client_cache_size=zeo_client_cache_size
        ))

    zope_port = 12000
    # One Distribution Node (Single Thread Always)
    zope_port += 1
    self.installZope(ip, zope_port, 'zope_distribution', with_timerservice=True,
        zodb_configuration_string=zodb_configuration_string,
        tidstorage_config=tidstorage_config)

    # Activity Nodes (Single Thread Always)
    for i in range(activity_node_amount):
      zope_port += 1
      self.installZope(ip, zope_port, 'zope_activity_%s' % i,
          with_timerservice=True,
          zodb_configuration_string=zodb_configuration_string,
          tidstorage_config=tidstorage_config)

    # Four Web Page Nodes (Human access)
    login_url_list = []
    for i in range(user_node_amount):
      zope_port += 1
      login_url_list.append(self.installZope(ip, zope_port,
        'zope_login_%s' % i, with_timerservice=False,
        zodb_configuration_string=zodb_configuration_string,
        tidstorage_config=tidstorage_config,
        thread_amount=thread_amount_per_zope))

    login_haproxy = self.installHaproxy(ip, 15001, 'login',
                               site_check_path, login_url_list)

    key_access = None
    if key_auth_node_amount > 0:
      service_url_list = []
      for i in range(key_auth_node_amount):
        zope_port += 1
        service_url_list.append(self.installZope(ip, zope_port,
          'zope_service_%s' % i, with_timerservice=False,
          zodb_configuration_string=zodb_configuration_string,
          tidstorage_config=tidstorage_config))
      service_haproxy = self.installHaproxy(ip, 15000, 'service',
          site_check_path, service_url_list)

      key_auth_key, key_auth_certificate = self.requestCertificate(
          'Key Based Access')
      key_access = self.installKeyAuthorisationApache(True, 15500,
          service_haproxy, key_auth_key, key_auth_certificate, ca_conf)

    self.installTidStorage(tidstorage_config['host'],
                           tidstorage_config['port'],
            known_tid_storage_identifier_dict, 'http://' + login_haproxy)

    return login_url_list[-1], login_haproxy, key_access

  def _requestZeoFileStorage(self, server_name, storage_name):
    """Local, slap.request compatible, call to ask for filestorage on Zeo

    filter_kw can be used to select specific Zeo server

    Someday in future it will be possible to invoke:

    self.request(
      software_release=self.computer_partition.getSoftwareRelease().getURI(),
      software_type='Zeo Server',
      partition_reference=storage_name,
      filter_kw={'server_name': server_name},
      shared=True
    )

    Thanks to this it will be possible to select precisely on which server
    which storage will be placed.
    """
    base_port = 35001
    if getattr(self, '_zeo_storage_dict', None) is None:
      self._zeo_storage_dict = {}
    if getattr(self, '_zeo_storage_port_dict', None) is None:
      self._zeo_storage_port_dict = {}
    self._zeo_storage_port_dict.setdefault(server_name,
        base_port+len(self._zeo_storage_port_dict))
    self._zeo_storage_dict[server_name] = self._zeo_storage_dict.get(
        server_name, []) + [storage_name]
    return dict(
      ip=self.getLocalIPv4Address(),
      port=self._zeo_storage_port_dict[server_name],
      storage_name=storage_name
    )

  def installLogrotate(self):
    """Installs logortate main configuration file and registers its to cron"""
    logrotate_d = os.path.abspath(os.path.join(self.etc_directory,
      'logrotate.d'))
    self._createDirectory(logrotate_d)
    logrotate_backup = self.createBackupDirectory('logrotate')
    logrotate_conf = self.createConfigurationFile("logrotate.conf",
        "include %s" % logrotate_d)
    logrotate_cron = os.path.join(self.cron_d, 'logrotate')
    state_file = os.path.join(self.data_root_directory, 'logrotate.status')
    open(logrotate_cron, 'w').write('0 0 * * * %s -s %s %s' %
        (self.options['logrotate_binary'], state_file, logrotate_conf))
    self.path_list.extend([logrotate_d, logrotate_conf, logrotate_cron])
    return logrotate_d, logrotate_backup

  def registerLogRotation(self, name, log_file_list, postrotate_script):
    """Register new log rotation requirement"""
    open(os.path.join(self.logrotate_d, name), 'w').write(
        self.substituteTemplate(self.getTemplateFilename(
          'logrotate_entry.in'),
          dict(file_list=' '.join(['"'+q+'"' for q in log_file_list]),
            postrotate=postrotate_script, olddir=self.logrotate_backup)))

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

  def installKumo(self, ip, kumo_manager_port=13101, kumo_server_port=13201,
      kumo_server_listen_port=13202, kumo_gateway_port=13301):
    # XXX: kumo is not storing pid in file, unless it is not running as daemon
    #      but running daemons is incompatible with SlapOS, so there is currently
    #      no way to have Kumo's pid files to rotate logs and send signals to them
    config = dict(
      kumo_gateway_binary=self.options['kumo_gateway_binary'],
      kumo_gateway_ip=ip,
      kumo_gateway_log=os.path.join(self.log_directory, "kumo-gateway.log"),
      kumo_manager_binary=self.options['kumo_manager_binary'],
      kumo_manager_ip=ip,
      kumo_manager_log=os.path.join(self.log_directory, "kumo-manager.log"),
      kumo_server_binary=self.options['kumo_server_binary'],
      kumo_server_ip=ip,
      kumo_server_log=os.path.join(self.log_directory, "kumo-server.log"),
      kumo_server_storage=os.path.join(self.data_root_directory, "kumodb.tch"),
      kumo_manager_port=kumo_manager_port,
      kumo_server_port=kumo_server_port,
      kumo_server_listen_port=kumo_server_listen_port,
      kumo_gateway_port=kumo_gateway_port
    )

    self.path_list.append(self.createRunningWrapper('kumo_gateway',
      self.substituteTemplate(self.getTemplateFilename('kumo_gateway.in'),
        config)))

    self.path_list.append(self.createRunningWrapper('kumo_manager',
      self.substituteTemplate(self.getTemplateFilename('kumo_manager.in'),
        config)))

    self.path_list.append(self.createRunningWrapper('kumo_server',
      self.substituteTemplate(self.getTemplateFilename('kumo_server.in'),
        config)))

    return dict(
      kumo_address = '%s:%s' % (config['kumo_gateway_ip'],
        config['kumo_gateway_port']),
      kumo_gateway_ip=config['kumo_gateway_ip'],
      kumo_gateway_port=config['kumo_gateway_port'],
    )

  def installMemcached(self, ip, port):
    config = dict(
        memcached_binary=self.options['memcached_binary'],
        memcached_ip=ip,
        memcached_port=port,
    )
    self.path_list.append(self.createRunningWrapper('memcached',
      self.substituteTemplate(self.getTemplateFilename('memcached.in'),
        config)))
    return dict(memcached_url='%s:%s' %
        (config['memcached_ip'], config['memcached_port']),
        memcached_ip=config['memcached_ip'],
        memcached_port=config['memcached_port'])

  def installSphinxSearchd(self, ip, port=9312, sql_port=9306):
    data_directory = self.createDataDirectory('sphinx')
    sphinx_conf_path = self.createConfigurationFile('sphinx.conf',
      self.substituteTemplate(self.getTemplateFilename('sphinx.conf.in'), dict(
          ip_address=ip,
          port=port,
          sql_port=sql_port,
          data_directory=data_directory,
          log_directory=self.log_directory,
          )))
    self.path_list.append(sphinx_conf_path)
    wrapper = zc.buildout.easy_install.scripts([('sphinx_searchd',
     'slapos.recipe.librecipe.execute', 'execute')], self.ws, sys.executable,
      self.wrapper_directory, arguments=[
        self.options['sphinx_searchd_binary'].strip(), '-c', sphinx_conf_path, '--nodetach']
      )[0]
    self.path_list.append(wrapper)
    return dict(sphinx_searchd_ip=ip,
                sphinx_searchd_port=port,
                sphinx_searchd_sql_port=sql_port)

  def installTestRunner(self, ca_conf, mysql_conf, conversion_server_conf,
                        memcached_conf, kumo_conf):
    """Installs bin/runUnitTest executable to run all tests using
       bin/runUnitTest"""
    testinstance = self.createDataDirectory('testinstance')
    # workaround wrong assumptions of ERP5Type.tests.runUnitTest about
    # directory existence
    unit_test = os.path.join(testinstance, 'unit_test')
    connection_string_list = []
    for test_database, test_user, test_password in \
          mysql_conf['mysql_parallel_test_dict'][-4:]:
      connection_string_list.append(
          '%s@%s:%s %s %s' % (test_database, mysql_conf['ip'],
                            mysql_conf['tcp_port'], test_user, test_password))
    if not os.path.isdir(unit_test):
      os.mkdir(unit_test)
    runUnitTest = zc.buildout.easy_install.scripts([
      ('runUnitTest', __name__ + '.testrunner', 'runUnitTest')],
      self.ws, sys.executable, self.bin_directory, arguments=[dict(
        instance_home=testinstance,
        prepend_path=self.bin_directory,
        openssl_binary=self.options['openssl_binary'],
        test_ca_path=ca_conf['certificate_authority_path'],
        call_list=[self.options['runUnitTest_binary'],
          '--erp5_sql_connection_string', '%(mysql_test_database)s@%'
          '(ip)s:%(tcp_port)s %(mysql_test_user)s '
          '%(mysql_test_password)s' % mysql_conf,
          '--extra_sql_connection_string_list',','.join(connection_string_list),
          '--conversion_server_hostname=%(conversion_server_ip)s' % \
                                                         conversion_server_conf,
          '--conversion_server_port=%(conversion_server_port)s' % \
                                                         conversion_server_conf,
          '--volatile_memcached_server_hostname=%(memcached_ip)s' % memcached_conf,
          '--volatile_memcached_server_port=%(memcached_port)s' % memcached_conf,
          '--persistent_memcached_server_hostname=%(kumo_gateway_ip)s' % kumo_conf,
          '--persistent_memcached_server_port=%(kumo_gateway_port)s' % kumo_conf,
      ]
        )])[0]
    self.path_list.append(runUnitTest)

  def installTestSuiteRunner(self, ca_conf, mysql_conf, conversion_server_conf,
                        memcached_conf, kumo_conf):
    """Installs bin/runTestSuite executable to run all tests using
       bin/runUnitTest"""
    testinstance = self.createDataDirectory('test_suite_instance')
    # workaround wrong assumptions of ERP5Type.tests.runUnitTest about
    # directory existence
    unit_test = os.path.join(testinstance, 'unit_test')
    if not os.path.isdir(unit_test):
      os.mkdir(unit_test)
    connection_string_list = []
    for test_database, test_user, test_password in \
        mysql_conf['mysql_parallel_test_dict']:
      connection_string_list.append(
          '%s@%s:%s %s %s' % (test_database, mysql_conf['ip'],
                              mysql_conf['tcp_port'], test_user, test_password))
    command = zc.buildout.easy_install.scripts([
      ('runTestSuite', __name__ + '.test_suite_runner', 'runTestSuite')],
      self.ws, sys.executable, self.bin_directory, arguments=[dict(
        instance_home=testinstance,
        prepend_path=self.bin_directory,
        openssl_binary=self.options['openssl_binary'],
        test_ca_path=ca_conf['certificate_authority_path'],
        call_list=[self.options['runTestSuite_binary'],
          '--db_list', ','.join(connection_string_list),
          '--conversion_server_hostname=%(conversion_server_ip)s' % \
                                                         conversion_server_conf,
          '--conversion_server_port=%(conversion_server_port)s' % \
                                                         conversion_server_conf,
          '--volatile_memcached_server_hostname=%(memcached_ip)s' % memcached_conf,
          '--volatile_memcached_server_port=%(memcached_port)s' % memcached_conf,
          '--persistent_memcached_server_hostname=%(kumo_gateway_ip)s' % kumo_conf,
          '--persistent_memcached_server_port=%(kumo_gateway_port)s' % kumo_conf,
      ]
        )])[0]
    self.path_list.append(command)

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

  def requestCertificate(self, name):
    hash = hashlib.sha512(name).hexdigest()
    key = os.path.join(self.ca_private, hash + self.ca_key_ext)
    certificate = os.path.join(self.ca_certs, hash + self.ca_crt_ext)
    parser = ConfigParser.RawConfigParser()
    parser.add_section('certificate')
    parser.set('certificate', 'name', name)
    parser.set('certificate', 'key_file', key)
    parser.set('certificate', 'certificate_file', certificate)
    parser.write(open(os.path.join(self.ca_request_dir, hash), 'w'))
    return key, certificate

  def installCertificateAuthority(self, ca_country_code='XX',
      ca_email='xx@example.com', ca_state='State', ca_city='City',
      ca_company='Company'):
    backup_path = self.createBackupDirectory('ca')
    self.ca_dir = os.path.join(self.data_root_directory, 'ca')
    self._createDirectory(self.ca_dir)
    self.ca_request_dir = os.path.join(self.ca_dir, 'requests')
    self._createDirectory(self.ca_request_dir)
    config = dict(ca_dir=self.ca_dir, request_dir=self.ca_request_dir)
    self.ca_private = os.path.join(self.ca_dir, 'private')
    self.ca_certs = os.path.join(self.ca_dir, 'certs')
    self.ca_crl = os.path.join(self.ca_dir, 'crl')
    self.ca_newcerts = os.path.join(self.ca_dir, 'newcerts')
    self.ca_key_ext = '.key'
    self.ca_crt_ext = '.crt'
    for d in [self.ca_private, self.ca_crl, self.ca_newcerts, self.ca_certs]:
      self._createDirectory(d)
    for f in ['crlnumber', 'serial']:
      if not os.path.exists(os.path.join(self.ca_dir, f)):
        open(os.path.join(self.ca_dir, f), 'w').write('01')
    if not os.path.exists(os.path.join(self.ca_dir, 'index.txt')):
      open(os.path.join(self.ca_dir, 'index.txt'), 'w').write('')
    openssl_configuration = os.path.join(self.ca_dir, 'openssl.cnf')
    config.update(
        working_directory=self.ca_dir,
        country_code=ca_country_code,
        state=ca_state,
        city=ca_city,
        company=ca_company,
        email_address=ca_email,
    )
    self._writeFile(openssl_configuration, pkg_resources.resource_string(
      __name__, 'template/openssl.cnf.ca.in') % config)
    self.path_list.extend(zc.buildout.easy_install.scripts([
      ('certificate_authority',
        __name__ + '.certificate_authority', 'runCertificateAuthority')],
        self.ws, sys.executable, self.wrapper_directory, arguments=[dict(
          openssl_configuration=openssl_configuration,
          openssl_binary=self.options['openssl_binary'],
          certificate=os.path.join(self.ca_dir, 'cacert.pem'),
          key=os.path.join(self.ca_private, 'cakey.pem'),
          crl=os.path.join(self.ca_crl),
          request_dir=self.ca_request_dir
          )]))
    # configure backup
    backup_cron = os.path.join(self.cron_d, 'ca_rdiff_backup')
    open(backup_cron, 'w').write(
        '''0 0 * * * %(rdiff_backup)s %(source)s %(destination)s'''%dict(
          rdiff_backup=self.options['rdiff_backup_binary'],
          source=self.ca_dir,
          destination=backup_path))
    self.path_list.append(backup_cron)

    return dict(
      ca_certificate=os.path.join(config['ca_dir'], 'cacert.pem'),
      ca_crl=os.path.join(config['ca_dir'], 'crl'),
      certificate_authority_path=config['ca_dir']
    )

  def installConversionServer(self, ip, port, openoffice_port):
    name = 'conversion_server'
    working_directory = self.createDataDirectory(name)
    conversion_server_dict = dict(
      working_path=working_directory,
      uno_path=self.options['ooo_uno_path'],
      office_binary_path=self.options['ooo_binary_path'],
      ip=ip,
      port=port,
      openoffice_port=openoffice_port,
    )
    for env_line in self.options['environment'].splitlines():
      env_line = env_line.strip()
      if not env_line:
        continue
      if '=' in env_line:
        env_key, env_value = env_line.split('=')
        conversion_server_dict[env_key.strip()] = env_value.strip()
      else:
        raise zc.buildout.UserError('Line %r in environment parameter is '
            'incorrect' % env_line)
    config_file = self.createConfigurationFile(name + '.cfg',
        self.substituteTemplate(self.getTemplateFilename('cloudooo.cfg.in'),
          conversion_server_dict))
    self.path_list.append(config_file)
    self.path_list.extend(zc.buildout.easy_install.scripts([(name,
     'slapos.recipe.librecipe.execute', 'execute_with_signal_translation')], self.ws,
      sys.executable, self.wrapper_directory,
      arguments=[self.options['ooo_paster'].strip(), 'serve', config_file]))
    return {
      name + '_port': conversion_server_dict['port'],
      name + '_ip': conversion_server_dict['ip']
      }

  def installHaproxy(self, ip, port, name, server_check_path, url_list):
    # inter must be quite short in order to detect quickly an unresponsive node
    #      and to detect quickly a node which is back
    # rise must be minimal possible : 1, indeed, a node which is back don't need
    #      to sleep more time and we can give him work immediately
    # fall should be quite sort. with inter at 3, and fall at 2, a node will be
    #      considered as dead after 6 seconds.
    # maxconn should be set as the maximum thread we have per zope, like this
    #      haproxy will manage the queue of request with the possibility to
    #      move a request to another node if the initially selected one is dead
    server_template = """  server %(name)s %(address)s cookie %(name)s check inter 3s rise 1 fall 2 maxconn %(cluster_zope_thread_amount)s"""
    config = dict(name=name, ip=ip, port=port,
        server_check_path=server_check_path,)
    i = 1
    server_list = []
    cluster_zope_thread_amount = self.options.get('cluster_zope_thread_amount', 1)
    for url in url_list:
      server_list.append(server_template % dict(name='%s_%s' % (name, i),
        address=url, cluster_zope_thread_amount=cluster_zope_thread_amount))
      i += 1
    config['server_text'] = '\n'.join(server_list)
    haproxy_conf_path = self.createConfigurationFile('haproxy_%s.cfg' % name,
      self.substituteTemplate(self.getTemplateFilename('haproxy.cfg.in'),
        config))
    self.path_list.append(haproxy_conf_path)
    wrapper = zc.buildout.easy_install.scripts([('haproxy_%s' % name,
     'slapos.recipe.librecipe.execute', 'execute')], self.ws, sys.executable,
      self.wrapper_directory, arguments=[
        self.options['haproxy_binary'].strip(), '-f', haproxy_conf_path]
      )[0]
    self.path_list.append(wrapper)
    return '%s:%s' % (ip, port)

  def installERP5(self):
    """
    All zope have to share file created by portal_classes
    (until everything is integrated into the ZODB).
    So, do not request zope instance and create multiple in the same partition.
    """
    # Create instance directories
    self.erp5_directory = self.createDataDirectory('erp5shared')
    # Create init user
    password = self.generatePassword()
    # XXX Unhardcoded me please
    user = 'zope'
    Zope2InitUser(
        os.path.join(self.erp5_directory, "inituser"), user, password)

    self._createDirectory(self.erp5_directory)
    for directory in (
      'Constraint',
      'Document',
      'Extensions',
      'PropertySheet',
      'import',
      'lib',
      'tests',
      'Products',
      'etc',
      ):
      self._createDirectory(os.path.join(self.erp5_directory, directory))
    self._createDirectory(os.path.join(self.erp5_directory, 'etc',
      'package-includes'))

    # Symlink to BT5 repositories defined in instance config.
    # Those paths will eventually end up in the ZODB, and having symlinks
    # inside the XXX makes it possible to reuse such ZODB with another software
    # release[ version].
    # Note: this path cannot be used for development, it's really just a
    # read-only repository.
    repository_path = os.path.join(self.var_directory, "bt5_repository")
    if not os.path.isdir(repository_path):
      os.mkdir(repository_path)
    self.path_list.append(repository_path)
    self.bt5_repository_list = []
    append = self.bt5_repository_list.append
    for repository in self.options.get('bt5_repository_list', '').split():
      repository = repository.strip()
      if not repository:
        continue

      if _isurl(repository) and not repository.startswith("file://"):
        # XXX: assume it's a valid URL
        append(repository)
        continue

      if repository.startswith('file://'):
        repository = repository.replace('file://', '', '')

      if os.path.isabs(repository):
        repo_id = hashlib.sha1(repository).hexdigest()
        link = os.path.join(repository_path, repo_id)
        if os.path.lexists(link):
          if not os.path.islink(link):
            raise zc.buildout.UserError(
              'Target link already %r exists but it is not link' % link)
          os.unlink(link)
        os.symlink(repository, link)
        self.logger.debug('Created link %r -> %r' % (link, repository_path))
        # Always provide a URL-Type
        append("file://" + link)

    return user, password

  def installERP5Site(self, user, password, zope_access, mysql_conf,
                      conversion_server_conf=None, memcached_conf=None,
                      kumo_conf=None,
                      erp5_site_id='erp5', default_bt5_list=[], ca_conf={},
                      supervisor_controlled=True):
    """
    Create  a script  to  automatically set  up  an erp5  site (controlled  by
    supervisor by default) on available zope and mysql environments.
    """
    conversion_server = None
    if conversion_server_conf is not None:
      conversion_server = "%s:%s" % (conversion_server_conf['conversion_server_ip'],
             conversion_server_conf['conversion_server_port'])
    if memcached_conf is None:
      memcached_conf = {}
    if kumo_conf is None:
      kumo_conf = {}
    # XXX Conversion server and memcache server coordinates are not relevant
    # for pure site creation.
    mysql_connection_string = "%(mysql_database)s@%(ip)s:%(tcp_port)s %(mysql_user)s %(mysql_password)s" % mysql_conf

    bt5_list = self.parameter_dict.get("bt5_list", "").split() or default_bt5_list
    bt5_repository_list = self.parameter_dict.get("bt5_repository_list", "").split() \
      or getattr(self, 'bt5_repository_list', [])

    erp5_update_directory = supervisor_controlled and self.wrapper_directory or \
        self.bin_directory

    script = zc.buildout.easy_install.scripts([('erp5_update',
            __name__ + '.erp5', 'updateERP5')], self.ws,
                  sys.executable, erp5_update_directory,
                  arguments=[erp5_site_id,
                             mysql_connection_string,
                             [user, password, zope_access],
                             memcached_conf.get('memcached_url'),
                             conversion_server,
                             kumo_conf.get("kumo_address"),
                             bt5_list,
                             bt5_repository_list,
                             ca_conf.get('certificate_authority_path'),
                             self.options.get('openssl_binary')])

    self.path_list.extend(script)

    return []

  def installZeo(self, ip):
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
        self.substituteTemplate(self.getTemplateFilename('zeo.conf.in'), config))
      self.path_list.append(zeo_conf_path)
      wrapper = zc.buildout.easy_install.scripts([('zeo_%s' % zeo_number,
       'slapos.recipe.librecipe.execute', 'execute')], self.ws, sys.executable,
        self.wrapper_directory, arguments=[
          self.options['runzeo_binary'].strip(), '-C', zeo_conf_path]
        )[0]
      self.path_list.append(wrapper)
    return zeo_configuration_dict

  def installRepozo(self, zodb_root_path):
    """
    Add only repozo to cron (e.g. without tidstorage) allowing full
    and incremental backups.
    """
    backup_path = self.createBackupDirectory('zodb')
    repozo_cron_path = os.path.join(self.cron_d, 'repozo')
    repozo_cron_file = open(repozo_cron_path, 'w')
    try:
      repozo_cron_file.write('''
0 0 * * 0 %(repozo_binary)s --backup --full --file="%(zodb_root_path)s" --repository="%(backup_path)s"
0 * * * * %(repozo_binary)s --backup --file="%(zodb_root_path)s" --repository="%(backup_path)s"
''' % dict(repozo_binary=self.options['repozo_binary'],
           zodb_root_path=zodb_root_path,
           backup_path=backup_path))
    finally:
      repozo_cron_file.close()

    self.path_list.append(repozo_cron_path)

  def installTidStorage(self, ip, port, known_tid_storage_identifier_dict,
      access_url):
    """Install TidStorage with all required backup tools

      known_tid_storage_identifier_dict is a dictionary of:
      (((ip, port),), storagename): (filestorage path, url for serialize)
      url for serialize will be merged with access_url by internal tidstorage

      """
    backup_base_path = self.createBackupDirectory('zodb')
    # it is time to fill known_tid_storage_identifier_dict with backup
    # destination
    formatted_storage_dict = dict()
    for key, v in known_tid_storage_identifier_dict.copy().iteritems():
      # generate unique name for each backup
      storage_name = key[1]
      destination = os.path.join(backup_base_path, storage_name)
      self._createDirectory(destination)
      formatted_storage_dict[str(key)] = (v[0], destination, v[1])
    logfile = os.path.join(self.log_directory, 'tidstorage.log')
    pidfile = os.path.join(self.run_directory, 'tidstorage.pid')
    statusfile = os.path.join(self.log_directory, 'tidstorage.tid')
    timestamp_file_path = os.path.join(self.log_directory,
          'repozo_tidstorage_timestamp.log')
    # shared configuration file
    tidstorage_config = self.createConfigurationFile('tidstorage.py',
        self.substituteTemplate(self.getTemplateFilename('tidstorage.py.in'),
          dict(
        known_tid_storage_identifier_dict=pprint.pformat(formatted_storage_dict),
        base_url='%s/%%s/serialize' % access_url,
        host=ip,
        port=port,
        timestamp_file_path=timestamp_file_path,
        logfile=logfile,
        pidfile=pidfile,
        statusfile=statusfile
      )))
    # TID server
    tidstorage_server = zc.buildout.easy_install.scripts([('tidstoraged',
     'slapos.recipe.librecipe.execute', 'execute')], self.ws, sys.executable,
      self.wrapper_directory, arguments=[
        self.options['tidstoraged_binary'], '--nofork', '--config',
        tidstorage_config])[0]
    self.registerLogRotation('tidsorage', [logfile, timestamp_file_path],
          self.killpidfromfile + ' ' + pidfile + ' SIGHUP')
    self.path_list.append(tidstorage_config)
    self.path_list.append(tidstorage_server)

    # repozo wrapper
    tidstorage_repozo = zc.buildout.easy_install.scripts([('tidstorage_repozo',
     'slapos.recipe.librecipe.execute', 'execute')], self.ws, sys.executable,
      self.bin_directory, arguments=[
        self.options['tidstorage_repozo_binary'], '--config', tidstorage_config,
      '--repozo', self.options['repozo_binary'], '-z'])[0]
    self.path_list.append(tidstorage_repozo)

    # and backup configuration
    tidstorage_repozo_cron = os.path.join(self.cron_d, 'tidstorage_repozo')
    open(tidstorage_repozo_cron, 'w').write('''0 0 * * * %(tidstorage_repozo)s
0 0 * * * cp -f %(tidstorage_tid)s %(tidstorage_tid_backup)s'''%dict(
      tidstorage_repozo=tidstorage_repozo,
      tidstorage_tid=statusfile,
      tidstorage_tid_backup=os.path.join(backup_base_path, 'tidstorage.tid')))
    self.path_list.append(tidstorage_repozo_cron)
    return dict(host=ip, port=port)

  def installZope(self, ip, port, name, zodb_configuration_string,
      with_timerservice=False, tidstorage_config=None, thread_amount=1,
      with_deadlockdebugger=True, zope_environment=None):
    default_zope_environment = dict(
      TMP=self.tmp_directory,
      TMPDIR=self.tmp_directory,
      HOME=self.tmp_directory,
      PATH=self.bin_directory
    )
    if zope_environment is None:
      zope_environment = default_zope_environment.copy()
    else:
      for envk, envv in default_zope_environment.iteritems():
        if envk not in zope_environment:
          zope_environment[envk] = envv
    # Create zope configuration file
    zope_config = dict(
        products=self.options['products'],
        thread_amount=thread_amount
    )
    # configure default Zope2 zcml
    open(os.path.join(self.erp5_directory, 'etc', 'site.zcml'), 'w').write(
        pkg_resources.resource_string(__name__, 'template/site.zcml'))
    zope_config['zodb_configuration_string'] = zodb_configuration_string
    zope_config['instance'] = self.erp5_directory
    zope_config['event_log'] = os.path.join(self.log_directory,
        '%s-event.log' % name)
    zope_config['z2_log'] = os.path.join(self.log_directory,
        '%s-Z2.log' % name)
    zope_config['pid-filename'] = os.path.join(self.run_directory,
        '%s.pid' % name)
    zope_config['lock-filename'] = os.path.join(self.run_directory,
        '%s.lock' % name)
    self.registerLogRotation(name, [zope_config['event_log'],
      zope_config['z2_log']], self.killpidfromfile + ' ' +
      zope_config['pid-filename'] + ' SIGUSR2')

    prefixed_products = []
    for product in reversed(zope_config['products'].split()):
      product = product.strip()
      if product:
        prefixed_products.append('products %s' % product)
    prefixed_products.insert(0, 'products %s' % os.path.join(
                             self.erp5_directory, 'Products'))
    zope_config['products'] = '\n'.join(prefixed_products)
    zope_config['address'] = '%s:%s' % (ip, port)

    zope_wrapper_template_location = self.getTemplateFilename('zope.conf.in')
    zope_conf_content = self.substituteTemplate(
        zope_wrapper_template_location, zope_config)
    if with_timerservice:
      zope_conf_content += self.substituteTemplate(
          self.getTemplateFilename('zope.conf.timerservice.in'), zope_config)
    if tidstorage_config is not None:
      zope_conf_content += self.substituteTemplate(
          self.getTemplateFilename('zope-tidstorage-snippet.conf.in'),
          tidstorage_config)
    if with_deadlockdebugger:
      zope_conf_content += self.substituteTemplate(
          self.getTemplateFilename('zope-deadlockdebugger-snippet.conf.in'),
          dict(dump_url='/manage_debug_threads',
            secret=self.generatePassword()))

    zope_conf_path = self.createConfigurationFile("%s.conf" % name,
        zope_conf_content)
    self.path_list.append(zope_conf_path)
    # Create init script
    wrapper = zc.buildout.easy_install.scripts([(name,
     'slapos.recipe.librecipe.execute', 'executee')], self.ws, sys.executable,
      self.wrapper_directory, arguments=[
        [self.options['runzope_binary'].strip(), '-C', zope_conf_path],
        zope_environment
      ])[0]
    self.path_list.append(wrapper)
    return zope_config['address']

  def _getApacheConfigurationDict(self, prefix, ip, port):
    apache_conf = dict()
    apache_conf['pid_file'] = os.path.join(self.run_directory,
        prefix + '.pid')
    apache_conf['lock_file'] = os.path.join(self.run_directory,
        prefix + '.lock')
    apache_conf['ip'] = ip
    apache_conf['port'] = port
    apache_conf['server_admin'] = 'admin@'
    apache_conf['error_log'] = os.path.join(self.log_directory,
        prefix + '-error.log')
    apache_conf['access_log'] = os.path.join(self.log_directory,
        prefix + '-access.log')
    self.registerLogRotation(prefix, [apache_conf['error_log'],
      apache_conf['access_log']], self.killpidfromfile + ' ' +
      apache_conf['pid_file'] + ' SIGUSR1')
    return apache_conf

  def _writeApacheConfiguration(self, prefix, apache_conf, backend,
      access_control_string=None):
    rewrite_rule_template = \
        "RewriteRule (.*) http://%(backend)s$1 [L,P]"
    if access_control_string is None:
      path_template = pkg_resources.resource_string(__name__,
        'template/apache.zope.conf.path.in')
      path = path_template % dict(path='/')
    else:
      path_template = pkg_resources.resource_string(__name__,
        'template/apache.zope.conf.path-protected.in')
      path = path_template % dict(path='/',
          access_control_string=access_control_string)
    d = dict(
          path=path,
          backend=backend,
          backend_path='/',
          port=apache_conf['port'],
          vhname=path.replace('/', ''),
    )
    rewrite_rule = rewrite_rule_template % d
    apache_conf.update(**dict(
      path_enable=path,
      rewrite_rule=rewrite_rule
    ))
    apache_conf_string = pkg_resources.resource_string(__name__,
          'template/apache.zope.conf.in') % apache_conf
    return self.createConfigurationFile(prefix + '.conf', apache_conf_string)

  def installFrontendZopeApache(self, ip, port, name, frontend_path, backend_url,
      backend_path, key, certificate, access_control_string=None):
    ident = 'frontend_' + name
    apache_conf = self._getApacheConfigurationDict(ident, ip, port)
    apache_conf['server_name'] = name
    apache_conf['frontend_path'] = frontend_path
    apache_conf['ssl_snippet'] = pkg_resources.resource_string(__name__,
        'template/apache.ssl-snippet.conf.in') % dict(
        login_certificate=certificate, login_key=key)

    path = pkg_resources.resource_string(__name__,
           'template/apache.zope.conf.path-protected.in') % \
              dict(path='/', access_control_string='none')

    if access_control_string is None:
      path_template = pkg_resources.resource_string(__name__,
        'template/apache.zope.conf.path.in')
      path += path_template % dict(path=frontend_path)
    else:
      path_template = pkg_resources.resource_string(__name__,
        'template/apache.zope.conf.path-protected.in')
      path += path_template % dict(path=frontend_path,
          access_control_string=access_control_string)

    rewrite_rule_template = \
        "RewriteRule ^%(path)s($|/.*) %(backend_url)s/VirtualHostBase/https/%(server_name)s:%(port)s%(backend_path)s/VirtualHostRoot/%(vhname)s$1 [L,P]\n"

    if frontend_path not in ["", None, "/"]:
      vhname = "_vh_%s" % frontend_path.replace('/', '')
    else:
      vhname = ""
      frontend_path = ""

    rewrite_rule = rewrite_rule_template % dict(
          path=frontend_path,
          backend_url=backend_url,
          backend_path=backend_path,
          port=apache_conf['port'],
          vhname=vhname,
          server_name=name)

    apache_conf.update(**dict(
      path_enable=path,
      rewrite_rule=rewrite_rule
    ))
    apache_conf_string = pkg_resources.resource_string(__name__,
          'template/apache.zope.conf.in') % apache_conf
    apache_config_file = self.createConfigurationFile(ident + '.conf',
        apache_conf_string)
    self.path_list.append(apache_config_file)
    self.path_list.extend(zc.buildout.easy_install.scripts([(
      ident, __name__ + '.apache', 'runApache')], self.ws,
          sys.executable, self.wrapper_directory, arguments=[
            dict(
              required_path_list=[key, certificate],
              binary=self.options['httpd_binary'],
              config=apache_config_file
            )
          ]))
    # Note: IPv6 is assumed always
    return 'https://%(server_name)s:%(port)s%(frontend_path)s' % (apache_conf)

  def installBackendApache(self, ip, port, backend, key, certificate,
      suffix='', access_control_string=None):
    apache_conf = self._getApacheConfigurationDict('backend_apache'+suffix, ip,
        port)
    apache_conf['server_name'] = '%s' % apache_conf['ip']
    apache_conf['ssl_snippet'] = pkg_resources.resource_string(__name__,
        'template/apache.ssl-snippet.conf.in') % dict(
        login_certificate=certificate, login_key=key)
    apache_config_file = self._writeApacheConfiguration('backend_apache'+suffix,
        apache_conf, backend, access_control_string)
    self.path_list.append(apache_config_file)
    self.path_list.extend(zc.buildout.easy_install.scripts([(
      'backend_apache'+suffix,
        __name__ + '.apache', 'runApache')], self.ws,
          sys.executable, self.wrapper_directory, arguments=[
            dict(
              required_path_list=[key, certificate],
              binary=self.options['httpd_binary'],
              config=apache_config_file
            )
          ]))
    # Note: IPv6 is assumed always
    return 'https://[%(ip)s]:%(port)s' % apache_conf

  def installMysqlServer(self, ip, port, database='erp5', user='user',
      test_database='test_erp5', test_user='test_user', template_filename=None,
      parallel_test_database_amount=100, mysql_conf=None, with_backup=True,
      with_maatkit=True):
    if mysql_conf is None:
      mysql_conf = {}
    backup_directory = self.createBackupDirectory('mysql')
    if template_filename is None:
      template_filename = self.getTemplateFilename('my.cnf.in')
    error_log = os.path.join(self.log_directory, 'mysqld.log')
    slow_query_log = os.path.join(self.log_directory, 'mysql-slow.log')
    mysql_conf.update(
        ip=ip,
        data_directory=os.path.join(self.data_root_directory,
          'mysql'),
        tcp_port=port,
        pid_file=os.path.join(self.run_directory, 'mysqld.pid'),
        socket=os.path.join(self.run_directory, 'mysqld.sock'),
        error_log=error_log,
        slow_query_log=slow_query_log,
        mysql_database=database,
        mysql_user=user,
        mysql_password=self.generatePassword(),
        mysql_test_password=self.generatePassword(),
        mysql_test_database=test_database,
        mysql_test_user=test_user,
        mysql_parallel_test_dict=[
            ('test_%i' % x,)*2 + (self.generatePassword(),) \
                 for x in xrange(0,parallel_test_database_amount)],
    )
    self.registerLogRotation('mysql', [error_log, slow_query_log],
        '%(mysql_binary)s --no-defaults -B --user=root '
        '--socket=%(mysql_socket)s -e "FLUSH LOGS"' % dict(
          mysql_binary=self.options['mysql_binary'],
          mysql_socket=mysql_conf['socket']))
    self._createDirectory(mysql_conf['data_directory'])

    mysql_conf_path = self.createConfigurationFile("my.cnf",
        self.substituteTemplate(template_filename,
          mysql_conf))

    mysql_script_list = []
    for x_database, x_user, x_password in \
          [(mysql_conf['mysql_database'],
            mysql_conf['mysql_user'],
            mysql_conf['mysql_password']),
           (mysql_conf['mysql_test_database'],
            mysql_conf['mysql_test_user'],
            mysql_conf['mysql_test_password']),
          ] + mysql_conf['mysql_parallel_test_dict']:
      mysql_script_list.append(pkg_resources.resource_string(__name__,
                     'template/initmysql.sql.in') % {
                        'mysql_database': x_database,
                        'mysql_user': x_user,
                        'mysql_password': x_password})
    mysql_script_list.append('EXIT')
    mysql_script = '\n'.join(mysql_script_list)
    self.path_list.extend(zc.buildout.easy_install.scripts([('mysql_update',
      __name__ + '.mysql', 'updateMysql')], self.ws,
      sys.executable, self.wrapper_directory, arguments=[dict(
        mysql_script=mysql_script,
        mysql_binary=self.options['mysql_binary'].strip(),
        mysql_upgrade_binary=self.options['mysql_upgrade_binary'].strip(),
        socket=mysql_conf['socket'],
        )]))
    self.path_list.extend(zc.buildout.easy_install.scripts([('mysqld',
      __name__ + '.mysql', 'runMysql')], self.ws,
        sys.executable, self.wrapper_directory, arguments=[dict(
        mysql_install_binary=self.options['mysql_install_binary'].strip(),
        mysqld_binary=self.options['mysqld_binary'].strip(),
        data_directory=mysql_conf['data_directory'].strip(),
        mysql_binary=self.options['mysql_binary'].strip(),
        socket=mysql_conf['socket'].strip(),
        configuration_file=mysql_conf_path,
       )]))
    self.path_list.extend([mysql_conf_path])

    if with_backup:
      # backup configuration
      backup_directory = self.createBackupDirectory('mysql')
      full_backup = os.path.join(backup_directory, 'full')
      incremental_backup = os.path.join(backup_directory, 'incremental')
      self._createDirectory(full_backup)
      self._createDirectory(incremental_backup)
      innobackupex_argument_list = [self.options['perl_binary'],
          self.options['innobackupex_binary'],
          '--defaults-file=%s' % mysql_conf_path,
          '--socket=%s' %mysql_conf['socket'].strip(), '--user=root',
          '--ibbackup=%s'% self.options['xtrabackup_binary']]
      environment = dict(PATH='%s' % self.bin_directory)
      innobackupex_incremental = zc.buildout.easy_install.scripts([(
        'innobackupex_incremental','slapos.recipe.librecipe.execute', 'executee')],
        self.ws, sys.executable, self.bin_directory, arguments=[
          innobackupex_argument_list + ['--incremental'],
          environment])[0]
      self.path_list.append(innobackupex_incremental)
      innobackupex_full = zc.buildout.easy_install.scripts([('innobackupex_full',
       'slapos.recipe.librecipe.execute', 'executee')], self.ws,
        sys.executable, self.bin_directory, arguments=[
          innobackupex_argument_list,
          environment])[0]
      self.path_list.append(innobackupex_full)
      backup_controller = zc.buildout.easy_install.scripts([
        ('innobackupex_controller', __name__ + '.innobackupex', 'controller')],
        self.ws, sys.executable, self.bin_directory,
        arguments=[innobackupex_incremental, innobackupex_full, full_backup,
          incremental_backup])[0]
      self.path_list.append(backup_controller)
      mysql_backup_cron = os.path.join(self.cron_d, 'mysql_backup')
      open(mysql_backup_cron, 'w').write('0 0 * * * ' + backup_controller)
      self.path_list.append(mysql_backup_cron)

    if with_maatkit:
      # maatkit installation
      for mk_script_name in (
          'mk-variable-advisor',
          'mk-table-usage',
          'mk-visual-explain',
          'mk-config-diff',
          'mk-deadlock-logger',
          'mk-error-log',
          'mk-index-usage',
          'mk-query-advisor',
          ):
        mk_argument_list = [self.options['perl_binary'],
            self.options['%s_binary' % mk_script_name],
            '--defaults-file=%s' % mysql_conf_path,
            '--socket=%s' %mysql_conf['socket'].strip(), '--user=root',
            ]
        environment = dict(PATH='%s' % self.bin_directory)
        mk_exe = zc.buildout.easy_install.scripts([(
          mk_script_name,'slapos.recipe.librecipe.execute', 'executee')],
          self.ws, sys.executable, self.bin_directory, arguments=[
            mk_argument_list, environment])[0]
        self.path_list.append(mk_exe)

    # The return could be more explicit database, user ...
    return mysql_conf

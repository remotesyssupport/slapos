from setuptools import setup, find_packages
import glob
import os

version = '0.23-dev'
name = 'slapos.cookbook'
long_description = open("README.txt").read() + "\n" + \
    open("CHANGES.txt").read() + "\n"

for f in sorted(glob.glob(os.path.join('slapos', 'recipe', 'README.*.txt'))):
  long_description += '\n' + open(f).read() + '\n'

# extras_requires are not used because of
#   https://bugs.launchpad.net/zc.buildout/+bug/85604
setup(name=name,
      version=version,
      description="SlapOS recipes.",
      long_description=long_description,
      classifiers=[
          "Framework :: Buildout :: Recipe",
          "Programming Language :: Python",
        ],
      keywords='slapos recipe',
      license='GPLv3',
      namespace_packages=['slapos', 'slapos.recipe'],
      packages=find_packages(),
      include_package_data=True,
      install_requires=[
        'PyXML', # for full blown python interpreter
        'lxml', # for full blown python interpreter
        'netaddr', # to manipulate on IP addresses
        'setuptools', # namespaces
        'slapos.core', # uses internally
#        'slapos.toolbox', # needed for libcloud, cloudmgr, disabled for now
        'xml_marshaller', # need to communication with slapgrid
        'zc.buildout', # plays with buildout
        'zc.recipe.egg', # for scripts generation
        ],
      zip_safe=True,
      entry_points={
        'zc.buildout': [
          'download = slapos.recipe.download:Recipe',
          'davstorage = slapos.recipe.davstorage:Recipe',
          'erp5 = slapos.recipe.erp5:Recipe',
          'erp5testnode = slapos.recipe.erp5testnode:Recipe',
          'helloworld = slapos.recipe.helloworld:Recipe',
          'java = slapos.recipe.java:Recipe',
          'kumofs = slapos.recipe.kumofs:Recipe',
          'kvm = slapos.recipe.kvm:Recipe',
          'libcloud = slapos.recipe.libcloud:Recipe',
          'libcloudrequest = slapos.recipe.libcloudrequest:Recipe',
          'memcached = slapos.recipe.memcached:Recipe',
          'mysql = slapos.recipe.mysql:Recipe',
          'nbdserver = slapos.recipe.nbdserver:Recipe',
          'nosqltestbed = slapos.recipe.nosqltestbed:NoSQLTestBed',
          'lamp = slapos.recipe.lamp:Request',
          'lamp.request = slapos.recipe.lamp:Request',
          'lamp.static = slapos.recipe.lamp:Static',
          'lamp.simple = slapos.recipe.lamp:Simple',
          'proactive = slapos.recipe.proactive:Recipe',
          'sheepdogtestbed = slapos.recipe.sheepdogtestbed:SheepDogTestBed',
          'siptester = slapos.recipe.siptester:SipTesterRecipe',
          'slaprunner = slapos.recipe.slaprunner:Recipe',
          'testnode = slapos.recipe.testnode:Recipe',
          'vifib = slapos.recipe.vifib:Recipe',
          'xwiki = slapos.recipe.xwiki:Recipe',
          'zabbixagent = slapos.recipe.zabbixagent:Recipe',
      ]},
    )

from setuptools import setup, find_packages

name = "slapos.recipe.nbdserver"
version = '1.2-dev'

def read(name):
  return open(name).read()

long_description=( read('README.txt')
                   + '\n' +
                   read('CHANGES.txt')
                 )

setup(
    name = name,
    version = version,
    description = "ZC Buildout recipe for create an nbd server ",
    long_description=long_description,
    license='GPLv3',
    keywords = "buildout nbd server",
    classifiers=[
        "Framework :: Buildout :: Recipe",
        "Programming Language :: Python",
    ],
    packages = find_packages('src'),
    package_dir = {'': 'src'},
    include_package_data=True,
    install_requires = [
      'zc.recipe.egg',
      'setuptools',
      'slapos.lib.recipe',
      ],
    namespace_packages = ['slapos', 'slapos.recipe'],
    entry_points = {'zc.buildout': ['default = %s:Recipe' % name]},
    )
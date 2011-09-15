===============
slapos.cookbook
===============

Cookbook of SlapOS recipes.

Generic recipes
===============

slapos.cookbook:format
----------------------

Usage
~~~~~

* ``buildout.cfg``

::

  [buildout]
  parts = example

  [example]
  recipe = slapos.cookbook:format
  filename = file.out
  source = /home/foobar/file.in
  location = ${buildout:directory}/out/
  substitute_test = value

* ``/home/foobar/file.in``

::

  This is the "%(test)s".
  And this is the parameter "%(parameter_test)s".

* The parameter XML of the instance :

::

  <instance>
    <parameter id="value">Another value</parameter>
  </instance>

Should generate the following content in ``buildout_directory/out/file.out`` :

::

  This is the "value".
  And this is the parameter "Another values"


Notes
~~~~~

This recipe does an dumb string format. See `String Formatting Operations<http://docs.python.org/library/stdtypes.html#string-formatting-operations>`_.

slapos.cookbook:mkdir
---------------------

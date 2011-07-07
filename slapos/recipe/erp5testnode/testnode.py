from xml_marshaller import xml_marshaller
import os, xmlrpclib, time, imp
from glob import glob
import signal
import slapos.slap
import subprocess
import sys
import socket
import pprint
import traceback
from SlapOSControler import SlapOSControler
import time

class SubprocessError(EnvironmentError):
  def __init__(self, status_dict):
    self.status_dict = status_dict
  def __getattr__(self, name):
    return self.status_dict[name]
  def __str__(self):
    return 'Error %i' % self.status_code


from Updater import Updater

def log(message):
  # Log to stdout, with a timestamp.
  print time.strftime('%Y/%m/%d %H:%M:%S'), message

supervisord_pid_file = None
process_group_pid_set = set()
def sigterm_handler(signal, frame):
  for pgpid in process_group_pid_set:
    try:
      os.killpg(pgpid, signal.SIGTERM)
    except:
      pass
  sys.exit(1)

signal.signal(signal.SIGTERM, sigterm_handler)

def safeRpcCall(function, *args):
  retry = 64
  while True:
    try:
      return function(*args)
    except:
      log('Error in RPC call: %s\n%s' % (
        traceback.format_exc(),
        pprint.pformat(args),
      ))
      time.sleep(retry)
      retry += retry >> 1

def getInputOutputFileList(config, command_name):
  stdout = open(os.path.join(
    config['log_directory'], '%s_out' % (command_name, )),
    'w+')
  stdout.write("%s\n" % command_name)
  stderr = open(os.path.join(
    config['log_directory'], '%s_err' % (command_name, )),
    'w+')
  return (stdout, stderr)

slapos_controler = None

def killPreviousRun():
  for pgpid in process_group_pid_set:
    try:
      os.killpg(pgpid, signal.SIGTERM)
    except:
      pass
  try:
    if os.path.exists(supervisord_pid_file):
      os.kill(int(open(supervisord_pid_file).read().strip()), signal.SIGTERM)
  except:
    pass

PROFILE_PATH_KEY = 'profile_path'

def run(args):
  config = args[0]
  slapgrid = None
  global supervisord_pid_file
  supervisord_pid_file = os.path.join(config['instance_root'], 'var', 'run',
    'supervisord.pid')
  subprocess.check_call([config['git_binary'],
                "config", "--global", "http.sslVerify", "false"])
  previous_revision = None

  run_software = True
  # Write our own software.cfg to use the local repository
  custom_profile_path = os.path.join(config['working_directory'], 'software.cfg')
  config['custom_profile_path'] = custom_profile_path
  vcs_repository_list = config['vcs_repository_list']
  profile_content = None
  assert len(vcs_repository_list), "we must have at least one repository"
  try:
    # BBB: Accept global profile_path, which is the same as setting it for the
    # first configured repository.
    profile_path = config.pop(PROFILE_PATH_KEY)
  except KeyError:
    pass
  else:
    vcs_repository_list[0][PROFILE_PATH_KEY] = profile_path
  for vcs_repository in vcs_repository_list:
    url = vcs_repository['url']
    buildout_section_id = vcs_repository.get('buildout_section_id', None)
    repository_id = buildout_section_id or \
                                  url.split('/')[-1].split('.')[0]
    repository_path = os.path.join(config['working_directory'],repository_id)
    vcs_repository['repository_id'] = repository_id
    vcs_repository['repository_path'] = repository_path
    try:
      profile_path = vcs_repository[PROFILE_PATH_KEY]
    except KeyError:
      pass
    else:
      if profile_content is not None:
        raise ValueError(PROFILE_PATH_KEY + ' defined more than once')
      profile_content = """
[buildout]
extends = %(software_config_path)s
""" %  {'software_config_path': os.path.join(repository_path, profile_path)}
    if not(buildout_section_id is None):
      profile_content += """
[%(buildout_section_id)s]
repository = %(repository_path)s
branch = %(branch)s
""" %  {'buildout_section_id': buildout_section_id,
        'repository_path' : repository_path,
        'branch' : vcs_repository.get('branch','master')}

  if profile_content is None:
    raise ValueError(PROFILE_PATH_KEY + ' not defined')
  custom_profile = open(custom_profile_path, 'w')
  custom_profile.write(profile_content)
  custom_profile.close()
  config['repository_path'] = repository_path
  sys.path.append(repository_path)
  test_suite_title = config['test_suite_title'] or config['test_suite']

  retry_software = False
  try:
    while True:
      remote_test_result_needs_cleanup = False
      # kill processes from previous loop if any
      try:
        killPreviousRun()
        process_group_pid_set.clear()
        full_revision_list = []
        # Make sure we have local repository
        for vcs_repository in vcs_repository_list:
          repository_path = vcs_repository['repository_path']
          repository_id = vcs_repository['repository_id']
          if not os.path.exists(repository_path):
            parameter_list = [config['git_binary'], 'clone',
                              vcs_repository['url']]
            if vcs_repository.get('branch') is not None:
              parameter_list.extend(['-b',vcs_repository.get('branch')])
            parameter_list.append(repository_path)
            subprocess.check_call(parameter_list)
          # Make sure we have local repository
          updater = Updater(repository_path, git_binary=config['git_binary'],
            log=log)
          updater.checkout()
          revision = "-".join(updater.getRevision())
          full_revision_list.append('%s=%s' % (repository_id, revision))
        revision = ','.join(full_revision_list)
        if previous_revision == revision:
          log('Sleeping a bit')
          time.sleep(120)
          if not(retry_software):
            continue
          log('Retrying install')
        retry_software = False
        previous_revision = revision

        portal_url = config['test_suite_master_url']
        test_result_path = None
        test_result = (test_result_path, revision)
        if portal_url:
          if portal_url[-1] != '/':
            portal_url += '/'
          portal = xmlrpclib.ServerProxy("%s%s" %
                      (portal_url, 'portal_task_distribution'),
                      allow_none=1)
          master = portal.portal_task_distribution
          assert master.getProtocolRevision() == 1
          test_result = safeRpcCall(master.createTestResult,
            config['test_suite'], revision, [],
            False, test_suite_title,
            config['test_node_title'], config['project_title'])
          remote_test_result_needs_cleanup = True
        log("testnode, test_result : %r" % (test_result, ))
        if test_result:
          test_result_path, test_revision = test_result
          if revision != test_revision:
            log('Disagreement on tested revision, checking out:')
            for i, repository_revision in enumerate(test_revision.split(',')):
              vcs_repository = vcs_repository_list[i]
              repository_path = vcs_repository['repository_path']
              revision = repository_revision.split('-')[1]
              # other testnodes on other boxes are already ready to test another
              # revision
              log('  %s at %s' % (repository_path, revision))
              updater = Updater(repository_path, git_binary=config['git_binary'],
                                revision=revision)
              updater.checkout()

          # Now prepare the installation of SlapOS and create instance
          slapos_controler = SlapOSControler(config,
            process_group_pid_set=process_group_pid_set, log=log)
          for method_name in ("runSoftwareRelease", "runComputerPartition"):
            stdout, stderr = getInputOutputFileList(config, method_name)
            slapos_method = getattr(slapos_controler, method_name)
            status_dict = slapos_method(config,
              environment=config['environment'],
              process_group_pid_set=process_group_pid_set,
              stdout=stdout, stderr=stderr
              )
            if status_dict['status_code'] != 0:
              retry_software = True
              raise SubprocessError(status_dict)

          partition_path = os.path.join(config['instance_root'],
                                        config['partition_reference'])
          run_test_suite_path = os.path.join(partition_path, 'bin',
                                            'runTestSuite')
          if not os.path.exists(run_test_suite_path):
            raise SubprocessError({
              'command': 'os.path.exists(run_test_suite_path)',
              'status_code': 1,
              'stdout': '',
              'stderr': 'File does not exist: %r' % (run_test_suite_path, ),
            })

          run_test_suite_revision = revision
          if isinstance(revision, tuple):
            revision = ','.join(revision)
          # Deal with Shebang size limitation
          file_object = open(run_test_suite_path, 'r')
          line = file_object.readline()
          file_object.close()
          invocation_list = []
          if line[:2] == '#!':
            invocation_list = line[2:].split()
          invocation_list.extend([run_test_suite_path,
                                  '--test_suite', config['test_suite'],
                                  '--revision', revision,
                                  '--test_suite_title', test_suite_title,
                                  '--node_quantity', config['node_quantity'],
                                  '--master_url', config['test_suite_master_url']])
          # From this point, test runner becomes responsible for updating test
          # result.
          # XXX: is it good for all cases (eg: test runner fails too early for
          # any custom code to pick the failure up and react ?)
          remote_test_result_needs_cleanup = False
          run_test_suite = subprocess.Popen(invocation_list,
            preexec_fn=os.setsid)
          process_group_pid_set.add(run_test_suite.pid)
          run_test_suite.wait()
          process_group_pid_set.remove(run_test_suite.pid)
      except SubprocessError, e:
        if remote_test_result_needs_cleanup:
          safeRpcCall(master.reportTaskFailure,
            test_result_path, e.status_dict, config['test_node_title'])
        time.sleep(120)

  finally:
    # Nice way to kill *everything* generated by run process -- process
    # groups working only in POSIX compilant systems
    # Exceptions are swallowed during cleanup phase
    log("going to kill %r" % (process_group_pid_set, ))
    killPreviousRun()

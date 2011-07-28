import socket
import sys

def check_promise(args):

  ip, port = args

  connection_okay = False

  try:
    s = socket.create_connection((ip, port), timeout=2)
    connection_okay = True
    s.close()
  except (socket.error, socket.timeout):
    connection_okay = False

  if not connection_okay:
    print >> sys.stderr, "The %(port)s on %(ip)s isn't listening" % {
      'port': port, 'ip': ip
    }
    sys.exit(127)

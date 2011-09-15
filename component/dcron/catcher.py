import os
import sys
import time
import shutil

if 'suffix' not in dir():
  suffix = '.log'

filename = os.path.join(directory,
                        time.strftime('%Y-%m-%d.%H:%M.%s') + suffix)
with open(filename, 'aw') as f:
  shutil.copyfileobj(sys.stdin, f)

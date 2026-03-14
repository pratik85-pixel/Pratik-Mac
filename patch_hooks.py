import os
import glob
import re

hooks_dir = '/Users/pratikbarman/Desktop/ZenFlowVerity/src/hooks'
files = glob.glob(os.path.join(hooks_dir, '*.ts'))

for file in files:
    with open(file, 'r') as f:
        content = f.read()

    # The goal is to replace fetch(url) / axios.get(url) with getClient() methods or just inject `DEFAULT_USER_ID`
    # Let's first just find them.
    print(file)

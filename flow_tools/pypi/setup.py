import io
from setuptools import setup

GITHUB_URL = 'https://github.com/cheshirekow/flow_tools'

with io.open('README.rst', encoding='utf8') as infile:
  long_description = infile.read()

VERSION = None
with io.open('flow_tools/__init__.py') as infile:
  for line in infile:
    if 'VERSION =' in line:
      VERSION = line.split('=', 1)[1].strip().strip('"')
      break

assert VERSION is not None

setup(
    name='flow_tools',
    packages=['flow_tools'],
    version=VERSION,
    description="Integrations and scripts for jira and gerrit",
    long_description=long_description,
    author='Josh Bialkowski',
    author_email='josh.bialkowski@gmail.com',
    url=GITHUB_URL,
    download_url='{}/archive/{}.tar.gz'.format(GITHUB_URL, VERSION),
    keywords=['jira', 'gerrit'],
    classifiers=[],
    entry_points={
        'console_scripts': ['flow-tools=flow_tools.__main__:main'],
    },
    install_requires=[
        'enum34',
        'gitpython',
        'jira',
        'pygerrit2',
        'requests',
        'sqlalchemy',
    ]

)
